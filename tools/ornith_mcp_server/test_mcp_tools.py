"""
test_mcp_tools.py - Comprehensive Unit Test Suite for Ornith MCP Server
Tests each submodule (Speech, Audit, Hardware, Computer Use) and verifies MCP Server tool registration.
"""

import asyncio
import json
import os
import sys

# Ensure local directory is in pythonpath
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(CUR_DIR))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

import tools_speech
import tools_audit
import tools_hardware
import tools_computer_use
from server import app

def test_audit():
    print("\n--- 1. Testing tools_audit.py ---")
    
    # Test 1.1: Active Conversation Transcript
    print("Testing get_active_conversation_transcript()...")
    trans_res = tools_audit.get_active_conversation_transcript()
    print(f"  Status: {trans_res.get('status')}")
    print(f"  Conversation ID: {trans_res.get('conversation_id')}")
    print(f"  Is Turn Done: {trans_res.get('is_turn_done')}")
    print(f"  Last Step Type: {trans_res.get('last_step_type')}")
    assert trans_res.get("status") == "success", f"Transcript reading failed: {trans_res}"

    # Test 1.2: Git Diff
    print("Testing get_git_diff()...")
    diff_res = tools_audit.get_git_diff()
    print(f"  Status: {diff_res.get('status')}")
    print(f"  Has Changes: {diff_res.get('has_changes')}")
    print(f"  Modified Files: {len(diff_res.get('modified_files', []))}")
    print(f"  Untracked Files: {len(diff_res.get('untracked_files', []))}")
    assert diff_res.get("status") == "success", f"Git diff failed: {diff_res}"

    # Test 1.3: Contract Scanner against clean vs bad patterns
    print("Testing scan_code_contracts()...")
    bad_diff = """
+++ b/pi500/test_bad.py
+def parse_config(data):
+    min_val = data.get("calib_min", 0)
+    facing = data.get("facing_mode", "audience_counter")
+    homing_pos = 2048
+    head_bob_rom = intensity * max_pitch * 0.5
+    caged_roll = max(35.0, min(65.0, target_val))
+    try:
+        send_command(min_val)
+    except:
+        pass
"""
    scan_res = tools_audit.scan_code_contracts(diff_text=bad_diff)
    print(f"  Clean: {scan_res.get('clean')}")
    print(f"  Violations found: {len(scan_res.get('violations', []))}")
    for v in scan_res.get("violations", []):
        print(f"    - [{v.get('rule')}] {v.get('snippet')} -> {v.get('reason')}")
    assert not scan_res.get("clean"), "Scanner should have flagged violations in bad diff"
    assert len(scan_res.get("violations")) == 6, f"Expected 6 violations, got {len(scan_res.get('violations'))}"
    print("  [PASS] Contract scanner successfully flagged all 6 violations (fallbacks, 2048, exceptions, multipliers, cages).")

    # Test 1.4: Spoken Summary Extraction
    print("Testing extract_spoken_summary()...")
    mock_ornith_rejection = """### VERDICT
[REJECTED]

### SPOKEN_SUMMARY
I am rejecting Antigravity's implementation for violating Rule 9: Fail-Fast Schemas. Gemini was supposed to utilize manifest.json and not hardcode the values into the compiler. I will not provide approval on the build until the piping complies with the dynamic calibration contract.

### DETAILED_AUDIT
1. pi500/test_bad.py:48: Forbidden default fallback in .get()."""

    extracted = tools_audit.extract_spoken_summary(mock_ornith_rejection, "REJECTED")
    print(f"  Extracted Spoken Script: '{extracted}'")
    assert "rejecting Antigravity's implementation" in extracted
    assert "manifest.json" in extracted
    assert "approval on the build" in extracted
    print("  [PASS] Successfully extracted inferred SPOKEN_SUMMARY from Ornith response.")

    # Test 1.5: Read Workspace File
    print("Testing read_workspace_file()...")
    read_res = tools_audit.read_workspace_file("AGENTS.md", start_line=1, max_lines=10)
    assert read_res.get("status") == "success", f"Read workspace file failed: {read_res}"
    print(f"  [PASS] Read AGENTS.md lines 1-10 successfully ({read_res.get('total_lines')} total lines).")

    # Test 1.6: Insidious Evasion Pattern Detection
    print("\nTesting Insidious Evasion Pattern Detection...")
    import contract_scanner

    # Evasion 1: Python alternative fallbacks (setdefault, pop, getattr, ternary, or)
    py_evasion = """
def sneaky_handler(data, obj):
    mode = data.setdefault("mode", "default")
    speed = data.pop("speed", 500)
    limit = getattr(obj, "limit", 100)
    x = data["x"] if "x" in data else 7
    y = data["y"] or 118
"""
    py_violations = contract_scanner.scan_python_code(py_evasion, "sneaky.py")
    print(f"  Python evasion violations found: {len(py_violations)}")
    for v in py_violations:
        print(f"    - [{v.get('rule')}] Line {v.get('line')}: {v.get('reason')}")
    assert len(py_violations) == 5, f"Expected 5 Python evasion violations, got {len(py_violations)}"
    print("  [PASS] All 5 sneaky Python fallback evasions detected.")

    # Evasion 2: JavaScript alternative fallbacks (ternary, ??, ||, destructuring)
    js_evasion = """
const joyX = activeTelem.x_val !== undefined ? activeTelem.x_val : 7;
const joyY = stick.y ?? 118;
const fallbackVal = state.data || 50;
const { target = 2048 } = packet;
"""
    js_violations = contract_scanner.scan_javascript_code(js_evasion, "sneaky.js")
    print(f"  JavaScript evasion violations found: {len(js_violations)}")
    for v in js_violations:
        print(f"    - [{v.get('rule')}] Line {v.get('line')}: {v.get('reason')}")
    assert len(js_violations) >= 4, f"Expected >= 4 JS evasion violations, got {len(js_violations)}"
    print("  [PASS] All JavaScript frontend dummy fallback evasions detected.")

    # Evasion 3: HTML embedded <script> tags
    html_evasion = """
<html><body><script>
let x = telem.raw_x || 7;
let y = telem.raw_y ?? 118;
</script></body></html>
"""
    html_violations = contract_scanner.scan_html_code(html_evasion, "index.html")
    print(f"  HTML script evasion violations found: {len(html_violations)}")
    assert len(html_violations) == 2, f"Expected 2 HTML script violations, got {len(html_violations)}"
    print("  [PASS] HTML embedded <script> fallback evasions detected.")

    # Evasion 4: Declarative Contracts Registry loading
    contracts = contract_scanner.load_contracts()
    print(f"  Loaded active contracts from JSON registry: {len(contracts)}")
    assert len(contracts) >= 6, f"Expected >= 6 contracts loaded, got {len(contracts)}"
    print("  [PASS] Declarative contract registry loaded successfully.")

