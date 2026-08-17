import paramiko
import urllib.request
import json

print("--- Pi 500 Logs ---")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

stdin, stdout, stderr = client.exec_command("tail -n 100 /tmp/so101_master.log")
print(stdout.read().decode())
client.close()

print("--- Mac Mini API Endpoints ---")
try:
    for ep in ["/api/status", "/api/config", "/api/calibration", "/api/telemetry"]:
        try:
            req = urllib.request.Request(f"http://192.168.0.2:8086{ep}")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                print(f"{ep} -> {resp.read().decode()[:300]}")
        except Exception as e:
            print(f"{ep} -> Error: {e}")
except Exception as e:
    print("Mac error:", e)
