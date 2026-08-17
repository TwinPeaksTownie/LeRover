import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.130', username='user', timeout=5)

script = """import json
import zmq
import time
import urllib.request
from pathlib import Path

calib_path = Path.home() / '.cache/huggingface/lerobot/calibration/robots/so_follower/follower.json'
with open(calib_path) as f:
    follower_calib = json.load(f)

req = urllib.request.Request('http://127.0.0.1:8085/api/status')
with urllib.request.urlopen(req) as resp:
    status_data = json.loads(resp.read().decode())

servos = status_data.get('servos', {})

print('=== FOLLOWER CURRENT POSITIONS & CALIBRATION ===')
for sid_str, data in sorted(servos.items(), key=lambda x: int(x[0])):
    sid = int(sid_str)
    if sid <= 6:
        name = data.get('name')
        cal = follower_calib.get(name, {})
        rmin = cal.get('range_min')
        rmax = cal.get('range_max')
        range_span = rmax - rmin if (rmax and rmin) else 0
        norm_val = data.get('raw')
        
        if norm_val is not None:
            if name == 'gripper':
                calc_tick = int((norm_val / 100.0) * range_span + rmin)
                pct = norm_val
            else:
                calc_tick = int(((norm_val + 100.0) / 200.0) * range_span + rmin)
                pct = (norm_val + 100.0) / 2.0
            offset_val = cal.get('homing_offset')
            print(f'Motor {sid} ({name:14s}): Norm={norm_val:7.2f}% ({pct:5.1f}% span) | CalcTicks={calc_tick:4d} | Range=[{rmin:4d}..{rmax:4d}] (span={range_span:4d}) | HomingOffset={offset_val}')
        else:
            print(f'Motor {sid} ({name:14s}): Norm=None | Range=[{rmin:4d}..{rmax:4d}]')

try:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PULL)
    sock.connect('tcp://127.0.0.1:5556')
    sock.setsockopt(zmq.RCVTIMEO, 500)
    obs = sock.recv_string()
    print('\\nObservation socket 5556 payload:', obs)
    sock.close()
    ctx.term()
except Exception as e:
    print('\\nObservation socket read:', e)
"""

sftp = client.open_sftp()
with sftp.file('/tmp/check_arm.py', 'w') as f:
    f.write(script)
sftp.close()

stdin, stdout, stderr = client.exec_command("/home/user/so101/.venv/bin/python /tmp/check_arm.py")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("ERR:\n", err)

client.close()
