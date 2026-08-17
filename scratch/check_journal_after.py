import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

stdin, stdout, stderr = client.exec_command("journalctl -u touch-ui.service -n 10 --no-pager")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
