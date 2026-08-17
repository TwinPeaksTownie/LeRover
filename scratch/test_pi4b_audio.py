import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

print("=== Pi 4B Audio Output Devices ===")
stdin, stdout, stderr = client.exec_command("aplay -l")
print(stdout.read().decode())

print("=== Pi 4B PulseAudio Status ===")
stdin, stdout, stderr = client.exec_command("pactl info 2>&1")
print(stdout.read().decode())

print("=== Pi 4B Mario Sounds Directory ===")
stdin, stdout, stderr = client.exec_command("ls -la /home/carson/mario_sounds/")
print(stdout.read().decode())

print("=== Pi 4B Test paplay ===")
stdin, stdout, stderr = client.exec_command("paplay /home/carson/mario_sounds/smw_shell_ricochet.wav 2>&1")
print("paplay stdout/err:", stdout.read().decode())

print("=== Pi 4B Test aplay ===")
stdin, stdout, stderr = client.exec_command("aplay -v /home/carson/mario_sounds/smw_shell_ricochet.wav 2>&1")
print("aplay stdout/err:", stdout.read().decode())

print("=== Pi 4B Test aplay sysdefault ===")
stdin, stdout, stderr = client.exec_command("aplay -D sysdefault /home/carson/mario_sounds/smw_shell_ricochet.wav 2>&1")
print("aplay sysdefault stdout/err:", stdout.read().decode())

client.close()
