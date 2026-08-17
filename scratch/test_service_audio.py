import paramiko
import urllib.request
import json
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

print("1. Checking systemctl status touch-ui.service")
stdin, stdout, stderr = client.exec_command("systemctl status touch-ui.service")
print(stdout.read().decode('utf-8', errors='replace'))

print("\n2. Sending /api/play_sound for smw_shell_ricochet")
req = urllib.request.Request(
    "http://192.168.0.86:8082/api/play_sound",
    data=json.dumps({"kind": "smw_shell_ricochet"}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=3.0) as resp:
    print("Response:", resp.status, resp.read().decode())

time.sleep(1.0)

print("\n3. Checking touch-ui journalctl logs for any audio playback errors")
stdin, stdout, stderr = client.exec_command("journalctl -u touch-ui.service -n 25 --no-pager")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
