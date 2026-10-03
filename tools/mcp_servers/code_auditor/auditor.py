"""
auditor.py - 3rd-Party Adversarial Code Reviewer & AST Contract Auditor
Performs Gate 1 Plan Audit and Gate 2 Diff Audit using NVIDIA NIM with automatic LM Studio fallback.
Also performs static AST contract scanning without external model dependencies.
"""

import ast
import glob
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional, Any

import requests
import auditor_config

logger = logging.getLogger("code_auditor")
REPO_ROOT = auditor_config.REPO_ROOT

IGNORE_EXTENSIONS = {
    ".pyc", ".pyd", ".log", ".bin", ".zip", ".tar", ".gz", ".exe", ".dll", ".so", ".db", ".png", ".jpg", ".jpeg", ".wav", ".mp3"
}

def _log_debug(msg: str):
    sys.stderr.write(f"[CODE_AUDITOR] {msg}\n")
    sys.stderr.flush()

def get_git_diff(repo_path: str = None, max_chars: int = 2000000) -> dict:
    if repo_path is None:
        repo_path = REPO_ROOT

    if not os.path.exists(repo_path):
        return {"status": "error", "error": f"Repository path not found: {repo_path}"}

    try:
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True
        )
        status_output = status_proc.stdout or ""

        modified_files = []
        untracked_files = []
        for line in status_output.splitlines():
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            status_code = line[:2]
            filename = line[3:].strip()
            _, ext = os.path.splitext(filename.lower())
            if ext in IGNORE_EXTENSIONS:
                continue
            if status_code.startswith("?"):
                untracked_files.append(filename)
            else:
                modified_files.append(filename)

        diff_proc = subprocess.run(
            ["git", "diff", "HEAD", "--", ".", ":!*manifest.json"],
            cwd=repo_path,
            capture_output=True,
            encoding="utf-8",
            errors="replace"
        )
        diff_text = diff_proc.stdout or ""

        # If clean, audit HEAD~1..HEAD
        if not diff_text.strip() and not modified_files:
            recent_diff = subprocess.run(
                ["git", "diff", "HEAD~1..HEAD", "--", ".", ":!*manifest.json"],
                cwd=repo_path,
                capture_output=True,
                encoding="utf-8",
                errors="replace"
            )
            if recent_diff.stdout and recent_diff.stdout.strip():
                diff_text = recent_diff.stdout
                recent_files = subprocess.run(
                    ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                    cwd=repo_path,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace"
                )
                if recent_files.stdout:
                    for f in recent_files.stdout.splitlines():
                        f = f.strip()
                        _, ext = os.path.splitext(f.lower())
                        if f and ext not in IGNORE_EXTENSIONS:
                            modified_files.append(f)

        untracked_diffs = []
        for u_file in untracked_files:
            u_path = os.path.join(repo_path, u_file)
            if os.path.isfile(u_path):
                try:
                    with open(u_path, "r", encoding="utf-8", errors="replace") as f:
                        u_content = f.read()
                    untracked_diffs.append(f"--- /dev/null\n+++ b/{u_file}\n@@ -0,0 +1 @@\n+{u_content}")
                except Exception:
                    pass

        full_diff = diff_text + ("\n" + "\n".join(untracked_diffs) if untracked_diffs else "")
        if len(full_diff) > max_chars:
            full_diff = full_diff[:max_chars] + f"\n... [Diff truncated to {max_chars} chars]"

        return {
            "status": "success",
            "modified_files": modified_files,
            "untracked_files": untracked_files,
            "diff": full_diff
        }
    except Exception as e:
        return {"status": "error", "error": f"Failed to get git diff: {str(e)}"}

class ContractVisitor(ast.NodeVisitor):
    def __init__(self, filename: str, is_hardware_or_calibration: bool):
        self.filename = filename
        self.is_hw = is_hardware_or_calibration
        self.violations = []
        self.warnings = []

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if self.is_hw and len(node.args) >= 2:
                default_arg = node.args[1]
                default_val = "non-None"
                if isinstance(default_arg, ast.Constant):
                    default_val = repr(default_arg.value)
                self.violations.append({
                    "rule": "FAIL_FAST_SCHEMA",
                    "file": self.filename,
                    "line": node.lineno,
                    "snippet": f".get(..., {default_val})",
                    "reason": "Direct bracket access required. Default fallbacks mask corrupted or missing JSON configs."
                })
        self.generic_visit(node)

    def visit_Constant(self, node):
        if self.is_hw and isinstance(node.value, int) and node.value == 2048:
            self.violations.append({
                "rule": "DYNAMIC_CALIBRATION",
                "file": self.filename,
                "line": node.lineno,
                "snippet": "2048",
                "reason": "Hardcoded 2048 tick neutral pose violates dynamic calibration schema."
            })
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        if not node.body:
            self.violations.append({
                "rule": "NO_SWALLOWED_EXCEPTIONS",
                "file": self.filename,
                "line": node.lineno,
                "snippet": "except: (empty)",
                "reason": "Empty exception handler completely swallows errors."
            })
        elif len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self.violations.append({
                "rule": "NO_SWALLOWED_EXCEPTIONS",
                "file": self.filename,
                "line": node.lineno,
                "snippet": "except: pass",
                "reason": "Swallowing exceptions with pass hides hardware and parsing failures."
            })
        self.generic_visit(node)

