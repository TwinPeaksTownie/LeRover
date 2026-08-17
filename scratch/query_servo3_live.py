import paramiko
import json

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

script = """import json
import urllib.request
from pathlib import Path
from scservo_sdk import PortHandler, PacketHandler

# 1. Calibration file
calib_path = Path.home() / '.cache/huggingface/lerobot/calibration/robots/so_follower/follower.json'
with open(calib_path) as f:
    calib = json.load(f)

s3_calib = calib.get('elbow_flex', {})

# 2. Check live status from API / backend
req = urllib.request.Request('http://127.0.0.1:8085/api/status')
with urllib.request.urlopen(req) as resp:
    status_data = json.loads(resp.read().decode())

s3_api = status_data.get('servos', {}).get('3', {})

print('=== SERVO 3 CALIBRATION (follower.json) ===')
print(json.dumps(s3_calib, indent=2))

print('\\n=== SERVO 3 API TELEMETRY ===')
print(json.dumps(s3_api, indent=2))
"""

sftp = client.open_sftp()
with sftp.file('/tmp/query_s3.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("/home/user/so101/.venv/bin/python /tmp/query_s3.py")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("ERR:\n", err)

# Also let's do a direct hardware read of register 56 (Present_Position) on servo 3
# To do a direct serial read safely without conflict, let's briefly query via a python script that reads register 56
direct_script = """import json
import time
from scservo_sdk import PortHandler, PacketHandler

# Temporarily stop main.py to read directly from serial if needed, or check if main.py is providing it
"""

client.close()
