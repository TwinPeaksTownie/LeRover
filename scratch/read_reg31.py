import paramiko
import sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

cmd = """/home/user/so101/.venv/bin/python -c "
import time
import os

# We can query register 31 through lerobot or scservo_sdk or direct serial
try:
    from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS
    portHandler = PortHandler('/dev/ttyACM0')
    packetHandler = PacketHandler(0) # STS protocol 0
    if not portHandler.openPort():
        print('Failed to open port')
    else:
        portHandler.setBaudRate(1000000)
        # Register 31 (Offset), 2 bytes on STS3215 (or 1 byte)
        # Let's read 1 byte and 2 bytes
        val_1byte, result, err = packetHandler.read1ByteTxRx(portHandler, 3, 31)
        val_2byte, result2, err2 = packetHandler.read2ByteTxRx(portHandler, 3, 31)
        print(f'Motor 3 Reg 31 (1-byte): val={val_1byte}, result={result} (COMM_SUCCESS={COMM_SUCCESS}), err={err}')
        print(f'Motor 3 Reg 31-32 (2-byte): val={val_2byte}, result={result2}, err={err2}')
        
        # Also convert 2-byte signed if bit 11 or bit 15 is sign
        # On STS3215, offset is typically signed 11-bit or 16-bit:
        # Bit 11 is sign bit or 2's complement
        if val_2byte is not None:
            # Let's see raw binary/hex
            print(f'Hex: {hex(val_2byte)}')
        portHandler.closePort()
except Exception as e:
    print('Error:', e)
" """

# Before running, check if main.py is running. If so, let's stop it briefly to read serial, then restart it if needed, or query via backend
stdin, stdout, stderr = client.exec_command("pkill -STOP -f 'main.py' || true")
stdout.channel.recv_exit_status()

stdin, stdout, stderr = client.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
print("OUTPUT:\n", out)
if err:
    print("ERR:\n", err)

# Resume main.py
client.exec_command("pkill -CONT -f 'main.py' || true")

client.close()
