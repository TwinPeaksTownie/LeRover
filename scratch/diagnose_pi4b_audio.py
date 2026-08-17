#!/usr/bin/env python3
"""Diagnostic script for Pi 4B physical audio hardware and service logs.
Executes ALSA tests, verifies mario_sounds assets, and checks touch-ui.service logs.
"""

import subprocess

PI4B = "carson@192.168.0.86"

def run_remote(cmd_str):
    full_cmd = f"ssh -o StrictHostKeyChecking=no user@192.168.0.130 'ssh -o StrictHostKeyChecking=no {PI4B} \"{cmd_str}\"'"
    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return res.stdout.strip(), res.stderr.strip(), res.returncode

def main():
    print("=== PI 4B AUDIO DIAGNOSTICS & ALSA HARDWARE AUDIT ===")

    print("\n1. ALSA Playback Devices (aplay -l):")
    out, err, code = run_remote("aplay -l")
    print(out if out else f"(Code {code}, Err: {err})")

    print("\n2. Audio Assets Directory (/home/carson/mario_sounds/):")
    out, err, code = run_remote("ls -la /home/carson/mario_sounds/")
    print(out if out else f"(Code {code}, Err: {err})")

    print("\n3. Testing Direct Local ALSA Playback on Pi 4B (aplay /home/carson/mario_sounds/smw_coin.wav)...")
    out, err, code = run_remote("aplay /home/carson/mario_sounds/smw_coin.wav")
    print(f"   aplay result (code={code}): stdout='{out}' stderr='{err}'")

    print("\n4. Active Pi 4B Service / Python Processes (ps aux):")
    out, err, code = run_remote("ps aux | grep -E 'main.py|touchscreen_ui' | grep -v grep")
    print(out if out else "   (No active Python server processes found)")

    print("\n5. Service Logs (journalctl -u touch-ui.service -n 20 / cat /tmp/touch_ui.log):")
    out, err, code = run_remote("tail -n 25 /tmp/touch_ui.log 2>/dev/null || journalctl -u touch-ui.service -n 25 --no-pager")
    print(out if out else f"   (Logs unavailable: {err})")

    print("\n=== DIAGNOSTICS COMPLETE ===")

if __name__ == "__main__":
    main()
