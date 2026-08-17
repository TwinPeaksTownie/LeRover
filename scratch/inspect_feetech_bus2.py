import paramiko
import sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

cmd = """/home/user/so101/.venv/bin/python -c "
import inspect
from lerobot.motors.motors_bus import MotorsBus
print('=== MotorsBus._unnormalize ===')
print(inspect.getsource(MotorsBus._unnormalize))
print('=== MotorsBus._normalize ===')
print(inspect.getsource(MotorsBus._normalize))
" """
stdin, stdout, stderr = client.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace')
sys.stdout.reconfigure(encoding='utf-8')
print(out)

client.close()
