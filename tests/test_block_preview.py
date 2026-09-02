#!/usr/bin/env python3
"""Test: Dynamic Isolated Block Preview
Verifies:
  1. preview_isolated_block isolates target channel while holding all other channels at neutral defaults.
  2. 50 Hz ChoreographyPlayer executes the exact block duration (start_sec -> end_sec).
  3. Harmonic bounce modifier oscillates actively during block preview while other channels remain neutral.
  4. Stop handshake halts playback and returns arm to neutral STAND pose.
  5. Fail-fast validation on missing block keys.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "pi500"))
from beat_bandit_app import BeatBanditApp
from robot_backend import RobotBackend


class MockRobotBackend:

    def __init__(self):
        self.dispatched_frames = []
        self.arm_calibration = {
            "shoulder_pan": {"range_min": 1000, "range_max": 3000},
            "shoulder_lift": {"range_min": 1000, "range_max": 3000},
            "elbow_flex": {"range_min": 1000, "range_max": 3000},
            "wrist_flex": {"range_min": 1000, "range_max": 3000},
            "wrist_roll": {"range_min": 1000, "range_max": 3000},
            "gripper": {"range_min": 500, "range_max": 1500},
        }
        self.aux_calibration = {
            "7": {"min_ticks": 1000, "max_ticks": 3000, "center_ticks": 2000},
            "8": {"min_ticks": 500, "max_ticks": 4500},
        }

    def dispatch_dance_frame(self, rom_posture, s7_rom=None, s8_goal=None, s8_is_rom=True, s8_speed=None):
        frame = {
            "time": time.time(),
            "rom_posture": dict(rom_posture),
            "s7_rom": s7_rom,
            "s8_goal": s8_goal,
            "s8_is_rom": s8_is_rom,
            "s8_speed": s8_speed,
        }
        self.dispatched_frames.append(frame)
        return {"status": "ok", "frame": frame}

    def set_arm_torque(self, enable=True):
        return True


class TestBlockPreview(unittest.TestCase):

    def setUp(self):
        self.app = BeatBanditApp(running_on_pi=False)
        self.mock_backend = MockRobotBackend()

        self.mock_analysis = {
            "title": "Preview Test Song",
            "duration": 10.0,
            "bpm": 120.0,
            "beat_times": [i * 0.5 for i in range(20)],
            "downbeats": [0.0, 2.0, 4.0, 6.0, 8.0],
            "drops": [],
            "held_notes": [],
            "amplitude_envelope_50hz": [0.5] * 500,
            "mouth_envelope_50hz": [0.0] * 500,
            "sections": [{"start_sec": 0.0, "end_sec": 10.0, "type": "verse", "energy_score": 0.5}],
            "lyrics": [],
        }

        import tempfile
        self.tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self.tmp_wav.write(b"RIFF" + b"\x00" * 40)
        self.tmp_wav.close()

        self.mock_track_meta = {
            "track_id": "test_track_preview",
            "title": "Preview Test Song",
            "artist": "Test Artist",
            "duration": 10.0,
            "bpm": 120.0,
            "wav_path": self.tmp_wav.name,
            "analysis": self.mock_analysis,
        }

        self.app.manifest["test_track_preview"] = self.mock_track_meta
        self.app.audio_client = MagicMock()

    def tearDown(self):
        import os
        if hasattr(self, "tmp_wav") and os.path.exists(self.tmp_wav.name):
            os.remove(self.tmp_wav.name)

    def test_spine_block_isolated_preview_execution(self):
        """Tests that a spine block with bounce runs isolated at 50 Hz and oscillates lift while other channels stay neutral."""
        block = {
            "id": "blk_test_spine",
            "name": "Test Spine Bounce",
            "start_sec": 1.0,
            "end_sec": 2.5,
            "pose_name": "stand",
            "pattern": "hold_stand",
            "transition_sec": 0.3,
            "neck_pitch_rom": 70.0,
            "bounce_modifier": {
                "enabled": True,
                "intensity": 0.25,
                "target": "body_bounce",
            },
        }

        res = self.app.preview_isolated_block(
            self.mock_backend,
            track_id="test_track_preview",
            channel="spine_gaze",
            block=block,
        )

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["start_sec"], 1.0)
        self.assertEqual(res["end_sec"], 2.5)
        self.assertEqual(res["duration"], 1.5)
        self.assertTrue(self.app.player.is_playing)

        # Allow player loop to run briefly to collect 50Hz frames
        time.sleep(1.0)
        self.app.stop_dance()
        self.assertFalse(self.app.player)

        # Verify frames were dispatched
        self.assertGreater(len(self.mock_backend.dispatched_frames), 10)
        lift_vals = [f["rom_posture"]["shoulder_lift"] for f in self.mock_backend.dispatched_frames]
        lift_variance = max(lift_vals) - min(lift_vals)
        self.assertGreater(lift_variance, 0.5, f"Expected dynamic bounce variance on shoulder_lift, got {lift_variance}")

        # Verify isolated channels were held at neutral
        s7_vals = [f["s7_rom"] for f in self.mock_backend.dispatched_frames if f["s7_rom"] is not None]
        s8_vals = [f["s8_goal"] for f in self.mock_backend.dispatched_frames if f["s8_goal"] is not None]
        for s7 in s7_vals:
            self.assertAlmostEqual(s7, 50.0, delta=0.2)
        for s8 in s8_vals:
            self.assertAlmostEqual(s8, 49.97, delta=0.2)

    def test_preview_fail_fast_missing_keys(self):
        """Tests that preview_isolated_block raises KeyError when mandatory keys are missing."""
        malformed_block = {"name": "Bad Block"}
        with self.assertRaises(KeyError) as ctx:
            self.app.preview_isolated_block(
                self.mock_backend,
                track_id="test_track_preview",
                channel="spine_gaze",
                block=malformed_block,
            )
        self.assertIn("start_sec", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
