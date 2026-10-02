#!/usr/bin/env python3
"""tests/test_obstacle_safety_guard.py - Unit tests for ObstacleSafetyGuard supervisor."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.obstacle_safety_guard import ObstacleSafetyGuard


class TestObstacleSafetyGuard(unittest.TestCase):
    """Verifies binary state machine (Rule 13), collision halt, and 2-second recovery."""

    def setUp(self):
        self.config = {
            "pwm": {"max_speed_pct": 35},
            "control": {"min_speed_pct": 0, "max_speed_pct_limit": 100},
            "collision_guard": {
                "enabled": True,
                "danger_zone_cm": 25.0,
                "min_valid_cm": 4.0,
                "max_valid_cm": 100.0,
                "ground_exclusion_adc": 62000,
                "recovery_button": "a",
                "recovery_hold_sec": 2.0,
                "speed_penalty_pct": 50,
                "halt_pulse_left": 1500,
                "halt_pulse_right": 1500
            }
        }
        self.guard = ObstacleSafetyGuard(
            config=self.config,
            api_host="127.0.0.1",
            api_port=8089,
            telemetry_path="/tmp/mock_joycon_telemetry.json"
        )

    @patch.object(ObstacleSafetyGuard, "query_distance_status")
    @patch.object(ObstacleSafetyGuard, "read_joycon_telemetry")
    @patch.object(ObstacleSafetyGuard, "dispatch_emergency_halt")
    def test_clear_path_forward_drive(self, mock_halt, mock_telem, mock_dist):
        """Driving forward with no obstacle keeps state NORMAL and does not halt."""
        mock_dist.return_value = {
            "object_detected": False,
            "in_danger_zone": False,
            "distance_cm": None,
            "emergency_halt": False,
            "max_speed_pct": 35
        }
        mock_telem.return_value = {
            "drivetrain": {"throttle": 1.0},
            "buttons": {"a": False}
        }
        res = self.guard.step(now=100.0)
        self.assertEqual(res["state"], "NORMAL")
        self.assertEqual(res["action"], "NONE")
        mock_halt.assert_not_called()

    @patch.object(ObstacleSafetyGuard, "query_distance_status")
    @patch.object(ObstacleSafetyGuard, "read_joycon_telemetry")
    @patch.object(ObstacleSafetyGuard, "dispatch_emergency_halt")
    def test_danger_zone_reverse_drive_allowed(self, mock_halt, mock_telem, mock_dist):
        """Obstacle in danger zone while reversing (throttle < 0) does not halt (allows backing out)."""
        mock_dist.return_value = {
            "object_detected": True,
            "in_danger_zone": True,
            "distance_cm": 12.0,
            "emergency_halt": False,
            "max_speed_pct": 35
        }
        mock_telem.return_value = {
            "drivetrain": {"throttle": -1.0},
            "buttons": {"a": False}
        }
        res = self.guard.step(now=100.0)
        self.assertEqual(res["state"], "NORMAL")
        self.assertEqual(res["action"], "NONE")
        mock_halt.assert_not_called()

    @patch.object(ObstacleSafetyGuard, "query_distance_status")
    @patch.object(ObstacleSafetyGuard, "read_joycon_telemetry")
    @patch.object(ObstacleSafetyGuard, "dispatch_emergency_halt")
    def test_danger_zone_forward_drive_triggers_lockout(self, mock_halt, mock_telem, mock_dist):
        """Obstacle in danger zone while driving forward triggers emergency halt and LOCKOUT."""
        mock_dist.return_value = {
            "object_detected": True,
            "in_danger_zone": True,
            "distance_cm": 15.0,
            "emergency_halt": False,
            "max_speed_pct": 35
        }
        mock_telem.return_value = {
            "drivetrain": {"throttle": 0.8},
            "buttons": {"a": False}
        }
        res = self.guard.step(now=100.0)
        self.assertEqual(res["state"], "LOCKOUT")
        self.assertEqual(res["action"], "TRIGGERED_LOCKOUT")
        mock_halt.assert_called_once_with(True)

    @patch.object(ObstacleSafetyGuard, "query_distance_status")
    @patch.object(ObstacleSafetyGuard, "read_joycon_telemetry")
    @patch.object(ObstacleSafetyGuard, "dispatch_emergency_halt")
    @patch.object(ObstacleSafetyGuard, "dispatch_speed_penalty")
    def test_recovery_requires_2s_hold(self, mock_speed, mock_halt, mock_telem, mock_dist):
        """Holding button A < 2s maintains LOCKOUT; holding >= 2s clears LOCKOUT and reduces speed to 50%."""
        self.guard.state = "LOCKOUT"
        self.guard.last_known_speed = 35

        mock_dist.return_value = {
            "object_detected": True,
            "in_danger_zone": True,
            "distance_cm": 15.0,
            "emergency_halt": True,
            "max_speed_pct": 35
        }
        mock_telem.return_value = {
            "drivetrain": {"throttle": 0.0},
            "buttons": {"a": True}
        }

        # Step 1: t=100.0, press button A
        res1 = self.guard.step(now=100.0)
        self.assertEqual(res1["state"], "LOCKOUT")
        self.assertEqual(res1["action"], "HOLDING_RECOVERY_BUTTON")
        mock_halt.assert_not_called()
        mock_speed.assert_not_called()

        # Step 2: t=101.5 (1.5s elapsed, < 2.0s)
        res2 = self.guard.step(now=101.5)
        self.assertEqual(res2["state"], "LOCKOUT")
        mock_halt.assert_not_called()
        mock_speed.assert_not_called()

        # Step 3: t=102.1 (2.1s elapsed, >= 2.0s) -> Recovery triggers!
        res3 = self.guard.step(now=102.1)
        self.assertEqual(res3["state"], "NORMAL")
        self.assertEqual(res3["action"], "CLEARED_LOCKOUT")
        mock_halt.assert_called_once_with(False)
        mock_speed.assert_called_once_with(17)  # 35 * 0.5 = 17


if __name__ == "__main__":
    unittest.main()
