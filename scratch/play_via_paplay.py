import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("Connecting to Pi 4B to play smw_shell_ricochet.wav via paplay...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_shell_ricochet.wav")
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
print("Output:", out)
print("Error:", err)

client.close()
print("Physical paplay execution complete.")
