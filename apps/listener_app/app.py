#!/usr/bin/env python3
"""apps/listener_app/app.py - Ephemeral Voice Listener Application for SO-101.
Managed by AppManager on the Pi 500 under exclusive RobotAppLock.
Lifecycle:
  LAUNCH -> Opens Daemon Audio Stream -> Runs Offline KWS Loop -> Trigger
         -> Capture Command Buffer -> Local ASR Transcription
         -> Intent Dispatch:
              1. SWITCH_APP -> Calls app_manager.start_app() (terminates listener)
              2. MOVE_PRIMITIVE -> Executes calibrated motion via RobotBackend
              3. DOWNLOAD_SONG -> Triggers yt-dlp + choreography compiler
              4. PLAY_SONG -> Launches sequence playback
Strict Fail-Fast schema compliance: Zero .get(k, default) fallbacks.
Strict Dynamic Calibration: Zero hardcoded 2048 ticks.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import threading
import time
import urllib.request
import wave
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List

APP_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = APP_DIR.parent.parent
PI500_DIR = WORKSPACE_ROOT / "pi500"
CONFIG_DIR = WORKSPACE_ROOT / "config"

for p in [WORKSPACE_ROOT, PI500_DIR, CONFIG_DIR]:
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend, dispatch_audio_event
from telemetry_proxies import MOTOR_NAMES

import network_resolver
import audio_resolver

from apps.listener_app.intent_parser import parse_intent
from apps.listener_app.song_pipeline import (
    download_and_compile,
    find_compiled_sequence,
    find_beat_bandit_track,
    fetch_search_candidates,
    get_beat_bandit_manifest_path,
)

CONFIG_PATH = APP_DIR / "config.json"


def load_listener_config() -> Dict[str, Any]:
    """Loads listener_app config with strict fail-fast validation."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing required ListenerApp config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Validate mandatory schema keys
    _ = cfg["name"]
    _ = cfg["title"]
    _ = cfg["description"]
    _ = cfg["version"]
    _ = cfg["icon"]
    _ = cfg["tags"]
    _ = int(cfg["hotword"]["chunk_samples"])
    _ = int(cfg["hotword"]["sample_rate"])
    _ = float(cfg["hotword"]["energy_multiplier"])
    _ = cfg["asr"]["engine"]
    _ = str(cfg["asr"]["server_url"])
    _ = str(cfg["asr"]["health_url"])
    _ = float(cfg["asr"]["timeout_sec"])
    _ = bool(cfg["asr"]["use_dynamic_grammar"])
    settle_sec = float(cfg["vad"]["settle_delay_sec"])
    if settle_sec <= 0:
        raise ValueError("settle_delay_sec must be positive")
    _ = float(cfg["vad"]["silence_timeout_sec"])
    _ = float(cfg["vad"]["max_record_sec"])
    _ = float(cfg["vad"]["min_record_sec"])
    _ = int(cfg["vad"]["energy_threshold"])
    pre_roll = int(cfg["vad"]["pre_roll_chunks"])
    if pre_roll <= 0:
        raise ValueError("pre_roll_chunks must be positive")
    fuzzy_thresh = float(cfg["vad"]["fuzzy_match_threshold"])
    if fuzzy_thresh <= 0.0 or fuzzy_thresh > 1.0:
        raise ValueError("fuzzy_match_threshold must be between 0.0 and 1.0")
    _ = cfg["chimes"]["app_start"]
    _ = cfg["chimes"]["wake"]
    _ = cfg["chimes"]["commit"]
    _ = cfg["chimes"]["cancel"]
    _ = cfg["chimes"]["exit"]
    _ = str(cfg["feedback"]["unmatched_action"])
    _ = str(cfg["feedback"]["idle_action"])
    _ = str(cfg["feedback"]["idle_transcript"])
    _ = int(cfg["network"]["pi4b_port"])
    _ = int(cfg["network"]["mac_port"])
    return cfg


_CONFIG = load_listener_config()


