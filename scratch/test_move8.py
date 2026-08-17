import urllib.request
import json

url = "http://127.0.0.1:8085/api/nudge_physical"
payload = json.dumps({"id": 8, "direction": "right", "amount": 100}).encode("utf-8")
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

try:
    with urllib.request.urlopen(req, timeout=2) as resp:
        print("MOVE MOTOR 8 RESPONSE:", resp.read().decode())
except Exception as e:
    print("MOVE ERROR:", e)
