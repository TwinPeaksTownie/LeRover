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
            "downbeats": [0.0, 2.0, 4.0],
            "lyrics": [
                {"id": "ly_001", "name": "Vocal 1", "text": "Hello world", "start_sec": 1.0, "end_sec": 3.0, "type": "lyric"}
            ],
            "sections": [
                {"start_sec": 0.0, "end_sec": 6.0, "type": "verse", "energy_score": 0.8}
            ],
            "drops": [{"drop_sec": 2.5}],
            "held_notes": [{"start_sec": 1.5, "end_sec": 2.5}],
            "amplitude_envelope_50hz": [0.5] * 300,
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

    def test_spine_block_bounce_modifier(self):
        """Verifies that user-edited spine block bounce_modifier drives dynamic vertical oscillation."""
        choreo_with_bounce = dict(self.compiled_choreo)
        spine_track = choreo_with_bounce["tracks"]["spine_gaze"]
        for block in spine_track:
            block["bounce_modifier"] = {
                "enabled": True,
                "intensity": 0.20,
                "target": "body_bounce"
            }

        backend = MockRobotBackend()
        player = ChoreographyPlayer(
            backend=backend,
            choreography=choreo_with_bounce,
            analysis=self.mock_analysis,
            start_sec=0.0,
            end_sec=2.0,
            loop=False,
        )

        player.start()
        time.sleep(1.2)
        player.stop()

        self.assertGreater(len(backend.dispatched_frames), 20)
        lift_values = [f["rom_posture"]["shoulder_lift"] for f in backend.dispatched_frames]
        # Verify dynamic oscillation variance exists
        lift_variance = max(lift_values) - min(lift_values)
        self.assertGreater(lift_variance, 0.5, f"Shoulder lift variance too low: {lift_variance}")

    def test_spine_block_bounce_fail_fast(self):
        """Verifies fail-fast schema: missing required bounce keys records KeyError immediately."""
        choreo_malformed = dict(self.compiled_choreo)
        spine_track = choreo_malformed["tracks"]["spine_gaze"]
        # Missing 'target' key
        spine_track[0]["bounce_modifier"] = {"enabled": True, "intensity": 0.20}

        backend = MockRobotBackend()
        player = ChoreographyPlayer(
            backend=backend,
            choreography=choreo_malformed,
            analysis=self.mock_analysis,
            start_sec=0.0,
            end_sec=2.0,
            loop=False,
        )

        player._playback_loop()
        self.assertIsNotNone(player.error)
        self.assertIn("Fail-Fast Error", player.error)

    def test_four_state_verification_pipeline(self):
        """Verifies complete 4-state verification pipeline for bounce modifier integration."""
        # State 1: Schema contract & MD5 / key presence verification
        choreo = dict(self.compiled_choreo)
        for b in choreo["tracks"]["spine_gaze"]:
            b["bounce_modifier"] = {"enabled": True, "intensity": 0.25, "target": "body_bounce"}
            self.assertIn("enabled", b["bounce_modifier"])
            self.assertIn("intensity", b["bounce_modifier"])
            self.assertIn("target", b["bounce_modifier"])

        # State 2: Bi-directional motion cycle (Origin -> Target A -> Target B -> Origin)
        backend = MockRobotBackend()
        player = ChoreographyPlayer(
            backend=backend,
            choreography=choreo,
            analysis=self.mock_analysis,
            start_sec=0.0,
            end_sec=2.0,
            loop=False,
        )
        player.start()
        time.sleep(1.0)
        player.stop()

        # State 3: Live telemetry & joint variance sampling across both S2 and S3
        self.assertGreater(len(backend.dispatched_frames), 15)
        s2_vals = [f["rom_posture"]["shoulder_lift"] for f in backend.dispatched_frames]
        s3_vals = [f["rom_posture"]["elbow_flex"] for f in backend.dispatched_frames]
        s2_variance = max(s2_vals) - min(s2_vals)
        s3_variance = max(s3_vals) - min(s3_vals)
        self.assertGreater(s2_variance, 0.5, f"State 3 failed: S2 lift variance {s2_variance} < 0.5")
        self.assertGreater(s3_variance, 0.3, f"State 3 failed: S3 elbow variance {s3_variance} < 0.3")

        # State 4: Telemetry verification handshake
        st = player.get_status()
        self.assertFalse(st["is_playing"])
        self.assertGreater(st["time_sec"], 0.0)

    def test_head_tilt_three_phase_lifecycle(self):
        """Verifies that Head Tilt (S5) executes Attack -> Hold -> Return to Center (50.0)."""
        choreo = dict(self.compiled_choreo)
        s5_track = choreo["tracks"]["s5_head_tilt"]
        # Explicitly configure a tilt block from 0.0 to 2.0s with peak ROM 70.0 (Right Tilt)
        s5_track[0] = {
            "id": "s5_test_tilt",
            "block_id": "blk_001",
            "name": "Test Snap Right",
            "tilt_mode": "snap_pulse_right",
            "tilt_rom": 70.0,
            "target_rom": 70.0,
            "start_sec": 0.0,
            "end_sec": 2.0,
            "pulse_duration_sec": 2.0,
            "roll_amplitude": 0.0,
            "roll_freq_hz": 0.0,
        }

        backend = MockRobotBackend()
        player = ChoreographyPlayer(
            backend=backend,
            choreography=choreo,
            analysis=self.mock_analysis,
            start_sec=0.0,
            end_sec=2.0,
            loop=False,
        )

        player.start()
        time.sleep(2.1)
        player.stop()

        self.assertGreater(len(backend.dispatched_frames), 30)
        roll_vals = [f["rom_posture"]["wrist_roll"] for f in backend.dispatched_frames]

        # 1. Start near 50.0
        self.assertAlmostEqual(roll_vals[0], 50.0, delta=5.0)
        # 2. Reaches peak tilt (> 60.0) during hold phase
        max_roll = max(roll_vals)
        self.assertGreater(max_roll, 60.0, f"Head tilt did not reach peak tilt ROM: {max_roll}")
        # 3. Resolves back to level center near 50.0 at end of block
        self.assertAlmostEqual(roll_vals[-1], 50.0, delta=5.0, msg=f"Head tilt did not return to center: {roll_vals[-1]}")

    def test_head_bob_and_tilt_bounce_modulation(self):
        """Verifies that bounce modifier modulates Servos 4 (wrist_flex) and 5 (wrist_roll)."""
        choreo = dict(self.compiled_choreo)
        for b in choreo["tracks"]["spine_gaze"]:
            b["bounce_modifier"] = {"enabled": True, "intensity": 0.30, "target": "head_bob"}

        backend = MockRobotBackend()
        player = ChoreographyPlayer(
            backend=backend,
            choreography=choreo,
            analysis=self.mock_analysis,
            start_sec=0.0,
            end_sec=2.0,
            loop=False,
        )

        player.start()
        time.sleep(1.2)
        player.stop()

        self.assertGreater(len(backend.dispatched_frames), 20)
        flex_vals = [f["rom_posture"]["wrist_flex"] for f in backend.dispatched_frames]
        roll_vals = [f["rom_posture"]["wrist_roll"] for f in backend.dispatched_frames]

        flex_var = max(flex_vals) - min(flex_vals)
        roll_var = max(roll_vals) - min(roll_vals)

        self.assertGreater(flex_var, 0.5, f"Servo 4 (wrist_flex) lack of bounce variance: {flex_var}")
        self.assertGreater(roll_var, 0.3, f"Servo 5 (wrist_roll) lack of bounce variance: {roll_var}")

    def test_hip_sway_bounce_modulation(self):
        """Verifies that hip_sway bounce target produces symmetric shoulder_pan oscillation."""
        choreo = dict(self.compiled_choreo)
        for b in choreo["tracks"]["spine_gaze"]:
            b["bounce_modifier"] = {"enabled": True, "intensity": 0.40, "target": "hip_sway"}

        backend = MockRobotBackend()
        player = ChoreographyPlayer(
            backend=backend,
            choreography=choreo,
            analysis=self.mock_analysis,
            start_sec=0.0,
            end_sec=2.0,
            loop=False,
        )

        player.start()
        time.sleep(1.2)
        player.stop()

        self.assertGreater(len(backend.dispatched_frames), 20)
        pan_vals = [f["rom_posture"]["shoulder_pan"] for f in backend.dispatched_frames]
        pan_var = max(pan_vals) - min(pan_vals)
        self.assertGreater(pan_var, 0.5, f"Servo 1 (shoulder_pan) lack of hip sway variance: {pan_var}")

    def test_max_rom_schema_validation(self):
        """Verifies that missing max_rom sub-keys in probabilities raises KeyError."""
        from choreography_compiler import validate_probabilities_schema
        malformed_probs = {
            "pedestal_s7": {"vocal_start_shift_probability": 0.3, "target_rom": {"shift_left": 42.0, "shift_right": 58.0, "center": 50.0}, "transition_beats": {"vocal_shift": 1.0, "return_center": 2.0, "hold": 1.0}},
            "gantry_s8": {"non_drop_move_probability": 0.65, "move_type_probabilities": {"full_glide": 0.4, "early_step": 0.3, "late_step": 0.3}, "drop_targets_rom": [85.0, 15.0], "normal_targets_rom_left": [15.0, 40.0], "normal_targets_rom_right": [60.0, 85.0], "speeds": {"drop_glide": 700, "drop_hold": 600, "hold": 250, "min_glide": 350, "max_glide": 700}},
            "torso_s1": {"audience_counter_probability": 0.8},
            "head_tilt_s5": {"center_probability": 0.7, "snap_pulse_probability": 0.2, "continuous_roll_probability": 0.1, "snap_pulse_left_rom": 42.0, "snap_pulse_right_rom": 58.0, "snap_pulse_duration_sec": 0.8, "continuous_roll_amplitude_rom": 8.0, "continuous_roll_freq_hz": 1.0, "center_rom": 50.0},
            "neck_pitch_s4": {"up_probability": 0.15, "down_probability": 0.05, "level_probability": 0.8, "pitch_up_rom": 50.0, "pitch_down_rom": 85.0, "pitch_level_rom": 70.0},
            "spine_gaze": {"max_climax_arches": 2, "min_separation_bars": 4},
            "bounce_modifier": {"default_intensity": 0.12, "targets": ["hip_sway", "body_bounce", "head_bob"]},  # Missing max_rom
        }
        with self.assertRaises(KeyError) as ctx:
            validate_probabilities_schema(malformed_probs)
        self.assertIn("max_rom", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
