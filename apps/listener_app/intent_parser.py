#!/usr/bin/env python3
"""apps/listener_app/intent_parser.py - Regex and Pattern-Matched Intent Extractor.
Extracts typed intent dictionaries and entities from transcribed command strings.
Strict Fail-Fast schema compliance: Zero .get(k, default) fallbacks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Dict, Any, Optional

logger = logging.getLogger("so101.listener_app.intent_parser")

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
if not CONFIG_PATH.exists():
    raise FileNotFoundError(f"Missing required ListenerApp config: {CONFIG_PATH}")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    _CONFIG = json.load(f)

APP_ALIAS_MAP = {
    "teleop": "teleop_app",
    "teleoperation": "teleop_app",
    "joystick": "teleop_app",
    "servo studio": "servo_studio_app",
    "studio": "servo_studio_app",
    "beat bandit": "beat_bandit_app",
    "bandit": "beat_bandit_app",
    "preset": "preset_app",
    "joycon": "joycon_teleop_app",
    "controller": "joycon_teleop_app",
    "clack": "piranha_pose_app",
    "piranha": "piranha_pose_app",
    "ornith": "ornith_voice",
    "voice": "ornith_voice",
}

POSTURE_COMMANDS: Dict[str, str] = _CONFIG["posture_aliases"]

POSTURE_PATTERNS = [
    (re.compile(r"\bstand\s+up\b"), "stand"),
    (re.compile(r"\bget\s+up\b"), "stand"),
    (re.compile(r"\bsit\s+down\b"), "sit"),
    (re.compile(r"\bplay\s+dead\b"), "play_dead"),
    (re.compile(r"\bbang\s+(?:(?:youre|your|you\s+are|you)\s+)?dead\b"), "play_dead"),
    (re.compile(r"\btippy\s+toes?\b"), "tiptoes"),
    (re.compile(r"\btiptoes\b"), "tiptoes"),
    (re.compile(r"\btiptoe\b"), "tiptoes"),
    (re.compile(r"\bstand\b"), "stand"),
    (re.compile(r"\bsit\b"), "sit"),
]


def strip_hallucinated_the(text: str) -> str:
    """Smart filtering: strips the isolated word 'the' if it occurs at the start, end,
    both, or if the transcription consists entirely of 'the'. Words with 'the' inside
    the sentence or as subwords (e.g. 'theme', 'breathe', 'to the beat') are preserved.
    """
    if not text:
        return ""
    s = text.strip()
    s = re.sub(r"^(?:the\b[^\w\s]*\s*)+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:\s*[^\w\s]*\bthe[^\w\s]*)+$", "", s, flags=re.IGNORECASE)
    return s.strip()


def sanitize_input(text: str) -> str:
    """Lowercases, cleans trailing punctuation, and strips hallucinated 'the' from transcribed audio."""
    cleaned = text.lower().strip()
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return strip_hallucinated_the(cleaned)


def parse_intent(text: str) -> Dict[str, Any]:
    """Parses transcribed voice command into a structured intent payload.
    
    Returns one of:
      {"intent": "SWITCH_APP", "app": str, "raw": str}
      {"intent": "POSTURE", "action": str, "raw": str}
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

    # 3. Exact and Phrase-Contained Physical Posture Commands ('stand up', 'get up', 'stand', 'sit down', 'sit', 'tiptoes', 'tiptoe', 'tippy toes', 'play dead', 'bang youre dead')
    if raw_clean in POSTURE_COMMANDS:
        return {"intent": "POSTURE", "action": POSTURE_COMMANDS[raw_clean], "raw": raw_clean}

    for pattern, action in POSTURE_PATTERNS:
        if pattern.search(raw_clean):
            if action != "play_dead" and (raw_clean.startswith("play ") or raw_clean.startswith("sing ") or raw_clean.startswith("download ")):
                continue
            return {"intent": "POSTURE", "action": action, "raw": raw_clean}

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

    # 6. Direct song title lookup fallback (e.g. "red wine supernova", "redwine supernova", "peaches")
    try:
        from apps.listener_app.song_pipeline import find_beat_bandit_track, find_compiled_sequence
        matched_track = find_beat_bandit_track(raw_clean)
        if matched_track is not None:
            return {"intent": "PLAY_SONG", "title": str(matched_track["title"]), "raw": raw_clean}
        compiled_seq = find_compiled_sequence(raw_clean)
        if compiled_seq is not None:
            return {"intent": "PLAY_SONG", "title": raw_clean, "raw": raw_clean}
    except Exception as e:
        logger.warning("Direct title lookup failed for query %r: %s", raw_clean, e, exc_info=True)

    return {"intent": "UNKNOWN", "raw": raw_clean}
