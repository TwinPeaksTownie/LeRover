import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

stdin, stdout, stderr = client.exec_command('cat /tmp/so101_master.log | tail -n 30')
print("LOGS:")
print(stdout.read().decode())

stdin, stdout, stderr = client.exec_command('ps aux | grep main.py')
print("PROCESS:")
print(stdout.read().decode())

client.close()
