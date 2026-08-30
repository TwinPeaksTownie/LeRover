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
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from beat_bandit_audio import BeatBanditAudioClient, sanitize_title_and_artist
    from beat_studio import BeatStudioManager
    from choreography_player import ChoreographyPlayer

LIBRARY_DIR = Path.home() / "so101/beat_bandit/library"
LOCAL_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "library" / "beat_bandit"


def get_library_path() -> Path:
    if os.name == "nt":
        LOCAL_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        return LOCAL_LIBRARY_DIR
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    return LIBRARY_DIR


class BeatBanditApp(BaseApp):
    metadata = AppMetadata(
        name="beat_bandit_app",
        title="Beat Bandit",
        description="Character Kinematics & Audio-Synchronized Choreographer",
        version="3.2.0",
        icon="music",
        tags=["audio", "youtube", "choreography", "music", "singing", "dance"],
    )

    def __init__(self, running_on_pi: bool = True) -> None:
        super().__init__(running_on_pi=running_on_pi)
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
            wav_path = meta.get("wav_path", "")
            if os.path.exists(wav_path):
                if "bpm" not in meta and "tempo" not in meta:
                    raise KeyError(f"Track '{tid}' missing 'bpm' in manifest.")
                bpm_val = float(meta.get("bpm") or meta.get("tempo"))
                tracks.append({
                    "track_id": tid,
                    "title": meta.get("title", tid),
                    "artist": meta.get("artist", ""),
                    "duration": float(meta.get("duration", 0.0)),
                    "bpm": bpm_val,
                    "is_ready": True
                })
        return tracks

    def setup(self, backend: RobotBackend) -> None:
        self.logger.info("Setting up Beat Bandit Character Kinematics Coordinator...")
        self.manifest = self._load_manifest()

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        while not stop_event.is_set():
            time.sleep(0.1)
        self.stop_dance()

    def teardown(self, backend: RobotBackend) -> None:
        self.stop_dance()

    def get_status(self) -> Dict[str, Any]:
        if self.player and self.player.is_playing:
            p_stat = self.player.get_status()
            return {
                "app_name": "beat_bandit_app",
                "state": p_stat["state"],
                "active_track": self.active_track.get("title") if self.active_track else None,
                "artist": self.active_track.get("artist") if self.active_track else None,
                "progress_pct": p_stat["progress_pct"],
                "time_sec": p_stat["time_sec"],
                "current_beat": p_stat["current_beat"],
                "current_move": p_stat["current_move"],
                "energy_level": p_stat["energy_level"],
                "vocal_power": p_stat["vocal_power"],
                "pedestal_rom_pct": p_stat["pedestal_rom_pct"],
                "pedestal_angle_deg": p_stat["pedestal_angle_deg"],
                "tracks_count": len(self.manifest),
                "error": p_stat["error"] or self.error,
            }

        return {
            "app_name": "beat_bandit_app",
            "state": self.current_state,
            "active_track": self.active_track.get("title") if self.active_track else None,
            "artist": self.active_track.get("artist") if self.active_track else None,
            "progress_pct": 0.0,
            "time_sec": 0.0,
            "current_beat": 0,
            "current_move": "Rest Stance",
            "energy_level": "IDLE",
            "vocal_power": 0.0,
            "pedestal_rom_pct": 50.0,
            "pedestal_angle_deg": 0.0,
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

            raw_title = analysis.get("title", track_id)
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

    def _start_player_session(
        self,
        backend: RobotBackend,
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        loop: bool = False
    ) -> None:
        if not self.active_track or not self.active_analysis:
            return

        track_id = self.active_track.get("track_id", "")
        choreo = self.active_track.get("choreography")
        if not choreo or not choreo.get("tracks"):
            choreo = self.studio_manager.get_track_choreography(track_id)
            self.active_track["choreography"] = choreo

        wav_path = self.active_track.get("wav_path", "")

        def _on_loop(st: float, et: Optional[float]):
            self.audio_client.dispatch_playback(wav_path, start_sec=st, end_sec=et)

        def _on_finish():
            self.current_state = "IDLE"

        # Dispatch Audio to Pi 4B
        self.audio_client.dispatch_playback(wav_path, start_sec=start_sec, end_sec=end_sec)

        # Start Playback Engine
        self.player = ChoreographyPlayer(
            backend=backend,
            choreography=choreo,
            analysis=self.active_analysis,
            start_sec=start_sec,
            end_sec=end_sec,
            loop=loop,
            on_loop_callback=_on_loop,
            on_finish_callback=_on_finish,
        )
        self.current_state = "DANCING"
        self.player.start()

    def stop_dance(self) -> None:
        if self.player:
            self.player.stop()
            self.player = None
        self.audio_client.stop_playback()
        self.current_state = "IDLE"
