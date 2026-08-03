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

PORT = 8082
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PI500_IP = "192.168.0.130"
PI500_HOST = "user@192.168.0.130"
MAC_HOST = "twinpeakstownie@192.168.0.243"

STATUS_CACHE = {
    "pokeball": {"running": False, "connected": False, "status": "DISCONNECTED", "pid": ""},
    "follower": {"running": False, "pid": ""},
    "leader": {"running": False, "pid": ""},
    "pi500_online": False,
    "hardware_telemetry": None,
    "last_telemetry_time": 0
}

def poll_status_loop():
    while True:
        # 1. Check Pi 500 online & fetch closed-loop hardware telemetry from aux_daemon (port 8085)
        try:
            req = urllib.request.Request("http://192.168.0.130:8085/api/status", headers={'User-Agent': 'Pi4B-TouchUI'})
            with urllib.request.urlopen(req, timeout=1.2) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    STATUS_CACHE["hardware_telemetry"] = data
                    STATUS_CACHE["last_telemetry_time"] = time.time()
                    STATUS_CACHE["pi500_online"] = True
                else:
                    STATUS_CACHE["hardware_telemetry"] = None
                    STATUS_CACHE["pi500_online"] = False
        except Exception:
            STATUS_CACHE["hardware_telemetry"] = None
            try:
                res = subprocess.run(["ping", "-c", "1", "-W", "1", PI500_IP], capture_output=True)
                STATUS_CACHE["pi500_online"] = (res.returncode == 0)
            except Exception:
                STATUS_CACHE["pi500_online"] = False

        # 2. Check Pokeball status & BLE telemetry on Pi 500
        try:
            res = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=2", PI500_HOST, "cat /tmp/pokeball_telemetry.json 2>/dev/null; echo '---'; pgrep -f pokeball_teleop_driver.py"],
                capture_output=True, text=True, timeout=3.0
            )
            out = res.stdout.strip()
            parts = out.split('---')
            telemetry_str = parts[0].strip() if len(parts) > 0 else ""
            proc_out = parts[1].strip() if len(parts) > 1 else ""

            pids = proc_out.split()
            is_running = len(pids) > 0 and pids[0].isdigit()

            pokeball_data = {"running": is_running, "pid": pids[0] if is_running else ""}

            if is_running and telemetry_str:
                try:
                    telem_obj = json.loads(telemetry_str)
                    pokeball_data["telemetry"] = telem_obj
                    pokeball_data["connected"] = telem_obj.get("connected", False)
                    pokeball_data["status"] = telem_obj.get("status", "SEARCHING")
                except Exception:
                    pokeball_data["connected"] = False
                    pokeball_data["status"] = "SEARCHING"
            else:
                pokeball_data["connected"] = False
                pokeball_data["status"] = "DISCONNECTED"

            STATUS_CACHE["pokeball"] = pokeball_data
        except Exception as e:
            STATUS_CACHE["pokeball"] = {"running": False, "connected": False, "status": "DISCONNECTED", "pid": ""}

        # 3. Check Pi500 Follower status on Pi 500 via pgrep
        try:
            res = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=2", PI500_HOST, "pgrep -f sewer_daemon.py"],
                capture_output=True, text=True, timeout=3.0
            )
            out = res.stdout.strip()
            if res.returncode == 0 and out:
                pids = out.split()
                STATUS_CACHE["follower"] = {"running": True, "pid": pids[0]}
            else:
                STATUS_CACHE["follower"] = {"running": False, "pid": ""}
        except Exception:
            STATUS_CACHE["follower"] = {"running": False, "pid": ""}

        # 4. Check Mac Leader status via pgrep
        try:
            res = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=2", MAC_HOST, "pgrep -f so101_leader_client.py"],
                capture_output=True, text=True, timeout=3.0
            )
            if res.returncode == 0 and res.stdout.strip():
                STATUS_CACHE["leader"] = {"running": True, "pid": res.stdout.strip().split()[0]}
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
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
                return
            elif os.path.exists(os.path.join(DIRECTORY, "index.html")):
                with open(os.path.join(DIRECTORY, "index.html"), "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
                return

        if parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            
            resp = dict(STATUS_CACHE)
            if STATUS_CACHE["hardware_telemetry"]:
                resp["closed_loop_verified"] = True
            else:
                resp["closed_loop_verified"] = False
                
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        req_data = json.loads(body) if body else {}

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

        if path in ["/api/toggle", "/api/pokeball_teleop_toggle"]:
            action = req_data.get("action", "toggle")
            if action == "start":
                subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", PI500_HOST, "pkill -f pokeball_teleop_driver.py || true"])
                time.sleep(0.3)
                subprocess.Popen(["ssh", "-o", "StrictHostKeyChecking=no", PI500_HOST, "nohup python3 /home/user/pokeball_teleop_driver.py > /tmp/pokeball.log 2>&1 &"])
            elif action == "stop":
                subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", PI500_HOST, "pkill -f pokeball_teleop_driver.py"])

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "action": action}).encode())
            return

        if path == "/api/pi500_follower_toggle":
            action = req_data.get("action", "toggle")
            if action == "start":
                subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", PI500_HOST, "pkill -f sewer_daemon.py || true"])
                time.sleep(0.3)
                subprocess.Popen(["ssh", "-o", "StrictHostKeyChecking=no", PI500_HOST, "nohup /home/user/so101/.venv/bin/python /home/user/sewer_daemon.py > /tmp/follower.log 2>&1 &"])
            elif action == "stop":
                subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", PI500_HOST, "pkill -f sewer_daemon.py"])

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "action": action}).encode())
            return

        if path == "/api/mac_leader_toggle":
            action = req_data.get("action", "toggle")
            if action == "start":
                subprocess.Popen(["ssh", "-o", "StrictHostKeyChecking=no", MAC_HOST, "nohup /Users/twinpeakstownie/lerobot/.venv/bin/python /Users/twinpeakstownie/lerobot/so101_leader_client.py > /tmp/leader.log 2>&1 &"])
            elif action == "stop":
                subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", MAC_HOST, "pkill -f so101_leader_client.py"])

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "action": action}).encode())
            return

        if path in ["/api/slider", "/api/nudge_physical"]:
            try:
                url = "http://192.168.0.130:8085/api/nudge_physical" if "nudge" in path else "http://192.168.0.130:8085/api/move"
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
                print(f"Error forwarding slider request to aux_daemon: {e}", flush=True)
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "12V Power Off"}).encode())
                return

        if path == "/api/sync_position":
            try:
                url = "http://192.168.0.130:8085/api/sync_position"
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
                print(f"Error forwarding sync request to aux_daemon: {e}", flush=True)
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "12V Power Off"}).encode())
                return

        self.send_response(404)
        self.end_headers()

class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    with ReuseTCPServer(("", PORT), CustomHandler) as httpd:
        print(f"Touch UI Server active on port {PORT}", flush=True)
        httpd.serve_forever()
