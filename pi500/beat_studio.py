#!/usr/bin/env python3
"""Beat Bandit Choreography Studio & Timeline Storage for SO-101.
Provides:
  - Manifest CRUD and track timeline persistence in manifest.json.
  - Integration with choreography_compiler.py with user-edit preservation.
  - Live hardware preview and pose capture routines.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

try:
    from choreography_compiler import (
        compile_choreography_tracks,
        load_dance_presets,
        load_choreography_probabilities,
        get_choreography_probabilities_path,
        load_choreo_settings,
        ROM_POSES,
        CHOREO_SCHEMA_VERSION,
        DEFAULT_CHOREO_SETTINGS,
        DEFAULT_CHOREO_PROBABILITIES,
    )
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from choreography_compiler import (
        compile_choreography_tracks,
        load_dance_presets,
        load_choreography_probabilities,
        get_choreography_probabilities_path,
        load_choreo_settings,
        ROM_POSES,
        CHOREO_SCHEMA_VERSION,
        DEFAULT_CHOREO_SETTINGS,
        DEFAULT_CHOREO_PROBABILITIES,
    )

logger = logging.getLogger("so101.beat_studio")


def compile_default_choreography(analysis: Dict[str, Any], duration: float, existing_choreo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compiles audio analysis into a structured choreography timeline using the compiler."""
    return compile_choreography_tracks(analysis, duration, existing_choreography=existing_choreo)


