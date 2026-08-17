#!/usr/bin/env python3
import os
import json
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

brain_dir = r"C:\Users\carso\.gemini\antigravity\brain"

# Yesterday was August 15th, 2026.
# We will list all conversations, sort them by creation time, and search for Servo 7 offset references.
convs = []
for cid in os.listdir(brain_dir):
    cpath = os.path.join(brain_dir, cid, ".system_generated", "logs", "transcript.jsonl")
    if os.path.exists(cpath):
        # Read the first line to get creation time
        try:
            with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline()
                if first_line:
                    data = json.loads(first_line)
                    created_at_str = data.get("created_at")
                    if created_at_str:
                        # Parse ISO timestamp
                        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                        convs.append((created_at, cid, cpath))
        except Exception:
            pass

convs.sort()

print(f"Auditing {len(convs)} conversations chronologically:")
for created_at, cid, cpath in convs:
    # Filter for August 14th, 15th, and 16th
    if not (14 <= created_at.day <= 16 and created_at.month == 8 and created_at.year == 2026):
        continue
        
    print("=" * 100)
    print(f"CONVERSATION: {cid} | Created: {created_at}")
    
    # Read the full file
    # We want to find references to Servo 7, Register 31, 1949, and offset math.
    filepath = cpath.replace("transcript.jsonl", "transcript_full.jsonl")
    if not os.path.exists(filepath):
        filepath = cpath
        
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                # Search for key terms in the line
                low_line = line.lower()
                if "1949" in low_line or "register 31" in low_line or ("servo 7" in low_line and "offset" in low_line):
                    try:
                        data = json.loads(line)
                        content = data.get("content", "")
                        # Check if this content is actually explaining the offset math
                        # We print the model responses or user inputs
                        if data.get("source") in ("MODEL", "USER_EXPLICIT") and data.get("type") in ("PLANNER_RESPONSE", "USER_INPUT"):
                            print("-" * 50)
                            print(f"Line {line_no} | Step {data.get('step_index')} | Source: {data.get('source')} | Type: {data.get('type')}")
                            # Print first 600 characters of content
                            if len(content) > 600:
                                print(content[:600] + "\n...[TRUNCATED]")
                            else:
                                print(content)
                    except Exception:
                        pass
    except Exception as e:
        print(f"Error reading {cid}: {e}")
