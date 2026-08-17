#!/usr/bin/env python3
import sys
import serial
import time

try:
    ser = serial.Serial('/dev/ttyACM0', 1000000, timeout=0.1)
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    # Read Reg 56 (Present Position, 2 bytes)
    pkt_pos = [0xFF, 0xFF, 7, 4, 2, 56, 2]
    chk_pos = (~sum(pkt_pos[2:])) & 0xFF
    ser.write(bytes(pkt_pos + [chk_pos]))
    ser.flush()
    time.sleep(0.02)
    resp_pos = ser.read(64)

    # Read Reg 31 (Offset, 2 bytes)
    pkt_off = [0xFF, 0xFF, 7, 4, 2, 31, 2]
    chk_off = (~sum(pkt_off[2:])) & 0xFF
    ser.write(bytes(pkt_off + [chk_off]))
    ser.flush()
    time.sleep(0.02)
    resp_off = ser.read(64)

    pos_val = None
    if resp_pos and len(resp_pos) >= 8:
        # Strip echo if present
        if resp_pos[:8] == bytes(pkt_pos + [chk_pos]):
            resp_pos = resp_pos[8:]
        for i in range(len(resp_pos) - 5):
            if resp_pos[i] == 0xFF and resp_pos[i+1] == 0xFF and resp_pos[i+2] == 7:
                pos_val = resp_pos[i+5] | (resp_pos[i+6] << 8)
                break

    off_val = None
    if resp_off and len(resp_off) >= 8:
        if resp_off[:8] == bytes(pkt_off + [chk_off]):
            resp_off = resp_off[8:]
        for i in range(len(resp_off) - 5):
            if resp_off[i] == 0xFF and resp_off[i+1] == 0xFF and resp_off[i+2] == 7:
                off_val = resp_off[i+5] | (resp_off[i+6] << 8)
                break

    print(f"SERVO 7 REPORTED POSITION: {pos_val} ticks")
    print(f"SERVO 7 EEPROM OFFSET (REG 31): {off_val} ticks")

    if pos_val is not None:
        deg = (pos_val - 2048) * 360.0 / 4096.0
        print(f"SERVO 7 CALCULATED ANGLE: {deg:.1f} deg")

    ser.close()
except Exception as e:
    print(f"ERROR: {e}")
