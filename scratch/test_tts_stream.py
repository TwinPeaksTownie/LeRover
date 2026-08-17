#!/usr/bin/env python3
"""Test script to generate a TTS WAV sample from the workstation TTS server (192.168.0.194:8057)
and stream the resulting raw binary audio bytes to the Pi 4B Audio Gateway (192.168.0.86:8082).
"""

import urllib.request
import urllib.parse
import json
import sys

TTS_SERVER_URL = "http://192.168.0.194:8057/tts"
PI4B_AUDIO_URL = "http://192.168.0.86:8082/api/play_sound"
TEST_TEXT = "Hello Carson! This is a test of the new Pi 4B sequential FIFO audio queue."

def main():
    print(f"1. Requesting TTS synthesis from workstation ({TTS_SERVER_URL})...")
    tts_payload = urllib.parse.urlencode({"text": TEST_TEXT, "voice_url": "hf://laura"}).encode("utf-8")
    tts_req = urllib.request.Request(TTS_SERVER_URL, data=tts_payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    
    try:
        with urllib.request.urlopen(tts_req, timeout=30.0) as tts_resp:
            if tts_resp.status != 200:
                print(f"Error: TTS server returned HTTP status {tts_resp.status}")
                return
            wav_bytes = tts_resp.read()
            print(f"   Received {len(wav_bytes)} raw WAV bytes from TTS server.")
    except Exception as e:
        print(f"   TTS synthesis server (192.168.0.194:8057) error/unreachable: {e}")
        print("   Synthesizing dynamic local PCM test chime WAV for verification...")
        import struct, math
        sr = 22050
        buf = bytearray()
        tones = [(523.25, 0.15, 0.3), (659.25, 0.15, 0.3), (784.00, 0.3, 0.4)]
        for freq, duration, vol in tones:
            n_samples = int(sr * duration)
            for i in range(n_samples):
                t = i / sr
                val = int(vol * 32767 * math.sin(2 * math.pi * freq * t))
                buf.extend(struct.pack('<h', val))
        header = bytearray(b"RIFF")
        header.extend(struct.pack("<I", 36 + len(buf)))
        header.extend(b"WAVEfmt ")
        header.extend(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        header.extend(b"data")
        header.extend(struct.pack("<I", len(buf)))
        wav_bytes = bytes(header + buf)

    print(f"2. Streaming {len(wav_bytes)} raw WAV bytes to Pi 4B ({PI4B_AUDIO_URL})...")
    pi4b_req = urllib.request.Request(PI4B_AUDIO_URL, data=wav_bytes, headers={"Content-Type": "audio/wav"})
    try:
        with urllib.request.urlopen(pi4b_req, timeout=5.0) as pi4b_resp:
            res_body = pi4b_resp.read().decode()
            print(f"   Pi 4B response (HTTP {pi4b_resp.status}): {res_body}")
    except Exception as e:
        print(f"   Error sending raw audio to Pi 4B: {e}")

if __name__ == "__main__":
    main()
