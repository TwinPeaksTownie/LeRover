import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

stdin, stdout, stderr = client.exec_command('/home/user/so101/.venv/bin/python /tmp/read_s7_registers.py')
out = stdout.read().decode()
err = stderr.read().decode()
print("OUTPUT:")
print(out)
print("STDERR:")
print(err)
client.close()
