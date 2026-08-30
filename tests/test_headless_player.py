#!/usr/bin/env python3
"""Test 2: Headless Player Test.
Runs choreography_player.py at 50 Hz against a mock backend for 5 simulated seconds,
logging the interpolated 0-100% ROM outputs without hardware or web servers.
"""

import sys
import time
import unittest
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).parent.parent / "pi500"))
from choreography_player import ChoreographyPlayer
from choreography_compiler import compile_choreography_tracks


class MockRobotBackend:
    def __init__(self):
        self.dispatched_frames: List[Dict[str, Any]] = []
        self.torque_enabled = False

    def set_arm_torque(self, enabled: bool):
        self.torque_enabled = enabled

    def dispatch_dance_frame(self, rom_posture: Dict[str, float], s7_rom: float = 50.0, s8_goal: float = 50.0, s8_is_rom: bool = True, s8_speed: int = 500):
        frame = {
            "timestamp": time.time(),
            "rom_posture": dict(rom_posture),
            "s7_rom": float(s7_rom),
            "s8_goal": s8_goal,
        }
        self.dispatched_frames.append(frame)
        return {"status": "ok"}


class TestHeadlessPlayer(unittest.TestCase):

    def setUp(self):
        self.mock_analysis = {
            "title": "Headless Test Track",
            "duration": 6.0,
            "bpm": 120.0,
            "beat_times": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5],
            "lyrics": [
                {"id": "ly_001", "name": "Vocal 1", "text": "Hello world", "start_sec": 1.0, "end_sec": 3.0, "type": "lyric"}
            ],
            "sections": [
                {"start_sec": 0.0, "end_sec": 6.0, "type": "verse", "energy_score": 0.8}
            ],
            "drops": [{"drop_sec": 2.5}],
            "held_notes": [{"start_sec": 1.5, "end_sec": 2.5}],
            "mouth_envelope_50hz": [0.0] * 50 + [35.0] * 100 + [0.0] * 150,
        }
        self.compiled_choreo = compile_choreography_tracks(self.mock_analysis, duration=6.0)
        self.mock_backend = MockRobotBackend()

    def test_headless_50hz_playback(self):
        """Runs the player for 5 simulated seconds at 50 Hz and verifies frame dispatch."""
        player = ChoreographyPlayer(
            backend=self.mock_backend,
            choreography=self.compiled_choreo,
            analysis=self.mock_analysis,
            start_sec=0.0,
            end_sec=5.0,
            loop=False,
        )

        player.start()
        self.assertTrue(player.is_playing)

        # Allow player to run for 2.0 real seconds to accumulate 50Hz frames
        time.sleep(2.0)
        status = player.get_status()

        self.assertGreater(status["time_sec"], 0.5)
        self.assertGreater(len(self.mock_backend.dispatched_frames), 30)

        # Audit frame ROM limits
        for frame in self.mock_backend.dispatched_frames:
            rom = frame["rom_posture"]
            for joint, val in rom.items():
                self.assertGreaterEqual(val, 0.0, f"Joint {joint} below 0% ROM: {val}")
                self.assertLessEqual(val, 100.0, f"Joint {joint} above 100% ROM: {val}")

            # Gripper / Jaw must never exceed 45% ROM
            self.assertLessEqual(rom.get("gripper", 0.0), 45.0, "Singing jaw exceeded 45% ROM limit")

        player.stop()
        self.assertFalse(player.is_playing)


if __name__ == "__main__":
    unittest.main()
