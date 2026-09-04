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

    def _simulate_input(self, buttons: int, now: float):
        """Dispatches synthetic BLE report directly into production PokeballService.notification_handler."""
        center = self.service.joystick_center
        b2 = center & 0xFF
        b3 = ((center >> 8) & 0x0F) | ((center & 0x0F) << 4)
        b4 = (center >> 4) & 0xFF
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
        mock_backend.pokeball_service = mock_service

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


if __name__ == "__main__":
    unittest.main()
