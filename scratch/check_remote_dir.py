#!/usr/bin/env python3
import subprocess

def main():
    print("=== CHECKING PI 4B TARGET DIRECTORY ===")
    cmd = (
        "ssh -o StrictHostKeyChecking=no user@192.168.0.130 "
        "'ssh -o StrictHostKeyChecking=no carson@192.168.0.86 \"cd /home/carson/touch_ui && ls -la\"'"
    )
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print("Code:", res.returncode)
    print("STDOUT:\n", res.stdout)
    print("STDERR:\n", res.stderr)

if __name__ == "__main__":
    main()
