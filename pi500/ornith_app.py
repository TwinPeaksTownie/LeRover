#!/usr/bin/env python3
"""pi500/ornith_app.py - Compatibility shim forwarding to apps.ornith_voice.app."""

import os
import sys
from pathlib import Path

# Ensure root directory is on sys.path
root_dir = str(Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from apps.ornith_voice.app import OrnithVoiceApp

__all__ = ["OrnithVoiceApp"]
