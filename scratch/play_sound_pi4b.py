#!/usr/bin/env python3
"""Script to trigger live audio playback on the Pi 4B (192.168.0.86:8082).
1. Sends sound asset request ('connect') over HTTP JSON.
2. Sends raw PCM WAV bytes over HTTP audio/wav.
"""

import urllib.request
import json
import struct
import math

PI4B_URL = "http://192.168.0.86:8082/api/play_sound"

def main():
    print("1. Sending 'connect' sound asset request to Pi 4B...")
    payload = json.dumps({"kind": "connect"}).encode("utf-8")
    req = urllib.request.Request(PI4B_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            print(f"   Response (HTTP {resp.status}): {resp.read().decode()}")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n2. Generating PCM WAV tone chime and streaming raw WAV bytes to Pi 4B...")
    sr = 22050
    buf = bytearray()
    tones = [(523.25, 0.15, 0.3), (659.25, 0.15, 0.3), (784.00, 0.35, 0.4)]
    for freq, duration, vol in tones:
        n_samples = int(sr * duration)
        for i in range(n_samples):
            t = i / sr
            val = int(vol * 32767 * math.sin(2 * math.pi * freq * t))
            buf.extend(struct.pack('<h', val))
    h = bytearray(b"RIFF")
    h.extend(struct.pack("<I", 36 + len(buf)))
    h.extend(b"WAVEfmt ")
    h.extend(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
    h.extend(b"data")
    h.extend(struct.pack("<I", len(buf)))
    raw_wav = bytes(h + buf)

    req2 = urllib.request.Request(PI4B_URL, data=raw_wav, headers={"Content-Type": "audio/wav"})
    try:
        with urllib.request.urlopen(req2, timeout=5.0) as resp:
            print(f"   Response (HTTP {resp.status}): {resp.read().decode()}")
    except Exception as e:
        print(f"   Error: {e}")

if __name__ == "__main__":
    main()
