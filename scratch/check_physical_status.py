import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

script = """import json
import urllib.request
from pathlib import Path

# Query the raw present position of all follower motors from backend
# The backend status or bus present position
import urllib.request
req = urllib.request.Request('http://127.0.0.1:8085/api/status')
with urllib.request.urlopen(req) as resp:
    status_data = json.loads(resp.read().decode())

print(json.dumps(status_data, indent=2))
"""

sftp = client.open_sftp()
with sftp.file('/tmp/check_raw_pos.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("/home/user/so101/.venv/bin/python /tmp/check_raw_pos.py")
print(stdout.read().decode())

client.close()
