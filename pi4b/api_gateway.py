#!/usr/bin/env python3
"""Single Responsibility ApiGatewayServer module for Pi 4B.
Standard library HTTP REST server and static UI host on port 8082.
Reverse-proxies motor control and mode toggle commands to Pi 500 (:8085) and Mac Mini (:8086),
dispatches audio requests (stored assets, raw binary/base64 streams) to AudioPlaybackService queue,
and exposes live telemetry cache.
"""

import base64
import json
import logging
import os
import socket
import socketserver
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional, Dict, Any

PI500_IP = "192.168.0.130"
MAC_HOST_API = "http://192.168.0.2:8086"
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server preventing slow clients from blocking API handling."""
    daemon_threads = True
    allow_reuse_address = True


class ApiGatewayHandler(SimpleHTTPRequestHandler):
    """HTTP Request Handler for Pi 4B Kiosk UI and API Gateway routing."""

    telemetry_service = None
    audio_service = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _send_json(self, data: Dict[str, Any], status_code: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ["/", "/index.html"]:
            static_file = os.path.join(DIRECTORY, "static", "gantry_ui.html")
            if not os.path.exists(static_file):
                static_file = os.path.join(DIRECTORY, "index.html")

            if os.path.exists(static_file):
                with open(static_file, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(content)
                return

        if path == "/api/status":
            if self.telemetry_service:
                resp = self.telemetry_service.get_status()
                if self.audio_service:
                    resp["audio_state"] = self.audio_service.get_state()
                self._send_json(resp)
            else:
                self._send_json({"error": "TelemetryPollerService unavailable"}, 503)
            return

        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        # 1. Raw Binary Audio Streaming (audio/wav, audio/mpeg, application/octet-stream)
        if content_type.startswith("audio/") or content_type.startswith("application/octet-stream"):
            raw_audio = self.rfile.read(content_length) if content_length > 0 else b""
            if self.audio_service and raw_audio:
                fmt = "mp3" if "mpeg" in content_type else "wav"
                self.audio_service.play_raw_audio(raw_audio, audio_format=fmt)
                self._send_json({"status": "ok", "mode": "raw_binary_stream", "bytes": len(raw_audio)})
            else:
                self._send_json({"error": "No binary audio data received or service uninitialized"}, 400)
            return

        # 2. Multipart Form Audio Upload
        if content_type.startswith("multipart/form-data"):
            raw_body = self.rfile.read(content_length) if content_length > 0 else b""
            if self.audio_service and raw_body:
                riff_idx = raw_body.find(b"RIFF")
                if riff_idx != -1:
                    audio_payload = raw_body[riff_idx:]
                    self.audio_service.play_raw_audio(audio_payload, audio_format="wav")
                    self._send_json({"status": "ok", "mode": "multipart_wav", "bytes": len(audio_payload)})
                    return

                id3_idx = raw_body.find(b"ID3")
                if id3_idx != -1:
                    audio_payload = raw_body[id3_idx:]
                    self.audio_service.play_raw_audio(audio_payload, audio_format="mp3")
                    self._send_json({"status": "ok", "mode": "multipart_mp3", "bytes": len(audio_payload)})
                    return

                self.audio_service.play_raw_audio(raw_body)
                self._send_json({"status": "ok", "mode": "multipart_raw", "bytes": len(raw_body)})
            else:
                self._send_json({"error": "Empty multipart payload or service uninitialized"}, 400)
            return

        # Read JSON / Text body
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        if body:
            try:
                req_data = json.loads(body)
            except Exception as e:
                self._send_json({"error": f"Invalid JSON payload: {e}"}, 400)
                return
        else:
            req_data = {}

        # 3. Sound Playback & Queue Control API (/api/play_sound, /api/play_audio)
        if path in ["/api/play_sound", "/api/play_audio"]:
            if not self.audio_service:
                self._send_json({"error": "AudioPlaybackService uninitialized"}, 503)
                return

            action = req_data.get("action")
            kind = req_data.get("kind", "connect")
            if action in ["stop", "clear"] or kind in ["stop", "stop_audio"]:
                self.audio_service.stop_all()
                self._send_json({"status": "ok", "action": "stopped_and_flushed"})
                return

            # Base64 encoded audio payload (strict canonical contract key: audio_b64)
            b64_data = req_data.get("audio_b64")
            if b64_data:
                try:
                    raw_bytes = base64.b64decode(b64_data)
                    fmt = req_data.get("format", "wav")
                    self.audio_service.play_raw_audio(raw_bytes, audio_format=fmt)
                    self._send_json({"status": "ok", "mode": "base64_audio", "bytes": len(raw_bytes)})
                except Exception as ex:
                    self._send_json({"error": f"Invalid base64 audio data: {ex}"}, 400)
                return

            # Asset sound lookup mode
            wav_path = req_data.get("wav_path")
            self.audio_service.play_sound(kind=kind, wav_path=wav_path)
            self._send_json({"status": "ok", "mode": "asset_sound", "sound": kind or wav_path})
            return

        # 4. Wake-on-LAN Magic Packet
        if path == "/api/pi500_poweron":
            try:
                mac_hex = "d83add8a4642"
                mac_bytes = bytes.fromhex(mac_hex)
                magic_payload = b"\xff" * 6 + mac_bytes * 16
                udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                udp_sock.sendto(magic_payload, ("255.255.255.255", 9))
                udp_sock.sendto(magic_payload, ("192.168.0.255", 9))
                udp_sock.close()
                subprocess.Popen(["wakeonlan", "-i", "eth0", "d8:3a:dd:8a:46:42"])
            except Exception as e:
                logging.error("WOL magic packet execution error: %s", e)
            self._send_json({"status": "ok", "message": "WOL magic packet sent"})
            return

        # 5. Master Daemon Restart Subprocess
        if path in ["/api/pi500_master_daemon_restart", "/api/pi500_daemon_restart"]:
            try:
                script_path = os.path.join(DIRECTORY, "restart_daemon.py")
                res = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=10)
                logging.info("[ApiGateway] Daemon restart stdout: '%s', stderr: '%s'", res.stdout.strip(), res.stderr.strip())
                self._send_json({"status": "ok", "message": "Pi 500 Master Daemon restart initiated", "stdout": res.stdout, "stderr": res.stderr})
            except Exception as e:
                logging.error("[ApiGateway] Daemon restart failed: %s", e)
                self._send_json({"error": str(e), "status": "failed"}, 500)
            return

        # 6. Mode Toggles & Teleop Controls (Forwarded to Pi 500 or Mac Mini)
        if path in ["/api/pi500_follower_toggle", "/api/mac_leader_toggle", "/api/servo_studio_toggle", "/api/pokeball_teleop_toggle", "/api/kill_all"]:
            action = req_data.get("action", "toggle")
            try:
                url = f"{MAC_HOST_API}/api/leader_toggle" if path == "/api/mac_leader_toggle" else f"http://{PI500_IP}:8085{path}"
                post_data = json.dumps({"action": action}).encode("utf-8")
                req = urllib.request.Request(url, data=post_data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    resp_body = resp.read()
                    try:
                        st_req = urllib.request.Request(f"http://{PI500_IP}:8085/api/status")
                        with urllib.request.urlopen(st_req, timeout=1.0) as st_resp:
                            if st_resp.status == 200 and self.telemetry_service:
                                self.telemetry_service.set_hardware_telemetry(json.loads(st_resp.read().decode()))
                    except Exception as ste:
                        logging.warning("Failed to refresh hardware telemetry post-toggle: %s", ste)
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
            except Exception as e:
                self._send_json({"error": f"HTTP endpoint error: {e}", "status": "failed"}, 500)
                return

        # 7. Direct Motor Commands & Position Sync Forwarding
        if path in ["/api/slider", "/api/nudge_physical", "/api/pedestal_step", "/api/pedestal", "/api/move", "/api/sync_position"]:
            try:
                target_url = f"http://{PI500_IP}:8085{path}"

                data_bytes = body.encode("utf-8")
                req = urllib.request.Request(target_url, data=data_bytes, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(e.read())
                return
            except Exception as e:
                logging.error("Error forwarding request to %s: %s", path, e)
                self._send_json({"error": f"Connection Error: {e}"}, 400)
                return

        self.send_response(404)
        self.end_headers()


def create_api_gateway_server(host: str, port: int, telemetry_service: Any, audio_service: Any) -> ThreadedHTTPServer:
    """Factory creating and configuring a ThreadedHTTPServer instance."""
    ApiGatewayHandler.telemetry_service = telemetry_service
    ApiGatewayHandler.audio_service = audio_service
    server = ThreadedHTTPServer((host, port), ApiGatewayHandler)
    return server
