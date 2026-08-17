import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.130", username="user", timeout=10)

cmd = """
echo "=== pyvenv.cfg ==="
cat /home/user/so101/.venv/pyvenv.cfg
echo "=== check lerobot in python3.12 vs python3.11 ==="
/home/user/so101/.venv/bin/python --version
/home/user/so101/.venv/bin/python -c "import sys; print(sys.path)"
"""

stdin, stdout, stderr = client.exec_command(cmd)
print(stdout.read().decode())
print(stderr.read().decode())
client.close()
