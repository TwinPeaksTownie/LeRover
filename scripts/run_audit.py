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
MCP_DIR = os.path.join(REPO_ROOT, "tools", "mcp_servers", "code_auditor")
for p in [REPO_ROOT, MCP_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import auditor

def main():
    task_summary = (
        "Decoupled monolithic Ornith supervisor into 3 distinct MCP servers: "
        "code-auditor (QA and AST contracts), device-bridge (telemetry and deployment), and voice-bridge (TTS)."
    )

    print("=== Launching Adversarial Code Review ===")
    res = auditor.query_adversarial_review(
        task_summary=task_summary,
        repo_path=REPO_ROOT
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

    out_file = os.path.join(REPO_ROOT, "code_audit_result.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(f"\nAudit results saved to {out_file}")

if __name__ == "__main__":
    main()
