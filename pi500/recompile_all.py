import sys
import json
from pathlib import Path

base_dir = Path("/home/user/so101")
sys.path.insert(0, str(base_dir / "pi500"))
from beat_studio import compile_default_choreography

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
    if duration > 0 and "beat_times" in analysis:
        choreo = compile_default_choreography(analysis, duration)
        track["choreography"] = choreo
        count += 1
        print(f"Recompiled {tid} ({track.get('title', '')}) -> {len(choreo['blocks'])} blocks, version {choreo['version']}")

with open(m_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

print(f"Successfully recompiled {count} tracks to Version 3.1.0 on Pi 500!")
