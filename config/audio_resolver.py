#!/usr/bin/env python3
"""audio_resolver.py - Centralized Audio Configuration Resolver.
Loads and validates acoustic event mappings from config/audio_files.json.
Enforces strict fail-fast schema validation without arbitrary fallbacks.
"""

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger("audio_resolver")

_AUDIO_CONFIG_CACHE: Optional[Dict[str, Any]] = None


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
