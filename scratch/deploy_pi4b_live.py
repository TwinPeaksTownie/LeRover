#!/usr/bin/env python3
"""Live deployment script for Pi 4B Touch UI and Media Gateway.
Uploads refactored pi4b/ modules to Pi 4B (192.168.0.86:/home/carson/touch_ui/) via Pi 500 bridge
and restarts touch-ui.service / main.py.
"""

import subprocess
import sys
import time

def main():
    print("=== LIVE PI 4B DEPLOYMENT & RESTART ===")
    
    # 1. Upload local pi4b directory to Pi 500 staging
    print("1. Uploading pi4b modules to Pi 500 staging (/tmp/pi4b_staging)...")
    res1 = subprocess.run(["scp", "-o", "StrictHostKeyChecking=no", "-r", "pi4b", "user@192.168.0.130:/tmp/pi4b_staging"], capture_output=True, text=True)
    print(f"   Upload to Pi 500 code: {res1.returncode}")

    # 2. Sync staging files from Pi 500 to Pi 4B target directory (/home/carson/touch_ui/)
    print("2. Syncing staging files from Pi 500 to Pi 4B (carson@192.168.0.86:/home/carson/touch_ui/)...")
    cmd2 = (
        "ssh -o StrictHostKeyChecking=no user@192.168.0.130 "
        "'ssh -o StrictHostKeyChecking=no carson@192.168.0.86 \"mkdir -p /home/carson/touch_ui\"; "
        "scp -r /tmp/pi4b_staging/* carson@192.168.0.86:/home/carson/touch_ui/'"
    )
    res2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
    print(f"   Sync to Pi 4B code: {res2.returncode}")
    if res2.stdout:
        print("   Sync STDOUT:", res2.stdout.strip())
    if res2.stderr:
        print("   Sync STDERR:", res2.stderr.strip())

    # 3. Kill legacy processes and restart touch-ui.service / main.py on Pi 4B
    print("3. Restarting service / main.py on Pi 4B...")
    cmd3 = (
        "ssh -o StrictHostKeyChecking=no user@192.168.0.130 "
        "'ssh -o StrictHostKeyChecking=no carson@192.168.0.86 "
        "\"pkill -9 -f touchscreen_ui.py 2>/dev/null; "
        "pkill -9 -f main.py 2>/dev/null; "
        "sudo systemctl restart touch-ui.service 2>/dev/null || "
        "(cd /home/carson/touch_ui && nohup /home/carson/.venv/bin/python main.py </dev/null >/tmp/touch_ui.log 2>&1 &)\"'"
    )
    res3 = subprocess.run(cmd3, shell=True, capture_output=True, text=True)
    print(f"   Restart command code: {res3.returncode}")
    if res3.stdout:
        print("   Restart STDOUT:", res3.stdout.strip())
    if res3.stderr:
        print("   Restart STDERR:", res3.stderr.strip())

    # 4. Sleep 2s and inspect running processes on Pi 4B
    time.sleep(2.0)
    print("\n4. Verifying live running processes on Pi 4B...")
    cmd4 = (
        "ssh -o StrictHostKeyChecking=no user@192.168.0.130 "
        "'ssh -o StrictHostKeyChecking=no carson@192.168.0.86 \"ps aux | grep -E \\\"main.py|touchscreen_ui\\\" | grep -v grep\"'"
    )
    res4 = subprocess.run(cmd4, shell=True, capture_output=True, text=True)
    print(f"   Live Processes (code={res4.returncode}):")
    print(res4.stdout if res4.stdout else "   (No matching process output)")

    print("=== DEPLOYMENT COMPLETE ===")

if __name__ == "__main__":
    main()
