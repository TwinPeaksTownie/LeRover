#!/usr/bin/env python3
"""tests/test_acoustic_safety_interlock.py - Verifies locomotion safety interlock and acoustic attack gating."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "pi4b"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "preset_app"))

from apps.preset_app.app import PiranhaPoseApp


class TestAcousticSafetyInterlock(unittest.TestCase):
    """Verifies that acoustic tap triggers strictly adhere to server-side locomotion interlocks."""

    def setUp(self):
        self.app = PiranhaPoseApp(running_on_pi=False)
        self.backend = MagicMock()
        self.backend.aux_calibration = {"7": {"min_ticks": 0, "max_ticks": 4096, "center_ticks": 2048}}
        self.backend.interpolate_arm_norm.return_value = (True, "OK")

    @patch("apps.preset_app.app.threading.Thread")
    @patch("apps.preset_app.app.dispatch_audio_event")
    def test_acoustic_tap_skips_drive_burst_when_locomotion_disabled(self, mock_dispatch_audio, mock_thread):
        """Acoustic tap trigger must NOT spawn _drive_burst_helper thread when allow_acoustic_locomotion is False."""
        self.app.config["clack_detector"]["allow_acoustic_locomotion"] = False
        self.app.config["clack_detector"]["acoustic_attack_enabled"] = True

        # Mock presets
        dummy_keyframes = {
            "lunge": {"normalized": {"shoulder_pan": 50.0}},
            "ready": {"normalized": {"shoulder_pan": 50.0}},
            "roar": {"normalized": {"shoulder_pan": 50.0}},
            "pose_1": {"normalized": {"shoulder_pan": 50.0}},
        }
        self.app.get_arm_presets = MagicMock(return_value=dummy_keyframes)
        self.app._execute_arm_and_pedestal_sweep = MagicMock()
        self.app._execute_roar_pan_sweep = MagicMock()

        ok, msg = self.app.execute_attack_sequence(self.backend, source="acoustic_tap")

        self.assertTrue(ok)
        # Verify drive burst thread was NOT created
        for call_item in mock_thread.call_args_list:
            kwargs = call_item[1] if len(call_item) > 1 else {}
            self.assertNotEqual(kwargs.get("target"), self.app._drive_burst_helper,
                                "Drive burst helper must not be spawned on acoustic_tap when allow_acoustic_locomotion=False")

    @patch("apps.preset_app.app.threading.Thread")
    @patch("apps.preset_app.app.dispatch_audio_event")
    def test_ui_trigger_allows_drive_burst(self, mock_dispatch_audio, mock_thread):
        """UI trigger must spawn _drive_burst_helper thread even when allow_acoustic_locomotion is False."""
        self.app.config["clack_detector"]["allow_acoustic_locomotion"] = False
        self.app.config["clack_detector"]["acoustic_attack_enabled"] = True

        dummy_keyframes = {
            "lunge": {"normalized": {"shoulder_pan": 50.0}},
            "ready": {"normalized": {"shoulder_pan": 50.0}},
            "roar": {"normalized": {"shoulder_pan": 50.0}},
            "pose_1": {"normalized": {"shoulder_pan": 50.0}},
        }
        self.app.get_arm_presets = MagicMock(return_value=dummy_keyframes)
        self.app._execute_arm_and_pedestal_sweep = MagicMock()
        self.app._execute_roar_pan_sweep = MagicMock()

        ok, msg = self.app.execute_attack_sequence(self.backend, source="ui")

        self.assertTrue(ok)
        # Verify drive burst thread WAS created for UI trigger
        spawned_targets = [call_item[1].get("target") for call_item in mock_thread.call_args_list if "target" in call_item[1]]
        self.assertIn(self.app._drive_burst_helper, spawned_targets,
                      "Drive burst helper must be spawned for UI trigger")

    @patch("apps.preset_app.app.dispatch_audio_event")
    def test_acoustic_attack_disabled_gates_early(self, mock_dispatch_audio):
        """When acoustic_attack_enabled is False, acoustic tap trigger returns early with warning chime."""
        self.app.config["clack_detector"]["acoustic_attack_enabled"] = False
        self.app.get_arm_presets = MagicMock()

        ok, msg = self.app.execute_attack_sequence(self.backend, source="acoustic_tap")

        self.assertTrue(ok)
        self.assertEqual(msg, "Acoustic attack sequence disabled by config")
        # Ensure arm keyframes were never queried or touched
        self.app.get_arm_presets.assert_not_called()
        mock_dispatch_audio.assert_called_with(kind="incorrect", stop_previous=True)


if __name__ == "__main__":
    unittest.main()
