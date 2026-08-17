#!/usr/bin/env python3
import subprocess
import os

def main():
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "user@192.168.0.130", "cat /home/user/pi4b_status.txt"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print("=== PI 4B STATUS REPORT FROM PI 500 ===")
    print(res.stdout)
    if res.stderr:
        print("STDERR:", res.stderr)

    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi4b_status.log")
    with open(out_file, "w") as f:
        f.write(res.stdout + "\n" + res.stderr)

if __name__ == "__main__":
    main()
