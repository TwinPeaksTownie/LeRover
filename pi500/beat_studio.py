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


def partition_timeline_into_blocks(analysis: Dict[str, Any], duration: float) -> List[Dict[str, Any]]:
    """Partitions the song into continuous discrete blocks spanning vocal segments
    and instrumental gaps (subdividing long instrumental gaps into chunks of >= 8 beats).
    """
    beat_times = [float(b) for b in analysis.get("beat_times", [])]
    raw_lyrics = analysis.get("lyrics", [])

    # Sort lyrics chronologically
    sorted_lyrics = []
    for l_idx, seg in enumerate(raw_lyrics):
        if not isinstance(seg, dict) or "start_sec" not in seg or "end_sec" not in seg:
            continue
        st = max(0.0, float(seg["start_sec"]))
        et = min(duration, float(seg["end_sec"]))
        if et > st:
            sorted_lyrics.append({
                "id": str(seg.get("id", f"ly_{l_idx + 1:03d}")),
                "name": str(seg.get("name", seg.get("text", f"Lyric {l_idx + 1}"))),
                "text": str(seg.get("text", "")),
                "original_asr_text": str(seg.get("original_asr_text", seg.get("text", ""))),
                "type": str(seg.get("type", "lyric")),
                "is_user_edited": bool(seg.get("is_user_edited", False)),
                "start_sec": round(st, 2),
                "end_sec": round(et, 2),
                "duration": round(et - st, 2),
                "is_vocal": True,
            })
    sorted_lyrics.sort(key=lambda x: x["start_sec"])

    def sub_chunk_instrumental(gap_st: float, gap_et: float, base_name: str) -> List[Dict[str, Any]]:
        gap_dur = gap_et - gap_st
        if gap_dur <= 0.05:
            return []

        # Find beats strictly inside this gap
        beats_in_gap = [b for b in beat_times if gap_st <= b < gap_et]
        chunks = []

        if len(beats_in_gap) >= 16:
            # Subdivide into 8-beat or 16-beat chunks
            chunk_step = 8
            for c_i in range(0, len(beats_in_gap), chunk_step):
                c_st = gap_st if c_i == 0 else beats_in_gap[c_i]
                c_nxt = c_i + chunk_step
                c_et = gap_et if c_nxt >= len(beats_in_gap) else beats_in_gap[c_nxt]
                if c_et - c_st >= 0.2:
                    chunks.append({
                        "id": f"inst_{uuid.uuid4().hex[:6]}",
                        "name": f"{base_name} Part {len(chunks) + 1}",
                        "text": "",
                        "type": "instrumental",
                        "is_user_edited": False,
                        "start_sec": round(c_st, 2),
                        "end_sec": round(c_et, 2),
                        "duration": round(c_et - c_st, 2),
                        "is_vocal": False,
                    })
        else:
            chunks.append({
                "id": f"inst_{uuid.uuid4().hex[:6]}",
                "name": base_name,
                "text": "",
                "type": "instrumental",
                "is_user_edited": False,
                "start_sec": round(gap_st, 2),
                "end_sec": round(gap_et, 2),
                "duration": round(gap_dur, 2),
                "is_vocal": False,
            })
        return chunks

    master_blocks = []
    curr_time = 0.0

    if not sorted_lyrics:
        # Pure instrumental song: partition entire duration into 8/16-beat blocks
        master_blocks = sub_chunk_instrumental(0.0, duration, "Instrumental Block")
    else:
        for seg in sorted_lyrics:
            seg_st = float(seg["start_sec"])
            seg_et = float(seg["end_sec"])

            if seg_st > curr_time + 0.2:
                # Instrumental gap before this lyric
                gap_name = "Intro" if curr_time == 0.0 else "Instrumental Break"
                gap_chunks = sub_chunk_instrumental(curr_time, seg_st, gap_name)
                master_blocks.extend(gap_chunks)

            master_blocks.append(seg)
            curr_time = max(curr_time, seg_et)

        if curr_time < duration - 0.2:
            outro_chunks = sub_chunk_instrumental(curr_time, duration, "Outro")
            master_blocks.extend(outro_chunks)

    # Clean monotonic sequence
    cleaned_blocks = []
    for idx, b in enumerate(master_blocks):
        b["block_index"] = idx
        cleaned_blocks.append(b)
    return cleaned_blocks


