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


def get_choreography_probabilities_path() -> Path:
    """Resolves the empirical choreography_probabilities.json file path."""
    base_dir = Path(__file__).resolve().parent.parent
    p1 = base_dir / "library" / "beat_bandit" / "choreography_probabilities.json"
    if p1.exists():
        return p1
    p2 = Path.home() / "so101" / "library" / "beat_bandit" / "choreography_probabilities.json"
    if p2.exists():
        return p2
    raise FileNotFoundError(f"choreography_probabilities.json not found at {p1} or {p2}")


def load_choreography_probabilities(filepath: Optional[str] = None) -> Dict[str, Any]:
    """Loads master choreography decision probabilities and ROM thresholds strictly from JSON with fail-fast KeyError enforcement."""
    if filepath is None:
        fpath = str(get_choreography_probabilities_path())
    else:
        fpath = filepath
    if not os.path.exists(fpath):
        raise FileNotFoundError(f"Choreography probabilities configuration file not found at: {fpath}")
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return validate_probabilities_schema(data, source_desc=fpath)

def validate_probabilities_schema(data: Dict[str, Any], source_desc: str = "probabilities") -> Dict[str, Any]:
    """Strict fail-fast contract validator for choreography probabilities schema."""
    if not isinstance(data, dict):
        raise KeyError(f"Fail-Fast Schema Error: {source_desc} must be a dictionary")

    required_sections = ["pedestal_s7", "gantry_s8", "torso_s1", "head_tilt_s5", "neck_pitch_s4", "spine_gaze", "bounce_modifier"]
    for sec in required_sections:
        if sec not in data or not isinstance(data[sec], dict):
            raise KeyError(f"Fail-Fast Schema Error: Mandatory section '{sec}' missing in {source_desc}")

    # Validate Pedestal keys
    ped = data["pedestal_s7"]
    _ = float(ped["vocal_start_shift_probability"])
    _ = float(ped["target_rom"]["shift_left"])
    _ = float(ped["target_rom"]["shift_right"])
    _ = float(ped["target_rom"]["center"])
    _ = float(ped["transition_beats"]["vocal_shift"])
    _ = float(ped["transition_beats"]["return_center"])
    _ = float(ped["transition_beats"]["hold"])

    # Validate Gantry keys
    gan = data["gantry_s8"]
    _ = float(gan["non_drop_move_probability"])
    _ = float(gan["move_type_probabilities"]["full_glide"])
    _ = float(gan["move_type_probabilities"]["early_step"])
    _ = float(gan["move_type_probabilities"]["late_step"])
    _ = [float(x) for x in gan["drop_targets_rom"]]
    _ = [float(x) for x in gan["normal_targets_rom_left"]]
    _ = [float(x) for x in gan["normal_targets_rom_right"]]
    _ = int(gan["speeds"]["drop_glide"])
    _ = int(gan["speeds"]["drop_hold"])
    _ = int(gan["speeds"]["hold"])
    _ = int(gan["speeds"]["min_glide"])
    _ = int(gan["speeds"]["max_glide"])

    # Validate Torso keys
    _ = float(data["torso_s1"]["audience_counter_probability"])

    # Validate Head Tilt keys
    tilt = data["head_tilt_s5"]
    _ = float(tilt["center_probability"])
    _ = float(tilt["snap_pulse_probability"])
    _ = float(tilt["continuous_roll_probability"])
    _ = float(tilt["snap_pulse_left_rom"])
    _ = float(tilt["snap_pulse_right_rom"])
    _ = float(tilt["snap_pulse_duration_sec"])
    _ = float(tilt["continuous_roll_amplitude_rom"])
    _ = float(tilt["continuous_roll_freq_hz"])
    _ = float(tilt["center_rom"])

    # Validate Neck Pitch keys
    pitch = data["neck_pitch_s4"]
    _ = float(pitch["up_probability"])
    _ = float(pitch["down_probability"])
    _ = float(pitch["level_probability"])
    _ = float(pitch["pitch_up_rom"])
    _ = float(pitch["pitch_down_rom"])
    _ = float(pitch["pitch_level_rom"])

    # Validate Spine Gaze keys
    spine = data["spine_gaze"]
    _ = int(spine["max_climax_arches"])
    _ = int(spine["min_separation_bars"])

    # Validate Bounce Modifier keys
    bounce = data["bounce_modifier"]
    _ = float(bounce["default_intensity"])
    if "targets" not in bounce or not isinstance(bounce["targets"], list):
        raise KeyError(f"Fail-Fast Schema Error: Mandatory 'targets' list missing in bounce_modifier section of {source_desc}")

    return data





