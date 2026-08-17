import paramiko
import json
import urllib.request

print("--- Querying Servo 7 Telemetry on Pi 500 ---")

# Try HTTP API first
try:
    req = urllib.request.Request("http://192.168.0.130:8085/api/status")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        data = json.loads(resp.read().decode())
        s7 = data.get("servos", {}).get("7")
        print("API Servo 7 Data:", json.dumps(s7, indent=2))
        print("Full Status Summary:", {k: v for k, v in data.items() if k != "servos"})
except Exception as e:
    print("HTTP API query failed (daemon may not be running yet):", e)

# Also let's check over SSH to see if main.py is running or read direct from serial
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

stdin, stdout, stderr = client.exec_command("ps aux | grep -E 'python|main.py' | grep -v grep")
print("\nRunning Processes:\n", stdout.read().decode())

# Check calibration_aux.json
stdin, stdout, stderr = client.exec_command("cat ~/so101/calibration_aux.json 2>/dev/null || cat ~/.cache/huggingface/lerobot/calibration/robots/so_follower/calibration_aux.json 2>/dev/null")
print("Aux Calibration:\n", stdout.read().decode())

client.close()
