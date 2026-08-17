#!/usr/bin/env python3
import os
import json
import sys
import re

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

brain_dir = r"C:\Users\carso\.gemini\antigravity\brain"

# Target conversations from yesterday/today
cids = [
    "1b4819a1-2286-4f2e-a9e5-3c41c65c05df",
    "20d00f64-d3a4-4c1d-b119-079ef2d4f1e1",
    "088c8a1a-0b60-43c5-a036-63d50afefc4f",
    "6803fd60-c732-4814-9d57-07b2d7d81d4f",
    "39badef8-2e49-4e51-a6a0-e751e57461be",
    "3b9d496a-1250-48ff-bbcb-9b358abaa497",
    "d405c905-e8dc-4650-bcbf-be1aace9b5af",
    "bc86c8e6-ea3b-4e39-a31c-7d4b6428fcd1",
    "5694ce95-b863-4455-995b-05b3a91012b2",
    "db370404-e484-457c-ab18-4863ec4431c2",
    "f05f326b-31c4-4209-9f84-aa5f408613a0",
    "d71e3c0c-bdfa-490a-a3b7-453e8a5481cb",
    "e00d4ecd-e201-456d-8290-43962d03fa32",
    "3abf4d57-a128-41c5-a844-3b433ce40a4b"
]

print("Scanning conversation logs for API request patterns...")
for cid in cids:
    cpath = os.path.join(brain_dir, cid, ".system_generated", "logs", "transcript_full.jsonl")
    if not os.path.exists(cpath):
        cpath = cpath.replace("transcript_full.jsonl", "transcript.jsonl")
    if not os.path.exists(cpath):
        continue
        
    print("=" * 80)
    print(f"CONVERSATION: {cid}")
    
    with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
        for line_no, line in enumerate(f, 1):
            # Find stdout/stderr or model content mentioning GET/POST api endpoints or Invoke-RestMethod
            if "/api/" in line or "/pedestal" in line or "/slider" in line:
                try:
                    data = json.loads(line)
                    content = data.get("content", "")
                    # Extract HTTP request lines
                    http_lines = []
                    for cl in content.split("\n"):
                        if any(x in cl for x in ["GET /", "POST /", "api/status", "api/move", "api/pedestal", "api/slider", "api/nudge_physical"]):
                            http_lines.append(cl.strip())
                    if http_lines:
                        print(f"  Line {line_no} | Step {data.get('step_index')} | Type: {data.get('type')}")
                        for hl in http_lines[:6]:
                            print(f"    {hl}")
                        if len(http_lines) > 6:
                            print(f"    ... and {len(http_lines)-6} more request lines")
                except Exception:
                    pass
