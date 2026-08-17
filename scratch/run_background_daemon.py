import subprocess
import sys
import time

cmd = [
    "ssh",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=30",
    "user@192.168.0.130",
    "pkill -9 -f main.py 2>/dev/null || true; sleep 1; cd /home/user/so101/pi500 && exec /home/user/so101/.venv/bin/python -u main.py"
]

proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
print(f"Master daemon process launched with PID {proc.pid}")

# Wait for startup confirmation
for _ in range(30):
    line = proc.stdout.readline()
    if line:
        print(line.strip())
        if "Master API Web Server successfully bound" in line:
            print(">>> DAEMON ONLINE <<<")
            break
    time.sleep(0.2)
