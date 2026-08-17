import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.130", username="user", timeout=10)

cmd = """
for py in /usr/bin/python3 /home/user/Claude-to-Speech/venv/bin/python /home/user/reachy/venv/bin/python /home/user/reachy/venv-choreography/bin/python; do
  echo "--- Testing $py ---"
  $py -c "import lerobot; print(lerobot.__file__)" 2>&1
done
echo "--- Finding lerobot directories ---"
find /home/user -name "lerobot" 2>/dev/null
find /home/user -name "*venv*" 2>/dev/null
"""

stdin, stdout, stderr = client.exec_command(cmd)
print(stdout.read().decode())
print(stderr.read().decode())
client.close()
