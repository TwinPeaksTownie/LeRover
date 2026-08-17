import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.130", username="user", timeout=5)

stdin, stdout, stderr = client.exec_command("export PYTHONUNBUFFERED=1; timeout 10 /home/user/so101/.venv/bin/python -u /home/user/so101/pi500/main.py")

print("STDOUT:\n" + stdout.read().decode())
print("STDERR:\n" + stderr.read().decode())

client.close()