def test_hardware():
    print("\n--- 2. Testing tools_hardware.py ---")
    
    # Test 2.1: Non-interactive SSH Ping
    print("Testing ssh_run_command on pi4b...")
    ssh_res = tools_hardware.ssh_run_command("pi4b", "echo 'PING_PI4B_OK'")
    print(f"  Status: {ssh_res.get('status')} | Exit code: {ssh_res.get('exit_code')}")
    print(f"  Stdout: {ssh_res.get('stdout')}")
    assert ssh_res.get("status") == "success" and ssh_res.get("stdout") == "PING_PI4B_OK", "SSH Ping failed"

    # Test 2.2: Daemon log query
    print("Testing query_daemon_logs on pi4b...")
    log_res = tools_hardware.query_daemon_logs("pi4b", service_name="backend.service", lines=5)
    print(f"  Status: {log_res.get('status')} | Clean: {log_res.get('clean')} | Errors: {log_res.get('error_count')}")
    assert log_res.get("status") == "success", "Daemon log query failed"

    # Test 2.3: Telemetry check (non-colliding)
    print("Testing sample_motor_telemetry...")
    telem_res = tools_hardware.sample_motor_telemetry("pi4b")
    print(f"  Status: {telem_res.get('status')} | Source: {telem_res.get('source')}")
    assert telem_res.get("status") == "success", "Telemetry check failed"

    # Test 2.4: Target Deployment Parity Checks
    print("Testing target deployment parity checks...")
    dep_res = tools_hardware.check_target_deployments([
        "pi4b/static/js/ui.js",
        "pi4b/server.py"
    ])
    print(f"  Status: {dep_res.get('status')} | Checked: {dep_res.get('checked_files')} | All verified: {dep_res.get('all_verified')}")
    assert dep_res.get("status") == "success" and dep_res.get("all_verified"), "Production files deployment parity failed"
    print("  [PASS] Deployed files on Pi 4B match local MD5.")

    dummy_local = os.path.join(REPO_ROOT, "pi4b", "un_deployed_test_file.py")
    with open(dummy_local, "w", encoding="utf-8") as f:
        f.write("# temp test file\n")
    try:
        mismatch_res = tools_hardware.check_target_deployments([
            "pi4b/un_deployed_test_file.py"
        ])
        assert mismatch_res.get("has_mismatch"), "Missing remote file should flag mismatch"
        print("  [PASS] Un-deployed remote file correctly flagged as deployment mismatch.")
    finally:
        if os.path.exists(dummy_local):
            os.remove(dummy_local)


def test_speech():
    print("\n--- 3. Testing tools_speech.py ---")
    print("Testing Pocket TTS synthesis in Laura's voice (hf://laura)...")
    res = tools_speech.speak_laura("Ornith MCP server verification test online.", voice_url="hf://laura")
    print(f"  Status: {res.get('status')}")
    print(f"  Bytes played: {res.get('bytes_played')}")
    assert res.get("status") == "success", f"Speech synthesis/playback failed: {res}"
    print("  [PASS] Spoken audio playback completed.")

def test_computer_use():
    print("\n--- 4. Testing tools_computer_use.py ---")
    win_res = tools_computer_use.get_active_window()
    print(f"  Active Window Status: {win_res.get('status')} | Title: {win_res.get('title')}")
    
    ag_win = tools_computer_use.find_antigravity_window()
    print(f"  Antigravity Window Lookup: {ag_win.get('status')}")
    if ag_win.get("status") == "success":
        print(f"  Title: {ag_win.get('title')} | Rect: {ag_win.get('rect')}")

async def test_mcp_server():
    print("\n--- 5. Testing MCP Server Tool Registration ---")
    tools = await app.list_tools()
    print(f"Total Registered MCP Tools: {len(tools)}")
    for t in tools:
        print(f"  - {t.name}: {t.description.strip()[:60]}...")
    assert len(tools) >= 17, f"Expected >= 17 tools, found {len(tools)}"
    print(f"  [PASS] All {len(tools)} MCP tools registered with valid schemas.")

async def main():
    print("==================================================")
    print("  STARTING ORNITH MCP SERVER INTEGRATION TESTS")
    print("==================================================")
    
    test_audit()
    test_hardware()
    test_computer_use()
    test_speech()
    await test_mcp_server()
    
    print("\n==================================================")
    print("  ALL ORNITH MCP TOOLS AND SERVER TESTS PASSED!")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(main())
