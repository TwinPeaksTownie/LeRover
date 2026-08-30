#!/usr/bin/env python3
"""Test 5: Synchronized Stop Integration Test.
Verifies that calling stop_dance() on BeatBanditApp simultaneously:
  - Signals the Pi 4B PulseAudio endpoint to stop sound.
  - Terminates the 50 Hz ChoreographyPlayer thread cleanly.
  - Resets all robot actuators to calibrated neutral postures.
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "pi500"))
from beat_bandit_app import BeatBanditApp
from choreography_compiler import compile_choreography_tracks


class TestSynchronizedStop(unittest.TestCase):

    def setUp(self):
        self.app = BeatBanditApp(running_on_pi=False)
        self.mock_backend = MagicMock()
        self.mock_backend.dispatch_dance_frame = MagicMock(return_value={"status": "ok"})

        self.mock_analysis = {
            "title": "Stop Test Song",
            "duration": 5.0,
            "bpm": 120.0,
            "beat_times": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5],
            "lyrics": [{"id": "ly_001", "name": "Vocal 1", "text": "Testing stop", "start_sec": 0.5, "end_sec": 4.0, "type": "lyric"}],
            "sections": [{"start_sec": 0.0, "end_sec": 5.0, "type": "verse", "energy_score": 0.5}],
            "drops": [],
            "held_notes": [],
            "mouth_envelope_50hz": [0.0] * 250,
        }

        self.app.active_track = {
            "track_id": "test_track_123",
            "title": "Stop Test Song",
            "artist": "Test Artist",
            "duration": 5.0,
            "bpm": 120.0,
            "wav_path": "/tmp/nonexistent.wav",
            "analysis": self.mock_analysis,
            "choreography": compile_choreography_tracks(self.mock_analysis, 5.0),
        }
        self.app.active_analysis = self.mock_analysis

    @patch("beat_bandit_audio.urllib.request.urlopen")
    def test_synchronized_stop_handshake(self, mock_urlopen):
        """Starts playback session, halts it, and verifies audio stop, thread termination, and neutral return."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # Start session
        self.app._start_player_session(self.mock_backend, start_sec=0.0, end_sec=5.0, loop=False)

        # Assert player is active and running
        self.assertIsNotNone(self.app.player)
        self.assertTrue(self.app.player.is_playing)
        self.assertEqual(self.app.current_state, "DANCING")

        time.sleep(0.3)

        # Execute Synchronized Stop
        self.app.stop_dance()

        # 1. Player thread must be dead and player set to None
        self.assertIsNone(self.app.player)
        self.assertEqual(self.app.current_state, "IDLE")

        # 2. Pi 4B sound stop request must have been triggered via audio_client
        self.assertGreaterEqual(mock_urlopen.call_count, 1)

        # 3. Neutral return frame must have been dispatched to backend
        self.assertGreaterEqual(self.mock_backend.dispatch_dance_frame.call_count, 2)
        last_call_kwargs = self.mock_backend.dispatch_dance_frame.call_args_list[-1]
        # Verify neutral return home posture was dispatched
        self.assertEqual(last_call_kwargs[1].get("s7_rom"), 50.0)
        self.assertEqual(last_call_kwargs[1].get("s8_goal"), 50.0)


if __name__ == "__main__":
    unittest.main()
