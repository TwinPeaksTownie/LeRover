#!/usr/bin/env python3
"""pi500/teleop_control_loop.py - Compatibility shim forwarding to apps.teleop_app.app."""

import os
import sys
from pathlib import Path

root_dir = str(Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from apps.teleop_app.app import (
    TeleopControlApp,
    get_motor_norm_bounds,
    validate_and_clamp_teleop_frame,
    get_mac_api_url
)

__all__ = [
    "TeleopControlApp",
    "get_motor_norm_bounds",
    "validate_and_clamp_teleop_frame",
    "get_mac_api_url"
]