def scan_code_contracts(diff_text: str = "", repo_path: str = None) -> dict:
    if repo_path is None:
        repo_path = REPO_ROOT

    if not diff_text or not diff_text.strip():
        diff_res = get_git_diff(repo_path)
        if diff_res["status"] == "success":
            diff_text = diff_res["diff"]
            all_changed_files = list(dict.fromkeys(diff_res["modified_files"] + diff_res["untracked_files"]))
        else:
            all_changed_files = []
    else:
        all_changed_files = []

    violations = []
    warnings = []

    for f in all_changed_files:
        if not f.endswith(".py"):
            continue
        full_path = os.path.join(repo_path, f)
        if not os.path.exists(full_path):
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as py_file:
                source = py_file.read()
            tree = ast.parse(source, filename=f)
            is_hw = any(p in f.lower() for p in ["motor", "servo", "hardware", "serial", "feetech", "rover", "teleop", "gesture", "pose", "calibration"])
            visitor = ContractVisitor(filename=f, is_hardware_or_calibration=is_hw)
            visitor.visit(tree)
            violations.extend(visitor.violations)
            warnings.extend(visitor.warnings)
        except SyntaxError as e:
            violations.append({
                "rule": "SYNTAX_ERROR",
                "file": f,
                "line": e.lineno or 1,
                "snippet": str(e.text or "").strip(),
                "reason": f"Python syntax error: {e.msg}"
            })
        except Exception as e:
            warnings.append({
                "rule": "AST_PARSE_FAILURE",
                "file": f,
                "line": 1,
                "snippet": "",
                "reason": f"Could not parse AST: {str(e)}"
            })

    deduped = []
    seen = set()
    for v in violations:
        key = (v.get("rule"), v.get("file"), v.get("line"), v.get("reason"))
        if key not in seen:
            seen.add(key)
            deduped.append(v)

    return {
        "status": "success",
        "clean": len(deduped) == 0,
        "violations": deduped,
        "warnings": warnings,
        "changed_files": all_changed_files,
        "audit_summary": f"AST Scan complete: {len(deduped)} violations across {len(all_changed_files)} changed files."
    }

def read_workspace_file(file_path: str, start_line: int = 1, max_lines: int = 500) -> dict:
    if not os.path.isabs(file_path):
        file_path = os.path.join(REPO_ROOT, file_path)
    if not os.path.exists(file_path):
        return {"status": "error", "error": f"File not found: {file_path}"}

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total_lines = len(lines)
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, start_idx + max_lines)
        chunk = "".join(lines[start_idx:end_idx])
        return {
            "status": "success",
            "file": file_path,
            "start_line": start_idx + 1,
            "end_line": end_idx,
            "total_lines": total_lines,
            "content": chunk
        }
    except Exception as e:
        return {"status": "error", "error": f"Failed to read file: {str(e)}"}

def search_workspace_code(query: str, repo_path: str = None, max_matches: int = 100) -> dict:
    if repo_path is None:
        repo_path = REPO_ROOT
    if not os.path.exists(repo_path):
        return {"status": "error", "error": f"Repo path not found: {repo_path}"}

    matches = []
    ignored_dirs = {".git", "__pycache__", ".gemini", "node_modules", ".venv", "venv"}
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    extensions = [".py", ".json", ".js", ".html", ".md", ".sh", ".service"]

    try:
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, repo_path)
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                            for idx, line in enumerate(f, start=1):
                                if pattern.search(line):
                                    matches.append({
                                        "file": rel_path,
                                        "line": idx,
                                        "content": line.strip()
                                    })
                                    if len(matches) >= max_matches:
                                        return {"status": "success", "query": query, "matches_count": len(matches), "capped": True, "matches": matches}
                    except Exception:
                        continue
        return {"status": "success", "query": query, "matches_count": len(matches), "capped": False, "matches": matches}
    except Exception as e:
        return {"status": "error", "error": f"Search failed: {str(e)}"}

