import paramiko
import time
import urllib.request
import json

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

# Transfer file
sftp = client.open_sftp()
local_path = r"i:\aux_servo_interface\pi500\teleop_control_loop.py"
remote_path = "/home/user/so101/pi500/teleop_control_loop.py"
sftp.put(local_path, remote_path)
sftp.close()

# Restart
stdin, stdout, stderr = client.exec_command("pkill -9 -f main.py; fuser -k /dev/ttyACM0 2>/dev/null; sleep 0.5")
stdout.channel.recv_exit_status()

stdin, stdout, stderr = client.exec_command("cd /home/user/so101/pi500 && nohup /home/user/so101/.venv/bin/python main.py </dev/null >/tmp/so101_master.log 2>&1 &")
time.sleep(1.5)

# Verification 1: Process running
stdin, stdout, stderr = client.exec_command("ps aux | grep -E 'main.py' | grep -v grep")
print("Process status:\n", stdout.read().decode())

# Verification 2: Unit test function
test_cmd = """cd /home/user/so101/pi500 && /home/user/so101/.venv/bin/python -c "
import sys
sys.path.insert(0, '.')
from teleop_control_loop import validate_and_clamp_teleop_frame
calib = {'elbow_flex': None, 'shoulder_pan': None, 'gripper': None}
test_action = {'elbow_flex': -105.2, 'shoulder_pan': 102.5, 'gripper': 110.0}
res = validate_and_clamp_teleop_frame(test_action, calib)
print('Unit Test Clamped Result:', res)
assert res['elbow_flex'] == -100.0
assert res['shoulder_pan'] == 100.0
assert res['gripper'] == 100.0
print('Assertion tests passed successfully!')
" """
stdin, stdout, stderr = client.exec_command(test_cmd)
print("Verification test:\n", stdout.read().decode())
err = stderr.read().decode()
if err:
    print("Verification ERR:\n", err)

# Verification 3: HTTP API online
try:
    req = urllib.request.Request("http://192.168.0.130:8085/api/status")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        print("API Status 200 OK:", resp.read().decode()[:200])
except Exception as e:
    print("API Error:", e)

client.close()
