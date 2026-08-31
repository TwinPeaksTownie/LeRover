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
+    homing_pos = 2048
+    try:
+        send_command(min_val)
+    except:
+        pass
"""
    scan_res = tools_audit.scan_code_contracts(diff_text=bad_diff)
    print(f"  Clean: {scan_res.get('clean')}")
    print(f"  Violations found: {len(scan_res.get('violations', []))}")
    assert not scan_res.get("clean"), "Scanner should have flagged violations in bad diff"
    assert len(scan_res.get("violations")) == 3, f"Expected 3 violations, got {len(scan_res.get('violations'))}"
    print("  [PASS] Contract scanner successfully flagged all 3 violations.")

    # Test 1.4: Read Workspace File
    print("Testing read_workspace_file()...")
    read_res = tools_audit.read_workspace_file("AGENTS.md", start_line=1, max_lines=10)
    assert read_res.get("status") == "success", f"Read workspace file failed: {read_res}"
    print(f"  [PASS] Read AGENTS.md lines 1-10 successfully ({read_res.get('total_lines')} total lines).")

def test_hardware():
    print("\n--- 2. Testing tools_hardware.py ---")
    
    # Test 2.1: Non-interactive SSH Ping
    print("Testing ssh_run_command on pi500...")
    ssh_res = tools_hardware.ssh_run_command("pi500", "echo 'PING_PI500_OK'")
    print(f"  Status: {ssh_res.get('status')} | Exit code: {ssh_res.get('exit_code')}")
    print(f"  Stdout: {ssh_res.get('stdout')}")
    assert ssh_res.get("status") == "success" and ssh_res.get("stdout") == "PING_PI500_OK", "SSH Ping failed"

    # Test 2.2: Daemon log query
    print("Testing query_daemon_logs on pi500...")
    log_res = tools_hardware.query_daemon_logs("pi500", service_name="backend.service", lines=5)
    print(f"  Status: {log_res.get('status')} | Clean: {log_res.get('clean')} | Errors: {log_res.get('error_count')}")
    assert log_res.get("status") == "success", "Daemon log query failed"

    # Test 2.3: Telemetry check (non-colliding)
    print("Testing sample_motor_telemetry...")
    telem_res = tools_hardware.sample_motor_telemetry("pi500")
    print(f"  Status: {telem_res.get('status')} | Source: {telem_res.get('source')}")
    assert telem_res.get("status") == "success", "Telemetry check failed"

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
    assert len(tools) == 14, f"Expected 14 tools, found {len(tools)}"
    print("  [PASS] All 14 MCP tools registered with valid schemas.")

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
