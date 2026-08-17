import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

stdin, stdout, stderr = client.exec_command('cat /home/user/so101/calibration_aux.json')
print("CALIBRATION_AUX.JSON on Pi 500:")
print(stdout.read().decode())
client.close()
