#!/usr/bin/env python3
"""Mac HTTP API Daemon for SO-101 Leader Process Control.
Runs on Mac (192.168.0.2) on Port 8086.
Provides fast (<2ms) HTTP endpoints for status polling and process management.
"""

import http.server
import socketserver
import json
import urllib.parse
import subprocess
import sys
from pathlib import Path

PORT = 8086
SCRIPT_DIR = Path(__file__).parent.resolve()
LEADER_SCRIPT = str(SCRIPT_DIR / "so101_leader_client.py")
PYTHON_BIN = sys.executable if sys.executable else "python3"

def check_leader_running():
    try:
        res = subprocess.run(["pgrep", "-f", "so101_leader_client.py"], capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0 and res.stdout.strip():
            pid = res.stdout.strip().split()[0]
            return True, pid
        return False, ""
    except Exception:
        return False, ""

def kill_leader():
    try:
        subprocess.run(["pkill", "-9", "-f", "so101_leader_client.py"], check=False)
        res = subprocess.run(["lsof", "-t", "/dev/cu.usbmodem5B415318721"], capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0 and res.stdout.strip():
            for p in res.stdout.strip().split():
                subprocess.run(["kill", "-9", p], check=False)
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"Error in kill_leader: {e}", flush=True)
        return False

def start_leader():
    kill_leader()
    try:
        cmd = f"export PYTHONUNBUFFERED=1; nohup {PYTHON_BIN} {LEADER_SCRIPT} > /tmp/leader.log 2>&1 &"
        subprocess.Popen(["zsh", "-c", cmd])
        time.sleep(0.5)
        running, pid = check_leader_running()
        return running, pid
    except Exception as e:
        print(f"Error launching leader: {e}", flush=True)
        return False, ""

class MacDaemonHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy HTTP access logs
        pass

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            running, pid = check_leader_running()
            self._send_json({"running": running, "pid": pid, "host": "mac"})
        else:
            self._send_json({"status": "ok", "service": "mac_daemon_8086"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b'{}'
        try:
            body = json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
        except Exception:
            body = {}

        if parsed.path in ["/api/leader_toggle", "/api/start", "/api/stop"]:
            action = body.get("action", "toggle")
            if parsed.path == "/api/start":
                action = "start"
            elif parsed.path == "/api/stop":
                action = "stop"

            running, pid = check_leader_running()
            if action == "toggle":
                action = "stop" if running else "start"

            if action == "start":
                run_ok, new_pid = start_leader()
                self._send_json({"status": "ok", "action": "start", "running": run_ok, "pid": new_pid})
            elif action in ["stop", "kill"]:
                kill_leader()
                self._send_json({"status": "ok", "action": "stop", "running": False, "pid": ""})
            else:
                self._send_json({"error": f"Unknown action: {action}"}, 400)
        else:
            self._send_json({"error": "Endpoint not found"}, 404)

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

def main():
    print(f"Starting Mac HTTP API Daemon on port {PORT}...", flush=True)
    server = ThreadedHTTPServer(('0.0.0.0', PORT), MacDaemonHandler)
    server.serve_forever()

if __name__ == "__main__":
    main()
