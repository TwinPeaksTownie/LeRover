#!/usr/bin/env python3
"""Batch Recompilation Script for Beat Bandit Manifest."""

import sys
import json
from pathlib import Path

# Resolve base_dir dynamically for both local workspace and remote deployment
base_dir = Path(__file__).resolve().parent.parent
if not (base_dir / "library" / "beat_bandit" / "manifest.json").exists():
    p2 = Path("/home/user/so101")
    if (p2 / "library" / "beat_bandit" / "manifest.json").exists():
        base_dir = p2
    else:
        p3 = Path("/home/carson/touch_ui")
        if (p3 / "library" / "beat_bandit" / "manifest.json").exists():
            base_dir = p3

sys.path.insert(0, str(base_dir / "pi500"))
from choreography_compiler import compile_choreography_tracks, CHOREO_SCHEMA_VERSION

m_path = base_dir / "library" / "beat_bandit" / "manifest.json"
if not m_path.exists():
    print(f"Manifest not found at {m_path}")
    sys.exit(1)

with open(m_path, "r", encoding="utf-8") as f:
    manifest = json.load(f)

count = 0
for tid, track in manifest.items():
    analysis = track.get("analysis", track)
    duration = float(track.get("duration", analysis.get("duration", 0.0)))
    existing_choreo = track.get("choreography")
    if duration > 0 and "beat_times" in analysis:
        choreo = compile_choreography_tracks(analysis, duration, existing_choreography=existing_choreo)
        track["choreography"] = choreo
        count += 1
        spine = choreo.get("tracks", {}).get("spine_gaze", [])
        arch_moves = [m for m in spine if "arch" in [m.get("start_pose"), m.get("mid_pose"), m.get("end_pose"), m.get("pose_name")]]
        print(f"Recompiled {tid} ({track.get('title', '')}) -> {len(choreo['blocks'])} blocks, version {choreo['version']}, arch moves: {len(arch_moves)}")

with open(m_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

pi4b_manifest = base_dir / "pi4b" / "beat_bandit_manifest.json"
if pi4b_manifest.exists():
    with open(pi4b_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Synchronized copy to {pi4b_manifest}")

print(f"Successfully recompiled {count} tracks to Version {CHOREO_SCHEMA_VERSION} at {m_path}!")

