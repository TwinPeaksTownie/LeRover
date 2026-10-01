#!/usr/bin/env python3
"""tests/test_rover_controller.py - Unit tests for RoverController arcade drive kinematics and serial parameters."""

import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rover.rover_controller import RoverController


class TestRoverControllerKinematics(unittest.TestCase):
    """Verifies that RoverController differential drive kinematics and pulse mapping match physical Overlander-4 ESCs."""

    def setUp(self):
        self.config_path = str(REPO_ROOT / "config" / "rover_config.json")
        self.controller = RoverController(config_path=self.config_path, mock_mode=True)
        self.controller.accel_ramp_rate = 1.0  # Instant response for deterministic unit testing
        self.controller.steering_trim = 0.0    # Baseline kinematics testing without trim bias
        self.controller.start()

    def tearDown(self):
        self.controller.stop()

    def test_config_loaded_rts(self):
        """Assert that assert_rts is False from rover_config.json."""
        self.assertFalse(self.controller.assert_rts)
        self.assertTrue(self.controller.assert_dtr)

    def test_neutral_stop(self):
        """Zero input should yield 1500 us neutral on both motors."""
        self.controller.set_drive(0.0, 0.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertEqual(telem["left_pulse"], 1500)
        self.assertEqual(telem["right_pulse"], 1500)

    def test_forward_drive(self):
        """Forward throttle (y > 0) must increase left pulse (>1500) and decrease right pulse (<1500)."""
        self.controller.set_drive(0.0, 1.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertGreater(telem["left_pulse"], 1500, "Left pulse must be >1500 for forward drive")
        self.assertLess(telem["right_pulse"], 1500, "Right pulse must be <1500 for forward drive")
        self.assertEqual(telem["left_pulse"], 1500 + self.controller.max_pulse_offset)
        self.assertEqual(telem["right_pulse"], 1500 - self.controller.max_pulse_offset)

    def test_reverse_drive(self):
        """Reverse throttle (y < 0) must decrease left pulse (<1500) and increase right pulse (>1500)."""
        self.controller.set_drive(0.0, -1.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertLess(telem["left_pulse"], 1500, "Left pulse must be <1500 for reverse drive")
        self.assertGreater(telem["right_pulse"], 1500, "Right pulse must be >1500 for reverse drive")
        self.assertEqual(telem["left_pulse"], 1500 - self.controller.max_pulse_offset)
        self.assertEqual(telem["right_pulse"], 1500 + self.controller.max_pulse_offset)

    def test_turn_right(self):
        """Steering right (x > 0) must rotate clockwise: left forward (>1500), right reverse (>1500)."""
        self.controller.set_drive(1.0, 0.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertGreater(telem["left_pulse"], 1500, "Left motor must drive forward (>1500) on right turn")
        self.assertGreater(telem["right_pulse"], 1500, "Right motor must drive reverse (>1500) on right turn")

    def test_turn_left(self):
        """Steering left (x < 0) must rotate counter-clockwise: left reverse (<1500), right forward (<1500)."""
        self.controller.set_drive(-1.0, 0.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertLess(telem["left_pulse"], 1500, "Left motor must drive reverse (<1500) on left turn")
        self.assertLess(telem["right_pulse"], 1500, "Right motor must drive forward (<1500) on left turn")

    def test_steering_trim_compensation(self):
        """Positive steering trim must bias right motor slower to counter left drift."""
        self.controller.set_steering_trim(0.05)
        self.controller.set_drive(0.0, 1.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertEqual(telem["left_pulse"], 1675)
        self.assertEqual(telem["right_pulse"], 1334)

    def test_speed_step_adjustment(self):
        """adjust_speed_pct must step max_speed_pct and update max_pulse_offset atomically."""
        new_speed = self.controller.adjust_speed_pct(5)
        self.assertEqual(new_speed, 40)
        self.assertEqual(self.controller.max_pulse_offset, 200)

    def test_throttle_gated_steering(self):
        """When enforce_throttle_gate is True and throttle is 0, steering must not move wheels."""
        self.controller.set_drive(1.0, 0.0, enforce_throttle_gate=True)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertEqual(telem["left_pulse"], 1500)
        self.assertEqual(telem["right_pulse"], 1500)


if __name__ == "__main__":
    unittest.main()
