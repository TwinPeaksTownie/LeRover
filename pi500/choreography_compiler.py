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
# All joints normalized strictly to 0.0 - 100.0% ROM:
# Motor 1: 50% = Center Pan
# Motor 2: 4% = Squat, 26% = Stand, 43% = Tiptoe, 10% = Arch
# Motor 3: 69% = Squat, 46% = Stand, 19% = Tiptoe, 20% = Arch
# Motor 4: 50% = Lifted Up, 70% = Audience Gaze (Level), 85% = Pointed Down
# Motor 5: 35% = Left, 50% = Center, 65% = Right
# Motor 6: 0% = Closed, 45% = Max Singing Aperture
# Motor 7: 25% = Left, 50% = Center, 75% = Right
# Motor 8: 0% = Left rail hardstop, 50% = Center, 100% = Right rail hardstop
# -----------------------------------------------------------------------------

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


def load_dance_presets() -> Dict[str, Dict[str, float]]:
    """Loads empirical 0-100% ROM joint postures strictly from presets_dance.json."""
    fpath = get_dance_presets_path()
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    clean_poses = {}
    for name, pdata in data.items():
        if not isinstance(pdata, dict):
            continue
        if "rom_pct" in pdata:
            clean_poses[name] = {
                k: float(v)
                for k, v in pdata["rom_pct"].items()
                if k in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
            }
        elif "normalized" in pdata:
            clean_poses[name] = {
                k: float(v)
                for k, v in pdata["normalized"].items()
                if k in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
            }

    for mandatory_pose in ["stand", "squat", "tiptoe", "arch"]:
        if mandatory_pose not in clean_poses:
            raise KeyError(f"Mandatory posture '{mandatory_pose}' missing in {fpath}")
    return clean_poses


ROM_POSES = load_dance_presets()

DEFAULT_CHOREO_SETTINGS: Dict[str, Any] = {
    "jaw_gate_threshold": 0.18,
    "jaw_max_open_rom": 45.0,
    "head_nod_depth_rom": 6.0,
    "vibrato_amplitude": 20.0,
    "groove_max_sway_rom": 15.0,
    "head_tilt_max_rom": 15.0,
    "gantry_default_speed": 500,
}


def sec_to_beat_index(sec: float, beat_times: List[float]) -> int:
    """Resolves a continuous second timestamp to the closest discrete musical beat index."""
    if not beat_times:
        return 0
    import bisect
    pos = bisect.bisect_left(beat_times, sec)
    if pos == 0:
        return 0
    if pos >= len(beat_times):
        return len(beat_times) - 1
    before = beat_times[pos - 1]
    after = beat_times[pos]
    if (after - sec) < (sec - before):
        return pos
    return pos - 1


