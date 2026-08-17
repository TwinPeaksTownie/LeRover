#!/usr/bin/env python3
import subprocess
import time

def main():
    print("=== DIRECT PI 4B CODE DEPLOY & SERVICE RESTART ===")
    
    # 1. Sync pi4b modules from Pi 500 to Pi 4B (/home/carson/touch_ui/)
    print("[1] Syncing pi4b modules to carson@192.168.0.86:/home/carson/touch_ui/...")
    cmd1 = "ssh -o StrictHostKeyChecking=no carson@192.168.0.86 'mkdir -p /home/carson/touch_ui'; scp -o StrictHostKeyChecking=no -r /home/user/so101/pi4b/* carson@192.168.0.86:/home/carson/touch_ui/"
    r1 = subprocess.run(cmd1, shell=True, capture_output=True, text=True)
    print("    Sync code:", r1.returncode)
    print("    Sync stdout:", r1.stdout.strip())
    print("    Sync stderr:", r1.stderr.strip())

    # 2. Check files in /home/carson/touch_ui/
    print("\n[2] Checking files in /home/carson/touch_ui/...")
    cmd2 = "ssh -o StrictHostKeyChecking=no carson@192.168.0.86 'ls -la /home/carson/touch_ui/'"
    r2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
    print(r2.stdout)

    # 3. Kill legacy touchscreen_ui.py / main.py processes on Pi 4B and restart touch-ui.service / main.py
    print("\n[3] Killing legacy processes and restarting main.py / touch-ui.service...")
    cmd3 = (
        "ssh -o StrictHostKeyChecking=no carson@192.168.0.86 "
        "\"pkill -9 -f touchscreen_ui.py 2>/dev/null; "
        "pkill -9 -f main.py 2>/dev/null; "
        "sudo systemctl restart touch-ui.service 2>/dev/null || "
        "(cd /home/carson/touch_ui && nohup /home/carson/.venv/bin/python main.py </dev/null >/tmp/touch_ui.log 2>&1 &)\""
    )
    r3 = subprocess.run(cmd3, shell=True, capture_output=True, text=True)
    print("    Restart code:", r3.returncode)
    print("    Restart stdout:", r3.stdout.strip())
    print("    Restart stderr:", r3.stderr.strip())

    time.sleep(2.0)

    # 4. Verify running processes on Pi 4B
    print("\n[4] Active processes on Pi 4B:")
    cmd4 = "ssh -o StrictHostKeyChecking=no carson@192.168.0.86 'ps aux | grep -E \"main.py|touchscreen_ui\" | grep -v grep'"
    r4 = subprocess.run(cmd4, shell=True, capture_output=True, text=True)
    print(r4.stdout if r4.stdout else "    (No matching processes found)")

if __name__ == "__main__":
    main()
