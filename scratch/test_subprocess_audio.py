import paramiko
import sys
sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

py_code = """
import subprocess

wav = "/home/carson/mario_sounds/smw_shell_ricochet.wav"

res1 = subprocess.run(["aplay", "-q", wav], capture_output=True)
print("aplay -q returncode:", res1.returncode, "stderr:", res1.stderr.decode())

res2 = subprocess.run(["paplay", wav], capture_output=True)
print("paplay returncode:", res2.returncode, "stderr:", res2.stderr.decode())

res3 = subprocess.run(["aplay", "-D", "sysdefault", "-q", wav], capture_output=True)
print("aplay -D sysdefault -q returncode:", res3.returncode, "stderr:", res3.stderr.decode())
"""

stdin, stdout, stderr = client.exec_command(f"python3 -c '{py_code}'")
print(stdout.read().decode('utf-8', errors='replace'))
print(stderr.read().decode('utf-8', errors='replace'))

client.close()
