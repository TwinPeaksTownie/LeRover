import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

sftp = client.open_sftp()
sftp.put("i:/aux_servo_interface/scratch/test_pulse_env.py", "/tmp/test_pulse_env.py")
sftp.close()

stdin, stdout, stderr = client.exec_command("python3 /tmp/test_pulse_env.py")
print("Output:\n", stdout.read().decode('utf-8', errors='replace'))
print("Error:\n", stderr.read().decode('utf-8', errors='replace'))

client.close()
