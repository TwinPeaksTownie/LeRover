#!/usr/bin/env python3
"""Unit tests for Beat Bandit Double B Button Press & Dynamic Center Homing Gesture.
Strictly validates:
  1. Fail-Fast Schema: Explicit AttributeError if app_manager or pokeball_service is unbound.
  2. Double-Click Recognition: Two Button B clicks within double_click_window_sec trigger stop_and_center.
  3. Single-Click Ignored: Single click or clicks separated by > window do not trigger stop_and_center.
  4. Dynamic Calibration Homing: Stand pose from presets_dance.json and S7/S8 centers from calibration_aux.json.
  5. Audio Cut & Confirmation Chime: Pi 4B audio stopped and app_exit_idle chime dispatched.
"""

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
PI500_DIR = REPO_ROOT / "pi500"
sys.path.insert(0, str(PI500_DIR))
sys.path.insert(0, str(REPO_ROOT / "apps" / "beat_bandit"))


from apps.beat_bandit.app import BeatBanditApp
from choreography_compiler import load_dance_presets


class TestBeatBanditFailFast(unittest.TestCase):
    """Verifies strict fail-fast validation in BeatBanditApp.run()."""

    def setUp(self):
        self.app = BeatBanditApp(running_on_pi=False)
        self.mock_backend = MagicMock()
        self.stop_event = threading.Event()

    def test_missing_app_manager_raises_attribute_error(self):
        self.app.app_manager = None
        with self.assertRaises(AttributeError) as ctx:
            self.app.run(self.mock_backend, self.stop_event)
        self.assertIn("authoritative app_manager", str(ctx.exception))

    def test_missing_pokeball_service_raises_attribute_error(self):
        self.app.app_manager = MagicMock()
        self.app.app_manager.pokeball_service = None
        with self.assertRaises(AttributeError) as ctx:
            self.app.run(self.mock_backend, self.stop_event)
        self.assertIn("authoritative app_manager.pokeball_service", str(ctx.exception))

    def test_missing_button_b_click_event_raises_attribute_error(self):
        self.app.app_manager = MagicMock()
        mock_service = MagicMock(spec=[])  # no button_b_click_event
        self.app.app_manager.pokeball_service = mock_service
        with self.assertRaises(AttributeError) as ctx:
            self.app.run(self.mock_backend, self.stop_event)
        self.assertIn("button_b_click_event", str(ctx.exception))


class TestBeatBanditDoubleClickGesture(unittest.TestCase):
    """Verifies double-click event handling and debounce timing in BeatBanditApp.run()."""

    def setUp(self):
        self.app = BeatBanditApp(running_on_pi=False)
        self.mock_backend = MagicMock()
        self.mock_backend.dispatch_dance_frame = MagicMock(return_value={"status": "ok"})

        self.mock_service = MagicMock()
        self.mock_service.button_b_click_event = threading.Event()

        self.mock_app_manager = MagicMock()
        self.mock_app_manager.pokeball_service = self.mock_service
        self.app.app_manager = self.mock_app_manager

    @patch.object(BeatBanditApp, "stop_and_center")
    def test_single_click_does_not_trigger_stop_and_center(self, mock_stop_and_center):
        stop_event = threading.Event()
        worker = threading.Thread(target=self.app.run, args=(self.mock_backend, stop_event), daemon=True)
        worker.start()

        # Fire single click
        self.mock_service.button_b_click_event.set()
        time.sleep(0.1)

        stop_event.set()
        worker.join(timeout=1.0)

        mock_stop_and_center.assert_not_called()

    @patch.object(BeatBanditApp, "stop_and_center")
    def test_spaced_clicks_do_not_trigger_stop_and_center(self, mock_stop_and_center):
        stop_event = threading.Event()
        worker = threading.Thread(target=self.app.run, args=(self.mock_backend, stop_event), daemon=True)
        worker.start()

        # First click
        self.mock_service.button_b_click_event.set()
        time.sleep(0.55)  # Greater than 0.45s window

        # Second click
        self.mock_service.button_b_click_event.set()
        time.sleep(0.1)

        stop_event.set()
        worker.join(timeout=1.0)

        mock_stop_and_center.assert_not_called()

    @patch.object(BeatBanditApp, "stop_and_center")
    def test_double_click_triggers_stop_and_center(self, mock_stop_and_center):
        stop_event = threading.Event()
        worker = threading.Thread(target=self.app.run, args=(self.mock_backend, stop_event), daemon=True)
        worker.start()

        # First click
        self.mock_service.button_b_click_event.set()
        time.sleep(0.1)

        # Second click within 0.45s
        self.mock_service.button_b_click_event.set()
        time.sleep(0.1)

        stop_event.set()
        worker.join(timeout=1.0)

        mock_stop_and_center.assert_called_once_with(self.mock_backend)


