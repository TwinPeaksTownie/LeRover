import subprocess
import json

def run_ssh(host, cmd):
    res = subprocess.run(['ssh', '-o', 'StrictHostKeyChecking=no', host, cmd], capture_output=True, text=True)
    return res.stdout.strip(), res.stderr.strip()

def main():
    print("=== Recompiling Pi 500 Manifest ===")
    recompile_cmd = (
        "/home/user/so101/.venv/bin/python -c \""
        "import sys, json; "
        "sys.path.insert(0, '/home/user/so101/pi500'); "
        "from beat_studio import compile_default_choreography; "
        "m_path = '/home/user/so101/library/beat_bandit/manifest.json'; "
        "m = json.load(open(m_path)); "
        "count = 0; "
        "for tid, track in m.items(): "
        "    analysis = track.get('analysis', track); "
        "    duration = float(track.get('duration', analysis.get('duration', 0.0))); "
        "    if duration > 0 and 'beat_times' in analysis: "
        "        choreo = compile_default_choreography(analysis, duration); "
        "        track['choreography'] = choreo; "
        "        count += 1; "
        "        print('Recompiled ' + str(tid) + ' (' + str(track.get('title', '')) + ') -> ' + str(len(choreo['blocks'])) + ' blocks, version ' + str(choreo['version'])); "
        "json.dump(m, open(m_path, 'w'), indent=2); "
        "print('Successfully recompiled ' + str(count) + ' tracks to Version 3.1.0 on Pi 500!'); "
        "\""
    )
    out, err = run_ssh('user@192.168.0.130', recompile_cmd)
    print(out)
    if err:
        print("Error:", err)

    print("\n=== Syncing updated manifest to Pi 4B ===")
    sync_cmd = "scp user@192.168.0.130:/home/user/so101/library/beat_bandit/manifest.json /home/carson/touch_ui/beat_bandit_manifest.json"
    out, err = run_ssh('carson@192.168.0.86', sync_cmd)
    print("Sync complete:", out)

    print("\n=== Verifying API Response for Red Wine Supernova (y9Wxl9Q9lUQ) ===")
    api_out, _ = run_ssh('user@192.168.0.130', 'curl -s "http://127.0.0.1:8085/api/apps/beat_bandit/choreo?track_id=y9Wxl9Q9lUQ"')
    api_data = json.loads(api_out)
    c = api_data.get('choreography', {})
    print("New API Choreo version:", c.get('version'))
    print("New API Total blocks:", len(c.get('blocks', [])))
    print("First 8 Spine moves:")
    for m in c.get('tracks', {}).get('spine_gaze', [])[:8]:
        print("  [" + str(m.get('id')) + "] " + str(m.get('name')) + " (" + str(m.get('pattern')) + " -> " + str(m.get('pose_name')) + ") " + str(m.get('start_sec')) + "s-" + str(m.get('end_sec')) + "s")

if __name__ == '__main__':
    main()
