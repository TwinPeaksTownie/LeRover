import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

py_script = """
import serial, time

try:
    ser = serial.Serial('/dev/ttyACM0', 1000000, timeout=0.2)
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    # Read Reg 56 (Present Position, 2 bytes)
    pkt_pos = [0xFF, 0xFF, 7, 4, 2, 56, 2]
    chk_pos = (~sum(pkt_pos[2:])) & 0xFF
    ser.write(bytes(pkt_pos + [chk_pos]))
    ser.flush()
    time.sleep(0.04)
    resp_pos = ser.read(64)

    # Read Reg 31 (Offset, 2 bytes)
    pkt_off = [0xFF, 0xFF, 7, 4, 2, 31, 2]
    chk_off = (~sum(pkt_off[2:])) & 0xFF
    ser.write(bytes(pkt_off + [chk_off]))
    ser.flush()
    time.sleep(0.04)
    resp_off = ser.read(64)

    pos_val = None
    if resp_pos:
        # Strip echo if present
        if len(resp_pos) >= 8 and resp_pos[:8] == bytes(pkt_pos + [chk_pos]):
            resp_pos = resp_pos[8:]
        for i in range(len(resp_pos) - 6):
            if resp_pos[i] == 0xFF and resp_pos[i+1] == 0xFF and resp_pos[i+2] == 7 and resp_pos[i+3] == 4:
                pos_val = resp_pos[i+5] | (resp_pos[i+6] << 8)
                break

    off_val = None
    if resp_off:
        if len(resp_off) >= 8 and resp_off[:8] == bytes(pkt_off + [chk_off]):
            resp_off = resp_off[8:]
        for i in range(len(resp_off) - 6):
            if resp_off[i] == 0xFF and resp_off[i+1] == 0xFF and resp_off[i+2] == 7 and resp_off[i+3] == 4:
                off_val = resp_off[i+5] | (resp_off[i+6] << 8)
                break

    print(f"PRESENT_POSITION_REG_56: {pos_val}")
    print(f"EEPROM_OFFSET_REG_31: {off_val}")
    ser.close()
except Exception as e:
    print(f"ERROR: {e}")
"""

sftp = client.open_sftp()
with sftp.file('/tmp/read_s7_registers.py', 'w') as f:
    f.write(py_script)
sftp.close()

# Ensure serial port is free, run script, restart master daemon if needed
stdin, stdout, stderr = client.exec_command('pkill -9 -f main.py 2>/dev/null || true; sleep 0.5; python3 /tmp/read_s7_registers.py; nohup bash -c "exec /home/user/so101/.venv/bin/python -u /home/user/so101/pi500/main.py" </dev/null >/tmp/so101_master.log 2>&1 &')
print("OUT:", stdout.read().decode())
print("ERR:", stderr.read().decode())
client.close()
