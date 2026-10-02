#!/usr/bin/env python3
"""apps/listener_app/app.py - Lean Voice Listener Coordinator for SO-101.

Coordinates the push-to-talk voice interface:
  IDLE -> Button B Tap -> AudioStreamClient & VAD -> VoskStreamingSession -> ActionDispatcher
Strict Open-Vocabulary Mode: Zero grammar compilation constraints.
Strict Fail-Fast schema compliance: Zero .get(k, default) fallbacks.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

APP_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = APP_DIR.parent.parent
PI4B_DIR = WORKSPACE_ROOT / "pi4b"
CONFIG_DIR = WORKSPACE_ROOT / "config"

for p in [WORKSPACE_ROOT, PI4B_DIR, CONFIG_DIR]:
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

from app_manager import BaseApp, AppMetadata
from robot_backend import RobotBackend
import audio_resolver

from apps.listener_app.intent_parser import parse_intent
from apps.listener_app.song_pipeline import load_dance_presets, load_calibration_limits
from apps.listener_app.audio_client import AudioStreamClient, VoiceActivityDetector
from apps.listener_app.vosk_client import VoskClient
from apps.listener_app.dispatcher import ActionDispatcher

CONFIG_PATH = APP_DIR / "config.json"
logger = logging.getLogger("so101.app.listener_app")


def load_listener_config() -> Dict[str, Any]:
    """Loads listener_app config with strict fail-fast validation."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing required ListenerApp config: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

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
    flush_bytes = int(cfg["vad"]["stream_flush_bytes"])
    if flush_bytes <= 0:
        raise ValueError("stream_flush_bytes must be positive")
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
    for alias_k, alias_v in cfg["posture_aliases"].items():
        _ = str(alias_k)
        _ = str(alias_v)
    return cfg


_CONFIG = load_listener_config()


