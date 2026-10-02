#!/usr/bin/env python3
"""apps/listener_app/audio_client.py - Real-Time Audio Stream Transport & Dynamic VAD.

Provides:
  1. AudioStreamClient: Connects to HTTP streaming socket (GET /api/microphone/stream)
     and performs clean socket shutdown to avoid BrokenPipeError.
  2. VoiceActivityDetector: Evaluates frame RMS energy, manages circular pre-roll ring buffer,
     detects speech onset, and endpoints dynamically upon silence (sub-second latency).

Strict Fail-Fast schema compliance: Zero .get(k, default) fallbacks.
"""

from __future__ import annotations

import collections
import logging
import socket
import struct
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, Callable, Deque

logger = logging.getLogger("so101.listener_app.audio_client")


class AudioStreamClient:
    """Manages HTTP streaming socket connection to the master Pi 4B microphone daemon."""

    def __init__(self, config: Dict[str, Any], pi4b_ip_override: Optional[str] = None) -> None:
        self.config = config
        self.pi4b_port = int(self.config["network"]["pi4b_port"])
        self.pi4b_ip_override = pi4b_ip_override
        self.chunk_samples = int(self.config["hotword"]["chunk_samples"])
        self.chunk_bytes = self.chunk_samples * 2  # 16-bit mono PCM = 2 bytes per sample

    def _get_base_url(self) -> str:
        if self.pi4b_ip_override:
            ip = self.pi4b_ip_override
        else:
            import network_resolver
            ip = network_resolver.get_pi4b_ip(prefer_port=self.pi4b_port)
        return f"http://{ip}:{self.pi4b_port}"

    def get_stream_url(self) -> str:
        return f"{self._get_base_url()}/api/microphone/stream"

    def connect_stream(self, timeout_sec: float = 5.0):
        """Connects to the persistent HTTP audio stream on Pi 4B."""
        url = self.get_stream_url()
        logger.info("Connecting to microphone audio stream: %s (chunk_bytes=%d)", url, self.chunk_bytes)
        req = urllib.request.Request(url, headers={"User-Agent": "SO101-ListenerApp/1.0"})
        resp = urllib.request.urlopen(req, timeout=timeout_sec)
        return resp

    def close_stream(self, stream_resp) -> None:
        """Safely shuts down underlying socket and closes response."""
        if stream_resp is None:
            return
        try:
            if hasattr(stream_resp, "fp") and stream_resp.fp is not None:
                fp = stream_resp.fp
                if hasattr(fp, "raw") and fp.raw is not None:
                    if hasattr(fp.raw, "_sock") and fp.raw._sock is not None:
                        raw_sock = fp.raw._sock
                        try:
                            raw_sock.shutdown(socket.SHUT_RDWR)
                        except OSError as se:
                            logger.debug("Socket already shut down: %s", se)
            stream_resp.close()
            logger.info("Microphone audio stream closed cleanly.")
        except Exception as e:
            logger.debug("Exception closing audio stream: %s", e)


