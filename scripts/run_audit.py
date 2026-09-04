#!/usr/bin/env python3
"""scripts/run_audit.py - Run Ornith Adversarial Review and output verdict."""

import io
import json
import os
import sys

# Ensure UTF-8 output encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_DIR = os.path.join(REPO_ROOT, "tools", "ornith_mcp_server")
for p in [REPO_ROOT, MCP_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import tools_audit

def main():
    task_summary = (
        "Overhaul of Pokéball Plus gestures (2.0s hold on Button A to arm rover with 4.25s countdown lockout, "
        "Button B emergency brake, 1.0s simultaneous A+B chord hold to cancel audio capture, "
        "Button B double-click within 1.0s to commit speech turn to LLM), "
        "unified AppManager lifecycle audio cues, and centralized audio resolution architecture "
        "without hardcoded filepaths."
    )

    print("=== Launching Ornith Adversarial Audit ===")
    res = tools_audit.query_ornith_for_review(
        task_summary=task_summary,
        repo_path=REPO_ROOT,
        speak_verdict=True
    )

    if "verdict" not in res:
        raise KeyError(f"[FAIL_FAST] Audit response missing mandatory key 'verdict'. Keys present: {sorted(res.keys())}")
    verdict = res["verdict"]

    if "spoken_summary" not in res:
        raise KeyError(f"[FAIL_FAST] Audit response missing mandatory key 'spoken_summary'. Keys present: {sorted(res.keys())}")
    spoken = res["spoken_summary"]

    print("\n=== AUDIT VERDICT ===")
    print(verdict)
    print("\n=== SPOKEN SUMMARY ===")
    print(spoken)

    out_file = os.path.join(REPO_ROOT, "ornith_audit_result.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(f"\nAudit results saved to {out_file}")

if __name__ == "__main__":
    main()
