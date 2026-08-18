"""Pi 4B Touchscreen Kiosk UI & Router Server.
Target Deployment: /home/carson/touch_ui/server.py on Pi 4B (192.168.0.86)
Executed by: touch-ui.service (Port 8082)
"""

import http.server
import socketserver
import urllib.parse
import json
import subprocess
import os
import time
import threading
import socket
import urllib.request
import random
import sys

PORT = 8082
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PI500_IP = "192.168.0.130"
PI500_HOST = "user@192.168.0.130"
MAC_HOST = "twinpeakstownie@192.168.0.2"

STATUS_CACHE = {
    "pokeball": {"running": False, "connected": False, "status": "DISCONNECTED", "pid": ""},
    "pokeball_rover": {"running": False, "pid": ""},
    "follower": {"running": False, "pid": ""},
    "leader": {"running": False, "pid": ""},
    "pi500_online": False,
    "hardware_telemetry": None,
    "last_telemetry_time": 0
}

MARIO_SOUNDS_DIR = "/home/carson/mario_sounds"
PLANT_VINE_SOUNDS = [
    "nsmbwiiGiantPiranhaPlant.wav",
    "nsmbwiiPiranhaPlant1.wav",
    "nsmbwiiPiranhaPlant2.wav",
    "piranhaPlant.wav",
    "smw_vine.wav"
]