def get_operator_directives(brain_dir: str = None) -> list:
    if brain_dir is None:
        brain_dir = os.environ.get("BRAIN_DIR", r"C:\Users\carso\.gemini\antigravity\brain" if os.name == "nt" else "/brain")
    if not os.path.exists(brain_dir):
        return []

    search_pattern = os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl")
    transcript_files = glob.glob(search_pattern)
    if not transcript_files:
        return []

    transcript_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    latest_transcript = transcript_files[0]
    directives = []

    with open(latest_transcript, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                step = json.loads(line)
            except Exception:
                continue
            if step.get("type") == "USER_INPUT":
                raw = str(step.get("content", "")).strip()
                clean = re.sub(r"<USER_REQUEST>\s*", "", raw)
                clean = re.sub(r"\s*</USER_REQUEST>", "", clean)
                clean = re.sub(r"<ADDITIONAL_METADATA>[\s\S]*?</ADDITIONAL_METADATA>", "", clean)
                clean = re.sub(r"<USER_SETTINGS_CHANGE>[\s\S]*?</USER_SETTINGS_CHANGE>", "", clean).strip()
                if clean:
                    directives.append({"step_index": step.get("step_index"), "text": clean})
    return directives

def _dispatch_inference(system_prompt: str, user_prompt: str) -> dict:
    cfg = auditor_config.get_config()
    backends_to_try = []

    active_backend = cfg.get("active_backend", "nim")
    if active_backend == "nim":
        backends_to_try.append(("nim", cfg["nim_url"], cfg["nim_model"]))
        backends_to_try.append(("lm_studio", cfg["lm_studio_url"], cfg["lm_studio_model"]))
    else:
        backends_to_try.append(("lm_studio", cfg["lm_studio_url"], cfg["lm_studio_model"]))
        backends_to_try.append(("nim", cfg["nim_url"], cfg["nim_model"]))

    last_error = None
    for backend_name, url, model in backends_to_try:
        headers = {"Content-Type": "application/json"}
        if backend_name == "nim":
            try:
                api_key = auditor_config.get_secret("NVIDIA_API_KEY")
                headers["Authorization"] = f"Bearer {api_key}"
            except Exception as e:
                _log_debug(f"NIM API key missing or unreadable: {e}. Skipping NIM.")
                last_error = f"NIM API key missing: {e}"
                continue

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": int(cfg.get("max_tokens", 4096)),
            "temperature": float(cfg.get("temperature", 0.1)),
            "stream": False
        }

        _log_debug(f"Attempting review via {backend_name} ({model}) at {url}...")
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                content = str(msg.get("content", "") or "")
                reasoning = str(msg.get("reasoning_content", "") or "")
                output = content if content else reasoning
                if output.strip():
                    return {"status": "success", "backend": backend_name, "model": model, "raw_output": output.strip()}
            else:
                last_error = f"{backend_name} HTTP {resp.status_code}: {resp.text}"
                _log_debug(f"{backend_name} failed with HTTP {resp.status_code}. Trying next backend...")
        except Exception as e:
            last_error = f"{backend_name} exception: {str(e)}"
            _log_debug(f"{backend_name} failed: {e}. Trying next backend...")

    return {"status": "error", "error": f"All inference backends failed. Last error: {last_error}"}

