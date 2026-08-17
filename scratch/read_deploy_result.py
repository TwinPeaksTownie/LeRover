#!/usr/bin/env python3
import subprocess
import os

def main():
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "user@192.168.0.130", "cat /home/user/deploy_log.txt"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    report_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_report.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(res.stdout + "\n" + res.stderr)
    print("Report written to:", report_file)
    print(res.stdout)

if __name__ == "__main__":
    main()
