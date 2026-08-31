"""
win32_host_bridge.py - Lightweight Windows Host Webhook for Docker Container
Listens on port 8059 on the Windows host.
When the Ornith Docker container rejects a task, it sends HTTP POST /inject.
This host bridge executes the Win32 relative-coordinate click and paste into Antigravity.
"""

import http.server
import json
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import tools_computer_use

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [HOST_BRIDGE] %(message)s"
)
logger = logging.getLogger("win32_host_bridge")

class BridgeHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/inject":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len)
            try:
                data = json.loads(post_body.decode("utf-8"))
                text = data.get("feedback_text", "")
                click_send = data.get("click_send", True)
                
                logger.info(f"Received feedback injection request ({len(text)} chars)")
                res = tools_computer_use.send_feedback_to_antigravity(text, click_send=click_send)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                logger.error(f"Error handling injection: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "healthy", "service": "win32_host_bridge"}')
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port=8059):
    server = http.server.HTTPServer(("0.0.0.0", port), BridgeHandler)
    logger.info(f"Win32 Host Bridge listening on http://0.0.0.0:{port}...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Host bridge stopped.")

if __name__ == "__main__":
    run_server()
