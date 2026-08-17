import urllib.request
import json
import paramiko

print("--- Querying Pi 500 API ---")
try:
    req = urllib.request.Request("http://192.168.0.130:8085/api/status")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        pi500_data = json.loads(resp.read().decode())
        print("Pi 500 Status / Motors:")
        print(json.dumps(pi500_data.get("motors", pi500_data), indent=2))
except Exception as e:
    print("Pi 500 HTTP Error:", e)

print("\n--- Querying Mac Mini API ---")
try:
    req = urllib.request.Request("http://192.168.0.2:8086/api/telemetry")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        print("Mac Telemetry:", resp.read().decode())
except Exception as e:
    print("Mac Telemetry Error:", e)

try:
    req = urllib.request.Request("http://192.168.0.2:8086/api/calibration")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        print("Mac Calibration:", resp.read().decode())
except Exception as e:
    print("Mac Calibration Error:", e)

try:
    req = urllib.request.Request("http://192.168.0.2:8086/api/status")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        print("Mac Status:", resp.read().decode())
except Exception as e:
    print("Mac Status Error:", e)