class ListenerApp(BaseApp):
    """Thin coordinator for push-to-talk voice commands and application routing."""

    metadata = AppMetadata(
        name=_CONFIG["name"],
        title=_CONFIG["title"],
        description=_CONFIG["description"],
        version=_CONFIG["version"],
        icon=_CONFIG["icon"],
        tags=list(_CONFIG["tags"]),
    )

    def __init__(self, running_on_pi: bool = True, caller_app: Optional[str] = None) -> None:
        self.config = load_listener_config()
        self.metadata = AppMetadata(
            name=self.config["name"],
            title=self.config["title"],
            description=self.config["description"],
            version=self.config["version"],
            icon=self.config["icon"],
            tags=list(self.config["tags"]),
        )
        super().__init__(running_on_pi=running_on_pi)
        self.running_on_pi = running_on_pi
        self.caller_app = caller_app
        self.single_turn = bool(self.config["execution"]["single_turn"])

        # Modular Subsystems
        self.audio_client = AudioStreamClient(self.config)
        self.vad = VoiceActivityDetector(self.config)
        self.vosk_client = VoskClient(self.config)
        self.dispatcher = ActionDispatcher(self.config, lambda c, **kw: self._play_chime(c, **kw))

        # Synchronization & State
        self.state: str = "IDLE"
        self.transcript: str = str(self.config["feedback"]["idle_transcript"])
        self.action_taken: str = str(self.config["feedback"]["idle_action"])
        self.error: Optional[str] = None

        self.start_listen_event = threading.Event()
        self.abort_listen_event = threading.Event()
        self._selection_lock = threading.Lock()

        # Runtime Motor Limits & Presets
        self.calib_limits: Dict[int, Dict[str, int]] = {}
        self.dance_presets: Dict[str, Any] = {}

    @property
    def search_results(self) -> List[Dict[str, Any]]:
        return self.dispatcher.search_results

    @search_results.setter
    def search_results(self, val: List[Dict[str, Any]]) -> None:
        self.dispatcher.search_results = val

    @property
    def selected_index(self) -> int:
        return self.dispatcher.selected_index

    @selected_index.setter
    def selected_index(self, val: int) -> None:
        self.dispatcher.selected_index = val

    @property
    def search_query(self) -> str:
        return self.dispatcher.search_query

    @search_query.setter
    def search_query(self, val: str) -> None:
        self.dispatcher.search_query = val

    @property
    def last_analyzed_track(self) -> Optional[Dict[str, Any]]:
        return self.dispatcher.last_analyzed_track

    @last_analyzed_track.setter
    def last_analyzed_track(self, val: Optional[Dict[str, Any]]) -> None:
        self.dispatcher.last_analyzed_track = val

    def _play_chime(self, chime_key: str, blocking: bool = False) -> float:
        event_name = str(self.config["chimes"][chime_key])
        try:
            return audio_resolver.dispatch_audio_event(event_name, blocking=blocking)
        except Exception as e:
            logger.warning("Failed to dispatch audio chime '%s': %s", event_name, e)
            return 0.0

    def _get_pi4b_url(self) -> str:
        return self.audio_client._get_base_url()

    def _get_vosk_urls(self) -> tuple[str, str, str]:
        return self.vosk_client.health_url, self.vosk_client.ws_url, self.vosk_client.recognize_url

    def _execute_posture(self, backend: RobotBackend, action: str) -> None:
        self.dispatcher.execute_posture(backend, action, app=self)

    def select_track(self, index: int) -> Dict[str, Any]:
        return self.dispatcher.select_track(index, app=self)

    def navigate_selection(self, step: int) -> int:
        return self.dispatcher.navigate_selection(step, app=self)

    def cancel_selection(self) -> None:
        self.dispatcher.cancel_selection(app=self)

    def trigger_analysis(self, index: Optional[int] = None) -> Dict[str, Any]:
        return self.dispatcher.trigger_analysis(index, app=self)

    def get_status(self) -> Dict[str, Any]:
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

    def setup(self, backend: RobotBackend) -> None:
        logger.info("Initializing ListenerApp dependencies...")
        self.calib_limits = load_calibration_limits(backend=backend)
        self.dance_presets = load_dance_presets()
        if not self.vosk_client.verify_health():
            logger.warning("Vosk service not ready at startup, continuing in offline standby...")

    def run(self, backend: RobotBackend, stop_event: threading.Event) -> None:
        logger.info("Starting ListenerApp coordinator loop...")
        max_retries = int(self.config["execution"]["max_retries"])
        acoustic_pad = float(self.config["vad"]["acoustic_decay_pad_sec"])
        post_settle = float(self.config["vad"]["post_chime_settle_sec"])

        while not stop_event.is_set():
            with self._selection_lock:
                self.state = "IDLE"
            if not self.action_taken or self.action_taken == "Listening for voice command...":
                self.action_taken = "Press Button B to speak"
            logger.info("ListenerApp in IDLE. Awaiting Button B single tap...")

            # 1. Await Button B trigger
            while not stop_event.is_set():
                if self.start_listen_event.wait(timeout=0.1):
                    self.start_listen_event.clear()
                    break

            if stop_event.is_set():
                break

            attempt = 0
            turn_success = False

            # 2. Managed Speech Capture Loop
            while attempt <= max_retries and not stop_event.is_set() and not self.abort_listen_event.is_set():
                chime_kind = "wake" if attempt == 0 else "error"
                dur = self._play_chime(chime_kind, blocking=True)
                if attempt > 0:
                    self.action_taken = f"Could not hear speech (retry {attempt}/{max_retries}). Speak now..."

                if stop_event.wait(timeout=acoustic_pad) or self.abort_listen_event.is_set():
                    break

                with self._selection_lock:
                    self.state = "LISTENING"
                self.action_taken = "Listening for voice command..."

                stream_resp = None
                try:
                    stream_resp = self.audio_client.connect_stream()
                except Exception as sc_err:
                    logger.error("Failed to connect audio stream: %s", sc_err)
                    attempt += 1
                    continue

                session = self.vosk_client.create_session()
                captured = False
                try:
                    session.start()
                    captured = self.vad.capture_utterance(
                        stream_resp=stream_resp,
                        on_chunk=session.send_chunk,
                        on_speech_start=lambda: setattr(self, "state", "CAPTURING"),
                        stop_event=stop_event,
                        abort_event=self.abort_listen_event,
                    )
                except Exception as cap_err:
                    logger.error("Streaming capture error: %s", cap_err)
                finally:
                    self.audio_client.close_stream(stream_resp)

                if stop_event.is_set() or self.abort_listen_event.is_set():
                    session.finish()
                    break

                if captured:
                    with self._selection_lock:
                        self.state = "PROCESSING"
                    self._play_chime("commit")
                    transcript = session.finish()
                    if transcript:
                        self.transcript = transcript
                        logger.info("Finalized transcript: '%s'", self.transcript)
                        intent = parse_intent(transcript)
                        logger.info("Parsed intent: %s", intent)
                        handled = self.dispatcher.dispatch(intent, self, backend)
                        if handled:
                            turn_success = True
                            break
                    else:
                        logger.warning("Speech captured but transcript was empty (attempt %d/%d).",
                                       attempt + 1, max_retries + 1)
                        attempt += 1
                else:
                    logger.warning("VAD detected no speech (attempt %d/%d).", attempt + 1, max_retries + 1)
                    session.finish()
                    attempt += 1

            # 3. Handle Abort or Failed Turn
            if self.abort_listen_event.is_set():
                logger.info("Turn cancelled by user gesture.")
                self.action_taken = "Voice turn cancelled. Press Button B to speak"
                self.abort_listen_event.clear()
                self.start_listen_event.clear()
                with self._selection_lock:
                    self.state = "IDLE"
                continue

            if not turn_success and not stop_event.is_set():
                logger.warning("Voice turn failed. Playing lost-life chime...")
                self.action_taken = "Voice capture failed. Resetting..."
                dur = self._play_chime("lost_life")
                time.sleep(dur + 0.1)

            # 4. Handle Track Selection Pause
            with self._selection_lock:
                is_selecting = (self.state in ("SELECTING", "ANALYZING"))
            if is_selecting:
                while not stop_event.is_set():
                    with self._selection_lock:
                        if self.state not in ("SELECTING", "ANALYZING"):
                            break
                    if self.abort_listen_event.is_set():
                        self.cancel_selection()
                        self.abort_listen_event.clear()
                        break
                    time.sleep(0.1)
                if stop_event.is_set():
                    break

            if self.single_turn:
                self.stop()
                return

            if stop_event.wait(timeout=post_settle):
                break

            with self._selection_lock:
                self.state = "IDLE"
            if not self.action_taken.endswith("Press Button B to speak"):
                self.action_taken = f"{self.action_taken}. Press Button B to speak"
            self.abort_listen_event.clear()
            self.start_listen_event.clear()

    def stop(self) -> None:
        logger.info("Stopping ListenerApp...")
        super().stop()
        self.abort_listen_event.set()
