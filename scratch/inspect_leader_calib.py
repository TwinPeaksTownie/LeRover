import paramiko
import sys

print("Checking Mac Mini SSH / calibration...")
try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # Let's try connecting to mac mini 192.168.0.2 with username carson or similar
    client.connect('192.168.0.2', username='carson', timeout=3)
    stdin, stdout, stderr = client.exec_command("cat ~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/leader.json 2>/dev/null || find ~ -name '*leader.json' 2>/dev/null")
    print(stdout.read().decode())
    client.close()
except Exception as e:
    print("Direct Mac SSH error:", e)

# Also check from Pi 500
try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('192.168.0.130', username='user', timeout=5)
    stdin, stdout, stderr = client.exec_command("ssh -o StrictHostKeyChecking=no carson@192.168.0.2 'cat ~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/leader.json 2>/dev/null || find ~ -name \"*leader.json\" 2>/dev/null'")
    print("Via Pi 500 to Mac:\n", stdout.read().decode())
    print("Via Pi 500 to Mac ERR:\n", stderr.read().decode())
    client.close()
except Exception as e:
    print("Pi 500 hop error:", e)
