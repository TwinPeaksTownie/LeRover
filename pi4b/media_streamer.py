#!/usr/bin/env python3
"""Single Responsibility MediaStreamerService module for Pi 4B.
Manages USB hardware GStreamer background subprocesses for remote video and audio streaming.
Streams USB Camera (/dev/video0) over HTTP/MJPEG port 8083 and USB Microphone over UDP port 5004
using native ALSA audio capture without forced sample-rate conversions.
"""

import logging
import shutil
import subprocess
from typing import Optional


class MediaStreamerService:
    """Dedicated manager for USB GStreamer video and audio streaming background processes."""

    def __init__(self, video_device: str = "/dev/video0", video_port: int = 8083, audio_port: int = 5004) -> None:
        self.video_device = video_device
        self.video_port = video_port
        self.audio_port = audio_port
        self._video_proc: Optional[subprocess.Popen] = None
        self._audio_proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        """Launches GStreamer background pipelines for video and audio if gst-launch-1.0 is available."""
        gst_bin = shutil.which("gst-launch-1.0")
        if not gst_bin:
            logging.warning("gst-launch-1.0 binary not found on system PATH. Skipping GStreamer media pipelines.")
            return

        # 1. USB Camera Video Pipeline (HTTP MJPEG Server on port 8083)
        video_cmd = [
            gst_bin, "-q",
            "v4l2src", f"device={self.video_device}",
            "!", "videoconvert",
            "!", "jpegenc",
            "!", "tcpserversink", "host=0.0.0.0", f"port={self.video_port}"
        ]
        try:
            self._video_proc = subprocess.Popen(video_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logging.info("Launched GStreamer Video Streamer on port %d (device=%s)", self.video_port, self.video_device)
        except Exception as e:
            logging.error("Failed to launch GStreamer video pipeline: %s", e)

        # 2. USB Microphone Audio Pipeline (Native ALSA Capture to UDP port 5004)
        audio_cmd = [
            gst_bin, "-q",
            "alsasrc",
            "!", "audioconvert",
            "!", "udpsink", "host=0.0.0.0", f"port={self.audio_port}"
        ]
        try:
            self._audio_proc = subprocess.Popen(audio_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logging.info("Launched GStreamer Audio Streamer on UDP port %d (native ALSA capture)", self.audio_port)
        except Exception as e:
            logging.error("Failed to launch GStreamer audio pipeline: %s", e)

    def stop(self) -> None:
        """Gracefully stops all background GStreamer streaming subprocesses."""
        if self._video_proc:
            try:
                self._video_proc.terminate()
                self._video_proc.wait(timeout=2.0)
            except Exception:
                self._video_proc.kill()
            self._video_proc = None
            logging.info("Stopped GStreamer video stream subprocess.")

        if self._audio_proc:
            try:
                self._audio_proc.terminate()
                self._audio_proc.wait(timeout=2.0)
            except Exception:
                self._audio_proc.kill()
            self._audio_proc = None
            logging.info("Stopped GStreamer audio stream subprocess.")
