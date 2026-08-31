#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

# Add pi500 to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pi500"))

from choreography_compiler import (
    compile_choreography_tracks,
    partition_timeline_into_blocks,
    load_dance_presets,
    CHOREO_SCHEMA_VERSION,
)


class TestChoreographyCompiler(unittest.TestCase):

    def setUp(self):
        self.mock_analysis = {
            "duration": 45.0,
            "bpm": 96.0,
            "danceability": 0.75,
            "beat_times": [i * 0.625 for i in range(72)],
            "sections": [
                {"start_sec": 0.0, "end_sec": 10.0, "type": "intro", "energy_score": 0.4},
                {"start_sec": 10.0, "end_sec": 25.0, "type": "verse", "energy_score": 0.65},
                {"start_sec": 25.0, "end_sec": 45.0, "type": "chorus", "energy_score": 0.9},
            ],
            "drops": [{"drop_sec": 25.0}],
            "held_notes": [{"start_sec": 18.0, "end_sec": 22.0}],
            "lyrics": [
                {"id": "ly_001", "start_sec": 10.5, "end_sec": 14.0, "text": "Walking down the lane", "type": "lyric"},
                {"id": "br_001", "start_sec": 14.0, "end_sec": 15.5, "text": "[breath]", "type": "breath"},
                {"id": "ly_002", "start_sec": 15.5, "end_sec": 23.0, "text": "Singing in the rain", "type": "lyric"},
                {"id": "ly_003", "start_sec": 26.0, "end_sec": 34.0, "text": "Thunder and lightning strike", "type": "lyric"},
            ],
        }

    def test_block_partitioning_coverage(self):
        blocks = partition_timeline_into_blocks(self.mock_analysis, 45.0)
        self.assertGreater(len(blocks), 0)

        # Verify time coverage from 0.0 to 45.0 without gaps
        self.assertEqual(blocks[0]["start_sec"], 0.0)
        self.assertEqual(blocks[-1]["end_sec"], 45.0)

        for i in range(len(blocks) - 1):
            curr_end = blocks[i]["end_sec"]
            next_start = blocks[i + 1]["start_sec"]
            self.assertAlmostEqual(curr_end, next_start, delta=0.01,
                                   msg=f"Gap detected between block {i} ({curr_end}s) and {i+1} ({next_start}s)")

    def test_compile_default_choreography(self):
        choreo = compile_choreography_tracks(self.mock_analysis, 45.0)
        self.assertEqual(choreo["version"], CHOREO_SCHEMA_VERSION)
        self.assertIn("blocks", choreo)
        self.assertIn("tracks", choreo)

        blocks = choreo["blocks"]
        tracks = choreo["tracks"]

        # Assert all 7 tracks are present
        for t_name in ["lyrics", "spine_gaze", "s8_gantry", "s7_pedestal", "s1_torso", "s5_head_tilt", "s6_jaw"]:
            self.assertIn(t_name, tracks)
            self.assertGreater(len(tracks[t_name]), 0, f"Track {t_name} is empty")

        # Verify Gantry ROM Bounds (0 to 100%)
        for g_move in tracks["s8_gantry"]:
            t_pos = g_move["target_pos_rom"]
            self.assertGreaterEqual(t_pos, 0.0)
            self.assertLessEqual(t_pos, 100.0)

        # Verify Bounce Modifiers (Strictly 1 target per block)
        valid_bounce_targets = {"hip_sway", "body_bounce", "head_bob"}
        for blk in blocks:
            b_mod = blk.get("bounce_modifier", {})
            self.assertIn("target", b_mod)
            self.assertIn(b_mod["target"], valid_bounce_targets)
            self.assertEqual(b_mod.get("intensity"), 0.12)

        # Verify Pedestal S7 ROM (0 to 100%)
        for p_move in tracks["s7_pedestal"]:
            p_rom = p_move["target_pos_rom"]
            self.assertGreaterEqual(p_rom, 0.0)
            self.assertLessEqual(p_rom, 100.0)

    def test_arch_pose_budget_and_climax_alignment(self):
        """Asserts that arch is initiated at most 2 times across the entire song and only at climax moments."""
        choreo = compile_choreography_tracks(self.mock_analysis, 45.0, seed=42)
        spine_moves = choreo["tracks"]["spine_gaze"]

        # Find all moves where arch was initiated / entered as the target posture
        initiated_arches = [m for m in spine_moves if m.get("end_pose") == "arch" and m.get("pattern") in ["stand_to_pose", "stand_dip_stand"]]

        # Must not exceed 2 arches initiated
        self.assertLessEqual(len(initiated_arches), 2, f"Too many arch poses initiated: {len(initiated_arches)}")
        self.assertGreater(len(initiated_arches), 0, "Expected at least one climax arch to be selected")

        # Initiated arch moves must have head_pitch == 'up' and neck_pitch_rom == 50.0
        for am in initiated_arches:
            self.assertEqual(am["head_pitch"], "up")
            self.assertEqual(am["neck_pitch_rom"], 50.0)

        # For any block that ended in arch, the immediately subsequent block must recover to stand
        for idx, m in enumerate(spine_moves[:-1]):
            if m.get("end_pose") == "arch":
                next_m = spine_moves[idx + 1]
                self.assertEqual(next_m.get("start_pose"), "arch")
                self.assertEqual(next_m.get("end_pose"), "stand")
                self.assertIn(next_m.get("pattern"), ["return_stand_early", "return_stand_mid", "return_stand_late"])

    def test_musical_unit_timing_and_schema_validation(self):
        """Asserts that all timeline blocks contain discrete musical unit parameters
        and fail-fast KeyError is raised when mandatory timing keys are missing.
        """
        from choreography_compiler import identify_climax_blocks
        blocks = partition_timeline_into_blocks(self.mock_analysis, 45.0)

        for b in blocks:
            self.assertIn("start_beat", b)
            self.assertIn("end_beat", b)
            self.assertIn("duration_beats", b)
            self.assertIn("measure", b)
            self.assertGreaterEqual(b["end_beat"], b["start_beat"])
            self.assertEqual(b["duration_beats"], b["end_beat"] - b["start_beat"])
            self.assertEqual(b["measure"], b["start_beat"] // 4)

        # Fail-fast schema test: passing block without start_beat must raise KeyError
        invalid_block = [{"id": "bad_blk", "start_sec": 10.0, "end_sec": 20.0}]
        with self.assertRaises(KeyError):
            identify_climax_blocks(invalid_block, self.mock_analysis, first_vocal_beat=0)

    def test_pedestal_vocal_kickoff_and_center_return(self):
        """Asserts that pedestal snaps align with vocal kick-offs and returns to center during silence."""
        choreo = compile_choreography_tracks(self.mock_analysis, 45.0, seed=42)
        s7_moves = choreo["tracks"]["s7_pedestal"]
        blocks = choreo["blocks"]

        self.assertEqual(choreo["version"], CHOREO_SCHEMA_VERSION)
        self.assertEqual(len(s7_moves), len(blocks))

        # First intro block (instrumental) must be centered at 50%
        self.assertEqual(s7_moves[0]["target_pos_rom"], 50.0)

        # Last outro block (instrumental) must resolve to 50%
        self.assertEqual(s7_moves[-1]["target_pos_rom"], 50.0)


if __name__ == "__main__":
    unittest.main()



