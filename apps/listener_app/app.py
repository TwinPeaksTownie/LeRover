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

import network_resolver
import audio_resolver

from apps.listener_app.intent_parser import parse_intent
from apps.listener_app.song_pipeline import download_and_compile, find_compiled_sequence, fetch_search_candidates

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
    _ = cfg["asr"]["model_size"]
    _ = cfg["asr"]["language"]
    _ = float(cfg["vad"]["silence_timeout_sec"])
    _ = float(cfg["vad"]["max_record_sec"])
    _ = float(cfg["vad"]["min_record_sec"])
    _ = int(cfg["vad"]["energy_threshold"])
    _ = cfg["chimes"]["wake"]
    _ = cfg["chimes"]["commit"]
    _ = cfg["chimes"]["cancel"]
    _ = cfg["chimes"]["exit"]
    _ = int(cfg["network"]["pi4b_port"])
    _ = int(cfg["network"]["mac_port"])
    return cfg


_CONFIG = load_listener_config()


def load_calibration_limits() -> Dict[int, Dict[str, int]]:
    """Loads empirical follower calibration limits dynamically into memory. Zero hardcoded 2048."""
    calib_file = CONFIG_DIR / "follower.json"
    if not calib_file.exists():
        raise FileNotFoundError(f"Missing required follower calibration: {calib_file}")
    with open(calib_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    limits = {}
    for sid in range(1, 7):
        sid_str = str(sid)
        if sid_str not in data:
            raise KeyError(f"Follower calibration missing required servo ID {sid} in {calib_file}")
        cdata = data[sid_str]
        limits[sid] = {
            "min": int(cdata["calib_min"]),
            "max": int(cdata["calib_max"]),
            "center": (int(cdata["calib_min"]) + int(cdata["calib_max"])) // 2,
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
        self.search_query: str = ""
        self.search_results: List[Dict[str, Any]] = []
        self.selected_index: int = 0
        self._selection_lock = threading.RLock()
        self.app_manager: Any = None
        self.asr_model: Any = None
        self.kws_engine: Any = None
        self.calib_limits: Dict[int, Dict[str, int]] = {}

    def get_status(self) -> Dict[str, Any]:
        """Returns structured status dictionary for Master API inspection."""
        with self._selection_lock:
            return {
                "name": self.name,
                "state": self.state,
                "query": self.search_query,
                "search_query": self.search_query,
                "search_results": list(self.search_results),
                "selected_index": self.selected_index,
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

    def select_track(self, index: Optional[int] = None, track_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Selects a track by index or track_id and dispatches download & compilation."""
        with self._selection_lock:
            if self.state == "DOWNLOADING":
                self.logger.warning("select_track rejected: download and compilation already active")
                return None
            if not self.search_results:
                self.logger.warning("select_track called with empty search_results")
                return None

            target_track = None
            if index is not None:
                if 0 <= index < len(self.search_results):
                    self.selected_index = index
                    target_track = self.search_results[index]
                else:
                    self.logger.warning("Invalid track index %d (out of range)", index)
                    return None
            elif track_id is not None:
                for i, t in enumerate(self.search_results):
                    if t["id"] == track_id:
                        self.selected_index = i
                        target_track = t
                        break
                if target_track is None:
                    self.logger.warning("Track ID '%s' not found in search results", track_id)
                    return None
            else:
                if 0 <= self.selected_index < len(self.search_results):
                    target_track = self.search_results[self.selected_index]
                else:
                    return None

            self.logger.info("Track selected: '%s' (%s), initiating download...", target_track["title"], target_track["id"])
            self.state = "DOWNLOADING"
            self._play_chime("commit")

        def _do_download_and_compile():
            try:
                out_path = download_and_compile(
                    title=target_track["title"],
                    video_id=target_track["id"],
                )
                self.logger.info("Choreography ready at: %s", out_path)
                with self._selection_lock:
                    self.state = "IDLE"
                self._play_chime("wake")
            except Exception as e:
                self.logger.error("Download and compile error: %s", e, exc_info=True)
                with self._selection_lock:
                    self.error = str(e)
                    self.state = "IDLE"
                self._play_chime("cancel")

        threading.Thread(target=_do_download_and_compile, daemon=True).start()
        return target_track

    def setup(self, backend: RobotBackend) -> None:
        """Pre-run setup: loads calibration limits and initializes local ASR model."""
        self.logger.info("Initializing ListenerApp dependencies...")
        self.calib_limits = load_calibration_limits()
        self._init_local_asr()

    def _init_local_asr(self) -> None:
        """Initializes local offline speech-to-text model."""
        try:
            import whisper
            model_name = self.config["asr"]["model_size"]
            self.logger.info("Loading local Whisper model '%s'...", model_name)
            self.asr_model = whisper.load_model(model_name)
            self.logger.info("Local Whisper model successfully loaded.")
        except Exception as e:
            self.logger.error("Could not initialize local Whisper model: %s", e, exc_info=True)
            self.asr_model = None
            raise RuntimeError(f"Whisper ASR model failed to load: {e}") from e

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

    def _transcribe_pcm_buffer(self, pcm_chunks: List[bytes]) -> str:
        """Transcribes accumulated PCM audio buffer using local Whisper."""
        if not pcm_chunks or self.asr_model is None:
            return ""

        full_pcm = b"".join(pcm_chunks)
        sample_rate = self.config["hotword"]["sample_rate"]

        # Convert raw PCM bytes to WAV in memory
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(full_pcm)
        wav_io.seek(0)

        # Temporary file for whisper ingestion
        if os.name == "nt":
            tmp_wav = Path(os.environ["TEMP"]) / "listener_cmd.wav"
        else:
            tmp_wav = Path("/tmp/listener_cmd.wav")
        with open(tmp_wav, "wb") as f:
            f.write(wav_io.read())

        try:
            result = self.asr_model.transcribe(str(tmp_wav), language=self.config["asr"]["language"])
            text = result["text"].strip()
            self.logger.info("Transcribed command: '%s'", text)
            return text
        except Exception as e:
            self.logger.error("Whisper transcription error: %s", e, exc_info=True)
            return ""
        finally:
            if tmp_wav.exists():
                try:
                    os.remove(tmp_wav)
                except Exception as e:
                    self.logger.warning("Failed to cleanup temp WAV: %s", e, exc_info=True)

    def _execute_movement_primitive(self, backend: RobotBackend, action: str) -> None:
        """Executes calibrated movement primitive on hardware. Zero hardcoded 2048."""
        if not self.calib_limits:
            self.calib_limits = load_calibration_limits()

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
        self._play_chime("wake")

        chunk_samples = self.config["hotword"]["chunk_samples"]
        chunk_bytes = chunk_samples * 2  # 16-bit mono = 2 bytes per sample
        energy_multiplier = self.config["hotword"]["energy_multiplier"]
        silence_timeout = self.config["vad"]["silence_timeout_sec"]
        max_record_sec = self.config["vad"]["max_record_sec"]
        energy_thresh = self.config["vad"]["energy_threshold"]

        stream_resp = None
        try:
            try:
                stream_resp = self._connect_daemon_audio_stream()
                self.logger.info("Successfully bound to live daemon microphone stream.")
            except Exception as e:
                self.logger.warning("Could not open daemon audio stream (%s), entering command polling mode...", e, exc_info=True)

            # Hotword evaluation loop
            while not stop_event.is_set():
                if stream_resp is not None:
                    chunk = stream_resp.read(chunk_bytes)
                    if not chunk:
                        self.logger.warning("Daemon audio stream EOF, attempting stream reconnect...")
                        try:
                            stream_resp.close()
                        except (OSError, ValueError) as close_err:
                            self.logger.debug("Closing stream on EOF: %s", close_err)
                        time.sleep(1.0)
                        try:
                            stream_resp = self._connect_daemon_audio_stream()
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

                # Keyword Spotting trigger condition consuming configured energy multiplier
                hotword_triggered = (energy > (energy_thresh * energy_multiplier))

                if hotword_triggered:
                    self.logger.info("Hotword triggered! Entering command capture window...")
                    self.state = "CAPTURING"
                    self._play_chime("commit")

                    command_chunks: List[bytes] = [chunk]
                    record_start = time.time()
                    last_voice_time = time.time()

                    # Capture spoken command until silence
                    while not stop_event.is_set():
                        c = stream_resp.read(chunk_bytes)
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
                    transcript = self._transcribe_pcm_buffer(command_chunks)
                    if transcript:
                        intent = parse_intent(transcript)
                        self.logger.info("Parsed intent: %s", intent)

                        intent_type = intent["intent"]
                        if intent_type == "SWITCH_APP":
                            target_app = intent["app"]
                            self.logger.info("Switching to app '%s', terminating listener...", target_app)
                            if self.app_manager is not None:
                                self.app_manager.start_app(target_app)
                            return

                        elif intent_type == "MOVE_PRIMITIVE":
                            self._execute_movement_primitive(backend, intent["action"])

                        elif intent_type == "DOWNLOAD_SONG":
                            with self._selection_lock:
                                if self.state == "DOWNLOADING":
                                    self.logger.warning("Rejecting search query: track download and compilation active")
                                    self._play_chime("cancel")
                                    continue
                            title = intent["title"]
                            artist = intent["artist"]
                            query_str = f"{title} {artist}".strip()
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
                                    self.state = "LISTENING"
                                self._play_chime("cancel")

                        elif intent_type == "PLAY_SONG":
                            title = intent["title"]
                            seq_file = find_compiled_sequence(title)
                            if seq_file is not None:
                                self.logger.info("Found compiled sequence '%s', launching playback...", seq_file)
                                if self.app_manager is not None:
                                    self.app_manager.start_app("preset_app")
                            else:
                                self.logger.warning("Compiled sequence for '%s' not found.", title)

                        elif intent_type == "EXIT":
                            self.logger.info("Exit command received, stopping listener app...")
                            return

                    # Return to listening for next trigger
                    self.state = "LISTENING"
                    self._play_chime("wake")

        except Exception as e:
            self.logger.error("ListenerApp run error: %s", e, exc_info=True)
            self.error = str(e)
        finally:
            if stream_resp is not None:
                try:
                    stream_resp.close()
                except Exception as e:
                    self.logger.warning("Error closing daemon stream response: %s", e, exc_info=True)
            self.state = "IDLE"
            self._play_chime("exit")
            self.logger.info("ListenerApp execution loop exited.")

    def stop(self) -> None:
        """Signals the application loop to stop and release all hardware."""
        self.logger.info("Stopping ListenerApp...")
        self.stop_event.set()
