import paramiko
import sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)

sftp = client.open_sftp()
with sftp.file("/tmp/fix_audio_test.py", "w") as f:
    f.write("""import subprocess
import wave
import struct
import math
import os

# 1. Inspect module-suspend-on-idle
res = subprocess.run(["pactl", "list", "modules", "short"], capture_output=True, text=True)
print("PulseAudio modules loaded:\\n", res.stdout)

# 2. Amplify smw_shell_ricochet.wav to 100% full scale (peak normalize) and pad with 100ms silence so USB DAC doesn't clip
src = "/home/carson/mario_sounds/smw_shell_ricochet.wav"
dst = "/home/carson/mario_sounds/smw_shell_ricochet_boosted.wav"

with wave.open(src, 'rb') as r:
    params = r.getparams()
    nframes = r.getnframes()
    frames = r.readframes(nframes)
    samples = list(struct.unpack(f"<{nframes}h", frames))

max_val = max(abs(s) for s in samples)
scale = 32000.0 / max_val if max_val > 0 else 1.0
print(f"Original max amp: {max_val}, boosting by {scale:.2f}x")

boosted_samples = [int(s * scale) for s in samples]

# Pad 200ms silence at end so playback stream stays open
lead_silence = [0] * int(params.framerate * 0.05) # 50ms lead
tail_silence = [0] * int(params.framerate * 0.20) # 200ms tail
final_samples = lead_silence + boosted_samples + tail_silence

with wave.open(dst, 'wb') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(params.framerate)
    packed = struct.pack(f"<{len(final_samples)}h", *final_samples)
    w.writeframes(packed)

print(f"Saved boosted wav to {dst} (duration: {len(final_samples)/params.framerate:.3f}s)")

# Replace the original with the boosted version
os.replace(dst, src)
# Update symlinks
os.system("cd /home/carson/mario_sounds && ln -sf smw_shell_ricochet.wav smw_shell_richochet.wav && ln -sf smw_shell_ricochet.wav shell_ricochet.wav")
print("Replaced smw_shell_ricochet.wav with peak-normalized version!")

# 3. Disable suspend-on-idle in pulse temporarily or permanently
os.system("pactl unload-module module-suspend-on-idle 2>&1")
print("Unloaded module-suspend-on-idle")

# 4. Test play
print("Testing playback now...")
res = subprocess.run(["paplay", "/home/carson/mario_sounds/smw_shell_ricochet.wav"], capture_output=True, text=True)
print("paplay output:", res.stdout, res.stderr)
""")
sftp.close()

stdin, stdout, stderr = client.exec_command("python3 /tmp/fix_audio_test.py")
print(stdout.read().decode('utf-8', errors='replace'))
print(stderr.read().decode('utf-8', errors='replace'))

client.close()
