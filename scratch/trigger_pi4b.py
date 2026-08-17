#!/usr/bin/env python3
import subprocess

def main():
    print("Sending live audio trigger to Pi 4B over HTTP...")
    cmd = (
        "ssh -o StrictHostKeyChecking=no user@192.168.0.130 "
        "'/home/user/so101/.venv/bin/python -c \"import urllib.request, json; "
        "req = urllib.request.Request(\\\"http://192.168.0.86:8082/api/play_sound\\\", data=json.dumps({\\\"kind\\\": \\\"connect\\\"}).encode(), headers={\\\"Content-Type\\\": \\\"application/json\\\"}); "
        "resp = urllib.request.urlopen(req); print(\\\"HTTP Status:\\\", resp.status, \\\"Body:\\\", resp.read().decode())\"'"
    )
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print("Return Code:", res.returncode)
    print("STDOUT:", res.stdout.strip())
    print("STDERR:", res.stderr.strip())

if __name__ == "__main__":
    main()
