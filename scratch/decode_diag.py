#!/usr/bin/env python3
import subprocess
import base64
import sys

def main():
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "user@192.168.0.130", "cat /home/user/diag_b64.txt"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    b64_str = res.stdout.strip()
    if b64_str:
        decoded = base64.b64decode(b64_str).decode("utf-8", errors="replace")
        print("=== PI 4B DIAGNOSTIC LOG REPORT ===")
        print(decoded)
    else:
        print("No base64 log data returned. Err:", res.stderr)

if __name__ == "__main__":
    main()
