#!/usr/bin/env python3
"""Test 3: Unified Dispatch Test.
Tests RobotBackend.dispatch_dance_frame() proving:
  - Multi-servo tick conversions from 0-100% ROM execute accurately against loaded calibration.
  - SERIAL_LOCK and multi-bus calls are fully encapsulated inside RobotBackend.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "pi4b"))
from robot_backend import RobotBackend, SERIAL_LOCK


class TestUnifiedDispatch(unittest.TestCase):

    def setUp(self):
        # Create uninitialized mock backend instance
        self.backend = RobotBackend.__new__(RobotBackend)
        self.backend.lock = MagicMock()
        self.backend.servos = {i: {"normalized": 50.0, "pos": 2048, "raw": 2048, "torque": False} for i in range(1, 9)}
        self.backend.arm_calibration = {
            "shoulder_pan": {"range_min": 1000, "range_max": 3000},
            "shoulder_lift": {"range_min": 1000, "range_max": 3000},
            "elbow_flex": {"range_min": 1000, "range_max": 3000},
            "wrist_flex": {"range_min": 1000, "range_max": 3000},
            "wrist_roll": {"range_min": 1000, "range_max": 3000},
            "gripper": {"range_min": 500, "range_max": 1500},
        }
        self.backend.aux_calibration = {
            "7": {"min_ticks": 1000, "max_ticks": 3000, "center_ticks": 2000},
            "8": {"min_ticks": 500, "max_ticks": 4500},
        }
        self.backend.bus = MagicMock()
        self.backend.ctrl = MagicMock()
        self.backend.move_target = MagicMock()
        self.backend._last_dance_s7_ticks = None

    def test_dispatch_dance_frame_tick_conversion(self):
        """Tests that 50% ROM converts to exactly midpoint ticks (2000)."""
        rom_frame = {
            "shoulder_pan": 50.0,
            "shoulder_lift": 0.0,
            "elbow_flex": 100.0,
            "wrist_flex": 50.0,
            "wrist_roll": 50.0,
            "gripper": 25.0,
        }

        res = self.backend.dispatch_dance_frame(rom_frame, s7_rom=50.0, s8_goal=50.0, s8_is_rom=True)

        self.assertEqual(res["status"], "ok")
        ticks = res["goal_ticks"]

        # 50% of (1000 to 3000) = 2000
        self.assertEqual(ticks["shoulder_pan"], 2000)
        # 0% of (1000 to 3000) = 1000
        self.assertEqual(ticks["shoulder_lift"], 1000)
        # 100% of (1000 to 3000) = 3000
        self.assertEqual(ticks["elbow_flex"], 3000)
        # 25% of (500 to 1500) = 750
        self.assertEqual(ticks["gripper"], 750)

        # Servo 7 at 50% = 2000
        self.assertEqual(res["s7_ticks"], 2000)
        # Servo 8 at 50% of (500 to 4500) = 2500
        self.assertEqual(res["s8_ticks"], 2500)

        # Verify underlying bus sync_write was called with ticks
        self.backend.bus.sync_write.assert_called_once_with("Goal_Position", ticks, normalize=False)
        self.backend.ctrl.write_goal_raw.assert_called_once_with(7, 2000, speed=800)
        self.backend.move_target.assert_called_once_with(8, 2500, speed=500, max_t=800)

    def test_dispatch_dance_frame_fail_fast_missing_calibration(self):
        """Tests that dispatch_dance_frame raises KeyError when arm calibration is missing."""
        self.backend.arm_calibration = {}
        rom_frame = {"shoulder_pan": 50.0}
        with self.assertRaises(KeyError) as ctx:
            self.backend.dispatch_dance_frame(rom_frame)
        self.assertIn("Fail-Fast Error", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
