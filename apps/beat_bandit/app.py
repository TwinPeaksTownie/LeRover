#!/usr/bin/env python3
"""Beat Bandit Application Coordinator for SO-101.
Strict Single Responsibility:
Coordinates application lifecycle, REST API commands, the audio transport client,
the studio manager, and the 50 Hz choreography player.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend, dispatch_audio_event

try:
    from beat_bandit_audio import BeatBanditAudioClient, sanitize_title_and_artist
    from beat_studio import BeatStudioManager
    from choreography_player import ChoreographyPlayer
    from choreography_compiler import load_dance_presets, load_choreography_probabilities
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from beat_bandit_audio import BeatBanditAudioClient, sanitize_title_and_artist
    from beat_studio import BeatStudioManager
    from choreography_player import ChoreographyPlayer
    from choreography_compiler import load_dance_presets, load_choreography_probabilities

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

def load_beat_bandit_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing required BeatBandit config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_CONFIG = load_beat_bandit_config()

LIBRARY_SUBDIR = _CONFIG["library_subdir"]
LIBRARY_DIR = Path.home() / "so101" / LIBRARY_SUBDIR
LOCAL_LIBRARY_DIR = Path(__file__).resolve().parent.parent.parent / LIBRARY_SUBDIR


def get_library_path() -> Path:
    if os.name == "nt":
        LOCAL_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        return LOCAL_LIBRARY_DIR
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    return LIBRARY_DIR


class BeatBanditApp(BaseApp):
    _config = load_beat_bandit_config()
    metadata = AppMetadata(
        name=_config["name"],
        title=_config["title"],
        description=_config["description"],
        version=_config["version"],
        icon=_config["icon"],
        tags=_config["tags"],
    )

    def __init__(self, running_on_pi: bool = True) -> None:
        super().__init__(running_on_pi=running_on_pi)
        self.config = _CONFIG
        self.library_dir = get_library_path()
        self.manifest_file = self.library_dir / "manifest.json"
        self.audio_client = BeatBanditAudioClient(self.library_dir)
        self.studio_manager = BeatStudioManager(self.library_dir, self.manifest_file)
        self.manifest = self._load_manifest()

        self.player: Optional[ChoreographyPlayer] = None
        self.active_track: Optional[Dict[str, Any]] = None
        self.active_analysis: Optional[Dict[str, Any]] = None
        self.current_state: str = "IDLE"
        self.current_worker: Optional[threading.Thread] = None

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
            if "wav_path" not in meta:
                raise KeyError(f"Track '{tid}' missing required 'wav_path' in manifest.")
            wav_path = meta["wav_path"]
            if os.path.exists(wav_path):
                if "bpm" in meta and meta["bpm"] is not None:
                    bpm_val = float(meta["bpm"])
                elif "tempo" in meta and meta["tempo"] is not None:
                    bpm_val = float(meta["tempo"])
                else:
                    raise KeyError(f"Track '{tid}' missing required 'bpm' or 'tempo' in manifest.")

                if "title" not in meta:
                    raise KeyError(f"Track '{tid}' missing required 'title' in manifest.")
                if "artist" not in meta:
                    raise KeyError(f"Track '{tid}' missing required 'artist' in manifest.")
                if "duration" not in meta:
                    raise KeyError(f"Track '{tid}' missing required 'duration' in manifest.")

                tracks.append({
                    "track_id": tid,
                    "title": str(meta["title"]),
                    "artist": str(meta["artist"]),
                    "duration": float(meta["duration"]),
                    "bpm": bpm_val,
                    "is_ready": True
                })
        return tracks

    def setup(self, backend: RobotBackend) -> None:
        self.logger.info("Setting up Beat Bandit Character Kinematics Coordinator...")
        self.manifest = self._load_manifest()

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.stop_event = stop_event

        if self.app_manager is None:
            raise AttributeError("BeatBanditApp requires authoritative app_manager injected by daemon host")
        if not hasattr(self.app_manager, "pokeball_service") or self.app_manager.pokeball_service is None:
            raise AttributeError("BeatBanditApp requires authoritative app_manager.pokeball_service from daemon host")
        service = self.app_manager.pokeball_service

        if not hasattr(service, "button_b_click_event") or service.button_b_click_event is None:
            raise AttributeError("PokeballService is missing required 'button_b_click_event' attribute")
        service.button_b_click_event.clear()

        if "double_click_window_sec" not in self.config:
            raise KeyError("Fail-Fast Error: Missing required 'double_click_window_sec' in config.json")
        double_click_window = float(self.config["double_click_window_sec"])

        self.logger.info("BeatBanditApp run loop active. Monitoring Pokeball Button B double-clicks (window=%.2fs)...", double_click_window)

        last_b_click_time = 0.0

        while not stop_event.is_set():
            if service.button_b_click_event.is_set():
                service.button_b_click_event.clear()
                now = time.time()
                if (now - last_b_click_time) <= double_click_window:
                    self.logger.info("🛑 Double Button B click detected (interval=%.3fs). Triggering stop_and_center...", now - last_b_click_time)
                    last_b_click_time = 0.0
                    self.stop_and_center(backend)
                else:
                    self.logger.info("🔘 First Button B click detected. Waiting for second click within %.2fs...", double_click_window)
                    last_b_click_time = now

            time.sleep(0.03)

        self.stop_dance()


    def teardown(self, backend: RobotBackend) -> None:
        self.stop_dance()

    def get_status(self) -> Dict[str, Any]:
        if self.player and self.player.is_playing:
            p_stat = self.player.get_status()
            tempo_val = 0.0
            if self.active_track:
                if "bpm" in self.active_track and self.active_track["bpm"] is not None:
                    tempo_val = float(self.active_track["bpm"])
                elif "tempo" in self.active_track and self.active_track["tempo"] is not None:
                    tempo_val = float(self.active_track["tempo"])

            track_obj = None
            active_title = None
            active_artist = None
            if self.active_track:
                active_title = str(self.active_track["title"])
                active_artist = str(self.active_track["artist"])
                track_obj = {
                    "title": active_title,
                    "artist": active_artist
                }

            return {
                "app_name": "beat_bandit_app",
                "state": p_stat["state"],
                "is_dancing": True,
                "is_playing": True,
                "active_track": active_title,
                "artist": active_artist,
                "track": track_obj,
                "tempo": tempo_val,
                "progress": p_stat["progress_pct"],
                "progress_pct": p_stat["progress_pct"],
                "time_sec": p_stat["time_sec"],
                "current_beat": p_stat["current_beat"],
                "current_move": p_stat["current_move"],
                "energy_level": p_stat["energy_level"],
                "vocal_power": p_stat["vocal_power"],
                "pedestal_rom_pct": p_stat["pedestal_rom_pct"],
                "pedestal_angle_deg": p_stat["pedestal_angle_deg"],
                "s7_angle_deg": p_stat["pedestal_angle_deg"],
                "tracks_count": len(self.manifest),
                "error": p_stat["error"] or self.error,
            }

        tempo_val = 0.0
        if self.active_track:
            if "bpm" in self.active_track and self.active_track["bpm"] is not None:
                tempo_val = float(self.active_track["bpm"])
            elif "tempo" in self.active_track and self.active_track["tempo"] is not None:
                tempo_val = float(self.active_track["tempo"])

        track_obj = None
        active_title = None
        active_artist = None
        if self.active_track:
            active_title = str(self.active_track["title"])
            active_artist = str(self.active_track["artist"])
            track_obj = {
                "title": active_title,
                "artist": active_artist
            }

        return {
            "app_name": "beat_bandit_app",
            "state": self.current_state,
            "is_dancing": (self.current_state == "DANCING"),
            "is_playing": False,
            "active_track": active_title,
            "artist": active_artist,
            "track": track_obj,
            "tempo": tempo_val,
            "progress": 0.0,
            "progress_pct": 0.0,
            "time_sec": 0.0,
            "current_beat": 0,
            "current_move": "Rest Stance",
            "energy_level": "IDLE",
            "vocal_power": 0.0,
            "pedestal_rom_pct": 50.0,
            "pedestal_angle_deg": 0.0,
            "s7_angle_deg": 0.0,
            "tracks_count": len(self.manifest),
            "error": self.error,
        }

    def start_track_by_url_or_id(
        self,
        backend: RobotBackend,
        url_or_id: str,
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        loop: bool = False
    ) -> Dict[str, Any]:
        self.stop_dance()
        clean_id = url_or_id.strip()
        if "youtu" in clean_id:
            m = re.search(r"(?:v=|\/|embed\/|shorts\/)([0-9A-Za-z_-]{11})", clean_id)
            track_id = m.group(1) if m else clean_id
        else:
            track_id = clean_id

        # 1. Check local cache
        if track_id in self.manifest:
            track_meta = self.manifest[track_id]
            wav_path = track_meta.get("wav_path")
            if not wav_path or not os.path.exists(wav_path):
                cand_path = str(self.library_dir / f"{track_id}.wav")
                if os.path.exists(cand_path):
                    wav_path = cand_path
                    track_meta["wav_path"] = cand_path

            if wav_path and os.path.exists(wav_path):
                self.logger.info(f"Loading cached track '{track_meta.get('title')}' ({track_id})...")
                self.active_track = track_meta
                self.active_analysis = track_meta.get("analysis")
                self._start_player_session(backend, start_sec=start_sec, end_sec=end_sec, loop=loop)
                return {
                    "status": "ok",
                    "mode": "cached_instant",
                    "track": self.active_track,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "loop": loop
                }

        # 2. Download and Analyze asynchronously
        self.current_state = "DOWNLOADING"
        self.current_worker = threading.Thread(
            target=self._download_and_dance_worker,
            args=(backend, clean_id, track_id, start_sec, end_sec, loop),
            daemon=True
        )
        self.current_worker.start()
        return {
            "status": "ok",
            "mode": "downloading_and_analyzing",
            "target": clean_id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "loop": loop
        }

    def _download_and_dance_worker(
        self,
        backend: RobotBackend,
        url: str,
        track_id: str,
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        loop: bool = False
    ) -> None:
        try:
            self.logger.info(f"Initiating neural audio analysis pipeline for {url} ({track_id})...")
            self.current_state = "DOWNLOADING"

            # 1. Fetch analysis from Mac Mini
            analysis = self.audio_client.fetch_analysis(url, track_id)

            # 2. Download WAV from Mac Mini
            wav_path = self.audio_client.download_wav(track_id)

            if "title" not in analysis or not analysis["title"]:
                raise KeyError(f"Audio analysis for '{track_id}' missing required 'title' field.")
            raw_title = str(analysis["title"])
            song_title, artist = sanitize_title_and_artist(raw_title)

            if "duration" not in analysis or float(analysis["duration"]) <= 0.0:
                raise ValueError("Audio analysis is missing valid 'duration'.")
            if "bpm" not in analysis or float(analysis["bpm"]) <= 0.0:
                raise ValueError("Audio analysis is missing valid 'bpm'.")

            track_meta = {
                "track_id": track_id,
                "title": song_title,
                "artist": artist,
                "duration": float(analysis["duration"]),
                "bpm": float(analysis["bpm"]),
                "wav_path": wav_path,
                "analysis": analysis,
                "created_at": time.time(),
            }
            self.manifest[track_id] = track_meta
            self._save_manifest()

            self.active_track = track_meta
            self.active_analysis = analysis

            self.logger.info(f"Ready to perform '{song_title}'. Starting dance session...")
            self._start_player_session(backend, start_sec=start_sec, end_sec=end_sec, loop=loop)

        except Exception as e:
            self.logger.error(f"Download/Analysis worker error: {e}", exc_info=True)
            self.current_state = "ERROR"
            self.error = str(e)
            dispatch_audio_event(kind="incorrect")

    def _handle_player_loop(self, wav_path: str, st: float, et: Optional[float]) -> None:
        self.audio_client.dispatch_playback(wav_path, start_sec=st, end_sec=et)

    def _handle_player_finish(self) -> None:
        self.current_state = "IDLE"
        self.audio_client.stop_playback()

    def _start_player_session(
        self,
        backend: RobotBackend,
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        loop: bool = False
    ) -> None:
        if not self.active_track or not self.active_analysis:
            return

        track_id = self.active_track["track_id"]
        choreo = self.studio_manager.get_track_choreography(track_id)
        self.active_track["choreography"] = choreo

        if "probabilities" not in choreo or not isinstance(choreo["probabilities"], dict):
            choreo["probabilities"] = load_choreography_probabilities()

        wav_path = self.active_track["wav_path"]

        # 1. Instantiate and strictly validate ChoreographyPlayer BEFORE dispatching audio
        self.player = ChoreographyPlayer(
            backend=backend,
            choreography=choreo,
            analysis=self.active_analysis,
            start_sec=start_sec,
            end_sec=end_sec,
            loop=loop,
            on_loop_callback=lambda st, et: self._handle_player_loop(wav_path, st, et),
            on_finish_callback=self._handle_player_finish,
        )

        # 2. Dispatch Audio to Pi 4B only after player initialization succeeds
        self.audio_client.dispatch_playback(wav_path, start_sec=start_sec, end_sec=end_sec)

        self.current_state = "DANCING"
        self.player.start()

    def stop_dance(self) -> None:
        if self.player:
            self.player.stop()
            self.player = None
        self.audio_client.stop_playback()
        self.current_state = "IDLE"

    def stop_and_center(self, backend: RobotBackend) -> None:
        """Stops active choreography, halts audio on Pi 4B, and dynamically homes Servos 1-8."""
        self.logger.info("🛑 stop_and_center requested! Halting choreography and centering actuators...")
        self.stop_dance()

        # Dynamic Calibration: Servos 1-6 loaded from presets_dance.json["stand"]
        poses = load_dance_presets()
        if "stand" not in poses:
            raise KeyError("Fail-Fast Error: Missing required 'stand' preset in presets_dance.json")
        stand = poses["stand"]
        for motor_key in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]:
            if motor_key not in stand:
                raise KeyError(f"Fail-Fast Error: Motor '{motor_key}' missing in 'stand' preset")
        home_rom = {
            "shoulder_pan": float(stand["shoulder_pan"]),
            "shoulder_lift": float(stand["shoulder_lift"]),
            "elbow_flex": float(stand["elbow_flex"]),
            "wrist_flex": float(stand["wrist_flex"]),
            "wrist_roll": float(stand["wrist_roll"]),
            "gripper": float(stand["gripper"]),
        }

        # Dynamic Calibration: Servos 7 and 8 computed from calibration_aux.json bounds
        calib_aux_file = Path(__file__).resolve().parent.parent.parent / "calibration_aux.json"
        if not calib_aux_file.exists():
            calib_aux_file = Path.home() / "so101" / "calibration_aux.json"
        if not calib_aux_file.exists():
            raise FileNotFoundError(f"Fail-Fast Error: 'calibration_aux.json' not found at {calib_aux_file}")
        with open(calib_aux_file, "r", encoding="utf-8") as f:
            calib_aux = json.load(f)

        if "7" not in calib_aux or "min_ticks" not in calib_aux["7"] or "max_ticks" not in calib_aux["7"] or "center_ticks" not in calib_aux["7"]:
            raise KeyError("Fail-Fast Error: Servo 7 calibration parameters missing in calibration_aux.json")
        min_7 = float(calib_aux["7"]["min_ticks"])
        max_7 = float(calib_aux["7"]["max_ticks"])
        center_7 = float(calib_aux["7"]["center_ticks"])
        if max_7 <= min_7:
            raise ValueError(f"Fail-Fast Error: Invalid Servo 7 calibration bounds: min={min_7}, max={max_7}")
        s7_neutral_rom = round(((center_7 - min_7) / (max_7 - min_7)) * 100.0, 2)

        if "8" not in calib_aux or "min_ticks" not in calib_aux["8"] or "max_ticks" not in calib_aux["8"] or "center_ticks" not in calib_aux["8"]:
            raise KeyError("Fail-Fast Error: Servo 8 calibration parameters missing in calibration_aux.json")
        min_8 = float(calib_aux["8"]["min_ticks"])
        max_8 = float(calib_aux["8"]["max_ticks"])
        center_8 = float(calib_aux["8"]["center_ticks"])
        if max_8 <= min_8:
            raise ValueError(f"Fail-Fast Error: Invalid Servo 8 calibration bounds: min={min_8}, max={max_8}")
        s8_neutral_rom = round(((center_8 - min_8) / (max_8 - min_8)) * 100.0, 2)

        if "homing_speed" not in self.config:
            raise KeyError("Fail-Fast Error: Missing required 'homing_speed' in config.json")
        homing_speed = int(self.config["homing_speed"])

        if hasattr(backend, "dispatch_dance_frame"):
            backend.dispatch_dance_frame(
                home_rom,
                s7_rom=s7_neutral_rom,
                s8_goal=s8_neutral_rom,
                s8_is_rom=True,
                s8_speed=homing_speed,
            )

        dispatch_audio_event(kind="app_exit_idle")
        self.current_state = "IDLE"


    def preview_isolated_block(
        self,
        backend: RobotBackend,
        track_id: str,
        channel: str,
        block: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Runs a 50 Hz dynamic preview session for a single block while isolating all other channels at neutral defaults."""
        self.stop_dance()
        if track_id not in self.manifest:
            raise KeyError(f"Fail-Fast Error: Track '{track_id}' not found in manifest")

        track_meta = self.manifest[track_id]
        if "analysis" not in track_meta:
            raise KeyError(f"Fail-Fast Error: 'analysis' missing for track '{track_id}'")
        analysis = track_meta["analysis"]
        if "wav_path" not in track_meta:
            raise KeyError(f"Fail-Fast Error: 'wav_path' missing in manifest for track '{track_id}'")
        wav_path = track_meta["wav_path"]
        if not os.path.exists(wav_path):
            raise FileNotFoundError(f"Fail-Fast Error: WAV audio file not found at '{wav_path}' for track '{track_id}'")

        if "start_sec" not in block or "end_sec" not in block or "name" not in block:
            raise KeyError("Fail-Fast Error: 'name', 'start_sec', and 'end_sec' required in preview block payload")

        st = max(0.0, float(block["start_sec"]))
        et = float(block["end_sec"])
        if et <= st:
            et = st + 1.0

        poses = load_dance_presets()
        probs = load_choreography_probabilities()

        if "neck_pitch_s4" not in probs or "pitch_level_rom" not in probs["neck_pitch_s4"]:
            raise KeyError("Fail-Fast Error: 'neck_pitch_s4.pitch_level_rom' missing in choreography probabilities")
        neutral_neck_pitch = float(probs["neck_pitch_s4"]["pitch_level_rom"])

        if "pedestal_s7" not in probs or "target_rom" not in probs["pedestal_s7"] or "center" not in probs["pedestal_s7"]["target_rom"]:
            raise KeyError("Fail-Fast Error: 'pedestal_s7.target_rom.center' missing in choreography probabilities")
        neutral_s7_center = float(probs["pedestal_s7"]["target_rom"]["center"])

        if "head_tilt_s5" not in probs or "center_rom" not in probs["head_tilt_s5"]:
            raise KeyError("Fail-Fast Error: 'head_tilt_s5.center_rom' missing in choreography probabilities")
        neutral_s5_center = float(probs["head_tilt_s5"]["center_rom"])

        # Dynamically load Auxiliary Servo 8 Calibration from calibration_aux.json
        calib_aux_file = Path(__file__).resolve().parent.parent.parent / "calibration_aux.json"
        if not calib_aux_file.exists():
            calib_aux_file = Path.home() / "so101" / "calibration_aux.json"
        if not calib_aux_file.exists():
            raise FileNotFoundError("Fail-Fast Error: 'calibration_aux.json' not found on system")
        with open(calib_aux_file, "r", encoding="utf-8") as f:
            calib_aux = json.load(f)
        if "8" not in calib_aux or "min_ticks" not in calib_aux["8"] or "max_ticks" not in calib_aux["8"] or "center_ticks" not in calib_aux["8"]:
            raise KeyError("Fail-Fast Error: Servo 8 calibration parameters missing in calibration_aux.json")
        min_8 = float(calib_aux["8"]["min_ticks"])
        max_8 = float(calib_aux["8"]["max_ticks"])
        center_8 = float(calib_aux["8"]["center_ticks"])
        neutral_s8_center = round(((center_8 - min_8) / (max_8 - min_8)) * 100.0, 2)

        isolated_tracks: Dict[str, List[Dict[str, Any]]] = {
            "lyrics": [],
            "spine_gaze": [],
            "s8_gantry": [],
            "s7_pedestal": [],
            "s1_torso": [],
            "s5_head_tilt": [],
            "s6_jaw": [],
        }

        # Normalize channel name aliases
        target_channel = channel
        if channel == "body_pose":
            target_channel = "spine_gaze"
        elif channel == "head_jaw":
            target_channel = "s6_jaw"

        if target_channel not in isolated_tracks:
            raise KeyError(f"Fail-Fast Error: Unsupported preview channel '{channel}'")

        # Copy block to target channel
        isolated_tracks[target_channel] = [dict(block)]

        # Fill default neutral blocks for other channels across [st, et]
        if target_channel != "spine_gaze":
            isolated_tracks["spine_gaze"] = [{
                "id": "neutral_spine",
                "name": "Neutral Hold",
                "start_sec": st,
                "end_sec": et,
                "pose_name": "stand",
                "pattern": "hold_stand",
                "transition_sec": 0.3,
                "neck_pitch_rom": neutral_neck_pitch,
                "bounce_modifier": {"enabled": False, "intensity": 0.0, "target": "body_bounce"}
            }]

        if target_channel != "s7_pedestal":
            isolated_tracks["s7_pedestal"] = [{
                "id": "neutral_s7",
                "name": "Center Hold",
                "start_sec": st,
                "end_sec": et,
                "mode": "center_hold",
                "target_pos_rom": neutral_s7_center,
                "transition_sec": 0.3
            }]

        if target_channel != "s8_gantry":
            isolated_tracks["s8_gantry"] = [{
                "id": "neutral_s8",
                "name": "Center Hold",
                "start_sec": st,
                "end_sec": et,
                "mode": "hold",
                "target_pos_rom": neutral_s8_center,
                "speed": 500
            }]

        if target_channel != "s1_torso":
            isolated_tracks["s1_torso"] = [{
                "id": "neutral_s1",
                "name": "Base Aligned",
                "start_sec": st,
                "end_sec": et,
                "facing_mode": "base_aligned"
            }]

        if target_channel != "s5_head_tilt":
            isolated_tracks["s5_head_tilt"] = [{
                "id": "neutral_s5",
                "name": "Level Center",
                "start_sec": st,
                "end_sec": et,
                "tilt_mode": "center",
                "tilt_rom": neutral_s5_center
            }]

        if target_channel != "s6_jaw":
            isolated_tracks["s6_jaw"] = [{
                "id": "neutral_s6",
                "name": "Closed",
                "start_sec": st,
                "end_sec": et,
                "jaw_mode": "closed"
            }]

        isolated_choreo = {
            "version": "3.3.0",
            "title": f"Preview: {block['name']}",
            "duration": et,
            "poses": poses,
            "probabilities": probs,
            "blocks": [dict(block)],
            "tracks": isolated_tracks,
        }

        self.active_track = track_meta
        self.active_analysis = analysis

        # 1. Instantiate and strictly validate 50 Hz Player for exact block duration [st, et]
        self.player = ChoreographyPlayer(
            backend=backend,
            choreography=isolated_choreo,
            analysis=analysis,
            start_sec=st,
            end_sec=et,
            loop=False,
            on_finish_callback=self._handle_player_finish,
        )

        # 2. Dispatch Audio Slice to Pi 4B only after player initialization succeeds
        if wav_path and os.path.exists(wav_path):
            self.audio_client.dispatch_playback(wav_path, start_sec=st, end_sec=et)

        self.current_state = "PREVIEWING"
        self.player.start()

        return {
            "status": "ok",
            "mode": "block_preview",
            "channel": target_channel,
            "start_sec": st,
            "end_sec": et,
            "duration": et - st,
        }

