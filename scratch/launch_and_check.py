import paramiko
import time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

# Kill any existing main.py or fuser on /dev/ttyACM0
client.exec_command('pkill -9 -f main.py; fuser -k /dev/ttyACM0')
time.sleep(1)

# Start main.py in background via nohup and disown
transport = client.get_transport()
channel = transport.open_session()
channel.exec_command('nohup /home/user/so101/.venv/bin/python -u /home/user/so101/pi500/main.py </dev/null >/tmp/so101_master.log 2>&1 &')
time.sleep(3)

stdin, stdout, stderr = client.exec_command('ps aux | grep main.py')
print("PROCESSES:")
print(stdout.read().decode())

stdin, stdout, stderr = client.exec_command('curl -s http://127.0.0.1:8085/api/status')
print("API STATUS:")
print(stdout.read().decode())

client.close()
