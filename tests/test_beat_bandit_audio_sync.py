#!/usr/bin/env python3
"""Unit tests for Beat Bandit In-Process Master Audio Clock Synchronization.
Validates:
1. Canonical configuration keys in apps/beat_bandit/config.json.
2. BeatBanditAudioClient in-process Pygame audio methods.
3. ChoreographyPlayer get_audio_time_fn integration and timeline locking.
"""

import io
import json
import os
import sys
import time
import unittest
from pathlib import Path
from typing import Dict, Any, List

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "pi4b"))
sys.path.insert(0, str(ROOT_DIR / "apps" / "beat_bandit"))

from beat_bandit_audio import BeatBanditAudioClient
from choreography_player import ChoreographyPlayer
from choreography_compiler import compile_choreography_tracks


class MockBackend:
    def __init__(self):
        self.dispatched_frames: List[Dict[str, Any]] = []

    def dispatch_dance_frame(self, rom_posture: Dict[str, float], s7_rom: float = 50.0, s8_goal: float = 50.0, s8_is_rom: bool = True, s8_speed: int = 500):
        self.dispatched_frames.append({
            "rom_posture": dict(rom_posture),
            "s7_rom": float(s7_rom),
            "s8_goal": s8_goal,
            "time": time.time()
        })
        return {"status": "ok"}


class TestBeatBanditAudioSync(unittest.TestCase):

    def setUp(self):
        self.config_path = ROOT_DIR / "apps" / "beat_bandit" / "config.json"
        self.library_dir = ROOT_DIR / "library" / "beat_bandit"

        self.mock_analysis = {
            "title": "Test Sync Track",
            "duration": 4.0,
            "bpm": 120.0,
            "beat_times": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
            "downbeats": [0.0, 2.0],
            "lyrics": [
                {"id": "ly_001", "name": "Vocal 1", "text": "Singing", "start_sec": 1.0, "end_sec": 2.0, "type": "lyric"}
            ],
            "sections": [
                {"start_sec": 0.0, "end_sec": 4.0, "type": "verse", "energy_score": 0.8}
            ],
            "drops": [],
            "held_notes": [],
            "amplitude_envelope_50hz": [0.5] * 200,
            "mouth_envelope_50hz": [0.0] * 50 + [35.0] * 50 + [0.0] * 100,
        }
        self.compiled_choreo = compile_choreography_tracks(self.mock_analysis, duration=4.0)

    def test_config_schema(self):
        """Test 1: Verify config.json contains required canonical keys for in-process audio."""
        self.assertTrue(self.config_path.exists())
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        self.assertIn("audio_engine", cfg)
        self.assertIn("audio_driver", cfg)
        self.assertIn("sync_mode", cfg)
        self.assertEqual(cfg["audio_engine"], "pygame")
        self.assertEqual(cfg["audio_driver"], "pulse")
        self.assertEqual(cfg["sync_mode"], "master_audio_clock")

    def test_audio_client_methods(self):
        """Test 2: Verify BeatBanditAudioClient has required audio engine methods."""
        client = BeatBanditAudioClient(self.library_dir)
        self.assertTrue(hasattr(client, "init_audio_engine"))
        self.assertTrue(hasattr(client, "prepare_track"))
        self.assertTrue(hasattr(client, "start_playback"))
        self.assertTrue(hasattr(client, "get_audio_playback_time"))
        self.assertTrue(hasattr(client, "stop_playback"))

        # When stopped, get_audio_playback_time returns -1.0
        client.stop_playback()
        self.assertEqual(client.get_audio_playback_time(), -1.0)

    def test_choreography_player_uses_audio_time_fn(self):
        """Test 3: Verify ChoreographyPlayer locks its evaluation timeline to get_audio_time_fn."""
        backend = MockBackend()
        simulated_audio_time = 0.0

        def mock_audio_time():
            return simulated_audio_time

        player = ChoreographyPlayer(
            backend=backend,
            choreography=self.compiled_choreo,
            analysis=self.mock_analysis,
            start_sec=0.0,
            end_sec=4.0,
            loop=False,
            get_audio_time_fn=mock_audio_time,
        )

        player.start()
        time.sleep(0.08)

        # Force simulated audio time to 1.25s (inside singing mouth envelope range: 1.0s - 2.0s)
        simulated_audio_time = 1.25
        time.sleep(0.08)

        # Check telemetry status
        status = player.get_status()
        self.assertAlmostEqual(status["time_sec"], 1.25, delta=0.05)
        # Mouth open envelope at 1.25s should be active (> 0)
        self.assertGreater(status["vocal_power"], 0.0)

        player.stop()
        self.assertFalse(player.is_playing)


if __name__ == "__main__":
    unittest.main()
