#!/usr/bin/env python3
import subprocess

def main():
    print("Checking live process status on Pi 4B (192.168.0.86) via Pi 500 bridge...")
    cmd = "ssh -o StrictHostKeyChecking=no user@192.168.0.130 'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 carson@192.168.0.86 \"ps aux | grep -E \\\"python|touch|main\\\"; echo === SERVICE STATUS ===; systemctl status touch-ui.service\"'"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print("Return code:", res.returncode)
    print("STDOUT:\n", res.stdout)
    print("STDERR:\n", res.stderr)

if __name__ == "__main__":
    main()
