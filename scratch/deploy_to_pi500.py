import paramiko
import time
import json
import urllib.request
from pathlib import Path

PI500_IP = "192.168.0.130"
LOCAL_PI500 = Path("i:/aux_servo_interface/pi500")

def deploy():
    print(f"Connecting to Pi 500 @ {PI500_IP}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(PI500_IP, username="user", timeout=10)

    print("Opening SFTP channel...")
    sftp = client.open_sftp()
    
    files_to_upload = [
        "aux_servo_controller.py",
        "telemetry_proxies.py",
        "robot_backend.py",
    ]
    
    for fname in files_to_upload:
        local_path = LOCAL_PI500 / fname
        remote_path = f"/home/user/so101/pi500/{fname}"
        print(f"Uploading {local_path} -> {remote_path}...")
        sftp.put(str(local_path), remote_path)
    
    sftp.close()
    print("Files uploaded successfully.")

    print("Stopping existing processes on Pi 500...")
    client.exec_command("fuser -k 8085/tcp 2>/dev/null; pkill -9 -f 'python.*main.py' 2>/dev/null; fuser -k /dev/ttyACM0 2>/dev/null; sleep 1")
    time.sleep(1)

    print("Starting master daemon on Pi 500 with detached standard streams...")
    start_cmd = "cd /home/user/so101/pi500 && nohup /home/user/so101/.venv/bin/python main.py </dev/null >/tmp/so101_master.log 2>&1 &"
    client.exec_command(start_cmd)
    
    time.sleep(4)

    stdin, stdout, stderr = client.exec_command("cat /tmp/so101_master.log")
    print("\n--- /tmp/so101_master.log ---\n" + stdout.read().decode().strip() + "\n-----------------------------")

    stdin, stdout, stderr = client.exec_command("ps aux | grep main.py | grep -v grep")
    print(f"\nRunning processes:\n{stdout.read().decode().strip()}")

    client.close()

    print("\nVerifying HTTP /api/status endpoint...")
    for i in range(12):
        try:
            req = urllib.request.urlopen(f"http://{PI500_IP}:8085/api/status", timeout=3)
            if req.status == 200:
                data = json.loads(req.read().decode())
                print(f"API /api/status response received (Status: {data.get('status')})")
                print("Motor telemetry snapshot:")
                follower = data.get("follower", {})
                servos = follower.get("servos", {})
                for sid, info in servos.items():
                    print(f"  Motor {sid} ({info.get('name', 'N/A')}): pos={info.get('pos')}, raw={info.get('raw')}, connected={info.get('connected')}, torque={info.get('torque')}")
                print("\nDEPLOYMENT AND LIVE VERIFICATION SUCCEEDED!")
                return True
        except Exception as e:
            print(f"Waiting for API server to respond (attempt {i+1}/12): {e}")
            time.sleep(1)

    return False

if __name__ == "__main__":
    deploy()
