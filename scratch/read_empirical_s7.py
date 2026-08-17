import paramiko
import time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

py_script = """
import serial, time
s = serial.Serial('/dev/ttyACM0', 1000000, timeout=0.2)
s.reset_input_buffer()
s.reset_output_buffer()

def query(reg, length):
    pkt = [0xFF, 0xFF, 7, 4, 2, reg, length]
    chk = (~sum(pkt[2:])) & 0xFF
    s.reset_input_buffer()
    s.write(bytes(pkt + [chk]))
    s.flush()
    time.sleep(0.02)
    res = s.read(32)
    # Filter response
    for i in range(len(res) - 5):
        if res[i] == 0xFF and res[i+1] == 0xFF and res[i+2] == 7:
            val_len = res[i+3]
            data = res[i+5 : i+3+val_len]
            if len(data) == 1:
                return data[0]
            elif len(data) == 2:
                return data[0] | (data[1] << 8)
    return None

pos = query(56, 2)
offset = query(31, 2)
mode = query(33, 1)
lock = query(55, 1)

s.close()
print(f"EMPIRICAL_PRESENT_POSITION_REG_56: {pos}")
print(f"EMPIRICAL_OFFSET_REG_31: {offset}")
print(f"EMPIRICAL_MODE_REG_33: {mode}")
print(f"EMPIRICAL_EEPROM_LOCK_REG_55: {lock}")
"""

sftp = client.open_sftp()
with sftp.file('/tmp/read_emp.py', 'w') as f:
    f.write(py_script)
sftp.close()

cmd = """
pkill -9 -f main.py || true
sleep 1
/home/user/so101/.venv/bin/python /tmp/read_emp.py
bash /home/user/so101/start_master.sh >/dev/null 2>&1 &
"""

stdin, stdout, stderr = client.exec_command(cmd)
print("STDOUT:", stdout.read().decode())
print("STDERR:", stderr.read().decode())
client.close()
