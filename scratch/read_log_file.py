#!/usr/bin/env python3
import subprocess
import os

def main():
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "user@192.168.0.130", "cat /home/user/deploy_out.log"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_out.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(res.stdout + "\n" + res.stderr)
    print("Log size:", len(res.stdout))
    print(res.stdout)

if __name__ == "__main__":
    main()
