import paramiko

def check_pi(ip, user, pwd=None):
    print(f"=== Checking {ip} ({user}) ===")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if pwd:
        client.connect(ip, username=user, password=pwd, timeout=5)
    else:
        client.connect(ip, username=user, timeout=5)
    
    # 1. Check audio devices
    stdin, stdout, stderr = client.exec_command("aplay -l; aplay -L; pactl info 2>&1")
    print("--- Audio output info ---")
    print(stdout.read().decode())
    
    # 2. Check if smw_shell_ricochet exists
    stdin, stdout, stderr = client.exec_command("ls -la /home/carson/mario_sounds/ 2>&1 || ls -la /home/user/ 2>&1")
    print("--- Directory listing ---")
    print(stdout.read().decode())
    
    # 3. Test playing the sound via aplay and paplay
    print("--- Testing audio playback ---")
    cmd = "paplay /home/carson/mario_sounds/smw_shell_ricochet.wav 2>&1 || aplay -v /home/carson/mario_sounds/smw_shell_ricochet.wav 2>&1"
    stdin, stdout, stderr = client.exec_command(cmd)
    print("Test sound command output:", stdout.read().decode(), stderr.read().decode())
    
    client.close()

try:
    check_pi("192.168.0.86", "carson", "raspberry")
except Exception as e:
    print("Pi 4B error:", e)

try:
    check_pi("192.168.0.130", "user")
except Exception as e:
    print("Pi 500 error:", e)
