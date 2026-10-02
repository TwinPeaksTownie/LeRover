import subprocess
import json

def run_ssh(host, cmd):
    res = subprocess.run(['ssh', '-o', 'StrictHostKeyChecking=no', host, cmd], capture_output=True, text=True)
    return res.stdout.strip()

def main():
    print("\n=== Checking Pi 4B Manifest ===")
    cmd_4b = "cat /home/carson/touch_ui/beat_bandit_manifest.json"
    raw_4b = run_ssh('carson@192.168.0.86', cmd_4b)
    data_4b = json.loads(raw_4b)
    t_4b = data_4b["y9Wxl9Q9lUQ"]
    print("Keys in Pi4B y9Wxl9Q9lUQ:", list(t_4b.keys()))
    if 'choreography' in t_4b:
        c = t_4b['choreography']
        print("Pi4B Choreo version:", c["version"])
        print("Pi4B Spine moves count:", len(c["tracks"]["spine_gaze"]))
        for m in c["tracks"]["spine_gaze"][:5]:
            print("  ", m["name"], m["pose_name"])

    print("\n=== Testing API Endpoint /api/apps/beat_bandit/choreo?track_id=y9Wxl9Q9lUQ ===")
    api_out = run_ssh('carson@192.168.0.86', 'curl -s "http://127.0.0.1:8082/api/apps/beat_bandit/choreo?track_id=y9Wxl9Q9lUQ"')
    if api_out:
        try:
            api_data = json.loads(api_out)
            choreo_api = api_data["choreography"]
            print("API Choreo version:", choreo_api["version"])
            print("API Spine moves count:", len(choreo_api["tracks"]["spine_gaze"]))
            for m in choreo_api["tracks"]["spine_gaze"][:10]:
                print("  ", m["name"], m["pose_name"], m["pattern"], m["start_sec"], '->', m["end_sec"])
        except Exception as e:
            print("API response parse error:", e)

if __name__ == '__main__':
    main()
