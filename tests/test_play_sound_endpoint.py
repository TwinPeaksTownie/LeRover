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
    def test_play_sound_helper_asynchronous(self, mock_get_dur, mock_popen):
        """play_sound_helper must spawn a background thread and return duration immediately."""
        with patch('server.threading.Thread') as mock_thread:
            mock_inst = MagicMock()
            mock_thread.return_value = mock_inst

            dur = server.play_sound_helper(
                wav_path='/home/carson/mario_sounds/smw_whistle.wav'
            )
            self.assertEqual(dur, 0.5)
            mock_thread.assert_called_once()
            mock_inst.start.assert_called_once()

    def test_play_sound_endpoint_requires_contract_keys(self):
        """POST /api/play_sound must reject payload if required keys are missing."""
        mock_handler = MagicMock()
        mock_handler.path = '/api/play_sound'
        mock_handler.headers = {'Content-Type': 'application/json', 'Content-Length': '10'}
        mock_handler.send_response = MagicMock()
        mock_handler.send_header = MagicMock()
        mock_handler.end_headers = MagicMock()
        mock_handler.wfile = MagicMock()

        # Missing 'wav_path' key
        payload = {
            'event': 'test_sound',
            'stop_previous': False,
            'delay_sec': 0.0
        }

        with patch('server.play_sound_helper') as mock_helper:
            import io
            mock_handler.rfile = io.BytesIO(json.dumps(payload).encode('utf-8'))
            mock_handler.headers['Content-Length'] = str(len(json.dumps(payload)))
            server.UnifiedHandler.do_POST(mock_handler)
            mock_handler.send_response.assert_called_with(400)
            mock_helper.assert_not_called()

    def test_play_sound_endpoint_success(self):
        """POST /api/play_sound succeeds with standard 4 keys."""
        mock_handler = MagicMock()
        mock_handler.path = '/api/play_sound'
        mock_handler.send_response = MagicMock()
        mock_handler.send_header = MagicMock()
        mock_handler.end_headers = MagicMock()
        mock_handler.wfile = MagicMock()

        payload = {
            'event': 'test_sound',
            'stop_previous': False,
            'delay_sec': 0.0,
            'wav_path': ''
        }

        with patch('server.play_sound_helper', return_value=0.75) as mock_helper:
            import io
            mock_handler.rfile = io.BytesIO(json.dumps(payload).encode('utf-8'))
            mock_handler.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(json.dumps(payload)))}
            server.UnifiedHandler.do_POST(mock_handler)
            mock_handler.send_response.assert_called_with(200)
            mock_helper.assert_called_once_with(event='test_sound', wav_path='', stop_previous=False, delay_sec=0.0)

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
