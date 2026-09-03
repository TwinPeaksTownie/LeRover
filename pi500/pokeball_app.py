#!/usr/bin/env python3
"""pi500/pokeball_app.py - Compatibility shim forwarding to apps.pokeball_app.app."""

import os
import sys
from pathlib import Path

root_dir = str(Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from apps.pokeball_app.app import PokeballApp, PokeballService, MAC_ADDRESS, INPUT_UUID, API_URL, TELEMETRY_FILE

__all__ = ["PokeballApp", "PokeballService", "MAC_ADDRESS", "INPUT_UUID", "API_URL", "TELEMETRY_FILE"]
