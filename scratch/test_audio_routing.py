import paramiko
import sys
sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

# Test 1: Run python snippet as systemd would or via ssh to see where aplay outputs sound
print("=== Testing audio command variants ===")
tests = [
    "aplay -q /home/carson/mario_sounds/smw_shell_ricochet.wav",
    "aplay -D sysdefault /home/carson/mario_sounds/smw_shell_ricochet.wav",
    "paplay /home/carson/mario_sounds/smw_shell_ricochet.wav",
    "aplay -D plughw:4,0 /home/carson/mario_sounds/smw_shell_ricochet.wav"
]

for cmd in tests:
    stdin, stdout, stderr = client.exec_command(f"{cmd} 2>&1")
    out = stdout.read().decode('utf-8', errors='replace')
    print(f"CMD: {cmd}\nRESULT: {out}\n")

# Check ALSA configuration files on Pi 4B
print("=== ALSA / Pulse config on Pi 4B ===")
stdin, stdout, stderr = client.exec_command("cat /etc/asound.conf ~/.asoundrc 2>&1")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