def query_plan_review(plan_path: str = None, task_summary: str = "") -> dict:
    brain_dir = os.environ.get("BRAIN_DIR", r"C:\Users\carso\.gemini\antigravity\brain" if os.name == "nt" else "/brain")

    if not plan_path:
        search_pattern = os.path.join(brain_dir, "*", "implementation_plan.md")
        candidate_plans = glob.glob(search_pattern)
        if candidate_plans:
            candidate_plans.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            plan_path = candidate_plans[0]
        else:
            repo_plan = os.path.join(REPO_ROOT, "implementation_plan.md")
            if os.path.exists(repo_plan):
                plan_path = repo_plan
            else:
                return {"status": "error", "error": "Could not locate implementation_plan.md"}

    if not os.path.exists(plan_path):
        return {"status": "error", "error": f"Plan file not found: {plan_path}"}

    with open(plan_path, "r", encoding="utf-8", errors="replace") as f:
        plan_content = f.read()

    directives = get_operator_directives(brain_dir=brain_dir)
    directives_formatted = "\n".join(f"Turn {d['step_index']}: {d['text']}" for d in directives) if directives else "No previous directives recorded."
    if task_summary:
        directives_formatted += f"\n\nContext & Directives:\n{task_summary}"

    system_prompt = """You are the 3rd-Party Adversarial Code Reviewer & Architecture Supervisor.
Your job in GATE 1 (BUILD PLAN AUDIT) is to rigorously audit the proposed implementation plan BEFORE code is written.

Strictly enforce:
1. RULE 13 - ANTI-SLOP & FALSE TRI-STATES: Zero tolerance for logic padded to satisfy the LLM 'rule of three'. If options, flags, or states are padded with redundant 3rd options for aesthetic balance, REJECT the plan.
2. RULE 1 - FAIL-FAST SCHEMA: Direct bracket access only. Reject plans introducing .get() fallbacks or swallowed exceptions.
3. RULE 3 - DYNAMIC CALIBRATION: Zero tolerance for hardcoded 2048 ticks or fixed limits. Motor bounds must load dynamically.
4. SCOPE CONTAINMENT: Plan must satisfy operator directives without unprompted refactoring of unrelated subsystems.

Format your output strictly as:
### VERDICT
[APPROVED], [REJECTED], or [BLOCKER]

### SPOKEN_SUMMARY
Concise 2-to-3 sentence plain text summary (under 60 words, no markdown symbols).

### DETAILED_AUDIT
Detailed breakdown of contract compliance or violations."""

    user_prompt = f"""=== OPERATOR DIRECTIVES ===\n{directives_formatted}\n\n=== PROPOSED PLAN ===\n{plan_content}"""
    res = _dispatch_inference(system_prompt, user_prompt)
    if res["status"] != "success":
        return res

    raw = res["raw_output"]
    verdict_match = re.search(r'###\s*VERDICT\s*\n\s*\[?(APPROVED|REJECTED|BLOCKER)\]?', raw, re.IGNORECASE)
    verdict = verdict_match.group(1).upper() if verdict_match else ("APPROVED" if "[APPROVED]" in raw.upper() else "BLOCKER")

    spoken_match = re.search(r'###\s*SPOKEN_SUMMARY\s*\n(.*?)(?=\n###|\Z)', raw, re.DOTALL | re.IGNORECASE)
    spoken_summary = spoken_match.group(1).strip() if spoken_match else ""

    return {
        "status": "success",
        "verdict": verdict,
        "backend_used": res["backend"],
        "spoken_summary": re.sub(r'[*_`#\\[\\]]', '', spoken_summary),
        "detailed_audit": raw
    }

def query_adversarial_review(task_summary: str, diff_text: str = "", repo_path: str = None) -> dict:
    if repo_path is None:
        repo_path = REPO_ROOT

    if not diff_text:
        diff_res = get_git_diff(repo_path)
        if diff_res["status"] != "success":
            return diff_res
        diff_text = diff_res["diff"]

    contract_res = scan_code_contracts(diff_text=diff_text, repo_path=repo_path)

    system_prompt = """You are the 3rd-Party Adversarial Code Reviewer & Architecture Supervisor.
Your job in GATE 2 (PRE-COMMIT DEPLOYMENT AUDIT) is to rigorously audit code diffs against project rules:
1. FAIL-FAST SCHEMA: Direct bracket access only. No .get(key, default) or inline fallbacks in hardware/calibration paths.
2. DYNAMIC CALIBRATION: No hardcoded 2048 ticks. Limits and poses must resolve dynamically from configuration.
3. NO SWALLOWED EXCEPTIONS: No empty except blocks or 'except: pass'.
4. STRICT SRP & CLEAN ARCHITECTURE: Preserves separation of concerns across producer and consumer services.

Format your output strictly as:
### VERDICT
[APPROVED], [REJECTED], or [BLOCKER]

### SPOKEN_SUMMARY
Concise 2-to-3 sentence plain text summary (under 60 words, no markdown symbols).

### DETAILED_AUDIT
Detailed findings and rule compliance."""

    user_prompt = f"""=== TASK SUMMARY ===\n{task_summary}\n\n=== STATIC AST CONTRACT SCAN ===\n{json.dumps(contract_res, indent=2)}\n\n=== GIT DIFF ===\n{diff_text}"""
    res = _dispatch_inference(system_prompt, user_prompt)
    if res["status"] != "success":
        return res

    raw = res["raw_output"]
    verdict_match = re.search(r'###\s*VERDICT\s*\n\s*\[?(APPROVED|REJECTED|BLOCKER)\]?', raw, re.IGNORECASE)
    verdict = verdict_match.group(1).upper() if verdict_match else ("APPROVED" if "[APPROVED]" in raw.upper() else "BLOCKER")

    spoken_match = re.search(r'###\s*SPOKEN_SUMMARY\s*\n(.*?)(?=\n###|\Z)', raw, re.DOTALL | re.IGNORECASE)
    spoken_summary = spoken_match.group(1).strip() if spoken_match else ""

    return {
        "status": "success",
        "verdict": verdict,
        "backend_used": res["backend"],
        "static_contracts": contract_res,
        "spoken_summary": re.sub(r'[*_`#\\[\\]]', '', spoken_summary),
        "detailed_audit": raw
    }
