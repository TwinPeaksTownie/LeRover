#!/usr/bin/env python3
"""tests/test_audio_and_gestures.py - Test suite for audio resolver, gestures, and app lifecycle."""

import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "config"))
sys.path.insert(0, str(REPO_ROOT / "pi500"))
sys.path.insert(0, str(REPO_ROOT / "apps"))

import audio_resolver
from apps.pokeball_app.app import PokeballService
from apps.ornith_voice.app import OrnithVoiceApp


class TestAudioResolver(unittest.TestCase):
    """Verifies audio_files.json schema enforcement and event mapping."""

    def test_audio_config_keys(self):
        config = audio_resolver.load_audio_config(force_reload=True)
        events = config["events"]

        # Required semantic events
        required = [
            ("device_connect", "smw_coin.wav"),
            ("app_start", "smw_riding_yoshi.wav"),
            ("ornith_app_start", "smw_switch_activated.wav"),
            ("ornith_listen_start", "smw_whistle.wav"),
            ("ornith_commit_speech", "smw_midway_gate.wav"),
            ("ornith_abort_recording", "smw_switch_timer_ending.wav"),
            ("rover_arm_drivetrain", "mario_kart_start.wav"),
            ("rover_emergency_brake", "smw_yoshi_runs_away.wav"),
            ("app_exit_idle", "smw_goal_iris-out.wav"),
            ("smw_save_menu", "smw_save_menu.wav"),
        ]

        for ev_key, expected_file in required:
            self.assertIn(ev_key, events, f"Missing event key: {ev_key}")
            self.assertEqual(audio_resolver.get_audio_filename(ev_key), expected_file)

    def test_fail_fast_on_unknown_event(self):
        with self.assertRaises(KeyError):
            audio_resolver.get_audio_filename("non_existent_random_sound_key")


