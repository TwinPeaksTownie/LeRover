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

print("=== MOTOR 8 STEPPING SWEEP TEST ===")

# Torque ON
send_pkt([0xFF, 0xFF, 8, 5, 3, 48, 0xE8, 0x03])
send_pkt([0xFF, 0xFF, 8, 4, 3, 40, 1])

for target in [20, 50, 80, 100, 120]:
    t_l = target & 0xFF
    t_h = (target >> 8) & 0xFF
    # Goal Position = target, Goal Speed = 150
    send_pkt([0xFF, 0xFF, 8, 9, 3, 42, t_l, t_h, 0, 0, 0x96, 0x00])
    time.sleep(0.3)
    
    res = send_pkt([0xFF, 0xFF, 8, 4, 2, 56, 2])
    p = (res[5] | (res[6] << 8)) if (res and len(res) >= 7) else 'ERR'
    print(f"Commanded Target: {target} | Achieved Present Pos: {p}")

ser.close()