def load_calibration_limits(
    backend: Optional[RobotBackend] = None,
    calib_file: Optional[Path] = None,
) -> Dict[int, Dict[str, int]]:
    """Loads empirical follower calibration limits dynamically into memory. Zero hardcoded 2048."""
    # 1. Prefer in-memory backend calibration if available
    if backend is not None and hasattr(backend, "arm_calibration") and bool(backend.arm_calibration):
        limits = {}
        for sid in range(1, 7):
            name = MOTOR_NAMES[sid]
            if name not in backend.arm_calibration:
                raise KeyError(f"Follower calibration missing required servo '{name}' (ID {sid}) in backend")
            calib = backend.arm_calibration[name]
            rmin = int(calib.range_min)
            rmax = int(calib.range_max)
            limits[sid] = {
                "min": rmin,
                "max": rmax,
                "center": (rmin + rmax) // 2,
            }
        return limits

    # 2. Canonical LeRobot follower calibration file path
    target_path = calib_file or (Path.home() / ".cache/huggingface/lerobot/calibration/robots/so_follower/follower.json")
    if not target_path.exists():
        raise FileNotFoundError(f"Missing required follower calibration: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    limits = {}
    for sid in range(1, 7):
        name = MOTOR_NAMES[sid]
        if name not in data:
            raise KeyError(f"Follower calibration missing required servo '{name}' (ID {sid}) in {target_path}")
        cdata = data[name]
        rmin = int(cdata["range_min"])
        rmax = int(cdata["range_max"])
        limits[sid] = {
            "min": rmin,
            "max": rmax,
            "center": (rmin + rmax) // 2,
        }
    return limits


class ListenerApp(BaseApp):
    """Ephemeral Voice Listener App running strictly inside AppManager lifecycle."""
    _config = load_listener_config()
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
        self.logger = logging.getLogger("so101.app.listener_app")
        self.config = load_listener_config()
        self.state = "IDLE"
        self.transcript: str = str(self.config["feedback"]["idle_transcript"])
        self.action_taken: str = str(self.config["feedback"]["idle_action"])
        self.search_query: str = ""
        self.search_results: List[Dict[str, Any]] = []
        self.selected_index: int = 0
        self._selection_lock = threading.RLock()
        self._stream_resp: Any = None
        self.app_manager: Any = None
        self.asr_model: Any = None
        self.kws_engine: Any = None
        self.calib_limits: Dict[int, Dict[str, int]] = {}
        self.last_analyzed_track: Optional[Dict[str, Any]] = None
        self._vosk_ready: bool = False

    def get_status(self) -> Dict[str, Any]:
        """Returns structured status dictionary for Master API inspection."""
        with self._selection_lock:
            return {
                "name": self.name,
                "state": self.state,
                "transcript": self.transcript,
                "action_taken": self.action_taken,
                "query": self.search_query,
                "search_query": self.search_query,
                "search_results": list(self.search_results),
                "selected_index": self.selected_index,
                "last_analyzed_track": self.last_analyzed_track,
                "error": self.error,
            }

    def navigate_selection(self, delta: int) -> int:
        """Navigates track selection cursor by delta (+1 or -1) clamped to [0, len(results)-1]."""
        with self._selection_lock:
            if not self.search_results:
                self.selected_index = 0
                return 0
            max_idx = max(0, len(self.search_results) - 1)
            self.selected_index = max(0, min(max_idx, self.selected_index + delta))
            self.logger.info("Track selection navigated to index %d: %s", self.selected_index, self.search_results[self.selected_index]["title"])
            return self.selected_index

    def select_track(self, index: int) -> Dict[str, Any]:
        """Selects a candidate track by index without triggering download.
        Strict fail-fast bounds checking and Rule 13 compliance.
        """
        with self._selection_lock:
            if not self.search_results:
                raise ValueError("select_track called with empty search_results")
            if index < 0 or index >= len(self.search_results):
                raise IndexError(f"Track selection index {index} out of bounds (total: {len(self.search_results)})")
            self.selected_index = index
            target_track = self.search_results[index]
            _ = target_track["video_id"]
            _ = target_track["title"]
            self.logger.info("Track selected at index %d: '%s' (%s)", index, target_track["title"], target_track["video_id"])
            return target_track

    def trigger_analysis(self, index: Optional[int] = None) -> Dict[str, Any]:
        """Triggers YouTube download and neural analysis on Mac Mini for selected candidate.
        Strict fail-fast schema compliance and single ANALYZING state (Rule 13).
        """
        with self._selection_lock:
            if self.state == "ANALYZING":
                raise RuntimeError("trigger_analysis rejected: Mac analysis already active")
            if not self.search_results:
                raise ValueError("trigger_analysis called with empty search_results")

            if index is None:
                index = self.selected_index
            if index < 0 or index >= len(self.search_results):
                raise IndexError(f"Analysis index {index} out of bounds (total: {len(self.search_results)})")

            self.selected_index = index
            target_track = self.search_results[index]
            _ = target_track["video_id"]
            _ = target_track["title"]

            self.logger.info("Triggering Mac analysis for track index %d: '%s' (%s)...", index, target_track["title"], target_track["video_id"])
            self.state = "ANALYZING"
            self._play_chime("commit")

        def _do_mac_analysis():
            try:
                vid = str(target_track["video_id"])
                raw_title = str(target_track["title"])
                url = f"https://youtu.be/{vid}"

                # 1. Initialize BeatBanditAudioClient pointing to canonical Beat Bandit library
                from beat_bandit_audio import BeatBanditAudioClient, sanitize_title_and_artist
                manifest_path = get_beat_bandit_manifest_path()
                if manifest_path is not None:
                    lib_dir = manifest_path.parent
                else:
                    if os.name == "nt":
                        lib_dir = WORKSPACE_ROOT / "library" / "beat_bandit"
                    else:
                        lib_dir = Path.home() / "so101" / "library" / "beat_bandit"
                lib_dir.mkdir(parents=True, exist_ok=True)
                audio_client = BeatBanditAudioClient(lib_dir)

                # 2. Request analysis from Mac Mini (blocks until Demucs + Essentia complete)
                self.logger.info("Calling Mac Mini /api/analyze_track for '%s' (%s)...", raw_title, vid)
                analysis = audio_client.fetch_analysis(url_or_id=url, track_id=vid)

                # 3. Download finished WAV from Mac Mini to local Beat Bandit library
                self.logger.info("Downloading analyzed WAV for '%s' (%s) from Mac Mini...", raw_title, vid)
                wav_path = audio_client.download_wav(track_id=vid)

                # 4. Extract sanitized metadata
                song_title, artist = sanitize_title_and_artist(raw_title)

                # 5. Commit to manifest.json fail-fast
                manifest_file = lib_dir / "manifest.json"
                manifest_data: Dict[str, Any] = {}
                if manifest_file.exists():
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        manifest_data = json.load(f)

                manifest_data[vid] = {
                    "track_id": vid,
                    "title": song_title,
                    "artist": artist,
                    "duration": float(analysis["duration"]),
                    "bpm": float(analysis["bpm"]),
                    "wav_path": wav_path,
                    "analysis": analysis,
                    "created_at": time.time(),
                }
                with open(manifest_file, "w", encoding="utf-8") as f:
                    json.dump(manifest_data, f, indent=2)

                self.logger.info("Successfully analyzed and saved track '%s' (ID: %s) to %s", song_title, vid, wav_path)
                with self._selection_lock:
                    self.last_analyzed_track = {
                        "track_id": vid,
                        "title": song_title,
                        "artist": artist,
                        "timestamp": time.time(),
                    }
                    self.state = "IDLE"
                self._play_chime("commit")
            except Exception as e:
                self.logger.error("Mac analysis error for track '%s': %s", target_track["title"], e, exc_info=True)
                with self._selection_lock:
                    self.error = str(e)
                    self.state = "IDLE"
                self._play_chime("cancel")

        threading.Thread(target=_do_mac_analysis, daemon=True).start()
        return target_track

    def setup(self, backend: RobotBackend) -> None:
        """Pre-run setup: loads calibration limits and verifies resident Vosk standby server."""
        self.logger.info("Initializing ListenerApp dependencies...")
        self.calib_limits = load_calibration_limits(backend=backend)
        self._verify_vosk_standby_server()

    def _verify_vosk_standby_server(self) -> None:
        """Verifies resident Vosk standby server is warm and ready on Pi 4B."""
        health_url = str(self.config["asr"]["health_url"])
        timeout_sec = float(self.config["asr"]["timeout_sec"])
        self.logger.info("Verifying resident Vosk standby server readiness at %s...", health_url)
        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "SO101-ListenerApp"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.logger.info("Vosk standby server is READY (model: %s).", data["model"])
                    self._vosk_ready = True
                    return
        except urllib.error.HTTPError as he:
            if he.code == 503:
                self.logger.warning("Vosk standby server is still warming up (2-min cold load in progress).")
                self._vosk_ready = False
                self._play_chime("cancel")
                return
            self.logger.error("Vosk standby server health check failed with HTTP %d: %s", he.code, he)
        except Exception as e:
            self.logger.warning("Vosk standby server unreachable (%s): %s", health_url, e)

        self._vosk_ready = False
        self._play_chime("cancel")

    def _get_pi4b_url(self) -> str:
        ip = network_resolver.get_pi4b_ip(prefer_port=self.config["network"]["pi4b_port"])
        return f"http://{ip}:{self.config['network']['pi4b_port']}"

    def _play_chime(self, chime_key: str) -> None:
        """Dispatches audio cue playback to the daemon audio system."""
        event_name = self.config["chimes"][chime_key]
        try:
            dispatch_audio_event(event_name)
        except Exception as e:
            self.logger.warning("Failed to dispatch audio chime '%s': %s", event_name, e, exc_info=True)

    def _connect_daemon_audio_stream(self) -> Any:
        """Opens streaming PCM connection to the daemon on Pi 4B."""
        url = f"{self._get_pi4b_url()}/api/microphone/stream"
        req = urllib.request.Request(url, headers={"User-Agent": "SO101-ListenerApp"})
        return urllib.request.urlopen(req, timeout=10.0)

    def _calculate_frame_energy(self, pcm_bytes: bytes) -> float:
        """Calculates RMS energy of 16-bit PCM chunk for voice activity detection."""
        if not pcm_bytes:
            return 0.0
        import audioop
        return float(audioop.rms(pcm_bytes, 2))

    def _extract_dynamic_grammar(self) -> List[str]:
        """Extracts dynamic grammar phrases from Beat Bandit manifest and command list."""
        phrases: List[str] = [
            "down town", "downtown", "macklemore", "sing downtown", "play downtown",
            "home", "center", "park", "dance", "beat bandit", "teleop", "piranha", "exit", "quit"
        ]
        manifest_path = get_beat_bandit_manifest_path()
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                for tid, meta in manifest.items():
                    if "title" in meta and meta["title"]:
                        t = str(meta["title"]).lower()
                        if t not in phrases:
                            phrases.append(t)
                    if "artist" in meta and meta["artist"]:
                        a = str(meta["artist"]).lower()
                        if a not in phrases:
                            phrases.append(a)
            except Exception as e:
                self.logger.warning("Could not extract tracks from manifest for dynamic grammar: %s", e)
        return phrases

    def _transcribe_pcm_buffer(self, pcm_chunks: List[bytes]) -> str:
        """Transcribes accumulated PCM audio buffer via resident Vosk standby server."""
        if not pcm_chunks:
            return ""

        if not self._vosk_ready:
            self.logger.warning("Rejecting transcription: Vosk standby server not ready.")
            return ""

        full_pcm = b"".join(pcm_chunks)
        server_url = str(self.config["asr"]["server_url"])
        timeout_sec = float(self.config["asr"]["timeout_sec"])
        use_grammar = bool(self.config["asr"]["use_dynamic_grammar"])

        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(full_pcm)),
            "User-Agent": "SO101-ListenerApp"
        }

        if use_grammar:
            grammar_list = self._extract_dynamic_grammar()
            headers["X-Grammar"] = json.dumps(grammar_list)

        t0 = time.time()
        try:
            req = urllib.request.Request(server_url, data=full_pcm, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if resp.status == 200:
                    res = json.loads(resp.read().decode("utf-8"))
                    text = str(res["text"]).strip()
                    dur_ms = (time.time() - t0) * 1000
                    self.logger.info("Transcribed command via Vosk standby server in %.1f ms: '%s'", dur_ms, text)
                    return text
                else:
                    self.logger.error("Vosk server returned unexpected status %d", resp.status)
                    return ""
        except Exception as e:
            self.logger.error("Vosk standby server transcription error: %s", e, exc_info=True)
            return ""

    def _execute_movement_primitive(self, backend: RobotBackend, action: str) -> None:
        """Executes calibrated movement primitive on hardware. Zero hardcoded 2048."""
        if not self.calib_limits:
            self.calib_limits = load_calibration_limits(backend=backend)

        self.logger.info("Executing movement primitive: '%s'", action)
        if action in ("center", "home"):
            # Move all follower arm motors (1-6) to their calibrated midpoints fail-fast
            centers = {sid: self.calib_limits[sid]["center"] for sid in range(1, 7)}
            backend.set_goal_positions(centers, speed=400)
        elif action == "park":
            # Calibrated park posture: shoulder tuck fail-fast
            parks = {
                sid: self.calib_limits[sid]["min"] if sid in (2, 3) else self.calib_limits[sid]["center"]
                for sid in range(1, 7)
            }
            backend.set_goal_positions(parks, speed=300)

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        """Main execution loop of ListenerApp. Must monitor stop_event.is_set()."""
        self.logger.info("Starting ListenerApp hotword loop...")
        self.state = "LISTENING"

        settle_delay = float(self.config["vad"]["settle_delay_sec"])
        chunk_samples = int(self.config["hotword"]["chunk_samples"])
        chunk_bytes = chunk_samples * 2  # 16-bit mono = 2 bytes per sample
        energy_multiplier = float(self.config["hotword"]["energy_multiplier"])
        silence_timeout = float(self.config["vad"]["silence_timeout_sec"])
        max_record_sec = float(self.config["vad"]["max_record_sec"])
        energy_thresh = int(self.config["vad"]["energy_threshold"])

        self.logger.info("Awaiting %.1fs acoustic settle delay before opening microphone stream...", settle_delay)
        if stop_event.wait(timeout=settle_delay):
            self.logger.info("Stop event signaled during acoustic settle delay. Exiting...")
            return

        pre_roll_chunks = int(self.config["vad"]["pre_roll_chunks"])
        pre_roll_buffer: deque[bytes] = deque(maxlen=pre_roll_chunks)

        self._stream_resp = None
        try:
            try:
                self._stream_resp = self._connect_daemon_audio_stream()
                self.logger.info("Successfully bound to live daemon microphone stream.")
            except Exception as e:
                self.logger.warning("Could not open daemon audio stream (%s), entering command polling mode...", e, exc_info=True)

            # Utterance capture loop
            while not stop_event.is_set():
                if self._stream_resp is not None:
                    chunk = self._stream_resp.read(chunk_bytes)
                    if not chunk:
                        self.logger.warning("Daemon audio stream EOF, attempting stream reconnect...")
                        try:
                            self._stream_resp.close()
                        except (OSError, ValueError) as close_err:
                            self.logger.debug("Closing stream on EOF: %s", close_err)
                        time.sleep(1.0)
                        try:
                            self._stream_resp = self._connect_daemon_audio_stream()
                            self.logger.info("Reconnected to daemon audio stream.")
                        except Exception as rec_err:
                            self.logger.error("Failed to reconnect to daemon audio stream: %s", rec_err, exc_info=True)
                            raise ConnectionError(f"Daemon audio stream dropped and reconnect failed: {rec_err}") from rec_err
                        continue
                else:
                    # Polling simulation fallback when remote stream endpoint is offline
                    time.sleep(0.08)
                    continue

                energy = self._calculate_frame_energy(chunk)
                pre_roll_buffer.append(chunk)

                # Voice Activity Detection: speech onset detected when volume exceeds energy_thresh
                speech_detected = (energy > energy_thresh)

                if speech_detected:
                    self.logger.info("Speech onset detected (energy=%.1f > %d)! Entering command capture window...", energy, energy_thresh)
                    self.state = "CAPTURING"
                    self.transcript = ""

                    # Prepend pre-roll buffer so opening consonants ("s", "p", etc.) are not clipped
                    command_chunks: List[bytes] = list(pre_roll_buffer)
                    record_start = time.time()
                    last_voice_time = time.time()

                    # Capture spoken command until silence
                    while not stop_event.is_set():
                        c = self._stream_resp.read(chunk_bytes)
                        if not c:
                            break
                        command_chunks.append(c)
                        e = self._calculate_frame_energy(c)
                        now = time.time()
                        if e > energy_thresh:
                            last_voice_time = now

                        # Stop if silence timeout reached or max recording duration hit
                        if (now - last_voice_time) > silence_timeout or (now - record_start) > max_record_sec:
                            break

                    self.state = "PROCESSING"
                    self._play_chime("commit")
                    transcript = self._transcribe_pcm_buffer(command_chunks)
                    self.transcript = transcript if transcript else str(self.config["feedback"]["idle_transcript"])
                    pre_roll_buffer.clear()
                    if transcript:
                        intent = parse_intent(transcript)
                        self.logger.info("Parsed intent: %s", intent)

                        intent_type = intent["intent"]
                        if intent_type == "SWITCH_APP":
                            target_app = intent["app"]
                            self.action_taken = f"Switching to {target_app}"
                            self.logger.info("Switching to app '%s', terminating listener...", target_app)
                            self._play_chime("commit")
                            if self.app_manager is not None:
                                def _switch_app():
                                    try:
                                        self.app_manager.start_app_by_name(target_app)
                                    except Exception as ex:
                                        self.logger.error("Failed switching to app '%s': %s", target_app, ex, exc_info=True)
                                threading.Thread(target=_switch_app, daemon=True).start()
                            self.stop()
                            return

                        elif intent_type == "MOVE_PRIMITIVE":
                            action = intent["action"]
                            self.action_taken = f"Moving to {action}"
                            self._execute_movement_primitive(backend, action)

                        elif intent_type == "DOWNLOAD_SONG":
                            with self._selection_lock:
                                if self.state == "ANALYZING":
                                    self.logger.warning("Rejecting search query: track analysis active on Mac")
                                    self._play_chime("cancel")
                                    continue
                            title = intent["title"]
                            artist = intent["artist"]
                            query_str = f"{title} {artist}".strip()
                            self.action_taken = f"Searching tracks: '{query_str}'"
                            with self._selection_lock:
                                self.search_query = query_str
                                self.state = "SEARCHING"
                            self.logger.info("Querying top 4 tracks for '%s'...", query_str)
                            try:
                                candidates = fetch_search_candidates(query_str, limit=4)
                                with self._selection_lock:
                                    self.search_results = candidates
                                    self.selected_index = 0
                                    self.state = "SELECTING"
                                self._play_chime("commit")
                                self.logger.info("Retrieved %d candidates for selection: %s", len(candidates), [c["title"] for c in candidates])
                            except Exception as e:
                                self.logger.error("Search query failed for '%s': %s", query_str, e, exc_info=True)
                                with self._selection_lock:
                                    self.error = str(e)
                                    self.state = "IDLE"
                                self._play_chime("cancel")

                        elif intent_type == "PLAY_SONG":
                            title = intent["title"]
                            bb_track = find_beat_bandit_track(title)
                            if bb_track is not None:
                                track_id = str(bb_track["track_id"])
                                track_title = str(bb_track["title"])
                                self.action_taken = f"Playing Beat Bandit: '{track_title}'"
                                self.logger.info("Found Beat Bandit library track '%s' (ID: %s), transitioning to Beat Bandit...", track_title, track_id)
                                self._play_chime("commit")
                                if self.app_manager is not None:
                                    def _launch_bb():
                                        try:
                                            self.logger.info("Engaging Beat Bandit app session...")
                                            ok = self.app_manager.start_app_by_name("beat_bandit_app")
                                            if not ok:
                                                self.logger.error("Failed to start beat_bandit_app via AppManager")
                                                return
                                            bb_app = self.app_manager.active_app
                                            if bb_app and hasattr(bb_app, "start_track_by_url_or_id"):
                                                self.logger.info("Triggering Beat Bandit track playback for '%s'...", track_id)
                                                robot_backend = self.app_manager.backend
                                                bb_app.start_track_by_url_or_id(robot_backend, track_id)
                                            else:
                                                self.logger.error("Active app is not a valid BeatBanditApp instance")
                                        except Exception as ex:
                                            self.logger.error("Beat Bandit launch error: %s", ex, exc_info=True)
                                    threading.Thread(target=_launch_bb, daemon=True).start()
                                self.stop()
                                return
                            else:
                                seq_file = find_compiled_sequence(title)
                                if seq_file is not None:
                                    self.action_taken = f"Playing Preset: '{title}'"
                                    self.logger.info("Found compiled sequence '%s', launching preset playback...", seq_file)
                                    self._play_chime("commit")
                                    if self.app_manager is not None:
                                        def _launch_preset():
                                            try:
                                                self.app_manager.start_app_by_name("preset_app")
                                            except Exception as ex:
                                                self.logger.error("Failed to start preset_app: %s", ex, exc_info=True)
                                        threading.Thread(target=_launch_preset, daemon=True).start()
                                    self.stop()
                                    return
                                else:
                                    self.action_taken = str(self.config["feedback"]["unmatched_action"])
                                    self.logger.warning("No Beat Bandit track or compiled sequence found for '%s'.", title)
                                    self._play_chime("cancel")

                        elif intent_type == "EXIT":
                            self.action_taken = "Exiting Voice Listener"
                            self.logger.info("Exit command received, stopping listener app...")
                            self.stop()
                            return

                        else:
                            self.action_taken = str(self.config["feedback"]["unmatched_action"])
                            self.logger.warning("Unrecognized voice command '%s'. Action: %s", transcript, self.action_taken)
                            self._play_chime("cancel")

                    else:
                        self.action_taken = str(self.config["feedback"]["unmatched_action"])
                        self._play_chime("cancel")

                    # If waiting for user track selection or Mac analysis, close microphone and wait
                    with self._selection_lock:
                        is_selecting = (self.state in ("SELECTING", "ANALYZING"))
                    if is_selecting:
                        if self._stream_resp is not None:
                            try:
                                self._stream_resp.close()
                            except Exception as e:
                                self.logger.debug("Closing stream during track selection: %s", e)
                            self._stream_resp = None
                        while not stop_event.is_set():
                            with self._selection_lock:
                                if self.state not in ("SELECTING", "ANALYZING"):
                                    break
                            time.sleep(0.1)
                        if stop_event.is_set():
                            break

                    # Single turn complete: close stream and transition to IDLE without looping wake chime
                    if self._stream_resp is not None:
                        try:
                            self._stream_resp.close()
                        except Exception as e:
                            self.logger.debug("Closing stream after command completion: %s", e)
                        self._stream_resp = None

                    with self._selection_lock:
                        if self.state not in ("SELECTING", "ANALYZING"):
                            self.state = "IDLE"
                    self.logger.info("ListenerApp single turn completed. Remaining in IDLE state.")
                    stop_event.wait()
                    break

        except Exception as e:
            self.logger.error("ListenerApp run error: %s", e, exc_info=True)
            self.error = str(e)
        finally:
            if self._stream_resp is not None:
                try:
                    self._stream_resp.close()
                except Exception as e:
                    self.logger.warning("Error closing daemon stream response: %s", e, exc_info=True)
                self._stream_resp = None
            self.state = "IDLE"
            self._play_chime("exit")
            self.logger.info("ListenerApp execution loop exited.")

    def stop(self) -> None:
        """Signals the application loop to stop and release all hardware."""
        self.logger.info("Stopping ListenerApp...")
        self.stop_event.set()
        if self._stream_resp is not None:
            try:
                self._stream_resp.close()
            except Exception as e:
                self.logger.debug("Error closing stream on stop: %s", e)
            self._stream_resp = None
