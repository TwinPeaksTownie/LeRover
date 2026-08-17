import paramiko
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("Connecting to Pi 4B (192.168.0.86)...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

print("\n--- 1. Playing ricochet sound on Pi 4B via paplay ---")
stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_shell_ricochet.wav")
print("paplay stderr:", stderr.read().decode())
print("paplay stdout:", stdout.read().decode())

time.sleep(0.5)

print("\n--- 2. Playing ricochet sound on Pi 4B via aplay -D sysdefault ---")
stdin, stdout, stderr = client.exec_command("aplay -D sysdefault /home/carson/mario_sounds/smw_shell_ricochet.wav")
print("aplay stderr:", stderr.read().decode())
print("aplay stdout:", stdout.read().decode())

client.close()
print("Done playing ricochet noise on Pi 4B.")
