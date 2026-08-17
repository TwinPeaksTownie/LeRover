#!/usr/bin/env python3
import os
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

brain_dir = r"C:\Users\carso\.gemini\antigravity\brain"
cid = "3abf4d57-a128-41c5-a844-3b433ce40a4b"

filepath = os.path.join(brain_dir, cid, ".system_generated", "logs", "transcript_full.jsonl")
if not os.path.exists(filepath):
    filepath = os.path.join(brain_dir, cid, ".system_generated", "logs", "transcript.jsonl")

if not os.path.exists(filepath):
    print("Transcript not found.")
    sys.exit(0)

with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        try:
            data = json.loads(line)
            step = data.get("step_index", -1)
            if step in (45, 47):
                print("=" * 80)
                print(f"Step {step} | Source: {data.get('source')} | Type: {data.get('type')}")
                print(data.get("content", ""))
        except Exception as e:
            pass