class TestPokeballServiceGestures(unittest.TestCase):
    """Tests A+B chord hold, rover arm hold, and emergency brake."""

    def setUp(self):
        self.service = PokeballService(api_url="http://127.0.0.1:8085")
        self.service.logger = MagicMock()

    @patch("apps.pokeball_app.app.play_chime")
    def test_chord_abort_detection(self, mock_play_chime):
        """Simultaneous A + B held for 1.0s must set abort_audio_event."""
        t0 = 100.0
        # Button A (0x02) + Button B (0x01) = 0x03
        buttons = 0x03

        # Frame 1: Chord begins
        with patch("time.time", return_value=t0):
            self._simulate_input(buttons=0x03, now=t0)
            self.assertFalse(self.service.abort_audio_event.is_set())
            self.assertFalse(self.service.ab_hold_triggered)

        # Frame 2: 0.5s held (under 1.0s)
        with patch("time.time", return_value=t0 + 0.5):
            self._simulate_input(buttons=0x03, now=t0 + 0.5)
            self.assertFalse(self.service.abort_audio_event.is_set())

        # Frame 3: 1.0s reached -> Abort triggered!
        with patch("time.time", return_value=t0 + 1.05):
            self._simulate_input(buttons=0x03, now=t0 + 1.05)
            self.assertTrue(self.service.abort_audio_event.is_set())
            self.assertTrue(self.service.ab_hold_triggered)

    @patch("apps.pokeball_app.app.play_chime")
    def test_rover_arm_hold_and_brake(self, mock_play_chime):
        """Holding Button A for 2.0s arms drivetrain with 4.25s lockout. Button B emergency brakes."""
        self.service.teleop_enabled = True
        self.service.rover_ctrl = MagicMock()
        t0 = 200.0

        # Press Button A (0x02)
        with patch("time.time", return_value=t0):
            self._simulate_input(buttons=0x02, now=t0)
            self.assertFalse(self.service.is_armed)

        # 1.5s (under 2.0s)
        with patch("time.time", return_value=t0 + 1.5):
            self._simulate_input(buttons=0x02, now=t0 + 1.5)
            self.assertFalse(self.service.is_armed)

        # 2.0s reached -> armed!
        with patch("time.time", return_value=t0 + 2.05):
            self._simulate_input(buttons=0x02, now=t0 + 2.05)
            self.assertTrue(self.service.is_armed)
            self.assertAlmostEqual(self.service.arm_lockout_until, t0 + 2.05 + 4.25, delta=0.01)
            mock_play_chime.assert_called_with("rover_arm_drivetrain")

        # Now tap Button B (0x01) -> Instant Emergency Brake!
        t_tap = t0 + 3.0
        with patch("time.time", return_value=t_tap):
            self._simulate_input(buttons=0x01, now=t_tap)
        with patch("time.time", return_value=t_tap + 0.1):
            self._simulate_input(buttons=0x00, now=t_tap + 0.1)
            self.assertFalse(self.service.is_armed)
            self.assertEqual(self.service.arm_lockout_until, 0.0)
            self.service.rover_ctrl.stop.assert_called()
            mock_play_chime.assert_called_with("rover_emergency_brake")

    @patch("apps.pokeball_app.app.play_chime")
    def test_button_b_hold_launches_listener_app(self, mock_play_chime):
        """Holding Button B for 3.0s must launch listener_app via AppManager."""
        self.service.app_manager = MagicMock()
        t0 = 300.0

        # Press Button B (0x01)
        with patch("time.time", return_value=t0):
            self._simulate_input(buttons=0x01, now=t0)
            self.assertFalse(self.service.b_hold_triggered)
            self.service.app_manager.start_app_by_name.assert_not_called()

        # Hold for 3.05s -> ListenerApp triggered!
        with patch("time.time", return_value=t0 + 3.05):
            with patch("threading.Thread") as mock_thread:
                self._simulate_input(buttons=0x01, now=t0 + 3.05)
                self.assertTrue(self.service.b_hold_triggered)
                mock_thread.assert_called_once_with(
                    target=self.service.app_manager.start_app_by_name,
                    args=("listener_app",),
                    daemon=True,
                )
                mock_thread.return_value.start.assert_called_once()

    def test_gantry_up_plus_b_nudges_right(self):
        """Tilting stick UP (norm_y > 0.35) and pressing Button B must dispatch /api/nudge_physical with direction='right'."""
        self.service.teleop_enabled = True
        self.service.is_armed = False
        self.service.zero_calibrated = True
        t0 = 500.0

        # Simulate stick UP (raw_y = center_y + 1000) with Button B (0x01)
        up_y = self.service.joystick_center_y + 1000
        with patch.object(self.service, "_send_aux_request") as mock_aux:
            with patch("time.time", return_value=t0):
                self._simulate_input(buttons=0x01, now=t0, raw_y=up_y)
                mock_aux.assert_called_once_with(
                    "/api/nudge_physical",
                    {"id": 8, "direction": "right", "amount": self.service.gantry_step_ticks},
                    lock_duration=self.service.aux_lock_duration_sec
                )

    def test_gantry_down_plus_b_nudges_left(self):
        """Tilting stick DOWN (norm_y < -0.35) and pressing Button B must dispatch /api/nudge_physical with direction='left'."""
        self.service.teleop_enabled = True
        self.service.is_armed = False
        self.service.zero_calibrated = True
        t0 = 600.0

        # Simulate stick DOWN (raw_y = center_y - 1000) with Button B (0x01)
        down_y = self.service.joystick_center_y - 1000
        with patch.object(self.service, "_send_aux_request") as mock_aux:
            with patch("time.time", return_value=t0):
                self._simulate_input(buttons=0x01, now=t0, raw_y=down_y)
                mock_aux.assert_called_once_with(
                    "/api/nudge_physical",
                    {"id": 8, "direction": "left", "amount": self.service.gantry_step_ticks},
                    lock_duration=self.service.aux_lock_duration_sec
                )

    def test_pedestal_left_right_plus_b(self):
        """Tilting stick RIGHT (norm_x > 0.35) and pressing Button B must dispatch /api/pedestal_step with direction='right'."""
        self.service.teleop_enabled = True
        self.service.is_armed = False
        self.service.zero_calibrated = True
        t0 = 700.0

        right_x = self.service.joystick_center_x + 1000
        with patch.object(self.service, "_send_aux_request") as mock_aux:
            with patch("time.time", return_value=t0):
                self._simulate_input(buttons=0x01, now=t0, raw_x=right_x)
                mock_aux.assert_called_once_with(
                    "/api/pedestal_step",
                    {"direction": "right"},
                    lock_duration=self.service.aux_lock_duration_sec
                )

    def _simulate_input(self, buttons: int, now: float, raw_x: Optional[int] = None, raw_y: Optional[int] = None):
        """Dispatches synthetic BLE report directly into production PokeballService.notification_handler."""
        rx = self.service.joystick_center_x if raw_x is None else raw_x
        ry = self.service.joystick_center_y if raw_y is None else raw_y
        b2 = rx & 0xFF
        b3 = ((rx >> 8) & 0x0F) | ((ry & 0x0F) << 4)
        b4 = (ry >> 4) & 0xFF
        data = bytearray([0x00, buttons, b2, b3, b4])
        with patch("time.time", return_value=now):
            self.service.notification_handler(None, data)


