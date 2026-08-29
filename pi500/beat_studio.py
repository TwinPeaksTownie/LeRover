#!/usr/bin/env python3
"""Beat Bandit Choreography Studio & Timeline Engine for SO-101.
Provides:
  - Multi-track linear timeline representation (Body Postures, Pedestal, Gantry, Head/Jaw, Vocal Style).
  - 4-bar block (16 beats) choreography compiler from audio analysis.
  - CRUD operations for movement blocks and preset loading from presets_dance.json.
  - Live hardware preview with safe interpolation and pose capture routines.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

DEFAULT_SETTINGS = {
    "jaw_gate_threshold": 0.18,
    "jaw_max_open": 45.0,
    "head_nod_depth": 6.0,
    "vibrato_amplitude": 20.0,
    "gantry_default_speed": 800,
    "joint_alphas": {
        "wrist_flex": 0.35,
        "elbow_flex": 0.35,
        "wrist_roll": 0.25,
        "shoulder_lift": 0.15,
        "shoulder_pan": 0.15,
    },
}


def get_dance_presets_path() -> Path:
    """Resolves the empirical presets_dance.json file path."""
    base_dir = Path(__file__).resolve().parent.parent
    p1 = base_dir / "apps" / "preset_app" / "presets" / "presets_dance.json"
    if p1.exists():
        return p1
    p2 = Path.home() / "so101" / "apps" / "preset_app" / "presets" / "presets_dance.json"
    if p2.exists():
        return p2
    raise FileNotFoundError(f"presets_dance.json not found at {p1} or {p2}")


def get_aux_calibration_path() -> Path:
    base_dir = Path(__file__).resolve().parent.parent
    p1 = Path.home() / "so101" / "calibration_aux.json"
    if p1.exists():
        return p1
    p2 = base_dir / "calibration_aux.json"
    if p2.exists():
        return p2
    return p1


def get_s8_rail_bounds() -> Tuple[int, int]:
    fpath = get_aux_calibration_path()
    if fpath.exists():
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "8" in data and "min_ticks" in data["8"] and "max_ticks" in data["8"]:
                    return int(data["8"]["min_ticks"]), int(data["8"]["max_ticks"])
        except Exception:
            pass
    return 3, 4800


def calc_s8_rail_pos(pct: float) -> int:
    """Computes tick position for Motor 8 based on normalized travel percentage (0.0 to 1.0)
    clamped strictly to a safe mechanical envelope between 10% and 90% travel span.
    """
    min_t, max_t = get_s8_rail_bounds()
    clamped_pct = max(0.10, min(0.90, float(pct)))
    return int(round(min_t + clamped_pct * (max_t - min_t)))


def load_dance_presets() -> Dict[str, Dict[str, float]]:
    """Loads empirical normalized joint postures strictly from presets_dance.json."""
    fpath = get_dance_presets_path()
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    clean_poses = {}
    for name, pdata in data.items():
        if name.lower() == "arch":
            continue
        if isinstance(pdata, dict) and "normalized" in pdata:
            clean_poses[name] = {
                k: float(v)
                for k, v in pdata["normalized"].items()
                if k in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
            }
        elif isinstance(pdata, dict):
            clean_poses[name] = {
                k: float(v)
                for k, v in pdata.items()
                if k in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
            }

    if "stand" not in clean_poses:
        raise ValueError(f"Mandatory 'stand' posture missing in {fpath}")
    return clean_poses


def blend_5joint_poses(p_a: Dict[str, float], p_b: Dict[str, float], alpha: float) -> Dict[str, float]:
    """Blends between two 5-joint normalized poses (alpha 0.0 to 1.0)."""
    alpha = max(0.0, min(1.0, float(alpha)))
    res = {}
    for j in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]:
        if j not in p_a or j not in p_b:
            raise KeyError(f"Mandatory joint '{j}' missing during pose interpolation.")
        va = float(p_a[j])
        vb = float(p_b[j])
        res[j] = va + (vb - va) * alpha
    return res


def compile_default_choreography(analysis: Dict[str, Any], duration: float) -> Dict[str, Any]:
    """Compiles audio analysis (beats, drops, sections, held notes) into a complete,
    structured multi-track linear timeline organized around 4-bar blocks (16 beats).
    """
    if not analysis:
        raise ValueError("Cannot compile choreography: audio 'analysis' payload is empty or missing.")

    duration = float(duration or analysis.get("duration", 0.0))
    if duration <= 0.0:
        raise ValueError(f"Invalid duration '{duration}' for choreography compilation.")

    beat_times = analysis.get("beat_times", [])
    if not beat_times:
        raise ValueError("Cannot compile choreography: 'beat_times' missing or empty in audio analysis.")

    drops = analysis.get("drops", [])
    sections = analysis.get("sections", [])
    if not sections:
        # Auto-partition sections from 16-beat (4-bar) intervals
        sections = []
        for idx in range(0, len(beat_times), 16):
            st = float(beat_times[idx])
            end_idx = min(idx + 16, len(beat_times) - 1)
            et = float(beat_times[end_idx]) if end_idx < len(beat_times) else duration
            sections.append({
                "start_sec": st,
                "end_sec": et,
                "type": "CHORUS_DROP" if any(d.get("drop_sec", 0.0) >= st and d.get("drop_sec", 0.0) < et for d in drops) else "VERSE_GROOVE"
            })

    held_notes = analysis.get("held_notes", [])

    # Load real calibration poses
    choreo_poses = load_dance_presets()
    p_stand = choreo_poses["stand"]
    p_tiptoe = choreo_poses["tiptoe"]
    p_squat = choreo_poses["squat"]

    # 1. Sections breakdown
    sec_blocks = []
    for idx, s in enumerate(sections):
        st = float(s.get("start_sec", 0.0))
        et = min(duration, float(s.get("end_sec", duration)))
        stype = str(s.get("type", "VERSE_GROOVE"))
        sec_blocks.append({
            "id": f"sec_{idx + 1}",
            "name": stype.replace("_", " ").title(),
            "type": stype,
            "start_sec": round(st, 2),
            "end_sec": round(et, 2),
        })

    # Timeline Tracks
    body_moves = []
    s7_moves = []
    s8_moves = []
    vocal_moves = []

    # Check intro section
    intro_sec = next((s for s in sections if s.get("type") == "BEATLESS_INTRO"), None)
    intro_end = float(intro_sec.get("end_sec", 0.0)) if intro_sec else 0.0

    if intro_end > 3.0:
        body_moves.append({
            "id": f"bm_{uuid.uuid4().hex[:6]}",
            "name": "Cinematic Intro Stance",
            "pose_name": "stand",
            "start_sec": 0.0,
            "end_sec": round(intro_end, 2),
            "transition_sec": 1.5,
        })
        s7_moves.append({
            "id": f"s7_{uuid.uuid4().hex[:6]}",
            "name": "Front Facing Stage",
            "start_sec": 0.0,
            "end_sec": round(intro_end, 2),
            "target_deg": 0.0,
            "transition_sec": 0.8,
        })
        s8_moves.append({
            "id": f"s8_{uuid.uuid4().hex[:6]}",
            "name": "Intro Stage Left Glide",
            "start_sec": 0.0,
            "end_sec": round(min(intro_end * 0.5, 12.0), 2),
            "target_pos": calc_s8_rail_pos(0.75),
            "speed": 220,
        })
        s8_moves.append({
            "id": f"s8_{uuid.uuid4().hex[:6]}",
            "name": "Intro Return Center",
            "start_sec": round(min(intro_end * 0.5, 12.0), 2),
            "end_sec": round(intro_end, 2),
            "target_pos": calc_s8_rail_pos(0.50),
            "speed": 250,
        })
        vocal_moves.append({
            "id": f"voc_{uuid.uuid4().hex[:6]}",
            "name": "Intro Storytelling",
            "style": "conversational",
            "start_sec": 0.0,
            "end_sec": round(intro_end, 2),
        })

    # Divide active groove into 4-bar blocks (16 beats each)
    groove_start = intro_end
    total_beats = len(beat_times)
    start_beat_idx = int(sum(1 for b in beat_times if b < groove_start))

    # Compile drop anticipation intervals
    drop_windows = []
    for d in drops:
        d_sec = float(d.get("drop_sec", 0.0))
        ant_st = float(d.get("anticipation_start_sec", max(0.0, d_sec - 4.0)))
        vac_st = float(d.get("vacuum_start_sec", max(0.0, d_sec - 1.0)))
        drop_windows.append({
            "ant_st": ant_st,
            "vac_st": vac_st,
            "drop_sec": d_sec,
            "burst_end": min(duration, d_sec + 3.5),
        })

    curr_b = start_beat_idx
    block_num = 0

    while curr_b < total_beats:
        block_st_time = float(beat_times[curr_b])
        end_b = min(curr_b + 16, total_beats - 1)
        block_et_time = float(beat_times[end_b]) if end_b < total_beats else duration

        if block_et_time <= block_st_time:
            break

        # Check if drop occurs in this 4-bar block
        drop_in_block = next(
            (dw for dw in drop_windows if dw["ant_st"] < block_et_time and dw["burst_end"] > block_st_time),
            None
        )

        if drop_in_block:
            # Leading block segment before drop anticipation
            if drop_in_block["ant_st"] > block_st_time + 0.3:
                body_moves.append({
                    "id": f"bm_{uuid.uuid4().hex[:6]}",
                    "name": "Intro Stage Presence" if block_num == 0 else "Pre-Riser Groove",
                    "pose_name": "stand",
                    "start_sec": round(block_st_time, 2),
                    "end_sec": round(drop_in_block["ant_st"], 2),
                    "transition_sec": 0.5,
                })
            # 1. Riser Buildup
            if drop_in_block["ant_st"] < drop_in_block["vac_st"]:
                body_moves.append({
                    "id": f"bm_{uuid.uuid4().hex[:6]}",
                    "name": "Snare Riser Energy Lift",
                    "pose_name": "tiptoe",
                    "start_sec": round(drop_in_block["ant_st"], 2),
                    "end_sec": round(drop_in_block["vac_st"], 2),
                    "transition_sec": 0.5,
                })
            # 2. Pre-Drop Suspense Hold
            body_moves.append({
                "id": f"bm_{uuid.uuid4().hex[:6]}",
                "name": "Pre-Drop Suspense Hold",
                "pose_name": "stand",
                "start_sec": round(drop_in_block["vac_st"], 2),
                "end_sec": round(drop_in_block["drop_sec"], 2),
                "transition_sec": 0.2,
            })
            # 3. Bass Drop Impact
            body_moves.append({
                "id": f"bm_{uuid.uuid4().hex[:6]}",
                "name": "Bass Drop Energy Release",
                "pose_name": "tiptoe",
                "start_sec": round(drop_in_block["drop_sec"], 2),
                "end_sec": round(drop_in_block["burst_end"], 2),
                "transition_sec": 0.15,
            })
            # S7 Drop Center
            s7_moves.append({
                "id": f"s7_{uuid.uuid4().hex[:6]}",
                "name": "Center Drop Anchor",
                "start_sec": round(drop_in_block["ant_st"], 2),
                "end_sec": round(drop_in_block["burst_end"], 2),
                "target_deg": 0.0,
                "transition_sec": 0.3,
            })
            # S8 Gantry Explosive Glide (Clamped to safe 85% / 15% travel bounds)
            s8_moves.append({
                "id": f"s8_{uuid.uuid4().hex[:6]}",
                "name": "Bass Drop Rail Sweep",
                "start_sec": round(drop_in_block["drop_sec"], 2),
                "end_sec": round(drop_in_block["burst_end"] + 1.0, 2),
                "target_pos": calc_s8_rail_pos(0.85 if (block_num % 2 == 0) else 0.15),
                "speed": 650,
            })
            vocal_moves.append({
                "id": f"voc_{uuid.uuid4().hex[:6]}",
                "name": "Drop Power Burst",
                "style": "belting",
                "start_sec": round(drop_in_block["drop_sec"], 2),
                "end_sec": round(drop_in_block["burst_end"], 2),
            })

            # Advance past drop burst
            curr_b = int(sum(1 for b in beat_times if b < (drop_in_block["burst_end"] + 0.2)))
            block_num += 1
            continue

        # Standard 4-Bar Block Patterns
        pattern = block_num % 4
        if pattern == 0:
            # Center Stage Neutral
            body_moves.append({
                "id": f"bm_{uuid.uuid4().hex[:6]}",
                "name": f"Center Stage Groove (Block {block_num + 1})",
                "pose_name": "stand",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "transition_sec": 0.5,
            })
            s7_moves.append({
                "id": f"s7_{uuid.uuid4().hex[:6]}",
                "name": "Center Neutral",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "target_deg": 0.0,
                "transition_sec": 0.4,
            })
            vocal_moves.append({
                "id": f"voc_{uuid.uuid4().hex[:6]}",
                "name": f"Verse Groove {block_num + 1}",
                "style": "conversational",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
            })
            if block_num % 2 == 0:
                s8_moves.append({
                    "id": f"s8_{uuid.uuid4().hex[:6]}",
                    "name": "Stage Center Alignment",
                    "start_sec": round(block_st_time, 2),
                    "end_sec": round(block_st_time + 4.0, 2),
                    "target_pos": calc_s8_rail_pos(0.50),
                    "speed": 280,
                })

        elif pattern == 1:
            # Stage Left Gaze Shift (+25 deg)
            body_moves.append({
                "id": f"bm_{uuid.uuid4().hex[:6]}",
                "name": f"Stage Left Focus (Block {block_num + 1})",
                "pose_name": "stand",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "transition_sec": 0.5,
            })
            s7_moves.append({
                "id": f"s7_{uuid.uuid4().hex[:6]}",
                "name": "Stage Left Facing (+25°)",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "target_deg": 25.0,
                "transition_sec": 0.5,
            })
            s8_moves.append({
                "id": f"s8_{uuid.uuid4().hex[:6]}",
                "name": "Stage Left Rail Drift",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "target_pos": calc_s8_rail_pos(0.70),
                "speed": 220,
            })
            vocal_moves.append({
                "id": f"voc_{uuid.uuid4().hex[:6]}",
                "name": f"Stage Shift Vocal {block_num + 1}",
                "style": "conversational",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
            })

        elif pattern == 2:
            # High Energy Upright Tiptoe
            body_moves.append({
                "id": f"bm_{uuid.uuid4().hex[:6]}",
                "name": f"High Energy Lift (Block {block_num + 1})",
                "pose_name": "tiptoe",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "transition_sec": 0.6,
            })
            s7_moves.append({
                "id": f"s7_{uuid.uuid4().hex[:6]}",
                "name": "High Energy Center",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "target_deg": 0.0,
                "transition_sec": 0.4,
            })
            s8_moves.append({
                "id": f"s8_{uuid.uuid4().hex[:6]}",
                "name": "Center Rail Hold",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "target_pos": calc_s8_rail_pos(0.50),
                "speed": 280,
            })
            vocal_moves.append({
                "id": f"voc_{uuid.uuid4().hex[:6]}",
                "name": f"High Energy Section {block_num + 1}",
                "style": "belting",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
            })

        else:
            # Stage Right Gaze Shift (-25 deg)
            body_moves.append({
                "id": f"bm_{uuid.uuid4().hex[:6]}",
                "name": f"Stage Right Focus (Block {block_num + 1})",
                "pose_name": "stand",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "transition_sec": 0.5,
            })
            s7_moves.append({
                "id": f"s7_{uuid.uuid4().hex[:6]}",
                "name": "Stage Right Facing (-25°)",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "target_deg": -25.0,
                "transition_sec": 0.5,
            })
            s8_moves.append({
                "id": f"s8_{uuid.uuid4().hex[:6]}",
                "name": "Stage Right Rail Drift",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
                "target_pos": calc_s8_rail_pos(0.30),
                "speed": 220,
            })
            vocal_moves.append({
                "id": f"voc_{uuid.uuid4().hex[:6]}",
                "name": f"Stage Right Vocal {block_num + 1}",
                "style": "conversational",
                "start_sec": round(block_st_time, 2),
                "end_sec": round(block_et_time, 2),
            })

        curr_b = end_b
        block_num += 1

    # 5. Head and Jaw Track
    head_jaw_moves = [
        {
            "id": f"hj_{uuid.uuid4().hex[:6]}",
            "name": "Full Performance Vocal & Head Agility",
            "start_sec": 0.0,
            "end_sec": round(duration, 2),
            "nod_enabled": True,
            "jaw_mode": "singing",
        }
    ]

    return {
        "version": "2.0.0",
        "duration": round(duration, 2),
        "settings": dict(DEFAULT_SETTINGS),
        "poses": choreo_poses,
        "sections": sec_blocks,
        "tracks": {
            "body_pose": body_moves,
            "s7_pedestal": s7_moves,
            "s8_gantry": s8_moves,
            "head_jaw": head_jaw_moves,
            "vocal_style": vocal_moves,
        },
    }


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
        """Loads choreography from manifest or auto-compiles from 4-bar blocks if not yet generated."""
        manifest = self._load_manifest()
        track_meta = manifest.get(track_id)
        if not track_meta:
            raise FileNotFoundError(f"Track '{track_id}' not found in Beat Bandit manifest.")

        choreo = track_meta.get("choreography")
        analysis = track_meta.get("analysis", {})
        duration = float(track_meta.get("duration", 0.0) or analysis.get("duration", 0.0))
        if duration <= 0.0:
            raise ValueError(f"Invalid duration '{duration}' for track '{track_id}'.")

        if not choreo or not choreo.get("tracks"):
            self.logger.info(f"Auto-compiling 4-bar block choreography for '{track_meta.get('title')}' ({track_id})...")
            choreo = compile_default_choreography(analysis, duration)
            track_meta["choreography"] = choreo
            manifest[track_id] = track_meta
            self._save_manifest(manifest)

        # Merge in beat grid metadata for UI ruler
        choreo["track_id"] = track_id
        choreo["title"] = track_meta.get("title", track_id)
        choreo["artist"] = track_meta.get("artist", "Unknown Artist")
        choreo["tempo"] = float(track_meta.get("bpm") or track_meta.get("tempo") or analysis.get("bpm") or analysis.get("tempo", 0.0))
        if choreo["tempo"] <= 0.0:
            raise ValueError(f"Invalid tempo for track '{track_id}'.")
        choreo["beat_times"] = analysis.get("beat_times", [])

        return choreo

    def save_track_choreography(self, track_id: str, choreo_data: Dict[str, Any]) -> Dict[str, Any]:
        """Persists edited choreography back into manifest.json."""
        manifest = self._load_manifest()
        if track_id not in manifest:
            raise FileNotFoundError(f"Track '{track_id}' not found in manifest.")

        track_meta = manifest[track_id]
        poses = choreo_data.get("poses") or load_dance_presets()

        clean_choreo = {
            "version": choreo_data.get("version", "2.0.0"),
            "duration": float(choreo_data.get("duration", track_meta.get("duration", 0.0))),
            "settings": choreo_data.get("settings", DEFAULT_SETTINGS),
            "poses": poses,
            "sections": choreo_data.get("sections", []),
            "tracks": choreo_data.get("tracks", {
                "body_pose": [],
                "s7_pedestal": [],
                "s8_gantry": [],
                "head_jaw": [],
                "vocal_style": [],
            }),
            "updated_at": time.time(),
        }
        track_meta["choreography"] = clean_choreo
        manifest[track_id] = track_meta
        self._save_manifest(manifest)
        self.logger.info(f"Successfully saved 4-bar choreography for '{track_meta.get('title')}' ({track_id}).")
        return {"status": "ok", "track_id": track_id, "updated_at": clean_choreo["updated_at"]}

    def auto_generate_choreography(self, track_id: str, style: str = "balanced") -> Dict[str, Any]:
        """Re-compiles choreography from analysis with selected style."""
        manifest = self._load_manifest()
        track_meta = manifest.get(track_id)
        if not track_meta:
            raise FileNotFoundError(f"Track '{track_id}' not found.")

        analysis = track_meta.get("analysis", {})
        duration = float(track_meta.get("duration", 0.0) or analysis.get("duration", 0.0))
        choreo = compile_default_choreography(analysis, duration)

        track_meta["choreography"] = choreo
        manifest[track_id] = track_meta
        self._save_manifest(manifest)
        return choreo

    def preview_pose_on_robot(self, backend: Any, pose_dict: Dict[str, float]) -> Dict[str, Any]:
        """Smoothly drives follower arm to target normalized pose over 1.0 second for physical verification."""
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

        backend.set_arm_torque(True)
        backend.interpolate_arm_norm(clean_goals, duration=1.0, steps=30)
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
        from robot_backend import SERIAL_LOCK, degrees_to_ticks_s7

        if channel == "s7_pedestal":
            deg = float(target_val)
            aux_calib = getattr(backend, "aux_calibration", {})
            if "7" not in aux_calib or "center_ticks" not in aux_calib["7"]:
                raise RuntimeError("Servo 7 calibration missing in calibration_aux.json.")
            aux_s7_center = aux_calib["7"]["center_ticks"]
            s7_ticks = degrees_to_ticks_s7(deg, center_ticks=aux_s7_center)
            with SERIAL_LOCK:
                if hasattr(backend, "ctrl") and backend.ctrl:
                    backend.ctrl.set_torque(7, True, max_torque_enable=800)
                    backend.ctrl.write_goal_raw(7, s7_ticks, speed=1000)
            return {"status": "ok", "channel": channel, "target_deg": deg, "ticks": s7_ticks}

        elif channel == "s8_gantry":
            ticks = int(target_val)
            backend.move_target(8, ticks, speed=600, max_t=800)
            return {"status": "ok", "channel": channel, "target_pos": ticks}

        elif channel == "body_pose":
            if isinstance(target_val, dict):
                return self.preview_pose_on_robot(backend, target_val)

        return {"status": "error", "message": f"Unsupported channel '{channel}'"}


_GLOBAL_STUDIO_MANAGER: Optional[BeatStudioManager] = None


def get_global_studio_manager() -> BeatStudioManager:
    global _GLOBAL_STUDIO_MANAGER
    if _GLOBAL_STUDIO_MANAGER is None:
        if os.name == "nt":
            lib_dir = Path(__file__).resolve().parent.parent / "library" / "beat_bandit"
        else:
            lib_dir = Path.home() / "so101/beat_bandit/library"
        lib_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = lib_dir / "manifest.json"
        _GLOBAL_STUDIO_MANAGER = BeatStudioManager(lib_dir, manifest_file)
    return _GLOBAL_STUDIO_MANAGER
