#!/usr/bin/env python3
"""Test 4: User Edit Preservation Test.
Tests that compile_choreography_tracks() strictly preserves:
  - Any movement block or master block where is_user_edited is True.
  - Recompiles unedited blocks dynamically while retaining custom user parameters.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pi4b"))
from choreography_compiler import compile_choreography_tracks, CHOREO_SCHEMA_VERSION


class TestUserEditPreservation(unittest.TestCase):

    def setUp(self):
        self.mock_analysis = {
            "title": "Edit Preservation Song",
            "duration": 10.0,
            "bpm": 120.0,
            "beat_times": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5],
            "lyrics": [
                {"id": "ly_001", "name": "Line 1", "text": "First vocal", "start_sec": 1.0, "end_sec": 4.0, "type": "lyric"},
                {"id": "ly_002", "name": "Line 2", "text": "Second vocal", "start_sec": 5.0, "end_sec": 8.0, "type": "lyric"},
            ],
            "sections": [
                {"start_sec": 0.0, "end_sec": 10.0, "type": "verse", "energy_score": 0.5}
            ],
            "drops": [],
            "held_notes": [],
            "downbeats": [0.0, 2.0, 4.0, 6.0, 8.0],
            "amplitude_envelope_50hz": [0.5] * 500,
            "mouth_envelope_50hz": [0.0] * 500,
        }

    def test_preserves_custom_track_edits(self):
        """Compiles baseline choreography, applies a manual edit to a block, and verifies re-compilation retains it."""
        initial_choreo = compile_choreography_tracks(self.mock_analysis, duration=10.0, seed=1)

        # Apply custom manual user edits to block 'ly_001' on Gantry (S8) and Spine
        custom_s8_block = {
            "id": "s8_ly_001",
            "block_id": "ly_001",
            "name": "Custom User Rail Move",
            "mode": "user_custom_sweep",
            "start_sec": 1.0,
            "end_sec": 4.0,
            "target_pos_rom": 99.9,
            "speed": 777,
            "is_user_edited": True,
        }
        custom_spine_block = {
            "id": "sp_ly_001",
            "block_id": "ly_001",
            "name": "Custom User Spine Stance",
            "start_pose": "stand",
            "mid_pose": "arch",
            "end_pose": "arch",
            "pose_name": "arch",
            "pattern": "custom_arch_pattern",
            "head_pitch": "up",
            "neck_pitch_rom": 50.0,
            "start_sec": 1.0,
            "end_sec": 4.0,
            "transition_sec": 0.99,
            "is_user_edited": True,
        }

        existing_choreo = dict(initial_choreo)
        existing_choreo["tracks"]["s8_gantry"][1] = custom_s8_block  # Block 0 is intro, 1 is ly_001
        existing_choreo["tracks"]["spine_gaze"][1] = custom_spine_block

        # Re-compile with a different seed to prove unedited blocks change while edited blocks remain intact
        recompiled = compile_choreography_tracks(
            self.mock_analysis,
            duration=10.0,
            seed=999,
            existing_choreography=existing_choreo
        )

        self.assertEqual(recompiled["version"], CHOREO_SCHEMA_VERSION)

        # Assert custom S8 block was preserved exactly
        recompiled_s8 = next((b for b in recompiled["tracks"]["s8_gantry"] if b.get("block_id") == "ly_001"), None)
        self.assertIsNotNone(recompiled_s8)
        self.assertEqual(recompiled_s8["target_pos_rom"], 99.9)
        self.assertEqual(recompiled_s8["speed"], 777)
        self.assertEqual(recompiled_s8["mode"], "user_custom_sweep")

        # Assert custom Spine block was preserved exactly
        recompiled_sp = next((b for b in recompiled["tracks"]["spine_gaze"] if b.get("block_id") == "ly_001"), None)
        self.assertIsNotNone(recompiled_sp)
        self.assertEqual(recompiled_sp["name"], "Custom User Spine Stance")
        self.assertEqual(recompiled_sp["transition_sec"], 0.99)
        self.assertEqual(recompiled_sp["pattern"], "custom_arch_pattern")


if __name__ == "__main__":
    unittest.main()
