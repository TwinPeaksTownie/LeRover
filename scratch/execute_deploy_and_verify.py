#!/usr/bin/env python3
"""Master deploy and verification script executed on Pi 500.
Syncs pi4b modules to carson@192.168.0.86:/home/carson/touch_ui/,
restarts system service/main.py, inspects processes, and triggers sound playback.
"""

import subprocess
import time
import json
import urllib.request
import os

PI4B_HOST = "carson@192.168.0.86"
PI4B_DIR = "/home/carson/touch_ui"
PI500_SRC = "/home/user/so101/pi4b"
LOG_FILE = "/home/user/deploy_final.log"

def main():
    log = []
    log.append("=== LIVE PI 4B DEPLOYMENT AND VERIFICATION ===")

    # 1. Sync files from Pi 500 to Pi 4B target directory (/home/carson/touch_ui/)
    log.append(f"1. Syncing modules from Pi 500 ({PI500_SRC}) to Pi 4B ({PI4B_HOST}:{PI4B_DIR})...")
    mkdir_cmd = f"ssh -o StrictHostKeyChecking=no {PI4B_HOST} 'mkdir -p {PI4B_DIR}'"
    subprocess.run(mkdir_cmd, shell=True, capture_output=True)

    sync_cmd = f"scp -o StrictHostKeyChecking=no -r {PI500_SRC}/* {PI4B_HOST}:{PI4B_DIR}/"
    res_sync = subprocess.run(sync_cmd, shell=True, capture_output=True, text=True)
    log.append(f"   Sync return code: {res_sync.returncode}")
    if res_sync.stdout:
        log.append(f"   Sync STDOUT: {res_sync.stdout.strip()}")
    if res_sync.stderr:
        log.append(f"   Sync STDERR: {res_sync.stderr.strip()}")

    # 2. Check directory files on Pi 4B
    ls_cmd = f"ssh -o StrictHostKeyChecking=no {PI4B_HOST} 'ls -la {PI4B_DIR}'"
    res_ls = subprocess.run(ls_cmd, shell=True, capture_output=True, text=True)
    log.append(f"\n2. Target files in {PI4B_DIR}:")
    log.append(res_ls.stdout if res_ls.stdout else "(empty or error)")

    # 3. Kill legacy processes and restart service / main.py daemon on Pi 4B
    log.append("\n3. Stopping legacy processes and restarting main.py on Pi 4B...")
    restart_cmd = (
        f"ssh -o StrictHostKeyChecking=no {PI4B_HOST} "
        "\"pkill -9 -f touchscreen_ui.py 2>/dev/null; "
        "pkill -9 -f main.py 2>/dev/null; "
        "sudo systemctl restart touch-ui.service 2>/dev/null || "
        "(cd /home/carson/touch_ui && nohup /home/carson/.venv/bin/python main.py </dev/null >/tmp/touch_ui.log 2>&1 &)\""
    )
    res_restart = subprocess.run(restart_cmd, shell=True, capture_output=True, text=True)
    log.append(f"   Restart command code: {res_restart.returncode}")

    time.sleep(2.5)

    # 4. Verify running processes on Pi 4B
    log.append("\n4. Verifying active processes on Pi 4B...")
    ps_cmd = f"ssh -o StrictHostKeyChecking=no {PI4B_HOST} 'ps aux | grep -E \"main.py|touchscreen_ui\" | grep -v grep'"
    res_ps = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True)
    log.append(f"   Active processes:\n{res_ps.stdout if res_ps.stdout else '   (None found)'}")

    # 5. Trigger live audio playback request to Pi 4B
    log.append("\n5. Triggering sound playback request to http://192.168.0.86:8082/api/play_sound...")
    try:
        req = urllib.request.Request("http://192.168.0.86:8082/api/play_sound", data=json.dumps({"kind": "connect"}).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            log.append(f"   HTTP Response ({resp.status}): {resp.read().decode()}")
    except Exception as ex:
        log.append(f"   HTTP Trigger Error: {ex}")

    output_text = "\n".join(log)
    print(output_text)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(output_text + "\n")

if __name__ == "__main__":
    main()
