import paramiko
import sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

cmd = """/home/user/so101/.venv/bin/python -c "
import inspect
from lerobot.teleoperators.so_leader import SO101Leader
print('=== SO101Leader.get_action ===')
print(inspect.getsource(SO101Leader.get_action))
" """
stdin, stdout, stderr = client.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace')
sys.stdout.reconfigure(encoding='utf-8')
print(out)

client.close()