def partition_timeline_into_blocks(analysis: Dict[str, Any], duration: float) -> List[Dict[str, Any]]:
    """Partitions the song into continuous discrete blocks spanning vocal segments
    and instrumental gaps (subdividing long instrumental gaps into musical chunks of >= 8 beats / 2 bars).
    All blocks track both physical timestamps and discrete musical beats/measures.
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
            s_beat = sec_to_beat_index(st, beat_times)
            e_beat = max(s_beat + 1, sec_to_beat_index(et, beat_times))
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
                "start_beat": s_beat,
                "end_beat": e_beat,
                "duration_beats": e_beat - s_beat,
                "measure": s_beat // 4,
                "is_vocal": True,
            })
    sorted_lyrics.sort(key=lambda x: x["start_sec"])

    def sub_chunk_instrumental(gap_start: float, gap_end: float, base_name: str) -> List[Dict[str, Any]]:
        gap_dur = gap_end - gap_start
        if gap_dur <= 0.2:
            return []

        beats_in_gap = [b for b in beat_times if gap_start <= b <= gap_end]
        if len(beats_in_gap) <= 12 or gap_dur < 6.0:
            s_beat = sec_to_beat_index(gap_start, beat_times)
            e_beat = max(s_beat + 1, sec_to_beat_index(gap_end, beat_times))
            return [{
                "id": f"inst_{abs(hash((gap_start, gap_end))) % 1000000:06x}",
                "name": base_name,
                "text": "",
                "type": "instrumental",
                "is_user_edited": False,
                "start_sec": round(gap_start, 2),
                "end_sec": round(gap_end, 2),
                "duration": round(gap_dur, 2),
                "start_beat": s_beat,
                "end_beat": e_beat,
                "duration_beats": e_beat - s_beat,
                "measure": s_beat // 4,
                "is_vocal": False,
            }]

        chunks = []
        c_st = gap_start
        step = 8  # Subdivide instrumental gaps into 8-beat (2-measure) musical phrases
        for i in range(step, len(beats_in_gap), step):
            c_et = beats_in_gap[i]
            if (gap_end - c_et) < 3.0:
                break
            if c_et > c_st + 0.5:
                s_beat = sec_to_beat_index(c_st, beat_times)
                e_beat = max(s_beat + 1, sec_to_beat_index(c_et, beat_times))
                chunks.append({
                    "id": f"inst_{abs(hash((c_st, c_et))) % 1000000:06x}",
                    "name": f"{base_name} Pt {len(chunks) + 1}",
                    "text": "",
                    "type": "instrumental",
                    "is_user_edited": False,
                    "start_sec": round(c_st, 2),
                    "end_sec": round(c_et, 2),
                    "duration": round(c_et - c_st, 2),
                    "start_beat": s_beat,
                    "end_beat": e_beat,
                    "duration_beats": e_beat - s_beat,
                    "measure": s_beat // 4,
                    "is_vocal": False,
                })
                c_st = c_et

        if gap_end > c_st + 0.2:
            s_beat = sec_to_beat_index(c_st, beat_times)
            e_beat = max(s_beat + 1, sec_to_beat_index(gap_end, beat_times))
            chunks.append({
                "id": f"inst_{abs(hash((c_st, gap_end))) % 1000000:06x}",
                "name": f"{base_name} Pt {len(chunks) + 1}" if chunks else base_name,
                "text": "",
                "type": "instrumental",
                "is_user_edited": False,
                "start_sec": round(c_st, 2),
                "end_sec": round(gap_end, 2),
                "duration": round(gap_end - c_st, 2),
                "start_beat": s_beat,
                "end_beat": e_beat,
                "duration_beats": e_beat - s_beat,
                "measure": s_beat // 4,
                "is_vocal": False,
            })
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


def identify_climax_blocks(
    timeline_blocks: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    first_vocal_beat: int,
    max_arches: int = 2,
    min_separation_bars: int = 4,
) -> set[str]:
    """Identifies up to max_arches peak climax blocks across the song (e.g. audio drops,
    highest section energy, held vocal notes) to reserve the dramatic 'arch' posture for.
    Calculates candidate alignment strictly in musical beats, measures, and 4-bar / 8-bar phrases.
    """
    if max_arches <= 0 or not timeline_blocks:
        return set()

    beat_times = [float(b) for b in analysis.get("beat_times", [])]
    min_separation_beats = min_separation_bars * 4  # Standard 4/4 musical measure phrasing

    drops = analysis.get("drops", [])
    drop_beats = [
        sec_to_beat_index(float(d["drop_sec"]), beat_times)
        for d in drops
        if "drop_sec" in d
    ]
    held_notes = analysis.get("held_notes", [])
    held_spans = [
        (
            sec_to_beat_index(float(h["start_sec"]), beat_times),
            sec_to_beat_index(float(h["end_sec"]), beat_times)
        )
        for h in held_notes
        if "start_sec" in h and "end_sec" in h
    ]
    raw_sections = analysis.get("sections", [])
    section_spans = [
        (
            sec_to_beat_index(float(s["start_sec"]), beat_times),
            sec_to_beat_index(float(s["end_sec"]), beat_times),
            max(0.0, min(1.0, float(s.get("energy_score", 0.5)))),
            str(s.get("type", "")).lower()
        )
        for s in raw_sections
        if "start_sec" in s and "end_sec" in s
    ]

    candidates: List[Tuple[float, int, str]] = []  # (score, start_beat, block_id)

    for blk in timeline_blocks:
        if "start_beat" not in blk or "end_beat" not in blk:
            raise KeyError(f"Block '{blk.get('id', 'unknown')}' missing mandatory 'start_beat' / 'end_beat' fields")
        b_sbeat = int(blk["start_beat"])
        b_ebeat = int(blk["end_beat"])
        blk_id = str(blk["id"])

        # Exclude intro blocks prior to first vocal beat
        if b_ebeat <= first_vocal_beat and first_vocal_beat > 0:
            continue

        score = 0.0

        # 1. Drop Match (Highest Priority)
        is_drop_hit = any(b_sbeat <= db <= b_ebeat for db in drop_beats)
        if is_drop_hit:
            score += 100.0

        # 2. Section Energy Score
        sec_match = next((s for s in section_spans if s[0] <= b_sbeat < s[1]), None)
        if sec_match:
            sec_energy, stype = sec_match[2], sec_match[3]
            score += sec_energy * 20.0
            if stype in ["chorus", "drop", "climax", "solo"]:
                score += 10.0

        # 3. Held Notes (Vocal Sustain)
        has_held = any(h_st <= b_sbeat < h_et for h_st, h_et in held_spans)
        if has_held:
            score += 15.0

        if score > 0.0:
            candidates.append((score, b_sbeat, blk_id))

    # Sort candidates by score descending, then start_beat ascending
    candidates.sort(key=lambda x: (-x[0], x[1]))

    # If no candidates met positive criteria, fallback to post-intro long phrases
    if not candidates:
        for blk in timeline_blocks:
            b_sbeat = int(blk["start_beat"])
            b_ebeat = int(blk["end_beat"])
            if b_ebeat <= first_vocal_beat and first_vocal_beat > 0:
                continue
            candidates.append((float(b_ebeat - b_sbeat), b_sbeat, str(blk["id"])))
        candidates.sort(key=lambda x: (-x[0], x[1]))

    selected_ids: set[str] = set()
    selected_beats: List[int] = []

    for score, b_sbeat, blk_id in candidates:
        if len(selected_ids) >= max_arches:
            break
        # Ensure 4-bar (16-beat) musical phrasing separation between climax arches
        if any(abs(b_sbeat - s_beat) < min_separation_beats for s_beat in selected_beats):
            continue
        selected_ids.add(blk_id)
        selected_beats.append(b_sbeat)

    return selected_ids


CHOREO_SCHEMA_VERSION = "3.2.1"


def compile_choreography_tracks(
    analysis: Dict[str, Any],
    duration: float,
    seed: int = 42,
    existing_choreography: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compiles audio analysis into discrete 0-100% ROM movement tracks using
    exact decision trees and probability distributions, while preserving any
    blocks marked with is_user_edited: true.
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

    # Build lookup of existing user-edited moves across all channels
    existing_tracks = existing_choreography.get("tracks", {}) if existing_choreography else {}
    existing_master_blocks = existing_choreography.get("blocks", []) if existing_choreography else []
    edited_master_by_id = {b["id"]: b for b in existing_master_blocks if b.get("is_user_edited")}

    has_user_edits = bool(edited_master_by_id)
    for ch_moves in existing_tracks.values():
        if any(m.get("is_user_edited") for m in ch_moves):
            has_user_edits = True
            break
            
    if has_user_edits and existing_master_blocks:
        timeline_blocks = existing_master_blocks
        for b in timeline_blocks:
            if "start_beat" not in b or "end_beat" not in b:
                s_beat = sec_to_beat_index(float(b["start_sec"]), beat_times)
                e_beat = max(s_beat + 1, sec_to_beat_index(float(b["end_sec"]), beat_times))
                b["start_beat"] = s_beat
                b["end_beat"] = e_beat
                b["duration_beats"] = e_beat - s_beat
                b["measure"] = s_beat // 4
    else:
        timeline_blocks = partition_timeline_into_blocks(analysis, duration)

    edited_moves_by_channel: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for ch in ["spine_gaze", "s8_gantry", "s7_pedestal", "s1_torso", "s5_head_tilt", "s6_jaw"]:
        edited_moves_by_channel[ch] = {}
        for m in existing_tracks.get(ch, []):
            if m.get("is_user_edited") or (m.get("block_id") in edited_master_by_id):
                blk_key = m.get("block_id") or m.get("id")
                if blk_key:
                    edited_moves_by_channel[ch][blk_key] = m

    first_vocal_beat = len(beat_times)
    first_vocal_sec = duration
    for b in timeline_blocks:
        if b.get("is_vocal"):
            if "start_beat" not in b:
                raise KeyError(f"Vocal block '{b.get('id')}' missing mandatory 'start_beat' field")
            first_vocal_beat = int(b["start_beat"])
            first_vocal_sec = float(b["start_sec"])
            break

    # Tag at most 2 peak climax blocks to receive the dramatic 'arch' posture (separated by at least 4 bars)
    climax_arch_block_ids = identify_climax_blocks(
        timeline_blocks,
        analysis,
        first_vocal_beat,
        max_arches=2,
        min_separation_bars=4,
    )

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
            "energy_score": max(0.0, min(1.0, float(s.get("energy_score", 0.5)))),
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

    for blk_idx, blk in enumerate(timeline_blocks):
        b_st = float(blk["start_sec"])
        b_et = float(blk["end_sec"])
        b_dur = b_et - b_st
        is_vocal = bool(blk.get("is_vocal", False))
        blk_id = blk["id"]
        blk_name = blk["name"]
        is_intro = (b_et <= first_vocal_sec)
        next_is_climax = (
            blk_idx + 1 < len(timeline_blocks)
            and timeline_blocks[blk_idx + 1]["id"] in climax_arch_block_ids
        )

        sec = next((s for s in sec_blocks if s["start_sec"] <= b_st < s["end_sec"]), None)
        sec_energy = max(0.0, min(1.0, float(sec["energy_score"]))) if sec else 0.5

        is_drop_hit = any(b_st <= d_t <= b_et for d_t in drop_times)
        drop_t_hit = next((d_t for d_t in drop_times if b_st <= d_t <= b_et), b_st)

        # 1. Track 8: Gantry Slider (S8)
        if blk_id in edited_moves_by_channel.get("s8_gantry", {}):
            s8_moves.append(dict(edited_moves_by_channel["s8_gantry"][blk_id]))
            prev_state["gantry_pos_rom"] = float(edited_moves_by_channel["s8_gantry"][blk_id].get("target_pos_rom", prev_state["gantry_pos_rom"]))
        else:
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
                    g_spd = int(350 + 350 * sec_energy)
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
                    "target_pos_rom": float(target_rom),
                    "speed": int(max(200, min(800, g_spd))),
                    "drop_sec": drop_t_hit if is_drop_hit else None,
                })

        # 2. Track 6: Singing Jaw (S6)
        if blk_id in edited_moves_by_channel.get("s6_jaw", {}):
            jaw_moves.append(dict(edited_moves_by_channel["s6_jaw"][blk_id]))
        else:
            jaw_mode = "singing" if is_vocal else "closed"
            jaw_moves.append({
                "id": f"jw_{blk_id}",
                "block_id": blk_id,
                "name": f"{blk_name} Jaw ({jaw_mode.title()})",
                "start_sec": b_st,
                "end_sec": b_et,
                "jaw_mode": jaw_mode,
                "max_open_rom": 45.0,
            })

        # 3. Track 4: Neck Pitch (S4)
        pitch_r = rng.random()
        has_held_note = any(h.get("start_sec", 0.0) <= b_st < h.get("end_sec", 0.0) for h in held_notes)

        if has_held_note or pitch_r < 0.15:
            head_pitch_mode = "up"
            neck_pitch_rom = 50.0
        elif pitch_r < 0.20:
            head_pitch_mode = "down"
            neck_pitch_rom = 85.0
        else:
            head_pitch_mode = "level"
            neck_pitch_rom = 70.0

        # 4. Tracks 2-3: Spine Elevation Group (S2 Lift & S3 Elbow)
        if blk_id in edited_moves_by_channel.get("spine_gaze", {}):
            custom_spine = dict(edited_moves_by_channel["spine_gaze"][blk_id])
            spine_moves.append(custom_spine)
            prev_state["spine_pose"] = custom_spine.get("end_pose", custom_spine.get("pose_name", prev_state["spine_pose"]))
        else:
            start_pose = prev_state["spine_pose"]
            is_climax_arch = (blk_id in climax_arch_block_ids)

            if is_intro:
                spine_pattern = "hold_stand"
                mid_pose = "stand"
                end_pose = "stand"
                trans_sec = 0.5
            elif is_climax_arch:
                # Reserved peak climax moment: execute dramatic arch from stand
                spine_pattern = "stand_to_pose"
                start_pose = "stand"  # Lead-in ensures stand; enforce for clean kinematics
                mid_pose = "arch"
                end_pose = "arch"
                trans_sec = 0.5
            elif next_is_climax:
                # Lead-in block immediately preceding a climax arch: guarantee smooth return to stand
                available_poses = ["squat", "tiptoe"]
                if start_pose == "stand":
                    spine_r = rng.random()
                    if spine_r < 0.60:
                        spine_pattern = "hold_stand"
                        mid_pose = "stand"
                        end_pose = "stand"
                        trans_sec = 0.5
                    else:
                        spine_pattern = "stand_dip_stand"
                        mid_pose = rng.choice(available_poses)
                        end_pose = "stand"
                        trans_sec = 0.4
                else:
                    spine_pattern = "return_stand_mid"
                    mid_pose = start_pose
                    end_pose = "stand"
                    trans_sec = 0.45
            elif start_pose == "stand":
                available_poses = ["squat", "tiptoe"]  # arch is reserved exclusively for climax blocks
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

            if end_pose == "arch" or mid_pose == "arch":
                head_pitch_mode = "up"
                neck_pitch_rom = 50.0

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

        # 5. Track 7: Pedestal Spinner (S7)
        if blk_id in edited_moves_by_channel.get("s7_pedestal", {}):
            custom_s7 = dict(edited_moves_by_channel["s7_pedestal"][blk_id])
            s7_moves.append(custom_s7)
            prev_state["pedestal_rom"] = float(custom_s7.get("target_pos_rom", prev_state["pedestal_rom"]))
        else:
            p_r = rng.random()
            if p_r < 0.50:
                p_mode = "hold"
                target_p_rom = prev_state["pedestal_rom"]
                p_trans = 0.5
            elif p_r < 0.75:
                p_mode = "snap_left"
                target_p_rom = 25.0
                p_trans = 0.25
            else:
                p_mode = "snap_right"
                target_p_rom = 75.0
                p_trans = 0.25

            prev_state["pedestal_rom"] = target_p_rom

            s7_moves.append({
                "id": f"s7_{blk_id}",
                "block_id": blk_id,
                "name": f"{blk_name} Pedestal ({p_mode.replace('_', ' ').title()})",
                "mode": p_mode,
                "start_sec": b_st,
                "end_sec": b_et,
                "target_pos_rom": float(target_p_rom),
                "transition_sec": p_trans,
            })

        # 6. Track 1: Hips / Torso Pan (S1)
        if blk_id in edited_moves_by_channel.get("s1_torso", {}):
            s1_moves.append(dict(edited_moves_by_channel["s1_torso"][blk_id]))
        else:
            facing_mode = "audience_counter" if rng.random() < 0.80 else "base_aligned"
            s1_moves.append({
                "id": f"s1_{blk_id}",
                "block_id": blk_id,
                "name": f"{blk_name} Hips ({facing_mode.replace('_', ' ').title()})",
                "facing_mode": facing_mode,
                "start_sec": b_st,
                "end_sec": b_et,
            })

        # 7. Track 5: Head Tilt & Wrist Roll (S5)
        if blk_id in edited_moves_by_channel.get("s5_head_tilt", {}):
            s5_moves.append(dict(edited_moves_by_channel["s5_head_tilt"][blk_id]))
        else:
            tilt_r = rng.random()
            if tilt_r < 0.50:
                tilt_mode = "center"
                tilt_rom = 50.0
            elif tilt_r < 0.75:
                tilt_mode = "snap_left"
                tilt_rom = 35.0
            else:
                tilt_mode = "snap_right"
                tilt_rom = 65.0

            s5_moves.append({
                "id": f"s5_{blk_id}",
                "block_id": blk_id,
                "name": f"{blk_name} Tilt ({tilt_mode.replace('_', ' ').title()})",
                "tilt_mode": tilt_mode,
                "tilt_rom": float(tilt_rom),
                "start_sec": b_st,
                "end_sec": b_et,
            })

        # 8. Master Block Bounce Modifier
        if blk_id in edited_master_by_id and "bounce_modifier" in edited_master_by_id[blk_id]:
            blk_with_accent = dict(edited_master_by_id[blk_id])
        else:
            bounce_target = rng.choice(["hip_sway", "body_bounce", "head_bob"])
            blk_with_accent = dict(blk)
            blk_with_accent["bounce_modifier"] = {
                "enabled": True,
                "intensity": 0.12,
                "target": bounce_target,
            }
        compiled_master_blocks.append(blk_with_accent)

    return {
        "version": CHOREO_SCHEMA_VERSION,
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
