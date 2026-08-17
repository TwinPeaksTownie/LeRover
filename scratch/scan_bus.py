import serial
import time

s = serial.Serial('/dev/ttyACM0', 1000000, timeout=0.1)
s.reset_input_buffer()
s.reset_output_buffer()

def read_motor(sid):
    # Read Reg 56 (2 bytes)
    pkt = [0xFF, 0xFF, sid, 4, 2, 56, 2]
    chk = (~sum(pkt[2:])) & 0xFF
    s.reset_input_buffer()
    s.write(bytes(pkt + [chk]))
    s.flush()
    time.sleep(0.015)
    res = s.read(32)
    for i in range(len(res) - 5):
        if res[i] == 0xFF and res[i+1] == 0xFF and res[i+2] == sid:
            val_len = res[i+3]
            data = res[i+5 : i+3+val_len]
            if len(data) >= 2:
                return data[0] | (data[1] << 8)
    return None

def read_vol(sid):
    # Read Reg 62 (1 byte)
    pkt = [0xFF, 0xFF, sid, 4, 2, 62, 1]
    chk = (~sum(pkt[2:])) & 0xFF
    s.reset_input_buffer()
    s.write(bytes(pkt + [chk]))
    s.flush()
    time.sleep(0.015)
    res = s.read(32)
    for i in range(len(res) - 5):
        if res[i] == 0xFF and res[i+1] == 0xFF and res[i+2] == sid:
            val_len = res[i+3]
            data = res[i+5 : i+3+val_len]
            if len(data) >= 1:
                return data[0] / 10.0
    return None

print("=== BUS SCAN (Motors 1-8) ===")
for sid in range(1, 9):
    p = read_motor(sid)
    v = read_vol(sid)
    print(f"Motor {sid}: POS={p}, VOLT={v}V")
s.close()
