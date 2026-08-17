#!/usr/bin/env python3
import urllib.request
import urllib.parse

TTS_URL = "http://192.168.0.194:8057/tts"
PI4B_URL = "http://192.168.0.86:8082/api/play_sound"
TEXT = "Hello Carson! This is a test of synthesized TTS audio streaming to the Pi 4B."

def test():
    wav_bytes = None
    print(f"1. Querying TTS server on 192.168.0.194:8057...")
    try:
        data = urllib.parse.urlencode({"text": TEXT, "voice_url": "hf://laura"}).encode("utf-8")
        req = urllib.request.Request(TTS_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                wav_bytes = resp.read()
                print(f"✅ TTS Synthesis Successful! Received {len(wav_bytes)} raw WAV audio bytes.")
    except Exception as e:
        print(f"⚠️ TTS server query notice: {e}")

    if not wav_bytes:
        print("Generating test PCM audio wave...")
        import struct, math
        sr = 22050
        buf = bytearray()
        for freq, duration, vol in [(523.25, 0.15, 0.3), (659.25, 0.15, 0.3), (784.00, 0.3, 0.4)]:
            n = int(sr * duration)
            for i in range(n):
                buf.extend(struct.pack('<h', int(vol * 32767 * math.sin(2 * math.pi * freq * (i / sr)))))
        h = bytearray(b"RIFF") + struct.pack("<I", 36 + len(buf)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16) + b"data" + struct.pack("<I", len(buf))
        wav_bytes = bytes(h + buf)

    print(f"2. Sending {len(wav_bytes)} raw WAV bytes to Pi 4B ({PI4B_URL})...")
    req = urllib.request.Request(PI4B_URL, data=wav_bytes, headers={"Content-Type": "audio/wav"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            print(f"✅ Pi 4B Response (HTTP {resp.status}): {body}")
    except Exception as e:
        print(f"❌ Error sending audio to Pi 4B: {e}")

if __name__ == "__main__":
    test()
