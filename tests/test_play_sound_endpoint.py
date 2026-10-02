#!/usr/bin/env python3
"""tests/test_play_sound_endpoint.py - Verifies /api/play_sound endpoint contracts and interlocks."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'pi4b'))

import server


class TestPlaySoundEndpoint(unittest.TestCase):
    """Verifies synchronous/blocking audio execution and microphone stream safety interlocks."""

    @patch('server.subprocess.Popen')
    @patch('server.audio_resolver.get_audio_duration_sec', return_value=0.5)
    def test_play_sound_helper_blocking(self, mock_get_dur, mock_popen):
        """play_sound_helper with blocking=True must execute synchronously without spawning a thread."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b'', b'')
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        with patch('server.threading.Thread') as mock_thread:
            with patch('server.os.path.exists', return_value=True):
                dur = server.play_sound_helper(
                    wav_path='/home/carson/mario_sounds/smw_whistle.wav',
                    blocking=True
                )
                self.assertEqual(dur, 0.5)
                # Thread should NOT be spawned when blocking=True
                mock_thread.assert_not_called()
                # Popen communicate should be called directly
                mock_proc.communicate.assert_called_once()

    @patch('server.subprocess.Popen')
    @patch('server.audio_resolver.get_audio_duration_sec', return_value=0.5)
    def test_play_sound_helper_non_blocking(self, mock_get_dur, mock_popen):
        """play_sound_helper with blocking=False must spawn a background thread."""
        with patch('server.threading.Thread') as mock_thread:
            mock_inst = MagicMock()
            mock_thread.return_value = mock_inst

            dur = server.play_sound_helper(
                wav_path='/home/carson/mario_sounds/smw_whistle.wav',
                blocking=False
            )
            self.assertEqual(dur, 0.5)
            mock_thread.assert_called_once()
            mock_inst.start.assert_called_once()

    def test_play_sound_endpoint_requires_blocking_key(self):
        """POST /api/play_sound must reject payload if required 'blocking' key is missing."""
        mock_handler = MagicMock()
        mock_handler.path = '/api/play_sound'
        mock_handler.headers = {'Content-Type': 'application/json', 'Content-Length': '10'}
        mock_handler.send_response = MagicMock()
        mock_handler.send_header = MagicMock()
        mock_handler.end_headers = MagicMock()
        mock_handler.wfile = MagicMock()

        # Missing 'blocking' key
        payload = {
            'event': 'test_sound',
            'stop_previous': False,
            'delay_sec': 0.0,
            'wav_path': ''
        }

        # Mock UnifiedHandler execution
        with patch('server.play_sound_helper') as mock_helper:
            server.UnifiedHandler.do_POST.__wrapped__ = None  # Ensure unadorned if any
            # Directly call do_POST logic by feeding rfile
            import io
            mock_handler.rfile = io.BytesIO(json.dumps(payload).encode('utf-8'))
            mock_handler.headers['Content-Length'] = str(len(json.dumps(payload)))
            server.UnifiedHandler.do_POST(mock_handler)
            mock_handler.send_response.assert_called_with(400)
            mock_helper.assert_not_called()

    def test_microphone_stream_rejects_while_speaker_active(self):
        """GET /api/microphone/stream must return 409 if CURRENT_PAPLAY_PROC is actively playing."""
        mock_handler = MagicMock()
        mock_handler.path = '/api/microphone/stream'
        mock_handler._send_json = MagicMock()

        mock_active_proc = MagicMock()
        mock_active_proc.poll.return_value = None  # None means process is still running!

        old_proc = server.CURRENT_PAPLAY_PROC
        try:
            server.CURRENT_PAPLAY_PROC = mock_active_proc

            server.UnifiedHandler.do_GET(mock_handler)
            mock_handler._send_json.assert_called_once()
            args, _ = mock_handler._send_json.call_args
            self.assertIn('error', args[0])
            self.assertIn('speaker audio playback is active', args[0]['error'])
            self.assertEqual(args[1], 409)
        finally:
            server.CURRENT_PAPLAY_PROC = old_proc


if __name__ == '__main__':
    unittest.main()
