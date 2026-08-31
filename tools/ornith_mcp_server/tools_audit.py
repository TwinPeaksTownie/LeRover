"""
tools_audit.py - Perception & Codebase Audit Tooling for Ornith Supervisor
Provides functions to read the active Antigravity conversation transcript directly from disk,
capture untracked and modified git diffs (filtering binary files and logs), scan diffs for banned anti-patterns,
and query the Ornith 1.0 35B model in LM Studio for full adversarial review.
All logging is directed strictly to sys.stderr.
"""

import glob
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
import tools_speech

DEFAULT_LM_STUDIO_URL = os.environ.get(
    "LM_STUDIO_URL",
    "http://127.0.0.1:1234/v1/chat/completions" if os.name == "nt" else "http://host.docker.internal:1234/v1/chat/completions"
)

IGNORE_EXTENSIONS = {
    ".wav", ".mp3", ".ogg", ".flac", ".png", ".jpg", ".jpeg", ".gif",
    ".pyc", ".pyd", ".log", ".bin", ".zip", ".tar", ".gz", ".exe", ".dll", ".so", ".db"
}

def _log_debug(msg: str):
    sys.stderr.write(f"[AUDIT] {msg}\n")
    sys.stderr.flush()

def get_active_conversation_transcript(
    brain_dir: str = None,
    max_turns: int = 3
) -> dict:
    """
    Reads the active Antigravity conversation transcript directly from disk.
    """
    if brain_dir is None:
        brain_dir = os.environ.get("BRAIN_DIR", r"C:\Users\carso\.gemini\antigravity\brain" if os.name == "nt" else "/brain")

    if not os.path.exists(brain_dir):
        return {"status": "error", "error": f"Brain directory not found: {brain_dir}"}

    search_pattern = os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl")
    transcript_files = glob.glob(search_pattern)
    
    if not transcript_files:
        return {"status": "error", "error": f"No transcript files found under {brain_dir}"}

    transcript_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    latest_transcript = transcript_files[0]
    conv_id = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(latest_transcript))))
    
    _log_debug(f"Found active conversation transcript: {conv_id} ({latest_transcript})")
    
    steps = []
    try:
        with open(latest_transcript, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    steps.append(json.loads(line))
    except Exception as e:
        return {"status": "error", "error": f"Failed to read transcript file: {str(e)}"}

    if not steps:
        return {"status": "error", "error": f"Transcript file {latest_transcript} is empty"}

    last_step = steps[-1]
    last_type = last_step.get("type", "UNKNOWN")
    last_status = last_step.get("status", "UNKNOWN")
    last_source = last_step.get("source", "UNKNOWN")
    
    is_turn_done = (last_type == "PLANNER_RESPONSE" and last_status == "DONE" and "tool_calls" not in last_step)
    
    latest_assistant_response = ""
    latest_user_request = ""
    
    for step in reversed(steps):
        st_type = step.get("type")
        content = step.get("content", "")
        if st_type == "PLANNER_RESPONSE" and not latest_assistant_response and content:
            latest_assistant_response = content
        elif st_type == "USER_INPUT" and not latest_user_request and content:
            latest_user_request = content
        if latest_assistant_response and latest_user_request:
            break

    recent_history = []
    for step in steps[-max_turns * 2:]:
        recent_history.append({
            "step_index": step.get("step_index"),
            "type": step.get("type"),
            "status": step.get("status"),
            "content_preview": (step.get("content") or "")[:200]
        })

    return {
        "status": "success",
        "conversation_id": conv_id,
        "transcript_path": latest_transcript,
        "is_turn_done": is_turn_done,
        "last_step_type": last_type,
        "last_step_status": last_status,
        "last_step_source": last_source,
        "latest_assistant_response": latest_assistant_response,
        "latest_user_request": latest_user_request,
        "recent_history": recent_history
    }

def get_git_diff(repo_path: str = None, max_chars: int = 25000) -> dict:
    """
    Captures complete git diff including untracked and modified text source files.
    """
    if repo_path is None:
        repo_path = os.environ.get("REPO_PATH", r"i:\aux_servo_interface" if os.name == "nt" else "/workspace")

    if not os.path.exists(repo_path):
        return {"status": "error", "error": f"Repository path not found: {repo_path}"}

    try:
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        status_output = status_proc.stdout.strip()
        
        modified_files = []
        untracked_files = []
        for line in status_output.splitlines():
            line = line.strip()
            if not line:
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
            text=True
        )
        diff_text = diff_proc.stdout

        # If no uncommitted diffs, inspect recent code commits (HEAD~4..HEAD)
        if not diff_text.strip() and not untracked_files:
            diff_proc_last = subprocess.run(
                ["git", "diff", "HEAD~4..HEAD", "--", ".", ":!*manifest.json"],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            if diff_proc_last.returncode == 0 and diff_proc_last.stdout.strip():
                diff_text = f"=== RECENT COMMITS DIFF (HEAD~4..HEAD) ===\n\n" + diff_proc_last.stdout

        untracked_diffs = []
        for ufile in untracked_files:
            full_path = os.path.join(repo_path, ufile)
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        u_content = f.read()
                    lines = u_content.splitlines()
                    untracked_diffs.append(f"--- /dev/null\n+++ b/{ufile}\n@@ -0,0 +1,{len(lines)} @@\n" + "\n".join("+" + l for l in lines))
                except Exception as e:
                    untracked_diffs.append(f"[Untracked file read error: {ufile} ({e})]")

        full_diff = diff_text
        if untracked_diffs:
            full_diff += "\n\n=== UNTRACKED FILES ===\n\n" + "\n\n".join(untracked_diffs)

        if len(full_diff) > max_chars:
            full_diff = full_diff[:max_chars] + f"\n\n[... Truncated: diff exceeded {max_chars} characters ...]"

        return {
            "status": "success",
            "repo_path": repo_path,
            "has_changes": bool(modified_files or untracked_files),
            "modified_files": modified_files,
            "untracked_files": untracked_files,
            "status_summary": status_output,
            "diff": full_diff
        }
    except Exception as e:
        return {"status": "error", "error": f"Failed to get git diff: {str(e)}"}

def scan_code_contracts(diff_text: str = "", repo_path: str = None) -> dict:
    if repo_path is None:
        repo_path = os.environ.get("REPO_PATH", r"i:\aux_servo_interface" if os.name == "nt" else "/workspace")

    if not diff_text:
        diff_res = get_git_diff(repo_path)
        if diff_res.get("status") != "success":
            return diff_res
        diff_text = diff_res.get("diff", "")

    if not diff_text.strip():
        return {
            "status": "success",
            "clean": True,
            "violations": [],
            "warnings": [],
            "audit_summary": "No changes detected in repository diff."
        }

    violations = []
    warnings = []
    current_file = "unknown"
    lines = diff_text.splitlines()
    prev_except_line = None
    
    for line_idx, line in enumerate(lines, 1):
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            prev_except_line = None
            continue
        elif line.startswith("+++ "):
            current_file = line[4:].strip()
            prev_except_line = None
            continue

        if not line.startswith("+") or line.startswith("+++"):
            continue

        code_line = line[1:].strip()
        if code_line.startswith("#") or code_line.startswith("//"):
            continue

        if re.search(r'\.get\s*\(\s*["\'](calib_min|calib_max|homing_offset|position|target|angle|servo_id)["\']\s*,\s*[^)]+\)', code_line):
            violations.append({
                "rule": "FAIL_FAST_CALIBRATION_SCHEMA",
                "file": current_file,
                "line": line_idx,
                "snippet": code_line,
                "reason": "Forbidden fallback default in .get() for hardware/calibration parameters. Must fail-fast with KeyError."
            })

        if re.search(r'\b(2048|0x800)\b', code_line) and not current_file.lower().endswith((".md", ".json")):
            if any(k in code_line.lower() for k in ["pos", "target", "neutral", "center", "homing", "offset", "default"]):
                violations.append({
                    "rule": "NO_HARDCODED_2048_NEUTRAL",
                    "file": current_file,
                    "line": line_idx,
                    "snippet": code_line,
                    "reason": "Hardcoded 2048/0x800 neutral detected. Offsets and bounds must load dynamically from follower.json or calibration_aux.json."
                })

        if re.search(r'except(\s+\w+)?:(\s*pass|\s*\.\.\.)\b', code_line):
            violations.append({
                "rule": "NO_SWALLOWED_EXCEPTIONS",
                "file": current_file,
                "line": line_idx,
                "snippet": code_line,
                "reason": "Swallowed exception detected ('except: pass'). Must raise descriptive error or log explicit traceback."
            })
            prev_except_line = None
        elif re.search(r'except(\s+\w+)?:', code_line):
            prev_except_line = (line_idx, code_line)
        elif prev_except_line and code_line in ("pass", "..."):
            violations.append({
                "rule": "NO_SWALLOWED_EXCEPTIONS",
                "file": current_file,
                "line": line_idx,
                "snippet": f"{prev_except_line[1]} -> {code_line}",
                "reason": "Swallowed exception detected (multiline except -> pass). Must raise descriptive error or log explicit traceback."
            })
            prev_except_line = None
        else:
            if code_line:
                prev_except_line = None

        if "/dev/ttyACM0" in code_line and "serial.Serial" in code_line:
            warnings.append({
                "rule": "SERIAL_BUS_LOCK_HYGIENE",
                "file": current_file,
                "line": line_idx,
                "snippet": code_line,
                "reason": "Direct serial.Serial on /dev/ttyACM0 may collide with backend.service. Use HTTP REST telemetry or verify port isolation first."
            })

    clean = len(violations) == 0
    summary = f"Audit complete: {len(violations)} violations, {len(warnings)} warnings found across diff."
    
    return {
        "status": "success",
        "clean": clean,
        "violations": violations,
        "warnings": warnings,
        "audit_summary": summary
    }

def query_ornith_for_review(
    task_summary: str,
    diff_text: str = "",
    repo_path: str = None,
    speak_verdict: bool = True,
    lm_studio_url: str = None
) -> dict:
    if repo_path is None:
        repo_path = os.environ.get("REPO_PATH", r"i:\aux_servo_interface" if os.name == "nt" else "/workspace")
    if lm_studio_url is None:
        lm_studio_url = DEFAULT_LM_STUDIO_URL

    if not diff_text:
        diff_res = get_git_diff(repo_path)
        if diff_res.get("status") != "success":
            return diff_res
        diff_text = diff_res.get("diff", "")

    contract_res = scan_code_contracts(diff_text=diff_text, repo_path=repo_path)
    
    system_prompt = """You are Ornith, the adversarial code reviewer and hardware supervisor for the SO-101 robotic arm and touch UI system.
Your job is to strictly enforce the following rules:
1. FAIL-FAST SCHEMA: No .get(key, default) or 'or <default>' fallbacks for hardware/calibration parameters. Raise KeyError immediately.
2. DYNAMIC CALIBRATION: No hardcoded 2048 or 0x800 neutral ticks. Offsets and bounds must load from follower.json (servos 1-6) or calibration_aux.json (servos 7-8).
3. NO SWALLOWED EXCEPTIONS: No 'except: pass' or unhandled generic catches.
4. MANDATORY 4-STATE VERIFICATION: (1) Sync MD5, (2) Bi-directional cycle, (3) Telemetry audit, (4) Human confirmation.
5. MUSICAL UNITS: Choreography divisions must use measures, beats, 4bars, 8bars.

Evaluate the git diff against the task summary and these strict rules.
State your verdict clearly at the top as: [APPROVED], [REJECTED], or [BLOCKER].
Then explain the exact reasons, line-by-line violations, and recommended corrections."""

    user_prompt = f"""Task Summary: {task_summary}

Static Contract Scan Result:
- Clean: {contract_res.get('clean')}
- Rule Violations: {len(contract_res.get('violations', []))}
- Warnings: {len(contract_res.get('warnings', []))}

Repository Changes (Git Diff):
```diff
{diff_text if diff_text.strip() else 'No unstaged or staged diffs.'}
```

Provide your adversarial audit:"""

    payload = {
        "model": "ornith-1.0-35b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 4096,
        "temperature": 0.2
    }

    _log_debug(f"Querying Ornith 1.0 35B at {lm_studio_url} (payload chars: {len(user_prompt)})...")
    try:
        req = urllib.request.Request(
            lm_studio_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=90) as res:
            data = json.loads(res.read())
            content = data["choices"][0]["message"].get("content", "")
            reasoning = data["choices"][0]["message"].get("reasoning_content", "")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        _log_debug(f"LM Studio HTTP {e.code}: {err_body}")
        return {
            "status": "error",
            "error": f"LM Studio returned HTTP {e.code}: {err_body}",
            "static_contracts": contract_res
        }
    except Exception as e:
        _log_debug(f"Failed to query LM Studio: {e}")
        return {
            "status": "error",
            "error": f"Failed to communicate with Ornith in LM Studio ({lm_studio_url}): {str(e)}",
            "static_contracts": contract_res
        }

    verdict_text = content.strip()
    is_approved = "[APPROVED]" in verdict_text.upper()
    is_rejected = "[REJECTED]" in verdict_text.upper()
    is_blocker = "[BLOCKER]" in verdict_text.upper()

    spoken_status = "not_spoken"
    if speak_verdict:
        try:
            if is_approved:
                tools_speech.notify_task_verified(f"Task '{task_summary}' approved by Ornith audit.")
                spoken_status = "spoken_approval"
            elif is_blocker:
                tools_speech.notify_user_of_blocker(f"Ornith identified a blocker on '{task_summary}'.")
                spoken_status = "spoken_blocker"
            elif is_rejected:
                tools_speech.speak_laura(f"Ornith supervisor has rejected the changes for '{task_summary}'. Please review the audit feedback.")
                spoken_status = "spoken_rejection"
        except Exception as e:
            _log_debug(f"Speech notification error: {e}")

    return {
        "status": "success",
        "task_summary": task_summary,
        "verdict": "APPROVED" if is_approved else ("REJECTED" if is_rejected else ("BLOCKER" if is_blocker else "REVIEW_COMPLETED")),
        "verdict_text": verdict_text,
        "reasoning_summary": reasoning[:400],
        "spoken_status": spoken_status,
        "static_contracts": contract_res
    }

def read_workspace_file(file_path: str, start_line: int = 1, max_lines: int = 500) -> dict:
    if not os.path.isabs(file_path):
        base = os.environ.get("REPO_PATH", r"i:\aux_servo_interface" if os.name == "nt" else "/workspace")
        file_path = os.path.join(base, file_path)

    if not os.path.exists(file_path):
        return {"status": "error", "error": f"File not found: {file_path}"}

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        total_lines = len(lines)
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, start_idx + max_lines)
        selected_lines = lines[start_idx:end_idx]
        
        return {
            "status": "success",
            "file_path": file_path,
            "start_line": start_idx + 1,
            "end_line": end_idx,
            "total_lines": total_lines,
            "content": "".join(selected_lines)
        }
    except Exception as e:
        return {"status": "error", "error": f"Failed to read {file_path}: {str(e)}"}
