#!/usr/bin/env python3
"""Beat Bandit Application for SO-101 (Character Kinematics & Timeline Engine).
Integrates:
  - High-precision dual-engine audio analysis from Mac Mini (MMDenseLSTM neural vocal isolation + Librosa drop tagging).
  - Multi-track linear timeline execution (Body Postures, Pedestal S7, Gantry S8, Head/Jaw, Vocal Style).
  - Character-driven choreography mapped across empirical postures (STAND, TIPTOE, SQUAT).
  - 4-bar block (16 beats) rhythmic execution and smooth posture interpolation.
  - Mode A singing jaw (S6 envelope 0-45% maximum opening).
  - Gantry macro sweeps (S8 across rail during drops).
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend, SERIAL_LOCK, degrees_to_ticks_s7, ticks_to_degrees_s7, dispatch_audio_event

try:
    from beat_studio import BeatStudioManager, DEFAULT_SETTINGS, compile_default_choreography, load_dance_presets
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from beat_studio import BeatStudioManager, DEFAULT_SETTINGS, compile_default_choreography, load_dance_presets

try:
    import network_resolver
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver

LIBRARY_DIR = Path.home() / "so101/beat_bandit/library"
LOCAL_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "library" / "beat_bandit"


def get_library_path() -> Path:
    if os.name == "nt":
        LOCAL_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        return LOCAL_LIBRARY_DIR
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    return LIBRARY_DIR


def get_pi4b_sound_url() -> str:
    pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=8082)
    return f"http://{pi4b_ip}:8082/api/play_sound"


def slice_wav_in_memory(wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> bytes:
    """Extracts a precise slice of a WAV file in memory using stdlib wave."""
    if not os.path.exists(wav_path):
        return b""
    try:
        with wave.open(wav_path, "rb") as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()
            total_dur = nframes / float(framerate) if framerate > 0 else 0.0

            start_f = int(max(0.0, float(start_sec)) * framerate)
            if end_sec is not None and float(end_sec) > 0.0:
                end_f = int(min(total_dur, float(end_sec)) * framerate)
            else:
                end_f = nframes

            start_f = min(start_f, nframes)
            end_f = max(start_f, min(end_f, nframes))

            wf.setpos(start_f)
            frames_to_read = end_f - start_f
            data = wf.readframes(frames_to_read)

            buf = io.BytesIO()
            with wave.open(buf, "wb") as out_wf:
                out_wf.setnchannels(nchannels)
                out_wf.setsampwidth(sampwidth)
                out_wf.setframerate(framerate)
                out_wf.writeframes(data)
            return buf.getvalue()
    except Exception as e:
        logging.error(f"Failed slicing WAV file '{wav_path}' ({start_sec}s -> {end_sec}s): {e}")
        return b""


def sanitize_title_and_artist(raw_title: str, uploader: str = "") -> Tuple[str, str]:
    """Cleans YouTube video titles to extract pure Song Title and Artist."""
    t = raw_title.strip()
    t = re.sub(r"[\(\[\{][^\)\]\}]*(?:lyrics|official|audio|video|hd|hq|4k|visualizer|soundtrack|ost)[^\)\]\}]*[\)\]\}]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\|\s*.*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()

    if " - " in t:
        parts = t.split(" - ", 1)
        artist = parts[0].strip()
        song = parts[1].strip()
    elif " by " in t.lower():
        parts = re.split(r"\s+by\s+", t, flags=re.IGNORECASE, maxsplit=1)
        song = parts[0].strip()
        artist = parts[1].strip()
    else:
        song = t
        artist = uploader or "Unknown Artist"
    return song, artist

def compute_jaw_opening(vocal_rms: float, gate_threshold: float = 0.18, max_opening_pct: float = 45.0) -> float:
    """Computes mouth aperture percentage (0-45%) from vocal power RMS."""
    if vocal_rms < gate_threshold:
        return 0.0
    norm = min(1.0, max(0.0, (vocal_rms - gate_threshold) / (1.0 - gate_threshold)))
    return norm * max_opening_pct


# S7 4-bar alternating hip shift sequence (degrees)
S7_4BAR_ANGLES = [0.0, 25.0, -25.0, 35.0, -35.0, 0.0, 30.0, -30.0, 40.0, -40.0]



class BeatBanditApp(BaseApp):
    metadata = AppMetadata(
        name="beat_bandit_app",
        title="Beat Bandit",
        description="Character Kinematics & Audio-Synchronized Choreographer",
        version="2.0.0",
        icon="music",
        tags=["audio", "youtube", "choreography", "music", "singing", "dance"],
    )

    def __init__(self, running_on_pi: bool = True) -> None:
        super().__init__(running_on_pi=running_on_pi)
        self.library_dir = get_library_path()
        self.manifest_file = self.library_dir / "manifest.json"
        self.manifest = self._load_manifest()
        self.studio_manager = BeatStudioManager(self.library_dir, self.manifest_file)
        self.active_track: Optional[Dict[str, Any]] = None
        self.active_analysis: Optional[Dict[str, Any]] = None
        self.current_state: str = "IDLE"
        self.current_move_name: str = "Rest Stance"
        self.current_energy_level: str = "IDLE"
        self.current_vocal_power: float = 0.0
        self.current_s7_target_deg: float = 0.0
        self.current_beat_idx: int = 0
        self.current_time_sec: float = 0.0
        self.progress_pct: float = 0.0
        self.dance_thread: Optional[threading.Thread] = None
        self.track_stop_event = threading.Event()

    def _load_manifest(self) -> Dict[str, Any]:
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Failed to load manifest: {e}")
        return {}

    def _save_manifest(self) -> None:
        try:
            with open(self.manifest_file, "w", encoding="utf-8") as f:
                json.dump(self.manifest, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save manifest: {e}")

    def list_tracks(self) -> List[Dict[str, Any]]:
        tracks = []
        for tid, meta in self.manifest.items():
            wav_path = meta.get("wav_path", "")
            if os.path.exists(wav_path):
                tracks.append({
                    "track_id": tid,
                    "title": meta.get("title", tid),
                    "artist": meta.get("artist", "Unknown"),
                    "duration": meta.get("duration", 0),
                    "bpm": meta.get("tempo") or meta.get("bpm", 120),
                    "is_ready": True
                })
        return tracks

    def setup(self, backend: RobotBackend) -> None:
        self.logger.info("Setting up Beat Bandit Character Kinematics Engine...")
        self.manifest = self._load_manifest()

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        while not stop_event.is_set():
            time.sleep(0.1)
        self.stop_dance()

    def teardown(self, backend: RobotBackend) -> None:
        self.stop_dance()

    def get_status(self) -> Dict[str, Any]:
        return {
            "app_name": "beat_bandit_app",
            "state": self.current_state,
            "active_track": self.active_track.get("title") if self.active_track else None,
            "artist": self.active_track.get("artist") if self.active_track else None,
            "progress_pct": round(self.progress_pct, 1),
            "time_sec": round(self.current_time_sec, 2),
            "current_beat": self.current_beat_idx,
            "current_move": self.current_move_name,
            "energy_level": self.current_energy_level,
            "vocal_power": round(self.current_vocal_power, 1),
            "pedestal_angle_deg": round(self.current_s7_target_deg, 1),
            "tracks_count": len(self.manifest),
            "error": self.error
        }

    def start_track_by_url_or_id(self, backend: RobotBackend, url_or_id: str, start_sec: float = 0.0, end_sec: Optional[float] = None, loop: bool = False) -> Dict[str, Any]:
        self.stop_dance()
        clean_id = url_or_id.strip()
        if "youtu" in clean_id:
            m = re.search(r"(?:v=|\/|embed\/|shorts\/)([0-9A-Za-z_-]{11})", clean_id)
            track_id = m.group(1) if m else clean_id
        else:
            track_id = clean_id

        # Check local cache first
        if track_id in self.manifest:
            track_meta = self.manifest[track_id]
            wav_path = track_meta.get("wav_path")
            if not wav_path or not os.path.exists(wav_path):
                cand_path = str(self.library_dir / f"{track_id}.wav")
                if os.path.exists(cand_path):
                    wav_path = cand_path
                    track_meta["wav_path"] = cand_path

            if wav_path and os.path.exists(wav_path):
                self.logger.info(f"Loading cached track '{track_meta.get('title')}' ({track_id}) [start={start_sec:.2f}s, end={end_sec if end_sec else 'END'}s, loop={loop}]...")
                self.active_track = track_meta
                self.active_analysis = track_meta.get("analysis")
                self._launch_dance_thread(backend, start_sec=start_sec, end_sec=end_sec, loop=loop)
                return {"status": "ok", "mode": "cached_instant", "track": self.active_track, "start_sec": start_sec, "end_sec": end_sec, "loop": loop}

        # Launch downloader & dual-engine analyzer
        self.current_state = "DOWNLOADING"
        t = threading.Thread(target=self._download_and_dance_worker, args=(backend, clean_id, track_id, start_sec, end_sec, loop), daemon=True)
        t.start()
        return {"status": "ok", "mode": "downloading_and_analyzing", "target": clean_id, "start_sec": start_sec, "end_sec": end_sec, "loop": loop}

    def _download_and_dance_worker(self, backend: RobotBackend, url: str, track_id: str, start_sec: float = 0.0, end_sec: Optional[float] = None, loop: bool = False) -> None:
        try:
            self.logger.info(f"Initiating neural audio analysis pipeline for {url} ({track_id})...")
            self.current_state = "DOWNLOADING"
            download_dir = self.library_dir
            wav_path = str(download_dir / f"{track_id}.wav")

            # 1. Call Mac Deep Audio Analysis Microservice (Port 8086)
            mac_ip = network_resolver.get_mac_ip(prefer_port=8086)
            mac_url = f"http://{mac_ip}:8086/api/analyze_track"
            self.logger.info(f"Calling Mac Audio Microservice at {mac_url}...")
            req_data = json.dumps({"url": url if "http" in url else f"https://youtu.be/{track_id}", "track_id": track_id}).encode("utf-8")
            req = urllib.request.Request(mac_url, data=req_data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Mac Audio Service returned HTTP {resp.status}")
                analysis = json.loads(resp.read().decode("utf-8"))

            if not analysis or "mouth_envelope_50hz" not in analysis:
                raise RuntimeError("Mac Audio Service returned invalid or empty manifest")

            self.logger.info(
                f"Successfully received dual-engine analysis from Mac: {len(analysis.get('held_notes', []))} held notes, "
                f"{len(analysis.get('drops', []))} drops, {len(analysis.get('mouth_envelope_50hz', []))} 50Hz mouth frames."
            )

            # 2. Download WAV audio file from Mac cache
            if not os.path.exists(wav_path):
                audio_dl_url = f"http://{mac_ip}:8086/api/audio/{track_id}"
                self.logger.info(f"Downloading WAV audio from {audio_dl_url}...")
                urllib.request.urlretrieve(audio_dl_url, wav_path)

            if not os.path.exists(wav_path) or os.path.getsize(wav_path) < 1000:
                raise RuntimeError(f"Failed to retrieve WAV audio for track {track_id}")

            raw_title = analysis.get("title", track_id)
            song_title, artist = sanitize_title_and_artist(raw_title)

            # Store in Manifest
            track_meta = {
                "track_id": track_id,
                "title": song_title,
                "artist": artist,
                "duration": float(analysis.get("duration", 0.0)),
                "bpm": float(analysis.get("bpm", 120.0)),
                "wav_path": wav_path,
                "analysis": analysis,
                "created_at": time.time(),
            }
            self.manifest[track_id] = track_meta
            self._save_manifest()

            self.active_track = track_meta
            self.active_analysis = analysis

            self.logger.info(f"Ready to perform '{song_title}'. Starting dance loop...")
            self._launch_dance_thread(backend, start_sec=start_sec, end_sec=end_sec, loop=loop)

        except Exception as e:
            self.logger.error(f"Download/Analysis worker error: {e}", exc_info=True)
            self.current_state = "ERROR"
            self.error = str(e)
            dispatch_audio_event(kind="incorrect")

    def _launch_dance_thread(self, backend: RobotBackend, start_sec: float = 0.0, end_sec: Optional[float] = None, loop: bool = False) -> None:
        self.track_stop_event.clear()
        self.current_state = "DANCING"
        self.dance_thread = threading.Thread(target=self._dance_loop, args=(backend, start_sec, end_sec, loop), daemon=True)
        self.dance_thread.start()

    def _dispatch_audio_to_pi4b(self, wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> bool:
        """Dispatches audio payload to Pi 4B PulseAudio service (full or sliced)."""
        try:
            stop_req = urllib.request.Request(
                get_pi4b_sound_url(),
                data=json.dumps({"action": "stop"}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                urllib.request.urlopen(stop_req, timeout=1.0)
            except Exception:
                pass

            if os.path.exists(wav_path):
                if float(start_sec) > 0.05 or (end_sec is not None and float(end_sec) > 0.0):
                    self.logger.info(f"Slicing in-memory WAV audio for section {start_sec:.2f}s to {end_sec if end_sec else 'END'}s...")
                    raw_wav = slice_wav_in_memory(wav_path, start_sec=start_sec, end_sec=end_sec)
                else:
                    self.logger.info(f"Dispatching full audio ({os.path.getsize(wav_path)/(1024*1024):.1f} MB) to Pi 4B...")
                    with open(wav_path, "rb") as f:
                        raw_wav = f.read()

                if raw_wav:
                    req = urllib.request.Request(
                        get_pi4b_sound_url(),
                        data=raw_wav,
                        headers={"Content-Type": "audio/wav"}
                    )
                    with urllib.request.urlopen(req, timeout=7.0) as resp:
                        if resp.status == 200:
                            self.logger.info(f"Audio payload ({len(raw_wav)/1024:.1f} KB) successfully dispatched to Pi 4B.")
                            return True
        except Exception as e:
            self.logger.warning(f"Audio dispatch warning: {e}")
        return False

    def _dance_loop(self, backend: RobotBackend, start_sec: float = 0.0, end_sec: Optional[float] = None, loop: bool = False) -> None:
        """Main 50 Hz Synchronized Character Kinematics Choreography Playback Loop."""
        if not self.active_analysis or not self.active_track:
            return

        wav_path = self.active_track.get("wav_path", "")
        analysis = self.active_analysis
        duration = float(analysis.get("duration", 0.0) or analysis.get("duration_sec", 0.0))
        if "beat_times" not in analysis or len(analysis["beat_times"]) == 0:
            raise ValueError(f"Cannot perform track '{self.active_track.get('title')}': 'beat_times' missing in audio analysis.")
        beat_times = np.array(analysis["beat_times"])

        target_start_sec = max(0.0, float(start_sec))
        target_end_sec = min(duration, float(end_sec)) if (end_sec is not None and float(end_sec) > 0.0) else duration

        if target_end_sec <= target_start_sec:
            target_end_sec = duration

        # 1. Load Pre-Compiled Choreography Tracks (6-Track Timeline Contract)
        track_id = self.active_track.get("track_id", "")
        choreo = self.active_track.get("choreography")
        if not choreo or not choreo.get("tracks"):
            choreo = self.studio_manager.get_track_choreography(track_id)
            self.active_track["choreography"] = choreo

        choreo_tracks = choreo.get("tracks", {})
        spine_track = choreo_tracks.get("spine_gaze") or choreo_tracks.get("body_pose", [])
        s7_track = choreo_tracks.get("s7_pedestal", [])
        s8_track = choreo_tracks.get("s8_gantry", [])
        s1_track = choreo_tracks.get("s1_torso", [])
        s5_track = choreo_tracks.get("s5_head_tilt", [])
        mouth_env_50hz = analysis.get("mouth_envelope_50hz", [])

        settings = choreo.get("settings", DEFAULT_SETTINGS)
        max_sway_deg = float(settings.get("groove_max_sway_deg", 18.0))

        # Calibration & Center Points from Backend
        aux_calib = getattr(backend, "aux_calibration", {})
        if "7" not in aux_calib or "center_ticks" not in aux_calib["7"]:
            raise RuntimeError("Servo 7 calibration missing in calibration_aux.json")
        if "8" not in aux_calib or "min_ticks" not in aux_calib["8"] or "max_ticks" not in aux_calib["8"]:
            raise RuntimeError("Servo 8 gantry calibration missing in calibration_aux.json")

        aux_s7_center = aux_calib["7"]["center_ticks"]
        gantry_min = aux_calib["8"]["min_ticks"]
        gantry_max = aux_calib["8"]["max_ticks"]
        gantry_center = int(0.5 * (gantry_min + gantry_max))

        # Base Calibrated Poses from presets_dance.json
        choreo_poses = load_dance_presets()
        if "stand" not in choreo_poses:
            raise KeyError("Pose 'stand' missing in presets_dance.json")

        base_home = {
            "shoulder_pan": float(choreo_poses["stand"]["shoulder_pan"]),
            "shoulder_lift": float(choreo_poses["stand"]["shoulder_lift"]),
            "elbow_flex": float(choreo_poses["stand"]["elbow_flex"]),
            "wrist_flex": float(choreo_poses["stand"]["wrist_flex"]),
            "wrist_roll": float(choreo_poses["stand"]["wrist_roll"]),
        }

        # Initialize smooth dynamic state
        smooth_posture = dict(base_home)
        target_posture = dict(base_home)
        current_s7_deg = 0.0
        last_s7_sent_deg: Optional[float] = None
        last_s8_block_id: Optional[str] = None

        # Pre-roll 1: Enable torque on all servos
        try:
            backend.set_arm_torque(True)
            if hasattr(backend, "ctrl") and backend.ctrl:
                with SERIAL_LOCK:
                    backend.ctrl.set_torque(7, True, max_torque_enable=800)
                    backend.ctrl.set_torque(8, True, max_torque_enable=800)
        except Exception as t_err:
            self.logger.warning(f"Torque enable error: {t_err}")

        # Pre-roll 2: Drive to base home posture & center stage
        try:
            backend.interpolate_arm_norm(base_home, duration=0.8, steps=30)
            if hasattr(backend, "ctrl") and backend.ctrl:
                with SERIAL_LOCK:
                    backend.ctrl.write_goal_raw(7, aux_s7_center, speed=800)
                    backend.aux_positions[7] = aux_s7_center
                    with backend.lock:
                        backend.servos[7]["pos"] = aux_s7_center

            backend.move_target(8, gantry_center, speed=500, max_t=800)
            time.sleep(0.8)
        except Exception as pre_err:
            self.logger.warning(f"Arm pre-roll warning: {pre_err}")

        # Pre-roll 3: Dispatch audio to Pi 4B
        self._dispatch_audio_to_pi4b(wav_path, start_sec=target_start_sec, end_sec=target_end_sec)

        # Start 50 Hz Synchronized Loop
        start_time = time.time()
        self.logger.info(f"Starting 6-track measure performance loop ({target_start_sec:.1f}s -> {target_end_sec:.1f}s, loop={loop})...")

        try:
            while not self.track_stop_event.is_set() and not (self.stop_event and self.stop_event.is_set()):
                loop_start = time.time()
                elapsed = (loop_start - start_time) + target_start_sec
                self.current_time_sec = elapsed

                if elapsed >= target_end_sec:
                    if loop and not self.track_stop_event.is_set():
                        self.logger.info(f"Looping performance ({target_start_sec:.1f}s -> {target_end_sec:.1f}s)...")
                        start_time = time.time()
                        self._dispatch_audio_to_pi4b(wav_path, start_sec=target_start_sec, end_sec=target_end_sec)
                        continue
                    else:
                        break

                self.progress_pct = min(100.0, (elapsed / duration) * 100.0)

                # Current Beat Index and Phase Lookup
                beat_idx = int(np.searchsorted(beat_times, elapsed)) - 1
                beat_idx = max(0, min(beat_idx, len(beat_times) - 1))
                self.current_beat_idx = beat_idx

                # Calculate continuous rhythmic sway phase across beats
                if beat_idx < len(beat_times) - 1:
                    b_cur = beat_times[beat_idx]
                    b_nxt = beat_times[beat_idx + 1]
                    b_frac = (elapsed - b_cur) / max(0.05, b_nxt - b_cur)
                    sway_offset = math.sin((beat_idx % 2 + b_frac) * math.pi)
                else:
                    sway_offset = 0.0

                # 1. Track 1: Spine & Elevation (Servos 2, 3, 4)
                spine_block = next((b for b in spine_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                if spine_block:
                    pose_name = spine_block.get("pose_name", "stand")
                    if pose_name not in choreo_poses:
                        pose_name = "stand"
                    target_posture = choreo_poses[pose_name]
                    trans_sec = float(spine_block.get("transition_sec", 0.5))
                    alpha = min(1.0, max(0.04, 0.020 / max(0.1, trans_sec)))

                    head_pitch = spine_block.get("head_pitch", "level")
                    pitch_offset = 20.0 if head_pitch == "up" else (-15.0 if head_pitch == "down" else 0.0)

                    smooth_posture["shoulder_lift"] += alpha * (float(target_posture["shoulder_lift"]) - smooth_posture["shoulder_lift"])
                    smooth_posture["elbow_flex"] += alpha * (float(target_posture["elbow_flex"]) - smooth_posture["elbow_flex"])
                    smooth_posture["wrist_flex"] += alpha * ((float(target_posture["wrist_flex"]) + pitch_offset) - smooth_posture["wrist_flex"])

                    self.current_move_name = spine_block.get("name", pose_name)
                    self.current_energy_level = "HIGH ENERGY" if pose_name in ["tiptoe", "arch"] else "GROOVE"

                # 2. Track 4: Torso Pan & Groove Modifier (Servo 1)
                s1_block = next((b for b in s1_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                groove_int = float(s1_block.get("groove_intensity", 0.5)) if s1_block else 0.5
                sway_enabled = s1_block.get("sway_enabled", True) if s1_block else True
                sway_deg = (groove_int * max_sway_deg * sway_offset) if sway_enabled else 0.0
                target_pan = float(target_posture["shoulder_pan"]) + sway_deg
                smooth_posture["shoulder_pan"] += 0.25 * (target_pan - smooth_posture["shoulder_pan"])

                # 3. Track 5: Head Tilt (Servo 5)
                s5_block = next((b for b in s5_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                target_tilt = float(s5_block.get("tilt_deg", 0.0)) if s5_block else 0.0
                target_roll = float(target_posture["wrist_roll"]) + target_tilt
                smooth_posture["wrist_roll"] += 0.25 * (target_roll - smooth_posture["wrist_roll"])

                # 4. Track 3: Pedestal S7 (Macro Stage Facing)
                s7_block = next((b for b in s7_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                if s7_block:
                    target_s7_deg = float(s7_block.get("target_deg", 0.0))
                    trans_sec_s7 = float(s7_block.get("transition_sec", 0.5))
                    alpha_s7 = min(1.0, max(0.04, 0.020 / max(0.1, trans_sec_s7)))
                    current_s7_deg += alpha_s7 * (target_s7_deg - current_s7_deg)
                    current_s7_deg = max(-135.0, min(135.0, current_s7_deg))
                    self.current_s7_target_deg = current_s7_deg

                # 5. Track 2: Gantry S8 (Tier A One-Shot Dispatch)
                s8_block = next((b for b in s8_track if b["start_sec"] <= elapsed < b["end_sec"]), None)
                if s8_block and s8_block.get("id") != last_s8_block_id:
                    dest_s8 = int(s8_block.get("target_pos", gantry_center))
                    spd = int(s8_block.get("speed", 500))
                    try:
                        backend.move_target(8, dest_s8, speed=spd, max_t=800)
                        last_s8_block_id = s8_block.get("id")
                    except Exception as g_err:
                        self.logger.warning(f"Gantry timeline move warning: {g_err}")

                # 6. Track 6: Servo 6 Vocal Jaw Lip-Sync (Mode A - Capped strictly at 45%)
                jaw_open_pct = 0.0
                if mouth_env_50hz:
                    env_idx = int(elapsed * 50.0)
                    if 0 <= env_idx < len(mouth_env_50hz):
                        jaw_open_pct = float(mouth_env_50hz[env_idx])
                jaw_open_pct = max(0.0, min(45.0, jaw_open_pct))
                self.current_vocal_power = jaw_open_pct

                # 7. Assemble Goal Positions (Normalized Telemetry)
                arm_goals = {
                    "shoulder_pan": float(max(-100.0, min(100.0, smooth_posture["shoulder_pan"]))),
                    "shoulder_lift": float(max(-100.0, min(100.0, smooth_posture["shoulder_lift"]))),
                    "elbow_flex": float(max(-100.0, min(100.0, smooth_posture["elbow_flex"]))),
                    "wrist_flex": float(max(-100.0, min(100.0, smooth_posture["wrist_flex"]))),
                    "wrist_roll": float(max(-100.0, min(100.0, smooth_posture["wrist_roll"]))),
                    "gripper": float(max(0.0, min(45.0, jaw_open_pct))),
                }

                # 8. Hardware Writes (50 Hz Atomic Bulk sync_write for Motors 1-6 & Pedestal S7)
                try:
                    with SERIAL_LOCK:
                        # Atomic write to Motors 1-6
                        if backend.bus and hasattr(backend.bus, "sync_write"):
                            backend.bus.sync_write("Goal_Position", arm_goals)

                        # Write to Servo 7 (Pedestal) if angle changed by >= 0.5 deg
                        if last_s7_sent_deg is None or abs(current_s7_deg - last_s7_sent_deg) >= 0.5:
                            if hasattr(backend, "ctrl") and backend.ctrl:
                                s7_ticks = degrees_to_ticks_s7(current_s7_deg, center_ticks=aux_s7_center)
                                backend.ctrl.write_goal_raw(7, s7_ticks, speed=800)
                                last_s7_sent_deg = current_s7_deg
                                backend.aux_positions[7] = s7_ticks
                                with backend.lock:
                                    backend.servos[7]["pos"] = s7_ticks
                                    backend.servos[7]["raw"] = s7_ticks % 4096
                                    backend.servos[7]["torque"] = True
                except Exception as cmd_err:
                    self.logger.warning(f"Hardware write tick error: {cmd_err}")

                elapsed_loop = time.time() - loop_start
                sleep_time = max(0.002, 0.020 - elapsed_loop)
                time.sleep(sleep_time)

        except Exception as loop_err:
            self.logger.error(f"Fatal error in _dance_loop: {loop_err}", exc_info=True)
            self.error = str(loop_err)

        # Teardown return home
        self.current_state = "IDLE"
        self.logger.info("Performance complete. Returning to neutral stance.")
        try:
            backend.interpolate_arm_norm(base_home, duration=1.0, steps=30)
            if hasattr(backend, "ctrl") and backend.ctrl:
                with SERIAL_LOCK:
                    backend.ctrl.write_goal_raw(7, aux_s7_center, speed=500)
                    backend.aux_positions[7] = aux_s7_center
                    with backend.lock:
                        backend.servos[7]["pos"] = aux_s7_center

            backend.move_target(8, gantry_center, speed=500, max_t=800)
            time.sleep(0.8)
        except Exception as td_err:
            self.logger.warning(f"Performance teardown return home warning: {td_err}")

    def stop_dance(self) -> None:
        self.track_stop_event.set()
        if self.dance_thread and self.dance_thread.is_alive():
            self.dance_thread.join(timeout=1.0)
        self.dance_thread = None
        self.current_state = "IDLE"
        self.current_move_name = "Rest Stance"
        self.current_energy_level = "IDLE"
        self.current_vocal_power = 0.0
        self.current_s7_target_deg = 0.0

        try:
            stop_req = urllib.request.Request(get_pi4b_sound_url(), data=json.dumps({"action": "stop"}).encode("utf-8"), headers={"Content-Type": "application/json"})
            urllib.request.urlopen(stop_req, timeout=1.0)
        except Exception:
            pass

