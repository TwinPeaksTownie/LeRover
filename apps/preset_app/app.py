#!/usr/bin/env python3
"""apps/preset_app/app.py - Clack / Piranha Pose Application for SO-101.
Registered under AppManager on Pi 500 to provide coordinated state locking and logging
for acoustic multi-tap pose capture and playback teaching workflows.
Loads configuration from apps/preset_app/config.json.
"""

import json
import logging
import os
import sys
import threading
import time
from typing import Optional

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

def load_preset_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing required Preset config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_CONFIG = load_preset_config()

class PiranhaPoseApp(BaseApp):
    metadata = AppMetadata(
        name=_CONFIG["name"],
        title=_CONFIG["title"],
        description=_CONFIG["description"],
        version=_CONFIG["version"],
        tags=_CONFIG["tags"],
        icon=_CONFIG["icon"]
    )

    def __init__(self, running_on_pi: bool = True) -> None:
        super().__init__(running_on_pi=running_on_pi)
        self.logger = logging.getLogger("so101.app.piranha_pose")

    def setup(self, backend: RobotBackend) -> None:
        self.logger.info("PiranhaPoseApp setup initialized.")

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.logger.info("PiranhaPoseApp active and ready for pose capture/resume requests.")
        while not stop_event.is_set():
            time.sleep(0.5)

    def teardown(self, backend: RobotBackend) -> None:
        self.logger.info("PiranhaPoseApp teardown: ensuring torque is safely maintained.")
        try:
            backend.set_arm_torque(enable=True)
        except Exception as e:
            self.logger.warning("Teardown torque enable warning: %s", e)


class ClackPoseApp(PiranhaPoseApp):
    metadata = AppMetadata(
        name="clack_pose_app",
        title=_CONFIG["title"],
        description=f"{_CONFIG['description']} (legacy alias)",
        version=_CONFIG["version"],
        tags=_CONFIG["tags"],
        icon=_CONFIG["icon"]
    )
