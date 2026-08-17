#!/usr/bin/env python3
import subprocess
import os

def main():
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "user@192.168.0.130", "/home/user/so101/.venv/bin/python /home/user/read_log.py"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_out.txt")
    with open(out_file, "w") as f:
        f.write(res.stdout + "\n" + res.stderr)
    print("Wrote output to", out_file)

if __name__ == "__main__":
    main()
