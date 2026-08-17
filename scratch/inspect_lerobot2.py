import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

cmd = """/home/user/so101/.venv/bin/python -c "
import inspect
from lerobot.motors import motors_bus
print(inspect.getsource(motors_bus.MotorCalibration))
" """
stdin, stdout, stderr = client.exec_command(cmd)
print("STDOUT:\n", stdout.read().decode())
print("STDERR:\n", stderr.read().decode())

client.close()
