import paramiko

def test_audio_playback():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        print("Connecting to Pi 4B (192.168.0.86) to test audio playback...")
        client.connect('192.168.0.86', username='carson', password='raspberry', timeout=5)
        
        # Command to play a 440 Hz sine wave tone for 1 second using speaker-test or paplay / aplay
        # We test both pulse audio (paplay / speaker-test) and direct alsa (aplay)
        cmd = """
python3 -c "
import numpy as np
import wave
import subprocess

# Generate a 1-second 440Hz sine wave tone
sample_rate = 44100
duration = 1.0
t = np.linspace(0, duration, int(sample_rate * duration), False)
tone = np.sin(2 * np.pi * 440 * t)
audio = (tone * 32767).astype(np.int16)

with wave.open('/tmp/test_tone.wav', 'w') as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(sample_rate)
    f.writeframes(audio.tobytes())

print('Test WAV file generated at /tmp/test_tone.wav')
"
echo "--- Testing paplay (PulseAudio) ---"
paplay /tmp/test_tone.wav 2>&1 || echo "paplay failed"

echo "--- Testing aplay -D sysdefault (ALSA) ---"
aplay -D sysdefault /tmp/test_tone.wav 2>&1 || echo "aplay sysdefault failed"

echo "--- Testing aplay -D plughw:4,0 (USB Audio Device) ---"
aplay -D plughw:4,0 /tmp/test_tone.wav 2>&1 || echo "aplay USB failed"
"""
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        print(out)
        if err:
            print("STDERR:", err)

    except Exception as e:
        print("Error during audio test:", e)
    finally:
        client.close()

if __name__ == "__main__":
    test_audio_playback()
