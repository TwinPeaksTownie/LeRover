import urllib.request
import json
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

# Move to right limit (+165°)
print("1. Stepping to 165°...")
for _ in range(5):
    req = urllib.request.Request(
        "http://192.168.0.130:8085/api/pedestal_step",
        data=json.dumps({"direction": "right"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        res = json.loads(resp.read().decode())
    time.sleep(0.7)

print("Arrived at right limit:", res)

print("\n2. Stepping RIGHT beyond range (should reject move and play shell ricochet)...")
req = urllib.request.Request(
    "http://192.168.0.130:8085/api/pedestal_step",
    data=json.dumps({"direction": "right"}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=3.0) as resp:
    res = json.loads(resp.read().decode())
print("Bumper collision result:", res)

time.sleep(1.0)

print("\n3. Centering pedestal back to 0°...")
for _ in range(4):
    req = urllib.request.Request(
        "http://192.168.0.130:8085/api/pedestal_step",
        data=json.dumps({"direction": "left"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        res = json.loads(resp.read().decode())
    time.sleep(0.7)

print("Centered pedestal:", res)
