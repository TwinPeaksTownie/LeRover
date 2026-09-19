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
import queue
import sys
import threading
import time
import urllib.request
import wave
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List
from websockets.sync.client import connect as ws_connect

APP_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = APP_DIR.parent.parent
PI4B_DIR = WORKSPACE_ROOT / "pi4b"
CONFIG_DIR = WORKSPACE_ROOT / "config"

for p in [WORKSPACE_ROOT, PI4B_DIR, CONFIG_DIR]:
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend, dispatch_audio_event
from telemetry_proxies import MOTOR_NAMES

import network_resolver
import audio_resolver

from apps.listener_app.intent_parser import parse_intent, strip_hallucinated_the
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
    _ = float(cfg["watchdog"]["retry_backoff_sec"])
    _ = int(cfg["watchdog"]["max_consecutive_resets"])
    _ = bool(cfg["execution"]["single_turn"])
    max_retries = int(cfg["execution"]["max_retries"])
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")
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
    post_settle_sec = float(cfg["vad"]["post_chime_settle_sec"])
    if post_settle_sec <= 0:
        raise ValueError("post_chime_settle_sec must be positive")
    _ = float(cfg["vad"]["silence_timeout_sec"])
    post_speech_silence_sec = float(cfg["vad"]["post_speech_silence_sec"])
    if post_speech_silence_sec <= 0:
        raise ValueError("post_speech_silence_sec must be positive")
    acoustic_decay_pad_sec = float(cfg["vad"]["acoustic_decay_pad_sec"])
    if acoustic_decay_pad_sec < 0:
        raise ValueError("acoustic_decay_pad_sec cannot be negative")
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
    _ = cfg["chimes"]["error"]
    _ = cfg["chimes"]["lost_life"]
    _ = cfg["chimes"]["cancel"]
    _ = cfg["chimes"]["exit"]
    _ = cfg["chimes"]["play_dead"]
    _ = str(cfg["feedback"]["unmatched_action"])
    _ = str(cfg["feedback"]["idle_action"])
    _ = str(cfg["feedback"]["idle_transcript"])
    _ = int(cfg["network"]["pi4b_port"])
    _ = int(cfg["network"]["mac_port"])
    _ = int(cfg["network"]["vosk_server_port"])
    _ = int(cfg["network"]["vosk_websocket_port"])
    _ = float(cfg["motion"]["interpolation_duration_sec"])
    _ = int(cfg["motion"]["interpolation_steps"])
    _ = str(cfg["motion"]["dead_posture"])
    return cfg


_CONFIG = load_listener_config()

DANCE_PRESETS_PATH_CANDIDATES = [
    WORKSPACE_ROOT / "apps" / "preset_app" / "presets" / "presets_dance.json",
    Path("/home/carson/touch_ui/apps/preset_app/presets/presets_dance.json"),
    Path("/home/user/so101/apps/preset_app/presets/presets_dance.json"),
]