class VoiceActivityDetector:
    """Evaluates acoustic energy and enforces dynamic pre-roll and silence endpointing."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.chunk_samples = int(self.config["hotword"]["chunk_samples"])
        self.chunk_bytes = self.chunk_samples * 2
        self.settle_delay_sec = float(self.config["vad"]["settle_delay_sec"])
        self.silence_timeout_sec = float(self.config["vad"]["silence_timeout_sec"])
        self.post_speech_silence_sec = float(self.config["vad"]["post_speech_silence_sec"])
        self.max_record_sec = float(self.config["vad"]["max_record_sec"])
        self.min_record_sec = float(self.config["vad"]["min_record_sec"])
        self.energy_threshold = int(self.config["vad"]["energy_threshold"])
        self.sustain_energy_threshold = int(self.config["vad"]["sustain_energy_threshold"])
        self.min_utterance_chunks = int(self.config["vad"]["min_utterance_chunks"])
        self.pre_roll_chunks = int(self.config["vad"]["pre_roll_chunks"])
        self.stream_flush_bytes = int(self.config["vad"]["stream_flush_bytes"])

    @staticmethod
    def calculate_frame_energy(chunk: bytes) -> int:
        """Computes mathematical Root Mean Square (RMS) energy on 16-bit mono PCM."""
        if not chunk:
            return 0
        count = len(chunk) // 2
        if count == 0:
            return 0
        shorts = struct.unpack(f"{count}h", chunk[:count * 2])
        return int((sum(s * s for s in shorts) / count) ** 0.5)

    def capture_utterance(
        self,
        stream_resp,
        on_chunk: Callable[[bytes], None],
        on_speech_start: Optional[Callable[[], None]] = None,
        stop_event: Optional[Any] = None,
        abort_event: Optional[Any] = None,
    ) -> bool:
        """Executes streaming VAD: pre-roll buffering, significant utterance qualification, and 0.85s silence endpointing.
        Returns True if a speech utterance was successfully captured, False if timed out or aborted.
        """
        # 1. Flush stale buffered bytes from the stream pipe
        if self.stream_flush_bytes > 0:
            try:
                _ = stream_resp.read(self.stream_flush_bytes)
            except Exception as fe:
                logger.debug("Stream flush read: %s", fe)

        pre_roll_buffer: Deque[bytes] = collections.deque(maxlen=self.pre_roll_chunks)
        start_time = time.time()
        speech_detected = False
        consecutive_voice_chunks = 0

        # Phase 1: Await significant speech utterance while maintaining pre-roll buffer
        while True:
            if stop_event is not None and stop_event.is_set():
                return False
            if abort_event is not None and abort_event.is_set():
                return False

            if (time.time() - start_time) > self.silence_timeout_sec:
                logger.info("Speech onset timed out after %.2fs of silence.", self.silence_timeout_sec)
                return False

            try:
                chunk = stream_resp.read(self.chunk_bytes)
            except Exception as r_err:
                logger.warning("Error reading stream chunk during onset phase: %s", r_err)
                return False

            if not chunk or len(chunk) < self.chunk_bytes:
                time.sleep(0.01)
                continue

            energy = self.calculate_frame_energy(chunk)
            pre_roll_buffer.append(chunk)

            if energy > self.energy_threshold:
                consecutive_voice_chunks += 1
                if consecutive_voice_chunks >= self.min_utterance_chunks:
                    logger.info("Significant speech utterance detected (RMS energy %d > %d threshold, %d consecutive chunks). Entering capture window...",
                                energy, self.energy_threshold, consecutive_voice_chunks)
                    speech_detected = True
                    break
            else:
                consecutive_voice_chunks = 0

        if not speech_detected:
            return False

        if on_speech_start is not None:
            on_speech_start()

        # Phase 2: Flush pre-roll buffer into consumer, then stream live chunks until 0.85s post-utterance silence
        for prc in pre_roll_buffer:
            on_chunk(prc)

        record_start = time.time()
        last_voice_time = record_start

        while True:
            if stop_event is not None and stop_event.is_set():
                return False
            if abort_event is not None and abort_event.is_set():
                return False

            now = time.time()
            total_elapsed = now - record_start
            silence_elapsed = now - last_voice_time

            # Dynamic 0.85s silence endpointing strictly after significant utterance
            if silence_elapsed > self.post_speech_silence_sec and total_elapsed >= self.min_record_sec:
                logger.info("Silence detected after speech (silence=%.2fs > %.2fs, total=%.2fs). Capture complete.",
                            silence_elapsed, self.post_speech_silence_sec, total_elapsed)
                return True

            if total_elapsed >= self.max_record_sec:
                logger.info("Max recording duration (%.1fs) reached. Capture complete.", self.max_record_sec)
                return True

            try:
                chunk = stream_resp.read(self.chunk_bytes)
            except Exception as stream_err:
                logger.warning("Error reading stream chunk during capture phase: %s", stream_err)
                break

            if not chunk or len(chunk) < self.chunk_bytes:
                time.sleep(0.01)
                continue

            on_chunk(chunk)
            e = self.calculate_frame_energy(chunk)
            if e > self.sustain_energy_threshold:
                last_voice_time = time.time()

        return True

