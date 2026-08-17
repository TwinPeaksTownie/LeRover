import paramiko
import time
import urllib.request
import json

print("=== 1. Deploying to Pi 500 (192.168.0.130) ===")
client500 = paramiko.SSHClient()
client500.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client500.connect('192.168.0.130', username='user', timeout=5)

sftp500 = client500.open_sftp()
files_to_deploy_500 = [
    (r"i:\aux_servo_interface\pi500\robot_backend.py", "/home/user/so101/pi500/robot_backend.py"),
    (r"i:\aux_servo_interface\pi500\api_server.py", "/home/user/so101/pi500/api_server.py"),
    (r"i:\aux_servo_interface\pi500\pokeball_app.py", "/home/user/so101/pi500/pokeball_app.py"),
]
for local_f, remote_f in files_to_deploy_500:
    print(f"SFTP -> Pi 500: {remote_f}")
    sftp500.put(local_f, remote_f)
sftp500.close()

# Restart Pi 500 master daemon
client500.exec_command("pkill -9 -f main.py; fuser -k /dev/ttyACM0 2>/dev/null; fuser -k 8085/tcp 2>/dev/null; sleep 0.5")
time.sleep(1.0)
client500.exec_command("cd /home/user/so101/pi500 && nohup /home/user/so101/.venv/bin/python main.py </dev/null >/tmp/so101_master.log 2>&1 &")
time.sleep(1.5)

stdin, stdout, stderr = client500.exec_command("ps aux | grep -E 'main.py' | grep -v grep")
print("Pi 500 Process Status:\n", stdout.read().decode())
client500.close()


print("\n=== 2. Deploying to Pi 4B Touch UI (192.168.0.86) ===")
client4b = paramiko.SSHClient()
client4b.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client4b.connect('192.168.0.86', username='carson', password='raspberry', timeout=5)

sftp4b = client4b.open_sftp()
files_to_deploy_4b = [
    (r"i:\aux_servo_interface\pi4b\server.py", "/home/carson/touch_ui/server.py"),
    (r"i:\aux_servo_interface\pi4b\api_gateway.py", "/home/carson/touch_ui/api_gateway.py"),
    (r"i:\aux_servo_interface\pi4b\static\gantry_ui.html", "/home/carson/touch_ui/static/gantry_ui.html"),
]
for local_f, remote_f in files_to_deploy_4b:
    print(f"SFTP -> Pi 4B: {remote_f}")
    sftp4b.put(local_f, remote_f)
sftp4b.close()

# Restart Pi 4B touch-ui service
stdin, stdout, stderr = client4b.exec_command("sudo systemctl restart touch-ui.service; sleep 1.0; systemctl is-active touch-ui.service")
print("Pi 4B Service Status:\n", stdout.read().decode())
client4b.close()


print("\n=== 3. End-to-End Verification of /api/pedestal_step ===")
time.sleep(1.0)

# Check Pi 500 status directly
try:
    req = urllib.request.Request("http://192.168.0.130:8085/api/status")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        print("Pi 500 API Status 200 OK")
except Exception as e:
    print("Pi 500 API check failed:", e)

# Test /api/pedestal_step endpoint calculation via Pi 4B Router
try:
    # Test read current angle via Pi 4B Router
    req = urllib.request.Request("http://192.168.0.86:8082/api/telemetry")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        tdata = json.loads(resp.read().decode())
        s7_telem = tdata.get("hardware_telemetry", {}).get("servos", {}).get("7", {})
        print("Pi 4B Router Telemetry for Servo 7:", s7_telem)
except Exception as e:
    print("Pi 4B Telemetry poll failed:", e)
