import paramiko
import sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

cmd = """/home/user/so101/.venv/bin/python -c "
import inspect
from lerobot.motors.feetech import FeetechMotorsBus
print('=== FeetechMotorsBus.sync_read ===')
print(inspect.getsource(FeetechMotorsBus.sync_read))
" """
stdin, stdout, stderr = client.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace')
sys.stdout.reconfigure(encoding='utf-8')
print(out)

client.close()
