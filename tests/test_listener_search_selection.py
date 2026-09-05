#!/usr/bin/env python3
"""tests/test_listener_search_selection.py - Unit tests for ListenerApp Search & 4-Row Selection.

Verifies:
  1. fetch_search_candidates returns 4 structured items with title, duration, uploader, id, url.
  2. navigate_selection clamps index between 0 and 3.
  3. select_track validates bounds and starts download/compile pipeline.
  4. PokeballApp joystick Y-tilt navigates listener track selection and Button A confirms.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
PI500_DIR = WORKSPACE_ROOT / "pi500"
for p in [WORKSPACE_ROOT, PI500_DIR]:
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

from apps.listener_app.song_pipeline import fetch_search_candidates
from apps.listener_app.app import ListenerApp
from apps.pokeball_app.app import PokeballApp


class TestListenerSearchSelection(unittest.TestCase):

    def test_fetch_search_candidates_mocked(self):
        mock_output = (
            '{"id": "vid1", "title": "Song One - Artist A", "duration": 210, "uploader": "Artist A", "webpage_url": "https://youtu.be/vid1"}\n'
            '{"id": "vid2", "title": "Song Two - Artist B", "duration": 180, "uploader": "Artist B", "webpage_url": "https://youtu.be/vid2"}\n'
            '{"id": "vid3", "title": "Song Three - Artist C", "duration": 240, "uploader": "Artist C", "webpage_url": "https://youtu.be/vid3"}\n'
            '{"id": "vid4", "title": "Song Four - Artist D", "duration": 195, "uploader": "Artist D", "webpage_url": "https://youtu.be/vid4"}\n'
            '{"id": "vid5", "title": "Song Five - Artist E", "duration": 300, "uploader": "Artist E", "webpage_url": "https://youtu.be/vid5"}\n'
        )

        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = mock_output
            mock_run.return_value = mock_proc

            candidates = fetch_search_candidates("test query", limit=4)
            self.assertEqual(len(candidates), 4)
            self.assertEqual(candidates[0]["id"], "vid1")
            self.assertEqual(candidates[0]["title"], "Song One - Artist A")
            self.assertEqual(candidates[0]["duration"], "3:30")
            self.assertEqual(candidates[0]["duration_sec"], 210)
            self.assertEqual(candidates[0]["uploader"], "Artist A")
            self.assertEqual(candidates[3]["id"], "vid4")

    def test_fetch_search_candidates_empty_or_whitespace(self):
        with self.assertRaises(ValueError):
            fetch_search_candidates("   ")

    def test_listener_app_selection_navigation(self):
        app = ListenerApp(running_on_pi=False)
        self.assertEqual(app.selected_index, 0)
        self.assertEqual(app.search_results, [])

        # Manually populate 4 results
        app.search_results = [
            {"id": "1", "title": "Track 1", "duration": 100, "uploader": "Up 1", "url": ""},
            {"id": "2", "title": "Track 2", "duration": 200, "uploader": "Up 2", "url": ""},
            {"id": "3", "title": "Track 3", "duration": 300, "uploader": "Up 3", "url": ""},
            {"id": "4", "title": "Track 4", "duration": 400, "uploader": "Up 4", "url": ""},
        ]
        app.state = "SELECTING"

        # Navigate down
        new_idx = app.navigate_selection(1)
        self.assertEqual(new_idx, 1)
        self.assertEqual(app.selected_index, 1)

        app.navigate_selection(1)
        self.assertEqual(app.selected_index, 2)
        app.navigate_selection(1)
        self.assertEqual(app.selected_index, 3)

        # Clamping at boundary (max index 3)
        app.navigate_selection(1)
        self.assertEqual(app.selected_index, 3)

        # Navigate up
        app.navigate_selection(-1)
        self.assertEqual(app.selected_index, 2)

        # Clamping at boundary (min index 0)
        app.navigate_selection(-2)
        self.assertEqual(app.selected_index, 0)
        app.navigate_selection(-1)
        self.assertEqual(app.selected_index, 0)

    def test_listener_app_select_track_dispatch(self):
        app = ListenerApp(running_on_pi=False)
        app.search_results = [
            {"id": "vid1", "title": "Track 1", "duration": 100, "uploader": "Up 1", "url": ""},
            {"id": "vid2", "title": "Track 2", "duration": 200, "uploader": "Up 2", "url": ""},
        ]
        app.state = "SELECTING"

        with patch("threading.Thread") as mock_thread:
            selected = app.select_track(index=1)
            self.assertIsNotNone(selected)
            self.assertEqual(selected["id"], "vid2")
            self.assertEqual(app.state, "DOWNLOADING")
            self.assertTrue(mock_thread.called)

    def test_listener_app_status_telemetry(self):
        app = ListenerApp(running_on_pi=False)
        app.search_query = "pink pony club"
        app.search_results = [{"id": "v1", "title": "PPC", "duration": 180, "uploader": "CR", "url": ""}]
        app.selected_index = 0
        app.state = "SELECTING"

        status = app.get_status()
        self.assertEqual(status["state"], "SELECTING")
        self.assertEqual(status["query"], "pink pony club")
        self.assertEqual(len(status["search_results"]), 1)
        self.assertEqual(status["selected_index"], 0)

    def test_pokeball_listener_selection_handling(self):
        from apps.pokeball_app.app import PokeballService
        service = PokeballService()
        mock_mgr = MagicMock()
        mock_mgr.current_app_name = "listener_app"
        mock_listener = MagicMock()
        mock_listener.state = "SELECTING"
        mock_mgr.active_app = mock_listener
        service.app_manager = mock_mgr

        def make_packet(buttons=0, x=None, y=None):
            x_val = service.joystick_center_x if x is None else x
            y_val = service.joystick_center_y if y is None else y
            return bytearray([
                0x00,
                buttons & 0xFF,
                x_val & 0xFF,
                ((x_val >> 8) & 0x0F) | ((y_val & 0x0F) << 4),
                (y_val >> 4) & 0xFF,
            ])

        # 1. Drive actual notification_handler with joystick tilted DOWN (y=500 -> norm_y < -0.4)
        tilt_down_pkt = make_packet(buttons=0x00, x=service.joystick_center_x, y=int(service.joystick_center_y * 0.3))
        service.notification_handler(None, tilt_down_pkt)
        mock_listener.navigate_selection.assert_called_with(1)

        # 2. Drive actual notification_handler with joystick tilted UP (y=3500 -> norm_y > 0.4) after debounce
        service.last_listener_nav_time = 0.0
        tilt_up_pkt = make_packet(buttons=0x00, x=service.joystick_center_x, y=int(service.joystick_center_y * 1.7))
        service.notification_handler(None, tilt_up_pkt)
        mock_listener.navigate_selection.assert_called_with(-1)

        # 3. Drive actual notification_handler with Button A click (buttons=0x02)
        btn_a_pkt = make_packet(buttons=0x02, x=service.joystick_center_x, y=service.joystick_center_y)
        service.notification_handler(None, btn_a_pkt)
        mock_listener.select_track.assert_called_once()


if __name__ == "__main__":
    unittest.main()
