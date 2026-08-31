#!/usr/bin/env python3
import sys
import os
import io
import time
import json
import ast
from unittest.mock import MagicMock

# Add pi500 to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "pi500")))

def run_audio_isolation_audit():
    print("1. Running Audio Isolation Audit...")
    target_file = os.path.join("pi500", "beat_bandit_app.py")
    with open(target_file, "r") as f:
        tree = ast.parse(f.read(), filename=target_file)
    
    banned_imports = ["requests", "wave", "io"]
    found_banned = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in banned_imports:
                    found_banned.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module in banned_imports:
                found_banned.append(node.module)
                
    if not found_banned:
        print("  [PASS] beat_bandit_app.py has no requests, wave, or io imports.")
    else:
        print(f"  [FAIL] beat_bandit_app.py imports banned modules: {found_banned}")


def run_headless_simulation():
    print("\n2. Running Headless Motion Simulation...")
    try:
        from pi500.choreography_player import ChoreographyPlayer
        
        mock_backend = MagicMock()
        mock_analysis = {
            "beat_times": [0.0, 0.5, 1.0, 1.5, 2.0],
            "mouth_envelope_50hz": [0.0] * 100
        }
        mock_choreo = {
            "duration": 2.0,
            "blocks": [],
            "tracks": {},
            "poses": {
                "stand": {"shoulder_pan": 50, "shoulder_lift": 50, "elbow_flex": 50, "wrist_flex": 50, "wrist_roll": 50},
                "squat": {"shoulder_pan": 50, "shoulder_lift": 50, "elbow_flex": 50, "wrist_flex": 50, "wrist_roll": 50},
                "tiptoe": {"shoulder_pan": 50, "shoulder_lift": 50, "elbow_flex": 50, "wrist_flex": 50, "wrist_roll": 50},
                "arch": {"shoulder_pan": 50, "shoulder_lift": 50, "elbow_flex": 50, "wrist_flex": 50, "wrist_roll": 50},
            }
        }
        
        player = ChoreographyPlayer(mock_backend, mock_choreo, mock_analysis)
        player.start()
        time.sleep(1.0) # Let it run the 50Hz loop
        player.stop()
        
        calls = mock_backend.dispatch_dance_frame.call_count
        if calls > 0:
            print(f"  [PASS] ChoreographyPlayer ran headless successfully. (Frames dispatched: {calls})")
        else:
            print("  [FAIL] ChoreographyPlayer did not dispatch any frames.")
    except Exception as e:
        print(f"  [FAIL] ChoreographyPlayer crashed: {e}")


def run_hardware_leak_check():
    print("\n3. Running Hardware Dispatch Leak Check...")
    files_to_check = [
        "pi500/choreography_player.py",
        "pi500/beat_bandit_app.py",
        "pi500/beat_studio.py",
        "pi500/api_server.py",
        "pi500/teleop_control_loop.py"
    ]
    leaks = []
    
    for fname in files_to_check:
        with open(fname, "r") as f:
            lines = f.readlines()
            for i, line in enumerate(lines):
                if "SERIAL_LOCK" in line and not line.strip().startswith("#"):
                    leaks.append(f"{fname}:{i+1} -> {line.strip()}")
                if "sync_write" in line and not line.strip().startswith("#"):
                    leaks.append(f"{fname}:{i+1} -> {line.strip()}")
    
    if not leaks:
        print("  [PASS] No SERIAL_LOCK or sync_write leaked outside robot_backend.py")
    else:
        print("  [FAIL] Leaks found:")
        for leak in leaks:
            print(f"    - {leak}")


def run_user_edit_preservation_test():
    print("\n4. Running User-Edit Preservation Test...")
    try:
        from pi500.choreography_compiler import compile_choreography_tracks
        mock_analysis = {
            "beat_times": [0.0, 1.0, 2.0],
            "duration": 2.0
        }
        
        existing_choreo = {
            "blocks": [{"id": "b1", "name": "block 1", "is_user_edited": True, "start_sec": 0, "end_sec": 2, "bounce_modifier": {"enabled": True, "intensity": 0.1, "target": "head_bob"}}],
            "tracks": {
                "s8_gantry": [{"id": "s8_1", "block_id": "b1", "name": "user move", "mode": "custom", "is_user_edited": True, "target_pos_rom": 88.0, "start_sec": 0, "end_sec": 1, "speed": 100}]
            }
        }
        
        new_choreo = compile_choreography_tracks(mock_analysis, 2.0, existing_choreography=existing_choreo)
        
        s8_track = new_choreo["tracks"]["s8_gantry"]
        preserved_move = next((m for m in s8_track if m.get("block_id") == "b1" and m.get("target_pos_rom") == 88.0), None)
        
        if preserved_move:
            print("  [PASS] User edits (s8_gantry to 88%) successfully preserved after re-compile.")
        else:
            print("  [FAIL] User edits were overwritten.")
    except Exception as e:
        print(f"  [FAIL] Compilation test failed: {e}")


def run_synchronized_stop_verification():
    print("\n5. Running Synchronized Stop Verification...")
    try:
        from pi500.beat_bandit_app import BeatBanditApp
        mock_backend = MagicMock()
        
        app = BeatBanditApp(running_on_pi=False)
        app.setup(mock_backend)
        
        app.audio_client = MagicMock()
        
        # Fake active session
        app.player = MagicMock()
        
        app.stop_dance()
        
        player_stopped = app.player is None
        audio_stopped = app.audio_client.stop_playback.call_count > 0
        
        if player_stopped and audio_stopped:
            print("  [PASS] Synchronized stop verified: Audio stream stopped & Player 50Hz thread terminated.")
        else:
            print("  [FAIL] Stop logic did not simultaneously halt audio and player.")
    except Exception as e:
        print(f"  [FAIL] Synchronized stop test crashed: {e}")


if __name__ == "__main__":
    print("Beat Bandit 5-Layer Verification Suite")
    print("======================================")
    run_audio_isolation_audit()
    run_headless_simulation()
    run_hardware_leak_check()
    run_user_edit_preservation_test()
    run_synchronized_stop_verification()
    print("======================================")
    print("Audit Complete.")