PULSE_ENV = dict(os.environ)
PULSE_ENV["XDG_RUNTIME_DIR"] = "/run/user/1000"
PULSE_ENV["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"

def play_sound_helper(kind="connect", wav_path=None):
    def _work():
        try:
            if kind == "stop_audio":
                subprocess.run(["pkill", "-9", "mpg123"], check=False)
                subprocess.run(["pkill", "-9", "paplay"], check=False)
                subprocess.run(["pkill", "-9", "aplay"], check=False)
                return

            target_wav = wav_path
            if not target_wav or not os.path.exists(target_wav):
                if kind == "connect":
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, "smw_coin.wav")
                elif kind == "mario_kart_start":
                    target_mp3 = "/home/carson/mario_kart_start.mp3"
                    if os.path.exists(target_mp3):
                        subprocess.run(["mpg123", "-q", target_mp3], env=PULSE_ENV, check=False)
                        return
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, "mario_kart_start.wav")
                elif kind in ("red_button", "random_plant_vine", "plant_vine"):
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, random.choice(PLANT_VINE_SOUNDS))
                elif kind == "disconnect":
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, "smw_pause.wav")
                elif kind in ("smw_shell_ricochet", "smw_shell_richochet", "shell_ricochet"):
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, "smw_shell_ricochet.wav")
                elif kind:
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, f"{kind}.wav")

            if target_wav and os.path.exists(target_wav):
                res = subprocess.run(["paplay", target_wav], env=PULSE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if res.returncode != 0:
                    subprocess.run(["aplay", "-D", "sysdefault", "-q", target_wav], env=PULSE_ENV, check=False)
        except Exception as e:
            print(f"Sound playback error: {e}", flush=True)
    threading.Thread(target=_work, daemon=True).start()

def poll_status_loop():
    while True:
        # 1. Check Pi 500 physical host network reachability via ICMP ping
        pi500_host_online = False
        try:
            res = subprocess.run(["ping", "-c", "1", "-W", "1", PI500_IP], capture_output=True)
            pi500_host_online = (res.returncode == 0)
        except Exception:
            pi500_host_online = False
        
        STATUS_CACHE["pi500_online"] = pi500_host_online

        # 2. Poll Pi 500 Master Daemon over HTTP 8085 (500ms loop, zero stale telemetry retention)
        try:
            req = urllib.request.Request(f"http://{PI500_IP}:8085/api/status", headers={'User-Agent': 'Pi4B-TouchUI'})
            with urllib.request.urlopen(req, timeout=1.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    STATUS_CACHE["hardware_telemetry"] = data
                    STATUS_CACHE["last_telemetry_time"] = time.time()
                    STATUS_CACHE["daemon_running"] = bool(data.get("hardware_connected", True))
                    if isinstance(data, dict):
                        if "follower" in data and isinstance(data["follower"], dict):
                            STATUS_CACHE["follower"] = data["follower"]
                        else:
                            STATUS_CACHE["follower"] = {"running": False, "pid": ""}
                        if "pokeball" in data and isinstance(data["pokeball"], dict):
                            STATUS_CACHE["pokeball"] = data["pokeball"]
                        else:
                            STATUS_CACHE["pokeball"] = {"running": False, "connected": False, "status": "DISCONNECTED", "pid": ""}
                else:
                    STATUS_CACHE["daemon_running"] = False
                    STATUS_CACHE["follower"] = {"running": False, "pid": ""}
                    STATUS_CACHE["hardware_telemetry"] = None
        except Exception:
            # Immediately clear telemetry cache on failure - never serve stale data
            STATUS_CACHE["daemon_running"] = False
            STATUS_CACHE["follower"] = {"running": False, "pid": ""}
            STATUS_CACHE["hardware_telemetry"] = None

        # 3. Poll Mac Leader directly over HTTP 8086
        try:
            req_mac = urllib.request.Request("http://192.168.0.2:8086/api/status", headers={'User-Agent': 'Pi4B-TouchUI'})
            with urllib.request.urlopen(req_mac, timeout=1.0) as response_mac:
                if response_mac.status == 200:
                    mac_data = json.loads(response_mac.read().decode())
                    leader_data = mac_data.get("leader", mac_data) if isinstance(mac_data.get("leader"), dict) else mac_data
                    STATUS_CACHE["leader"] = {"running": bool(leader_data.get("running", False)), "pid": str(leader_data.get("pid", ""))}
                else:
                    STATUS_CACHE["leader"] = {"running": False, "pid": ""}
        except Exception:
            STATUS_CACHE["leader"] = {"running": False, "pid": ""}

        time.sleep(0.5)

threading.Thread(target=poll_status_loop, daemon=True).start()


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ["/", "/index.html"]:
            static_file = os.path.join(DIRECTORY, "static", "gantry_ui.html")
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
            elif os.path.exists(os.path.join(DIRECTORY, "index.html")):
                with open(os.path.join(DIRECTORY, "index.html"), "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(content)
                return

        if parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            
            resp = dict(STATUS_CACHE)
            time_since_telem = time.time() - STATUS_CACHE.get("last_telemetry_time", 0)
            resp["closed_loop_verified"] = bool(STATUS_CACHE.get("hardware_telemetry")) and (time_since_telem < 2.0)
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        try:
            req_data = json.loads(body) if body else {}
        except Exception:
            req_data = {}

        if path == "/api/play_sound":
            kind = req_data.get("kind", "connect")
            wav_path = req_data.get("wav_path")
            play_sound_helper(kind=kind, wav_path=wav_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "sound": kind or wav_path}).encode('utf-8'))
            return

        if path == "/api/pi500_poweron":
            try:
                mac_hex = "d83add8a4642"
                mac_bytes = bytes.fromhex(mac_hex)
                magic_payload = b'\xff' * 6 + mac_bytes * 16
                udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                udp_sock.sendto(magic_payload, ('255.255.255.255', 9))
                udp_sock.sendto(magic_payload, ('192.168.0.255', 9))
                udp_sock.close()
                subprocess.Popen(["wakeonlan", "-i", "eth0", "d8:3a:dd:8a:46:42"])
            except Exception as e:
                print(f"WOL error: {e}", flush=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "WOL magic packet sent"}).encode())
            return

        if path in ["/api/pi500_master_daemon_restart", "/api/pi500_daemon_restart"]:
            try:
                script_path = os.path.join(DIRECTORY, "restart_daemon.py")
                res = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=10)
                print(f"[TouchUI] Daemon restart executed: out='{res.stdout.strip()}', err='{res.stderr.strip()}'", flush=True)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "message": "Pi 500 Master Daemon restart initiated", "stdout": res.stdout, "stderr": res.stderr}).encode())
                return
            except Exception as e:
                print(f"[TouchUI] Daemon restart failed: {e}", flush=True)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e), "status": "failed"}).encode())
                return

        if path == "/api/pokeball_rover_toggle":
            action = req_data.get("action", "toggle")
            try:
                try:
                    import rover_launcher
                except ImportError:
                    sys.path.insert(0, DIRECTORY)
                    import rover_launcher

                running = rover_launcher.is_running()
                if action == "toggle":
                    action = "stop" if running else "start"

                if action == "start":
                    rover_launcher.start_rover()
                    time.sleep(0.6)
                    running = rover_launcher.is_running()
                    STATUS_CACHE["pokeball_rover"] = {"running": running}
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "action": "started", "running": running}).encode())
                    return
                else:
                    rover_launcher.stop_rover()
                    time.sleep(0.3)
                    running = rover_launcher.is_running()
                    STATUS_CACHE["pokeball_rover"] = {"running": running}
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "action": "stopped", "running": running}).encode())
                    return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e), "status": "failed"}).encode())
                return

        if path in ["/api/pi500_follower_toggle", "/api/mac_leader_toggle", "/api/servo_studio_toggle", "/api/pokeball_teleop_toggle", "/api/kill_all"]:
            action = req_data.get("action", "toggle")
            try:
                if path == "/api/mac_leader_toggle":
                    url = "http://192.168.0.2:8086/api/leader_toggle"
                else:
                    url = f"http://{PI500_IP}:8085{path}"
                
                post_data = json.dumps({"action": action}).encode('utf-8')
                req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    resp_body = resp.read()
                    try:
                        st_req = urllib.request.Request(f"http://{PI500_IP}:8085/api/status")
                        with urllib.request.urlopen(st_req, timeout=1.0) as st_resp:
                            if st_resp.status == 200:
                                STATUS_CACHE["hardware_telemetry"] = json.loads(st_resp.read().decode())
                    except Exception:
                        pass
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"HTTP endpoint error: {e}", "status": "failed"}).encode())
                return

        if path in ["/api/slider", "/api/nudge_physical", "/api/pedestal_step", "/api/pedestal", "/api/move", "/api/sync_position"]:
            try:
                url = f"http://{PI500_IP}:8085{path}"
                data_bytes = body.encode('utf-8')
                req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
            except urllib.error.HTTPError as e:
                err_body = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err_body)
                return
            except Exception as e:
                print(f"Error forwarding slider request: {e}", flush=True)
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Connection Error: {e}"}).encode())
                return

        if path == "/api/sync_position":
            try:
                url = f"http://{PI500_IP}:8085/api/sync_position"
                data_bytes = body.encode('utf-8')
                req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
            except urllib.error.HTTPError as e:
                err_body = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err_body)
                return
            except Exception as e:
                print(f"Error forwarding sync request: {e}", flush=True)
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Connection Error: {e}"}).encode())
                return

        self.send_response(404)
        self.end_headers()

class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    with ReuseTCPServer(("", PORT), CustomHandler) as httpd:
        print(f"Touch UI Server active on port {PORT}", flush=True)
        httpd.serve_forever()
