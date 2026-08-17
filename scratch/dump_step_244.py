#!/usr/bin/env python3
import os
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

brain_dir = r"C:\Users\carso\.gemini\antigravity\brain"
cid = "3b9d496a-1250-48ff-bbcb-9b358abaa497"

filepath = os.path.join(brain_dir, cid, ".system_generated", "logs", "transcript_full.jsonl")
if not os.path.exists(filepath):
    filepath = os.path.join(brain_dir, cid, ".system_generated", "logs", "transcript.jsonl")

with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
    for line_no, line in enumerate(f, 1):
        try:
            data = json.loads(line)
            step = data.get("step_index", -1)
            if step == 244:
                print("=" * 80)
                print(f"Step {step} | Source: {data.get('source')} | Type: {data.get('type')}")
                if "tool_calls" in data:
                    print(json.dumps(data["tool_calls"], indent=2))
        except Exception:
            pass
