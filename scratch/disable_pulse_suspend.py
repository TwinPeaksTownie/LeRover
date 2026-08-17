import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

# Check PulseAudio config files
stdin, stdout, stderr = client.exec_command("grep -n 'module-suspend-on-idle' /etc/pulse/default.pa ~/.config/pulse/default.pa 2>&1")
print("=== module-suspend-on-idle in config ===")
print(stdout.read().decode('utf-8', errors='replace'))

# Check if ~/.config/pulse exists
stdin, stdout, stderr = client.exec_command("mkdir -p ~/.config/pulse && cp /etc/pulse/default.pa ~/.config/pulse/default.pa && sed -i 's/load-module module-suspend-on-idle/#load-module module-suspend-on-idle/' ~/.config/pulse/default.pa")
stdout.read()

# Restart pulseaudio user service or kill it to reload config
stdin, stdout, stderr = client.exec_command("pulseaudio -k && sleep 1 && pactl info 2>&1")
print("=== PulseAudio restart status ===")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
