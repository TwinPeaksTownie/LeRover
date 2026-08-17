import paramiko
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

print("Playing smw_shell_ricochet.wav via paplay on Pi 4B (192.168.0.86)...")
stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_shell_ricochet.wav")
stdout.read()
time.sleep(0.6)

print("Playing second ricochet...")
stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_shell_ricochet.wav")
stdout.read()

client.close()
print("Direct playback via SSH complete.")