def load_dance_presets() -> Dict[str, Any]:
    """Loads empirical dance presets fail-fast for physical voice posture execution."""
    target_path: Optional[Path] = None
    for p in DANCE_PRESETS_PATH_CANDIDATES:
        if p.exists():
            target_path = p
            break
    if target_path is None:
        raise FileNotFoundError(f"Missing required presets_dance.json. Checked: {DANCE_PRESETS_PATH_CANDIDATES}")

    with open(target_path, "r", encoding="utf-8") as f:
        presets = json.load(f)

    # Fail-fast validation of required posture entries
    for req_key in ["stand", "arch"]:
        if req_key not in presets:
            raise KeyError(f"presets_dance.json missing required posture '{req_key}'")
        if "normalized" not in presets[req_key]:
            raise KeyError(f"presets_dance.json posture '{req_key}' missing 'normalized' coordinates")

    if "sit" not in presets and "squat" not in presets:
        raise KeyError("presets_dance.json missing required 'sit' or 'squat' posture")

    if "tiptoe" not in presets and "tiptoes" not in presets:
        raise KeyError("presets_dance.json missing required 'tiptoe' or 'tiptoes' posture")

    return presets


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
        self._stream_lock = threading.Lock()
        self._stream_resp: Any = None
        self.app_manager: Any = None
        self.asr_model: Any = None
        self.kws_engine: Any = None
        self.calib_limits: Dict[int, Dict[str, int]] = {}
        self.dance_presets: Dict[str, Any] = {}
        self.last_analyzed_track: Optional[Dict[str, Any]] = None
        self._vosk_ready: bool = False
        self.single_turn: bool = bool(self.config["execution"]["single_turn"])
        self.start_listen_event = threading.Event()
        self.abort_listen_event = threading.Event()
        self.caller_app: Optional[str] = None

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
        """Pre-run setup: loads calibration limits, dance presets, and verifies resident Vosk standby server."""
        self.logger.info("Initializing ListenerApp dependencies...")
        self.calib_limits = load_calibration_limits(backend=backend)
        self.dance_presets = load_dance_presets()
        self._verify_vosk_standby_server()

    def _get_vosk_urls(self) -> Tuple[str, str, str]:
        """Dynamically resolves Vosk Standby Server HTTP health, WebSocket streaming, and HTTP recognize URLs."""
        server_port = int(self.config["network"]["vosk_server_port"])
        ws_port = int(self.config["network"]["vosk_websocket_port"])
        pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=server_port)
        health_url = f"http://{pi4b_ip}:{server_port}/health"
        ws_url = f"ws://{pi4b_ip}:{ws_port}"
        recognize_url = f"http://{pi4b_ip}:{server_port}/recognize"
        return health_url, ws_url, recognize_url

    def _verify_vosk_standby_server(self) -> None:
        """Verifies resident Vosk standby server is warm and ready on Pi 4B."""
        health_url, _, _ = self._get_vosk_urls()
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
        pi4b_ip = network_resolver.get_pi4b_ip(prefer_port=self.config["network"]["pi4b_port"])
        return f"http://{pi4b_ip}:{self.config['network']['pi4b_port']}"

    def _play_chime(self, chime_key: str, blocking: bool = False) -> float:
        """Dispatches audio cue playback to the daemon audio system and returns exact duration in seconds."""
        event_name = str(self.config["chimes"][chime_key])
        try:
            return audio_resolver.dispatch_audio_event(event_name, blocking=blocking)
        except Exception as e:
            self.logger.warning("Failed to dispatch audio chime '%s': %s", event_name, e, exc_info=True)
            return 0.0

    def _flush_stream(self, stream_resp: Any, drain_bytes: int = 3200) -> None:
        """Reads and discards initial bytes to flush startup transients or acoustic residues."""
        if stream_resp is None:
            return
        try:
            _ = stream_resp.read(drain_bytes)
        except Exception as e:
            self.logger.debug("Stream flush read note: %s", e)

    def _watchdog_cleanup(self) -> None:
        """Cleans up audio stream and re-verifies Vosk service connection with configured backoff."""
        self.logger.warning("Executing watchdog cleanup: closing stream and backing off before reconnect...")
        with self._stream_lock:
            if self._stream_resp is not None:
                try:
                    self._stream_resp.close()
                except Exception as e:
                    self.logger.warning("Failed to close stream response during watchdog cleanup: %s", e)
                self._stream_resp = None

        backoff_sec = float(self.config["watchdog"]["retry_backoff_sec"])
        time.sleep(backoff_sec)
        self._vosk_ready = False
        self._verify_vosk_standby_server()

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
            "stand up", "stand", "sit down", "sit", "tiptoes", "tiptoe", "play dead",
            "down town", "downtown", "macklemore", "sing downtown", "play downtown",
            "dance", "beat bandit", "teleop", "piranha", "exit", "quit"
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
        _, _, recognize_url = self._get_vosk_urls()
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
            req = urllib.request.Request(recognize_url, data=full_pcm, headers=headers, method="POST")
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

    def _execute_posture(self, backend: RobotBackend, action: str) -> None:
        """Executes calibrated posture on hardware via smooth cosine S-curve interpolation."""
        if not self.dance_presets:
            self.dance_presets = load_dance_presets()

        duration = float(self.config["motion"]["interpolation_duration_sec"])
        steps = int(self.config["motion"]["interpolation_steps"])

        self.logger.info("Executing posture action: '%s' (duration=%.1fs, steps=%d)", action, duration, steps)

        if action == "stand":
            backend.set_arm_torque(enable=True)
            target_norm = self.dance_presets["stand"]["normalized"]
            backend.interpolate_arm_norm(target_norm, duration=duration, steps=steps)
            self.action_taken = "Moved to stand"

        elif action == "sit":
            backend.set_arm_torque(enable=True)
            sit_key = "sit" if "sit" in self.dance_presets else "squat"
            target_norm = self.dance_presets[sit_key]["normalized"]
            backend.interpolate_arm_norm(target_norm, duration=duration, steps=steps)
            self.action_taken = "Moved to sit"

        elif action == "tiptoes":
            backend.set_arm_torque(enable=True)
            tiptoe_key = "tiptoe" if "tiptoe" in self.dance_presets else "tiptoes"
            target_norm = self.dance_presets[tiptoe_key]["normalized"]
            backend.interpolate_arm_norm(target_norm, duration=duration, steps=steps)
            self.action_taken = "Moved to tiptoes"

        elif action == "play_dead":
            backend.set_arm_torque(enable=True)
            dead_key = str(self.config["motion"]["dead_posture"])
            target_norm = self.dance_presets[dead_key]["normalized"]
            backend.interpolate_arm_norm(target_norm, duration=duration, steps=steps)
            backend.set_arm_torque(enable=False)
            self.action_taken = "Playing dead (torque relaxed)"
            self._play_chime("play_dead")

        else:
            raise KeyError(f"Unsupported posture action: '{action}'")

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        """Main execution loop of ListenerApp. Must monitor stop_event.is_set()."""
        self.logger.info("Starting ListenerApp loop...")

        settle_delay = float(self.config["vad"]["settle_delay_sec"])
        chunk_samples = int(self.config["hotword"]["chunk_samples"])
        chunk_bytes = chunk_samples * 2  # 16-bit mono = 2 bytes per sample
        energy_multiplier = float(self.config["hotword"]["energy_multiplier"])
        silence_timeout = float(self.config["vad"]["silence_timeout_sec"])
        max_record_sec = float(self.config["vad"]["max_record_sec"])
        energy_thresh = int(self.config["vad"]["energy_threshold"])
        pre_roll_chunks = int(self.config["vad"]["pre_roll_chunks"])
        post_settle_sec = float(self.config["vad"]["post_chime_settle_sec"])
        max_retries = int(self.config["execution"]["max_retries"])
        acoustic_decay_pad = float(self.config["vad"]["acoustic_decay_pad_sec"])
        post_speech_silence = float(self.config["vad"]["post_speech_silence_sec"])

        self._stream_resp = None

        try:
            while not stop_event.is_set() and not self.abort_listen_event.is_set():
                with self._selection_lock:
                    self.state = "IDLE"
                if not self.action_taken or self.action_taken == "Listening for voice command...":
                    self.action_taken = "Press Button B to speak"
                self.logger.info("ListenerApp in IDLE. Awaiting Button B single tap to start listening...")

                # 1. Await single Button B tap (or stop/abort)
                while not stop_event.is_set() and not self.abort_listen_event.is_set():
                    if self.start_listen_event.wait(timeout=0.1):
                        self.start_listen_event.clear()
                        break

                if stop_event.is_set() or self.abort_listen_event.is_set():
                    self.logger.info("Stop or abort signaled while in IDLE. Exiting ListenerApp...")
                    break

                attempt = 0
                command_executed = False
                turn_success = False

                while attempt <= max_retries and not stop_event.is_set() and not self.abort_listen_event.is_set():
                    if attempt == 0:
                        dur = self._play_chime("wake")
                    else:
                        dur = self._play_chime("error")
                        self.action_taken = f"Could not hear speech (retry {attempt}/{max_retries}). Speak now..."

                    # Exact audio delay based on WAV file length + decay pad
                    delay_wait = dur + acoustic_decay_pad
                    self.logger.info("Awaiting exact audio delay %.3fs (dur=%.3fs, pad=%.3fs) before mic capture (attempt %d/%d)...",
                                     delay_wait, dur, acoustic_decay_pad, attempt + 1, max_retries + 1)
                    if stop_event.wait(timeout=delay_wait) or self.abort_listen_event.is_set():
                        break

                    # Audio stream flush: close prior stream, connect fresh stream, and drain initial samples
                    with self._stream_lock:
                        if self._stream_resp is not None:
                            try:
                                self._stream_resp.close()
                            except Exception as e:
                                self.logger.warning("Failed to close previous stream response: %s", e)
                            self._stream_resp = None
                        try:
                            self._stream_resp = self._connect_daemon_audio_stream()
                            self._flush_stream(self._stream_resp, drain_bytes=3200)
                            self.logger.info("Fresh daemon microphone stream connected and flushed.")
                        except Exception as e:
                            self.logger.warning("Could not open daemon audio stream (%s), entering polling mode...", e, exc_info=True)

                    with self._selection_lock:
                        self.state = "LISTENING"
                    if attempt == 0:
                        self.action_taken = "Listening for voice command..."

                    pre_roll_buffer: deque[bytes] = deque(maxlen=pre_roll_chunks)
                    listen_start_time = time.time()
                    speech_detected = False

                    # Await speech onset
                    while not stop_event.is_set() and not self.abort_listen_event.is_set():
                        chunk = None
                        with self._stream_lock:
                            if self._stream_resp is not None:
                                try:
                                    chunk = self._stream_resp.read(chunk_bytes)
                                except Exception as r_err:
                                    self.logger.warning("Stream read error: %s", r_err)
                                    chunk = None

                        if chunk:
                            energy = self._calculate_frame_energy(chunk)
                            pre_roll_buffer.append(chunk)
                            if energy > energy_thresh:
                                speech_detected = True
                                break
                        else:
                            time.sleep(0.05)

                        if (time.time() - listen_start_time) > max_record_sec:
                            self.logger.info("No speech detected within %.1fs on attempt %d.", max_record_sec, attempt + 1)
                            break

                    if not speech_detected:
                        attempt += 1
                        continue

                    # Voice capture begins
                    self.logger.info("Speech onset detected (energy > %d)! Entering streaming capture window...", energy_thresh)
                    with self._selection_lock:
                        self.state = "CAPTURING"
                    self.transcript = ""

                    _, server_url, _ = self._get_vosk_urls()
                    ws_client = None
                    msg_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
                    stop_rx = threading.Event()
                    rx_thread: Optional[threading.Thread] = None

                    try:
                        ws_client = ws_connect(server_url, open_timeout=3.0)
                        try:
                            _ = ws_client.recv(timeout=1.0)
                        except Exception as ex_init:
                            self.logger.debug("Initial greeting read skipped: %s", ex_init)

                        def _rx_worker() -> None:
                            while not stop_rx.is_set():
                                try:
                                    if ws_client is None:
                                        break
                                    raw = ws_client.recv(timeout=0.1)
                                    msg = json.loads(raw)
                                    msg_queue.put(msg)
                                except TimeoutError:
                                    continue
                                except Exception as rx_err:
                                    self.logger.debug("WebSocket receiver terminated: %s", rx_err)
                                    break

                        rx_thread = threading.Thread(target=_rx_worker, daemon=True)
                        rx_thread.start()

                        for prc in pre_roll_buffer:
                            try:
                                ws_client.send(prc)
                            except Exception as pre_err:
                                self.logger.debug("Pre-roll send error: %s", pre_err)
                                break
                    except Exception as conn_err:
                        self.logger.warning("Could not establish streaming WebSocket session to %s: %s", server_url, conn_err)
                        ws_client = None

                    record_start = time.time()
                    last_voice_time = time.time()
                    complete_parts: List[str] = []
                    partial_text: str = ""
                    authoritative_transcript = ""

                    while not stop_event.is_set() and not self.abort_listen_event.is_set():
                        c = None
                        with self._stream_lock:
                            if self._stream_resp is not None:
                                try:
                                    c = self._stream_resp.read(chunk_bytes)
                                except Exception:
                                    c = None
                        if not c:
                            break

                        if ws_client is not None:
                            try:
                                ws_client.send(c)
                            except Exception as send_err:
                                self.logger.warning("WebSocket chunk send error: %s", send_err)

                        while not msg_queue.empty():
                            try:
                                m = msg_queue.get_nowait()
                                m_type = str(m["type"])
                                if m_type == "final":
                                    f_txt = str(m["text"]).strip()
                                    if f_txt:
                                        complete_parts.append(f_txt)
                                        partial_text = ""
                                elif m_type == "partial":
                                    partial_text = str(m["text"]).strip()
                                elif m_type == "final_result":
                                    authoritative_transcript = str(m["text"]).strip()

                                complete_clean = " ".join(complete_parts).strip()
                                partial_clean = partial_text.strip()
                                if complete_clean in partial_clean:
                                    combined = partial_clean
                                else:
                                    combined = f"{complete_clean} {partial_clean}".strip()

                                if combined:
                                    self.transcript = combined
                            except queue.Empty:
                                break

                        e = self._calculate_frame_energy(c)
                        now = time.time()
                        if e > energy_thresh:
                            last_voice_time = now

                        # Snappy silence detection
                        if (now - last_voice_time) > post_speech_silence or (now - record_start) > max_record_sec:
                            self.logger.info("Silence detected after speech (post-speech silence > %.2fs). Capturing complete.", post_speech_silence)
                            break

                    if stop_event.is_set() or self.abort_listen_event.is_set():
                        self.logger.info("Stop or abort signaled during capture.")
                        stop_rx.set()
                        if rx_thread is not None:
                            rx_thread.join(timeout=0.2)
                        if ws_client is not None:
                            try:
                                ws_client.close()
                            except Exception as e:
                                self.logger.warning("Failed to close Vosk websocket client on abort: %s", e)
                        break

                    # Silence detected: Sound 2 plays (commit chime: smw_midway_gate.wav)
                    with self._selection_lock:
                        self.state = "PROCESSING"
                    self._play_chime("commit")
                    pre_roll_buffer.clear()

                    # Settle Vosk service and await final transcription
                    if not authoritative_transcript and ws_client is not None:
                        try:
                            ws_client.send(json.dumps({"type": "final"}))
                            t_wait = time.time()
                            while (time.time() - t_wait) < 2.0:
                                try:
                                    m = msg_queue.get(timeout=0.2)
                                    if str(m["type"]) == "final_result":
                                        authoritative_transcript = str(m["text"]).strip()
                                        break
                                except queue.Empty:
                                    continue
                        except Exception as fin_err:
                            self.logger.warning("Error requesting final result: %s", fin_err)
                        finally:
                            stop_rx.set()
                            if rx_thread is not None:
                                rx_thread.join(timeout=0.5)
                            try:
                                ws_client.close()
                            except Exception as e:
                                self.logger.warning("Failed to close Vosk websocket client after final result: %s", e)
                    else:
                        stop_rx.set()
                        if rx_thread is not None:
                            rx_thread.join(timeout=0.5)
                        if ws_client is not None:
                            try:
                                ws_client.close()
                            except Exception as e:
                                self.logger.warning("Failed to close Vosk websocket client: %s", e)

                    if not authoritative_transcript:
                        complete_clean = " ".join(complete_parts).strip()
                        partial_clean = partial_text.strip()
                        if complete_clean in partial_clean:
                            authoritative_transcript = partial_clean
                        else:
                            authoritative_transcript = f"{complete_clean} {partial_clean}".strip()

                    transcript = strip_hallucinated_the(authoritative_transcript)
                    self.transcript = transcript if transcript else str(self.config["feedback"]["idle_transcript"])
                    self.logger.info("Finalized streaming transcript: '%s' (raw: '%s')", self.transcript, authoritative_transcript)

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

                        elif intent_type == "POSTURE":
                            action = intent["action"]
                            self._execute_posture(backend, action)
                            if action != "play_dead":
                                self._play_chime("commit")
                            command_executed = True
                            turn_success = True
                            break

                        elif intent_type == "DOWNLOAD_SONG":
                            with self._selection_lock:
                                if self.state == "ANALYZING":
                                    self.logger.warning("Rejecting search query: track analysis active on Mac")
                                    self._play_chime("cancel")
                                    break
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
                            command_executed = True
                            turn_success = True
                            break

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
                                    command_executed = True
                                    turn_success = True
                                    break

                        elif intent_type == "EXIT":
                            self.action_taken = "Exiting Voice Listener"
                            self.logger.info("Exit command received, stopping listener app...")
                            if self.caller_app and self.app_manager is not None:
                                caller = str(self.caller_app)
                                def _return_to_caller_exit():
                                    try:
                                        self.logger.info("Returning to caller app '%s' on exit...", caller)
                                        self.app_manager.start_app_by_name(caller)
                                    except Exception as ex:
                                        self.logger.error("Failed to return to caller app '%s': %s", caller, ex)
                                threading.Thread(target=_return_to_caller_exit, daemon=True).start()
                            self.stop()
                            return

                        else:
                            self.action_taken = str(self.config["feedback"]["unmatched_action"])
                            self.logger.warning("Unrecognized voice command '%s'. Action: %s", transcript, self.action_taken)
                            self._play_chime("cancel")
                            command_executed = True
                            turn_success = True
                            break
                    else:
                        self.logger.warning("Attempt %d/%d yielded empty/hallucinated transcript.", attempt + 1, max_retries + 1)
                        attempt += 1
                        if attempt > max_retries:
                            break

                if not turn_success and not stop_event.is_set() and not self.abort_listen_event.is_set():
                    self.logger.error("All %d attempts failed to capture valid speech. Triggering lose-a-life sound and watchdog reset...", max_retries + 1)
                    self.action_taken = "Voice capture failed. Resetting..."
                    dur = self._play_chime("lost_life")
                    time.sleep(dur + 0.1)
                    self._watchdog_cleanup()

                # 5. Clean up stream and handle track selection waiting
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

                if self._stream_resp is not None:
                    try:
                        self._stream_resp.close()
                    except (OSError, ValueError) as close_err:
                        self.logger.debug("Closing stream after command turn: %s", close_err)
                    self._stream_resp = None

                pre_roll_buffer.clear()

                if self.single_turn:
                    self.logger.info("Single-turn voice command completed. Terminating ListenerApp...")
                    if self.caller_app and self.app_manager is not None:
                        caller = str(self.caller_app)
                        def _return_to_caller():
                            try:
                                self.logger.info("Returning to caller app '%s'...", caller)
                                self.app_manager.start_app_by_name(caller)
                            except Exception as ex:
                                self.logger.error("Failed to return to caller app '%s': %s", caller, ex)
                        threading.Thread(target=_return_to_caller, daemon=True).start()
                    self.stop()
                    return

                # Multi-turn push-to-talk: post-turn acoustic cooldown then return to IDLE
                self.logger.info("Awaiting %.1fs post-turn acoustic cooldown...", post_settle_sec)
                if stop_event.wait(timeout=post_settle_sec):
                    self.logger.info("Stop event signaled during post-turn acoustic cooldown. Exiting...")
                    break

                with self._selection_lock:
                    self.state = "IDLE"
                if not self.action_taken.endswith("Press Button B to speak"):
                    self.action_taken = f"{self.action_taken}. Press Button B to speak"
                self.logger.info("Command turn completed. ListenerApp returned to IDLE state. Awaiting Button B.")

        except Exception as e:
            self.logger.error("ListenerApp run error: %s", e, exc_info=True)
            self.error = str(e)
        finally:
            with self._stream_lock:
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
        self.abort_listen_event.set()
        with self._stream_lock:
            if self._stream_resp is not None:
                try:
                    if hasattr(self._stream_resp, "fp") and self._stream_resp.fp is not None:
                        fp = self._stream_resp.fp
                        if hasattr(fp, "raw") and fp.raw is not None:
                            raw = fp.raw
                            if hasattr(raw, "_sock") and raw._sock is not None:
                                try:
                                    import socket
                                    raw._sock.shutdown(socket.SHUT_RDWR)
                                except OSError as e:
                                    self.logger.debug("Socket shutdown already completed: %s", e)
                    self._stream_resp.close()
                except Exception as e:
                    self.logger.debug("Error closing stream on stop: %s", e)
                self._stream_resp = None
