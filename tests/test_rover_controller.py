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
        self.controller.accel_time_sec = 0.0  # Instant response for deterministic unit testing
        self.controller.decel_time_sec = 0.0
        self.controller.steering_trim = 0.0    # Baseline kinematics testing without trim bias
        self.controller.start()

    def tearDown(self):
        self.controller.stop()

    def test_config_loaded_rts(self):
        """Assert that assert_rts is True from rover_config.json."""
        self.assertTrue(self.controller.assert_rts)
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
        """adjust_speed_pct must step max_speed_pct and update max_pulse_offset atomically up and down."""
        self.assertEqual(self.controller.max_speed_pct, 35)

        # SR button: step up +5%
        new_speed = self.controller.adjust_speed_pct(5)
        self.assertEqual(new_speed, 40)
        self.assertEqual(self.controller.max_pulse_offset, 200)

        # SL button: step down -5%
        decreased_speed = self.controller.adjust_speed_pct(-5)
        self.assertEqual(decreased_speed, 35)
        self.assertEqual(self.controller.max_pulse_offset, 175)

        # SL button: step down again -5%
        decreased_speed2 = self.controller.adjust_speed_pct(-5)
        self.assertEqual(decreased_speed2, 30)
        self.assertEqual(self.controller.max_pulse_offset, 150)

    def test_throttle_gated_steering(self):
        """When enforce_throttle_gate is True and throttle is 0, steering must not move wheels."""
        self.controller.set_drive(1.0, 0.0, enforce_throttle_gate=True)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertEqual(telem["left_pulse"], 1500)
        self.assertEqual(telem["right_pulse"], 1500)

    def test_emergency_halt_clamping(self):
        """When emergency_halt is True, full forward throttle must be clamped to neutral 1500."""
        self.controller.set_drive(0.0, 1.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertGreater(telem["left_pulse"], 1500)

        # Trigger emergency halt
        self.controller.set_emergency_halt(True)
        time.sleep(0.1)
        halt_telem = self.controller.get_telemetry()
        self.assertTrue(halt_telem["emergency_halt"])
        self.assertEqual(halt_telem["left_pulse"], 1500)
        self.assertEqual(halt_telem["right_pulse"], 1500)

        # Clear emergency halt
        self.controller.set_emergency_halt(False)
        self.controller.set_drive(0.0, 1.0)
        time.sleep(0.1)
        resume_telem = self.controller.get_telemetry()
        self.assertFalse(resume_telem["emergency_halt"])
        self.assertGreater(resume_telem["left_pulse"], 1500)

    def test_set_max_speed_pct(self):
        """set_max_speed_pct must directly clamp speed and calculate max_pulse_offset."""
        new_speed = self.controller.set_max_speed_pct(50)
        self.assertEqual(new_speed, 50)
        self.assertEqual(self.controller.max_pulse_offset, 250)

    def test_distance_telemetry_ground_exclusion(self):
        """Readings >= ground_exclusion_adc (e.g. 62000) must be rejected as ground/open air."""
        self.controller._parse_stat_line("STAT:AUTO,1500,1500,0,0,1000,1000,1000,63000")
        telem = self.controller.get_telemetry()
        self.assertFalse(telem["object_detected"])
        self.assertIsNone(telem["distance_cm"])
        self.assertFalse(telem["in_danger_zone"])

    def test_distance_telemetry_danger_zone(self):
        """Readings corresponding to <= danger_zone_cm (e.g. 8000 ADC ~ 12.2 cm) must trigger danger zone."""
        self.controller._parse_stat_line("STAT:AUTO,1500,1500,0,0,1000,1000,1000,8000")
        telem = self.controller.get_telemetry()
        self.assertTrue(telem["object_detected"])
        self.assertIsNotNone(telem["distance_cm"])
        self.assertLessEqual(telem["distance_cm"], 15.0)
        self.assertTrue(telem["in_danger_zone"])

    def test_distance_telemetry_safe_zone(self):
        """Readings > danger_zone_cm (e.g. 32768 ADC ~ 50.0 cm) must not trigger danger zone."""
        self.controller._parse_stat_line("STAT:AUTO,1500,1500,0,0,1000,1000,1000,32768")
        telem = self.controller.get_telemetry()
        self.assertTrue(telem["object_detected"])
        self.assertAlmostEqual(telem["distance_cm"], 50.0, delta=1.0)
        self.assertFalse(telem["in_danger_zone"])


    def test_asymmetric_slew_timing(self):
        """Verifies that acceleration takes 2.0s (50 ticks) and deceleration takes 0.5s (13 ticks)."""
        accel_step = (1.0 / 2.0) / 25.0  # 0.020
        decel_step = (1.0 / 0.5) / 25.0  # 0.080

        # 1. Acceleration from 0.0 to 1.0
        val = 0.0
        for tick in range(1, 51):
            val = RoverController._apply_asymmetric_slew(val, 1.0, accel_step, decel_step)
            expected = round(tick * 0.020, 4)
            self.assertAlmostEqual(val, expected, places=3)
        self.assertAlmostEqual(val, 1.0, places=3)

        # 2. Deceleration from 1.0 to 0.0
        for tick in range(1, 13):
            val = RoverController._apply_asymmetric_slew(val, 0.0, accel_step, decel_step)
            expected = round(1.0 - (tick * 0.080), 4)
            self.assertAlmostEqual(val, expected, places=3)
        # At tick 13, it should reach 0.0 exactly
        val = RoverController._apply_asymmetric_slew(val, 0.0, accel_step, decel_step)
        self.assertEqual(val, 0.0)


if __name__ == "__main__":
    unittest.main()

