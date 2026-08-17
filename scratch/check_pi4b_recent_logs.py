import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

stdin, stdout, stderr = client.exec_command("journalctl -u touch-ui.service -n 30 --no-pager")
print("=== Pi 4B touch-ui journalctl ===")
print(stdout.read().decode('utf-8', errors='replace'))

# Check amixer master volume on Pi 4B
stdin, stdout, stderr = client.exec_command("amixer get Master 2>&1")
print("=== Pi 4B amixer get Master ===")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
