import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

def audit_audio(ip, user, pwd=None):
    print(f"========================================")
    print(f"AUDITING AUDIO ON {ip} ({user})")
    print(f"========================================")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if pwd:
        client.connect(ip, username=user, password=pwd, timeout=5)
    else:
        client.connect(ip, username=user, timeout=5)
    
    # Check PulseAudio sinks and volume
    print("\n--- 1. pactl list sinks ---")
    stdin, stdout, stderr = client.exec_command("pactl list sinks 2>&1")
    print(stdout.read().decode('utf-8', errors='replace'))
    
    # Check amixer controls
    print("\n--- 2. amixer scontrols ---")
    stdin, stdout, stderr = client.exec_command("amixer scontrols 2>&1")
    print(stdout.read().decode('utf-8', errors='replace'))
    
    # Check USB devices
    print("\n--- 3. lsusb ---")
    stdin, stdout, stderr = client.exec_command("lsusb 2>&1")
    print(stdout.read().decode('utf-8', errors='replace'))
    
    client.close()

try:
    audit_audio("192.168.0.86", "carson", "raspberry")
except Exception as e:
    print("Pi 4B error:", e)

try:
    audit_audio("192.168.0.130", "user")
except Exception as e:
    print("Pi 500 error:", e)
