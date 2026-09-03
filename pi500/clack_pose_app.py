#!/usr/bin/env python3
"""pi500/clack_pose_app.py - Compatibility shim forwarding to apps.preset_app.app."""

import os
import sys
from pathlib import Path

root_dir = str(Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from apps.preset_app.app import PiranhaPoseApp, ClackPoseApp

__all__ = ["PiranhaPoseApp", "ClackPoseApp"]
