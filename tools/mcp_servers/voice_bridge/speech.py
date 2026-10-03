"""
speech.py - Laura Voice Synthesis via Pocket-TTS
Synthesizes speech via Pocket-TTS (port 8057) and plays through local speakers
or dispatches audio alerts.
"""

import io
import json
import logging
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from typing import Optional

import voice_config

logger = logging.getLogger("voice_bridge")

def _log_debug(msg: str):
    sys.stderr.write(f"[VOICE_BRIDGE] {msg}\n")
    sys.stderr.flush()

def _play_wav_bytes(wav_bytes: bytes) -> bool:
    """Attempts to play WAV audio bytes via sounddevice or winsound fallback."""
    try:
        import soundfile as sf
        import sounddevice as sd
        data, fs = sf.read(io.BytesIO(wav_bytes), dtype='float32')
        sd.play(data, fs)
        sd.wait()
        return True
    except Exception as e:
        _log_debug(f"sounddevice playback failed ({e}), trying winsound")

    try:
        import winsound
        temp_path = os.path.join(tempfile.gettempdir(), f"voice_bridge_tts_{os.getpid()}.wav")
        with open(temp_path, "wb") as f:
            f.write(wav_bytes)
        winsound.PlaySound(temp_path, winsound.SND_FILENAME)
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return True
    except Exception as e:
        _log_debug(f"winsound playback failed: {e}")

    return False

def speak_laura(text: str, voice_url: str = None) -> dict:
    """Synthesizes text in Laura's voice using Pocket-TTS (port 8057) and plays locally."""
    clean_text = text.strip()
    if not clean_text:
        return {"status": "error", "error": "Cannot speak empty text"}

    cfg = voice_config.get_config()
    tts_url_base = cfg.get("pocket_tts_url", "http://127.0.0.1:8057/tts")
    if voice_url is None:
        voice_url = cfg.get("voice_url", "hf://laura")

    encoded_text = urllib.parse.quote(clean_text)
    encoded_voice = urllib.parse.quote(voice_url)
    req_url = f"{tts_url_base}?text={encoded_text}&voice_url={encoded_voice}"

    _log_debug(f"Synthesizing {len(clean_text)} chars via Pocket-TTS ({req_url[:80]}...)")
    try:
        req = urllib.request.Request(req_url, headers={"User-Agent": "VoiceBridge/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                wav_bytes = resp.read()
            else:
                return {"status": "error", "error": f"Pocket-TTS returned HTTP {resp.status}"}
    except Exception as e:
        return {"status": "error", "error": f"Failed to connect to Pocket-TTS server at {tts_url_base}: {str(e)}"}

    played = _play_wav_bytes(wav_bytes)
    return {
        "status": "success",
        "text": clean_text,
        "voice_url": voice_url,
        "bytes_received": len(wav_bytes),
        "local_playback": played
    }

def notify_user_of_blocker(reason: str) -> dict:
    """Speaks a high-priority spoken alert when human input is required."""
    prompt = f"Attention required. {reason.strip()}"
    res = speak_laura(prompt)
    res["alert_type"] = "BLOCKER"
    return res

def notify_task_verified(summary: str, telemetry_delta: str = "") -> dict:
    """Speaks an official verification completion notice after verification states pass."""
    msg = f"Task verification complete. {summary.strip()}."
    if telemetry_delta:
        msg += f" {telemetry_delta.strip()}."
    res = speak_laura(msg)
    res["alert_type"] = "TASK_VERIFIED"
    return res
