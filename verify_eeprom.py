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
    attrs[0] = attrs[0] & ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP | termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
    attrs[1] = attrs[1] & ~termios.OPOST
    attrs[2] = (attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB)) | termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = attrs[3] & ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    
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
    time.sleep(0.05)
    
    res = bytearray()
    for _ in range(10):
        r, _, _ = select.select([fd], [], [], 0.03)
        if r:
            chunk = os.read(fd, 64)
            if chunk:
                res.extend(chunk)
        else:
            if len(res) > 0:
                break
    return list(res)

port = '/dev/cu.usbmodem5B415318721'
fd = open_serial(port, 1000000)

print(f"Reading EEPROM & RAM registers from Servo ID 2 on {port}...")

# Read Registers 3 to 35 (EEPROM block)
# Reg 3 (0x03): Firmware / Model
# Reg 5 (0x05): Servo ID
# Reg 6 (0x06): Baud Rate
# Reg 33 (0x21): Operating Mode
res_eeprom = send_pkt(fd, 2, 2, 3, [33]) # Read 33 bytes starting at Reg 3
print("Raw EEPROM Packet:", [hex(b) for b in res_eeprom])

if res_eeprom and len(res_eeprom) >= 38 and res_eeprom[2] == 2:
    # Payload starts at index 5
    data = res_eeprom[5:-1]
    print("\n--- SERVO ID 2 EEPROM VERIFICATION ---")
    print(f"Model / Firmware (Reg 3-4): {data[0]}.{data[1]}")
    print(f"Verified Servo ID (Reg 5)  : {data[2]}")
    print(f"Baud Rate (Reg 6)          : {data[3]} (0 = 1Mbps)")
    print(f"Return Delay (Reg 7)       : {data[4]}")
    print(f"Min Angle Limit (Reg 9-10) : {data[6] | (data[7] << 8)}")
    print(f"Max Angle Limit (Reg 11-12): {data[8] | (data[9] << 8)}")
    print(f"Operating Mode (Reg 33)    : {data[30]} (0=Position, 1=Wheel, 3=Multi-turn)")

# Read Present Status & Lock Register (Reg 55 to 65)
res_ram = send_pkt(fd, 2, 2, 55, [10])
print("\nRaw Status Packet:", [hex(b) for b in res_ram])
if res_ram and len(res_ram) >= 15 and res_ram[2] == 2:
    data_ram = res_ram[5:-1]
    print(f"EEPROM Lock (Reg 55)       : {data_ram[0]} (1 = Locked)")
    print(f"Present Position (Reg 56-57): {data_ram[1] | (data_ram[2] << 8)} ticks")
    print(f"Present Voltage (Reg 62)   : {data_ram[7] / 10.0} V")

os.close(fd)
