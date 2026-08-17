#!/usr/bin/env python3
"""Master deployment and remote control script for Pi 4B.
Deploy pi4b modules to carson@192.168.0.86:/home/carson/touch_ui/,
restart daemon, and trigger live sound playback.
"""

import subprocess
import time
import json
import urllib.request

def main():
    print("=== LIVE PI 4B DEPLOYMENT & SOUND VERIFICATION ===")

    # 1. Sync pi4b directory to Pi 500
    print("1. Uploading pi4b modules to Pi 500...")
    res1 = subprocess.run(["scp", "-o", "StrictHostKeyChecking=no", "-r", "pi4b", "user@192.168.0.130:/home/user/so101/"], capture_output=True, text=True)
    print(f"   Pi 500 code upload: {res1.returncode}")

    # 2. Sync from Pi 500 to Pi 4B target folder (/home/carson/touch_ui/)
    print("2. Syncing from Pi 500 to Pi 4B (carson@192.168.0.86:/home/carson/touch_ui/)...")
    sync_cmd = (
        "ssh -o StrictHostKeyChecking=no user@192.168.0.130 "
        "'ssh -o StrictHostKeyChecking=no carson@192.168.0.86 \"mkdir -p /home/carson/touch_ui\"; "
        "scp -r /home/user/so101/pi4b/* carson@192.168.0.86:/home/carson/touch_ui/'"
    )
    res2 = subprocess.run(sync_cmd, shell=True, capture_output=True, text=True)
    print(f"   Pi 4B file sync code: {res2.returncode}")

    # 3. Kill legacy processes and restart master main.py daemon on Pi 4B
    print("3. Restarting service / main.py daemon on Pi 4B...")
    restart_cmd = (
        "ssh -o StrictHostKeyChecking=no user@192.168.0.130 "
        "'ssh -o StrictHostKeyChecking=no carson@192.168.0.86 "
        "\"pkill -9 -f touchscreen_ui.py 2>/dev/null; "
        "pkill -9 -f main.py 2>/dev/null; "
        "sudo systemctl restart touch-ui.service 2>/dev/null || "
        "(cd /home/carson/touch_ui && nohup /home/carson/.venv/bin/python main.py </dev/null >/tmp/touch_ui.log 2>&1 &)\"'"
    )
    res3 = subprocess.run(restart_cmd, shell=True, capture_output=True, text=True)
    print(f"   Pi 4B service restart code: {res3.returncode}")

    time.sleep(2.0)

    # 4. Trigger audio playback on Pi 4B
    print("4. Triggering live sound playback on Pi 4B (http://192.168.0.86:8082/api/play_sound)...")
    trigger_cmd = (
        "ssh -o StrictHostKeyChecking=no user@192.168.0.130 "
        "'/home/user/so101/.venv/bin/python -c \"import urllib.request, json; "
        "req = urllib.request.Request(\\\"http://192.168.0.86:8082/api/play_sound\\\", data=json.dumps({\\\"kind\\\": \\\"connect\\\"}).encode(), headers={\\\"Content-Type\\\": \\\"application/json\\\"}); "
        "resp = urllib.request.urlopen(req); print(\\\"Trigger result:\\\", resp.read().decode())\"'"
    )
    res4 = subprocess.run(trigger_cmd, shell=True, capture_output=True, text=True)
    print(f"   Sound Trigger code: {res4.returncode} stdout: '{res4.stdout.strip()}' stderr: '{res4.stderr.strip()}'")

    print("=== VERIFICATION COMPLETE ===")

if __name__ == "__main__":
    main()
