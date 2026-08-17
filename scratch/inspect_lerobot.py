import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

cmd = """/home/user/so101/.venv/bin/python -c "
import inspect
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus
import lerobot.motors.feetech as ftech

print('FeetechMotorsBus file:', inspect.getfile(FeetechMotorsBus))
print('MotorCalibration file:', inspect.getfile(MotorCalibration))

# Let's inspect the source of normalization in feetech or motors
" """
stdin, stdout, stderr = client.exec_command(cmd)
print("STDOUT:\n", stdout.read().decode())
print("STDERR:\n", stderr.read().decode())

client.close()
