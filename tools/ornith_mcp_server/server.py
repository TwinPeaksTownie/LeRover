"""
server.py - Ornith MCP Server for Antigravity & LM Studio
Exposes tools for Antigravity to invoke the Ornith 1.0 35B model in LM Studio for adversarial review,
run code contract scans, verify hardware state on the Pi 4B, and speak via Laura Pocket TTS (port 8057).
"""

import asyncio
import importlib
import json
import logging
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Configure logging strictly to sys.stderr and logfile
log_file = os.path.join(BASE_DIR, "mcp_server.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
logger = logging.getLogger("ornith_mcp")

from mcp.server.mcpserver import MCPServer
import ornith_config_loader
import tools_speech
import tools_audit
import tools_hardware
import tools_computer_use
import tools_denoise

app = MCPServer(
    name="ornith-supervisor",
    description="Ornith 1.0 35B Adversarial Verification & Voice Supervision Suite"
)

def _reload_modules():
    global ornith_config_loader, tools_speech, tools_audit, tools_hardware, tools_computer_use, tools_denoise
    ornith_config_loader = importlib.reload(ornith_config_loader)
    tools_speech = importlib.reload(tools_speech)
    tools_audit = importlib.reload(tools_audit)
    tools_hardware = importlib.reload(tools_hardware)
    tools_computer_use = importlib.reload(tools_computer_use)
    tools_denoise = importlib.reload(tools_denoise)

# -----------------------------------------------------------------------------
# 1. Adversarial Review & Perception Tools
# -----------------------------------------------------------------------------

@app.tool()
def audit_implementation_plan(
    plan_path: str = None,
    task_summary: str = "",
    speak_verdict: bool = True
) -> str:
    """
    Gate 1: Performs an adversarial audit of implementation_plan.md before code execution.
    Ingests chronological operator directives (USER_INPUT steps) and verifies the plan against:
    - Rule 13: False tri-states and LLM aesthetic padding ('Rule of Three' bloat)
    - Rule 1: Fail-fast schema compliance
    - Rule 3: Dynamic calibration
    - Scope containment
    Physical deployment checks are explicitly DISABLED. Speaks the verdict via Laura TTS.
    """
    _reload_modules()
    res = tools_audit.query_ornith_for_plan_review(
        plan_path=plan_path,
        task_summary=task_summary,
        speak_verdict=speak_verdict
    )
    return json.dumps(res, indent=2)

@app.tool()
def invoke_ornith_adversarial_review(
    task_summary: str,
    repo_path: str = r"i:\aux_servo_interface",
    speak_verdict: bool = True
) -> str:
    """
    Gate 2: Invokes Ornith to perform a rigorous adversarial deployment audit
    of the codebase diffs and physical deployment status against project rules.
    If approved or blocked, announces the result to the user in Laura's voice via Pocket TTS.
    """
    _reload_modules()
    res = tools_audit.query_ornith_for_review(
        task_summary=task_summary,
        repo_path=repo_path,
        speak_verdict=speak_verdict
    )
    return json.dumps(res, indent=2)

@app.tool()
def get_git_diff(repo_path: str = r"i:\aux_servo_interface") -> str:
    """
    Captures complete git diff including untracked and modified files.
    """
    _reload_modules()
    res = tools_audit.get_git_diff(repo_path=repo_path)
    return json.dumps(res, indent=2)

@app.tool()
def scan_code_contracts(diff_text: str = "", repo_path: str = r"i:\aux_servo_interface") -> str:
    """
    Scans code diffs for anti-patterns:
    - .get(key, default) in hardware/calibration paths (violates fail-fast schema)
    - Hardcoded 2048 / 0x800 neutral ticks (must load from follower.json or calibration_aux.json)
    - Swallowed exceptions (except: pass)
    - Direct unverified /dev/ttyACM0 open statements
    """
    _reload_modules()
    res = tools_audit.scan_code_contracts(diff_text=diff_text, repo_path=repo_path)
    return json.dumps(res, indent=2)

@app.tool()
def get_active_conversation_transcript(
    brain_dir: str = r"C:\Users\carso\.gemini\antigravity\brain",
    max_turns: int = 3
) -> str:
    """
    Reads the active Antigravity conversation transcript directly from disk.
    """
    _reload_modules()
    res = tools_audit.get_active_conversation_transcript(brain_dir=brain_dir, max_turns=max_turns)
    return json.dumps(res, indent=2)

@app.tool()
def read_workspace_file(file_path: str, start_line: int = 1, max_lines: int = 500) -> str:
    """
    Reads specific lines from a file in the workspace on disk for inspection.
    """
    _reload_modules()
    res = tools_audit.read_workspace_file(file_path=file_path, start_line=start_line, max_lines=max_lines)
    return json.dumps(res, indent=2)

@app.tool()
def search_workspace_code(query: str, repo_path: str = r"i:\aux_servo_interface") -> str:
    """
    Performs a fast, read-only search across all workspace files for symbols, function names, or patterns.
    """
    _reload_modules()
    res = tools_audit.search_workspace_code(query=query, repo_path=repo_path)
    return json.dumps(res, indent=2)

# -----------------------------------------------------------------------------
# 2. Remote Hardware & System Verification Tools
# -----------------------------------------------------------------------------

@app.tool()
def ssh_run_command(node: str, command: str, timeout_sec: int = 15) -> str:
    """
    Executes a non-interactive shell command over SSH on a system node (pi4b, mac_mini).
    """
    _reload_modules()
    res = tools_hardware.ssh_run_command(node=node, command=command, timeout_sec=timeout_sec)
    return json.dumps(res, indent=2)

@app.tool()
def verify_file_deployment(local_file: str, remote_path: str, node: str = "pi4b") -> str:
    """
    Verifies State 1 of the Verification State Machine: compares local and remote MD5 checksums.
    """
    _reload_modules()
    res = tools_hardware.verify_file_deployment(local_file=local_file, remote_path=remote_path, node=node)
    return json.dumps(res, indent=2)

@app.tool()
def sample_motor_telemetry(
    node: str = "pi4b",
    endpoint_url: str = "http://192.168.0.86:8082/api/telemetry"
) -> str:
    """
    Queries live motor encoder telemetry via HTTP REST without colliding on /dev/ttyACM0 (States 2 & 3).
    """
    _reload_modules()
    res = tools_hardware.sample_motor_telemetry(node=node, endpoint_url=endpoint_url)
    return json.dumps(res, indent=2)

@app.tool()
def query_daemon_logs(node: str = "pi4b", service_name: str = "backend.service", lines: int = 50) -> str:
    """
    Verifies State 4: Scans systemd daemon logs on the target node for serial timeouts or exceptions.
    """
    _reload_modules()
    res = tools_hardware.query_daemon_logs(node=node, service_name=service_name, lines=lines)
    return json.dumps(res, indent=2)

@app.tool()
def deploy_to_pi(
    files: list,
    node: str = "pi4b",
    restart_service: str = "backend",
    verify_md5: bool = True
) -> str:
    """
    Deploys code files or directories to the Pi 4B over SFTP, verifies MD5 checksums,
    and optionally restarts target systemd services.
    """
    _reload_modules()
    res = tools_hardware.deploy_to_pi(
        files=files,
        node=node,
        restart_service=restart_service,
        verify_md5=verify_md5
    )
    return json.dumps(res, indent=2)

@app.tool()
def check_ssh_health(node: str = "pi4b") -> str:
    """
    Diagnoses SSH connectivity to the target node (Pi 4B).
    """
    _reload_modules()
    res = tools_hardware.check_ssh_health(node=node)
    return json.dumps(res, indent=2)

# -----------------------------------------------------------------------------
# 3. Speech & Voice Notification Tools
# -----------------------------------------------------------------------------

@app.tool()
def speak_laura(text: str, voice_url: str = None, target: str = None) -> str:
    """
    Synthesizes and speaks text aloud in Laura's voice using Pocket TTS (port 8057).
    target defaults to configured setting ("both", "local", or "pi4b").
    """
    _reload_modules()
    res = tools_speech.speak_laura(text=text, voice_url=voice_url, target=target)
    return json.dumps(res, indent=2)

@app.tool()
def notify_user_of_blocker(reason: str) -> str:
    """
    Speaks a high-priority spoken alert to Carson via Laura TTS when human input is required.
    """
    _reload_modules()
    res = tools_speech.notify_user_of_blocker(reason=reason)
    return json.dumps(res, indent=2)

@app.tool()
def notify_task_verified(summary: str, telemetry_delta: str = "") -> str:
    """
    Speaks an official verification completion notice in Laura's voice after all 4 verification states pass.
    """
    _reload_modules()
    res = tools_speech.notify_task_verified(summary=summary, telemetry_delta=telemetry_delta)
    return json.dumps(res, indent=2)

# -----------------------------------------------------------------------------
# 4. Computer Use & Desktop Tools
# -----------------------------------------------------------------------------

@app.tool()
def send_feedback_to_antigravity(feedback_text: str, click_send: bool = True) -> str:
    """
    Focuses the Antigravity IDE, clicks the chat input textarea using relative window coordinates,
    and pastes the feedback text.
    """
    _reload_modules()
    res = tools_computer_use.send_feedback_to_antigravity(feedback_text=feedback_text, click_send=click_send)
    return json.dumps(res, indent=2)

@app.tool()
def get_active_window() -> str:
    """
    Returns the title, handle (HWND), and process name of the currently active window on the desktop.
    """
    _reload_modules()
    res = tools_computer_use.get_active_window()
    return json.dumps(res, indent=2)

# -----------------------------------------------------------------------------
# 5. Denoising & Agent-to-Agent Handoff Tools
# -----------------------------------------------------------------------------

@app.tool()
def summarize_latest_turn(
    audio_target: str = "both",
    brain_dir: str = r"C:\Users\carso\.gemini\antigravity\brain"
) -> str:
    """
    Extracts Antigravity's latest response from active conversation transcript,
    submits to Ornith 1.0 in LM Studio for executive denoising, and speaks a 35-60 word
    BLUF summary via Pocket TTS (PC and Pi 4B kiosk).
    """
    _reload_modules()
    trans = tools_audit.get_active_conversation_transcript(brain_dir=brain_dir, max_turns=2)
    if trans.get("status") != "success":
        return json.dumps({"status": "error", "error": "Could not read transcript", "details": trans})
    
    raw_response = trans.get("latest_assistant_response", "")
    if not raw_response:
        return json.dumps({"status": "error", "error": "No assistant response found in active transcript"})
    
    denoise_res = tools_denoise.distill_response(raw_text=raw_response)
    if denoise_res.get("status") != "success":
        return json.dumps(denoise_res)
    
    distilled_text = denoise_res.get("distilled_text", "")
    speech_res = tools_speech.speak_laura(text=distilled_text, target=audio_target)
    
    return json.dumps({
        "status": "success",
        "distilled_text": distilled_text,
        "word_count": denoise_res.get("word_count", 0),
        "audio_dispatch": speech_res
    }, indent=2)

@app.tool()
def signal_task_complete(summary: str, status: str = "success") -> str:
    """
    Explicit hand-off tool that Antigravity calls upon finishing an assigned task.
    Signals to Ornith supervisor that execution is concluded and ready for verification.
    """
    _reload_modules()
    logger.info(f"Antigravity signaled task completion: status={status}, summary={summary}")
    return json.dumps({
        "status": "handoff_acknowledged",
        "task_status": status,
        "summary": summary,
        "message": "Ornith supervisor acknowledged task handoff."
    }, indent=2)

if __name__ == "__main__":
    logger.info("Starting Ornith MCP Server (stdio transport)...")
    app.run("stdio")
