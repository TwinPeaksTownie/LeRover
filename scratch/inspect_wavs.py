import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

sftp = client.open_sftp()
with sftp.file("/tmp/inspect_wav.py", "w") as f:
    f.write("""import wave
import struct
import math
import glob
import os

sounds = glob.glob('/home/carson/mario_sounds/*.wav')
for s in sorted(sounds):
    try:
        with wave.open(s, 'rb') as w:
            nchannels = w.getnchannels()
            sampwidth = w.getsampwidth()
            framerate = w.getframerate()
            nframes = w.getnframes()
            duration = nframes / float(framerate)
            frames = w.readframes(nframes)
            
            if sampwidth == 2:
                fmt = f"<{nframes * nchannels}h"
                samples = struct.unpack(fmt, frames)
                sum_sq = sum(s ** 2 for s in samples)
                rms = math.sqrt(sum_sq / len(samples))
                max_val = max(abs(s) for s in samples)
            else:
                rms = -1
                max_val = -1
            
            print(f"{os.path.basename(s):30s} | ch={nchannels} | width={sampwidth}B ({sampwidth*8}bit) | rate={framerate:5d}Hz | dur={duration:.3f}s | max_amp={max_val:5d} | rms={rms:7.1f}")
    except Exception as e:
        print(f"{os.path.basename(s):30s} | ERROR: {e}")
""")
sftp.close()

stdin, stdout, stderr = client.exec_command("python3 /tmp/inspect_wav.py")
print(stdout.read().decode('utf-8', errors='replace'))
print(stderr.read().decode('utf-8', errors='replace'))

client.close()
