#!/usr/bin/env python3
"""apps/listener_app/vosk_client.py - Native WebSocket Streaming ASR Client for Vosk.

Provides:
  1. VoskStreamingSession: Manages real-time WebSocket connection (ws://127.0.0.1:2700),
     pushing PCM audio chunks incrementally, draining interim transcripts in a background thread,
     and finalizing clean transcripts.
  2. VoskClient: Factory for creating streaming sessions and verifying service health.

Rule: Open vocabulary mode - strictly NO grammar constraints.
Strict Fail-Fast schema compliance: Zero .get(k, default) fallbacks.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List

from websockets.sync.client import connect as ws_connect
from apps.listener_app.intent_parser import strip_hallucinated_the

logger = logging.getLogger("so101.listener_app.vosk_client")


class VoskStreamingSession:
    """Encapsulates an active WebSocket streaming recognition session with Vosk."""

    def __init__(self, ws_url: str, timeout_sec: float = 5.0, drain_timeout_sec: float = 2.0) -> None:
        self.ws_url = ws_url
        self.timeout_sec = timeout_sec
        self.drain_timeout_sec = drain_timeout_sec
        self.ws_client = None
        self._rx_thread: Optional[threading.Thread] = None
        self._stop_rx = threading.Event()
        self._complete_parts: List[str] = []
        self._authoritative_transcript: str = ""
        self._interim_transcript: str = ""
        self._final_result_event = threading.Event()
        self._msg_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
        self._lock = threading.Lock()

    def start(self) -> VoskStreamingSession:
        """Connects to Vosk WebSocket service and spawns background message receiver."""
        logger.info("Opening Vosk streaming WebSocket session: %s", self.ws_url)
        self.ws_client = ws_connect(self.ws_url, open_timeout=self.timeout_sec)

        # Read optional initial connection greeting if available
        try:
            greeting = self.ws_client.recv(timeout=0.5)
            logger.debug("Vosk session initial greeting: %s", greeting)
        except TimeoutError:
            logger.debug("No immediate greeting packet from Vosk server.")
        except Exception as e:
            logger.debug("Handshake read non-fatal exception: %s", e)

        self._stop_rx.clear()
        self._rx_thread = threading.Thread(target=self._rx_worker, daemon=True)
        self._rx_thread.start()
        return self

    def _rx_worker(self) -> None:
        """Drains incoming JSON messages from Vosk WebSocket continuously."""
        while not self._stop_rx.is_set():
            if self.ws_client is None:
                break
            try:
                raw_msg = self.ws_client.recv(timeout=0.2)
                if not raw_msg:
                    continue
                data = json.loads(raw_msg)
                self._msg_queue.put(data)

                if "type" in data:
                    msg_type = str(data["type"])
                    if msg_type == "final":
                        if "text" in data:
                            part = str(data["text"]).strip()
                            if part:
                                with self._lock:
                                    self._complete_parts.append(part)
                                    self._interim_transcript = ""
                    elif msg_type == "final_result":
                        if "text" in data:
                            part = str(data["text"]).strip()
                            with self._lock:
                                self._authoritative_transcript = part
                                self._final_result_event.set()
                    elif msg_type == "partial":
                        part = ""
                        if "text" in data:
                            part = str(data["text"]).strip()
                        elif "partial" in data:
                            part = str(data["partial"]).strip()
                        if part:
                            with self._lock:
                                self._interim_transcript = part
                elif "partial" in data:
                    part = str(data["partial"]).strip()
                    if part:
                        with self._lock:
                            self._interim_transcript = part
                elif "text" in data:
                    part = str(data["text"]).strip()
                    if part:
                        with self._lock:
                            self._authoritative_transcript = part
                            self._final_result_event.set()
            except TimeoutError:
                continue
            except Exception as e_rx:
                if not self._stop_rx.is_set():
                    logger.debug("Vosk rx thread closed: %s", e_rx)
                break

    def send_chunk(self, chunk: bytes) -> None:
        """Pushes raw PCM binary chunk to the active WebSocket stream."""
        if not chunk or self.ws_client is None:
            return
        try:
            self.ws_client.send(chunk)
        except Exception as se:
            logger.warning("Failed to send chunk to Vosk WebSocket: %s", se)

    def get_interim_transcript(self) -> str:
        """Returns the current live partial transcript strictly for UI feedback."""
        with self._lock:
            return self._interim_transcript

    def finish(self, drain_timeout_sec: Optional[float] = None) -> str:
        """Signals end of stream, awaits authoritative final_result, and closes connection."""
        timeout = self.drain_timeout_sec if drain_timeout_sec is None else float(drain_timeout_sec)
        logger.info("Finalizing Vosk streaming session (drain timeout: %.2fs)...", timeout)
        if self.ws_client is not None:
            try:
                self.ws_client.send(json.dumps({"type": "final"}))
            except Exception as fe:
                logger.debug("Failed sending final marker to Vosk: %s", fe)

        # Await authoritative final_result event up to timeout
        signaled = self._final_result_event.wait(timeout=timeout)
        if not signaled:
            logger.warning("Vosk final_result timed out after %.2fs", timeout)

        self._stop_rx.set()
        if self._rx_thread is not None and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=0.5)

        if self.ws_client is not None:
            try:
                self.ws_client.close()
            except Exception as ce:
                logger.debug("Error closing Vosk WebSocket: %s", ce)
            self.ws_client = None

        with self._lock:
            parts = [p for p in self._complete_parts if p]
            if self._authoritative_transcript:
                parts.append(self._authoritative_transcript)
            raw_text = " ".join(parts).strip()
            # UNDER ZERO CIRCUMSTANCES DO WE FALL BACK TO _interim_transcript!
            # Premature live guesses are discarded.

        cleaned = strip_hallucinated_the(raw_text)
        logger.info("Vosk streaming recognized authoritative raw: '%s' (cleaned: '%s')", raw_text, cleaned)
        return cleaned

    def __enter__(self) -> VoskStreamingSession:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.ws_client is not None:
            self.finish()


class VoskClient:
    """Manages Vosk server configuration, health checks, and session creation."""

    def __init__(self, config: Dict[str, Any], host: str = "127.0.0.1") -> None:
        self.config = config
        self.host = host
        self.ws_port = int(self.config["network"]["vosk_websocket_port"])
        self.http_port = int(self.config["network"]["vosk_server_port"])
        self.ws_url = f"ws://{self.host}:{self.ws_port}"
        self.health_url = f"http://{self.host}:{self.http_port}/health"
        self.recognize_url = f"http://{self.host}:{self.http_port}/recognize"
        self.timeout_sec = float(self.config["asr"]["timeout_sec"])
        self.drain_timeout_sec = float(self.config["asr"]["drain_timeout_sec"])
        self.use_dynamic_grammar = bool(self.config["asr"]["use_dynamic_grammar"])

    def verify_health(self) -> bool:
        """Verifies that the resident Vosk server is healthy and ready."""
        try:
            req = urllib.request.Request(self.health_url)
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data["status"] == "ready"
                return False
        except Exception as e:
            logger.warning("Vosk health check failed: %s", e)
            return False

    def create_session(self) -> VoskStreamingSession:
        """Creates a new streaming WebSocket session."""
        return VoskStreamingSession(
            self.ws_url,
            timeout_sec=self.timeout_sec,
            drain_timeout_sec=self.drain_timeout_sec,
        )

    # Compatibility alias for batch calls if needed
    def recognize(self, audio_data: bytes, grammar: Optional[Any] = None) -> str:
        """Synchronous batch recognition via HTTP POST /recognize (fallback)."""
        if not audio_data:
            return ""
        headers = {
            "Content-Type": "audio/x-raw;format=s16le;rate=16000;channels=1",
            "Content-Length": str(len(audio_data)),
        }
        req = urllib.request.Request(self.recognize_url, data=audio_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                if resp.status == 200:
                    res_body = json.loads(resp.read().decode("utf-8"))
                    raw_text = str(res_body["text"]).strip()
                    return strip_hallucinated_the(raw_text)
                raise RuntimeError(f"Vosk /recognize returned unexpected status: {resp.status}")
        except Exception as e:
            logger.error("Vosk recognition request failed: %s", e)
            raise RuntimeError(f"Vosk recognition failed: {e}") from e