DEFAULT_CHOREO_PROBABILITIES: Dict[str, Any] = load_choreography_probabilities()

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


CHOREO_SCHEMA_VERSION = "3.2.3"


def compile_choreography_tracks(
    analysis: Dict[str, Any],
    duration: float,
    seed: int = 42,
    existing_choreography: Optional[Dict[str, Any]] = None,
    probabilities: Optional[Dict[str, Any]] = None,
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

    if "bpm" in analysis:
        tempo = float(analysis["bpm"])
    elif "tempo" in analysis:
        tempo = float(analysis["tempo"])
    else:
        raise KeyError("Audio analysis payload missing mandatory 'bpm' or 'tempo' field")
    if tempo <= 0.0:
        raise ValueError(f"Invalid non-positive tempo '{tempo}' in audio analysis.")
    bpm = tempo

    probs = validate_probabilities_schema(probabilities, source_desc="custom_probabilities") if probabilities is not None else load_choreography_probabilities()

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

    # Tag peak climax blocks to receive the dramatic 'arch' posture (configured via spine_gaze)
    climax_arch_block_ids = identify_climax_blocks(
        timeline_blocks,
        analysis,
        first_vocal_beat,
        max_arches=int(probs["spine_gaze"]["max_climax_arches"]),
        min_separation_bars=int(probs["spine_gaze"]["min_separation_bars"]),
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
            gan_cfg = probs["gantry_s8"]
            if is_drop_hit:
                if prev_state["gantry_moving"]:
                    g_mode = "glide_to_drop_hold"
                    target_rom = float(gan_cfg["drop_targets_rom"][0] if prev_state["gantry_pos_rom"] < 50.0 else gan_cfg["drop_targets_rom"][1])
                    g_spd = int(gan_cfg["speeds"]["drop_hold"])
                    prev_state["gantry_moving"] = False
                    prev_state["gantry_pos_rom"] = target_rom
                else:
                    g_mode = "hold_to_drop_glide"
                    target_rom = float(gan_cfg["drop_targets_rom"][0] if prev_state["gantry_pos_rom"] < 50.0 else gan_cfg["drop_targets_rom"][1])
                    g_spd = int(gan_cfg["speeds"]["drop_glide"])
                    prev_state["gantry_moving"] = True
                    prev_state["gantry_pos_rom"] = target_rom
            else:
                move_prob = float(gan_cfg["non_drop_move_probability"])
                full_glide_p = float(gan_cfg["move_type_probabilities"]["full_glide"])
                early_step_p = float(gan_cfg["move_type_probabilities"]["early_step"])
                if rng.random() < move_prob:
                    sub_r = rng.random()
                    if sub_r < full_glide_p:
                        g_mode = "full_glide"
                        prev_state["gantry_moving"] = True
                    elif sub_r < (full_glide_p + early_step_p):
                        g_mode = "early_step"
                        prev_state["gantry_moving"] = False
                    else:
                        g_mode = "late_step"
                        prev_state["gantry_moving"] = True

                    if prev_state["gantry_pos_rom"] <= 50.0:
                        target_rom = round(rng.uniform(float(gan_cfg["normal_targets_rom_right"][0]), float(gan_cfg["normal_targets_rom_right"][1])), 1)
                    else:
                        target_rom = round(rng.uniform(float(gan_cfg["normal_targets_rom_left"][0]), float(gan_cfg["normal_targets_rom_left"][1])), 1)
                    min_spd = int(gan_cfg["speeds"]["min_glide"])
                    max_spd = int(gan_cfg["speeds"]["max_glide"])
                    g_spd = int(min_spd + (max_spd - min_spd) * sec_energy)
                    prev_state["gantry_pos_rom"] = target_rom
                else:
                    g_mode = "hold"
                    target_rom = prev_state["gantry_pos_rom"]
                    g_spd = int(gan_cfg["speeds"]["hold"])
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
        pitch_cfg = probs["neck_pitch_s4"]
        pitch_r = rng.random()
        has_held_note = any(h.get("start_sec", 0.0) <= b_st < h.get("end_sec", 0.0) for h in held_notes)

        up_prob = float(pitch_cfg["up_probability"])
        down_prob = float(pitch_cfg["down_probability"])

        if has_held_note or pitch_r < up_prob:
            head_pitch_mode = "up"
            neck_pitch_rom = float(pitch_cfg["pitch_up_rom"])
        elif pitch_r < (up_prob + down_prob):
            head_pitch_mode = "down"
            neck_pitch_rom = float(pitch_cfg["pitch_down_rom"])
        else:
            head_pitch_mode = "level"
            neck_pitch_rom = float(pitch_cfg["pitch_level_rom"])

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
                "start_beat": b["start_beat"],
                "end_beat": b["end_beat"],
                "duration_beats": b["duration_beats"],
                "measure": b["measure"],
                "start_sec": b_st,
                "end_sec": b_et,
                "transition_sec": trans_sec,
                "bounce_modifier": {
                    "enabled": True,
                    "intensity": float(probs["bounce_modifier"]["default_intensity"]),
                    "target": rng.choice(probs["bounce_modifier"]["targets"]),
                },
            })

        # 5. Track 7: Pedestal Spinner (S7)
        if blk_id in edited_moves_by_channel.get("s7_pedestal", {}):
            custom_s7 = dict(edited_moves_by_channel["s7_pedestal"][blk_id])
            s7_moves.append(custom_s7)
            prev_state["pedestal_rom"] = float(custom_s7["target_pos_rom"])
        else:
            ped_cfg = probs["pedestal_s7"]
            is_vocal_start = is_vocal and (blk_idx == 0 or not timeline_blocks[blk_idx - 1].get("is_vocal"))
            cur_p = prev_state["pedestal_rom"]
            vocal_shift_p = float(ped_cfg["vocal_start_shift_probability"])
            left_rom = float(ped_cfg["target_rom"]["shift_left"])
            right_rom = float(ped_cfg["target_rom"]["shift_right"])
            center_rom = float(ped_cfg["target_rom"]["center"])

            if is_vocal_start:
                # Vocal line kick-off: trigger gentle physical shift with configured probability
                snap_r = rng.random()
                if snap_r < vocal_shift_p:
                    # Choose a subtle contrasting target angle (+/-21.6 deg)
                    if cur_p == center_rom:
                        target_p_rom = left_rom if rng.random() < 0.5 else right_rom
                        p_mode = "shift_left" if target_p_rom == left_rom else "shift_right"
                    elif cur_p < center_rom:
                        target_p_rom = right_rom if rng.random() < 0.65 else center_rom
                        p_mode = "shift_right" if target_p_rom == right_rom else "center"
                    else:
                        target_p_rom = left_rom if rng.random() < 0.65 else center_rom
                        p_mode = "shift_left" if target_p_rom == left_rom else "center"
                    trans_beats = float(ped_cfg["transition_beats"]["vocal_shift"])
                else:
                    p_mode = "hold"
                    target_p_rom = cur_p
                    trans_beats = float(ped_cfg["transition_beats"]["hold"])
            elif is_vocal:
                # Continuing vocal line: hold pedestal steady for singing presence
                p_mode = "hold"
                target_p_rom = cur_p
                trans_beats = float(ped_cfg["transition_beats"]["hold"])
            else:
                # Instrumental break / pause / intro / outro: smoothly return to center stage
                if cur_p != center_rom:
                    p_mode = "return_center"
                    target_p_rom = center_rom
                    trans_beats = float(ped_cfg["transition_beats"]["return_center"])
                else:
                    p_mode = "center_hold"
                    target_p_rom = center_rom
                    trans_beats = float(ped_cfg["transition_beats"]["hold"])

            prev_state["pedestal_rom"] = target_p_rom
            sec_per_beat = (60.0 / bpm)
            p_trans = float(trans_beats * sec_per_beat)

            s7_moves.append({
                "id": f"s7_{blk_id}",
                "block_id": blk_id,
                "name": f"{blk_name} Pedestal ({p_mode.replace('_', ' ').title()})",
                "mode": p_mode,
                "start_beat": b["start_beat"],
                "end_beat": b["end_beat"],
                "duration_beats": b["duration_beats"],
                "measure": b["measure"],
                "start_sec": b_st,
                "end_sec": b_et,
                "target_pos_rom": float(target_p_rom),
                "transition_sec": p_trans,
                "transition_beats": trans_beats,
            })

        # 6. Track 1: Hips / Torso Pan (S1)
        if blk_id in edited_moves_by_channel.get("s1_torso", {}):
            s1_moves.append(dict(edited_moves_by_channel["s1_torso"][blk_id]))
        else:
            torso_cfg = probs["torso_s1"]
            counter_p = float(torso_cfg["audience_counter_probability"])
            facing_mode = "audience_counter" if rng.random() < counter_p else "base_aligned"
            s1_moves.append({
                "id": f"s1_{blk_id}",
                "block_id": blk_id,
                "name": f"{blk_name} Hips ({facing_mode.replace('_', ' ').title()})",
                "facing_mode": facing_mode,
                "start_beat": b["start_beat"],
                "end_beat": b["end_beat"],
                "duration_beats": b["duration_beats"],
                "measure": b["measure"],
                "start_sec": b_st,
                "end_sec": b_et,
            })

        # 7. Track 5: Head Tilt & Wrist Roll (S5)
        if blk_id in edited_moves_by_channel.get("s5_head_tilt", {}):
            s5_moves.append(dict(edited_moves_by_channel["s5_head_tilt"][blk_id]))
        else:
            tilt_cfg = probs["head_tilt_s5"]
            tilt_r = rng.random()
            c_prob = float(tilt_cfg["center_probability"])
            p_prob = float(tilt_cfg["snap_pulse_probability"])
            
            if tilt_r < c_prob:
                tilt_mode = "center"
                tilt_rom = float(tilt_cfg["center_rom"])
                pulse_dur = 0.0
                roll_amp = 0.0
                roll_freq = 0.0
            elif tilt_r < (c_prob + p_prob):
                tilt_dir = "left" if rng.random() < 0.5 else "right"
                tilt_mode = f"snap_pulse_{tilt_dir}"
                tilt_rom = float(tilt_cfg["snap_pulse_left_rom"] if tilt_dir == "left" else tilt_cfg["snap_pulse_right_rom"])
                pulse_dur = min(b_et - b_st, float(tilt_cfg["snap_pulse_duration_sec"]))
                roll_amp = 0.0
                roll_freq = 0.0
            else:
                tilt_mode = "continuous_roll"
                tilt_rom = float(tilt_cfg["center_rom"])
                pulse_dur = 0.0
                roll_amp = float(tilt_cfg["continuous_roll_amplitude_rom"])
                roll_freq = float(tilt_cfg["continuous_roll_freq_hz"])

            s5_moves.append({
                "id": f"s5_{blk_id}",
                "block_id": blk_id,
                "name": f"{blk_name} Tilt ({tilt_mode.replace('_', ' ').title()})",
                "tilt_mode": tilt_mode,
                "tilt_rom": float(tilt_rom),
                "pulse_duration_sec": float(pulse_dur),
                "roll_amplitude": float(roll_amp),
                "roll_freq_hz": float(roll_freq),
                "start_beat": b["start_beat"],
                "end_beat": b["end_beat"],
                "duration_beats": b["duration_beats"],
                "measure": b["measure"],
                "start_sec": b_st,
                "end_sec": b_et,
            })

        # 8. Master Block Bounce Modifier
        if blk_id in edited_master_by_id and "bounce_modifier" in edited_master_by_id[blk_id]:
            blk_with_accent = dict(edited_master_by_id[blk_id])
        else:
            bounce_cfg = probs["bounce_modifier"]
            bounce_target = rng.choice(bounce_cfg["targets"])
            blk_with_accent = dict(blk)
            blk_with_accent["bounce_modifier"] = {
                "enabled": True,
                "intensity": float(bounce_cfg["default_intensity"]),
                "target": bounce_target,
            }
        compiled_master_blocks.append(blk_with_accent)

    if "amplitude_envelope" in analysis:
        amp_env = analysis["amplitude_envelope"]
    elif "amplitude_envelope_50hz" in analysis:
        amp_env = analysis["amplitude_envelope_50hz"]
    else:
        raise KeyError("Fail-Fast Error: 'amplitude_envelope' missing in audio analysis")

    if "mouth_envelope_50hz" in analysis:
        mouth_env = analysis["mouth_envelope_50hz"]
    elif "vocal_envelope_50hz" in analysis:
        mouth_env = analysis["vocal_envelope_50hz"]
    else:
        raise KeyError("Fail-Fast Error: 'mouth_envelope_50hz' missing in audio analysis")

    if "drops" not in analysis:
        raise KeyError("Fail-Fast Error: 'drops' missing in audio analysis")
    drops_list = analysis["drops"]

    if "downbeats" not in analysis:
        raise KeyError("Fail-Fast Error: 'downbeats' missing in audio analysis")
    downbeats_list = analysis["downbeats"]

    return {
        "version": CHOREO_SCHEMA_VERSION,
        "title": analysis.get("title", "Compiled Choreography"),
        "duration": duration,
        "bpm": tempo,
        "settings": DEFAULT_CHOREO_SETTINGS,
        "poses": ROM_POSES,
        "sections": sec_blocks,
        "blocks": compiled_master_blocks,
        "beat_times": beat_times,
        "downbeats": downbeats_list,
        "drops": drops_list,
        "amplitude_envelope_50hz": amp_env,
        "mouth_envelope_50hz": mouth_env,
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
