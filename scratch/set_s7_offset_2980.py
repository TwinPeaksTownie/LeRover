import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

py_script = """
import serial, time

ser = serial.Serial('/dev/ttyACM0', 1000000, timeout=0.2)
ser.reset_input_buffer()
ser.reset_output_buffer()

# Step 1: Disable Torque
pkt_tq = [0xFF, 0xFF, 7, 4, 3, 40, 0]
chk_tq = (~sum(pkt_tq[2:])) & 0xFF
ser.write(bytes(pkt_tq + [chk_tq]))
ser.flush()
time.sleep(0.05)
_ = ser.read(64)

# Step 2: Unlock EEPROM (Reg 55 = 0)
pkt_unlk = [0xFF, 0xFF, 7, 4, 3, 55, 0]
chk_unlk = (~sum(pkt_unlk[2:])) & 0xFF
ser.write(bytes(pkt_unlk + [chk_unlk]))
ser.flush()
time.sleep(0.05)
_ = ser.read(64)

# Step 3: Write Reg 31 = 2980 (0x0BA4 -> L: 0xA4, H: 0x0B)
val = 2980
vl = val & 0xFF
vh = (val >> 8) & 0xFF
pkt_wr = [0xFF, 0xFF, 7, 5, 3, 31, vl, vh]
chk_wr = (~sum(pkt_wr[2:])) & 0xFF
ser.write(bytes(pkt_wr + [chk_wr]))
ser.flush()
time.sleep(0.1)
_ = ser.read(64)

# Step 4: Lock EEPROM (Reg 55 = 1)
pkt_lock = [0xFF, 0xFF, 7, 4, 3, 55, 1]
chk_lock = (~sum(pkt_lock[2:])) & 0xFF
ser.write(bytes(pkt_lock + [chk_lock]))
ser.flush()
time.sleep(0.05)
_ = ser.read(64)

# Step 5: Read back Reg 31
pkt_off = [0xFF, 0xFF, 7, 4, 2, 31, 2]
chk_off = (~sum(pkt_off[2:])) & 0xFF
ser.write(bytes(pkt_off + [chk_off]))
ser.flush()
time.sleep(0.05)
resp_off = ser.read(64)

# Step 6: Read Reg 56 (Present Position)
pkt_pos = [0xFF, 0xFF, 7, 4, 2, 56, 2]
chk_pos = (~sum(pkt_pos[2:])) & 0xFF
ser.write(bytes(pkt_pos + [chk_pos]))
ser.flush()
time.sleep(0.05)
resp_pos = ser.read(64)

off_val = None
if resp_off:
    if len(resp_off) >= 8 and resp_off[:8] == bytes(pkt_off + [chk_off]):
        resp_off = resp_off[8:]
    for i in range(len(resp_off) - 6):
        if resp_off[i] == 0xFF and resp_off[i+1] == 0xFF and resp_off[i+2] == 7 and resp_off[i+3] == 4:
            off_val = resp_off[i+5] | (resp_off[i+6] << 8)
            break

pos_val = None
if resp_pos:
    if len(resp_pos) >= 8 and resp_pos[:8] == bytes(pkt_pos + [chk_pos]):
        resp_pos = resp_pos[8:]
    for i in range(len(resp_pos) - 6):
        if resp_pos[i] == 0xFF and resp_pos[i+1] == 0xFF and resp_pos[i+2] == 7 and resp_pos[i+3] == 4:
            pos_val = resp_pos[i+5] | (resp_pos[i+6] << 8)
            break

print(f"CONFIRMED_EEPROM_OFFSET: {off_val}")
print(f"CONFIRMED_PRESENT_POSITION: {pos_val}")
if pos_val is not None:
    deg = (pos_val - 2048) * 360.0 / 4096.0
    print(f"CONFIRMED_ANGLE: {deg:.2f} deg")

ser.close()
"""

sftp = client.open_sftp()
with sftp.file('/tmp/test_offset_2980.py', 'w') as f:
    f.write(py_script)
sftp.close()

stdin, stdout, stderr = client.exec_command('/home/user/so101/.venv/bin/python /tmp/test_offset_2980.py')
print(stdout.read().decode())
client.close()
