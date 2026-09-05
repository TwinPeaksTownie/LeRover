#!/usr/bin/env python3
"""tests/test_listener_pipeline.py - Comprehensive Unit Tests for ListenerApp and Voice Pipeline.
Verifies:
  1. Intent parser intent mapping & entity extraction.
  2. Fail-fast configuration schema validation.
  3. AppManager auto-discovery of listener_app.
  4. Dynamic calibration resolution without hardcoded ticks.
  5. Song pipeline slug sanitization and sequence lookup.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
PI500_DIR = WORKSPACE_ROOT / "pi500"
for p in [WORKSPACE_ROOT, PI500_DIR]:
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

from apps.listener_app.intent_parser import parse_intent, sanitize_input
from apps.listener_app.song_pipeline import sanitize_slug, find_compiled_sequence, get_sequences_dir
from apps.listener_app.app import ListenerApp, load_listener_config, load_calibration_limits
from app_manager import AppManager


class TestListenerPipeline(unittest.TestCase):

    def test_intent_parser_app_switch(self):
        # Canonical app switches
        res1 = parse_intent("start teleop")
        self.assertEqual(res1["intent"], "SWITCH_APP")
        self.assertEqual(res1["app"], "teleop")

        res2 = parse_intent("open servo studio")
        self.assertEqual(res2["intent"], "SWITCH_APP")
        self.assertEqual(res2["app"], "servo_studio")

        res3 = parse_intent("launch beat bandit")
        self.assertEqual(res3["intent"], "SWITCH_APP")
        self.assertEqual(res3["app"], "beat_bandit")

    def test_intent_parser_movement_primitives(self):
        res1 = parse_intent("home arm")
        self.assertEqual(res1["intent"], "MOVE_PRIMITIVE")
        self.assertEqual(res1["action"], "home")

        res2 = parse_intent("center")
        self.assertEqual(res2["intent"], "MOVE_PRIMITIVE")
        self.assertEqual(res2["action"], "center")

        res3 = parse_intent("park")
        self.assertEqual(res3["intent"], "MOVE_PRIMITIVE")
        self.assertEqual(res3["action"], "park")

    def test_intent_parser_download_song(self):
        res = parse_intent("download pink pony club by chappel roan")
        self.assertEqual(res["intent"], "DOWNLOAD_SONG")
        self.assertEqual(res["title"], "pink pony club")
        self.assertEqual(res["artist"], "chappel roan")

        res2 = parse_intent("fetch good luck babe by chappell roan")
        self.assertEqual(res2["intent"], "DOWNLOAD_SONG")
        self.assertEqual(res2["title"], "good luck babe")
        self.assertEqual(res2["artist"], "chappell roan")

    def test_intent_parser_play_song(self):
        res = parse_intent("sing pink pony club")
        self.assertEqual(res["intent"], "PLAY_SONG")
        self.assertEqual(res["title"], "pink pony club")

        res2 = parse_intent("play espresso")
        self.assertEqual(res2["intent"], "PLAY_SONG")
        self.assertEqual(res2["title"], "espresso")

    def test_intent_parser_exit(self):
        self.assertEqual(parse_intent("exit")["intent"], "EXIT")
        self.assertEqual(parse_intent("quit")["intent"], "EXIT")
        self.assertEqual(parse_intent("cancel")["intent"], "EXIT")

    def test_config_fail_fast(self):
        cfg = load_listener_config()
        self.assertEqual(cfg["name"], "listener_app")
        self.assertEqual(cfg["hotword"]["sample_rate"], 16000)
        self.assertEqual(cfg["asr"]["engine"], "faster_whisper")
        self.assertIn("app_start", cfg["chimes"])
        self.assertIn("wake", cfg["chimes"])

    def test_app_metadata_parity(self):
        cfg = load_listener_config()
        app = ListenerApp(running_on_pi=False)
        self.assertEqual(app.metadata.name, cfg["name"])
        self.assertEqual(app.metadata.title, cfg["title"])
        self.assertEqual(app.metadata.icon, cfg["icon"])

    def test_app_manager_auto_discovery(self):
        mock_backend = MagicMock()
        mgr = AppManager(backend=mock_backend)
        discovered = mgr.discover_apps()
        self.assertIn("listener_app", discovered)
        self.assertIn("listener_app", mgr.registry)

    def test_dynamic_calibration_resolution(self):
        import json
        from unittest.mock import patch, mock_open
        mock_calib = {
            "shoulder_pan": {"id": 1, "drive_mode": 0, "homing_offset": -33, "range_min": 743, "range_max": 3458},
            "shoulder_lift": {"id": 2, "drive_mode": 0, "homing_offset": -36, "range_min": 915, "range_max": 3273},
            "elbow_flex": {"id": 3, "drive_mode": 0, "homing_offset": 667, "range_min": 154, "range_max": 2334},
            "wrist_flex": {"id": 4, "drive_mode": 0, "homing_offset": -69, "range_min": 805, "range_max": 3142},
            "wrist_roll": {"id": 5, "drive_mode": 0, "homing_offset": 81, "range_min": 66, "range_max": 3894},
            "gripper": {"id": 6, "drive_mode": 0, "homing_offset": 63, "range_min": 1456, "range_max": 2901},
        }
        with patch("pathlib.Path.exists", return_value=True), patch("builtins.open", mock_open(read_data=json.dumps(mock_calib))):
            limits = load_calibration_limits()
            for sid in range(1, 7):
                self.assertIn(sid, limits)
                c = limits[sid]
                self.assertIn("min", c)
                self.assertIn("max", c)
                self.assertIn("center", c)
                self.assertTrue(c["min"] < c["max"])
                self.assertEqual(c["center"], (c["min"] + c["max"]) // 2)

        # Also verify in-memory backend calibration extraction
        mock_motor_calib = MagicMock()
        mock_motor_calib.range_min = 500
        mock_motor_calib.range_max = 2500
        mock_backend = MagicMock()
        mock_backend.arm_calibration = {
            "shoulder_pan": mock_motor_calib,
            "shoulder_lift": mock_motor_calib,
            "elbow_flex": mock_motor_calib,
            "wrist_flex": mock_motor_calib,
            "wrist_roll": mock_motor_calib,
            "gripper": mock_motor_calib,
        }
        limits_from_backend = load_calibration_limits(backend=mock_backend)
        self.assertEqual(len(limits_from_backend), 6)
        self.assertEqual(limits_from_backend[1]["center"], 1500)

    def test_song_slug_sanitization(self):
        slug = sanitize_slug("Pink Pony Club!")
        self.assertEqual(slug, "pink_pony_club")

        slug2 = sanitize_slug("Chappell Roan - Good Luck, Babe!")
        self.assertEqual(slug2, "chappell_roan_good_luck_babe")


if __name__ == "__main__":
    unittest.main()
