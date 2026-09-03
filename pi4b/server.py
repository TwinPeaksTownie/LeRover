"""Pi 4B Touchscreen Kiosk UI & Router Server.
Target Deployment: /home/carson/touch_ui/server.py on Pi 4B (192.168.0.86)
Executed by: backend.service (Port 8082)
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

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if DIRECTORY not in sys.path:
    sys.path.insert(0, DIRECTORY)

try:
    import network_resolver
except ImportError:
    network_resolver = None

PORT = 8082


def get_current_pi500_ip(port=8085) -> str:
    if network_resolver:
        return network_resolver.get_pi500_ip(prefer_port=port)
    return "10.0.0.1"


def get_current_mac_ip(port=8086) -> str:
    if network_resolver:
        return network_resolver.get_mac_ip(prefer_port=port)
    return "192.168.0.149"

STATUS_CACHE = {
    "pokeball": {"running": False, "connected": False, "status": "DISCONNECTED", "pid": ""},
    "follower": {"running": False, "pid": ""},
    "leader": {"running": False, "pid": ""},
    "clack_pose": {"running": False},
    "pi500_online": False,
    "hardware_telemetry": None,
    "last_telemetry_time": 0,
    "connection_mode": {"mode": "OFFLINE_DIRECT_ETH", "is_offline": True, "is_cloud_enabled": False}
}

TAP_DETECTOR = None
TAP_DETECTOR_LOCK = threading.Lock()

ROBOT_MIC_PROC = None
ROBOT_MIC_LOCK = threading.Lock()

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

CONFIG_FILE = os.path.join(DIRECTORY, "ui_config.json")
DEFAULT_CONFIG = {
    "clack_threshold": 5200,
    "volume_pct": 100,
    "rover_max_speed_pct": 35,
    "arm_speed_sec": 1.0
}

def load_ui_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                res = dict(DEFAULT_CONFIG)
                res.update(cfg)
                return res
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_ui_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}", flush=True)

UI_CONFIG = load_ui_config()
STATUS_CACHE["config"] = UI_CONFIG

def set_system_volume(pct: int):
    try:
        val = max(0, min(150, int(pct)))
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{val}%"], env=PULSE_ENV, check=False)
        subprocess.run(["amixer", "set", "Master", f"{val}%"], env=PULSE_ENV, check=False)
        UI_CONFIG["volume_pct"] = val
        STATUS_CACHE["config"] = UI_CONFIG
        save_ui_config(UI_CONFIG)
    except Exception as e:
        print(f"Error setting volume: {e}", flush=True)

def sync_rover_speed_config(pct: int):
    val = max(10, min(100, int(pct)))
    max_offset = int(500 * (val / 100.0))
    UI_CONFIG["rover_max_speed_pct"] = val
    STATUS_CACHE["config"] = UI_CONFIG
    save_ui_config(UI_CONFIG)
    try:
        import base64
        cfg_dict = {"max_speed_pct": val, "max_pulse_offset": max_offset}
        cfg_data = json.dumps(cfg_dict)
        with open("/tmp/rover_config.json", "w") as f:
            f.write(cfg_data)
        b64 = base64.b64encode(cfg_data.encode('utf-8')).decode('ascii')
        p500_ip = get_current_pi500_ip(port=22)
        cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 user@{p500_ip} \"echo {b64} | base64 -d > /tmp/rover_config.json\""
        subprocess.Popen(cmd, shell=True)
    except Exception as e:
        print(f"Error syncing rover speed: {e}", flush=True)

def play_sound_helper(kind="incorrect", wav_path=None, stop_previous=False, delay_sec=0.0):
    def _work():
        try:
            if stop_previous or kind == "stop_audio" or kind in ("trex_roar", "trex_roar_isolated"):
                subprocess.run(["pkill", "-9", "mpg123"], check=False)
                subprocess.run(["pkill", "-9", "paplay"], check=False)
                subprocess.run(["pkill", "-9", "aplay"], check=False)
                if kind == "stop_audio":
                    return

            if delay_sec > 0:
                time.sleep(delay_sec)

            global TAP_DETECTOR
            if TAP_DETECTOR and hasattr(TAP_DETECTOR, "mute"):
                mute_dur = 5.0 if kind in ("trex_roar", "trex_roar_isolated", "mario_kart_start") else 2.0
                TAP_DETECTOR.mute(mute_dur)

            target_wav = wav_path
            if not target_wav or not os.path.exists(target_wav):
                if kind == "connect":
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, "smw_coin.wav")
                elif kind in ("incorrect", "error", "invalid", "fallback"):
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, "smw_incorrect.wav")
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
                elif kind in ("trex_roar", "trex_roar_isolated"):
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, "trex_roar_isolated.wav")
                    if not os.path.exists(target_wav):
                        target_wav = "/home/carson/trex_roar_isolated.wav"
                elif kind:
                    target_wav = os.path.join(MARIO_SOUNDS_DIR, f"{kind}.wav")
                    if not os.path.exists(target_wav):
                        target_wav = os.path.join(MARIO_SOUNDS_DIR, "smw_incorrect.wav")

            if target_wav and os.path.exists(target_wav):
                res = subprocess.run(["paplay", target_wav], env=PULSE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
                if res.returncode != 0:
                    err_txt = res.stderr.decode('utf-8', errors='ignore') if res.stderr else "Unknown error"
                    print(f"PulseAudio paplay failed for {target_wav} (code {res.returncode}): {err_txt}", flush=True)
        except Exception as e:
            print(f"Sound playback error: {e}", flush=True)
    threading.Thread(target=_work, daemon=True).start()

def poll_status_loop():
    while True:
        p500_ip = get_current_pi500_ip(port=8085)
        mac_ip = get_current_mac_ip(port=8086)
        conn_mode = network_resolver.get_active_connection_mode() if network_resolver else {"mode": "OFFLINE_DIRECT_ETH", "is_offline": True, "is_cloud_enabled": False}

        # 1. Check Pi 500 physical host network reachability
        pi500_host_online = False
        if network_resolver:
            pi500_host_online = network_resolver.is_host_pingable(p500_ip, timeout_sec=1)
        else:
            try:
                res = subprocess.run(["ping", "-c", "1", "-W", "1", p500_ip], capture_output=True)
                pi500_host_online = (res.returncode == 0)
            except Exception:
                pi500_host_online = False
        
        STATUS_CACHE["pi500_online"] = pi500_host_online
        STATUS_CACHE["connection_mode"] = conn_mode
        STATUS_CACHE["resolved_pi500_ip"] = p500_ip
        STATUS_CACHE["resolved_mac_ip"] = mac_ip

        # 2. Poll Pi 500 Master Daemon over HTTP 8085
        try:
            req = urllib.request.Request(f"http://{p500_ip}:8085/api/status", headers={'User-Agent': 'Pi4B-TouchUI'})
            with urllib.request.urlopen(req, timeout=0.35) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    STATUS_CACHE["hardware_telemetry"] = data
                    STATUS_CACHE["last_telemetry_time"] = time.time()
                    STATUS_CACHE["daemon_running"] = True
                    STATUS_CACHE["hardware_connected"] = bool(data.get("hardware_connected", False))
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
            STATUS_CACHE["daemon_running"] = False
            STATUS_CACHE["follower"] = {"running": False, "pid": ""}
            STATUS_CACHE["hardware_telemetry"] = None

        # 3. Poll Mac Leader directly over HTTP 8086
        try:
            req_mac = urllib.request.Request(f"http://{mac_ip}:8086/api/status", headers={'User-Agent': 'Pi4B-TouchUI'})
            with urllib.request.urlopen(req_mac, timeout=0.35) as response_mac:
                if response_mac.status == 200:
                    mac_data = json.loads(response_mac.read().decode())
                    leader_data = mac_data.get("leader", mac_data) if isinstance(mac_data.get("leader"), dict) else mac_data
                    STATUS_CACHE["leader"] = {"running": bool(leader_data.get("running", False)), "pid": str(leader_data.get("pid", ""))}
                else:
                    STATUS_CACHE["leader"] = {"running": False, "pid": ""}
        except Exception:
            STATUS_CACHE["leader"] = {"running": False, "pid": ""}

        # 4. Update Clack Pose telemetry
        global TAP_DETECTOR
        with TAP_DETECTOR_LOCK:
            if TAP_DETECTOR is not None:
                STATUS_CACHE["clack_pose"] = TAP_DETECTOR.get_state()
            else:
                STATUS_CACHE["clack_pose"] = {"running": False, "mode": "CALIBRATION_DETECTION_ONLY"}

        time.sleep(0.33)

threading.Thread(target=poll_status_loop, daemon=True).start()


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ["/", "/index.html", "/gantry_ui.html"]:
            static_file = os.path.join(DIRECTORY, "static", "index.html")
            if not os.path.exists(static_file):
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

        rel_path = parsed.path.lstrip("/")
        if rel_path and not rel_path.startswith("api/"):
            static_asset = os.path.join(DIRECTORY, "static", rel_path)
            if os.path.isfile(static_asset):
                mime_type = "application/octet-stream"
                if rel_path.endswith(".css"):
                    mime_type = "text/css"
                elif rel_path.endswith(".js"):
                    mime_type = "application/javascript"
                elif rel_path.endswith(".json"):
                    mime_type = "application/json"
                elif rel_path.endswith(".html"):
                    mime_type = "text/html"
                elif rel_path.endswith(".png"):
                    mime_type = "image/png"
                elif rel_path.endswith(".svg"):
                    mime_type = "image/svg+xml"
                with open(static_asset, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
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

        if parsed.path == "/api/get_config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "config": UI_CONFIG}).encode('utf-8'))
            return

        if parsed.path.startswith("/api/apps") or parsed.path in ["/api/arm/presets", "/api/arm/sequences", "/api/pokeball_reconnect"]:
            try:
                p500_ip = get_current_pi500_ip(port=8085)
                req = urllib.request.Request(f"http://{p500_ip}:8085{self.path}")
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Failed to proxy to Pi 500: {e}"}).encode('utf-8'))
                return

        return super().do_GET()

    def do_POST(self):
        global TAP_DETECTOR, ROBOT_MIC_PROC
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get('Content-Length', 0))

        if path == "/api/play_sound" and (content_type.startswith("audio/") or content_type.startswith("application/octet-stream")):
            raw_audio = self.rfile.read(content_length) if content_length > 0 else b""
            if raw_audio:
                tmp_path = "/tmp/incoming_stream.wav"
                with open(tmp_path, "wb") as f:
                    f.write(raw_audio)
                play_sound_helper(wav_path=tmp_path, stop_previous=True)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "mode": "stream_audio", "bytes": len(raw_audio)}).encode('utf-8'))
                return

        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        try:
            req_data = json.loads(body) if body else {}
        except Exception:
            req_data = {}

        if path == "/api/microphone/start":
            with ROBOT_MIC_LOCK:
                if ROBOT_MIC_PROC is not None:
                    try:
                        ROBOT_MIC_PROC.terminate()
                        ROBOT_MIC_PROC.wait(timeout=1.0)
                    except Exception:
                        pass
                if os.path.exists("/tmp/robot_recording.wav"):
                    try:
                        os.remove("/tmp/robot_recording.wav")
                    except Exception:
                        pass
                cmd = ["parecord", "--format=s16le", "--rate=16000", "--channels=1", "/tmp/robot_recording.wav"]
                ROBOT_MIC_PROC = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[ROBOT MIC] Started onboard microphone recording to /tmp/robot_recording.wav", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "recording_started"}).encode())
            return

        if path == "/api/microphone/stop":
            with ROBOT_MIC_LOCK:
                if ROBOT_MIC_PROC is not None:
                    try:
                        ROBOT_MIC_PROC.terminate()
                        ROBOT_MIC_PROC.wait(timeout=1.5)
                    except Exception:
                        try:
                            ROBOT_MIC_PROC.kill()
                        except Exception:
                            pass
                    ROBOT_MIC_PROC = None

            wav_data = b""
            if os.path.exists("/tmp/robot_recording.wav"):
                try:
                    with open("/tmp/robot_recording.wav", "rb") as f:
                        wav_data = f.read()
                except Exception as e:
                    print(f"[ROBOT MIC] Error reading /tmp/robot_recording.wav: {e}", flush=True)

            voice_bridge_url = req_data.get("voice_bridge_url", "http://192.168.0.194:8058/api/voice/process_audio")
            dispatched = False
            if wav_data and voice_bridge_url:
                def _post_audio():
                    try:
                        req = urllib.request.Request(
                            voice_bridge_url,
                            data=wav_data,
                            headers={"Content-Type": "audio/wav"}
                        )
                        with urllib.request.urlopen(req, timeout=45) as resp:
                            print(f"[ROBOT MIC] Dispatched {len(wav_data)} bytes to Voice Bridge: status {resp.status}", flush=True)
                    except Exception as err:
                        print(f"[ROBOT MIC] Failed to dispatch audio to Voice Bridge: {err}", flush=True)
                threading.Thread(target=_post_audio, daemon=True).start()
                dispatched = True

            print(f"[ROBOT MIC] Stopped onboard recording: {len(wav_data)} bytes, dispatched={dispatched}", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "recording_stopped",
                "bytes": len(wav_data),
                "dispatched": dispatched
            }).encode())
            return

        if path == "/api/set_volume":
            vol = req_data.get("volume", 100)
            set_system_volume(vol)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "volume_pct": UI_CONFIG["volume_pct"]}).encode('utf-8'))
            return

        if path == "/api/set_config":
            if "volume_pct" in req_data:
                set_system_volume(req_data["volume_pct"])
            if "clack_threshold" in req_data:
                thresh = int(req_data["clack_threshold"])
                UI_CONFIG["clack_threshold"] = thresh
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)
                with TAP_DETECTOR_LOCK:
                    if TAP_DETECTOR is not None:
                        TAP_DETECTOR.set_threshold(thresh)
            if "rover_max_speed_pct" in req_data:
                sync_rover_speed_config(req_data["rover_max_speed_pct"])
            if "arm_speed_sec" in req_data:
                UI_CONFIG["arm_speed_sec"] = float(req_data["arm_speed_sec"])
                STATUS_CACHE["config"] = UI_CONFIG
                save_ui_config(UI_CONFIG)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "config": UI_CONFIG}).encode('utf-8'))
            return

        if path in ["/api/wifi_disable", "/api/wifi_restore"]:
            action = "enable" if path == "/api/wifi_restore" else "disable"
            try:
                script_path = "/home/carson/touch_ui/scripts/toggle_wifi_blacklist.py"
                if not os.path.exists(script_path):
                    script_path = os.path.join(DIRECTORY, "scripts", "toggle_wifi_blacklist.py")
                if not os.path.exists(script_path):
                    script_path = os.path.join(os.path.dirname(DIRECTORY), "scripts", "toggle_wifi_blacklist.py")
                
                subprocess.Popen([sys.executable, script_path, action])
                if action == "enable":
                    play_sound_helper(kind="connect")
                else:
                    play_sound_helper(kind="disconnect")
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "action": action, "message": f"Wi-Fi {action} command initiated"}).encode())
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

        if path == "/api/play_sound":
            action = req_data.get("action")
            kind = req_data.get("kind", "incorrect")
            if action in ["stop", "clear"] or kind in ["stop", "stop_audio"]:
                play_sound_helper(kind="stop_audio", stop_previous=True)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "action": "stopped"}).encode('utf-8'))
                return

            wav_path = req_data.get("wav_path")
            stop_prev = bool(req_data.get("stop_previous", False))
            delay_s = float(req_data.get("delay_sec", 0.0))
            play_sound_helper(kind=kind, wav_path=wav_path, stop_previous=stop_prev, delay_sec=delay_s)
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
                udp_sock.sendto(magic_payload, ('10.0.0.255', 9))
                udp_sock.close()
                subprocess.Popen(["wakeonlan", "-i", "eth0", "d8:3a:dd:8a:46:42"])
            except Exception as e:
                print(f"WOL error: {e}", flush=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "WOL magic packet sent"}).encode())
            return

        if path in ["/api/pi500_master_daemon_restart", "/api/pi500_daemon_restart", "/api/pi500_daemon_toggle"]:
            action = req_data.get("action", "restart")
            if action == "toggle":
                is_running = STATUS_CACHE.get("daemon_running", False)
                action = "stop" if is_running else "start"

            try:
                script_path = os.path.join(DIRECTORY, "restart_daemon.py")
                res = subprocess.run([sys.executable, script_path, action], capture_output=True, text=True, timeout=10)
                print(f"[TouchUI] Daemon {action} executed: out='{res.stdout.strip()}', err='{res.stderr.strip()}'", flush=True)
                if action == "stop":
                    STATUS_CACHE["daemon_running"] = False
                elif action in ["start", "restart"]:
                    STATUS_CACHE["daemon_running"] = (res.returncode == 0)

                self.send_response(200 if res.returncode == 0 else 500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok" if res.returncode == 0 else "error", "action": action, "message": f"Pi 500 sewer-daemon.service {action} executed", "stdout": res.stdout, "stderr": res.stderr}).encode())
                return
            except Exception as e:
                print(f"[TouchUI] Daemon {action} failed: {e}", flush=True)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e), "status": "failed"}).encode())
                return

        if path == "/api/clack_pose_toggle":
            action = req_data.get("action", "toggle")
            with TAP_DETECTOR_LOCK:
                is_running = bool(TAP_DETECTOR is not None and TAP_DETECTOR.is_alive())
                if action == "toggle":
                    action = "stop" if is_running else "start"

                if action == "start":
                    if TAP_DETECTOR is None or not TAP_DETECTOR.is_alive():
                        try:
                            from audio_tap_detector import AudioTapDetector
                            TAP_DETECTOR = AudioTapDetector(play_sound_cb=play_sound_helper)
                            TAP_DETECTOR.start()
                            STATUS_CACHE["clack_pose"] = {"running": True}
                            play_sound_helper(kind="connect")
                        except Exception as e:
                            print(f"[ClackPose] Startup error: {e}", flush=True)
                            self.send_response(500)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"error": str(e), "status": "failed"}).encode())
                            return
                    try:
                        p500_ip = get_current_pi500_ip(port=8085)
                        req_p500 = urllib.request.Request(
                            f"http://{p500_ip}:8085/api/clack_pose_toggle",
                            data=json.dumps({"action": "start"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"}
                        )
                        urllib.request.urlopen(req_p500, timeout=1.5)
                    except Exception as p500_err:
                        print(f"[ClackPose] Pi 500 start notify warning: {p500_err}", flush=True)

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "action": "started", "running": True}).encode())
                    return
                else:
                    if TAP_DETECTOR is not None:
                        try:
                            TAP_DETECTOR.stop()
                        except Exception as st_err:
                            print(f"[ClackPose] TAP_DETECTOR stop warning: {st_err}", flush=True)
                        TAP_DETECTOR = None
                    STATUS_CACHE["clack_pose"] = {"running": False}
                    play_sound_helper(kind="disconnect")

                    try:
                        p500_ip = get_current_pi500_ip(port=8085)
                        req_p500 = urllib.request.Request(
                            f"http://{p500_ip}:8085/api/clack_pose_toggle",
                            data=json.dumps({"action": "stop"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"}
                        )
                        urllib.request.urlopen(req_p500, timeout=1.5)
                    except Exception as p500_err:
                        print(f"[ClackPose] Pi 500 stop notify warning: {p500_err}", flush=True)

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "action": "stopped", "running": False}).encode())
                    return

        if path == "/api/clack_pose_threshold":
            thresh = req_data.get("threshold")
            refractory = req_data.get("refractory_ms")
            with TAP_DETECTOR_LOCK:
                if TAP_DETECTOR is not None:
                    if thresh is not None:
                        TAP_DETECTOR.set_threshold(int(thresh))
                    if refractory is not None:
                        TAP_DETECTOR.set_refractory(int(refractory))
                    st = TAP_DETECTOR.get_state()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "state": st}).encode())
                    return
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "message": "Detector not active"}).encode())
                    return

        if path in ["/api/pi500_follower_toggle", "/api/mac_leader_toggle", "/api/servo_studio_toggle", "/api/pokeball_teleop_toggle", "/api/beat_bandit_toggle", "/api/kill_all"]:
            action = req_data.get("action", "toggle")
            if path == "/api/kill_all":
                play_sound_helper(kind="stop_audio", stop_previous=True)
                with TAP_DETECTOR_LOCK:
                    if TAP_DETECTOR is not None:
                        try:
                            TAP_DETECTOR.stop()
                        except Exception as k_err:
                            print(f"[KillAll] Tap detector stop warning: {k_err}", flush=True)
                        TAP_DETECTOR = None
                STATUS_CACHE["clack_pose"] = {"running": False}

            if path in ["/api/pi500_follower_toggle", "/api/pokeball_teleop_toggle", "/api/servo_studio_toggle", "/api/beat_bandit_toggle"] and action != "stop":
                with TAP_DETECTOR_LOCK:
                    if TAP_DETECTOR is not None:
                        try:
                            TAP_DETECTOR.stop()
                        except Exception as t_err:
                            print(f"[Toggle] Tap detector stop warning: {t_err}", flush=True)
                        TAP_DETECTOR = None
                STATUS_CACHE["clack_pose"] = {"running": False}

            if path == "/api/beat_bandit_toggle" and action in ["stop", "kill"]:
                play_sound_helper(kind="stop_audio", stop_previous=True)

            try:
                p500_ip = get_current_pi500_ip(port=8085)
                mac_ip = get_current_mac_ip(port=8086)
                if path == "/api/mac_leader_toggle":
                    url = f"http://{mac_ip}:8086/api/leader_toggle"
                else:
                    url = f"http://{p500_ip}:8085{path}"
                
                post_data = json.dumps({"action": action}).encode('utf-8')
                req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    resp_body = resp.read()
                    if path == "/api/kill_all":
                        try:
                            script_path = os.path.join(DIRECTORY, "restart_daemon.py")
                            subprocess.run([sys.executable, script_path, "stop"], capture_output=True, timeout=6)
                            STATUS_CACHE["daemon_running"] = False
                            STATUS_CACHE["hardware_telemetry"] = None
                        except Exception as stop_err:
                            print(f"[KillAll] Service stop warning: {stop_err}", flush=True)
                    else:
                        try:
                            st_req = urllib.request.Request(f"http://{p500_ip}:8085/api/status")
                            with urllib.request.urlopen(st_req, timeout=1.0) as st_resp:
                                if st_resp.status == 200:
                                    STATUS_CACHE["hardware_telemetry"] = json.loads(st_resp.read().decode())
                        except Exception as st_err:
                            print(f"[Telemetry] Status refresh warning: {st_err}", flush=True)
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
            except Exception as e:
                if path == "/api/kill_all":
                    try:
                        script_path = os.path.join(DIRECTORY, "restart_daemon.py")
                        subprocess.run([sys.executable, script_path, "stop"], capture_output=True, timeout=6)
                        STATUS_CACHE["daemon_running"] = False
                        STATUS_CACHE["hardware_telemetry"] = None
                    except Exception:
                        pass
                play_sound_helper(kind="incorrect")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"HTTP endpoint error: {e}", "status": "failed"}).encode())
                return

        if path.startswith("/api/apps/"):
            if path in ["/api/apps/beat_bandit/stop", "/api/apps/stop"]:
                play_sound_helper(kind="stop_audio", stop_previous=True)
                with TAP_DETECTOR_LOCK:
                    if TAP_DETECTOR is not None:
                        try:
                            TAP_DETECTOR.stop()
                        except Exception as b_err:
                            print(f"[AppStop] Tap detector stop warning: {b_err}", flush=True)
                        TAP_DETECTOR = None
                STATUS_CACHE["clack_pose"] = {"running": False}

            app_req_name = req_data.get("name", "") if isinstance(req_data, dict) else ""
            if path == "/api/apps/start":
                if app_req_name in ["clack_pose_app", "piranha_pose_app"]:
                    with TAP_DETECTOR_LOCK:
                        if TAP_DETECTOR is None or not TAP_DETECTOR.is_alive():
                            try:
                                from audio_tap_detector import AudioTapDetector
                                TAP_DETECTOR = AudioTapDetector(play_sound_cb=play_sound_helper)
                                TAP_DETECTOR.start()
                                STATUS_CACHE["clack_pose"] = {"running": True}
                                play_sound_helper(kind="connect")
                            except Exception as te:
                                print(f"[ClackPose] AudioTapDetector start error: {te}", flush=True)
                else:
                    with TAP_DETECTOR_LOCK:
                        if TAP_DETECTOR is not None:
                            try:
                                TAP_DETECTOR.stop()
                            except Exception as t_err:
                                print(f"[AppStart] Tap detector stop warning: {t_err}", flush=True)
                            TAP_DETECTOR = None
                    STATUS_CACHE["clack_pose"] = {"running": False}

            try:
                p500_ip = get_current_pi500_ip(port=8085)
                url = f"http://{p500_ip}:8085{path}"
                post_data = body.encode('utf-8')
                req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Error proxying to Pi 500: {e}"}).encode('utf-8'))
                return

        if path in [
            "/api/slider",
            "/api/nudge_physical",
            "/api/pedestal_step",
            "/api/pedestal",
            "/api/move",
            "/api/sync_position",
            "/api/calibration",
            "/api/torque",
            "/api/arm/torque",
            "/api/arm/capture_pose",
            "/api/arm/commit_preset",
            "/api/arm/overwrite_preset",
            "/api/arm/delete_preset",
            "/api/arm/resume_last_pose",
            "/api/arm/move_to_preset",
            "/api/arm/move_norm",
            "/api/arm/execute_sequence",
            "/api/arm/sequence",
            "/api/arm/attack_sequence",
            "/api/arm/attack",
            "/api/arm/stop_sequence",
        ]:
            try:
                if TAP_DETECTOR and hasattr(TAP_DETECTOR, "mute"):
                    if path in ["/api/arm/attack_sequence", "/api/arm/attack", "/api/arm/execute_sequence"]:
                        TAP_DETECTOR.mute(12.0)
                    elif path in ["/api/arm/resume_last_pose", "/api/arm/move_to_preset", "/api/arm/move_norm"]:
                        TAP_DETECTOR.mute(2.5)
                    else:
                        TAP_DETECTOR.mute(1.5)
                p500_ip = get_current_pi500_ip(port=8085)
                url = f"http://{p500_ip}:8085{path}"
                post_data = body.encode('utf-8')
                req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
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
                print(f"Error forwarding request {path}: {e}", flush=True)
                play_sound_helper(kind="incorrect")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Connection Error: {e}"}).encode())
                return

        self.send_response(404)
        self.end_headers()

class ReuseTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

if __name__ == "__main__":
    with ReuseTCPServer(("", PORT), CustomHandler) as httpd:
        print(f"Touch UI Server active on port {PORT}", flush=True)
        httpd.serve_forever()
