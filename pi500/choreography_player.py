#!/usr/bin/env python3
"""Choreography Playback Engine for Beat Bandit SO-101.
Strict Single Responsibility:
Encapsulates real-time 50 Hz timeline evaluation, alpha smoothing,
sway/bounce modulation, and unified frame dispatch to the hardware backend.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Dict, Any, Optional, List, Callable

import numpy as np

try:
    from choreography_compiler import ROM_POSES, load_dance_presets
except ImportError:
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from choreography_compiler import ROM_POSES, load_dance_presets

logger = logging.getLogger("so101.choreography_player")


class ChoreographyPlayer:
    """Real-time 50 Hz playback engine for 6-track 0-100% ROM choreography."""

    def __init__(
        self,
        backend: Any,
        choreography: Dict[str, Any],
        analysis: Dict[str, Any],
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        loop: bool = False,
        on_loop_callback: Optional[Callable[[float, Optional[float]], None]] = None,
        on_finish_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.backend = backend
        self.choreo = choreography
        self.analysis = analysis
        self.start_sec = max(0.0, float(start_sec))
        self.duration = float(choreography.get("duration", 0.0) or analysis.get("duration", 0.0))
        self.end_sec = min(self.duration, float(end_sec)) if (end_sec is not None and float(end_sec) > 0.0) else self.duration
        if self.end_sec <= self.start_sec:
            self.end_sec = self.duration

        self.loop = loop
        self.on_loop_callback = on_loop_callback
        self.on_finish_callback = on_finish_callback

        # State Telemetry
        self.is_playing = False
        self.current_state = "IDLE"
        self.current_time_sec = self.start_sec
        self.progress_pct = 0.0
        self.current_beat_idx = 0
        self.current_move_name = "Rest Stance"
        self.current_energy_level = "IDLE"
        self.current_vocal_power = 0.0
        self.current_s7_target_rom = 50.0
        self.current_s7_target_deg = 0.0
        self.error: Optional[str] = None

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts background 50 Hz playback thread."""
        self.stop()
        self._stop_event.clear()
        self.is_playing = True
        self.current_state = "PLAYING"
        self._thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signals stop and waits for playback thread to return to neutral."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        self.is_playing = False
        self.current_state = "IDLE"

    def get_status(self) -> Dict[str, Any]:
        return {
            "state": self.current_state,
            "is_playing": self.is_playing,
            "time_sec": round(self.current_time_sec, 2),
            "progress_pct": round(self.progress_pct, 1),
            "current_beat": self.current_beat_idx,
            "current_move": self.current_move_name,
            "energy_level": self.current_energy_level,
            "vocal_power": round(self.current_vocal_power, 1),
            "pedestal_rom_pct": round(self.current_s7_target_rom, 1),
            "pedestal_angle_deg": round(self.current_s7_target_deg, 1),
            "error": self.error,
        }

    def _playback_loop(self) -> None:
        """Core 50 Hz playback execution."""
        try:
            beat_times = np.array(self.analysis.get("beat_times", []))
            if len(beat_times) == 0:
                raise ValueError("Missing 'beat_times' in audio analysis.")

            choreo_tracks = self.choreo.get("tracks", {})
            spine_track = choreo_tracks.get("spine_gaze", [])
            s7_track = choreo_tracks.get("s7_pedestal", [])
            s8_track = choreo_tracks.get("s8_gantry", [])
            s1_track = choreo_tracks.get("s1_torso", [])
            s5_track = choreo_tracks.get("s5_head_tilt", [])
            jaw_track = choreo_tracks.get("s6_jaw", [])
            mouth_env_50hz = self.analysis.get("mouth_envelope_50hz", [])

            choreo_poses = self.choreo.get("poses") or load_dance_presets()
            base_home_rom = {
                "shoulder_pan": float(choreo_poses["stand"]["shoulder_pan"]),
                "shoulder_lift": float(choreo_poses["stand"]["shoulder_lift"]),
                "elbow_flex": float(choreo_poses["stand"]["elbow_flex"]),
                "wrist_flex": float(choreo_poses["stand"]["wrist_flex"]),
                "wrist_roll": float(choreo_poses["stand"]["wrist_roll"]),
                "gripper": 0.0,
            }

            smooth_posture_rom = dict(base_home_rom)
            current_s7_rom = 50.0
            last_s8_block_id: Optional[str] = None

            # Pre-roll: Enable torque and center stage
            if hasattr(self.backend, "set_arm_torque"):
                try:
                    self.backend.set_arm_torque(True)
                except Exception as ex:
                    logger.debug(f"Torque enable warning: {ex}")

            if hasattr(self.backend, "dispatch_dance_frame"):
                self.backend.dispatch_dance_frame(base_home_rom, s7_rom=50.0, s8_goal=50.0, s8_is_rom=True)
            time.sleep(0.3)

            start_clock = time.time()
            logger.info(f"Choreography player loop active ({self.start_sec:.1f}s -> {self.end_sec:.1f}s, loop={self.loop})...")

            while not self._stop_event.is_set():
                loop_start = time.time()
                elapsed = (loop_start - start_clock) + self.start_sec
                self.current_time_sec = elapsed

                if elapsed >= self.end_sec:
                    if self.loop and not self._stop_event.is_set():
                        logger.info("Looping choreography playback...")
                        start_clock = time.time()
                        if self.on_loop_callback:
                            self.on_loop_callback(self.start_sec, self.end_sec)
                        continue
                    else:
                        break

                self.progress_pct = min(100.0, (elapsed / max(0.1, self.duration)) * 100.0)

                # Active Master Block & Beat Lookup
                current_block = next((b for b in self.choreo.get("blocks", []) if b["start_sec"] <= elapsed < b["end_sec"]), None)
                beat_idx = int(np.searchsorted(beat_times, elapsed)) - 1
                beat_idx = max(0, min(beat_idx, len(beat_times) - 1))
                self.current_beat_idx = beat_idx

                # Continuous rhythmic sway
                if beat_idx < len(beat_times) - 1:
                    b_cur = beat_times[beat_idx]
                    b_nxt = beat_times[beat_idx + 1]
                    b_frac = (elapsed - b_cur) / max(0.05, b_nxt - b_cur)
                    sway_offset = math.sin((beat_idx % 2 + b_frac) * math.pi)
                else:
                    sway_offset = 0.0

                # Bounce Modifier
                hip_sway_rom = 0.0
                body_bounce_rom = 0.0
                head_bob_rom = 0.0
                if current_block and "bounce_modifier" in current_block:
                    bmod = current_block["bounce_modifier"]
                    if bmod.get("enabled", True):
                        b_int = float(bmod.get("intensity", 0.12))
                        btarget = bmod.get("target", "body_bounce")
                        if btarget == "hip_sway":
                            hip_sway_rom = b_int * 15.0 * sway_offset
                        elif btarget == "body_bounce":
                            body_bounce_rom = b_int * 15.0 * abs(sway_offset)
                        elif btarget == "head_bob":
                            head_bob_rom = b_int * 18.0 * max(0.0, sway_offset)

                # 1. Tracks 2-4: Spine & Pitch (Servos 2, 3, 4)
                spine_block = next((b for b in spine_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                if spine_block:
                    pat = spine_block["pattern"]
                    b_st = float(spine_block["start_sec"])
                    b_et = float(spine_block["end_sec"])
                    b_dur = max(0.1, b_et - b_st)

                    if pat == "stand_dip_stand":
                        progress = max(0.0, min(1.0, (elapsed - b_st) / b_dur))
                        dip_weight = math.sin(progress * math.pi)
                        p_stand = choreo_poses["stand"]
                        mid_pose_name = spine_block["mid_pose"]
                        p_mid = choreo_poses[mid_pose_name]
                        target_lift = p_stand["shoulder_lift"] + (p_mid["shoulder_lift"] - p_stand["shoulder_lift"]) * dip_weight
                        target_elbow = p_stand["elbow_flex"] + (p_mid["elbow_flex"] - p_stand["elbow_flex"]) * dip_weight
                        active_pose_name = "stand" if dip_weight < 0.3 else mid_pose_name
                    else:
                        if pat == "return_stand_mid":
                            active_pose_name = spine_block["start_pose"] if elapsed < (b_st + b_dur * 0.5) else "stand"
                        elif pat == "return_stand_late":
                            active_pose_name = spine_block["start_pose"] if elapsed < (b_et - 0.4) else "stand"
                        elif pat == "return_stand_early":
                            active_pose_name = "stand"
                        else:
                            active_pose_name = spine_block["pose_name"]

                        pose_dict = choreo_poses[active_pose_name]
                        target_lift = float(pose_dict["shoulder_lift"])
                        target_elbow = float(pose_dict["elbow_flex"])

                    target_pitch = float(spine_block["neck_pitch_rom"])
                    trans_sec = float(spine_block["transition_sec"])
                    alpha = min(1.0, max(0.04, 0.020 / max(0.1, trans_sec)))

                    smooth_posture_rom["shoulder_lift"] += alpha * ((target_lift + body_bounce_rom) - smooth_posture_rom["shoulder_lift"])
                    smooth_posture_rom["elbow_flex"] += alpha * ((target_elbow - (body_bounce_rom * 0.6)) - smooth_posture_rom["elbow_flex"])
                    smooth_posture_rom["wrist_flex"] += alpha * ((target_pitch + head_bob_rom) - smooth_posture_rom["wrist_flex"])

                    self.current_move_name = spine_block.get("name", active_pose_name)
                    self.current_energy_level = "HIGH ENERGY" if active_pose_name in ["tiptoe", "arch"] else "GROOVE"

                # 2. Track 7: Pedestal (Servo 7)
                s7_block = next((b for b in s7_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                if s7_block:
                    target_s7_rom = float(s7_block["target_pos_rom"])
                    trans_s7 = float(s7_block["transition_sec"])
                    alpha_s7 = min(1.0, max(0.04, 0.020 / max(0.1, trans_s7)))
                    current_s7_rom += alpha_s7 * (target_s7_rom - current_s7_rom)
                    current_s7_rom = max(0.0, min(100.0, current_s7_rom))
                    self.current_s7_target_rom = current_s7_rom
                    self.current_s7_target_deg = (current_s7_rom - 50.0) * 2.7

                # 3. Track 1: Torso / Hips (Servo 1)
                s1_block = next((b for b in s1_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                facing_mode = s1_block.get("facing_mode", "audience_counter") if s1_block else "audience_counter"
                if facing_mode == "audience_counter":
                    counter_pan_rom = (50.0 - current_s7_rom) * 0.8
                    target_pan = 50.0 + counter_pan_rom + hip_sway_rom
                else:
                    target_pan = 50.0 + hip_sway_rom
                smooth_posture_rom["shoulder_pan"] += 0.25 * (target_pan - smooth_posture_rom["shoulder_pan"])

                # 4. Track 5: Head Tilt (Servo 5)
                s5_block = next((b for b in s5_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                target_roll = float(s5_block["tilt_rom"]) if s5_block else 50.0
                smooth_posture_rom["wrist_roll"] += 0.25 * (target_roll - smooth_posture_rom["wrist_roll"])

                # 5. Track 8: Gantry (Servo 8)
                s8_block = next((b for b in s8_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                s8_goal_rom = None
                s8_speed = 500
                if s8_block and s8_block["id"] != last_s8_block_id:
                    s8_mode = s8_block["mode"]
                    s8_drop_sec = s8_block.get("drop_sec")
                    s8_speed = int(s8_block.get("speed", 500))
                    should_move = True
                    if s8_mode == "hold_to_drop_glide" and s8_drop_sec and elapsed < float(s8_drop_sec):
                        should_move = False

                    if should_move:
                        s8_goal_rom = float(s8_block["target_pos_rom"])
                        last_s8_block_id = s8_block["id"]
                elif s8_block and s8_block["id"] == last_s8_block_id:
                    s8_mode = s8_block["mode"]
                    s8_drop_sec = s8_block.get("drop_sec")
                    if s8_mode == "hold_to_drop_glide" and s8_drop_sec and elapsed >= float(s8_drop_sec):
                        s8_goal_rom = float(s8_block["target_pos_rom"])
                        s8_speed = int(s8_block.get("speed", 500))

                # 6. Track 6: Singing Jaw (Servo 6) Capped strictly at 45%
                jaw_block = next((b for b in jaw_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                jaw_mode = jaw_block.get("jaw_mode", "singing") if jaw_block else "singing"
                jaw_open_pct = 0.0
                if jaw_mode == "singing" and mouth_env_50hz:
                    env_idx = int(elapsed * 50.0)
                    if 0 <= env_idx < len(mouth_env_50hz):
                        jaw_open_pct = float(mouth_env_50hz[env_idx])
                elif jaw_mode == "nod" and sway_offset > 0.4:
                    jaw_open_pct = 12.0

                jaw_open_pct = max(0.0, min(45.0, jaw_open_pct))
                smooth_posture_rom["gripper"] = jaw_open_pct
                self.current_vocal_power = jaw_open_pct

                # Dispatch atomic frame to backend
                if hasattr(self.backend, "dispatch_dance_frame"):
                    self.backend.dispatch_dance_frame(
                        smooth_posture_rom,
                        s7_rom=current_s7_rom,
                        s8_goal=s8_goal_rom,
                        s8_is_rom=True,
                        s8_speed=s8_speed,
                    )

                loop_time = time.time() - loop_start
                sleep_time = max(0.002, 0.020 - loop_time)
                time.sleep(sleep_time)

        except Exception as ex:
            logger.error(f"Error in choreography player: {ex}", exc_info=True)
            self.error = str(ex)
        finally:
            self.is_playing = False
            self.current_state = "IDLE"
            # Return home neutral
            if hasattr(self.backend, "dispatch_dance_frame"):
                try:
                    choreo_poses = self.choreo.get("poses") or load_dance_presets()
                    home_rom = {
                        "shoulder_pan": float(choreo_poses["stand"]["shoulder_pan"]),
                        "shoulder_lift": float(choreo_poses["stand"]["shoulder_lift"]),
                        "elbow_flex": float(choreo_poses["stand"]["elbow_flex"]),
                        "wrist_flex": float(choreo_poses["stand"]["wrist_flex"]),
                        "wrist_roll": float(choreo_poses["stand"]["wrist_roll"]),
                        "gripper": 0.0,
                    }
                    self.backend.dispatch_dance_frame(home_rom, s7_rom=50.0, s8_goal=50.0, s8_is_rom=True, s8_speed=500)
                except Exception:
                    pass

            if self.on_finish_callback:
                self.on_finish_callback()
