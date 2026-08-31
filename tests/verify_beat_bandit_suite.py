#!/usr/bin/env python3
"""Comprehensive Beat Bandit Verification Suite.
Validates the 5 decoupled architectural layers and tests the 5 mandatory failure modes:
  1. Audio Isolation Audit (Zero audio processing / requests in beat_bandit_app.py)
  2. Headless Motion Simulation (50 Hz ChoreographyPlayer against mock backend)
  3. Hardware Dispatch Leak Check (SERIAL_LOCK / sync_write / raw tick math isolation)
  4. User-Edit Preservation Test (Re-compile preserves is_user_edited blocks)
  5. Synchronized Stop Verification (Simultaneous audio halt, thread termination, neutral return)
"""

import ast
import io
import json
import os
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
PI500_DIR = REPO_ROOT / "pi500"
sys.path.insert(0, str(PI500_DIR))

import beat_bandit_audio
from choreography_compiler import compile_choreography_tracks, partition_timeline_into_blocks, load_dance_presets, CHOREO_SCHEMA_VERSION
from choreography_player import ChoreographyPlayer
from beat_bandit_app import BeatBanditApp
from robot_backend import RobotBackend, SERIAL_LOCK


# =============================================================================
# 1. AUDIO ISOLATION AUDIT
# =============================================================================
class TestAudioIsolationAudit(unittest.TestCase):
    """Failure Mode 1: Verifies beat_bandit_app has zero audio processing leaks
    and beat_bandit_audio functions completely independently.
    """

    def test_ast_beat_bandit_app_imports(self):
        """Statically inspects beat_bandit_app.py AST to verify zero disallowed imports."""
        app_path = PI500_DIR / "beat_bandit_app.py"
        with open(app_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(app_path))

        prohibited_modules = {"requests", "wave", "scipy", "soundfile", "pydub"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name,
                        prohibited_modules,
                        f"Architecture Violation: Prohibited audio/network module '{alias.name}' imported in beat_bandit_app.py",
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(
                        node.module,
                        prohibited_modules,
                        f"Architecture Violation: Prohibited audio/network module '{node.module}' imported in beat_bandit_app.py",
                    )
                if node.module == "io":
                    for alias in node.names:
                        self.assertNotEqual(
                            alias.name,
                            "BytesIO",
                            "Architecture Violation: 'BytesIO' for in-memory audio slicing must NOT be imported in beat_bandit_app.py",
                        )

    def test_in_memory_wav_slicing_independent(self):
        """Tests that beat_bandit_audio slices WAV files in memory without external app dependencies."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = os.path.join(tmp_dir, "test.wav")
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                wf.writeframes(b"\x00" * (44100 * 4))  # 1 second of audio

            sliced = beat_bandit_audio.slice_wav_in_memory(wav_path, start_sec=0.25, end_sec=0.75)
            self.assertGreater(len(sliced), 44)

            buf = io.BytesIO(sliced)
            with wave.open(buf, "rb") as wf:
                self.assertEqual(wf.getnchannels(), 2)
                self.assertEqual(wf.getframerate(), 44100)
                # 0.5 sec * 44100 = 22050 frames
                self.assertAlmostEqual(wf.getnframes(), 22050, delta=10)

    def test_title_and_artist_sanitizer(self):
        """Tests cleaning artist and title strings in beat_bandit_audio."""
        raw = "Queen - Bohemian Rhapsody (Official Video) [Remastered 4K]"
        song, artist = beat_bandit_audio.sanitize_title_and_artist(raw)
        self.assertEqual(song, "Bohemian Rhapsody")
        self.assertEqual(artist, "Queen")


# =============================================================================
# 2. HEADLESS MOTION SIMULATION
# =============================================================================
class MockHeadlessBackend:
    """Mock hardware backend collecting 50 Hz frame dispatches without serial hardware."""

    def __init__(self):
        self.frames: List[Dict[str, Any]] = []
        self.torque_enabled = False

    def set_arm_torque(self, enabled: bool):
        self.torque_enabled = enabled

    def dispatch_dance_frame(
        self,
        rom_posture: Dict[str, float],
        s7_rom: float = 50.0,
        s8_goal: float = 50.0,
        s8_is_rom: bool = True,
        s8_speed: int = 500,
    ):
        self.frames.append({
            "timestamp": time.time(),
            "rom": dict(rom_posture),
            "s7_rom": float(s7_rom),
            "s8_goal": s8_goal,
            "s8_speed": s8_speed,
        })
        return {"status": "ok"}


class TestHeadlessMotionSimulation(unittest.TestCase):
    """Failure Mode 2: Verifies ChoreographyPlayer executes a 50 Hz interpolated loop
    against a mock backend without crashing, without web servers, and without serial ports.
    """

    def setUp(self):
        self.analysis = {
            "title": "Headless Simulation Track",
            "duration": 4.0,
            "bpm": 120.0,
            "beat_times": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
            "lyrics": [
                {"id": "ly_001", "name": "Vocal 1", "text": "Testing 50Hz Loop", "start_sec": 0.5, "end_sec": 2.5, "type": "lyric"}
            ],
            "sections": [
                {"start_sec": 0.0, "end_sec": 4.0, "type": "verse", "energy_score": 0.7}
            ],
            "drops": [{"drop_sec": 2.0}],
            "held_notes": [{"start_sec": 1.0, "end_sec": 1.8}],
            "mouth_envelope_50hz": [0.0] * 25 + [30.0] * 100 + [0.0] * 75,
        }
        self.choreo = compile_choreography_tracks(self.analysis, duration=4.0)
        self.mock_backend = MockHeadlessBackend()

    def test_headless_50hz_interpolation_execution(self):
        """Runs headless player for 1.0 simulated second and audits 50 Hz frame stream."""
        player = ChoreographyPlayer(
            backend=self.mock_backend,
            choreography=self.choreo,
            analysis=self.analysis,
            start_sec=0.0,
            end_sec=3.0,
            loop=False,
        )

        player.start()
        self.assertTrue(player.is_playing)
        time.sleep(1.0)
        status = player.get_status()
        player.stop()

        self.assertFalse(player.is_playing)
        self.assertGreater(status["time_sec"], 0.3)
        self.assertGreater(len(self.mock_backend.frames), 20)

        # Audit joint ROM boundaries
        for frame in self.mock_backend.frames:
            rom = frame["rom"]
            for jname, val in rom.items():
                self.assertGreaterEqual(val, 0.0, f"Joint {jname} value {val} < 0.0% ROM")
                self.assertLessEqual(val, 100.0, f"Joint {jname} value {val} > 100.0% ROM")

            # Gripper / Jaw must never exceed 45.0% ROM singing limit
            self.assertLessEqual(rom.get("gripper", 0.0), 45.0, "Singing jaw exceeded 45% ROM limit")

            # Pedestal and Gantry values
            self.assertGreaterEqual(frame["s7_rom"], 0.0)
            self.assertLessEqual(frame["s7_rom"], 100.0)


# =============================================================================
# 3. HARDWARE DISPATCH & LEAK CHECK
# =============================================================================
class TestHardwareDispatchLeakCheck(unittest.TestCase):
    """Failure Mode 3: Verifies SERIAL_LOCK, sync_write, and raw tick math
    are contained within robot_backend.py and not leaked into player, app, or studio.
    """

    def test_ast_leak_check_choreography_player(self):
        """Ensures choreography_player has zero serial bus leaks."""
        player_path = PI500_DIR / "choreography_player.py"
        with open(player_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertNotIn("SERIAL_LOCK", code, "SERIAL_LOCK leaked into choreography_player.py")
        self.assertNotIn("sync_write", code, "sync_write leaked into choreography_player.py")
        self.assertNotIn("write_goal_raw", code, "write_goal_raw leaked into choreography_player.py")

    def test_ast_leak_check_beat_bandit_app(self):
        """Ensures beat_bandit_app has zero serial bus leaks."""
        app_path = PI500_DIR / "beat_bandit_app.py"
        with open(app_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertNotIn("SERIAL_LOCK", code, "SERIAL_LOCK leaked into beat_bandit_app.py")
        self.assertNotIn("sync_write", code, "sync_write leaked into beat_bandit_app.py")
        self.assertNotIn("write_goal_raw", code, "write_goal_raw leaked into beat_bandit_app.py")

    def test_ast_leak_check_beat_studio(self):
        """Ensures beat_studio has zero serial bus or raw lock leaks."""
        studio_path = PI500_DIR / "beat_studio.py"
        with open(studio_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertNotIn("SERIAL_LOCK", code, "SERIAL_LOCK leaked into beat_studio.py")
        self.assertNotIn("sync_write", code, "sync_write leaked into beat_studio.py")
        self.assertNotIn("write_goal_raw", code, "write_goal_raw leaked into beat_studio.py")

    def test_robot_backend_dispatch_dance_frame_tick_math(self):
        """Verifies RobotBackend.dispatch_dance_frame properly manages multi-servo tick math internally."""
        backend = RobotBackend.__new__(RobotBackend)
        backend.lock = MagicMock()
        backend.servos = {i: {"normalized": 50.0, "pos": 2048, "raw": 2048, "torque": False} for i in range(1, 9)}
        backend.arm_calibration = {
            "shoulder_pan": {"range_min": 1000, "range_max": 3000},
            "shoulder_lift": {"range_min": 1000, "range_max": 3000},
            "elbow_flex": {"range_min": 1000, "range_max": 3000},
            "wrist_flex": {"range_min": 1000, "range_max": 3000},
            "wrist_roll": {"range_min": 1000, "range_max": 3000},
            "gripper": {"range_min": 500, "range_max": 1500},
        }
        backend.aux_calibration = {
            "7": {"min_ticks": 1000, "max_ticks": 3000, "center_ticks": 2000},
            "8": {"min_ticks": 500, "max_ticks": 4500},
        }
        backend.bus = MagicMock()
        backend.ctrl = MagicMock()
        backend.move_target = MagicMock()

        rom_posture = {
            "shoulder_pan": 50.0,   # (1000 + 0.5 * 2000) = 2000
            "shoulder_lift": 0.0,   # (1000 + 0.0 * 2000) = 1000
            "elbow_flex": 100.0,    # (1000 + 1.0 * 2000) = 3000
            "wrist_flex": 50.0,     # (1000 + 0.5 * 2000) = 2000
            "wrist_roll": 50.0,     # (1000 + 0.5 * 2000) = 2000
            "gripper": 25.0,        # (500 + 0.25 * 1000) = 750
        }

        res = backend.dispatch_dance_frame(rom_posture, s7_rom=50.0, s8_goal=50.0, s8_is_rom=True)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["goal_ticks"]["shoulder_pan"], 2000)
        self.assertEqual(res["goal_ticks"]["shoulder_lift"], 1000)
        self.assertEqual(res["goal_ticks"]["elbow_flex"], 3000)
        self.assertEqual(res["goal_ticks"]["gripper"], 750)
        self.assertEqual(res["s7_ticks"], 2000)
        self.assertEqual(res["s8_ticks"], 2500)

        # Verify underlying bus sync_write was called with ticks
        backend.bus.sync_write.assert_called_once_with("Goal_Position", res["goal_ticks"], normalize=False)
        backend.ctrl.write_goal_raw.assert_called_once_with(7, 2000, speed=800)
        backend.move_target.assert_called_once_with(8, 2500, speed=500, max_t=800)


# =============================================================================
# 4. USER-EDIT PRESERVATION TEST
# =============================================================================
class TestUserEditPreservation(unittest.TestCase):
    """Failure Mode 4: Verifies compile_choreography_tracks strictly preserves
    blocks where is_user_edited is True while updating unedited blocks.
    """

    def setUp(self):
        self.analysis = {
            "title": "Preservation Test Song",
            "duration": 12.0,
            "bpm": 120.0,
            "beat_times": [i * 0.5 for i in range(24)],
            "lyrics": [
                {"id": "ly_001", "name": "Line 1", "text": "First vocal", "start_sec": 1.0, "end_sec": 4.0, "type": "lyric"},
                {"id": "ly_002", "name": "Line 2", "text": "Second vocal", "start_sec": 5.0, "end_sec": 8.0, "type": "lyric"},
                {"id": "ly_003", "name": "Line 3", "text": "Third vocal", "start_sec": 9.0, "end_sec": 11.0, "type": "lyric"},
            ],
            "sections": [
                {"start_sec": 0.0, "end_sec": 12.0, "type": "verse", "energy_score": 0.5}
            ],
            "drops": [],
            "held_notes": [],
            "mouth_envelope_50hz": [0.0] * 600,
        }

    def test_user_edit_preservation_across_recompiles(self):
        """Preserves custom user edits across re-compiles with differing seeds."""
        base_choreo = compile_choreography_tracks(self.analysis, duration=12.0, seed=1)

        # Inject manual user edits into block 'ly_002'
        custom_s8_move = {
            "id": "s8_ly_002",
            "block_id": "ly_002",
            "name": "Custom User S8 Move",
            "mode": "custom_rail_sweep",
            "start_sec": 5.0,
            "end_sec": 8.0,
            "target_pos_rom": 88.8,
            "speed": 666,
            "is_user_edited": True,
        }
        custom_s7_move = {
            "id": "s7_ly_002",
            "block_id": "ly_002",
            "name": "Custom User S7 Snap",
            "mode": "snap_left",
            "start_sec": 5.0,
            "end_sec": 8.0,
            "target_pos_rom": 12.3,
            "transition_sec": 0.15,
            "is_user_edited": True,
        }

        existing_choreo = dict(base_choreo)
        # Find index for ly_002 in tracks
        s8_idx = next(i for i, b in enumerate(existing_choreo["tracks"]["s8_gantry"]) if b.get("block_id") == "ly_002")
        s7_idx = next(i for i, b in enumerate(existing_choreo["tracks"]["s7_pedestal"]) if b.get("block_id") == "ly_002")
        existing_choreo["tracks"]["s8_gantry"][s8_idx] = custom_s8_move
        existing_choreo["tracks"]["s7_pedestal"][s7_idx] = custom_s7_move

        # Recompile with seed 4242
        recompiled = compile_choreography_tracks(
            self.analysis,
            duration=12.0,
            seed=4242,
            existing_choreography=existing_choreo,
        )

        self.assertEqual(recompiled["version"], CHOREO_SCHEMA_VERSION)

        # Assert custom moves were strictly preserved
        s8_preserved = next(b for b in recompiled["tracks"]["s8_gantry"] if b.get("block_id") == "ly_002")
        self.assertEqual(s8_preserved["target_pos_rom"], 88.8)
        self.assertEqual(s8_preserved["speed"], 666)
        self.assertEqual(s8_preserved["mode"], "custom_rail_sweep")

        s7_preserved = next(b for b in recompiled["tracks"]["s7_pedestal"] if b.get("block_id") == "ly_002")
        self.assertEqual(s7_preserved["target_pos_rom"], 12.3)
        self.assertEqual(s7_preserved["transition_sec"], 0.15)


# =============================================================================
# 5. SYNCHRONIZED STOP VERIFICATION
# =============================================================================
class TestSynchronizedStopVerification(unittest.TestCase):
    """Failure Mode 5: Verifies stop command simultaneously halts Pi 4B audio stream,
    terminates 50 Hz thread on Pi 500, and returns all 8 actuators to neutral positions.
    """

    def setUp(self):
        self.app = BeatBanditApp(running_on_pi=False)
        self.mock_backend = MagicMock()
        self.mock_backend.dispatch_dance_frame = MagicMock(return_value={"status": "ok"})

        self.analysis = {
            "title": "Stop Verification Song",
            "duration": 5.0,
            "bpm": 120.0,
            "beat_times": [i * 0.5 for i in range(10)],
            "lyrics": [{"id": "ly_001", "name": "Vocal", "text": "Halt test", "start_sec": 0.5, "end_sec": 4.0, "type": "lyric"}],
            "sections": [{"start_sec": 0.0, "end_sec": 5.0, "type": "verse", "energy_score": 0.5}],
            "drops": [],
            "held_notes": [],
            "mouth_envelope_50hz": [0.0] * 250,
        }

        self.app.active_track = {
            "track_id": "stop_test_001",
            "title": "Stop Verification Song",
            "artist": "Test",
            "duration": 5.0,
            "bpm": 120.0,
            "wav_path": "/tmp/dummy.wav",
            "analysis": self.analysis,
            "choreography": compile_choreography_tracks(self.analysis, 5.0),
        }
        self.app.active_analysis = self.analysis

    @patch("beat_bandit_audio.urllib.request.urlopen")
    def test_synchronized_stop_execution(self, mock_urlopen):
        """Starts player, commands stop, and asserts all 3 halt actions execute cleanly."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # 1. Start playback session
        self.app._start_player_session(self.mock_backend, start_sec=0.0, end_sec=5.0, loop=False)
        self.assertIsNotNone(self.app.player)
        self.assertTrue(self.app.player.is_playing)
        self.assertEqual(self.app.current_state, "DANCING")

        time.sleep(0.3)

        # 2. Command Synchronized Stop
        self.app.stop_dance()

        # Check 1: 50 Hz player thread dead and cleared
        self.assertIsNone(self.app.player)
        self.assertEqual(self.app.current_state, "IDLE")

        # Check 2: Pi 4B audio stop HTTP dispatch triggered
        self.assertGreaterEqual(mock_urlopen.call_count, 1)

        # Check 3: Final neutral posture dispatched to all 8 servos
        self.assertGreaterEqual(self.mock_backend.dispatch_dance_frame.call_count, 2)
        final_call_args = self.mock_backend.dispatch_dance_frame.call_args_list[-1]
        final_kwargs = final_call_args[1]
        self.assertEqual(final_kwargs.get("s7_rom"), 50.0, "Servo 7 failed to return to neutral (50% ROM)")
        self.assertEqual(final_kwargs.get("s8_goal"), 50.0, "Servo 8 failed to return to center rail (50% ROM)")

        final_arm_rom = final_call_args[0][0] if final_call_args[0] else final_kwargs.get("rom_posture", {})
        self.assertEqual(final_arm_rom.get("gripper"), 0.0, "Gripper / Jaw failed to close (0% ROM) on stop")


if __name__ == "__main__":
    unittest.main()
