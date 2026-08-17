import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

stdin, stdout, stderr = client.exec_command("ps aux | grep -i 'server.py' | grep -v grep")
print("Process line:\n", stdout.read().decode('utf-8', errors='replace'))

# Check environment of touch-ui server process
stdin, stdout, stderr = client.exec_command("cat /proc/$(pgrep -f 'python3 /home/carson/touch_ui/server.py' | head -n 1)/environ | tr '\\0' '\\n'")
print("=== Environ of touch-ui.service ===\n", stdout.read().decode('utf-8', errors='replace'))

# Test running paplay without XDG_RUNTIME_DIR
stdin, stdout, stderr = client.exec_command("env -i HOME=/home/carson USER=carson PATH=/usr/bin:/bin paplay /home/carson/mario_sounds/smw_coin.wav 2>&1")
print("=== paplay without XDG_RUNTIME_DIR ===\n", stdout.read().decode('utf-8', errors='replace'))

# Test running paplay WITH XDG_RUNTIME_DIR
stdin, stdout, stderr = client.exec_command("env -i HOME=/home/carson USER=carson PATH=/usr/bin:/bin XDG_RUNTIME_DIR=/run/user/1000 paplay /home/carson/mario_sounds/smw_coin.wav 2>&1")
print("=== paplay WITH XDG_RUNTIME_DIR ===\n", stdout.read().decode('utf-8', errors='replace'))

client.close()
