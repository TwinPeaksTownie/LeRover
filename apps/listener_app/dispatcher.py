#!/usr/bin/env python3
"""apps/listener_app/dispatcher.py - Intent Action Dispatcher & Selection Manager.

Executes parsed voice intents and manages track selection state:
  1. POSTURE: Executes normalized joint interpolations via load_dance_presets() with torque control.
  2. DOWNLOAD_SONG: Queries YouTube candidates and transitions state to SELECTING.
  3. PLAY_SONG: Transitions to Beat Bandit track or compiled preset sequence.
  4. SWITCH_APP: Delegates app transition to AppManager.
  5. EXIT: Terminates listener or returns to caller app.
  6. Track Selection: Cursor navigation, candidate selection, Mac analysis offload, and cancel.

Strict Fail-Fast Schema: Zero .get(k, default) fallbacks.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Dict, Any, List

from robot_backend import RobotBackend
from apps.listener_app.song_pipeline import (
    find_compiled_sequence,
    find_beat_bandit_track,
    fetch_search_candidates,
    load_dance_presets,
    execute_mac_analysis,
)

logger = logging.getLogger("so101.listener_app.dispatcher")


class ActionDispatcher:
    """Dispatches recognized voice intents to physical hardware and application manager."""

    def __init__(self, config: Dict[str, Any], play_chime_fn) -> None:
        self.config = config
        self.play_chime = play_chime_fn
        self.dance_presets: Optional[Dict[str, Any]] = None
        self.interp_dur = float(self.config["motion"]["interpolation_duration_sec"])
        self.interp_steps = int(self.config["motion"]["interpolation_steps"])

        # Track selection state
        self.selection_lock = threading.Lock()
        self.selected_index: int = 0
        self.search_query: str = ""
        self.search_results: List[Dict[str, Any]] = []
        self.last_analyzed_track: Optional[Dict[str, Any]] = None

    def execute_posture(self, backend: RobotBackend, action: str, app=None) -> None:
        """Executes calibrated arm posture movement on RobotBackend."""
        logger.info("Executing posture action: '%s' (duration=%.1fs, steps=%d)",
                    action, self.interp_dur, self.interp_steps)

        if not self.dance_presets:
            if app is not None and hasattr(app, "dance_presets") and bool(app.dance_presets):
                self.dance_presets = app.dance_presets
            else:
                self.dance_presets = load_dance_presets()

        if action == "stand":
            backend.set_arm_torque(enable=True)
            target = self.dance_presets["stand"]["normalized"]
            backend.interpolate_arm_norm(target, duration=self.interp_dur, steps=self.interp_steps)
            if app is not None:
                app.action_taken = "Moved to stand"
        elif action == "sit":
            backend.set_arm_torque(enable=True)
            sit_key = "sit" if "sit" in self.dance_presets else "squat"
            target = self.dance_presets[sit_key]["normalized"]
            backend.interpolate_arm_norm(target, duration=self.interp_dur, steps=self.interp_steps)
            if app is not None:
                app.action_taken = "Moved to sit"
        elif action == "tiptoes":
            backend.set_arm_torque(enable=True)
            tiptoe_key = "tiptoe" if "tiptoe" in self.dance_presets else "tiptoes"
            target = self.dance_presets[tiptoe_key]["normalized"]
            backend.interpolate_arm_norm(target, duration=self.interp_dur, steps=self.interp_steps)
            if app is not None:
                app.action_taken = "Moved to tiptoes"
        elif action == "play_dead":
            backend.set_arm_torque(enable=True)
            dead_key = str(self.config["motion"]["dead_posture"])
            target = self.dance_presets[dead_key]["normalized"]
            backend.interpolate_arm_norm(target, duration=self.interp_dur, steps=self.interp_steps)
            backend.set_arm_torque(enable=False)
            if app is not None:
                app.action_taken = "Playing dead (torque relaxed)"
            self.play_chime("play_dead")
        else:
            raise KeyError(f"Unsupported posture action: '{action}'")

    def navigate_selection(self, step: int, app=None) -> int:
        """Navigates track selection cursor up (-1) or down (+1)."""
        with self.selection_lock:
            if not self.search_results:
                return 0
            n = len(self.search_results)
            self.selected_index = max(0, min(n - 1, self.selected_index + step))
            track_title = str(self.search_results[self.selected_index]["title"])
            if app is not None:
                app.selected_index = self.selected_index
                app.action_taken = f"Selecting: {track_title}"
            logger.info("Track selection navigated to index %d: %s", self.selected_index, track_title)
            return self.selected_index

    def select_track(self, index: int, app=None) -> Dict[str, Any]:
        """Selects a candidate track by index without triggering download."""
        with self.selection_lock:
            if not self.search_results:
                raise ValueError("select_track called with empty search_results")
            if index < 0 or index >= len(self.search_results):
                raise IndexError(f"Track selection index {index} out of bounds (total: {len(self.search_results)})")
            self.selected_index = index
            target_track = self.search_results[index]
            _ = target_track["video_id"]
            _ = target_track["title"]
            if app is not None:
                app.selected_index = index
            logger.info("Track selected at index %d: '%s' (%s)", index, target_track["title"], target_track["video_id"])
            return target_track

    def cancel_selection(self, app=None) -> None:
        """Cleanly escapes SELECTING or ANALYZING state back to IDLE."""
        with self.selection_lock:
            self.search_results = []
            self.selected_index = 0
            if app is not None:
                with app._selection_lock:
                    app.state = "IDLE"
                    app.search_results = []
                    app.selected_index = 0
                    app.action_taken = "Selection cancelled. Press Button B to speak"
        self.play_chime("cancel")
        logger.info("Track selection cleanly cancelled. Returned to IDLE.")

    def trigger_analysis(self, index: Optional[int] = None, app=None) -> Dict[str, Any]:
        """Triggers neural rhythm analysis on Mac Mini for chosen track in background thread."""
        with self.selection_lock:
            if app is not None and app.state == "ANALYZING":
                raise RuntimeError("trigger_analysis rejected: Mac analysis already active")
            if not self.search_results:
                raise ValueError("trigger_analysis called with empty search_results")

            if index is None:
                index = self.selected_index
            if index < 0 or index >= len(self.search_results):
                raise IndexError(f"Analysis index {index} out of bounds (total: {len(self.search_results)})")

            self.selected_index = index
            target_track = self.search_results[index]
            _ = target_track["video_id"]
            _ = target_track["title"]

            logger.info("Triggering Mac analysis for track index %d: '%s' (%s)...",
                        index, target_track["title"], target_track["video_id"])
            if app is not None:
                with app._selection_lock:
                    app.selected_index = index
                    app.state = "ANALYZING"
            self.play_chime("commit")

        def _worker():
            try:
                entry = execute_mac_analysis(target_track)
                with self.selection_lock:
                    self.last_analyzed_track = entry
                    if app is not None:
                        with app._selection_lock:
                            app.last_analyzed_track = entry
                            app.state = "IDLE"
                self.play_chime("commit")
            except Exception as e:
                logger.error("Mac analysis error for track '%s': %s", target_track["title"], e, exc_info=True)
                with self.selection_lock:
                    if app is not None:
                        with app._selection_lock:
                            app.error = str(e)
                            app.state = "IDLE"
                self.play_chime("cancel")

        threading.Thread(target=_worker, daemon=True).start()
        return target_track

    def dispatch(self, intent: Dict[str, Any], app, backend: RobotBackend) -> bool:
        """Dispatches intent to appropriate subsystem. Returns True if handled."""
        intent_type = intent["intent"]

        if intent_type == "SWITCH_APP":
            target_app = intent["app"]
            app.action_taken = f"Switching to {target_app}"
            logger.info("Switching to app '%s', terminating listener...", target_app)
            self.play_chime("commit")
            if app.app_manager is not None:
                def _switch_app():
                    try:
                        app.app_manager.start_app_by_name(target_app)
                    except Exception as ex:
                        logger.error("Failed switching to app '%s': %s", target_app, ex, exc_info=True)
                threading.Thread(target=_switch_app, daemon=True).start()
            app.stop()
            return True

        elif intent_type == "POSTURE":
            action = intent["action"]
            self.execute_posture(backend, action, app=app)
            if action != "play_dead":
                self.play_chime("commit")
            return True

        elif intent_type == "DOWNLOAD_SONG":
            with self.selection_lock:
                if app.state == "ANALYZING":
                    logger.warning("Rejecting search query: track analysis active on Mac")
                    self.play_chime("cancel")
                    return False
            title = intent["title"]
            artist = intent["artist"]
            query_str = f"{title} {artist}".strip()
            app.action_taken = f"Searching tracks: '{query_str}'"
            with self.selection_lock:
                self.search_query = query_str
                with app._selection_lock:
                    app.search_query = query_str
                    app.state = "SEARCHING"
            logger.info("Querying top 4 tracks for '%s'...", query_str)
            try:
                candidates = fetch_search_candidates(query_str, limit=4)
                with self.selection_lock:
                    self.search_results = candidates
                    self.selected_index = 0
                    with app._selection_lock:
                        app.search_results = candidates
                        app.selected_index = 0
                        app.state = "SELECTING"
                self.play_chime("commit")
                logger.info("Retrieved %d candidates for selection: %s",
                            len(candidates), [c["title"] for c in candidates])
            except Exception as e:
                logger.error("Search query failed for '%s': %s", query_str, e, exc_info=True)
                with self.selection_lock:
                    with app._selection_lock:
                        app.error = str(e)
                        app.state = "IDLE"
                self.play_chime("cancel")
            return True

        elif intent_type == "PLAY_SONG":
            title = intent["title"]
            bb_track = find_beat_bandit_track(title)
            if bb_track is not None:
                track_id = str(bb_track["track_id"])
                track_title = str(bb_track["title"])
                app.action_taken = f"Playing Beat Bandit: '{track_title}'"
                logger.info("Found Beat Bandit track '%s' (ID: %s), transitioning...", track_title, track_id)
                self.play_chime("commit")
                if app.app_manager is not None:
                    def _on_bb_started(bb_app):
                        if hasattr(bb_app, "start_track_by_url_or_id"):
                            logger.info("Triggering Beat Bandit playback for '%s'...", track_id)
                            bb_app.start_track_by_url_or_id(app.app_manager.backend, track_id)
                    app.app_manager.switch_app("beat_bandit_app", on_started=_on_bb_started)
                    return True
                app.stop()
                return True
            else:
                seq_file = find_compiled_sequence(title)
                if seq_file is not None:
                    app.action_taken = f"Playing Preset: '{title}'"
                    logger.info("Found compiled sequence '%s', launching preset_app...", seq_file)
                    self.play_chime("commit")
                    if app.app_manager is not None:
                        def _launch_preset():
                            try:
                                app.app_manager.start_app_by_name("preset_app")
                            except Exception as ex:
                                logger.error("Failed to start preset_app: %s", ex, exc_info=True)
                        threading.Thread(target=_launch_preset, daemon=True).start()
                    app.stop()
                    return True
                else:
                    app.action_taken = str(self.config["feedback"]["unmatched_action"])
                    logger.warning("No Beat Bandit track or compiled sequence found for '%s'.", title)
                    self.play_chime("cancel")
                    return True

        elif intent_type == "EXIT":
            app.action_taken = "Exiting Voice Listener"
            logger.info("Exit command received, stopping listener app...")
            if app.caller_app and app.app_manager is not None:
                caller = str(app.caller_app)
                def _return_to_caller_exit():
                    try:
                        logger.info("Returning to caller app '%s' on exit...", caller)
                        app.app_manager.start_app_by_name(caller)
                    except Exception as ex:
                        logger.error("Failed to return to caller app '%s': %s", caller, ex)
                threading.Thread(target=_return_to_caller_exit, daemon=True).start()
            app.stop()
            return True

        else:
            app.action_taken = str(self.config["feedback"]["unmatched_action"])
            logger.warning("Unrecognized voice intent '%s'.", intent_type)
            self.play_chime("cancel")
            return True
