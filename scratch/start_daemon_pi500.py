import paramiko
import time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.130", username="user", timeout=15)

cmd = "pkill -9 -f main.py 2>/dev/null || true; sleep 1; cd /home/user/so101/pi500 && setsid /home/user/so101/.venv/bin/python -u main.py </dev/null >/tmp/so101_master.log 2>&1 &"
client.exec_command(cmd)
time.sleep(2)
client.close()

# Verify
client2 = paramiko.SSHClient()
client2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client2.connect("192.168.0.130", username="user", timeout=15)
_, stdout, _ = client2.exec_command("ps aux | grep main.py; head -n 15 /tmp/so101_master.log")
print(stdout.read().decode())
client2.close()
