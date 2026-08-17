import paramiko
import json
import sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

# Step 1: Read calibration file
cmd_calib = "cat ~/.cache/huggingface/lerobot/calibration/robots/so_follower/follower.json"
stdin, stdout, stderr = client.exec_command(cmd_calib)
calib_raw = stdout.read().decode()
print("=== CALIBRATION FILE (follower.json) ===")
print(calib_raw)

# Step 2: Read live hardware Present_Position directly from bus on Pi 500
# We stop main.py briefly to get exclusive clean bus access
client.exec_command("pkill -9 -f main.py; fuser -k /dev/ttyACM0 2>/dev/null; sleep 0.5")

hw_script = """import json
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

portHandler = PortHandler('/dev/ttyACM0')
packetHandler = PacketHandler(0)

if not portHandler.openPort():
    print('ERROR: Failed to open port')
    exit(1)

portHandler.setBaudRate(1000000)

# Read Servo 3 Register 56 (Present_Position, 2 bytes)
pos3, res3, err3 = packetHandler.read2ByteTxRx(portHandler, 3, 56)
# Read Servo 3 Register 31 (Offset, 2 bytes)
off3, res_off, err_off = packetHandler.read2ByteTxRx(portHandler, 3, 31)

# Read all servos 1-6 Present_Position for full context
all_positions = {}
for sid in range(1, 7):
    p, r, e = packetHandler.read2ByteTxRx(portHandler, sid, 56)
    all_positions[sid] = p if r == COMM_SUCCESS else f'Error(res={r}, err={e})'

portHandler.closePort()

print('=== LIVE HARDWARE ENCODER READINGS (Register 56) ===')
print(f'Servo 3 (elbow_flex) Raw Present_Position: {pos3} ticks (res={res3}, err={err3})')
print(f'Servo 3 (elbow_flex) Hardware Offset (Reg 31): {off3} ticks')
print('All Motors (1-6) Present Ticks:', json.dumps(all_positions, indent=2))
"""

cmd_hw = f"/home/user/so101/.venv/bin/python -c \"{hw_script}\""
stdin, stdout, stderr = client.exec_command(cmd_hw)
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("ERR:\n", err)

# Step 3: Restart master daemon
client.exec_command("cd /home/user/so101/pi500 && nohup /home/user/so101/.venv/bin/python main.py </dev/null >/tmp/so101_master.log 2>&1 &")
client.close()
