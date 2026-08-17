#!/usr/bin/env python3
"""Syncs refactored pi4b modules to Pi 4B (192.168.0.86:/home/carson/touch_ui/)
and restarts touch-ui.service / main.py master daemon.
"""

import subprocess
import os

def main():
    print("1. Uploading pi4b modules to Pi 500...")
    res1 = subprocess.run(["scp", "-o", "StrictHostKeyChecking=no", "-r", "pi4b", "user@192.168.0.130:/home/user/so101/"], capture_output=True, text=True)
    print(f"   Upload to Pi 500 code={res1.returncode}")

    print("2. Syncing from Pi 500 to Pi 4B (carson@192.168.0.86:/home/carson/touch_ui/)...")
    cmd2 = "ssh -o StrictHostKeyChecking=no user@192.168.0.130 'scp -r /home/user/so101/pi4b/* carson@192.168.0.86:/home/carson/touch_ui/'"
    res2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
    print(f"   Pi 4B sync code={res2.returncode} stdout='{res2.stdout.strip()}' stderr='{res2.stderr.strip()}'")

    print("3. Restarting touch-ui.service on Pi 4B...")
    cmd3 = "ssh -o StrictHostKeyChecking=no user@192.168.0.130 'ssh -o StrictHostKeyChecking=no carson@192.168.0.86 \"sudo systemctl restart touch-ui.service 2>/dev/null || (pkill -9 -f touchscreen_ui.py; pkill -9 -f main.py; cd /home/carson/touch_ui && nohup python3 main.py </dev/null >/tmp/touch_ui.log 2>&1 &)\"'"
    res3 = subprocess.run(cmd3, shell=True, capture_output=True, text=True)
    print(f"   Pi 4B restart code={res3.returncode} stdout='{res3.stdout.strip()}' stderr='{res3.stderr.strip()}'")

if __name__ == "__main__":
    main()
