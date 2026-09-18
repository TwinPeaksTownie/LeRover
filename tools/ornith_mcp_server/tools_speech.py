"""
tools_speech.py - Speech Output and Audio Alerts via Pocket TTS
Synthesizes speech via Pocket TTS server using Laura's voice conditioning (hf://laura)
and dispatches audio per declarative configuration in apps/ornith_voice/config.json.
"""

import io
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import ornith_config_loader

_CONFIG = ornith_config_loader.get_ornith_config()

if "POCKET_TTS_HOST" in os.environ:
    DEFAULT_TTS_HOST = os.environ["POCKET_TTS_HOST"]
else:
    DEFAULT_TTS_HOST = _CONFIG["speech"]["pocket_tts_host"]

if "POCKET_TTS_PORT" in os.environ:
    DEFAULT_TTS_PORT = int(os.environ["POCKET_TTS_PORT"])
else:
    DEFAULT_TTS_PORT = int(_CONFIG["speech"]["pocket_tts_port"])
DEFAULT_TARGET = _CONFIG["speech"]["target"]
DEFAULT_VOICE_URL = _CONFIG["speech"]["voice_url"]
MAX_WORDS = int(_CONFIG["speech"]["max_words"])

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
    except Exception as e:
        _log_debug(f"winsound playback failed ({e})")

    _log_debug("Audio playback failed on local device.")
    return False

if "PI4B_HOST" in os.environ:
    DEFAULT_PI4B_HOST = os.environ["PI4B_HOST"]
else:
    DEFAULT_PI4B_HOST = _CONFIG["network"]["pi4b_host"]

if "PI4B_PORT" in os.environ:
    DEFAULT_PI4B_PORT = int(os.environ["PI4B_PORT"])
else:
    DEFAULT_PI4B_PORT = int(_CONFIG["network"]["pi4b_port"])

def _send_wav_to_pi4b(wav_bytes: bytes, host: str = DEFAULT_PI4B_HOST, port: int = DEFAULT_PI4B_PORT) -> bool:
    """Streams raw WAV binary payload to Pi 4B kiosk /api/play_sound endpoint."""
    url = f"http://{host}:{port}/api/play_sound"
    req = urllib.request.Request(
        url,
        data=wav_bytes,
        headers={"Content-Type": "audio/wav"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status == 200
    except Exception as e:
        _log_debug(f"Failed to stream WAV to Pi 4B on {url}: {e}")
        return False

def send_pending_wav_to_pi4b(wav_bytes: bytes, host: str = DEFAULT_PI4B_HOST, port: int = DEFAULT_PI4B_PORT) -> bool:
    """Uploads raw WAV binary payload to Pi 4B kiosk /api/pending_audio endpoint for deferred playback."""
    url = f"http://{host}:{port}/api/pending_audio"
    req = urllib.request.Request(
        url,
        data=wav_bytes,
        headers={"Content-Type": "audio/wav"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status == 200
    except Exception as e:
        _log_debug(f"Failed to upload pending WAV to Pi 4B on {url}: {e}")
        return False

def synthesize_wav(
    text: str,
    voice_url: str = DEFAULT_VOICE_URL,
    host: str = DEFAULT_TTS_HOST,
    port: int = DEFAULT_TTS_PORT
) -> bytes:
    """Synthesizes text via Pocket TTS and returns raw WAV bytes without playing."""
    if not text or not text.strip():
        raise ValueError("Text argument cannot be empty")
    words = text.strip().split()
    if len(words) > MAX_WORDS:
        raise ValueError(f"Speech text exceeded configured max word limit ({len(words)} > {MAX_WORDS} words).")
    url = f"http://{host}:{port}/tts"
    payload = urllib.parse.urlencode({"text": text.strip(), "voice_url": voice_url}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as res:
        if res.status != 200:
            raise RuntimeError(f"Pocket TTS returned HTTP {res.status}")
        return res.read()

def speak_laura(
    text: str,
    voice_url: str = None,
    target: str = None,
    host: str = None,
    port: int = None,
    pi4b_host: str = None,
    pi4b_port: int = None
) -> dict:
    """
    Synthesizes and speaks text using Pocket TTS server in Laura's voice.
    target defaults to configured setting ("both", "local", or "pi4b").
    """
    if voice_url is None:
        voice_url = DEFAULT_VOICE_URL
    if target is None:
        target = DEFAULT_TARGET
    if host is None:
        host = DEFAULT_TTS_HOST
    if port is None:
        port = DEFAULT_TTS_PORT
    if pi4b_host is None:
        pi4b_host = DEFAULT_PI4B_HOST
    if pi4b_port is None:
        pi4b_port = DEFAULT_PI4B_PORT

    if not text or not text.strip():
        return {"status": "error", "error": "Text argument cannot be empty"}

    words = text.strip().split()
    if len(words) > MAX_WORDS:
        return {"status": "error", "error": f"Speech text exceeded limit ({len(words)} > {MAX_WORDS} words)"}

    _log_debug(f"Synthesizing {len(text)} chars ({len(words)} words) in voice '{voice_url}' on http://{host}:{port}/tts")
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

    _log_debug(f"Received {len(wav_data)} WAV bytes. Dispatching to target '{target}'.")
    played_local = False
    played_pi4b = False

    if target in ("local", "both"):
        try:
            played_local = _play_wav_bytes(wav_data)
        except Exception as e:
            _log_debug(f"Local playback error: {e}")

    if target in ("pi4b", "both"):
        try:
            played_pi4b = _send_wav_to_pi4b(wav_data, host=pi4b_host, port=pi4b_port)
        except Exception as e:
            _log_debug(f"Pi 4B audio stream error: {e}")

    return {
        "status": "success",
        "text": text,
        "voice_url": voice_url,
        "target": target,
        "bytes_played": len(wav_data),
        "played_local": played_local,
        "played_pi4b": played_pi4b,
        "message": f"Audio dispatched (local={played_local}, pi4b={played_pi4b})."
    }

def notify_user_of_blocker(reason: str, target: str = None, host: str = None, port: int = None) -> dict:
    if target is None:
        target = "local"
    spoken_text = f"Attention Carson. Ornith supervisor has encountered a blocker that requires your input: {reason}"
    return speak_laura(text=spoken_text, target=target, host=host, port=port)

def notify_task_verified(summary: str, telemetry_delta: str = "", target: str = None, host: str = None, port: int = None) -> dict:
    if target is None:
        target = "pi4b"
    if telemetry_delta:
        spoken_text = f"Ornith supervisor has verified task completion. {summary}. Physical telemetry confirmed {telemetry_delta}."
    else:
        spoken_text = f"Ornith supervisor has verified task completion. {summary}."
    return speak_laura(text=spoken_text, target=target, host=host, port=port)
