import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

py_script = """
import sys, time
sys.path.insert(0, '/home/user/so101/pi500')
from aux_servo_controller import AuxiliaryServoController

ctrl = AuxiliaryServoController()
time.sleep(0.05)
for attempt in range(5):
    ctrl.flush_buffers()
    pos7 = ctrl.read_pos(7)
    v7 = ctrl.read_voltage(7)
    if pos7 is not None:
        break
    time.sleep(0.05)

# Read Reg 31
pkt = [0xFF, 0xFF, 7, 4, 2, 31, 2]
res = ctrl._send_and_read(pkt, expected_res_len=8)
offset = None
if res and len(res) >= 8 and res[2] == 7:
    offset = res[5] | (res[6] << 8)

ctrl.disconnect()

print(f"LIVE_REPORTED_POS: {pos7}")
print(f"LIVE_VOLTAGE: {v7}")
print(f"HARDWARE_EEPROM_OFFSET: {offset}")
if pos7 is not None and offset is not None:
    raw = (pos7 - offset) % 4096
    print(f"LIVE_TRUE_RAW_SENSOR: {raw}")
"""

sftp = client.open_sftp()
with sftp.file('/tmp/read_live.py', 'w') as f:
    f.write(py_script)
sftp.close()

stdin, stdout, stderr = client.exec_command('pkill -9 -f main.py 2>/dev/null || true; sleep 1; /home/user/so101/.venv/bin/python /tmp/read_live.py; nohup bash -c "exec /home/user/so101/.venv/bin/python -u /home/user/so101/pi500/main.py" </dev/null >/tmp/so101_master.log 2>&1 &')
print("OUT:", stdout.read().decode())
print("ERR:", stderr.read().decode())
client.close()
