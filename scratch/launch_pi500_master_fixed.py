import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.130", username="user", timeout=15)

cmd = """
fuser -k 8085/tcp || true
pkill -9 -f main.py || true
sleep 1
cd /home/user/so101/pi500
nohup /home/user/so101/.venv/bin/python -u /home/user/so101/pi500/main.py </dev/null > /tmp/so101_master.log 2>&1 &
sleep 3
cat /tmp/so101_master.log
echo "=== PS AUX ==="
ps aux | grep main.py
"""

stdin, stdout, stderr = client.exec_command(cmd)
print(stdout.read().decode())
print(stderr.read().decode())
client.close()
