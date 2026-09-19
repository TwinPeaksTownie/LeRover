#!/usr/bin/env python3
"""Beat Bandit Audio Transport & Remote Service Client.
Handles:
  - Mac Mini (192.168.0.2:8086) deep neural analysis retrieval & WAV downloads.
  - In-memory WAV slicing for precise subsection playback.
  - Pi 4B (192.168.0.86:8082) PulseAudio dispatch and stop triggers.
  - Title and artist string sanitization.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

try:
    import network_resolver
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import network_resolver

logger = logging.getLogger("so101.beat_bandit_audio")


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
        logger.error(f"Failed slicing WAV file '{wav_path}' ({start_sec}s -> {end_sec}s): {e}")
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


def stop_pi4b_audio() -> bool:
    """Sends immediate stop signal to Pi 4B sound service."""
    try:
        stop_req = urllib.request.Request(
            get_pi4b_sound_url(),
            data=json.dumps({"action": "stop"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(stop_req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception as e:
        logger.debug(f"Pi 4B audio stop call notice: {e}")
        return False


def dispatch_audio_to_pi4b(wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> bool:
    """Dispatches audio payload to Pi 4B PulseAudio service (full fast-path or sliced)."""
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"Fail-Fast Error: Audio file not found for dispatch: {wav_path}")

    # 1. Sliced audio required for partial or seeked playback
    if float(start_sec) > 0.0 or (end_sec is not None and float(end_sec) > 0.0):
        logger.info(f"Slicing in-memory WAV audio for section {start_sec:.2f}s to {end_sec if end_sec else 'END'}s...")
        raw_wav = slice_wav_in_memory(wav_path, start_sec=start_sec, end_sec=end_sec)
        req = urllib.request.Request(
            get_pi4b_sound_url(),
            data=raw_wav,
            headers={"Content-Type": "audio/wav"}
        )
        with urllib.request.urlopen(req, timeout=7.0) as resp:
            if resp.status == 200:
                logger.info(f"Sliced audio payload ({len(raw_wav)/1024:.1f} KB) successfully dispatched to Pi 4B.")
                return True
            raise RuntimeError(f"Pi 4B audio server returned HTTP {resp.status} during sliced audio dispatch")

    # 2. Fast-path local file dispatch for full track playback (<8ms latency)
    payload = json.dumps({
        "event": "beat_bandit",
        "wav_path": str(wav_path),
        "stop_previous": True,
        "delay_sec": 0.0
    }).encode("utf-8")
    req = urllib.request.Request(
        get_pi4b_sound_url(),
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        if resp.status == 200:
            logger.info("Fast-path full track dispatch (%s) acknowledged by Pi 4B.", wav_path)
            return True
        raise RuntimeError(f"Pi 4B audio server returned HTTP {resp.status} during fast-path audio dispatch")


class BeatBanditAudioClient:
    """Client for Mac Mini neural audio analysis and Pi 4B sound distribution."""

    def __init__(self, library_dir: Path) -> None:
        self.library_dir = library_dir
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.current_start_sec: float = 0.0
        self.current_end_sec: Optional[float] = None
        self.active_wav_path: str = ""
        self.playback_start_time: float = 0.0
        self._is_playing: bool = False

    def init_audio_engine(self, driver: str = "pulse") -> None:
        """Configures audio client to dispatch playback through Pi 4B daemon."""
        logger.info("BeatBanditAudioClient initialized to dispatch playback through Pi 4B daemon (driver=%s).", driver)

    def _get_daemon_sound_url(self) -> str:
        try:
            from network_resolver import get_pi4b_ip
        except ImportError:
            try:
                from pi4b.network_resolver import get_pi4b_ip
            except ImportError:
                get_pi4b_ip = lambda prefer_port=8082: "127.0.0.1"
        ip = get_pi4b_ip(prefer_port=8082)
        return f"http://{ip}:8082/api/play_sound"

    def prepare_track(self, wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> bool:
        """Validates track existence and pre-calculates start/end bounds before playback."""
        if not os.path.exists(wav_path):
            raise FileNotFoundError(f"Fail-Fast Error: Audio file not found for playback: {wav_path}")

        self.active_wav_path = str(wav_path)
        self.current_start_sec = max(0.0, float(start_sec))
        self.current_end_sec = None
        if end_sec is not None and float(end_sec) > 0.0:
            self.current_end_sec = float(end_sec)

        self.playback_start_time = 0.0
        self._is_playing = False
        logger.info("Audio track '%s' prepared for daemon playback.", wav_path)
        return True

    def start_playback(self) -> bool:
        """Dispatches track playback to Pi 4B daemon /api/play_sound endpoint."""
        url = self._get_daemon_sound_url()
        payload = json.dumps({
            "event": "beat_bandit_track",
            "wav_path": self.active_wav_path,
            "stop_previous": True,
            "delay_sec": 0.0
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            pass
        self.playback_start_time = time.time()
        self._is_playing = True
        logger.info("Track playback dispatched to Pi 4B daemon /api/play_sound: %s", self.active_wav_path)
        return True

    def stop_playback(self) -> None:
        """Stops active audio playback on Pi 4B daemon."""
        url = self._get_daemon_sound_url()
        payload = json.dumps({"action": "stop"}).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                pass
        except Exception as e:
            logger.warning("Error stopping daemon audio: %s", e)
        self._is_playing = False
        self.playback_start_time = 0.0

    def get_audio_playback_time(self) -> float:
        """Returns current playback timestamp in seconds derived from start timestamp, or -1.0 if not playing."""
        if not self._is_playing or self.playback_start_time <= 0.0:
            return -1.0
        elapsed = time.time() - self.playback_start_time
        return self.current_start_sec + elapsed

    def fetch_analysis(self, url_or_id: str, track_id: str, mac_ip: Optional[str] = None) -> Dict[str, Any]:
        """Calls Mac Deep Audio Analysis Microservice (Port 8086)."""
        target_mac = mac_ip or network_resolver.get_mac_ip(prefer_port=8086)
        mac_url = f"http://{target_mac}:8086/api/analyze_track"
        logger.info(f"Calling Mac Audio Microservice at {mac_url}...")

        target_url = url_or_id if "http" in url_or_id else f"https://youtu.be/{track_id}"
        req_data = json.dumps({"url": target_url, "track_id": track_id}).encode("utf-8")
        req = urllib.request.Request(mac_url, data=req_data, headers={"Content-Type": "application/json"})

        with urllib.request.urlopen(req, timeout=300.0) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Mac Audio Service returned HTTP {resp.status}")
            analysis = json.loads(resp.read().decode("utf-8"))

        if not analysis:
            raise RuntimeError("Mac Audio Service returned empty analysis payload")
        if "mouth_envelope_50hz" not in analysis:
            raise KeyError("Fail-Fast Error: 'mouth_envelope_50hz' missing in Mac audio analysis payload")
        if "amplitude_envelope_50hz" not in analysis:
            raise KeyError("Fail-Fast Error: 'amplitude_envelope_50hz' missing in Mac audio analysis payload")

        return analysis

    def download_wav(self, track_id: str, mac_ip: Optional[str] = None) -> str:
        """Downloads cached WAV file from Mac Mini to local library directory."""
        dest_path = str(self.library_dir / f"{track_id}.wav")
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            return dest_path

        target_mac = mac_ip or network_resolver.get_mac_ip(prefer_port=8086)
        audio_dl_url = f"http://{target_mac}:8086/api/audio/{track_id}"
        logger.info(f"Downloading WAV audio from {audio_dl_url}...")
        urllib.request.urlretrieve(audio_dl_url, dest_path)

        if not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1000:
            raise RuntimeError(f"Failed to retrieve WAV audio for track '{track_id}'")

        return dest_path

    def dispatch_playback(self, wav_path: str, start_sec: float = 0.0, end_sec: Optional[float] = None) -> bool:
        """Unified playback dispatch: prepares and starts in-process audio."""
        try:
            self.prepare_track(wav_path, start_sec=start_sec, end_sec=end_sec)
            return self.start_playback()
        except Exception as e:
            logger.warning("In-process audio playback dispatch failed, falling back to HTTP: %s", e)
            return dispatch_audio_to_pi4b(wav_path, start_sec=start_sec, end_sec=end_sec)

    def stop_playback(self) -> bool:
        """Immediately halts in-process audio and cleans up external daemon playback."""
        try:
            import pygame
            if pygame.mixer.get_init() is not None:
                pygame.mixer.music.stop()
        except Exception as e:
            logger.debug("Pygame audio stop notice: %s", e)
        self._active_buf = None
        stop_pi4b_audio()
        return True
