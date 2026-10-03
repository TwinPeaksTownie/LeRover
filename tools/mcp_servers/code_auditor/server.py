"""
server.py - 3rd-Party Adversarial Code Reviewer & AST Contract MCP Server
Exposes Gate 1 Plan Audit, Gate 2 Diff Audit, AST static contract scanning, and code navigation tools.
Completely isolated from hardware serial buses and TTS.
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

log_file = os.path.join(BASE_DIR, "mcp_server.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
logger = logging.getLogger("code_auditor_mcp")

from mcp.server.mcpserver import MCPServer
import auditor_config
import auditor

app = MCPServer(
    name="code-auditor",
    description="3rd-Party Adversarial Code Reviewer & AST Contract Auditor (NIM + LM Studio Fallback)"
)

def _reload_modules():
    global auditor_config, auditor
    auditor_config = importlib.reload(auditor_config)
    auditor = importlib.reload(auditor)

@app.tool()
def audit_implementation_plan(
    plan_path: str = None,
    task_summary: str = ""
) -> str:
    """
    Gate 1: Performs an adversarial audit of implementation_plan.md before code execution.
    Ingests chronological operator directives and checks for:
    - Rule 13: False tri-states and LLM aesthetic padding ('Rule of Three' bloat)
    - Rule 1: Fail-fast schema compliance
    - Rule 3: Dynamic calibration
    - Scope containment
    """
    _reload_modules()
    res = auditor.query_plan_review(plan_path=plan_path, task_summary=task_summary)
    return json.dumps(res, indent=2)

@app.tool()
def invoke_adversarial_review(
    task_summary: str,
    repo_path: str = r"i:\aux_servo_interface"
) -> str:
    """
    Gate 2: Invokes 3rd-party adversarial review of git diffs and codebase against project rules
    using NVIDIA NIM (cloud primary) with automatic fallback to local LM Studio.
    """
    _reload_modules()
    res = auditor.query_adversarial_review(task_summary=task_summary, repo_path=repo_path)
    return json.dumps(res, indent=2)

@app.tool()
def scan_code_contracts(diff_text: str = "", repo_path: str = r"i:\aux_servo_interface") -> str:
    """
    Performs static AST code contract scan for anti-patterns:
    - .get(key, default) in hardware/calibration paths (violates fail-fast schema)
    - Hardcoded 2048 / 0x800 neutral ticks (violates dynamic calibration)
    - Swallowed exceptions (except: pass or empty except)
    """
    _reload_modules()
    res = auditor.scan_code_contracts(diff_text=diff_text, repo_path=repo_path)
    return json.dumps(res, indent=2)

@app.tool()
def get_git_diff(repo_path: str = r"i:\aux_servo_interface") -> str:
    """
    Captures complete git diff including untracked and modified files.
    """
    _reload_modules()
    res = auditor.get_git_diff(repo_path=repo_path)
    return json.dumps(res, indent=2)

@app.tool()
def read_workspace_file(file_path: str, start_line: int = 1, max_lines: int = 500) -> str:
    """
    Reads specific lines from a workspace file on disk.
    """
    _reload_modules()
    res = auditor.read_workspace_file(file_path=file_path, start_line=start_line, max_lines=max_lines)
    return json.dumps(res, indent=2)

@app.tool()
def search_workspace_code(query: str, repo_path: str = r"i:\aux_servo_interface") -> str:
    """
    Fast, read-only search across all workspace files for symbols, function names, or patterns.
    """
    _reload_modules()
    res = auditor.search_workspace_code(query=query, repo_path=repo_path)
    return json.dumps(res, indent=2)

if __name__ == "__main__":
    logger.info("Starting Code Auditor MCP Server (stdio transport)...")
    app.run("stdio")
