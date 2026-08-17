import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

# Check PulseAudio process and service status
stdin, stdout, stderr = client.exec_command("ps aux | grep -E '(pulse|touch_ui|server.py)'")
print("=== Running Processes on Pi 4B ===")
print(stdout.read().decode('utf-8', errors='replace'))

# Check pactl info
stdin, stdout, stderr = client.exec_command("pactl info 2>&1")
print("=== pactl info ===")
print(stdout.read().decode('utf-8', errors='replace'))

# Check what happens if we remove ~/.config/pulse to revert to system default
stdin, stdout, stderr = client.exec_command("rm -rf ~/.config/pulse && pulseaudio -k && sleep 1 && pactl info 2>&1")
print("=== Reverted ~/.config/pulse and restarted PulseAudio ===")
print(stdout.read().decode('utf-8', errors='replace'))

# Check touch-ui service status
stdin, stdout, stderr = client.exec_command("echo raspberry | sudo -S systemctl restart touch-ui.service")
stdout.read()

# Test playing a known working sound like smw_coin.wav
stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_coin.wav 2>&1; aplay -D sysdefault /home/carson/mario_sounds/smw_coin.wav 2>&1")
print("=== Test play smw_coin.wav ===")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
