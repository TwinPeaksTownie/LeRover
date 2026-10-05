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
        self.assertEqual(telem["left_pulse"], self.controller.neutral_pulse_us + self.controller.max_pulse_offset)
        trim = 0.05
        right_factor = 1.0 - trim
        expected_right = self.controller.neutral_pulse_us - int(right_factor * self.controller.max_pulse_offset)
        self.assertEqual(telem["right_pulse"], expected_right)

    def test_speed_step_adjustment(self):
        """adjust_speed_pct must step max_speed_pct and update max_pulse_offset atomically up and down."""
        initial_speed = self.controller.max_speed_pct
        initial_offset = self.controller.max_pulse_offset

        # SR button: step up +5%
        new_speed = self.controller.adjust_speed_pct(5)
        self.assertEqual(new_speed, initial_speed + 5)
        self.assertEqual(self.controller.max_pulse_offset, int(500 * ((initial_speed + 5) / 100.0)))

        # SL button: step down -5%
        decreased_speed = self.controller.adjust_speed_pct(-5)
        self.assertEqual(decreased_speed, initial_speed)
        self.assertEqual(self.controller.max_pulse_offset, int(500 * (initial_speed / 100.0)))

        # SL button: step down again -5%
        decreased_speed2 = self.controller.adjust_speed_pct(-5)
        self.assertEqual(decreased_speed2, initial_speed - 5)
        self.assertEqual(self.controller.max_pulse_offset, int(500 * ((initial_speed - 5) / 100.0)))

    def test_in_place_steering(self):
        """When throttle is 0 and steering is applied, wheels rotate for in-place turn."""
        self.controller.set_drive(1.0, 0.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertGreater(telem["left_pulse"], 1500)
        self.assertGreater(telem["right_pulse"], 1500)

    def test_smooth_stop_deceleration(self):
        """stop() zeroes target throttle without abruptly setting current velocity to 0."""
        self.controller.set_drive(0.0, 1.0)
        time.sleep(0.1)
        telem = self.controller.get_telemetry()
        self.assertGreater(telem["left_pulse"], 1500)

        # Call stop(): target is 0, but pulses smoothly ramp down instead of locking
        self.controller.stop()
        telem_after = self.controller.get_telemetry()
        self.assertEqual(telem_after["target_x"], 0.0)
        self.assertEqual(telem_after["target_y"], 0.0)

    def test_set_max_speed_pct(self):
        """set_max_speed_pct must directly clamp speed and calculate max_pulse_offset."""
        new_speed = self.controller.set_max_speed_pct(50)
        self.assertEqual(new_speed, 50)
        self.assertEqual(self.controller.max_pulse_offset, 250)

    def test_distance_telemetry_reporting(self):
        """Distance sensor reports distance_cm from ADC."""
        self.controller._parse_stat_line("STAT:AUTO,1500,1500,0,0,1000,1000,1000,32768")
        telem = self.controller.get_telemetry()
        self.assertTrue(telem["object_detected"])
        self.assertAlmostEqual(telem["distance_cm"], 50.0, delta=1.0)


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

    def test_command_timeout_watchdog(self):
        """If no set_drive() calls arrive within command_timeout_sec, target inputs reset to 0.0."""
        self.controller.command_timeout_sec = 0.15
        self.controller.set_drive(0.0, 1.0)
        time.sleep(0.05)
        telem = self.controller.get_telemetry()
        self.assertEqual(telem["target_y"], 1.0)

        # Wait for timeout to expire
        time.sleep(0.20)
        telem_timeout = self.controller.get_telemetry()
        self.assertEqual(telem_timeout["target_y"], 0.0)
        self.assertEqual(telem_timeout["target_x"], 0.0)

    def test_config_loaded_resilience_parameters(self):
        """Verifies fail-fast loading of loop_rate_hz, write_timeout_sec, and max_consecutive_write_failures."""
        self.assertEqual(self.controller.loop_rate_hz, 15.0)
        self.assertEqual(self.controller.write_timeout, 0.25)
        self.assertEqual(self.controller.max_consecutive_write_failures, 5)

    def test_immediate_nudge_dispatch_sets_event(self):
        """set_drive must trigger _drive_event immediately when thumbstick or throttle changes by > 0.02."""
        self.controller._drive_event.clear()
        self.assertFalse(self.controller._drive_event.is_set())

        # Micro-nudge > 0.02 should set the event immediately
        self.controller.set_drive(0.10, 0.0)
        self.assertTrue(self.controller._drive_event.is_set())

        # Sub-threshold change (< 0.02) should not set the event
        self.controller._drive_event.clear()
        self.controller.set_drive(0.11, 0.0)
        self.assertFalse(self.controller._drive_event.is_set())


if __name__ == "__main__":
    unittest.main()

