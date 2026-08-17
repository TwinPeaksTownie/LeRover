#!/usr/bin/env python3
"""Helper script executed by Touch UI to restart the Pi 500 Master Daemon cleanly."""
import subprocess

def main():
    cmd = (
        "ssh -f -n -o StrictHostKeyChecking=no -o ConnectTimeout=5 "
        "user@192.168.0.130 \"fuser -k 8085/tcp; sleep 1; "
        "cd /home/user/so101/pi500 && nohup /home/user/so101/.venv/bin/python main.py </dev/null >/tmp/so101_master.log 2>&1 &\""
    )
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
    print(f"Master daemon launch output: {res.stdout.strip()} err: {res.stderr.strip()}")

if __name__ == "__main__":
    main()