class TestOrnithVoiceCadence(unittest.TestCase):
    """Tests double-click commit and chord abort in OrnithVoiceApp executing production code."""

    def setUp(self):
        self.app = OrnithVoiceApp(running_on_pi=False)
        self.app.logger = MagicMock()
        self.app._play_pi4b_sound = MagicMock()
        self.app._set_kiosk_state = MagicMock()
        self.app._cancel_robot_mic = MagicMock()
        self.app._handle_voice_turn = MagicMock()
        self.app._start_robot_mic = MagicMock()

    def test_double_click_commit_logic(self):
        """First click in LISTENING waits; second click within 1.0s commits speech turn."""
        self.app.state = "LISTENING"
        stop_ev = threading.Event()
        t0 = 500.0

        # Click 1: executes real production method process_button_b_click
        committed = self.app.process_button_b_click(now=t0, stop_event=stop_ev)
        self.assertFalse(committed)
        self.assertEqual(self.app.last_b_click_time, t0)
        self.app._handle_voice_turn.assert_not_called()

        # Click 2 within 0.4s: executes real production method process_button_b_click
        committed = self.app.process_button_b_click(now=t0 + 0.4, stop_event=stop_ev)
        self.assertTrue(committed)
        self.assertEqual(self.app.last_b_click_time, 0.0)
        self.app._handle_voice_turn.assert_called_once_with(stop_ev)

    def test_double_click_timeout_resets(self):
        """Click 2 after > 1.0s resets timer and does not commit."""
        self.app.state = "LISTENING"
        stop_ev = threading.Event()
        t0 = 500.0

        # Click 1: executes production code
        committed = self.app.process_button_b_click(now=t0, stop_event=stop_ev)
        self.assertFalse(committed)
        self.assertEqual(self.app.last_b_click_time, t0)

        # Click 2 after 1.5s (> double_click_window_sec): executes production code
        committed = self.app.process_button_b_click(now=t0 + 1.5, stop_event=stop_ev)
        self.assertFalse(committed)
        self.assertEqual(self.app.last_b_click_time, t0 + 1.5)
        self.app._handle_voice_turn.assert_not_called()

    def test_button_b_click_in_awaiting_input(self):
        """Click on Button B while in AWAITING_INPUT triggers a listening turn."""
        self.app.state = "AWAITING_INPUT"
        stop_ev = threading.Event()
        self.app._start_listening_turn = MagicMock()

        committed = self.app.process_button_b_click(now=100.0, stop_event=stop_ev)
        self.assertFalse(committed)
        self.app._start_listening_turn.assert_called_once()

    def test_run_loop_drives_real_events(self):
        """Tests that OrnithVoiceApp.run() loop processes abort_audio_event and button_b_click_event."""
        mock_backend = MagicMock()
        mock_service = MagicMock()
        mock_service.button_b_click_event = threading.Event()
        mock_service.abort_audio_event = threading.Event()
        mock_app_mgr = MagicMock()
        mock_app_mgr.pokeball_service = mock_service
        self.app.app_manager = mock_app_mgr

        self.app.state = "LISTENING"
        self.app.recording_start_time = 500.0
        self.app.last_b_click_time = 500.0
        stop_event = threading.Event()

        def _mock_handle_turn(ev):
            self.app.state = "THINKING"
        self.app._handle_voice_turn.side_effect = _mock_handle_turn

        # Sequence: Click 1 at 500.0, Click 2 at 500.3 (within 1.0s double click window)
        timeline = [500.0, 500.0, 500.3, 500.3, 500.4, 500.5, 500.6, 500.7]
        def _fake_time():
            if timeline:
                return timeline.pop(0)
            return 500.8

        def _event_feeder():
            time.sleep(0.02)
            # Click 1
            mock_service.button_b_click_event.set()
            time.sleep(0.06)
            # Click 2
            mock_service.button_b_click_event.set()
            time.sleep(0.06)
            stop_event.set()

        with patch("time.time", side_effect=_fake_time):
            t = threading.Thread(target=_event_feeder)
            t.start()
            self.app.run(mock_backend, stop_event)
            t.join()

        # Verify that double-click commit was executed through run()
        self.app._handle_voice_turn.assert_called_once()
        self.assertFalse(mock_service.button_b_click_event.is_set())


