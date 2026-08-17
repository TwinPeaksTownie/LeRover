import paramiko
import json
import urllib.request

print("--- Pi 500 Telemetry & Calibration ---")
try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('192.168.0.130', username='user', timeout=5)

    cmds = [
        "cat ~/.cache/huggingface/lerobot/calibration/robots/so_follower/follower.json",
        "ps aux | grep python",
        "find ~ -name '*.json' | grep -E 'follower|leader|calib'"
    ]
    for c in cmds:
        print(f"=== CMD: {c} ===")
        stdin, stdout, stderr = client.exec_command(c)
        print(stdout.read().decode())
        err = stderr.read().decode()
        if err:
            print("ERR:", err)
    client.close()
except Exception as e:
    print("Pi 500 SSH Error:", e)

print("--- Mac Mini API & Calibration ---")
try:
    req = urllib.request.Request("http://192.168.0.2:8086/api/status")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        print("Status 200:", resp.read().decode())
except Exception as e:
    print("Mac Mini HTTP Error:", e)
