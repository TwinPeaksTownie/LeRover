#!/usr/bin/env python3
"""tests/test_joycon_teleop.py - Unit tests for JoyConService and JoyConApp logic.

Tests:
1. Fail-fast configuration loading.
2. Report 0x30 decoding: R forward (+1.0), ZR reverse (-1.0), neutral idle (0.0).
3. Strict throttle gating: horizontal stick deflection while idle suppresses steering to 0.0.
4. Real-time speed stepping (+5% on SR, -5% on SL).
5. Voice & Chord Abort events (Button B tap and A+B chord).
"""

import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
for p in [str(REPO_ROOT / "config"), str(REPO_ROOT / "pi4b")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from apps.joycon_app.app import JoyConService, JoyConApp, load_joycon_config, load_joycon_calibration
from rover.rover_controller import RoverController

CALIB = load_joycon_calibration()
DEFAULT_STICK_X = CALIB["center_x"]
DEFAULT_STICK_Y = CALIB["center_y"]


class MockRoverController:
    """Mock RoverController to capture drive commands and speed adjustments."""

    def __init__(self):
        self.last_x = 0.0
        self.last_y = 0.0
        self.speed_pct = 35
        self.max_pulse_offset = 175

    def set_drive(self, x: float, y: float, enforce_throttle_gate: bool = False):
        if enforce_throttle_gate and abs(y) < 0.01:
            self.last_x = 0.0
            self.last_y = 0.0
        else:
            self.last_x = float(x)
            self.last_y = float(y)

    def adjust_speed_pct(self, delta: int) -> int:
        self.speed_pct = max(10, min(100, self.speed_pct + int(delta)))
        self.max_pulse_offset = int(500 * (self.speed_pct / 100.0))
        return self.speed_pct


class TestJoyConTeleop(unittest.TestCase):
    """Verifies Joy-Con input decoding, strict throttle gating, and speed adjustments."""

    def setUp(self):
        self.service = JoyConService()
        self.mock_rover = MockRoverController()
        self.service.rover_ctrl = self.mock_rover
        self.service.teleop_enabled = True
        self.service.center_x = DEFAULT_STICK_X
        self.service.center_y = DEFAULT_STICK_Y
        self.service.zero_calibrated = True

    def _make_report(
        self,
        btn_r: bool = False,
        btn_zr: bool = False,
        btn_sr: bool = False,
        btn_sl: bool = False,
        btn_a: bool = False,
        btn_b: bool = False,
        stick_x: int = DEFAULT_STICK_X,
        stick_y: int = DEFAULT_STICK_Y
    ) -> bytes:
        """Constructs synthetic 49-byte Report 0x30."""
        buf = bytearray(49)
        buf[0] = 0x30
        buf[1] = 0x01
        buf[2] = 0x80  # Full battery

        # Byte 3: Right buttons
        b3 = 0
        if btn_b:
            b3 |= 0x04
        if btn_a:
            b3 |= 0x08
        if btn_sr:
            b3 |= 0x10
        if btn_sl:
            b3 |= 0x20
        if btn_r:
            b3 |= 0x40
        if btn_zr:
            b3 |= 0x80
        buf[3] = b3

        # Bytes 9-11: Right Stick (12-bit)
        buf[9] = stick_x & 0xFF
        buf[10] = ((stick_x >> 8) & 0x0F) | ((stick_y & 0x0F) << 4)
        buf[11] = (stick_y >> 4) & 0xFF

        return bytes(buf)

    def test_config_fail_fast(self):
        """Verifies that config loads with exact keys."""
        cfg = load_joycon_config()
        self.assertEqual(cfg["name"], "joycon_teleop_app")
        self.assertEqual(cfg["hardware"]["mac_address"], "5C:52:1E:1C:53:82")
        self.assertEqual(cfg["control"]["speed_step_pct"], 5)

    def test_forward_drive_r_button(self):
        """Holding R button alone must command forward throttle (+1.0)."""
        rep = self._make_report(btn_r=True)
        self.service._process_report_30(rep)
        self.assertEqual(self.service.telemetry["drivetrain"]["throttle"], 1.0)
        self.assertFalse(self.service.telemetry["drivetrain"]["gated_idle"])
        self.assertEqual(self.mock_rover.last_y, 1.0)

    def test_reverse_drive_zr_button(self):
        """Holding ZR button alone must command reverse throttle (-1.0)."""
        rep = self._make_report(btn_zr=True)
        self.service._process_report_30(rep)
        self.assertEqual(self.service.telemetry["drivetrain"]["throttle"], -1.0)
        self.assertFalse(self.service.telemetry["drivetrain"]["gated_idle"])
        self.assertEqual(self.mock_rover.last_y, -1.0)

    def test_idle_throttle_gated_steering(self):
        """When neither R nor ZR is held, horizontal stick deflection must NOT drive wheels."""
        # Deflect stick fully to the right (center + span -> norm_x = 1.0)
        deflected_x = int(DEFAULT_STICK_X + self.service.span_x)
        rep = self._make_report(btn_r=False, btn_zr=False, stick_x=deflected_x)
        self.service._process_report_30(rep)
        self.assertEqual(self.service.telemetry["drivetrain"]["throttle"], 0.0)
        self.assertEqual(self.service.telemetry["drivetrain"]["steering"], 0.0)
        self.assertTrue(self.service.telemetry["drivetrain"]["gated_idle"])
        self.assertEqual(self.mock_rover.last_x, 0.0)
        self.assertEqual(self.mock_rover.last_y, 0.0)

    def test_steering_while_forward(self):
        """When R is held, horizontal stick deflection must command steering."""
        deflected_x = int(DEFAULT_STICK_X + self.service.span_x)
        rep = self._make_report(btn_r=True, stick_x=deflected_x)
        self.service._process_report_30(rep)
        self.assertEqual(self.service.telemetry["drivetrain"]["throttle"], 1.0)
        self.assertGreater(self.service.telemetry["drivetrain"]["steering"], 0.5)
        self.assertGreater(self.mock_rover.last_x, 0.5)
        self.assertEqual(self.mock_rover.last_y, 1.0)

    def test_speed_step_sr_and_sl(self):
        """SR click must increase speed by 5%, SL click must decrease by 5%."""
        # Initial speed is 35%
        self.assertEqual(self.mock_rover.speed_pct, 35)

        # SR press
        rep_sr = self._make_report(btn_sr=True)
        self.service._process_report_30(rep_sr)
        self.assertEqual(self.mock_rover.speed_pct, 40)

        # SR release
        rep_rel = self._make_report(btn_sr=False)
        self.service._process_report_30(rep_rel)

        # Another SR press
        self.service._process_report_30(rep_sr)
        self.assertEqual(self.mock_rover.speed_pct, 45)

        # SL press
        self.service._process_report_30(rep_rel)
        rep_sl = self._make_report(btn_sl=True)
        self.service._process_report_30(rep_sl)
        self.assertEqual(self.mock_rover.speed_pct, 40)

    def test_voice_button_b_click(self):
        """Single click of B button must fire button_b_click_event."""
        self.service.button_b_click_event.clear()
        rep_b = self._make_report(btn_b=True)
        self.service._process_report_30(rep_b)
        self.assertTrue(self.service.button_b_click_event.is_set())

    def test_chord_abort_ab_hold(self):
        """Simultaneous hold of A + B for >= 1.0s must fire abort_audio_event."""
        self.service.abort_audio_event.clear()
        rep_ab = self._make_report(btn_a=True, btn_b=True)
        self.service._process_report_30(rep_ab)
        # Immediately should not have fired yet
        self.assertFalse(self.service.abort_audio_event.is_set())

        # Simulate 1.1s passing
        self.service.both_ab_press_start_time = time.time() - 1.1
        self.service._process_report_30(rep_ab)
        self.assertTrue(self.service.abort_audio_event.is_set())


if __name__ == "__main__":
    unittest.main()
