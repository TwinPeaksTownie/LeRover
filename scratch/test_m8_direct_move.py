import serial
import time

ser = serial.Serial('/dev/ttyACM0', 1000000, timeout=0.1)

def send_pkt(pkt):
    chk = (~sum(pkt[2:])) & 0xFF
    pkt_bytes = bytes(pkt + [chk])
    ser.reset_input_buffer()
    ser.write(pkt_bytes)
    ser.flush()
    time.sleep(0.02)
    return ser.read(32)

# 1. Torque ON (Reg 40 = 1, Reg 48 = 1000)
send_pkt([0xFF, 0xFF, 8, 5, 3, 48, 0xE8, 0x03])
send_pkt([0xFF, 0xFF, 8, 4, 3, 40, 1])

# 2. Read Present Position
res = send_pkt([0xFF, 0xFF, 8, 4, 2, 56, 2])
if res and len(res) >= 6:
    pos = res[5] | (res[6] << 8) if len(res) >= 7 else res[5]
    print(f"INITIAL PRESENT POS: {pos} (raw hex: {res.hex()})")
else:
    print("Failed to read initial pos")
    pos = 0

# 3. Command +200 Ticks
target = (pos + 200) % 4096
print(f"COMMANDING TARGET: {target}")

# Send Reg 42 Goal Position = target, Goal Time = 0, Goal Speed = 200 (0x00C8)
t_l = target & 0xFF
t_h = (target >> 8) & 0xFF
res_w = send_pkt([0xFF, 0xFF, 8, 9, 3, 42, t_l, t_h, 0, 0, 0xC8, 0x00])
print(f"WRITE RESP: {res_w.hex() if res_w else 'NONE'}")

# 4. Monitor Present Position over 2 seconds
for i in range(10):
    time.sleep(0.2)
    res_p = send_pkt([0xFF, 0xFF, 8, 4, 2, 56, 2])
    if res_p and len(res_p) >= 6:
        p = res_p[5] | (res_p[6] << 8) if len(res_p) >= 7 else res_p[5]
        v = send_pkt([0xFF, 0xFF, 8, 4, 2, 62, 1])
        vol = v[5]/10.0 if v and len(v) >= 6 else 0
        print(f"t={0.2*(i+1):.1f}s | Present Pos = {p} | Volt = {vol}V")

ser.close()
