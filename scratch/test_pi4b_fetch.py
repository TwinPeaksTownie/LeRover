import urllib.request

try:
    req = urllib.request.urlopen("http://192.168.0.130:8085/api/status", timeout=2)
    print("SUCCESS:", req.read().decode())
except Exception as e:
    print("ERROR:", e)
