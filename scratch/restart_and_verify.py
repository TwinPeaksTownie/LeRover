import paramiko
import time
import requests

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=10)

# Clean up scratch scripts in /tmp
client.exec_command('rm -f /tmp/calibrate_s7.py /tmp/test_offset*.py /tmp/read_live*.py /tmp/read_s7_registers.py')

# Restart main.py master daemon
client.exec_command('pkill -9 -f main.py 2>/dev/null || true; sleep 1; nohup bash -c "exec /home/user/so101/.venv/bin/python -u /home/user/so101/pi500/main.py" </dev/null >/tmp/so101_master.log 2>&1 &')
time.sleep(3)

# Query API status from Pi 500
stdin, stdout, stderr = client.exec_command('curl -s http://127.0.0.1:8085/api/status')
status_json = stdout.read().decode()
print("PI 500 /api/status RESPONSE:")
print(status_json)

client.close()
