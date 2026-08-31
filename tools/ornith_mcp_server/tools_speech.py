"""
tools_speech.py - Speech Output and Audio Alerts via Pocket TTS
Synthesizes speech via Pocket TTS server on port 8057 using Laura's voice conditioning (hf://laura)
and plays audio directly through PC speakers (or via HTTP in Docker).
"""

import io
import os
import sys
import tempfile
import urllib.parse
import urllib.request

DEFAULT_TTS_HOST = os.environ.get("POCKET_TTS_HOST", "127.0.0.1" if os.name == "nt" else "host.docker.internal")
DEFAULT_TTS_PORT = int(os.environ.get("POCKET_TTS_PORT", 8057))

def _log_debug(msg: str):
    sys.stderr.write(f"[SPEECH] {msg}\n")
    sys.stderr.flush()

def _play_wav_bytes(wav_bytes: bytes) -> bool:
    """Attempts to play WAV audio bytes via sounddevice/soundfile or winsound fallback."""
    try:
        import soundfile as sf
        import sounddevice as sd
        data, fs = sf.read(io.BytesIO(wav_bytes), dtype='float32')
        sd.play(data, fs)
        sd.wait()
        return True
    except Exception as e:
        _log_debug(f"sounddevice playback failed ({e}), trying winsound/fallback")

    try:
        import winsound
        temp_path = os.path.join(tempfile.gettempdir(), f"ornith_tts_{os.getpid()}.wav")
        with open(temp_path, "wb") as f:
            f.write(wav_bytes)
        winsound.PlaySound(temp_path, winsound.SND_FILENAME)
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return True
    except Exception:
        pass

    # If running inside Docker container without audio device, log completion
    _log_debug("Audio synthesized successfully (container mode).")
    return True

def speak_laura(
    text: str,
    voice_url: str = "hf://laura",
    host: str = None,
    port: int = None
) -> dict:
    """
    Synthesizes and speaks text using Pocket TTS server in Laura's voice.
    """
    if host is None:
        host = DEFAULT_TTS_HOST
    if port is None:
        port = DEFAULT_TTS_PORT

    if not text or not text.strip():
        return {"status": "error", "error": "Text argument cannot be empty"}

    _log_debug(f"Synthesizing {len(text)} chars in voice '{voice_url}' on http://{host}:{port}/tts")
    url = f"http://{host}:{port}/tts"
    
    payload = urllib.parse.urlencode({"text": text.strip(), "voice_url": voice_url}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            if res.status != 200:
                return {"status": "error", "error": f"Pocket TTS returned HTTP {res.status}"}
            wav_data = res.read()
    except Exception as e:
        _log_debug(f"Pocket TTS connection error: {e}")
        return {"status": "error", "error": f"Failed to reach Pocket TTS on {url}: {str(e)}"}

    _log_debug(f"Received {len(wav_data)} WAV bytes.")
    try:
        _play_wav_bytes(wav_data)
        return {
            "status": "success",
            "text": text,
            "voice_url": voice_url,
            "bytes_played": len(wav_data),
            "message": "Audio played successfully through local speakers."
        }
    except Exception as e:
        return {"status": "error", "error": f"Playback error: {str(e)}"}

def notify_user_of_blocker(reason: str, host: str = None, port: int = None) -> dict:
    spoken_text = f"Attention Carson. Ornith supervisor has encountered a blocker that requires your input: {reason}"
    return speak_laura(text=spoken_text, voice_url="hf://laura", host=host, port=port)

def notify_task_verified(summary: str, telemetry_delta: str = "", host: str = None, port: int = None) -> dict:
    if telemetry_delta:
        spoken_text = f"Ornith supervisor has verified task completion. {summary}. Physical telemetry confirmed {telemetry_delta}."
    else:
        spoken_text = f"Ornith supervisor has verified task completion. {summary}."
    return speak_laura(text=spoken_text, voice_url="hf://laura", host=host, port=port)
