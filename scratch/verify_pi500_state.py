import paramiko
import hashlib
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.130", username="user", timeout=5)

files = ["robot_backend.py", "api_server.py", "pokeball_app.py"]

for f in files:
    with open(f"i:/aux_servo_interface/pi500/{f}", "rb") as local_f:
        local_md5 = hashlib.md5(local_f.read()).hexdigest()
    
    stdin, stdout, stderr = client.exec_command(f"md5sum /home/user/so101/pi500/{f}")
    remote_md5 = stdout.read().decode().split()[0]
    
    match = (local_md5 == remote_md5)
    print(f"File {f}: match={match} (local={local_md5}, remote={remote_md5})")

# Check running process on Pi 500
stdin, stdout, stderr = client.exec_command("ps aux | grep -i 'python.*main.py' | grep -v grep")
print("\nRunning master process on Pi 500:\n", stdout.read().decode())

# Check recent logs on Pi 500
stdin, stdout, stderr = client.exec_command("tail -n 30 /tmp/so101_master.log")
print("\nRecent master logs on Pi 500:\n", stdout.read().decode())

client.close()