class TestJoystickCalibration(unittest.TestCase):
    """Verifies fail-fast loading of Pokéball joystick calibration."""

    def test_calibration_success(self):
        from apps.pokeball_app.app import load_joystick_calibration
        with open(REPO_ROOT / "calibration_aux.json", "r", encoding="utf-8") as f:
            expected = json.load(f)["pokeball_joystick"]
        cx, cy = load_joystick_calibration()
        self.assertIsInstance(cx, int)
        self.assertIsInstance(cy, int)
        self.assertEqual(cx, expected["center_x"])
        self.assertEqual(cy, expected["center_y"])

    def test_calibration_missing_block_raises_keyerror(self):
        from apps.pokeball_app.app import load_joystick_calibration
        bad_calib = {"7": {"center_ticks": 2400}}
        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(bad_calib))):
            with patch("os.path.exists", return_value=True):
                with self.assertRaises(KeyError):
                    load_joystick_calibration()


class TestClackTapDetectorLifecycle(unittest.TestCase):
    """Verifies AudioTapDetector active gating and AppManager stop callback dispatch."""

    def test_app_manager_stop_callback_invoked(self):
        from pi4b.app_manager import AppManager, BaseApp, AppMetadata

        mock_backend = MagicMock()
        mgr = AppManager(backend=mock_backend)

        class DummyApp(BaseApp):
            metadata = AppMetadata(name="test_dummy_app")
            def __init__(self):
                super().__init__()
                self.config = {"chimes": {"app_start": "app_start"}}
            def run(self, backend, stop_event):
                while not stop_event.is_set():
                    time.sleep(0.01)

        mgr.register_app(DummyApp)
        stopped_apps = []
        mgr.register_stop_callback(lambda name: stopped_apps.append(name))

        with patch("pi4b.app_manager.dispatch_audio_event"):
            ok = mgr.start_app_by_name("test_dummy_app")
            self.assertTrue(ok)
            self.assertEqual(mgr.current_app_name, "test_dummy_app")

            mgr.stop_app("test_dummy_app")
        self.assertIn("test_dummy_app", stopped_apps)
        self.assertIsNone(mgr.current_app_name)

    def test_audio_tap_detector_is_active_gate(self):
        sys.path.insert(0, str(REPO_ROOT / "pi4b"))
        from audio_tap_detector import AudioTapDetector

        mock_sound_cb = MagicMock()
        is_active = False

        detector = AudioTapDetector(
            play_sound_cb=mock_sound_cb,
            is_active_cb=lambda: is_active
        )

        # When inactive: action dispatch must be rejected and play zero sounds
        detector._dispatch_action(1, [], 5000)
        mock_sound_cb.assert_not_called()

        # When inactive: tap detected must be ignored
        with patch.object(detector, "_dispatch_action") as mock_dispatch:
            detector._on_tap_detected(5000)
            mock_dispatch.assert_not_called()

        # When active: action dispatch executes
        is_active = True
        with patch("urllib.request.urlopen"):
            detector._dispatch_action(1, [], 5000)
        mock_sound_cb.assert_called_with("smw_stomp_bones")


if __name__ == "__main__":
    unittest.main()