def compile_default_choreography(analysis: Dict[str, Any], duration: float) -> Dict[str, Any]:
    """Compiles audio analysis into a structured bottom-up decision tree choreography timeline."""
    if not analysis:
        raise ValueError("Cannot compile choreography: audio 'analysis' payload is empty or missing.")

    duration = float(duration or analysis.get("duration", 0.0))
    if duration <= 0.0:
        raise ValueError(f"Invalid duration '{duration}' for choreography compilation.")

    beat_times = analysis.get("beat_times", [])
    if not beat_times:
        raise ValueError("Cannot compile choreography: 'beat_times' missing or empty in audio analysis.")

    danceability = float(analysis.get("danceability", 0.5))
    tempo = float(analysis.get("bpm") or analysis.get("tempo", 120.0))
    raw_sections = analysis.get("sections", [])
    drops = analysis.get("drops", [])
    held_notes = analysis.get("held_notes", [])
    drop_times = [float(d.get("drop_sec", 0.0)) for d in drops]

    choreo_poses = load_dance_presets()

    # Partition timeline into continuous blocks
    timeline_blocks = partition_timeline_into_blocks(analysis, duration)

    sec_blocks = []
    for idx, s in enumerate(raw_sections):
        st = float(s["start_sec"])
        et = min(duration, float(s["end_sec"]))
        stype = str(s.get("type", "section")).lower()
        sec_blocks.append({
            "id": f"sec_{idx + 1}",
            "name": stype.title(),
            "type": stype,
            "start_sec": round(st, 2),
            "end_sec": round(et, 2),
            "energy_score": float(s.get("energy_score", 0.5)),
        })

    # Continuous state tracking across blocks
    prev_state = {
        "gantry_moving": False,
        "gantry_pos": calc_s8_rail_pos(0.50),
        "spine_pose": "stand",
        "pedestal_deg": 0.0,
    }

    # Timeline Tracks
    lyrics_moves = []
    spine_moves = []
    s8_moves = []
    s7_moves = []
    s1_moves = []
    s5_moves = []
    jaw_moves = []
    compiled_master_blocks = []

    import random
    rng = random.Random(42)  # Deterministic seed for reproducible compilation

    for blk in timeline_blocks:
        b_st = float(blk["start_sec"])
        b_et = float(blk["end_sec"])
        b_dur = b_et - b_st
        is_vocal = bool(blk.get("is_vocal", False))
        blk_id = blk["id"]
        blk_name = blk["name"]

        # Check section energy
        sec = next((s for s in sec_blocks if s["start_sec"] <= b_st < s["end_sec"]), None)
        sec_type = sec["type"] if sec else "verse"
        sec_energy = float(sec["energy_score"]) if sec else 0.5

        # Check drop in this block
        is_drop_hit = any(b_st <= d_t <= b_et for d_t in drop_times)
        drop_t_hit = next((d_t for d_t in drop_times if b_st <= d_t <= b_et), b_st)

        # ----------------------------------------------------
        # 1. Track 8: Gantry Rail (S8) Decision Tree
        # ----------------------------------------------------
        if is_drop_hit:
            if prev_state["gantry_moving"]:
                g_mode = "glide_to_drop_hold"
                target_pct = 0.80 if prev_state["gantry_pos"] < calc_s8_rail_pos(0.50) else 0.20
                g_target = calc_s8_rail_pos(target_pct)
                g_spd = 600
                prev_state["gantry_moving"] = False
                prev_state["gantry_pos"] = g_target
            else:
                g_mode = "hold_to_drop_glide"
                target_pct = 0.85 if prev_state["gantry_pos"] < calc_s8_rail_pos(0.50) else 0.15
                g_target = calc_s8_rail_pos(target_pct)
                g_spd = 700
                prev_state["gantry_moving"] = True
                prev_state["gantry_pos"] = g_target
        else:
            # 65% move probability scaled by section energy
            move_prob = 0.45 + (0.35 * sec_energy)
            if rng.random() < move_prob:
                sub_r = rng.random()
                if sub_r < 0.40:
                    g_mode = "full_glide"
                    prev_state["gantry_moving"] = True
                elif sub_r < 0.70:
                    g_mode = "early_step"
                    prev_state["gantry_moving"] = False
                else:
                    g_mode = "late_step"
                    prev_state["gantry_moving"] = True

                # Alternate sides
                if prev_state["gantry_pos"] <= calc_s8_rail_pos(0.50):
                    target_pct = rng.uniform(0.60, 0.85)
                else:
                    target_pct = rng.uniform(0.15, 0.40)
                g_target = calc_s8_rail_pos(target_pct)
                g_spd = int(350 + 300 * sec_energy)
                prev_state["gantry_pos"] = g_target
            else:
                g_mode = "hold"
                g_target = prev_state["gantry_pos"]
                g_spd = 250
                prev_state["gantry_moving"] = False

        s8_moves.append({
            "id": f"s8_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Rail {g_mode.replace('_', ' ').title()}",
            "mode": g_mode,
            "start_sec": b_st,
            "end_sec": b_et,
            "target_pos": g_target,
            "speed": g_spd,
            "drop_sec": drop_t_hit if is_drop_hit else None,
        })

        # ----------------------------------------------------
        # 2. Track 6: Singing Jaw (S6)
        # ----------------------------------------------------
        if is_vocal:
            # +90% singing lip-sync tracking 50 Hz neural envelope
            jaw_mode = "singing" if rng.random() < 0.95 else "nod"
        else:
            jaw_mode = "closed"

        jaw_moves.append({
            "id": f"jw_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Jaw ({jaw_mode.title()})",
            "start_sec": b_st,
            "end_sec": b_et,
            "jaw_mode": jaw_mode,
        })

        # ----------------------------------------------------
        # 3. Tracks 2-4: Spine Elevation Group (S2, S3, S4)
        # ----------------------------------------------------
        start_pose = prev_state["spine_pose"]
        available_poses = ["squat", "tiptoe", "arch"]

        if start_pose == "stand":
            spine_r = rng.random()
            if spine_r < 0.40:
                spine_pattern = "hold_stand"
                mid_pose = "stand"
                end_pose = "stand"
                trans_sec = 0.5
            elif spine_r < 0.75:
                spine_pattern = "stand_dip_stand"
                mid_pose = rng.choice(available_poses)
                end_pose = "stand"
                trans_sec = 0.4
            else:
                spine_pattern = "stand_to_pose"
                mid_pose = rng.choice(available_poses)
                end_pose = mid_pose
                trans_sec = 0.5
        else:
            spine_r = rng.random()
            if spine_r < 0.40:
                spine_pattern = "return_stand_early"
                mid_pose = "stand"
                end_pose = "stand"
                trans_sec = 0.35
            elif spine_r < 0.75:
                spine_pattern = "return_stand_mid"
                mid_pose = start_pose
                end_pose = "stand"
                trans_sec = 0.5
            else:
                spine_pattern = "return_stand_late"
                mid_pose = start_pose
                end_pose = "stand"
                trans_sec = 0.6

        prev_state["spine_pose"] = end_pose

        spine_moves.append({
            "id": f"sp_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Spine {spine_pattern.replace('_', ' ').title()}",
            "start_pose": start_pose,
            "mid_pose": mid_pose,
            "end_pose": end_pose,
            "pose_name": end_pose,
            "pattern": spine_pattern,
            "start_sec": b_st,
            "end_sec": b_et,
            "transition_sec": trans_sec,
        })

        # ----------------------------------------------------
        # 4. Track 7: Pedestal (S7) Decision Tree
        # ----------------------------------------------------
        prev_deg = prev_state["pedestal_deg"]
        # 50% hold stationary
        if rng.random() < 0.50:
            p_mode = "hold"
            target_deg = prev_deg
            step_deg = 0.0
            p_trans = 0.5
        else:
            if tempo < 110.0:  # Slower BPM allows midpoint back-and-forth pulse
                p_choice = rng.random()
                if p_choice < 0.35:
                    p_mode = "snap_45"
                    target_deg = float(rng.choice([-45.0, 45.0, 0.0]))
                    step_deg = 0.0
                    p_trans = 0.30
                elif p_choice < 0.70:
                    p_mode = "midpoint_pulse"
                    target_deg = prev_deg
                    step_deg = float(rng.choice([-25.0, 25.0]))
                    p_trans = 0.10  # instantaneous write
                else:
                    p_mode = "sweep_180"
                    target_deg = float(rng.choice([-135.0, 135.0, 0.0]))
                    step_deg = 0.0
                    p_trans = b_dur
            else:
                p_choice = rng.random()
                if p_choice < 0.60:
                    p_mode = "snap_45"
                    target_deg = float(rng.choice([-45.0, 45.0, 0.0]))
                    step_deg = 0.0
                    p_trans = 0.30
                else:
                    p_mode = "sweep_180"
                    target_deg = float(rng.choice([-135.0, 135.0, 0.0]))
                    step_deg = 0.0
                    p_trans = b_dur

        prev_state["pedestal_deg"] = target_deg

        s7_moves.append({
            "id": f"s7_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Pedestal ({p_mode.replace('_', ' ').title()})",
            "mode": p_mode,
            "start_sec": b_st,
            "end_sec": b_et,
            "target_deg": target_deg,
            "step_deg": step_deg,
            "transition_sec": p_trans,
        })

        # ----------------------------------------------------
        # 5. Track 1: Hips / Torso Pan (S1)
        # ----------------------------------------------------
        # 80% audience counter-rotation against S7, 20% base aligned
        facing_mode = "audience_counter" if rng.random() < 0.80 else "base_aligned"
        s1_moves.append({
            "id": f"s1_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Hips ({facing_mode.replace('_', ' ').title()})",
            "facing_mode": facing_mode,
            "start_sec": b_st,
            "end_sec": b_et,
        })

        # ----------------------------------------------------
        # 6. Track 5: Neck Pitch (S5) & Wrist Roll
        # ----------------------------------------------------
        neck_r = rng.random()
        has_held_note = any(h["start_sec"] <= b_st < h["end_sec"] for h in held_notes)
        if has_held_note or neck_r < 0.15:
            gaze = "up"
            tilt_deg = 15.0
        elif neck_r < 0.20:
            gaze = "down"
            tilt_deg = -12.0
        else:
            gaze = "level"
            tilt_deg = 0.0

        s5_moves.append({
            "id": f"s5_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Gaze ({gaze.title()})",
            "gaze": gaze,
            "tilt_deg": tilt_deg,
            "start_sec": b_st,
            "end_sec": b_et,
        })

        # Wrist roll
        wrist_r = rng.random()
        if wrist_r < 0.50:
            wrist_mode = "stationary"
        elif wrist_r < 0.80:
            wrist_mode = "sharp_cock"
        else:
            wrist_mode = "oscillate_2x"

        # ----------------------------------------------------
        # 7. Bounce Modifier (Strictly 1 accent per block)
        # ----------------------------------------------------
        bounce_target = rng.choice(["hip_sway", "body_bounce", "head_bob"])
        bounce_mod = {
            "enabled": True,
            "intensity": 0.12,
            "target": bounce_target,
        }

        # Master block metadata for UI inspector & overrides
        compiled_block = {
            "id": blk_id,
            "name": blk_name,
            "start_sec": b_st,
            "end_sec": b_et,
            "duration": b_dur,
            "is_vocal": is_vocal,
            "user_override": bool(blk.get("user_override", False)),
            "bounce_modifier": bounce_mod,
            "gantry_mode": g_mode,
            "gantry_target": g_target,
            "spine_pattern": spine_pattern,
            "spine_pose": end_pose,
            "pedestal_mode": p_mode,
            "pedestal_deg": target_deg,
            "facing_mode": facing_mode,
            "gaze": gaze,
            "wrist_mode": wrist_mode,
            "jaw_mode": jaw_mode,
        }
        compiled_master_blocks.append(compiled_block)

        if is_vocal:
            lyrics_moves.append(blk)

    return {
        "version": "3.1.0",
        "duration": round(duration, 2),
        "danceability": danceability,
        "tempo": tempo,
        "settings": dict(DEFAULT_SETTINGS),
        "poses": choreo_poses,
        "sections": sec_blocks,
        "blocks": compiled_master_blocks,
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

        if not choreo or not choreo.get("tracks") or choreo.get("version") != "3.1.0":
            self.logger.info(f"Auto-compiling bottom-up decision tree choreography for '{track_meta.get('title')}' ({track_id})...")
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
