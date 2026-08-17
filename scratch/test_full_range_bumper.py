import urllib.request
import json
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        return json.loads(resp.read().decode())

def get_json(url):
    with urllib.request.urlopen(url, timeout=3.0) as resp:
        return json.loads(resp.read().decode())

print("=== 1. Live Servo 7 Status ===")
status = get_json("http://192.168.0.130:8085/api/status")
s7 = status.get("servos", {}).get("7", {})
print(f"Current Servo 7: pos={s7.get('pos')}, angle={s7.get('angle')}°")

print("\n=== 2. Stepping to Right Limit (+165°) ===")
for i in range(5):
    res = post_json("http://192.168.0.130:8085/api/pedestal_step", {"direction": "right"})
    print(f"Step Right {i+1}: moved={res.get('moved')}, angle={res.get('target_angle')}°, at_limit={res.get('at_limit')}, msg='{res.get('message')}'")
    time.sleep(0.7)
    if res.get('at_limit') and not res.get('moved'):
        print(">>> Hard Right Limit Hit! <<<")
        break

print("\n=== 3. Attempting to rotate beyond right limit (+165° -> step right again) ===")
res = post_json("http://192.168.0.130:8085/api/pedestal_step", {"direction": "right"})
print(f"Attempt beyond limit result: moved={res.get('moved')}, at_limit={res.get('at_limit')}, msg='{res.get('message')}'")

time.sleep(1.0)

print("\n=== 4. Stepping to Left Limit (-165°) ===")
for i in range(10):
    res = post_json("http://192.168.0.130:8085/api/pedestal_step", {"direction": "left"})
    time.sleep(0.7)
    if res.get('at_limit') and not res.get('moved'):
        print(f">>> Hard Left Limit Hit on step {i+1}: moved={res.get('moved')}, angle={res.get('target_angle')}°, msg='{res.get('message')}' <<<")
        break

print("\n=== 5. Attempting to rotate beyond left limit (-165° -> step left again) ===")
res = post_json("http://192.168.0.130:8085/api/pedestal_step", {"direction": "left"})
print(f"Attempt beyond limit result: moved={res.get('moved')}, at_limit={res.get('at_limit')}, msg='{res.get('message')}'")

time.sleep(1.0)

print("\n=== 6. Returning to Center (0°) ===")
for i in range(4):
    res = post_json("http://192.168.0.130:8085/api/pedestal_step", {"direction": "right"})
    time.sleep(0.7)

status = get_json("http://192.168.0.130:8085/api/status")
s7 = status.get("servos", {}).get("7", {})
print(f"Final Servo 7: pos={s7.get('pos')}, angle={s7.get('angle')}°")
