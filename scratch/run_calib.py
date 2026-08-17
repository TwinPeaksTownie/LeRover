import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

stdin, stdout, stderr = client.exec_command('/home/user/so101/.venv/bin/python /tmp/calibrate_s7.py')
print("STDOUT:\n", stdout.read().decode())
print("STDERR:\n", stderr.read().decode())
client.close()
