import paramiko
import sys
import time
import urllib.request
import json

sys.stdout.reconfigure(encoding='utf-8')

print("--- 1. Connecting to Pi 4B (192.168.0.86) ---")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

# Deploy code files
sftp = client.open_sftp()
for f in ["server.py", "audio_service.py", "api_gateway.py"]:
    sftp.put(f"i:/aux_servo_interface/pi4b/{f}", f"/home/carson/touch_ui/{f}")
    print(f"Uploaded {f} -> /home/carson/touch_ui/{f}")
sftp.close()

# Update systemd service environment
service_content = """[Unit]
Description=Touch UI HTTP Server
After=network.target sound.target

[Service]
Type=simple
User=carson
WorkingDirectory=/home/carson/touch_ui
Environment="XDG_RUNTIME_DIR=/run/user/1000"
Environment="PULSE_SERVER=unix:/run/user/1000/pulse/native"
ExecStart=/usr/bin/python3 /home/carson/touch_ui/server.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
"""

stdin, stdout, stderr = client.exec_command(f"echo '{service_content}' | sudo tee /etc/systemd/system/touch-ui.service")
stdout.read()

stdin, stdout, stderr = client.exec_command("echo raspberry | sudo -S systemctl daemon-reload && echo raspberry | sudo -S systemctl restart touch-ui.service")
print("Systemctl output:", stdout.read().decode('utf-8', errors='replace'), stderr.read().decode('utf-8', errors='replace'))

time.sleep(2.0)

# Test 1: Play smw_coin.wav via API
print("\n--- 2. Testing smw_coin.wav via HTTP API ---")
req = urllib.request.Request(
    "http://192.168.0.86:8082/api/play_sound",
    data=json.dumps({"kind": "connect"}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=3.0) as resp:
    print("Coin response:", resp.status, resp.read().decode())

time.sleep(1.0)

# Test 2: Play smw_shell_ricochet.wav via API
print("\n--- 3. Testing smw_shell_ricochet.wav via HTTP API ---")
req = urllib.request.Request(
    "http://192.168.0.86:8082/api/play_sound",
    data=json.dumps({"kind": "smw_shell_ricochet"}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=3.0) as resp:
    print("Ricochet response:", resp.status, resp.read().decode())

time.sleep(1.0)

# Check journalctl logs
print("\n--- 4. Checking touch-ui journalctl logs ---")
stdin, stdout, stderr = client.exec_command("journalctl -u touch-ui.service -n 20 --no-pager")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
print("All deployment and service verification steps completed.")
