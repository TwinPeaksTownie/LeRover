#!/usr/bin/env python3
"""pi4b/audio_resolver.py - Audio resolver module for Pi 4B Touch UI node."""
import os
import sys
from pathlib import Path

root_dir = str(Path(__file__).parent.parent.resolve())
config_dir = os.path.join(root_dir, "config")
for p in [root_dir, config_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from config.audio_resolver import (
    load_audio_config,
    get_audio_event,
    get_audio_filename,
    find_audio_config_path,
)

__all__ = [
    "load_audio_config",
    "get_audio_event",
    "get_audio_filename",
    "find_audio_config_path",
]
