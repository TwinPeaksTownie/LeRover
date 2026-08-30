#!/usr/bin/env python3
"""Choreography Compiler Module for Beat Bandit SO-101.
Strict Single Responsibility Principle (SRP):
Encapsulates pure decision-tree compilation, musical partitioning,
and 0-100% Range of Motion (ROM) kinematics synthesis from audio analysis.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("so101.choreography_compiler")

# -----------------------------------------------------------------------------
# 0-100% ROM Standard Pose Definitions (Spine & Pitch)
# -----------------------------------------------------------------------------
# All joints normalized strictly to 0.0 - 100.0% ROM
# Motor 1: 50% = Center Pan
# Motor 2: 4% = Min Squat Hardstop, 26% = Stand, 100% = Full Extension
# Motor 3: 19% = Tiptoe, 46% = Stand, 69% = Squat
# Motor 4: 50% = Lifted Up, 70% = Audience Gaze (Level), 85% = Pointed Down
# Motor 5: 35% = Left, 50% = Center, 65% = Right
# Motor 6: 0% = Closed, 45% = Max Singing Aperture
# -----------------------------------------------------------------------------

ROM_POSES: Dict[str, Dict[str, float]] = {
    "stand": {
        "shoulder_pan": 50.0,
        "shoulder_lift": 26.0,
        "elbow_flex": 46.0,
        "wrist_flex": 70.0,
        "wrist_roll": 50.0,
        "gripper": 0.0,
    },
    "squat": {
        "shoulder_pan": 50.0,
        "shoulder_lift": 4.0,
        "elbow_flex": 69.0,
        "wrist_flex": 70.0,
        "wrist_roll": 50.0,
        "gripper": 0.0,
    },
    "tiptoe": {
        "shoulder_pan": 50.0,
        "shoulder_lift": 43.0,
        "elbow_flex": 19.0,
        "wrist_flex": 70.0,
        "wrist_roll": 50.0,
        "gripper": 0.0,
    },
    "arch": {
        "shoulder_pan": 50.0,
        "shoulder_lift": 10.0,
        "elbow_flex": 20.0,
        "wrist_flex": 50.0,
        "wrist_roll": 50.0,
        "gripper": 0.0,
    },
}

DEFAULT_CHOREO_SETTINGS: Dict[str, Any] = {
    "jaw_gate_threshold": 0.18,
    "jaw_max_open_rom": 45.0,
    "head_nod_depth_rom": 6.0,
    "vibrato_amplitude": 20.0,
    "groove_max_sway_rom": 15.0,
    "head_tilt_max_rom": 15.0,
    "gantry_default_speed": 800,
}


def partition_timeline_into_blocks(analysis: Dict[str, Any], duration: float) -> List[Dict[str, Any]]:
    """Partitions the song into continuous discrete blocks spanning vocal segments
    and instrumental gaps (subdividing long instrumental gaps into chunks of >= 8 beats).
    """
    beat_times = [float(b) for b in analysis.get("beat_times", [])]
    raw_lyrics = analysis.get("lyrics", [])

    sorted_lyrics = []
    for l_idx, seg in enumerate(raw_lyrics):
        if not isinstance(seg, dict) or "start_sec" not in seg or "end_sec" not in seg:
            continue
        st = max(0.0, float(seg["start_sec"]))
        et = min(duration, float(seg["end_sec"]))
        if et > st:
            sorted_lyrics.append({
                "id": str(seg.get("id", f"ly_{l_idx + 1:03d}")),
                "name": str(seg.get("name", seg.get("text", f"Line {l_idx + 1}"))),
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

    def sub_chunk_instrumental(gap_start: float, gap_end: float, base_name: str) -> List[Dict[str, Any]]:
        gap_dur = gap_end - gap_start
        if gap_dur <= 0.2:
            return []

        beats_in_gap = [b for b in beat_times if gap_start <= b <= gap_end]
        if len(beats_in_gap) <= 12 or gap_dur < 6.0:
            return [{
                "id": f"inst_{abs(hash((gap_start, gap_end))) % 1000000:06x}",
                "name": base_name,
                "text": "",
                "type": "instrumental",
                "is_user_edited": False,
                "start_sec": round(gap_start, 2),
                "end_sec": round(gap_end, 2),
                "duration": round(gap_dur, 2),
                "is_vocal": False,
            }]

        chunks = []
        c_st = gap_start
        idx = 0
        while idx < len(beats_in_gap):
            next_idx = min(len(beats_in_gap) - 1, idx + 8)
            c_et = beats_in_gap[next_idx]
            if (gap_end - c_et) < 3.0:
                c_et = gap_end
                idx = len(beats_in_gap)
            else:
                idx = next_idx

            if c_et > c_st + 0.5:
                chunks.append({
                    "id": f"inst_{abs(hash((c_st, c_et))) % 1000000:06x}",
                    "name": f"{base_name} Pt {len(chunks) + 1}",
                    "text": "",
                    "type": "instrumental",
                    "is_user_edited": False,
                    "start_sec": round(c_st, 2),
                    "end_sec": round(c_et, 2),
                    "duration": round(c_et - c_st, 2),
                    "is_vocal": False,
                })
            c_st = c_et
            if c_st >= gap_end - 0.2:
                break
        return chunks

    master_blocks: List[Dict[str, Any]] = []
    curr_time = 0.0

    if not sorted_lyrics:
        master_blocks = sub_chunk_instrumental(0.0, duration, "Instrumental")
    else:
        for seg in sorted_lyrics:
            seg_st = float(seg["start_sec"])
            seg_et = float(seg["end_sec"])

            if seg_st > curr_time + 0.2:
                gap_name = "Intro" if curr_time == 0.0 else "Instrumental Break"
                gap_chunks = sub_chunk_instrumental(curr_time, seg_st, gap_name)
                master_blocks.extend(gap_chunks)

            master_blocks.append(seg)
            curr_time = max(curr_time, seg_et)

        if curr_time < duration - 0.2:
            outro_chunks = sub_chunk_instrumental(curr_time, duration, "Outro")
            master_blocks.extend(outro_chunks)

    cleaned_blocks = []
    for idx, b in enumerate(master_blocks):
        b["block_index"] = idx
        cleaned_blocks.append(b)
    return cleaned_blocks


def compile_choreography_tracks(analysis: Dict[str, Any], duration: float, seed: int = 42) -> Dict[str, Any]:
    """Compiles audio analysis into discrete 0-100% ROM movement tracks using
    exact user-specified decision trees and probability distributions.
    """
    if not analysis:
        raise ValueError("Cannot compile choreography: audio 'analysis' payload is empty.")

    duration = float(duration or analysis.get("duration", 0.0))
    if duration <= 0.0:
        raise ValueError(f"Invalid duration '{duration}' for choreography compilation.")

    beat_times = analysis.get("beat_times", [])
    if not beat_times:
        raise ValueError("Cannot compile choreography: 'beat_times' missing in audio analysis.")

    tempo = float(analysis.get("bpm") or analysis.get("tempo", 120.0))
    raw_sections = analysis.get("sections", [])
    drops = analysis.get("drops", [])
    held_notes = analysis.get("held_notes", [])
    drop_times = [float(d.get("drop_sec", 0.0)) for d in drops]

    timeline_blocks = partition_timeline_into_blocks(analysis, duration)

    first_vocal_sec = duration
    for b in timeline_blocks:
        if b.get("is_vocal"):
            first_vocal_sec = float(b["start_sec"])
            break

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

    prev_state = {
        "gantry_moving": False,
        "gantry_pos_rom": 50.0,
        "spine_pose": "stand",
        "pedestal_rom": 50.0,
    }

    spine_moves = []
    s8_moves = []
    s7_moves = []
    s1_moves = []
    s5_moves = []
    jaw_moves = []
    compiled_master_blocks = []

    rng = random.Random(seed)

    for blk in timeline_blocks:
        b_st = float(blk["start_sec"])
        b_et = float(blk["end_sec"])
        b_dur = b_et - b_st
        is_vocal = bool(blk.get("is_vocal", False))
        blk_id = blk["id"]
        blk_name = blk["name"]
        is_intro = (b_et <= first_vocal_sec)

        sec = next((s for s in sec_blocks if s["start_sec"] <= b_st < s["end_sec"]), None)
        sec_energy = float(sec["energy_score"]) if sec else 0.5

        is_drop_hit = any(b_st <= d_t <= b_et for d_t in drop_times)
        drop_t_hit = next((d_t for d_t in drop_times if b_st <= d_t <= b_et), b_st)

        # -----------------------------------------------------------------
        # 1. Track 8: Gantry Slider (S8) Decision Tree
        # -----------------------------------------------------------------
        if is_drop_hit:
            if prev_state["gantry_moving"]:
                g_mode = "glide_to_drop_hold"
                target_rom = 80.0 if prev_state["gantry_pos_rom"] < 50.0 else 20.0
                g_spd = 600
                prev_state["gantry_moving"] = False
                prev_state["gantry_pos_rom"] = target_rom
            else:
                g_mode = "hold_to_drop_glide"
                target_rom = 85.0 if prev_state["gantry_pos_rom"] < 50.0 else 15.0
                g_spd = 700
                prev_state["gantry_moving"] = True
                prev_state["gantry_pos_rom"] = target_rom
        else:
            move_prob = 0.65
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

                if prev_state["gantry_pos_rom"] <= 50.0:
                    target_rom = round(rng.uniform(60.0, 85.0), 1)
                else:
                    target_rom = round(rng.uniform(15.0, 40.0), 1)
                g_spd = int(350 + 300 * sec_energy)
                prev_state["gantry_pos_rom"] = target_rom
            else:
                g_mode = "hold"
                target_rom = prev_state["gantry_pos_rom"]
                g_spd = 250
                prev_state["gantry_moving"] = False

        s8_moves.append({
            "id": f"s8_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Rail {g_mode.replace('_', ' ').title()} ({target_rom:.0f}%)",
            "mode": g_mode,
            "start_sec": b_st,
            "end_sec": b_et,
            "target_pos_rom": target_rom,
            "speed": g_spd,
            "drop_sec": drop_t_hit if is_drop_hit else None,
        })

        # -----------------------------------------------------------------
        # 2. Track 6: Singing Jaw (S6) Decision Tree
        # -----------------------------------------------------------------
        if is_vocal:
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
            "max_open_rom": 45.0,
        })

        # -----------------------------------------------------------------
        # 3. Track 4: Neck Pitch (S4) Decision Tree (80% Audience / 15% Up / 5% Down)
        # -----------------------------------------------------------------
        pitch_r = rng.random()
        has_held_note = any(h.get("start_sec", 0.0) <= b_st < h.get("end_sec", 0.0) for h in held_notes)

        if has_held_note or pitch_r < 0.15:
            head_pitch_mode = "up"
            neck_pitch_rom = 50.0   # 50% ROM = Lifted Up (Power Belt)
        elif pitch_r < 0.20:
            head_pitch_mode = "down"
            neck_pitch_rom = 85.0   # 85% ROM = Pointed Down (Introspective)
        else:
            head_pitch_mode = "level"
            neck_pitch_rom = 70.0   # 70% ROM = Audience Gaze (Level eye contact)

        # -----------------------------------------------------------------
        # 4. Tracks 2-3: Spine Elevation Group (S2 Lift & S3 Elbow)
        # -----------------------------------------------------------------
        start_pose = prev_state["spine_pose"]
        available_poses = ["squat", "tiptoe", "arch"]

        if is_intro:
            spine_pattern = "hold_stand"
            mid_pose = "stand"
            end_pose = "stand"
            trans_sec = 0.5
        elif start_pose == "stand":
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
            "head_pitch": head_pitch_mode,
            "neck_pitch_rom": neck_pitch_rom,
            "start_sec": b_st,
            "end_sec": b_et,
            "transition_sec": trans_sec,
        })

        # -----------------------------------------------------------------
        # 5. Track 7: Pedestal Spinner (S7) Decision Tree
        # -----------------------------------------------------------------
        prev_p_rom = prev_state["pedestal_rom"]
        p_r = rng.random()

        if p_r < 0.50:
            p_mode = "hold"
            target_p_rom = prev_p_rom
            step_rom = 0.0
            p_trans = 0.5
        elif p_r < 0.75:
            # 25% Midpoint Pulse (Back and forth +- 10% ROM)
            p_mode = "midpoint_pulse"
            target_p_rom = prev_p_rom
            step_rom = rng.choice([-10.0, 10.0])
            p_trans = 0.10
        elif p_r < 0.90:
            # 15% Snap 45 deg (33% or 67% ROM)
            p_mode = "snap_45"
            target_p_rom = float(rng.choice([33.0, 67.0, 50.0]))
            step_rom = 0.0
            p_trans = 0.30
        else:
            # 10% Sweep 180 deg (0% to 100% ROM)
            p_mode = "sweep_180"
            target_p_rom = float(rng.choice([0.0, 100.0, 50.0]))
            step_rom = 0.0
            p_trans = b_dur

        prev_state["pedestal_rom"] = target_p_rom

        s7_moves.append({
            "id": f"s7_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Pedestal ({p_mode.replace('_', ' ').title()})",
            "mode": p_mode,
            "start_sec": b_st,
            "end_sec": b_et,
            "target_pos_rom": target_p_rom,
            "step_rom": step_rom,
            "transition_sec": p_trans,
        })

        # -----------------------------------------------------------------
        # 6. Track 1: Hips / Torso Pan (S1) Decision Tree
        # -----------------------------------------------------------------
        facing_mode = "audience_counter" if rng.random() < 0.80 else "base_aligned"
        s1_moves.append({
            "id": f"s1_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Hips ({facing_mode.replace('_', ' ').title()})",
            "facing_mode": facing_mode,
            "start_sec": b_st,
            "end_sec": b_et,
        })

        # -----------------------------------------------------------------
        # 7. Track 5: Head Tilt & Wrist Roll (S5) (50% Center / 25% Left / 25% Right)
        # -----------------------------------------------------------------
        tilt_r = rng.random()
        if tilt_r < 0.50:
            tilt_mode = "center"
            tilt_rom = 50.0
        elif tilt_r < 0.75:
            tilt_mode = "rapid_left"
            tilt_rom = 35.0
        else:
            tilt_mode = "rapid_right"
            tilt_rom = 65.0

        s5_moves.append({
            "id": f"s5_{blk_id}",
            "block_id": blk_id,
            "name": f"{blk_name} Tilt ({tilt_mode.replace('_', ' ').title()})",
            "tilt_mode": tilt_mode,
            "tilt_rom": tilt_rom,
            "start_sec": b_st,
            "end_sec": b_et,
        })

        # -----------------------------------------------------------------
        # 8. Master Block Bounce Modifier (Strictly 1 active accent)
        # -----------------------------------------------------------------
        bounce_target = rng.choice(["hip_sway", "body_bounce", "head_bob"])
        blk_with_accent = dict(blk)
        blk_with_accent["bounce_modifier"] = {
            "enabled": True,
            "intensity": 0.12,
            "target": bounce_target,
        }
        compiled_master_blocks.append(blk_with_accent)

    return {
        "title": analysis.get("title", "Compiled Choreography"),
        "duration": duration,
        "bpm": tempo,
        "settings": DEFAULT_CHOREO_SETTINGS,
        "poses": ROM_POSES,
        "sections": sec_blocks,
        "blocks": compiled_master_blocks,
        "tracks": {
            "lyrics": [b for b in timeline_blocks if b.get("is_vocal")],
            "spine_gaze": spine_moves,
            "s8_gantry": s8_moves,
            "s7_pedestal": s7_moves,
            "s1_torso": s1_moves,
            "s5_head_tilt": s5_moves,
            "s6_jaw": jaw_moves,
        },
    }
