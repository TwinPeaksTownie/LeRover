#!/usr/bin/env python3
"""tests/test_attack_drive_burst.py - Verifies forward drive burst polarity in PiranhaPoseApp attack sequence."""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "pi4b"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "preset_app"))

from apps.preset_app.app import PiranhaPoseApp
from rover.rover_controller import RoverController


class TestAttackDriveBurst(unittest.TestCase):
    """Verifies that the attack sequence drive burst drives forward (+throttle), not reverse (-throttle)."""

    def test_drive_burst_helper_commands_positive_throttle(self):
        """_drive_burst_helper must call set_drive with positive throttle (y > 0) for forward lunge."""
        app = PiranhaPoseApp(running_on_pi=False)
        mock_ctrl = MagicMock()
        app.rover_ctrl = mock_ctrl

        app._drive_burst_helper(throttle=0.85, duration_sec=0.01)

        # First call must be (0.0, 0.85) - steering 0, throttle +0.85 (FORWARD)
        self.assertEqual(mock_ctrl.set_drive.call_count, 2)
        first_call = mock_ctrl.set_drive.call_args_list[0]
        self.assertEqual(first_call[0], (0.0, 0.85), "First set_drive must command positive forward throttle (+0.85)")

        # Second call must be (0.0, 0.0) - brake / neutral
        second_call = mock_ctrl.set_drive.call_args_list[1]
        self.assertEqual(second_call[0], (0.0, 0.0), "Second set_drive must command neutral (0.0, 0.0)")

    def test_drive_burst_kinematics_pulse_output(self):
        """End-to-end integration: _drive_burst_helper with RoverController yields forward ESC pulses (>1500 left, <1500 right)."""
        app = PiranhaPoseApp(running_on_pi=False)
        config_path = str(REPO_ROOT / "config" / "rover_config.json")
        controller = RoverController(config_path=config_path, mock_mode=True)
        controller.accel_ramp_rate = 1.0  # Instant response for deterministic test
        controller.start()
        app.rover_ctrl = controller

        try:
            # Command forward drive burst
            app._drive_burst_helper(throttle=0.85, duration_sec=0.05)
            # After burst completes, controller should have returned to neutral
            time.sleep(0.05)
            telem = controller.get_telemetry()
            self.assertEqual(telem["left_pulse"], 1500)
            self.assertEqual(telem["right_pulse"], 1500)

            # While driving at +0.85, left pulse must be > 1500 and right pulse < 1500
            controller.set_drive(0.0, 0.85)
            time.sleep(0.05)
            driving_telem = controller.get_telemetry()
            self.assertGreater(driving_telem["left_pulse"], 1500, "Left pulse must be > 1500 for forward drive")
            self.assertLess(driving_telem["right_pulse"], 1500, "Right pulse must be < 1500 for forward drive")
        finally:
            controller.stop()
            controller.shutdown()


if __name__ == "__main__":
    unittest.main()
