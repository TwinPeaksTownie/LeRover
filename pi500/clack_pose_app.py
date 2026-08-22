#!/usr/bin/env python3
"""Clack Pose Application for SO-101.
Registered under AppManager on Pi 500 to provide coordinated state locking and logging
for acoustic multi-tap pose capture and playback teaching workflows.
"""

import logging
import threading
import time
from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend


class ClackPoseApp(BaseApp):
    metadata = AppMetadata(
        name="clack_pose_app",
        title="Clack Pose",
        description="Acoustic multi-tap pose capture and playback teaching mode",
        version="1.0.0",
        tags=["teaching", "pose", "audio", "so101"],
        icon="🎬",
    )

    def __init__(self, running_on_pi: bool = True) -> None:
        super().__init__(running_on_pi=running_on_pi)
        self.logger = logging.getLogger("so101.app.clack_pose")

    def setup(self, backend: RobotBackend) -> None:
        self.logger.info("ClackPoseApp setup initialized.")

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.logger.info("ClackPoseApp active and ready for pose capture/resume requests.")
        while not stop_event.is_set():
            time.sleep(0.5)

    def teardown(self, backend: RobotBackend) -> None:
        self.logger.info("ClackPoseApp teardown: ensuring torque is safely maintained.")
        try:
            backend.set_arm_torque(enable=True)
        except Exception as e:
            self.logger.warning("Teardown torque enable warning: %s", e)
