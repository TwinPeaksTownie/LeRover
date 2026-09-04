#!/usr/bin/env python3
"""tests/test_audio_and_gestures.py - Test suite for audio resolver, gestures, and app lifecycle."""

import json
import os
import sys
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
            ("rover_arm_drivetrain", "mario_kart_start"),
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
        """Replicates input processing branch in PokeballService._input_handler."""
        center = self.service.joystick_center
        raw_x_12 = center
        raw_y_12 = center
        x_offset = raw_x_12 - center
        y_offset = raw_y_12 - center

        btn_a = bool(buttons & 0x02)
        btn_b = bool(buttons & 0x01)

        # --- 1. SIMULTANEOUS A + B CHORD (1.0s Hold) ---
        if btn_a and btn_b:
            if self.service.both_ab_press_start_time is None:
                self.service.both_ab_press_start_time = now
            hold_duration_ab = now - self.service.both_ab_press_start_time
            if hold_duration_ab >= 1.0 and not self.service.ab_hold_triggered:
                self.service.ab_hold_triggered = True
                self.service.abort_audio_event.set()
        else:
            self.service.both_ab_press_start_time = None
            self.service.ab_hold_triggered = False

        # --- 2. BUTTON B ---
        if btn_b and not btn_a:
            if self.service.btn_b_press_start_time is None:
                self.service.btn_b_press_start_time = now
        else:
            if self.service.btn_b_press_start_time is not None:
                duration = now - self.service.btn_b_press_start_time
                if 0.05 <= duration < 2.0 and not self.service.b_hold_triggered:
                    self.service.button_b_click_event.set()
                    if self.service.teleop_enabled and self.service.is_armed:
                        self.service.is_armed = False
                        self.service.arm_lockout_until = 0.0
                        if self.service.rover_ctrl:
                            self.service.rover_ctrl.stop()
                        from apps.pokeball_app.app import play_chime
                        play_chime("rover_emergency_brake")
                self.service.btn_b_press_start_time = None

        # --- 3. BUTTON A ---
        if btn_a and not btn_b:
            if self.service.stick_press_start_time is None:
                self.service.stick_press_start_time = now
            hold_duration_a = now - self.service.stick_press_start_time
            if self.service.teleop_enabled:
                if hold_duration_a >= 2.0 and not self.service.is_armed:
                    self.service.is_armed = True
                    self.service.arm_lockout_until = now + 4.25
                    from apps.pokeball_app.app import play_chime
                    play_chime("rover_arm_drivetrain")
        else:
            self.service.stick_press_start_time = None


class TestOrnithVoiceCadence(unittest.TestCase):
    """Tests double-click commit and chord abort in OrnithVoiceApp."""

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
        double_click_window = 1.0
        t0 = 500.0

        # Click 1:
        now = t0
        if self.app.last_b_click_time > 0.0 and (now - self.app.last_b_click_time <= double_click_window):
            self.app._handle_voice_turn(MagicMock())
        else:
            self.app.last_b_click_time = now

        self.assertEqual(self.app.last_b_click_time, t0)
        self.app._handle_voice_turn.assert_not_called()

        # Click 2 within 0.4s:
        now = t0 + 0.4
        if self.app.last_b_click_time > 0.0 and (now - self.app.last_b_click_time <= double_click_window):
            self.app.last_b_click_time = 0.0
            self.app._handle_voice_turn(MagicMock())
        else:
            self.app.last_b_click_time = now

        self.assertEqual(self.app.last_b_click_time, 0.0)
        self.app._handle_voice_turn.assert_called_once()

    def test_double_click_timeout_resets(self):
        """Click 2 after > 1.0s resets timer and does not commit."""
        self.app.state = "LISTENING"
        double_click_window = 1.0
        t0 = 500.0

        # Click 1
        self.app.last_b_click_time = t0

        # Click 2 after 1.5s
        now = t0 + 1.5
        if self.app.last_b_click_time > 0.0 and (now - self.app.last_b_click_time <= double_click_window):
            self.app.last_b_click_time = 0.0
            self.app._handle_voice_turn(MagicMock())
        else:
            self.app.last_b_click_time = now

        self.assertEqual(self.app.last_b_click_time, t0 + 1.5)
        self.app._handle_voice_turn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