class TestDynamicCalibrationHoming(unittest.TestCase):
    """Verifies dynamic calibration arithmetic and actuator dispatch in stop_and_center()."""

    def setUp(self):
        self.app = BeatBanditApp(running_on_pi=False)
        self.mock_backend = MagicMock()
        self.mock_backend.dispatch_dance_frame = MagicMock(return_value={"status": "ok"})
        self.app.audio_client.stop_playback = MagicMock()

    @patch("apps.beat_bandit.app.dispatch_audio_event")
    def test_stop_and_center_actuation(self, mock_dispatch_audio):
        self.app.current_state = "DANCING"
        self.app.stop_and_center(self.mock_backend)

        # 1. State must be IDLE
        self.assertEqual(self.app.current_state, "IDLE")

        # 2. Audio stop must have been signaled
        self.app.audio_client.stop_playback.assert_called_once()

        # 3. Audio confirmation chime dispatched
        mock_dispatch_audio.assert_called_once_with(kind="app_exit_idle")

        # 4. Dynamic calibration homing frame dispatched
        self.mock_backend.dispatch_dance_frame.assert_called_once()
        call_args, call_kwargs = self.mock_backend.dispatch_dance_frame.call_args

        # Verify Servos 1-6 stand pose matches presets_dance.json dynamically
        poses = load_dance_presets()
        stand = poses["stand"]
        for motor_key in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]:
            self.assertIn(motor_key, stand)
        expected_arm_rom = {
            "shoulder_pan": float(stand["shoulder_pan"]),
            "shoulder_lift": float(stand["shoulder_lift"]),
            "elbow_flex": float(stand["elbow_flex"]),
            "wrist_flex": float(stand["wrist_flex"]),
            "wrist_roll": float(stand["wrist_roll"]),
            "gripper": float(stand["gripper"]),
        }
        self.assertEqual(call_args[0], expected_arm_rom)

        # Verify Servos 7 and 8 neutral ROM computed dynamically from calibration_aux.json
        calib_aux_file = REPO_ROOT / "calibration_aux.json"
        with open(calib_aux_file, "r", encoding="utf-8") as f:
            calib_aux = json.load(f)

        min_7 = float(calib_aux["7"]["min_ticks"])
        max_7 = float(calib_aux["7"]["max_ticks"])
        center_7 = float(calib_aux["7"]["center_ticks"])
        expected_s7_rom = round(((center_7 - min_7) / (max_7 - min_7)) * 100.0, 2)

        min_8 = float(calib_aux["8"]["min_ticks"])
        max_8 = float(calib_aux["8"]["max_ticks"])
        center_8 = float(calib_aux["8"]["center_ticks"])
        expected_s8_rom = round(((center_8 - min_8) / (max_8 - min_8)) * 100.0, 2)

        self.assertEqual(call_kwargs["s7_rom"], expected_s7_rom)
        self.assertEqual(call_kwargs["s8_goal"], expected_s8_rom)
        self.assertTrue(call_kwargs["s8_is_rom"])
        self.assertEqual(call_kwargs["s8_speed"], 500)


if __name__ == "__main__":
    unittest.main()
