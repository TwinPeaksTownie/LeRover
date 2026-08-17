#!/usr/bin/env python3
"""Verification test script for Pi 4B Audio Gateway.
1. Synthesizes TTS audio from workstation (192.168.0.194:8057) or generates test WAV audio.
2. Sends multiple audio POST requests in rapid succession to Pi 4B (192.168.0.86:8082).
3. Queries Pi 4B /api/status to verify sequential FIFO queuing and queue status tracking.
"""

import urllib.request
import urllib.parse
import json
import time
import struct
import math

TTS_URL = "http://192.168.0.194:8057/tts"
PI4B_AUDIO_URL = "http://192.168.0.86:8082/api/play_sound"
PI4B_STATUS_URL = "http://192.168.0.86:8082/api/status"


def make_pcm_wav(freq: float, duration: float) -> bytes:
    sr = 22050
    buf = bytearray()
    n_samples = int(sr * duration)
    for i in range(n_samples):
        t = i / sr
        val = int(0.3 * 32767 * math.sin(2 * math.pi * freq * t))
        buf.extend(struct.pack('<h', val))
    h = bytearray(b"RIFF")
    h.extend(struct.pack("<I", 36 + len(buf)))
    h.extend(b"WAVEfmt ")
    h.extend(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
    h.extend(b"data")
    h.extend(struct.pack("<I", len(buf)))
    return bytes(h + buf)


def main():
    print("=== PI 4B AUDIO QUEUE & TTS VERIFICATION ===")
    
    # 1. Synthesize TTS speech or generate PCM test WAV
    wav_bytes = None
    try:
        data = urllib.parse.urlencode({"text": "Hello Carson! Sequential FIFO audio queue is active on Pi 4B.", "voice_url": "hf://laura"}).encode("utf-8")
        req = urllib.request.Request(TTS_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                wav_bytes = resp.read()
                print(f"[1] TTS Synthesis: Received {len(wav_bytes)} raw WAV bytes from workstation TTS server (192.168.0.194:8057).")
    except Exception as e:
        print(f"[1] TTS Server notice: {e}")

    if not wav_bytes:
        wav_bytes = make_pcm_wav(523.25, 0.4)
        print(f"[1] Generated test PCM WAV tone ({len(wav_bytes)} bytes).")

    # 2. Rapidly enqueue multiple raw audio payloads to Pi 4B
    print("\n[2] Enqueuing multiple audio payloads to Pi 4B in rapid succession...")
    for i in range(1, 4):
        p_req = urllib.request.Request(PI4B_AUDIO_URL, data=wav_bytes, headers={"Content-Type": "audio/wav"})
        try:
            with urllib.request.urlopen(p_req, timeout=5) as p_resp:
                print(f"    Item {i} POST Response (HTTP {p_resp.status}): {p_resp.read().decode()}")
        except Exception as e:
            print(f"    Item {i} POST Error: {e}")

    # 3. Query Pi 4B status endpoint to verify queue state tracking
    print("\n[3] Querying Pi 4B status endpoint (http://192.168.0.86:8082/api/status)...")
    try:
        st_req = urllib.request.Request(PI4B_STATUS_URL)
        with urllib.request.urlopen(st_req, timeout=5) as st_resp:
            st_data = json.loads(st_resp.read().decode())
            print(f"    Audio State Telemetry: {json.dumps(st_data.get('audio_state', {}))}")
    except Exception as e:
        print(f"    Status query error: {e}")

    print("\n=== VERIFICATION COMPLETE ===")


if __name__ == "__main__":
    main()
