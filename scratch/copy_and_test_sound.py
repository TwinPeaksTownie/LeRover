import os
import paramiko
import urllib.request
import json
import time

local_file = r"C:\Users\carso\Downloads\smw_shell_ricochet.wav"
print(f"Checking local file: {local_file}")
if os.path.exists(local_file):
    print(f"Found local file ({os.path.getsize(local_file)} bytes)")
else:
    print("WARNING: Local file not found in Downloads!")

print("\n--- Connecting to Pi 4B (192.168.0.86) ---")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.86', username='carson', password='raspberry', timeout=5)

sftp = client.open_sftp()
if os.path.exists(local_file):
    sftp.put(local_file, "/home/carson/mario_sounds/smw_shell_ricochet.wav")
    print("Uploaded to /home/carson/mario_sounds/smw_shell_ricochet.wav")
    sftp.put(local_file, "/home/carson/mario_sounds/shell_ricochet.wav")
    print("Uploaded to /home/carson/mario_sounds/shell_ricochet.wav")
sftp.close()

# Test physical audio playback directly on Pi 4B via paplay & aplay
print("\n--- Testing direct physical playback on Pi 4B ---")
stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_shell_ricochet.wav 2>&1 || aplay -D sysdefault /home/carson/mario_sounds/smw_shell_ricochet.wav 2>&1")
out = stdout.read().decode()
print("Direct command output:\n", out)

client.close()

# Test playback via HTTP API endpoint on Pi 4B
print("\n--- Testing HTTP API trigger to Pi 4B ---")
req = urllib.request.Request(
    "http://192.168.0.86:8082/api/play_sound",
    data=json.dumps({"kind": "smw_shell_ricochet"}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=3.0) as resp:
    print("HTTP API status:", resp.status, resp.read().decode())
