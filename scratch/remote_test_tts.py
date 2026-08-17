#!/usr/bin/env python3
import urllib.request
import urllib.parse
import json

TEST_TEXT = "Hello Carson! Testing TTS synthesis and streaming raw WAV bytes to Pi 4B audio queue."
TTS_URL = "http://192.168.0.194:8057/tts"
PI4B_URL = "http://192.168.0.86:8082/api/play_sound"

def main():
    print("1. Querying TTS server on 192.168.0.194:8057...")
    tts_data = urllib.parse.urlencode({"text": TEST_TEXT, "voice_url": "hf://laura"}).encode("utf-8")
    req = urllib.request.Request(TTS_SERVER_URL if "TTS_SERVER_URL" in globals() else TTS_URL, data=tts_data, headers={"Content-Type": "application/x-www-form-urlencoded"})

    wav_bytes = None
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            if resp.status == 200:
                wav_bytes = resp.read()
                print(f"   Successfully synthesized {len(wav_bytes)} raw WAV bytes from TTS server!")
            else:
                print(f"   TTS server returned status {resp.status}")
    except Exception as e:
        print(f"   TTS server (192.168.0.194:8057) notice: {e}")

    if not wav_bytes:
        print("   Generating dynamic PCM test chime WAV fallback for verification...")
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

    print(f"2. Streaming {len(wav_bytes)} raw WAV bytes to Pi 4B ({PI4B_URL})...")
    p_req = urllib.request.Request(PI4B_URL, data=wav_bytes, headers={"Content-Type": "audio/wav"})
    try:
        with urllib.request.urlopen(p_req, timeout=5.0) as p_resp:
            print(f"   Pi 4B Response (HTTP {p_resp.status}): {p_resp.read().decode()}")
    except Exception as e:
        print(f"   Pi 4B audio streaming error: {e}")

if __name__ == "__main__":
    main()
