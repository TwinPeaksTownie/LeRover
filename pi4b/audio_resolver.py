#!/usr/bin/env python3
"""audio_resolver.py - Centralized Audio Configuration Resolver.
Loads and validates acoustic event mappings from config/audio_files.json.
Enforces strict fail-fast schema validation without arbitrary fallbacks.
"""

import json
import logging
import os
import threading
import time
import urllib.request
import wave
from typing import Dict, Any, Optional

try:
    import network_resolver
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver

logger = logging.getLogger("audio_resolver")

_AUDIO_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_AUDIO_DURATION_CACHE: Dict[str, float] = {}


def find_audio_config_path() -> str:
    """Discovers audio_files.json across standard repository and system paths."""
    search_paths = []
    if "AUDIO_CONFIG_PATH" in os.environ:
        search_paths.append(os.environ["AUDIO_CONFIG_PATH"])
    search_paths.extend([
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_files.json"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "audio_files.json"),
        "/home/carson/so101/config/audio_files.json",
        "/home/user/so101/config/audio_files.json",
        "/home/carson/touch_ui/config/audio_files.json",
        "i:/aux_servo_interface/config/audio_files.json",
    ])
    for p in search_paths:
        if p and os.path.exists(p):
            return os.path.abspath(p)
    raise FileNotFoundError("Missing required audio configuration: audio_files.json not found in search paths.")


def load_audio_config(force_reload: bool = False) -> Dict[str, Any]:
    """Loads and caches audio_files.json. Raises FileNotFoundError if missing."""
    global _AUDIO_CONFIG_CACHE
    if _AUDIO_CONFIG_CACHE is not None and not force_reload:
        return _AUDIO_CONFIG_CACHE

    cfg_path = find_audio_config_path()
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "events" not in config or not isinstance(config["events"], dict):
        raise KeyError(f"Malformed audio configuration in {cfg_path}: missing top-level 'events' dictionary.")

    _AUDIO_CONFIG_CACHE = config
    return _AUDIO_CONFIG_CACHE


def get_audio_event(event_name: str) -> Dict[str, Any]:
    """Returns metadata dictionary for a given audio event. Raises KeyError if unknown."""
    config = load_audio_config()
    events = config["events"]
    if event_name not in events:
        raise KeyError(f"Unknown audio event '{event_name}'. Defined events: {list(events.keys())}")
    return events[event_name]


def get_audio_filename(event_name: str) -> str:
    """Returns the sound asset filename for an audio event. Raises KeyError if not found."""
    event = get_audio_event(event_name)
    if "file" not in event:
        raise KeyError(f"Audio event '{event_name}' missing required 'file' attribute.")
    return event["file"]


def resolve_audio_file_path(event_name_or_wav: str) -> str:
    """Resolves local absolute path to an audio WAV file. Raises FileNotFoundError if missing."""
    if event_name_or_wav and os.path.isabs(event_name_or_wav) and os.path.exists(event_name_or_wav):
        return os.path.abspath(event_name_or_wav)

    config = load_audio_config()
    events = config["events"]
    if event_name_or_wav in events:
        sound_file = events[event_name_or_wav]["file"]
    else:
        sound_file = event_name_or_wav

    search_dirs = [
        "/home/carson/mario_sounds",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sounds"),
        "i:/aux_servo_interface/assets/sounds",
        "/home/user/so101/assets/sounds",
        "/home/carson/touch_ui/assets/sounds",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "sounds"),
    ]
    for d in search_dirs:
        cand = os.path.join(d, sound_file)
        if os.path.exists(cand):
            return os.path.abspath(cand)

    raise FileNotFoundError(f"Audio asset '{sound_file}' (event: '{event_name_or_wav}') not found in search paths: {search_dirs}")


def get_audio_duration_sec(event_name_or_wav: str) -> float:
    """Calculates and caches the exact duration in seconds of a WAV audio asset.
    Raises FileNotFoundError if asset is missing, ValueError if invalid WAV format.
    """
    global _AUDIO_DURATION_CACHE
    if event_name_or_wav in _AUDIO_DURATION_CACHE:
        return _AUDIO_DURATION_CACHE[event_name_or_wav]

    target_path = resolve_audio_file_path(event_name_or_wav)
    with wave.open(target_path, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        if rate <= 0:
            raise ValueError(f"Invalid frame rate {rate} in audio file: {target_path}")
        duration = frames / float(rate)

    _AUDIO_DURATION_CACHE[event_name_or_wav] = duration
    return duration


def get_pi4b_sound_url() -> str:
    """Returns the audio dispatch URL on the Pi 4B."""
    pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=8082)
    return f"http://{pi4b_ip}:8082/api/play_sound"


def dispatch_audio_event(kind: str = "incorrect", wav_path: Optional[str] = None, stop_previous: bool = True, delay_sec: float = 0.0, blocking: bool = False) -> float:
    """Dispatches sound playback event to Pi 4B audio service asynchronously or blocking.
    Returns exact audio duration in seconds.
    """
    event_name = kind
    sound_file = get_audio_filename(kind) if not wav_path else os.path.basename(wav_path)
    duration_sec = get_audio_duration_sec(wav_path if wav_path else kind)

    def _work():
        try:
            if delay_sec > 0:
                time.sleep(delay_sec)
            payload = json.dumps({
                "kind": sound_file,
                "event": event_name,
                "wav_path": wav_path or "",
                "stop_previous": stop_previous,
                "delay_sec": 0.0,
                "blocking": blocking
            }).encode("utf-8")
            req = urllib.request.Request(
                get_pi4b_sound_url(),
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            if blocking:
                req_timeout = max(5.0, duration_sec + 5.0)
            else:
                req_timeout = 2.0
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                pass
        except Exception as e:
            logger.exception("Failed to dispatch audio event '%s' (%s) to Pi 4B: %s", event_name, sound_file, e)

    if blocking:
        _work()
    else:
        threading.Thread(target=_work, daemon=True).start()

    return duration_sec

