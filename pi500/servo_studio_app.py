#!/usr/bin/env python3
"""pi500/servo_studio_app.py - Compatibility shim forwarding to apps.servo_studio.app."""

import os
import sys
from pathlib import Path

root_dir = str(Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from apps.servo_studio.app import ServoStudioApp

__all__ = ["ServoStudioApp"]
