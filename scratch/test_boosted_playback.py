import paramiko
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

stdin, stdout, stderr = client.exec_command("pactl list sinks | grep -E '(Name|State|Volume|Mute)'")
print("=== PulseAudio Sinks State ===")
print(stdout.read().decode('utf-8', errors='replace'))

print("=== Playing boosted smw_shell_ricochet.wav now via paplay ===")
stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_shell_ricochet.wav")
stdout.read()
time.sleep(0.5)

print("=== Playing second time ===")
stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_shell_ricochet.wav")
stdout.read()

client.close()
