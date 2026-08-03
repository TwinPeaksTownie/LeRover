import os
import sys
import time
import termios
import fcntl
import array
import select

IOSSIOSPEED = 0x80045402

def open_serial(port_path, baud=1000000):
    fd = os.open(port_path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    
    # Raw mode
    attrs[0] = attrs[0] & ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP | termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
    attrs[1] = attrs[1] & ~termios.OPOST
    attrs[2] = (attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB)) | termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = attrs[3] & ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    
    # Set high speed baud rate on macOS
    speed = array.array('i', [baud])
    fcntl.ioctl(fd, IOSSIOSPEED, speed, True)
    return fd

def calc_chk(pkt):
    return (~sum(pkt[2:])) & 0xFF

def send_pkt(fd, sid, inst, reg, params=None):
    if params is None:
        params = []
    length = len(params) + 3
    pkt = [0xFF, 0xFF, sid, length, inst, reg] + params
    pkt.append(calc_chk(pkt))
    
    termios.tcflush(fd, termios.TCIFLUSH)
    os.write(fd, bytes(pkt))
    time.sleep(0.08)
    
    res = bytearray()
    for _ in range(10):
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            chunk = os.read(fd, 64)
            if chunk:
                res.extend(chunk)
        else:
            if len(res) > 0:
                break
    return list(res)

port = '/dev/cu.usbmodem5B415318721'
print(f"Target serial port: {port}")

for baud in [1000000, 115200, 57600]:
    try:
        print(f"\n--- Testing Baud Rate: {baud} ---")
        fd = open_serial(port, baud)
        
        # Step 1: Unlock EEPROM (Reg 55 = 0) broadcast
        res_u = send_pkt(fd, 0xFE, 3, 55, [0])
        print("EEPROM Unlock Resp:", [hex(b) for b in res_u])
        
        # Step 2: Set Servo ID = 2 (Reg 5 = 2) broadcast
        res_id = send_pkt(fd, 0xFE, 3, 5, [2])
        print("Set ID=2 Resp:", [hex(b) for b in res_id])
        
        # Step 3: Lock EEPROM (Reg 55 = 1) on ID 2
        res_l = send_pkt(fd, 2, 3, 55, [1])
        print("EEPROM Lock Resp:", [hex(b) for b in res_l])
        
        # Step 4: Read Present Position from Servo ID 2 (Reg 56, 2 bytes)
        res_p = send_pkt(fd, 2, 2, 56, [2])
        print("Read Position ID=2 Resp:", [hex(b) for b in res_p])
        
        if res_p and len(res_p) >= 6:
            for i in range(len(res_p) - 5):
                if res_p[i] == 0xFF and res_p[i+1] == 0xFF and res_p[i+2] == 2:
                    pos = res_p[i+5] + (res_p[i+6] << 8) if i+6 < len(res_p) else res_p[i+5]
                    print(f"\nSUCCESS: Servo ID changed to 2!")
                    print(f"Verified position response from Servo ID 2: {pos} ticks (0-4095)")
                    os.close(fd)
                    sys.exit(0)
        os.close(fd)
    except Exception as e:
        print(f"Error at {baud} baud: {e}")

print("\nFinished scan.")
