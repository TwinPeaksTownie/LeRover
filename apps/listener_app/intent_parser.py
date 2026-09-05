#!/usr/bin/env python3
"""apps/listener_app/intent_parser.py - Regex and Pattern-Matched Intent Extractor.
Extracts typed intent dictionaries and entities from transcribed command strings.
Strict Fail-Fast schema compliance: Zero .get(k, default) fallbacks.
"""

from __future__ import annotations

import re
from typing import Dict, Any, Optional

APP_ALIAS_MAP = {
    "teleop": "teleop",
    "teleoperation": "teleop",
    "joystick": "teleop",
    "servo studio": "servo_studio",
    "studio": "servo_studio",
    "beat bandit": "beat_bandit",
    "bandit": "beat_bandit",
    "preset": "preset_app",
    "presets": "preset_app",
    "pokeball": "pokeball_app",
    "ball": "pokeball_app",
    "clack": "clack_pose_app",
    "piranha": "clack_pose_app",
    "ornith": "ornith_voice",
    "voice": "ornith_voice",
}

MOVE_PRIMITIVES = {
    "home": "home",
    "center": "center",
    "park": "park",
    "rest": "park",
    "zero": "home",
}


def sanitize_input(text: str) -> str:
    """Lowercases and cleans trailing punctuation from transcribed audio."""
    cleaned = text.lower().strip()
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_intent(text: str) -> Dict[str, Any]:
    """Parses transcribed voice command into a structured intent payload.
    
    Returns one of:
      {"intent": "SWITCH_APP", "app": str, "raw": str}
      {"intent": "MOVE_PRIMITIVE", "action": str, "raw": str}
      {"intent": "DOWNLOAD_SONG", "title": str, "artist": str, "raw": str}
      {"intent": "PLAY_SONG", "title": str, "raw": str}
      {"intent": "EXIT", "raw": str}
      {"intent": "UNKNOWN", "raw": str}
    """
    raw_clean = sanitize_input(text)
    if not raw_clean:
        return {"intent": "UNKNOWN", "raw": ""}

    # 1. Exit / Cancel
    if raw_clean in ("exit", "quit", "cancel", "stop listening", "abort"):
        return {"intent": "EXIT", "raw": raw_clean}

    # 2. App Switch Intents (e.g. "start teleop", "launch studio", "switch to beat bandit")
    app_match = re.match(r"^(?:start|launch|open|switch to|run)\s+(.+)$", raw_clean)
    if app_match:
        target = app_match.group(1).strip()
        if target in APP_ALIAS_MAP:
            return {"intent": "SWITCH_APP", "app": APP_ALIAS_MAP[target], "raw": raw_clean}
        for alias, canonical in APP_ALIAS_MAP.items():
            if alias in target:
                return {"intent": "SWITCH_APP", "app": canonical, "raw": raw_clean}

    # 3. Movement Primitive Intents (e.g. "home", "center arm", "park")
    for prim in MOVE_PRIMITIVES:
        if raw_clean == prim or raw_clean == f"{prim} arm" or raw_clean == f"go {prim}":
            return {"intent": "MOVE_PRIMITIVE", "action": MOVE_PRIMITIVES[prim], "raw": raw_clean}

    # 4. Download Song Intent (e.g. "download <title> by <artist>" or "get <title> by <artist>")
    dl_match = re.match(r"^(?:download|fetch|get|learn)\s+(.+?)\s+by\s+(.+)$", raw_clean)
    if dl_match:
        title = dl_match.group(1).strip()
        artist = dl_match.group(2).strip()
        if title and artist:
            return {
                "intent": "DOWNLOAD_SONG",
                "title": title,
                "artist": artist,
                "raw": raw_clean
            }

    # 5. Play / Sing Choreography Intent (e.g. "sing pink pony club", "play pink pony club", "dance to pink pony club")
    play_match = re.match(r"^(?:sing|play|dance to|perform)\s+(.+)$", raw_clean)
    if play_match:
        title = play_match.group(1).strip()
        # Remove trailing "song" or "track" if present
        title = re.sub(r"\s+(?:song|track)$", "", title).strip()
        if title:
            return {"intent": "PLAY_SONG", "title": title, "raw": raw_clean}

    return {"intent": "UNKNOWN", "raw": raw_clean}
