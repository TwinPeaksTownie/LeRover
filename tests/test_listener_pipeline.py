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

from apps.listener_app.intent_parser import parse_intent, sanitize_input, strip_hallucinated_the, APP_ALIAS_MAP
from apps.listener_app.song_pipeline import sanitize_slug, find_compiled_sequence, get_sequences_dir, find_beat_bandit_track
from apps.listener_app.app import ListenerApp, load_listener_config, load_calibration_limits
from app_manager import AppManager


class TestListenerPipeline(unittest.TestCase):

    def test_intent_parser_app_switch(self):
        # Canonical app switches
        res1 = parse_intent("start teleop")
        self.assertEqual(res1["intent"], "SWITCH_APP")
        self.assertEqual(res1["app"], "teleop_app")

        res2 = parse_intent("open servo studio")
        self.assertEqual(res2["intent"], "SWITCH_APP")
        self.assertEqual(res2["app"], "servo_studio_app")

        res3 = parse_intent("launch beat bandit")
        self.assertEqual(res3["intent"], "SWITCH_APP")
        self.assertEqual(res3["app"], "beat_bandit_app")

    def test_intent_parser_posture_commands(self):
        # Exact physical posture commands
        res1 = parse_intent("stand up")
        self.assertEqual(res1["intent"], "POSTURE")
        self.assertEqual(res1["action"], "stand")

        res1b = parse_intent("stand")
        self.assertEqual(res1b["intent"], "POSTURE")
        self.assertEqual(res1b["action"], "stand")

        res2 = parse_intent("sit down")
        self.assertEqual(res2["intent"], "POSTURE")
        self.assertEqual(res2["action"], "sit")

        res2b = parse_intent("sit")
        self.assertEqual(res2b["intent"], "POSTURE")
        self.assertEqual(res2b["action"], "sit")

        res3 = parse_intent("tiptoes")
        self.assertEqual(res3["intent"], "POSTURE")
        self.assertEqual(res3["action"], "tiptoes")

        res3b = parse_intent("tiptoe")
        self.assertEqual(res3b["intent"], "POSTURE")
        self.assertEqual(res3b["action"], "tiptoes")

        res4 = parse_intent("play dead")
        self.assertEqual(res4["intent"], "POSTURE")
        self.assertEqual(res4["action"], "play_dead")

        # Physical posture commands with lingering words (e.g. "stand up the", "stand up now", "can you stand up")
        res_ling1 = parse_intent("stand up the")
        self.assertEqual(res_ling1["intent"], "POSTURE")
        self.assertEqual(res_ling1["action"], "stand")

        res_ling1b = parse_intent("the stand up")
        self.assertEqual(res_ling1b["intent"], "POSTURE")
        self.assertEqual(res_ling1b["action"], "stand")

        res_ling1c = parse_intent("the stand up the")
        self.assertEqual(res_ling1c["intent"], "POSTURE")
        self.assertEqual(res_ling1c["action"], "stand")

        res_ling1d = parse_intent("stand up now")
        self.assertEqual(res_ling1d["intent"], "POSTURE")
        self.assertEqual(res_ling1d["action"], "stand")

        res_ling1e = parse_intent("stand up please")
        self.assertEqual(res_ling1e["intent"], "POSTURE")
        self.assertEqual(res_ling1e["action"], "stand")

        res_ling1f = parse_intent("can you stand up")
        self.assertEqual(res_ling1f["intent"], "POSTURE")
        self.assertEqual(res_ling1f["action"], "stand")

        res_ling2 = parse_intent("sit down the")
        self.assertEqual(res_ling2["intent"], "POSTURE")
        self.assertEqual(res_ling2["action"], "sit")

        res_ling2b = parse_intent("sit down now")
        self.assertEqual(res_ling2b["intent"], "POSTURE")
        self.assertEqual(res_ling2b["action"], "sit")

        res_ling3 = parse_intent("tiptoes the")
        self.assertEqual(res_ling3["intent"], "POSTURE")
        self.assertEqual(res_ling3["action"], "tiptoes")

        res_ling3b = parse_intent("tiptoes please")
        self.assertEqual(res_ling3b["intent"], "POSTURE")
        self.assertEqual(res_ling3b["action"], "tiptoes")

        res_ling4 = parse_intent("play dead the")
        self.assertEqual(res_ling4["intent"], "POSTURE")
        self.assertEqual(res_ling4["action"], "play_dead")

        res_ling4b = parse_intent("play dead now")
        self.assertEqual(res_ling4b["intent"], "POSTURE")
        self.assertEqual(res_ling4b["action"], "play_dead")

        # Explicitly verify removed synthetic slop primitives return UNKNOWN
        self.assertEqual(parse_intent("home")["intent"], "UNKNOWN")
        self.assertEqual(parse_intent("center")["intent"], "UNKNOWN")
        self.assertEqual(parse_intent("park")["intent"], "UNKNOWN")
        self.assertEqual(parse_intent("rest")["intent"], "UNKNOWN")
        self.assertEqual(parse_intent("zero")["intent"], "UNKNOWN")
        self.assertEqual(parse_intent("ready")["intent"], "UNKNOWN")

    def test_strip_hallucinated_the(self):
        # 1. Only "the" (or repetitions) -> empty string
        self.assertEqual(strip_hallucinated_the("the"), "")
        self.assertEqual(strip_hallucinated_the("the the"), "")
        self.assertEqual(strip_hallucinated_the("The"), "")
        self.assertEqual(strip_hallucinated_the("The."), "")
        self.assertEqual(strip_hallucinated_the("  the  "), "")
        self.assertEqual(strip_hallucinated_the(""), "")

        # 2. Starts with "the" -> stripped
        self.assertEqual(strip_hallucinated_the("the stand up"), "stand up")
        self.assertEqual(strip_hallucinated_the("the the stand up"), "stand up")
        self.assertEqual(strip_hallucinated_the("The sit down"), "sit down")
        self.assertEqual(strip_hallucinated_the("the play"), "play")

        # 3. Ends with "the" -> stripped
        self.assertEqual(strip_hallucinated_the("stand up the"), "stand up")
        self.assertEqual(strip_hallucinated_the("stand up the the"), "stand up")
        self.assertEqual(strip_hallucinated_the("sit down the"), "sit down")
        self.assertEqual(strip_hallucinated_the("play dead the"), "play dead")

        # 4. Starts and ends with "the" -> stripped
        self.assertEqual(strip_hallucinated_the("the stand up the"), "stand up")
        self.assertEqual(strip_hallucinated_the("the play dead the"), "play dead")

        # 5. Internal "the" preserved
        self.assertEqual(strip_hallucinated_the("dance to the beat"), "dance to the beat")
        self.assertEqual(strip_hallucinated_the("sing the song"), "sing the song")
        self.assertEqual(strip_hallucinated_the("the dance to the beat the"), "dance to the beat")

        # 6. Subwords with "the" strictly preserved
        self.assertEqual(strip_hallucinated_the("theme park"), "theme park")
        self.assertEqual(strip_hallucinated_the("breathe"), "breathe")
        self.assertEqual(strip_hallucinated_the("soothe"), "soothe")
        self.assertEqual(strip_hallucinated_the("they are dancing"), "they are dancing")

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

        res3 = parse_intent("play redwine supernova")
        self.assertEqual(res3["intent"], "PLAY_SONG")
        self.assertEqual(res3["title"], "redwine supernova")

    def test_intent_parser_exit(self):
        self.assertEqual(parse_intent("exit")["intent"], "EXIT")
        self.assertEqual(parse_intent("quit")["intent"], "EXIT")
        self.assertEqual(parse_intent("cancel")["intent"], "EXIT")

    def test_config_fail_fast(self):
        import copy
        from unittest.mock import patch, mock_open
        import json

        cfg = load_listener_config()
        self.assertEqual(cfg["name"], "listener_app")
        self.assertEqual(cfg["hotword"]["sample_rate"], 16000)
        self.assertEqual(cfg["asr"]["engine"], "vosk")
        self.assertIn("app_start", cfg["chimes"])
        self.assertIn("wake", cfg["chimes"])
        self.assertEqual(cfg["vad"]["settle_delay_sec"], 2.5)
        self.assertEqual(cfg["vad"]["post_chime_settle_sec"], 1.5)
        self.assertEqual(cfg["vad"]["energy_threshold"], 450)
        self.assertEqual(cfg["vad"]["pre_roll_chunks"], 15)
        self.assertEqual(cfg["vad"]["fuzzy_match_threshold"], 0.55)
        self.assertGreater(cfg["vad"]["settle_delay_sec"], 0)
        self.assertGreater(cfg["vad"]["post_chime_settle_sec"], 0)
        self.assertEqual(cfg["motion"]["interpolation_duration_sec"], 1.2)
        self.assertEqual(cfg["motion"]["interpolation_steps"], 35)
        self.assertEqual(cfg["motion"]["dead_posture"], "arch")
        self.assertEqual(cfg["network"]["vosk_server_port"], 8059)
        self.assertEqual(cfg["network"]["vosk_websocket_port"], 2700)

        # Missing settle_delay_sec raises KeyError
        bad_cfg_missing = copy.deepcopy(cfg)
        del bad_cfg_missing["vad"]["settle_delay_sec"]
        with patch("builtins.open", mock_open(read_data=json.dumps(bad_cfg_missing))):
            with self.assertRaises(KeyError):
                load_listener_config()

        # Missing post_chime_settle_sec raises KeyError
        bad_cfg_missing_post = copy.deepcopy(cfg)
        del bad_cfg_missing_post["vad"]["post_chime_settle_sec"]
        with patch("builtins.open", mock_open(read_data=json.dumps(bad_cfg_missing_post))):
            with self.assertRaises(KeyError):
                load_listener_config()

        # Non-positive settle_delay_sec raises ValueError
        bad_cfg_zero = copy.deepcopy(cfg)
        bad_cfg_zero["vad"]["settle_delay_sec"] = 0.0
        with patch("builtins.open", mock_open(read_data=json.dumps(bad_cfg_zero))):
            with self.assertRaises(ValueError):
                load_listener_config()

        # Non-positive post_chime_settle_sec raises ValueError
        bad_cfg_post_zero = copy.deepcopy(cfg)
        bad_cfg_post_zero["vad"]["post_chime_settle_sec"] = 0.0
        with patch("builtins.open", mock_open(read_data=json.dumps(bad_cfg_post_zero))):
            with self.assertRaises(ValueError):
                load_listener_config()

        # Non-positive pre_roll_chunks raises ValueError
        bad_cfg_pr = copy.deepcopy(cfg)
        bad_cfg_pr["vad"]["pre_roll_chunks"] = 0
        with patch("builtins.open", mock_open(read_data=json.dumps(bad_cfg_pr))):
            with self.assertRaises(ValueError):
                load_listener_config()

        # Missing motion section raises KeyError
        bad_cfg_motion = copy.deepcopy(cfg)
        del bad_cfg_motion["motion"]
        with patch("builtins.open", mock_open(read_data=json.dumps(bad_cfg_motion))):
            with self.assertRaises(KeyError):
                load_listener_config()

    def test_find_beat_bandit_track_fuzzy(self):
        from apps.listener_app.song_pipeline import find_beat_bandit_track
        import tempfile
        import json
        from pathlib import Path

        mock_manifest = {
            "W8j1Gy41drQ": {
                "track_id": "W8j1Gy41drQ",
                "title": "Downtown",
                "artist": "Macklemore & Ryan Lewis",
                "wav_path": "/path/to/downtown.wav"
            }
        }
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as tf:
            json.dump(mock_manifest, tf)
            tf_path = Path(tf.name)

        try:
            # Exact match
            m1 = find_beat_bandit_track("downtown", manifest_path=tf_path)
            self.assertIsNotNone(m1)
            self.assertEqual(m1["track_id"], "W8j1Gy41drQ")

            # Fuzzy near-miss "allentown" (ratio 0.588 >= 0.55)
            m2 = find_beat_bandit_track("allentown", manifest_path=tf_path, fuzzy_threshold=0.55)
            self.assertIsNotNone(m2)
            self.assertEqual(m2["track_id"], "W8j1Gy41drQ")

            # Intent parser direct title lookup fallback with fuzzy match
            parsed = parse_intent("allentown")
            # When manifest path isn't injected, intent_parser uses get_beat_bandit_manifest_path()
            # but this verifies the standalone find_beat_bandit_track fuzzy logic

            # Complete mismatch returns None
            m3 = find_beat_bandit_track("bohemian rhapsody", manifest_path=tf_path, fuzzy_threshold=0.55)
            self.assertIsNone(m3)
        finally:
            tf_path.unlink(missing_ok=True)

    def test_app_metadata_parity(self):
        cfg = load_listener_config()
        app = ListenerApp(running_on_pi=False)
        self.assertEqual(app.metadata.name, cfg["name"])
        self.assertEqual(app.metadata.title, cfg["title"])
        self.assertEqual(app.metadata.icon, cfg["icon"])
        self.assertEqual(app.get_status()["transcript"], "(none)")
        app.transcript = "play redwine supernova"
        self.assertEqual(app.get_status()["transcript"], "play redwine supernova")

    def test_load_dance_presets(self):
        from apps.listener_app.app import load_dance_presets
        presets = load_dance_presets()
        for k in ["stand", "sit", "tiptoe", "arch"]:
            self.assertIn(k, presets)
            self.assertIn("normalized", presets[k])
            norm = presets[k]["normalized"]
            for joint in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]:
                self.assertIn(joint, norm)
                self.assertIsInstance(norm[joint], (int, float))

    def test_app_manager_auto_discovery(self):
        mock_backend = MagicMock()
        mgr = AppManager(backend=mock_backend)
        discovered = mgr.discover_apps()
        self.assertIn("listener_app", discovered)
        self.assertIn("listener_app", mgr.registry)

        # Test stop_current_app method existence and safe execution
        self.assertTrue(hasattr(mgr, "stop_current_app"))
        mgr.stop_current_app()  # Safe no-op when no active app

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

    def test_canonical_app_alias_map(self):
        canonical_apps = {"teleop_app", "servo_studio_app", "beat_bandit_app", "preset_app", "pokeball_teleop_app", "piranha_pose_app", "ornith_voice"}
        for alias, app_name in APP_ALIAS_MAP.items():
            self.assertIn(app_name, canonical_apps, f"Alias '{alias}' points to unknown '{app_name}'")

    def test_find_beat_bandit_track_matching(self):
        import tempfile
        import json

        sample_manifest = {
            "OlQJ2zy5DE8": {
                "track_id": "OlQJ2zy5DE8",
                "title": "Peaches",
                "artist": "Jack Black",
                "duration": 95.43,
                "bpm": 184.6,
                "wav_path": "/path/to/OlQJ2zy5DE8.wav",
                "analysis": {}
            },
            "F0N7aNy-9tg": {
                "track_id": "F0N7aNy-9tg",
                "title": "Dracula",
                "artist": "Unknown Artist",
                "duration": 209.84,
                "bpm": 114.8,
                "wav_path": "/path/to/F0N7aNy-9tg.wav",
                "analysis": {}
            },
            "y9Wxl9Q9lUQ": {
                "track_id": "y9Wxl9Q9lUQ",
                "title": "Red Wine Supernova",
                "artist": "Chappell Roan",
                "duration": 192.72,
                "bpm": 123.0,
                "wav_path": "/path/to/rw.wav",
                "analysis": {}
            }
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(sample_manifest, tf)
            tf_path = Path(tf.name)

        try:
            # 1. Exact title match
            t1 = find_beat_bandit_track("Peaches", manifest_path=tf_path)
            self.assertIsNotNone(t1)
            self.assertEqual(t1["track_id"], "OlQJ2zy5DE8")

            # 2. Case-insensitive title match
            t2 = find_beat_bandit_track("peaches", manifest_path=tf_path)
            self.assertIsNotNone(t2)
            self.assertEqual(t2["track_id"], "OlQJ2zy5DE8")

            # 3. Combined "title by artist" match
            t3 = find_beat_bandit_track("peaches by jack black", manifest_path=tf_path)
            self.assertIsNotNone(t3)
            self.assertEqual(t3["track_id"], "OlQJ2zy5DE8")

            # 4. Track ID match
            t4 = find_beat_bandit_track("OlQJ2zy5DE8", manifest_path=tf_path)
            self.assertIsNotNone(t4)
            self.assertEqual(t4["title"], "Peaches")

            # 5. Spaceless matching ("redwine supernova" -> "Red Wine Supernova")
            t_space1 = find_beat_bandit_track("redwine supernova", manifest_path=tf_path)
            self.assertIsNotNone(t_space1)
            self.assertEqual(t_space1["track_id"], "y9Wxl9Q9lUQ")

            # 6. Spaceless matching with split words ("red wine super nova" -> "Red Wine Supernova")
            t_space2 = find_beat_bandit_track("red wine super nova", manifest_path=tf_path)
            self.assertIsNotNone(t_space2)
            self.assertEqual(t_space2["track_id"], "y9Wxl9Q9lUQ")

            # 7. Missing track returns None
            t5 = find_beat_bandit_track("Nonexistent Song 12345", manifest_path=tf_path)
            self.assertIsNone(t5)

            # 8. Corrupt manifest key raises KeyError (fail-fast)
            bad_manifest = {"bad": {"title": "No track ID"}}
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as btf:
                json.dump(bad_manifest, btf)
                btf_path = Path(btf.name)
            try:
                with self.assertRaises(KeyError):
                    find_beat_bandit_track("anything", manifest_path=btf_path)
            finally:
                btf_path.unlink(missing_ok=True)
        finally:
            tf_path.unlink(missing_ok=True)

    def test_endpoint_urls_resolution(self):
        app = ListenerApp(running_on_pi=False)
        pi4b_url = app._get_pi4b_url()
        self.assertTrue(pi4b_url.startswith("http://"))
        self.assertIn(str(app.config["network"]["pi4b_port"]), pi4b_url)

        health_url, ws_url, recognize_url = app._get_vosk_urls()
        self.assertTrue(health_url.startswith("http://"))
        self.assertTrue(ws_url.startswith("ws://"))
        self.assertTrue(recognize_url.startswith("http://"))
        self.assertIn(str(app.config["network"]["vosk_server_port"]), health_url)
        self.assertIn(str(app.config["network"]["vosk_websocket_port"]), ws_url)
        self.assertIn(str(app.config["network"]["vosk_server_port"]), recognize_url)


if __name__ == "__main__":
    unittest.main()

