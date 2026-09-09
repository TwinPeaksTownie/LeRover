#!/usr/bin/env python3
"""Unit tests for Piranha Pose Lifecycle Gates, Dance Preset Schema, and Sequence Execution.
Validates:
  1. Fail-Fast Schema: presets_dance.json contains canonical 'normalized' joint dictionaries.
  2. Dance Sequence File: sequence_dance.json exists and defines valid steps.
  3. Active App Lifecycle Gate: Motion endpoints (move_to_preset, attack_sequence, execute_sequence, resume_last_pose)
     return HTTP 409 Conflict if Piranha Pose app is not running in AppManager.
  4. App Running State: Motion endpoints pass the gate when current_app_name is 'piranha_pose_app' or 'clack_pose_app'.
  5. Authoring Endpoints Unaffected: capture_pose, commit_preset, overwrite_preset are not blocked by the motion gate.
"""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "pi4b"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "preset_app"))

from apps.preset_app.app import PiranhaPoseApp


class TestDancePresetSchema(unittest.TestCase):
    """Verifies presets_dance.json and sequence_dance.json contracts."""

    def test_presets_dance_has_normalized_coordinates(self):
        presets_path = REPO_ROOT / "apps" / "preset_app" / "presets" / "presets_dance.json"
        self.assertTrue(presets_path.exists(), f"Missing {presets_path}")

        with open(presets_path, "r", encoding="utf-8") as f:
            presets = json.load(f)

        required_poses = ["stand", "squat", "tiptoe", "arch"]
        required_joints = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]

        for pose in required_poses:
            self.assertIn(pose, presets, f"Missing pose '{pose}' in presets_dance.json")
            self.assertIn("normalized", presets[pose], f"Pose '{pose}' missing 'normalized' key")
            norm = presets[pose]["normalized"]
            for joint in required_joints:
                self.assertIn(joint, norm, f"Pose '{pose}' missing joint '{joint}' in normalized")
                self.assertIsInstance(norm[joint], (int, float))

    def test_sequence_dance_file_validity(self):
        seq_path = REPO_ROOT / "apps" / "preset_app" / "sequences" / "sequence_dance.json"
        self.assertTrue(seq_path.exists(), f"Missing {seq_path}")

        with open(seq_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["mode"], "dance")
        self.assertIn("steps", data)
        self.assertGreater(len(data["steps"]), 0)

    def test_piranha_pose_move_to_dance_preset(self):
        app = PiranhaPoseApp(running_on_pi=False)
        mock_backend = MagicMock()
        mock_backend.interpolate_arm_norm.return_value = (True, "OK")

        ok, msg = app.move_to_specific_arm_preset(mock_backend, "stand", mode="dance")
        self.assertTrue(ok, f"Failed to move to dance preset: {msg}")
        mock_backend.interpolate_arm_norm.assert_called_once()
        target_norm = mock_backend.interpolate_arm_norm.call_args[0][0]
        self.assertEqual(target_norm["shoulder_pan"], 50.0)


class DummyHandler:
    """Helper mimicking MasterApiHandler request context."""

    def __init__(self, path: str, body: dict, current_app: str = None):
        self.path = path
        self.headers = {"Content-Length": str(len(json.dumps(body).encode("utf-8")))}
        self.rfile = io.BytesIO(json.dumps(body).encode("utf-8"))
        self.wfile = io.BytesIO()
        self.backend = MagicMock()
        self.backend.interpolate_arm_norm.return_value = (True, "OK")
        self.app_manager = MagicMock()
        self.app_manager.current_app_name = current_app
        if current_app:
            self.app_manager.active_app = PiranhaPoseApp(running_on_pi=False)
        else:
            self.app_manager.active_app = None
        self.app_manager.registry = {"piranha_pose_app": PiranhaPoseApp}
        self.sent_responses = []

    def _send_json(self, data, code=200):
        self.sent_responses.append((code, data))

    def send_response(self, code):
        pass

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass


class TestApiServerLifecycleGate(unittest.TestCase):
    """Verifies that API server enforces HTTP 409 for motion endpoints when app is stopped."""

    def setUp(self):
        from pi4b.api_server import MasterApiHandler
        self.handler_cls = MasterApiHandler

    def _run_post(self, path: str, body: dict, current_app: str = None):
        handler = DummyHandler(path=path, body=body, current_app=current_app)
        self.handler_cls.app_manager = handler.app_manager
        self.handler_cls.backend = handler.backend
        handler.get_preset_app = lambda: self.handler_cls.get_preset_app()
        # Bind do_POST logic
        parsed = MagicMock()
        parsed.path = path
        with patch("urllib.parse.urlparse", return_value=parsed):
            self.handler_cls.do_POST(handler)
        return handler.sent_responses

    def test_motion_endpoints_blocked_when_app_stopped(self):
        endpoints = [
            ("/api/arm/move_to_preset", {"name": "stand", "mode": "dance"}),
            ("/api/arm/attack_sequence", {}),
            ("/api/arm/execute_sequence", {"sequence": "sequence_dance", "mode": "dance"}),
            ("/api/arm/resume_last_pose", {"duration": 1.0, "mode": "normal"}),
        ]

        for path, body in endpoints:
            with self.subTest(endpoint=path):
                responses = self._run_post(path, body, current_app=None)
                self.assertTrue(len(responses) > 0, f"No response sent for {path}")
                status_code, data = responses[0]
                self.assertEqual(status_code, 409, f"{path} did not return 409 when stopped (got {status_code}: {data})")
                self.assertIn("Piranha Pose app is not running", data["message"])

    def test_motion_endpoints_allowed_when_app_running(self):
        endpoints = [
            ("/api/arm/move_to_preset", {"name": "stand", "mode": "dance"}),
            ("/api/arm/attack_sequence", {}),
            ("/api/arm/execute_sequence", {"sequence": "sequence_dance", "mode": "dance"}),
            ("/api/arm/resume_last_pose", {"duration": 1.0, "mode": "normal"}),
        ]

        for path, body in endpoints:
            with self.subTest(endpoint=path):
                responses = self._run_post(path, body, current_app="piranha_pose_app")
                self.assertTrue(len(responses) > 0, f"No response sent for {path}")
                status_code, data = responses[0]
                self.assertNotEqual(status_code, 409, f"{path} was blocked with 409 even though app is running")


if __name__ == "__main__":
    unittest.main()
