#!/usr/bin/env python3
"""Test 1: Audio Isolation Test.
Verifies beat_bandit_audio.py independently handles:
  - In-memory WAV slicing with exact header and frame alignment.
  - Title and artist string cleaning.
  - Remote API contract fetching and Pi 4B dispatch without importing beat_bandit_app.py.
"""

import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

# Strictly verify beat_bandit_app is NOT imported
assert "beat_bandit_app" not in sys.modules, "beat_bandit_app must NOT be imported for audio isolation test"

sys.path.insert(0, str(Path(__file__).parent.parent / "pi4b"))
import beat_bandit_audio

assert "beat_bandit_app" not in sys.modules, "beat_bandit_app must NOT be imported by beat_bandit_audio"


class TestAudioIsolation(unittest.TestCase):

    def setUp(self):
        # Create a synthetic 1-second 44.1kHz stereo WAV in temp dir
        self.temp_dir = tempfile.TemporaryDirectory()
        self.wav_path = os.path.join(self.temp_dir.name, "test_audio.wav")
        with wave.open(self.wav_path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            # 1 second of silence (44100 frames * 4 bytes)
            wf.writeframes(b"\x00" * (44100 * 4))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_in_memory_wav_slicing(self):
        """Tests slicing 0.2s to 0.6s from WAV file directly in memory."""
        sliced_bytes = beat_bandit_audio.slice_wav_in_memory(self.wav_path, start_sec=0.2, end_sec=0.6)
        self.assertGreater(len(sliced_bytes), 44)  # Must have valid RIFF header

        # Verify header structure
        buf = io.BytesIO(sliced_bytes)
        with wave.open(buf, "rb") as wf:
            self.assertEqual(wf.getnchannels(), 2)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 44100)
            # Expected 0.4s * 44100 = 17640 frames
            self.assertAlmostEqual(wf.getnframes(), 17640, delta=10)

    def test_title_and_artist_sanitization(self):
        """Tests removing visualizer, official audio, and tags from title strings."""
        raw = "Artist Name - Cool Song (Official Audio) [4K Visualizer]"
        song, artist = beat_bandit_audio.sanitize_title_and_artist(raw)
        self.assertEqual(song, "Cool Song")
        self.assertEqual(artist, "Artist Name")

        raw2 = "Solo Song by Pop Star | Official Visualizer"
        song2, artist2 = beat_bandit_audio.sanitize_title_and_artist(raw2)
        self.assertEqual(song2, "Solo Song")
        self.assertEqual(artist2, "Pop Star")

    @patch("urllib.request.urlopen")
    def test_pi4b_audio_dispatch_and_stop(self, mock_urlopen):
        """Tests sending WAV slice and stop signal over network to Pi 4B."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # Test stop signal
        ok_stop = beat_bandit_audio.stop_pi4b_audio()
        self.assertTrue(ok_stop)

        # Test dispatch
        ok_dispatch = beat_bandit_audio.dispatch_audio_to_pi4b(self.wav_path, start_sec=0.1, end_sec=0.5)
        self.assertTrue(ok_dispatch)
        self.assertGreaterEqual(mock_urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
