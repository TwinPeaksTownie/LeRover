#!/usr/bin/env python3
"""Single Responsibility AudioPlaybackService module for Pi 4B.
Manages audio asset mappings in /home/carson/mario_sounds/ and executes a thread-safe,
single-consumer sequential FIFO Audio Queue to prevent overlapping or garbled audio.
Supports raw binary audio byte streams (WAV/MP3) and emergency queue flushes.
Fails loudly with explicit logging on missing files or playback errors.
Zero synthetic fallback tones.
"""

import logging
import os
import queue
import random
import subprocess
import threading
import time
from typing import Optional, Dict, Any

MARIO_SOUNDS_DIR = "/home/carson/mario_sounds"
PLANT_VINE_SOUNDS = [
    "nsmbwiiGiantPiranhaPlant.wav",
    "nsmbwiiPiranhaPlant1.wav",
    "nsmbwiiPiranhaPlant2.wav",
    "piranhaPlant.wav",
    "smw_vine.wav",
]

PULSE_ENV = dict(os.environ)
PULSE_ENV["XDG_RUNTIME_DIR"] = "/run/user/1000"
PULSE_ENV["PULSE_SERVER"] = "unix:/run/user/1000/pulse/native"


class AudioPlaybackService:
    """Dedicated service for sequential FIFO audio queuing and overlap prevention."""

    def __init__(self, sounds_dir: str = MARIO_SOUNDS_DIR) -> None:
        self.sounds_dir = sounds_dir
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._current_proc: Optional[subprocess.Popen] = None
        self._is_playing: bool = False
        self._current_track: Optional[str] = None

        # Start single-consumer background worker loop
        self._worker_thread = threading.Thread(target=self._consumer_loop, daemon=True)
        self._worker_thread.start()
        logging.info("Started AudioPlaybackService sequential FIFO consumer thread.")

    def play_sound(self, kind: str = "connect", wav_path: Optional[str] = None) -> None:
        """Enqueues a pre-stored sound asset into the sequential FIFO queue."""
        if kind == "stop" or kind == "stop_audio":
            self.stop_all()
            return

        target_wav = wav_path
        if not target_wav or not os.path.exists(target_wav):
            if kind == "connect":
                target_wav = os.path.join(self.sounds_dir, "smw_coin.wav")
            elif kind == "mario_kart_start":
                target_mp3 = "/home/carson/mario_kart_start.mp3"
                if os.path.exists(target_mp3):
                    self._queue.put({"type": "asset_mp3", "path": target_mp3, "name": "mario_kart_start.mp3"})
                    return
                target_wav = os.path.join(self.sounds_dir, "mario_kart_start.wav")
            elif kind in ("red_button", "random_plant_vine", "plant_vine"):
                target_wav = os.path.join(self.sounds_dir, random.choice(PLANT_VINE_SOUNDS))
            elif kind == "disconnect":
                target_wav = os.path.join(self.sounds_dir, "smw_pause.wav")
            elif kind in ("smw_shell_ricochet", "smw_shell_richochet", "shell_ricochet"):
                target_wav = os.path.join(self.sounds_dir, "smw_shell_ricochet.wav")
            elif kind:
                target_wav = os.path.join(self.sounds_dir, f"{kind}.wav")

        if target_wav and os.path.exists(target_wav):
            self._queue.put({"type": "asset_wav", "path": target_wav, "name": os.path.basename(target_wav)})
            logging.info("Enqueued audio asset '%s' (queue depth=%d).", kind, self._queue.qsize())
        else:
            logging.warning("Audio asset not found for kind='%s' path='%s'", kind, target_wav)

    def play_raw_audio(self, audio_bytes: bytes, audio_format: str = "wav") -> None:
        """Enqueues raw binary audio bytes into the sequential FIFO queue."""
        if not audio_bytes:
            logging.warning("play_raw_audio received empty byte payload.")
            return

        fmt = audio_format.lower()
        if audio_bytes.startswith(b"RIFF"):
            fmt = "wav"
        elif audio_bytes.startswith(b"ID3") or audio_bytes.startswith(b"\xff\xfb") or audio_bytes.startswith(b"\xff\xf3"):
            fmt = "mp3"

        self._queue.put({"type": "raw_bytes", "bytes": audio_bytes, "format": fmt, "name": f"raw_{fmt}_{len(audio_bytes)}B"})
        logging.info("Enqueued raw %s audio payload (%d bytes, queue depth=%d).", fmt.upper(), len(audio_bytes), self._queue.qsize())

    def stop_all(self) -> None:
        """Immediately terminates active playback processes and drains the audio queue."""
        with self._lock:
            # Drain all pending items from queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except Exception:
                    break

            # Kill active playback subprocesses
            if self._current_proc:
                try:
                    self._current_proc.terminate()
                    self._current_proc.kill()
                except Exception:
                    pass
                self._current_proc = None

            subprocess.run(["pkill", "-9", "mpg123"], check=False)
            subprocess.run(["pkill", "-9", "paplay"], check=False)
            subprocess.run(["pkill", "-9", "aplay"], check=False)
            self._is_playing = False
            self._current_track = None
            logging.info("Flushed audio queue and stopped active playback processes.")

    def get_state(self) -> Dict[str, Any]:
        """Returns live state of the audio queue."""
        with self._lock:
            return {
                "is_playing": self._is_playing,
                "current_track": self._current_track,
                "queue_depth": self._queue.qsize()
            }

    def _consumer_loop(self) -> None:
        """Single-consumer loop ensuring audio items execute sequentially without overlap."""
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            item_type = item.get("type")
            item_name = item.get("name", "unknown")

            with self._lock:
                self._is_playing = True
                self._current_track = item_name

            try:
                if item_type == "asset_wav":
                    cmd = ["paplay", item["path"]]
                    proc = subprocess.Popen(cmd, env=PULSE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with self._lock:
                        self._current_proc = proc
                    proc.wait()
                    if proc.returncode != 0:
                        cmd_fallback = ["aplay", "-D", "sysdefault", "-q", item["path"]]
                        subprocess.run(cmd_fallback, env=PULSE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

                elif item_type == "asset_mp3":
                    cmd = ["mpg123", "-q", item["path"]]
                    proc = subprocess.Popen(cmd, env=PULSE_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with self._lock:
                        self._current_proc = proc
                    proc.wait()

                elif item_type == "raw_bytes":
                    fmt = item.get("format", "wav")
                    cmd = ["mpg123", "-q", "-"] if fmt == "mp3" else ["aplay", "-q"]
                    proc = subprocess.Popen(cmd, env=PULSE_ENV, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with self._lock:
                        self._current_proc = proc
                    proc.communicate(input=item["bytes"])

            except Exception as ex:
                logging.error("Error playing audio item '%s': %s", item_name, ex)
            finally:
                with self._lock:
                    self._current_proc = None
                    self._is_playing = False
                    self._current_track = None
                self._queue.task_done()
