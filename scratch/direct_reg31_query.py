import paramiko
import sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

# Step 1: Kill running main.py cleanly
client.exec_command("pkill -9 -f main.py; fuser -k /dev/ttyACM0 2>/dev/null; sleep 0.5")

# Step 2: Query Motor 3 Register 31 directly
script = """
import time
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

portHandler = PortHandler('/dev/ttyACM0')
packetHandler = PacketHandler(0)

if not portHandler.openPort():
    print('FAIL: Cannot open /dev/ttyACM0')
    exit(1)

portHandler.setBaudRate(1000000)

val_1b, res1, err1 = packetHandler.read1ByteTxRx(portHandler, 3, 31)
val_2b, res2, err2 = packetHandler.read2ByteTxRx(portHandler, 3, 31)

# Check communication
print(f'COMM_RESULT_1B: {res1} (0 is COMM_SUCCESS), ERR: {err1}, VAL_1B: {val_1b}')
print(f'COMM_RESULT_2B: {res2} (0 is COMM_SUCCESS), ERR: {err2}, VAL_2B: {val_2b}')

# Also read raw present position for context
pos_raw, res_pos, err_pos = packetHandler.read2ByteTxRx(portHandler, 3, 56)
print(f'PRESENT_POSITION (Reg 56): {pos_raw}, RES: {res_pos}')

# Check all motors 1-6 offset for comparison
for sid in range(1, 7):
    o2, r, e = packetHandler.read2ByteTxRx(portHandler, sid, 31)
    print(f'Motor {sid} Offset (Reg 31-32): {o2} (res={r})')

portHandler.closePort()
"""

cmd = f"/home/user/so101/.venv/bin/python -c \"{script}\""
stdin, stdout, stderr = client.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')

print("--- DIRECT HARDWARE READ RESULTS ---")
print(out)
if err:
    print("STDERR:\n", err)

# Step 3: Restart main.py master daemon
client.exec_command("cd /home/user/so101/pi500 && nohup /home/user/so101/.venv/bin/python main.py </dev/null >/tmp/so101_master.log 2>&1 &")
client.close()
