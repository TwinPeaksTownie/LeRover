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

# Ensure symlink for alternate spelling richochet -> ricochet
stdin, stdout, stderr = client.exec_command("cd /home/carson/mario_sounds && ln -sf smw_shell_ricochet.wav smw_shell_richochet.wav && ln -sf smw_shell_ricochet.wav shell_ricochet.wav")
stdout.read()

sftp = client.open_sftp()
for f in ["server.py", "audio_service.py", "api_gateway.py"]:
    local_p = f"i:/aux_servo_interface/pi4b/{f}"
    remote_p = f"/home/carson/touch_ui/{f}"
    sftp.put(local_p, remote_p)
    print(f"Uploaded {f} -> {remote_p}")
sftp.close()

print("\n--- 2. Restarting touch-ui.service ---")
stdin, stdout, stderr = client.exec_command("echo raspberry | sudo -S systemctl restart touch-ui.service")
print("Restart output:", stdout.read().decode('utf-8', errors='replace'), stderr.read().decode('utf-8', errors='replace'))

time.sleep(2.0)

print("\n--- 3. Triggering test sound via HTTP endpoint on Pi 4B ---")
req = urllib.request.Request(
    "http://192.168.0.86:8082/api/play_sound",
    data=json.dumps({"kind": "smw_shell_ricochet"}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=3.0) as resp:
    print("HTTP Response:", resp.status, resp.read().decode())

time.sleep(1.0)

print("\n--- 4. Checking touch-ui journalctl logs ---")
stdin, stdout, stderr = client.exec_command("journalctl -u touch-ui.service -n 15 --no-pager")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
print("Pi 4B Audio Update & Verification Complete!")
