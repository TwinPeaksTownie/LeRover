import urllib.request
import urllib.parse
import json
import paramiko
import os

TTS_URLS = [
    "http://127.0.0.1:8057/tts",
    "http://localhost:8057/tts",
    "http://192.168.0.194:8057/tts"
]

TEST_TEXT = "Hello! Pocket TTS is connected and playing audio directly on the Pi 4B sound card."

def fetch_tts_audio(text):
    data = urllib.parse.urlencode({"text": text, "voice_url": "hf://laura"}).encode("utf-8")
    for url in TTS_URLS:
        try:
            print(f"Querying Pocket TTS at {url}...")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status == 200:
                    wav_data = resp.read()
                    print(f"Received {len(wav_data)} bytes of WAV audio from Pocket TTS ({url})!")
                    return wav_data
        except Exception as e:
            print(f"Failed to connect to {url}: {e}")
    return None

def send_and_play_on_pi4b(wav_data):
    local_tmp = "scratch/temp_tts.wav"
    with open(local_tmp, "wb") as f:
        f.write(wav_data)
    
    print("Connecting to Pi 4B via Paramiko to transfer audio...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect("192.168.0.86", username="carson", password="raspberry", timeout=5)
        sftp = client.open_sftp()
        remote_tmp = "/tmp/tts_pocket_output.wav"
        sftp.put(local_tmp, remote_tmp)
        sftp.close()
        print(f"Transferred WAV to {remote_tmp} on Pi 4B!")

        # 1. Play via paplay directly over SSH
        print("Playing audio via paplay on Pi 4B...")
        stdin, stdout, stderr = client.exec_command(f"paplay {remote_tmp} 2>&1 || aplay {remote_tmp} 2>&1")
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        print("Playback output:", out.strip())

        # 2. Also test triggering via HTTP API endpoint
        api_url = "http://192.168.0.86:8082/api/play_sound"
        req = urllib.request.Request(api_url, data=json.dumps({"wav_path": remote_tmp}).encode('utf-8'), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            print("API trigger response:", resp.read().decode())

    except Exception as e:
        print("Error during transfer/playback on Pi 4B:", e)
    finally:
        client.close()
        if os.path.exists(local_tmp):
            os.remove(local_tmp)

if __name__ == "__main__":
    audio = fetch_tts_audio(TEST_TEXT)
    if audio:
        send_and_play_on_pi4b(audio)
    else:
        print("ERROR: Could not synthesize audio from Pocket TTS server on port 8057!")
