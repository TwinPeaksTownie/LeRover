import subprocess
import json

def run_ssh(host, cmd):
    res = subprocess.run(['ssh', '-o', 'StrictHostKeyChecking=no', host, cmd], capture_output=True, text=True)
    return res.stdout.strip()

def main():
    print("=== Checking Pi 500 Manifest ===")
    cmd_500 = "cat /home/user/so101/library/beat_bandit/manifest.json"
    raw_500 = run_ssh('user@192.168.0.130', cmd_500)
    data_500 = json.loads(raw_500)
    t_500 = data_500.get('y9Wxl9Q9lUQ', {})
    print("Keys in Pi500 y9Wxl9Q9lUQ:", list(t_500.keys()))
    if 'choreography' in t_500:
        c = t_500['choreography']
        print("Pi500 Choreo version:", c.get('version'))
        print("Pi500 Spine moves count:", len(c.get('tracks', {}).get('spine_gaze', [])))
        for m in c.get('tracks', {}).get('spine_gaze', [])[:5]:
            print("  ", m.get('name'), m.get('pose_name'))

    print("\n=== Checking Pi 4B Manifest ===")
    cmd_4b = "cat /home/carson/touch_ui/beat_bandit_manifest.json"
    raw_4b = run_ssh('carson@192.168.0.86', cmd_4b)
    data_4b = json.loads(raw_4b)
    t_4b = data_4b.get('y9Wxl9Q9lUQ', {})
    print("Keys in Pi4B y9Wxl9Q9lUQ:", list(t_4b.keys()))
    if 'choreography' in t_4b:
        c = t_4b['choreography']
        print("Pi4B Choreo version:", c.get('version'))
        print("Pi4B Spine moves count:", len(c.get('tracks', {}).get('spine_gaze', [])))
        for m in c.get('tracks', {}).get('spine_gaze', [])[:5]:
            print("  ", m.get('name'), m.get('pose_name'))

    print("\n=== Testing API Endpoint /api/apps/beat_bandit/choreo?track_id=y9Wxl9Q9lUQ ===")
    api_out = run_ssh('user@192.168.0.130', 'curl -s "http://127.0.0.1:8085/api/apps/beat_bandit/choreo?track_id=y9Wxl9Q9lUQ"')
    api_data = json.loads(api_out)
    choreo_api = api_data.get('choreography', {})
    print("API Choreo version:", choreo_api.get('version'))
    print("API Spine moves count:", len(choreo_api.get('tracks', {}).get('spine_gaze', [])))
    for m in choreo_api.get('tracks', {}).get('spine_gaze', [])[:10]:
        print("  ", m.get('name'), m.get('pose_name'), m.get('pattern'), m.get('start_sec'), '->', m.get('end_sec'))

if __name__ == '__main__':
    main()