class BeatStudioManager:
    """Manager providing full lifecycle CRUD, live preview, capture, and choreography management."""

    def __init__(self, library_dir: Path, manifest_file: Path) -> None:
        self.library_dir = library_dir
        self.manifest_file = manifest_file
        self.logger = logging.getLogger("BeatStudioManager")

    def _load_manifest(self) -> Dict[str, Any]:
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Error reading manifest: {e}")
        return {}

    def _save_manifest(self, manifest: Dict[str, Any]) -> bool:
        try:
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"Error saving manifest: {e}")
            return False

    def get_track_choreography(self, track_id: str) -> Dict[str, Any]:
        """Loads choreography from manifest or auto-compiles if not yet generated or outdated."""
        manifest = self._load_manifest()
        track_meta = manifest.get(track_id)
        if not track_meta:
            raise FileNotFoundError(f"Track '{track_id}' not found in Beat Bandit manifest.")

        choreo = track_meta.get("choreography")
        analysis = track_meta.get("analysis", {})
        duration = float(track_meta.get("duration", 0.0) or analysis.get("duration", 0.0))
        if duration <= 0.0:
            raise ValueError(f"Invalid duration '{duration}' for track '{track_id}'.")

        if not choreo or not choreo.get("tracks") or choreo.get("version") != CHOREO_SCHEMA_VERSION:
            self.logger.info(f"Auto-compiling choreography for '{track_meta.get('title')}' ({track_id})...")
            choreo = compile_default_choreography(analysis, duration, existing_choreo=choreo)
            track_meta["choreography"] = choreo
            manifest[track_id] = track_meta
            self._save_manifest(manifest)

        # Ensure settings is hydrated for fail-fast ChoreographyPlayer contract
        canonical_settings = load_choreo_settings()
        settings_modified = False
        if "settings" not in choreo or not isinstance(choreo["settings"], dict):
            choreo["settings"] = dict(canonical_settings)
            settings_modified = True
        else:
            for k, v in canonical_settings.items():
                if k not in choreo["settings"]:
                    choreo["settings"][k] = v
                    settings_modified = True
        if settings_modified:
            track_meta["choreography"] = choreo
            manifest[track_id] = track_meta
            self._save_manifest(manifest)

        # Ensure probabilities is hydrated for fail-fast ChoreographyPlayer contract
        if "probabilities" not in choreo or not isinstance(choreo["probabilities"], dict):
            choreo["probabilities"] = load_choreography_probabilities()
            track_meta["choreography"] = choreo
            manifest[track_id] = track_meta
            self._save_manifest(manifest)

        # Merge in beat grid metadata for UI ruler
        choreo["track_id"] = track_id
        choreo["title"] = track_meta.get("title", track_id)
        choreo["artist"] = track_meta.get("artist", "")
        tempo_val = track_meta.get("bpm") or track_meta.get("tempo") or analysis.get("bpm") or analysis.get("tempo")
        if tempo_val is None:
            raise KeyError(f"Track '{track_id}' missing 'bpm' or 'tempo' in manifest or audio analysis.")
        choreo["tempo"] = float(tempo_val)
        choreo["beat_times"] = analysis["beat_times"]
        choreo["drops"] = analysis["drops"]
        choreo["amplitude_envelope_50hz"] = analysis["amplitude_envelope_50hz"]
        choreo["mouth_envelope_50hz"] = analysis["mouth_envelope_50hz"]

        return choreo

    def save_track_choreography(self, track_id: str, choreo_data: Dict[str, Any]) -> Dict[str, Any]:
        """Persists edited choreography back into manifest.json."""
        manifest = self._load_manifest()
        if track_id not in manifest:
            raise FileNotFoundError(f"Track '{track_id}' not found in manifest.")

        track_meta = manifest[track_id]
        poses = choreo_data.get("poses") or load_dance_presets()
        probs = choreo_data.get("probabilities") or self.get_probabilities()

        clean_choreo = {
            "version": CHOREO_SCHEMA_VERSION,
            "duration": float(choreo_data.get("duration", track_meta.get("duration", 0.0))),
            "settings": choreo_data.get("settings", DEFAULT_CHOREO_SETTINGS),
            "poses": poses,
            "probabilities": probs,
            "sections": choreo_data.get("sections", []),
            "blocks": choreo_data.get("blocks", []),
            "tracks": choreo_data.get("tracks", {
                "lyrics": [],
                "spine_gaze": [],
                "s8_gantry": [],
                "s7_pedestal": [],
                "s1_torso": [],
                "s5_head_tilt": [],
                "s6_jaw": [],
            }),
            "updated_at": time.time(),
        }
        track_meta["choreography"] = clean_choreo
        manifest[track_id] = track_meta
        self._save_manifest(manifest)
        self.logger.info(f"Successfully saved choreography for '{track_meta.get('title')}' ({track_id}).")
        return {"status": "ok", "track_id": track_id, "updated_at": clean_choreo["updated_at"]}

    def auto_generate_choreography(self, track_id: str, style: str = "balanced", force_clean: bool = False) -> Dict[str, Any]:
        """Re-compiles choreography from analysis with preservation of manual edits."""
        manifest = self._load_manifest()
        track_meta = manifest.get(track_id)
        if not track_meta:
            raise FileNotFoundError(f"Track '{track_id}' not found.")

        existing_choreo = None if force_clean else track_meta.get("choreography")
        analysis = track_meta.get("analysis", {})
        duration = float(track_meta.get("duration", 0.0) or analysis.get("duration", 0.0))
        choreo = compile_default_choreography(analysis, duration, existing_choreo=existing_choreo)

        track_meta["choreography"] = choreo
        manifest[track_id] = track_meta
        self._save_manifest(manifest)
        return choreo

    def get_probabilities(self) -> Dict[str, Any]:
        """Loads master probabilities configuration."""
        return load_choreography_probabilities()

    def save_probabilities(self, probs_data: Dict[str, Any]) -> bool:
        """Validates and persists updated master probabilities configuration to disk."""
        if not isinstance(probs_data, dict):
            raise ValueError("Probabilities payload must be a JSON dictionary.")

        required_sections = ["pedestal_s7", "gantry_s8", "torso_s1", "head_tilt_s5", "neck_pitch_s4", "spine_gaze", "bounce_modifier"]
        for sec in required_sections:
            if sec not in probs_data or not isinstance(probs_data[sec], dict):
                raise KeyError(f"Mandatory section '{sec}' missing from probabilities payload")

        fpath = get_choreography_probabilities_path()
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(probs_data, f, indent=2)
        self.logger.info(f"Saved master probabilities to {fpath}")
        return True

    def preview_pose_on_robot(self, backend: Any, pose_dict: Dict[str, float]) -> Dict[str, Any]:
        """Drives follower arm to target normalized pose for physical verification."""
        if not backend:
            raise RuntimeError("Hardware backend uninitialized.")

        required_joints = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
        for j in required_joints:
            if j not in pose_dict:
                raise KeyError(f"Cannot preview pose: mandatory joint '{j}' missing from pose payload.")

        clean_goals = {
            "shoulder_pan": float(max(-100.0, min(100.0, pose_dict["shoulder_pan"]))),
            "shoulder_lift": float(max(-100.0, min(100.0, pose_dict["shoulder_lift"]))),
            "elbow_flex": float(max(-100.0, min(100.0, pose_dict["elbow_flex"]))),
            "wrist_flex": float(max(-100.0, min(100.0, pose_dict["wrist_flex"]))),
            "wrist_roll": float(max(-100.0, min(100.0, pose_dict["wrist_roll"]))),
            "gripper": float(max(0.0, min(45.0, pose_dict.get("gripper", 0.0)))),
        }

        if hasattr(backend, "set_arm_torque"):
            backend.set_arm_torque(True)
        if hasattr(backend, "interpolate_arm_norm"):
            backend.interpolate_arm_norm(clean_goals, duration=1.0, steps=30)
        elif hasattr(backend, "dispatch_dance_frame"):
            backend.dispatch_dance_frame(clean_goals)
        return {"status": "ok", "preview_pose": clean_goals}

    def capture_arm_current_pose(self, backend: Any, pose_name: str) -> Dict[str, Any]:
        """Reads live joint encoder positions from Servos 1-5 directly and creates a named pose."""
        if not backend:
            raise RuntimeError("Hardware backend uninitialized.")

        res = backend.capture_temporary_arm_pose()
        if not res or "normalized" not in res:
            raise RuntimeError("Failed to capture live arm pose from hardware.")

        normalized = res["normalized"]
        required_joints = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
        for j in required_joints:
            if j not in normalized:
                raise KeyError(f"Captured arm pose missing live telemetry for joint '{j}'.")

        clean_pose = {
            "shoulder_pan": round(float(normalized["shoulder_pan"]), 2),
            "shoulder_lift": round(float(normalized["shoulder_lift"]), 2),
            "elbow_flex": round(float(normalized["elbow_flex"]), 2),
            "wrist_flex": round(float(normalized["wrist_flex"]), 2),
            "wrist_roll": round(float(normalized["wrist_roll"]), 2),
        }
        return {"status": "ok", "pose_name": pose_name, "pose": clean_pose}

    def preview_movement_block(self, backend: Any, channel: str, target_val: Any) -> Dict[str, Any]:
        """Physically tests a specific movement block on target servo."""
        if channel == "s7_pedestal":
            rom = float(target_val)
            backend.dispatch_dance_frame({}, s7_rom=rom)
            return {"status": "ok", "channel": channel, "target_rom": rom}

        elif channel == "s8_gantry":
            rom = float(target_val)
            backend.dispatch_dance_frame({}, s8_goal=rom, s8_is_rom=True, s8_speed=600)
            return {"status": "ok", "channel": channel, "target_pos": rom}

        elif channel in ["spine_gaze", "body_pose"]:
            if isinstance(target_val, str):
                poses = load_dance_presets()
                if target_val in poses:
                    return self.preview_pose_on_robot(backend, poses[target_val])
            elif isinstance(target_val, dict):
                return self.preview_pose_on_robot(backend, target_val)

        elif channel == "s1_torso":
            norm_pan = float(max(0.0, min(100.0, float(target_val))))
            backend.dispatch_dance_frame({"shoulder_pan": norm_pan})
            return {"status": "ok", "channel": channel, "torso_pan": norm_pan}

        elif channel == "s5_head_tilt":
            norm_roll = float(max(0.0, min(100.0, float(target_val))))
            backend.dispatch_dance_frame({"wrist_roll": norm_roll})
            return {"status": "ok", "channel": channel, "head_tilt": norm_roll}
        
        elif channel == "s6_jaw":
            norm_jaw = float(max(0.0, min(45.0, float(target_val))))
            backend.dispatch_dance_frame({"gripper": norm_jaw})
            return {"status": "ok", "channel": channel, "jaw": norm_jaw}

        return {"status": "error", "message": f"Unsupported channel '{channel}'"}


_GLOBAL_STUDIO_MANAGER: Optional[BeatStudioManager] = None


def get_global_studio_manager() -> BeatStudioManager:
    global _GLOBAL_STUDIO_MANAGER
    if _GLOBAL_STUDIO_MANAGER is None:
        if os.name == "nt":
            lib_dir = Path(__file__).resolve().parent.parent / "library" / "beat_bandit"
        else:
            lib_dir = Path.home() / "so101" / "library" / "beat_bandit"
        lib_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = lib_dir / "manifest.json"
        _GLOBAL_STUDIO_MANAGER = BeatStudioManager(lib_dir, manifest_file)
    return _GLOBAL_STUDIO_MANAGER
