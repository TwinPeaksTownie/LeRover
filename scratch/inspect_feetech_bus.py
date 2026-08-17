import paramiko
import sys

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

cmd = """/home/user/so101/.venv/bin/python -c "
import inspect
from lerobot.motors.feetech import FeetechMotorsBus
from lerobot.motors import motors_bus

print('=== FeetechMotorsBus.sync_write ===')
print(inspect.getsource(FeetechMotorsBus.sync_write))

print('=== motors_bus normalization methods ===')
for name, member in inspect.getmembers(motors_bus):
    if inspect.isfunction(member) or inspect.isclass(member):
        if 'norm' in name.lower() or 'convert' in name.lower():
            print(name)
" """
stdin, stdout, stderr = client.exec_command(cmd)
out = stdout.read().decode('utf-8', errors='replace')
sys.stdout.reconfigure(encoding='utf-8')
print(out)

client.close()
