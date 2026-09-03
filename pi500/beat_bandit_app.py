#!/usr/bin/env python3
"""pi500/beat_bandit_app.py - Compatibility shim forwarding to apps.beat_bandit.app."""

import os
import sys
from pathlib import Path

root_dir = str(Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from apps.beat_bandit.app import BeatBanditApp, get_library_path

__all__ = ["BeatBanditApp", "get_library_path"]
