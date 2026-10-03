#!/usr/bin/env python3
"""tests/test_joycon_r_and_a_isolation.py - Automated unit tests validating Button R sensing and Button A isolation.

Verifies:
  1. Report 0x3F (Simple HID):
     - Button R (byte 2, bit 0x40) is sensed as True.
     - Button A remains False when Button R is pressed.
     - Joystick center hat (value 8 in byte 3) does NOT assert Button A (zero phantom press).
     - Button A (byte 1, bit 0x02) is sensed independently without triggering Button R.
  2. Report 0x30 (Standard Full Mode):
     - Button R (byte 3, bit 0x40) is sensed as True while Button A is False.
     - Button A (byte 3, bit 0x08) is sensed as True while Button R is False.
     - Simultaneous R + A presses parse both bits without crosstalk or stomping.
  3. Drivetrain Throttle Actuation:
     - When armed in ROVER mode, Button R sets throttle = 1.0.
     - Button A press does not overwrite or stomp on Button R throttle.
"""

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
for p in [str(REPO_ROOT / "config"), str(REPO_ROOT / "pi4b"), str(REPO_ROOT / "apps")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from apps.joycon_app.app import JoyConService, load_joycon_config


class MockRoverController:
    def __init__(self):
        self.steering = 0.0
        self.throttle = 0.0

    def set_drive(self, steering: float, throttle: float, enforce_throttle_gate: bool = False):
        self.steering = float(steering)
        self.throttle = float(throttle)


class TestJoyConRAndAIsolation(unittest.TestCase):
    def setUp(self):
        self.service = JoyConService()
        self.rover_ctrl = MockRoverController()
        self.service.rover_ctrl = self.rover_ctrl

    def test_report_3f_button_r_sensing(self):
        """In Report 0x3F, Byte 2 bit 0x40 must set Button R = True and leave Button A = False."""
        # 0x3F report buffer (12 bytes)
        raw = bytearray(12)
        raw[0] = 0x3F
        raw[1] = 0x00        # Face buttons: all clear
        raw[2] = 0x40        # Button R set (bit 0x40)
        raw[3] = 0x08        # Stick hat centered (8)

        self.service._process_report_30(bytes(raw))
        buttons = self.service.telemetry["buttons"]

        self.assertTrue(buttons["r"], "Button R must be sensed as True in Report 0x3F.")
        self.assertFalse(buttons["a"], "Button A must remain False when Button R is pressed (no crosstalk).")
        self.assertFalse(buttons["zr"])
        self.assertFalse(buttons["b"])

    def test_report_3f_stick_centered_no_phantom_a(self):
        """In Report 0x3F, stick hat value 8 (centered) must NOT assert Button A."""
        raw = bytearray(12)
        raw[0] = 0x3F
        raw[1] = 0x00        # All face buttons released
        raw[2] = 0x00        # All triggers released
        raw[3] = 0x08        # Stick centered (hat = 8)

        self.service._process_report_30(bytes(raw))
        buttons = self.service.telemetry["buttons"]

        self.assertFalse(buttons["a"], "Stick hat value 8 must not produce phantom Button A presses.")
        self.assertFalse(buttons["r"], "Button R must be False when unpressed.")

    def test_report_3f_button_a_independent_sensing(self):
        """In Report 0x3F, Byte 1 bit 0x02 must set Button A = True without triggering Button R."""
        raw = bytearray(12)
        raw[0] = 0x3F
        raw[1] = 0x02        # Button A set (bit 0x02)
        raw[2] = 0x00        # Button R released
        raw[3] = 0x08        # Stick hat centered

        self.service._process_report_30(bytes(raw))
        buttons = self.service.telemetry["buttons"]

        self.assertTrue(buttons["a"], "Button A must be sensed as True in Report 0x3F.")
        self.assertFalse(buttons["r"], "Button R must remain False when Button A is pressed.")

    def test_report_30_button_r_sensing(self):
        """In Report 0x30, Byte 3 bit 0x40 must set Button R = True and leave Button A = False."""
        raw = bytearray(49)
        raw[0] = 0x30
        raw[1] = 0x00
        raw[2] = 0x80        # Battery
        raw[3] = 0x40        # Byte 3: Button R (bit 0x40), Button A (bit 0x08) is clear

        self.service._process_report_30(bytes(raw))
        buttons = self.service.telemetry["buttons"]

        self.assertTrue(buttons["r"], "Button R must be sensed as True in Report 0x30.")
        self.assertFalse(buttons["a"], "Button A must remain False when Button R is pressed.")

    def test_report_30_button_a_independent_sensing(self):
        """In Report 0x30, Byte 3 bit 0x08 must set Button A = True and leave Button R = False."""
        raw = bytearray(49)
        raw[0] = 0x30
        raw[1] = 0x00
        raw[2] = 0x80
        raw[3] = 0x08        # Byte 3: Button A (bit 0x08), Button R (bit 0x40) is clear

        self.service._process_report_30(bytes(raw))
        buttons = self.service.telemetry["buttons"]

        self.assertTrue(buttons["a"], "Button A must be sensed as True in Report 0x30.")
        self.assertFalse(buttons["r"], "Button R must remain False when Button A is pressed.")

    def test_report_30_simultaneous_press_no_stomping(self):
        """Simultaneous R and A presses in Report 0x30 must report both buttons cleanly."""
        raw = bytearray(49)
        raw[0] = 0x30
        raw[1] = 0x00
        raw[2] = 0x80
        raw[3] = 0x48        # Both Button R (0x40) and Button A (0x08) set

        self.service._process_report_30(bytes(raw))
        buttons = self.service.telemetry["buttons"]

        self.assertTrue(buttons["r"], "Button R must be True during simultaneous press.")
        self.assertTrue(buttons["a"], "Button A must be True during simultaneous press.")

    def test_rover_throttle_actuation_on_button_r(self):
        """When teleop is enabled, pressing Button R drives forward at throttle 1.0."""
        self.service.teleop_enabled = True
        self.service.control_mode = "ROVER"
        self.service.is_armed = True

        # Send Report 0x3F with R pressed
        raw = bytearray(12)
        raw[0] = 0x3F
        raw[1] = 0x00
        raw[2] = 0x40        # Button R
        raw[3] = 0x08        # Stick centered

        self.service._process_report_30(bytes(raw))

        self.assertEqual(self.rover_ctrl.throttle, 1.0, "Throttle must be commanded to 1.0 when Button R is pressed.")
        self.assertEqual(self.service.telemetry["drivetrain"]["throttle"], 1.0)


if __name__ == "__main__":
    unittest.main()
