import serial
import time

print("=== BROADCAST UN-MUTE & POS READ TEST ===")

for b in [1000000, 500000, 115200, 57600]:
    try:
        ser = serial.Serial('/dev/ttyACM0', b, timeout=0.05)
        # Broadcast Reg 8 = 2 (Status Return Level 2)
        pkt1 = [0xFF, 0xFF, 0xFE, 4, 3, 8, 2]
        pkt1.append((~sum(pkt1[2:])) & 0xFF)
        ser.write(bytes(pkt1))
        ser.flush()
        time.sleep(0.02)
        
        # Broadcast Reg 35 = 0 (Clear Alarms)
        pkt2 = [0xFF, 0xFF, 0xFE, 4, 3, 35, 0]
        pkt2.append((~sum(pkt2[2:])) & 0xFF)
        ser.write(bytes(pkt2))
        ser.flush()
        time.sleep(0.02)
        ser.close()
    except Exception as e:
        print(f"Baud {b} error: {e}")

time.sleep(0.1)

ser = serial.Serial('/dev/ttyACM0', 1000000, timeout=0.05)
for sid in range(1, 9):
    pkt = [0xFF, 0xFF, sid, 4, 2, 56, 2] # Read Reg 56 (Present Position)
    pkt.append((~sum(pkt[2:])) & 0xFF)
    ser.reset_input_buffer()
    ser.write(bytes(pkt))
    ser.flush()
    time.sleep(0.02)
    res = ser.read(32)
    if res and len(res) >= 6:
        print(f"Motor {sid} RESPONDED @ 1000000 baud! Hex: {res.hex()}")
    else:
        print(f"Motor {sid}: NO RESPONSE")
ser.close()
