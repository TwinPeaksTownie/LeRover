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
    "groove_max_sway_deg": 18.0,
    "head_tilt_max_deg": 15.0,
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
    if not fpath.exists():
        raise FileNotFoundError(f"Mandatory auxiliary calibration file not found at {fpath}")
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
        if "8" in data and "min_ticks" in data["8"] and "max_ticks" in data["8"]:
            return int(data["8"]["min_ticks"]), int(data["8"]["max_ticks"])
    raise KeyError(f"Servo 8 'min_ticks' and 'max_ticks' calibration missing in {fpath}")


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

    for mandatory_pose in ["stand", "squat", "tiptoe", "arch"]:
        if mandatory_pose not in clean_poses:
            raise KeyError(f"Mandatory posture '{mandatory_pose}' missing in {fpath}")
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
    """Compiles Essentia audio analysis (sections, beats, downbeats, drops, held notes, danceability)
    into a structured 6-track measure-by-measure linear choreography timeline.
    """
    if not analysis:
        raise ValueError("Cannot compile choreography: audio 'analysis' payload is empty or missing.")

    duration = float(duration or analysis.get("duration", 0.0))
    if duration <= 0.0:
        raise ValueError(f"Invalid duration '{duration}' for choreography compilation.")

    beat_times = analysis.get("beat_times", [])
    if not beat_times:
        raise ValueError("Cannot compile choreography: 'beat_times' missing or empty in audio analysis.")

    if "danceability" not in analysis:
        raise ValueError("Cannot compile choreography: 'danceability' missing in audio analysis.")
    danceability = float(analysis["danceability"])

    raw_sections = analysis.get("sections", [])
    if not raw_sections:
        raise ValueError("Cannot compile choreography: empirical 'sections' missing in audio analysis.")

    drops = analysis.get("drops", [])
    held_notes = analysis.get("held_notes", [])

    # Load real calibration poses (stand, squat, tiptoe, arch)
    choreo_poses = load_dance_presets()

    sec_blocks = []
    for idx, s in enumerate(raw_sections):
        st = float(s["start_sec"])
        et = min(duration, float(s["end_sec"]))
        stype = str(s["type"]).lower()
        sec_blocks.append({
            "id": f"sec_{idx + 1}",
            "name": stype.title(),
            "type": stype,
            "start_sec": round(st, 2),
            "end_sec": round(et, 2),
            "energy_score": float(s.get("energy_score", 0.0)),
        })

    # Timeline Tracks (The 6 Coordinated Functional Lanes)
    spine_moves = []
    s8_moves = []
    s7_moves = []
    s1_moves = []
    s5_moves = []
    jaw_moves = []

    # Drop intervals
    drop_times = [float(d.get("drop_sec", 0.0)) for d in drops]

    # Partition beats into 4-beat measures
    measure_indices = list(range(0, len(beat_times), 4))
    total_measures = len(measure_indices)

    # Check intro before first beat if any
    first_beat = float(beat_times[0])
    if first_beat > 0.05:
        # Pre-beat intro measure covering from 0.0 to first beat
        spine_moves.append({
            "id": f"sp_{uuid.uuid4().hex[:6]}",
            "name": "Intro Stance",
            "pose_name": "stand",
            "head_pitch": "level",
            "start_sec": 0.0,
            "end_sec": round(first_beat, 2),
            "transition_sec": 0.5,
        })
        s8_moves.append({
            "id": f"s8_{uuid.uuid4().hex[:6]}",
            "name": "Intro Center Hold",
            "mode": "hold",
            "start_sec": 0.0,
            "end_sec": round(first_beat, 2),
            "target_pos": calc_s8_rail_pos(0.50),
            "speed": 200,
        })
        s7_moves.append({
            "id": f"s7_{uuid.uuid4().hex[:6]}",
            "name": "Intro Center Facing",
            "start_sec": 0.0,
            "end_sec": round(first_beat, 2),
            "target_deg": 0.0,
            "transition_sec": 0.5,
        })
        s1_moves.append({
            "id": f"s1_{uuid.uuid4().hex[:6]}",
            "name": "Intro Torso Stillness",
            "start_sec": 0.0,
            "end_sec": round(first_beat, 2),
            "groove_intensity": 0.0,
            "sway_enabled": False,
        })
        s5_moves.append({
            "id": f"s5_{uuid.uuid4().hex[:6]}",
            "name": "Intro Level Head",
            "start_sec": 0.0,
            "end_sec": round(first_beat, 2),
            "tilt_deg": 0.0,
        })

    for m_idx, b_start in enumerate(measure_indices):
        m_st = 0.0 if (m_idx == 0 and first_beat <= 0.05) else float(beat_times[b_start])
        b_end = b_start + 4
        if b_end < len(beat_times):
            m_et = float(beat_times[b_end])
        elif m_idx == total_measures - 1:
            m_et = duration
        else:
            m_et = float(beat_times[-1]) + 2.0

        m_dur = m_et - m_st
        if m_dur <= 0.05:
            continue

        # Find parent section
        sec = next((s for s in sec_blocks if s["start_sec"] <= m_st < s["end_sec"]), None)
        sec_type = sec["type"] if sec else "verse"

        # Check if near drop
        is_drop_hit = any(abs(d_t - m_st) < 2.0 for d_t in drop_times)
        is_pre_drop = any(0.0 < (d_t - m_st) <= 4.0 for d_t in drop_times)

        # Check held notes in this measure
        has_held_note = any(h["start_sec"] <= m_st < h["end_sec"] or m_st <= h["start_sec"] < m_et for h in held_notes)

        # Track 1: Spine & Elevation (S2, S3, S4)
        if is_drop_hit or sec_type == "chorus":
            pose = "tiptoe" if m_idx % 2 == 0 else "arch"
            head_pitch = "up" if has_held_note else "level"
            trans_sec = 0.35
        elif is_pre_drop:
            pose = "squat"
            head_pitch = "down"
            trans_sec = 0.5
        elif sec_type == "intro":
            pose = "stand"
            head_pitch = "level"
            trans_sec = 0.8
        elif sec_type == "bridge":
            pose = "squat" if m_idx % 2 == 0 else "arch"
            head_pitch = "up" if has_held_note else "down"
            trans_sec = 0.6
        elif sec_type == "outro":
            pose = "stand"
            head_pitch = "level"
            trans_sec = 1.0
        else:
            # Verse groove: cycle between stand, squat, and arch
            v_cycle = m_idx % 4
            if v_cycle in [0, 2]:
                pose = "stand"
            elif v_cycle == 1:
                pose = "squat"
            else:
                pose = "arch"
            head_pitch = "up" if has_held_note else "level"
            trans_sec = 0.5

        spine_moves.append({
            "id": f"sp_{uuid.uuid4().hex[:6]}",
            "name": f"M{m_idx + 1} {pose.title()}",
            "pose_name": pose,
            "head_pitch": head_pitch,
            "start_sec": round(m_st, 2),
            "end_sec": round(m_et, 2),
            "transition_sec": trans_sec,
        })

        # Track 2: Gantry Rail (S8)
        if is_drop_hit:
            g_mode = "full_glide"
            g_target = calc_s8_rail_pos(0.85 if m_idx % 2 == 0 else 0.15)
            g_spd = 650
        elif sec_type == "chorus":
            g_mode = "full_glide"
            g_target = calc_s8_rail_pos(0.70 if m_idx % 2 == 0 else 0.30)
            g_spd = 450
        elif sec_type in ["intro", "outro"]:
            g_mode = "hold"
            g_target = calc_s8_rail_pos(0.50)
            g_spd = 200
        else:
            # Verse: alternate late_move, early_settle, hold
            v_gantry_cycle = m_idx % 4
            if v_gantry_cycle == 0:
                g_mode = "hold"
                g_target = calc_s8_rail_pos(0.50)
                g_spd = 250
            elif v_gantry_cycle == 1:
                g_mode = "early_settle"
                g_target = calc_s8_rail_pos(0.65)
                g_spd = 280
            elif v_gantry_cycle == 2:
                g_mode = "hold"
                g_target = calc_s8_rail_pos(0.65)
                g_spd = 250
            else:
                g_mode = "late_move"
                g_target = calc_s8_rail_pos(0.35)
                g_spd = 280

        s8_moves.append({
            "id": f"s8_{uuid.uuid4().hex[:6]}",
            "name": f"M{m_idx + 1} Rail {g_mode.replace('_', ' ').title()}",
            "mode": g_mode,
            "start_sec": round(m_st, 2),
            "end_sec": round(m_et, 2),
            "target_pos": g_target,
            "speed": g_spd,
        })

        # Track 3: Pedestal Facing (S7)
        if is_drop_hit or sec_type in ["chorus", "intro", "outro"]:
            target_deg = 0.0
            p_trans = 0.35 if is_drop_hit else 0.6
        else:
            # Staging angle shifts every 2 measures
            p_cycle = (m_idx // 2) % 3
            if p_cycle == 0:
                target_deg = 0.0
            elif p_cycle == 1:
                target_deg = 25.0
            else:
                target_deg = -25.0
            p_trans = 0.5

        s7_moves.append({
            "id": f"s7_{uuid.uuid4().hex[:6]}",
            "name": f"M{m_idx + 1} Pedestal ({int(target_deg)}°)",
            "start_sec": round(m_st, 2),
            "end_sec": round(m_et, 2),
            "target_deg": target_deg,
            "transition_sec": p_trans,
        })

        # Track 4: Torso Pan & Groove Modifier (S1)
        if sec_type == "chorus" or is_drop_hit:
            groove_val = max(0.75, min(1.0, danceability * 1.2))
        elif sec_type == "verse":
            groove_val = max(0.30, min(0.75, danceability * 0.8))
        elif sec_type == "bridge":
            groove_val = 0.20
        else:
            groove_val = 0.0

        s1_moves.append({
            "id": f"s1_{uuid.uuid4().hex[:6]}",
            "name": f"M{m_idx + 1} Groove {int(groove_val * 100)}%",
            "start_sec": round(m_st, 2),
            "end_sec": round(m_et, 2),
            "groove_intensity": round(groove_val, 2),
            "sway_enabled": groove_val > 0.15,
        })

        # Track 5: Head Tilt (S5)
        if is_drop_hit:
            tilt = 0.0
        elif sec_type == "verse" and m_idx % 2 == 1:
            tilt = 12.0 if (m_idx // 2) % 2 == 0 else -12.0
        else:
            tilt = 0.0

        s5_moves.append({
            "id": f"s5_{uuid.uuid4().hex[:6]}",
            "name": f"M{m_idx + 1} Tilt ({int(tilt)}°)",
            "start_sec": round(m_st, 2),
            "end_sec": round(m_et, 2),
            "tilt_deg": tilt,
        })

    # Track 6: Full-track Singing Jaw
    jaw_moves = [
        {
            "id": f"jw_{uuid.uuid4().hex[:6]}",
            "name": "50 Hz Neural Vocal Lip-Sync",
            "start_sec": 0.0,
            "end_sec": round(duration, 2),
            "jaw_mode": "singing",
        }
    ]

    raw_lyrics = analysis.get("lyrics", [])
    lyrics_moves = [
        {
            "id": seg.get("id", f"ly_{l_idx + 1:03d}"),
            "name": seg.get("text", seg.get("name", "")),
            "text": seg.get("text", seg.get("name", "")),
            "original_asr_text": seg.get("original_asr_text", seg.get("text", seg.get("name", ""))),
            "type": seg.get("type", "lyric"),
            "singer_type": seg.get("singer_type", "female" if seg.get("type") != "breath" else "breath"),
            "is_user_edited": seg.get("is_user_edited", False),
            "start_sec": round(float(seg["start_sec"]), 2),
            "end_sec": round(float(seg["end_sec"]), 2),
            "duration": round(float(seg["end_sec"]) - float(seg["start_sec"]), 2),
            "words": seg.get("words", [])
        }
        for l_idx, seg in enumerate(raw_lyrics)
    ]

    return {
        "version": "3.0.0",
        "duration": round(duration, 2),
        "danceability": danceability,
        "settings": dict(DEFAULT_SETTINGS),
        "poses": choreo_poses,
        "sections": sec_blocks,
        "tracks": {
            "lyrics": lyrics_moves,
            "spine_gaze": spine_moves,
            "s8_gantry": s8_moves,
            "s7_pedestal": s7_moves,
            "s1_torso": s1_moves,
            "s5_head_tilt": s5_moves,
            "s6_jaw": jaw_moves,
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
        choreo["artist"] = track_meta.get("artist", "")
        tempo_val = track_meta.get("bpm") or track_meta.get("tempo") or analysis.get("bpm") or analysis.get("tempo")
        if tempo_val is None:
            raise KeyError(f"Track '{track_id}' missing 'bpm' or 'tempo' in manifest or audio analysis.")
        choreo["tempo"] = float(tempo_val)
        choreo["beat_times"] = analysis.get("beat_times", [])
        choreo["drops"] = analysis.get("drops", [])
        choreo["amplitude_envelope"] = analysis.get("amplitude_envelope", [])
        choreo["mouth_envelope_50hz"] = analysis.get("mouth_envelope_50hz", [])

        return choreo

    def save_track_choreography(self, track_id: str, choreo_data: Dict[str, Any]) -> Dict[str, Any]:
        """Persists edited choreography back into manifest.json."""
        manifest = self._load_manifest()
        if track_id not in manifest:
            raise FileNotFoundError(f"Track '{track_id}' not found in manifest.")

        track_meta = manifest[track_id]
        poses = choreo_data.get("poses") or load_dance_presets()

        clean_choreo = {
            "version": choreo_data.get("version", "3.0.0"),
            "duration": float(choreo_data.get("duration", track_meta.get("duration", 0.0))),
            "settings": choreo_data.get("settings", DEFAULT_SETTINGS),
            "poses": poses,
            "sections": choreo_data.get("sections", []),
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
        self.logger.info(f"Successfully saved measure choreography for '{track_meta.get('title')}' ({track_id}).")
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

        elif channel in ["spine_gaze", "body_pose"]:
            if isinstance(target_val, str):
                poses = load_dance_presets()
                if target_val in poses:
                    return self.preview_pose_on_robot(backend, poses[target_val])
            elif isinstance(target_val, dict):
                return self.preview_pose_on_robot(backend, target_val)

        elif channel == "s1_torso":
            deg = float(target_val)
            norm_pan = float(max(-100.0, min(100.0, deg)))
            return {"status": "ok", "channel": channel, "torso_pan": norm_pan}

        elif channel == "s5_head_tilt":
            deg = float(target_val)
            norm_roll = float(max(-100.0, min(100.0, deg)))
            return {"status": "ok", "channel": channel, "head_tilt": norm_roll}

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
