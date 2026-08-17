import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.86', username='carson', password='raspberry', timeout=5)

stdin, stdout, stderr = client.exec_command('ls -la /home/carson/mario_sounds/')
print("Mario sounds directory on Pi 4B:\n" + stdout.read().decode())

stdin, stdout, stderr = client.exec_command('find /home/carson/ -name "*.wav"')
print("All wav files on Pi 4B:\n" + stdout.read().decode())

# Check recent audio service logs on Pi 4B
stdin, stdout, stderr = client.exec_command('journalctl -u touch-ui.service -n 40 --no-pager')
print("Touch UI service logs on Pi 4B:\n" + stdout.read().decode())

client.close()
