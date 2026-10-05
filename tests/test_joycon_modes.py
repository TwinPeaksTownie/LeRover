#!/usr/bin/env python3
"""tests/test_joycon_modes.py - Unit tests for Joy-Con controls in JoyConService/JoyConApp.

Tests:
1. Fail-fast configuration loading and direct bracket access.
2. Report 0x30 decoding: R forward (+1.0), ZR reverse (-1.0), strict throttle-gated steering.
3. Speed adjustments (+5% on SR rising edge, -5% on SL rising edge).
4. Binary Mode Switching:
   - Single tap Button B (< 2.0s) -> switches to AUX mode, locks rover drive to 0.0.
   - Hold Button A for 2.0s -> switches back to ROVER mode, arms drivetrain.
5. Persistent IDLE App Launching:
   - Hold Button A for 2.0s from IDLE -> launches joycon_teleop_app in ROVER mode.
   - Hold Button B for 2.0s from any app -> stops apps and launches listener_app.
6. Ephemeral Listener Integration:
   - Single tap Button B triggers start_listen_event.
   - Double tap Button B triggers abort_listen_event.
7. Decoupled AppManager transition:
   - switch_app() stops active app and launches target app in daemon thread.
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
for p in [str(REPO_ROOT / "config"), str(REPO_ROOT / "pi4b"), str(REPO_ROOT / "apps")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import apps.joycon_app.app as joycon_module
from apps.joycon_app.app import JoyConService, JoyConApp, load_joycon_config, load_joycon_calibration
from app_manager import AppManager, BaseApp, AppMetadata

CALIB_CENTER_X, CALIB_CENTER_Y, SPAN_X, SPAN_Y, MIN_RAW, MAX_RAW = load_joycon_calibration()


class MockRoverController:
    """Mock RoverController to capture drive commands and speed adjustments."""

    def __init__(self):
        self.last_x = 0.0
        self.last_y = 0.0
        self.speed_pct = 35
        self.max_pulse_offset = 175
        self.is_running = True

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

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False

    def shutdown(self):
        self.is_running = False

    def get_telemetry(self):
        return {"speed_pct": self.speed_pct, "x": self.last_x, "y": self.last_y}


class MockAppManager:
    """Mock AppManager to verify app launching and switching."""

    def __init__(self):
        self.current_app_name = None
        self.active_app = None
        self.stopped_all = False
        self.started_apps = []

    def stop_all(self):
        self.stopped_all = True
        self.current_app_name = None
        self.active_app = None

    def start_app_by_name(self, name: str, **kwargs):
        self.current_app_name = name
        self.started_apps.append((name, kwargs))
        return True


class TestJoyConModes(unittest.TestCase):
    """Test suite for Joy-Con controls running inside JoyConService."""

    def setUp(self):
        self.mock_app_mgr = MockAppManager()
        self.mock_rover = MockRoverController()
        self.service = JoyConService(app_manager=self.mock_app_mgr)
        self.service.rover_ctrl = self.mock_rover
        self.service.teleop_enabled = True
        self.service.center_x = CALIB_CENTER_X
        self.service.center_y = CALIB_CENTER_Y
        self.service.span_x = SPAN_X
        self.service.span_y = SPAN_Y
        self.service.zero_calibrated = True

    def _make_report(
        self,
        btn_r: bool = False,
        btn_zr: bool = False,
        btn_sr: bool = False,
        btn_sl: bool = False,
        btn_a: bool = False,
        btn_b: bool = False,
        stick_x: int = CALIB_CENTER_X,
        stick_y: int = CALIB_CENTER_Y
    ) -> bytes:
        """Constructs synthetic 49-byte Joy-Con Report 0x30."""
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

    def test_config_fail_fast_schema(self):
        """Verifies fail-fast loading with direct bracket access."""
        cfg = load_joycon_config()
        self.assertEqual(cfg["name"], "joycon_teleop_app")
        self.assertEqual(cfg["hardware"]["mac_address"], "5C:52:1E:1C:53:82")
        self.assertEqual(cfg["hardware"]["vendor_id"], 1406)
        self.assertEqual(cfg["gestures"]["a_hold_sec"], 2.0)
        self.assertEqual(cfg["gestures"]["b_hold_sec"], 2.0)
        self.assertEqual(cfg["chimes"]["arm_rover"], "rover_arm_drivetrain")
        self.assertEqual(cfg["chimes"]["mode_switch_aux"], "mode_switch_aux")

    @patch("apps.joycon_app.app.play_chime")
    def test_forward_and_reverse_throttle(self, mock_chime):
        """R button moves forward (+1.0); ZR trigger moves reverse (-1.0)."""
        self.service.is_armed = True
        self.service.control_mode = "ROVER"

        # R alone
        rep_fwd = self._make_report(btn_r=True)
        self.service._process_report_30(rep_fwd)
        self.assertEqual(self.service.telemetry["drivetrain"]["throttle"], 1.0)
        self.assertFalse(self.service.telemetry["drivetrain"]["gated_idle"])
        self.assertEqual(self.mock_rover.last_y, 1.0)

        # ZR alone
        rep_rev = self._make_report(btn_zr=True)
        self.service._process_report_30(rep_rev)
        self.assertEqual(self.service.telemetry["drivetrain"]["throttle"], -1.0)
        self.assertFalse(self.service.telemetry["drivetrain"]["gated_idle"])
        self.assertEqual(self.mock_rover.last_y, -1.0)

    def test_idle_throttle_gated_steering(self):
        """When neither R nor ZR is held, throttle is 0.0 and steering is suppressed to 0.0 (strict throttle gating)."""
        self.service.is_armed = True
        self.service.control_mode = "ROVER"

        deflected_x = int(CALIB_CENTER_X + SPAN_X)
        rep_idle = self._make_report(btn_r=False, btn_zr=False, stick_x=deflected_x)
        self.service._process_report_30(rep_idle)

        self.assertEqual(self.service.telemetry["drivetrain"]["throttle"], 0.0)
        self.assertEqual(self.service.telemetry["drivetrain"]["steering"], 0.0)
        self.assertTrue(self.service.telemetry["drivetrain"]["gated_idle"])
        self.assertEqual(self.mock_rover.last_x, 0.0)
        self.assertEqual(self.mock_rover.last_y, 0.0)

    @patch("apps.joycon_app.app.play_chime")
    def test_speed_stepping_sr_sl(self, mock_chime):
        """SR steps up speed by +5%; SL steps down speed by -5%."""
        self.assertEqual(self.mock_rover.speed_pct, 35)

        # Press SR
        rep_sr = self._make_report(btn_sr=True)
        self.service._process_report_30(rep_sr)
        self.assertEqual(self.mock_rover.speed_pct, 40)
        mock_chime.assert_called_with("correct")

        # Release SR
        rep_neutral = self._make_report(btn_sr=False)
        self.service._process_report_30(rep_neutral)

        # Press SL
        rep_sl = self._make_report(btn_sl=True)
        self.service._process_report_30(rep_sl)
        self.assertEqual(self.mock_rover.speed_pct, 35)
        mock_chime.assert_called_with("incorrect")

    @patch("apps.joycon_app.app.play_chime")
    def test_mode_switch_to_aux_on_b_click(self, mock_chime):
        """Single click of Button B while in teleop switches to AUX mode and stops rover."""
        self.service.control_mode = "ROVER"
        self.service.is_armed = True
        self.mock_rover.last_y = 1.0

        # Press B
        rep_press = self._make_report(btn_b=True)
        self.service._process_report_30(rep_press)
        self.assertEqual(self.service.control_mode, "ROVER")  # Not yet released

        # Fast forward 0.1s and release B (< 2.0s hold)
        self.service.btn_b_press_start_time = time.time() - 0.1
        rep_rel = self._make_report(btn_b=False)
        self.service._process_report_30(rep_rel)

        self.assertEqual(self.service.control_mode, "AUX")
        self.assertFalse(self.service.is_armed)
        self.assertEqual(self.mock_rover.last_x, 0.0)
        self.assertEqual(self.mock_rover.last_y, 0.0)
        mock_chime.assert_called_with("mode_switch_aux")

    @patch("apps.joycon_app.app.play_chime")
    def test_mode_switch_to_rover_on_a_hold(self, mock_chime):
        """Holding Button A for 2.0s switches from AUX back to ROVER mode and arms drivetrain."""
        self.service.control_mode = "AUX"
        self.service.is_armed = False

        # Press A
        rep_a = self._make_report(btn_a=True)
        self.service._process_report_30(rep_a)
        self.assertEqual(self.service.control_mode, "AUX")  # Not yet held 2.0s

        # Simulate 2.1s hold
        self.service.btn_a_press_start_time = time.time() - 2.1
        self.service._process_report_30(rep_a)

        self.assertEqual(self.service.control_mode, "ROVER")
        self.assertTrue(self.service.is_armed)
        mock_chime.assert_called_with("rover_arm_drivetrain")

    @patch("apps.joycon_app.app.play_chime")
    def test_neutral_at_arm_prevent_lurch(self, mock_chime):
        """Holding Button A while R is also held must NOT arm the drivetrain until R is released."""
        self.service.control_mode = "AUX"
        self.service.is_armed = False

        # Press A + R simultaneously
        rep_a_r = self._make_report(btn_a=True, btn_r=True)
        self.service._process_report_30(rep_a_r)

        # Simulate 2.1s hold while R is still held
        self.service.btn_a_press_start_time = time.time() - 2.1
        self.service._process_report_30(rep_a_r)

        # Must still be disarmed because R is pressed
        self.assertFalse(self.service.is_armed)
        self.assertEqual(self.service.control_mode, "AUX")

        # Now release R (only A is held)
        rep_a_only = self._make_report(btn_a=True, btn_r=False)
        self.service._process_report_30(rep_a_only)

        # Now it arms!
        self.assertTrue(self.service.is_armed)
        self.assertEqual(self.service.control_mode, "ROVER")

    @patch("apps.joycon_app.app.play_chime")
    def test_idle_hold_a_launches_teleop_app(self, mock_chime):
        """Holding Button A for 2.0s from IDLE state launches joycon_teleop_app."""
        self.service.teleop_enabled = False
        self.mock_app_mgr.current_app_name = None

        rep_a = self._make_report(btn_a=True)
        self.service._process_report_30(rep_a)

        # Simulate 2.1s hold
        self.service.btn_a_press_start_time = time.time() - 2.1
        self.service._process_report_30(rep_a)

        self.assertEqual(self.service.control_mode, "ROVER")
        self.assertTrue(self.service.teleop_enabled)
        self.assertTrue(self.service.is_armed)
        time.sleep(0.05)  # Let worker thread fire
        self.assertTrue(self.mock_app_mgr.stopped_all)
        self.assertEqual(self.mock_app_mgr.current_app_name, "joycon_teleop_app")

    @patch("apps.joycon_app.app.play_chime")
    def test_hold_b_launches_listener_app(self, mock_chime):
        """Holding Button B for 2.0s stops active app and launches listener_app."""
        self.mock_app_mgr.current_app_name = "beat_bandit_app"

        rep_b = self._make_report(btn_b=True)
        self.service._process_report_30(rep_b)

        # Simulate 2.1s hold
        self.service.btn_b_press_start_time = time.time() - 2.1
        self.service._process_report_30(rep_b)

        time.sleep(0.05)
        self.assertTrue(self.mock_app_mgr.stopped_all)
        self.assertEqual(self.mock_app_mgr.current_app_name, "listener_app")
        mock_chime.assert_called_with("app_start")

    @patch("apps.joycon_app.app.play_chime")
    def test_listener_app_single_and_double_tap_b(self, mock_chime):
        """In listener_app, single tap B triggers start_listen, double tap B triggers abort_listen."""
        mock_listener = MagicMock()
        mock_listener.start_listen_event = MagicMock()
        mock_listener.abort_listen_event = MagicMock()
        self.mock_app_mgr.current_app_name = "listener_app"
        self.mock_app_mgr.active_app = mock_listener

        # Single tap B
        rep_press = self._make_report(btn_b=True)
        self.service._process_report_30(rep_press)
        self.service.btn_b_press_start_time = time.time() - 0.1
        rep_rel = self._make_report(btn_b=False)
        self.service._process_report_30(rep_rel)

        mock_listener.start_listen_event.set.assert_called_once()
        mock_listener.abort_listen_event.set.assert_not_called()

        # Double tap B (quick successive click within 0.4s)
        rep_press2 = self._make_report(btn_b=True)
        self.service._process_report_30(rep_press2)
        self.service.btn_b_press_start_time = time.time() - 0.1
        self.service._process_report_30(rep_rel)

        mock_listener.abort_listen_event.set.assert_called_once()
        mock_chime.assert_called_with("ornith_abort_recording")


if __name__ == "__main__":
    unittest.main()
