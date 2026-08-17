import paramiko
import time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

stdin, stdout, stderr = client.exec_command('pkill -9 -f main.py 2>/dev/null || true; sleep 1; nohup /home/user/so101/.venv/bin/python -u /home/user/so101/pi500/main.py > /tmp/so101_master.log 2>&1 &')
time.sleep(3)

stdin, stdout, stderr = client.exec_command('ps aux | grep main.py')
print("PROCESS:")
print(stdout.read().decode())

time.sleep(2)
stdin, stdout, stderr = client.exec_command('curl -s http://127.0.0.1:8085/api/status')
print("API STATUS:")
print(stdout.read().decode())

client.close()
