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
import requests
import time
import tools_speech
import tools_hardware
import contract_scanner
import ornith_config_loader

_CONFIG = ornith_config_loader.get_ornith_config()

DEFAULT_LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", _CONFIG["audit"]["lm_studio_url"])
DEFAULT_MODEL = _CONFIG["audit"]["model"]
DEFAULT_MAX_TOKENS = int(_CONFIG["audit"]["max_tokens"])
DEFAULT_TEMPERATURE = float(_CONFIG["audit"]["temperature"])
DEFAULT_SPEAK_VERDICT = bool(_CONFIG["audit"]["default_speak_verdict"])
FALLBACK_COMMITS = int(_CONFIG["audit"]["uncommitted_fallback_commits"])
MAX_DIFF_CHARS = int(_CONFIG["audit"]["max_diff_chars"])

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
    
    # 1. First pass: find latest substantive assistant response and user input
    for step in reversed(steps):
        st_type = step.get("type")
        content = step.get("content", "")
        if st_type == "PLANNER_RESPONSE" and not latest_assistant_response and content and content.strip():
            latest_assistant_response = content.strip()
        elif st_type == "USER_INPUT" and not latest_user_request and content and content.strip():
            latest_user_request = content.strip()
        if latest_assistant_response and latest_user_request:
            break

    # 2. Check transcript_full.jsonl if content was truncated or empty
    transcript_full = os.path.join(os.path.dirname(latest_transcript), "transcript_full.jsonl")
    if os.path.exists(transcript_full) and (not latest_assistant_response or len(latest_assistant_response) < 100):
        try:
            with open(transcript_full, "r", encoding="utf-8") as f_full:
                full_steps = [json.loads(l) for l in f_full if l.strip()]
                for s in reversed(full_steps):
                    if s.get("type") == "PLANNER_RESPONSE" and s.get("content") and len(s.get("content", "").strip()) > 50:
                        latest_assistant_response = s.get("content").strip()
                        break
        except Exception as full_err:
            _log_debug(f"transcript_full lookup warning: {full_err}")

    # 3. If latest user request is asking for a summary/distillation, ensure we target the PRIOR substantive response
    meta_words = ["summarize", "simplify", "distill", "last answer", "last response", "what did you say"]
    if latest_user_request and any(w in latest_user_request.lower() for w in meta_words):
        seen_count = 0
        for step in reversed(steps):
            if step.get("type") == "PLANNER_RESPONSE" and step.get("content") and len(step.get("content", "").strip()) > 50:
                seen_count += 1
                if seen_count > 1:
                    latest_assistant_response = step.get("content").strip()
                    break

    has_handoff = False
    handoff_summary = ""
    for step in reversed(steps[-10:]):
        tool_calls = step.get("tool_calls", []) or []
        for tc in tool_calls:
            fn_name = ""
            if isinstance(tc, dict):
                fn_name = tc.get("function", {}).get("name", "") or tc.get("name", "")
                if "signal_task_complete" in fn_name:
                    has_handoff = True
                    handoff_summary = str(tc.get("args", {}).get("summary", ""))
                    break
        if has_handoff:
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
        "has_handoff": has_handoff,
        "handoff_summary": handoff_summary,
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
            encoding="utf-8",
            errors="replace",
            check=True
        )
        status_output = (status_proc.stdout or "").strip()
        
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
            encoding="utf-8",
            errors="replace"
        )
        diff_text = diff_proc.stdout or ""

        # If no uncommitted diffs, inspect recent code commits (baseline..HEAD or HEAD~FALLBACK_COMMITS..HEAD)
        if not diff_text.strip() and not untracked_files:
            base_ref = f"HEAD~{FALLBACK_COMMITS}"
            try:
                base_proc = subprocess.run(
                    ["git", "log", "--grep=baseline:", "-n", "1", "--format=%H"],
                    cwd=repo_path,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace"
                )
                if base_proc.returncode == 0 and base_proc.stdout.strip():
                    base_ref = base_proc.stdout.strip()
            except Exception:
                pass

            diff_proc_last = subprocess.run(
                ["git", "diff", f"{base_ref}..HEAD", "--", ".", ":!*manifest.json"],
                cwd=repo_path,
                capture_output=True,
                encoding="utf-8",
                errors="replace"
            )
            if diff_proc_last.returncode == 0 and (diff_proc_last.stdout or "").strip():
                diff_text = f"=== RECENT COMMITS DIFF ({base_ref[:8]}..HEAD) ===\n\n" + (diff_proc_last.stdout or "")
                name_proc = subprocess.run(
                    ["git", "diff", "--name-only", f"{base_ref}..HEAD", "--", ".", ":!*manifest.json"],
                    cwd=repo_path,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace"
                )
                if name_proc.returncode == 0 and name_proc.stdout:
                    for nf in name_proc.stdout.splitlines():
                        nf = nf.strip()
                        if nf and os.path.splitext(nf.lower())[1] not in IGNORE_EXTENSIONS:
                            modified_files.append(nf)

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

def scan_code_contracts(diff_text: str = "", repo_path: str = None, check_deployments: bool = True) -> dict:
    if repo_path is None:
        repo_path = os.environ.get("REPO_PATH", r"i:\aux_servo_interface" if os.name == "nt" else "/workspace")

    diff_res = get_git_diff(repo_path)
    if not diff_text and diff_res.get("status") == "success":
        diff_text = diff_res.get("diff", "")

    modified_files = diff_res.get("modified_files", []) if isinstance(diff_res, dict) else []
    untracked_files = diff_res.get("untracked_files", []) if isinstance(diff_res, dict) else []
    all_changed_files = list(dict.fromkeys(modified_files + untracked_files))

    violations = []
    warnings = []

    # 1. If diff_text is provided (e.g. in unit tests or simulated audits), scan its contents
    if diff_text.strip():
        current_file = "unknown"
        chunk_lines = []
        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                current_file = line[6:].strip()
                continue
            elif line.startswith("+++ "):
                current_file = line[4:].strip()
                continue
            if line.startswith("+") and not line.startswith("+++"):
                code_line = line[1:]
                chunk_lines.append((current_file, code_line))

        files_map = {}
        for f, l in chunk_lines:
            files_map.setdefault(f, []).append(l)

        for f, lines_list in files_map.items():
            code_block = "\n".join(lines_list)
            lower_f = f.lower()
            if lower_f.endswith(".py"):
                violations.extend(contract_scanner.scan_python_code(code_block, f))
            elif lower_f.endswith(".js"):
                violations.extend(contract_scanner.scan_javascript_code(code_block, f))
            elif lower_f.endswith((".html", ".htm")):
                violations.extend(contract_scanner.scan_html_code(code_block, f))

    # 2. Full-file AST / Structural checks for all modified and untracked files on disk
    for rel_file in all_changed_files:
        full_path = os.path.join(repo_path, rel_file)
        if os.path.isfile(full_path):
            file_violations = contract_scanner.scan_source_file(full_path, repo_path=repo_path)
            for fv in file_violations:
                fv["file"] = rel_file
                violations.append(fv)


    # 3. Target Node Deployment Parity Verification (Verification State 1)
    deployment_res = None
    if check_deployments and all_changed_files:
        try:
            deployment_res = tools_hardware.check_target_deployments(all_changed_files, repo_path=repo_path)
            if deployment_res.get("has_mismatch"):
                for dep in deployment_res.get("deployments", []):
                    if not dep.get("match"):
                        violations.append({
                            "rule": "DEPLOYMENT_PARITY",
                            "file": dep.get("local_file"),
                            "line": 1,
                            "snippet": f"Local MD5: {dep.get('local_md5')} | Remote MD5: {dep.get('remote_md5')}",
                            "reason": f"Deployment mismatch on node {dep.get('node')}: {dep.get('message')}. Code must be deployed to physical device before approval."
                        })
        except Exception as e:
            _log_debug(f"Deployment parity check exception: {e}")

    # 4. Target Path & Bifurcation Verification
    if check_deployments:
        try:
            bifurcated_check = tools_hardware.verify_remote_directory_exists("pi500", "/home/user/so101/beat_bandit/library")
            if bifurcated_check.get("exists"):
                violations.append({
                    "rule": "TARGET_PATH_EXISTS",
                    "file": "apps/beat_bandit/config.json",
                    "line": 1,
                    "snippet": "/home/user/so101/beat_bandit/library",
                    "reason": "Bifurcated legacy library directory '/home/user/so101/beat_bandit/library' exists on Pi 500. Canonical path is '/home/user/so101/library/beat_bandit'."
                })
        except Exception as e:
            _log_debug(f"Target path check exception: {e}")

    # Deduplicate violations by (rule, file, line, reason)
    deduped = []
    seen = set()
    for v in violations:
        key = (v.get("rule"), v.get("file"), v.get("line"), v.get("reason"))
        if key not in seen:
            seen.add(key)
            deduped.append(v)

    clean = len(deduped) == 0
    summary = f"Audit complete: {len(deduped)} violations, {len(warnings)} warnings found across {len(all_changed_files)} changed files."

    return {
        "status": "success",
        "clean": clean,
        "violations": deduped,
        "warnings": warnings,
        "changed_files": all_changed_files,
        "deployment_status": deployment_res,
        "audit_summary": summary
    }


def extract_spoken_summary(verdict_text: str, verdict: str, contract_res: dict = None, task_summary: str = "") -> str:
    """
    Extracts the inferred SPOKEN_SUMMARY section from Ornith's response.
    Falls back to a clean rule violation summary if the section is missing.
    """
    if not verdict_text:
        return ""

    # 1. Match ### SPOKEN_SUMMARY block
    match = re.search(r'###\s*SPOKEN_SUMMARY\s*\n(.*?)(?=\n###|\Z)', verdict_text, re.DOTALL | re.IGNORECASE)
    if match:
        spoken = match.group(1).strip()
        spoken = re.sub(r'[*_`#\[\]]', '', spoken).strip()
        if spoken:
            return spoken

    # 2. Match inline SPOKEN_SUMMARY: block
    match2 = re.search(r'SPOKEN_SUMMARY:\s*(.*?)(?=\n\n|\n[A-Z_]+:|\Z)', verdict_text, re.DOTALL | re.IGNORECASE)
    if match2:
        spoken = match2.group(1).strip()
        spoken = re.sub(r'[*_`#\[\]]', '', spoken).strip()
        if spoken:
            return spoken

    # 3. Fail loudly if Ornith omitted the SPOKEN_SUMMARY section (Lesson 9)
    raise RuntimeError(
        f"Ornith model in LM Studio failed to provide a valid SPOKEN_SUMMARY section for verdict [{verdict}]. "
        "Failing loudly without dummy fallback synthesis."
    )


def query_ornith_for_review(
    task_summary: str,
    diff_text: str = "",
    repo_path: str = None,
    speak_verdict: bool = True,
    lm_studio_url: str = None,
    active_backend: str = None
) -> dict:
    if repo_path is None:
        repo_path = os.environ.get("REPO_PATH", r"i:\aux_servo_interface" if os.name == "nt" else "/workspace")

    if active_backend is None:
        active_backend = os.environ.get("ORNITH_AUDIT_BACKEND")
        if not active_backend:
            active_backend = _CONFIG["audit"]["active_backend"]

    backends = _CONFIG["audit"]["backends"]
    if active_backend not in backends:
        raise KeyError(f"Invalid audit backend '{active_backend}'. Available backends: {list(backends.keys())}")

    b_cfg = backends[active_backend]
    invoke_url = b_cfg["url"]
    if lm_studio_url is not None and active_backend == "local":
        invoke_url = lm_studio_url

    model_name = b_cfg["model"]
    max_tokens = int(b_cfg["max_tokens"])
    temperature = float(b_cfg["temperature"])

    if not diff_text:
        diff_res = get_git_diff(repo_path)
        if diff_res.get("status") != "success":
            return diff_res
        diff_text = diff_res.get("diff", "")

    contract_res = scan_code_contracts(diff_text=diff_text, repo_path=repo_path)

    violations_detail = "\n".join(
        f"- [{v['rule']}] {v['file']}:{v.get('line', 1)} - {v['reason']}\n  Snippet: {v.get('snippet', '')}"
        for v in contract_res.get("violations", [])
    ) if contract_res.get("violations") else "None. All code contracts verified."

    deployment_info = "No remote target files changed."
    if contract_res.get("deployment_status"):
        dep = contract_res["deployment_status"]
        deployment_info = f"Files checked: {dep.get('checked_files')}, Parity Mismatches: {dep.get('has_mismatch')}, All Verified: {dep.get('all_verified')}"

    # State 4 Daemon Log Inspection
    daemon_log_info = "Daemon logs clean."
    try:
        d_logs = tools_hardware.query_daemon_logs("pi500", "backend.service", lines=25)
        if not d_logs.get("clean"):
            daemon_log_info = f"Errors found ({d_logs.get('error_count')}): " + "; ".join(d_logs.get("detected_errors", [])[:3])
            violations_detail += f"\n- [DAEMON_LOG_ERROR] pi500 backend.service logs:\n  " + "\n  ".join(d_logs.get("detected_errors", [])[:3])
        else:
            daemon_log_info = "0 exceptions or timeouts in recent journalctl."
    except Exception as e:
        _log_debug(f"Daemon log query warning: {e}")

    system_prompt = """You are Ornith, the adversarial code reviewer and hardware supervisor for the SO-101 robotic arm and touch UI system.
Your job is to strictly enforce the following rules:
1. FAIL-FAST SCHEMA: Zero tolerance for .get(key, default), .setdefault(), .pop(k, default), getattr(obj, k, default), or 'd[k] if k in d else default' fallbacks in internal payloads, motion blocks, track dictionaries, modes, speeds, envelopes, or calibration. All dictionaries and motion blocks must use direct bracket access (e.g. block["speed"]) and fail-fast schema validators. Raise KeyError immediately on missing or malformed keys.
2. FRONTEND & JS DUMMY FALLBACKS: Zero tolerance for ?? <literal>, || <literal>, ternary defaults, or destructuring defaults on live telemetry/state in JavaScript and HTML.
3. DYNAMIC CALIBRATION: No hardcoded 2048 or 0x800 neutral ticks. Offsets and bounds must load dynamically from follower.json (servos 1-6), calibration_aux.json (servos 7-8), or manifest.json.
4. NO SWALLOWED EXCEPTIONS: No 'except: pass', 'except: ...', or unhandled generic catches. Raise descriptive errors or log explicit tracebacks.
5. NO SAFETY SLOP / OVER-DAMPING: No hardcoded neutering multipliers (* 0.5, * 0.8), no artificial sub-range cages (e.g. caging head roll to 35-65%), and no low-pass filters that crush dynamic beat frequencies. Joint ranges and modifier intensities must be controlled strictly via loaded JSON probabilities and calibrated ROM.
6. TARGET DEPLOYMENT PARITY: Modified code under pi500/ or pi4b/ must be deployed and MD5-verified on physical targets.
7. MANDATORY 4-STATE VERIFICATION: (1) Sync MD5, (2) Bi-directional cycle, (3) Telemetry audit, (4) Human confirmation.
8. MUSICAL UNITS: Choreography divisions must use measures, beats, 4bars, 8bars.
9. CONFIG PARITY & SINGLE SOURCE OF TRUTH: Modular apps under apps/ must consume their loaded _CONFIG values (name, title, icon, library_subdir) directly in AppMetadata and paths.
10. SCHEMA KEY COMPLETENESS: Choreography dictionary structures, sanitization handlers, and save routines must retain mandatory schema keys, specifically 'probabilities' and 'tracks'.
11. JS SCOPE INTEGRITY: JavaScript functions must not reference undeclared variables (e.g. referencing 'data' when 'data' is not in function scope). Use explicitly declared module state.
12. EXECUTION ORDER & SIDE-EFFECT PRECONDITIONS: Irreversible network side-effects (e.g. audio playback dispatch) must occur only after worker and player instantiation has succeeded.

Evaluate the git diff, contract violations, and deployment status against the task summary and these strict rules.

You MUST structure your response strictly using these exact markdown headers:

### VERDICT
State your verdict on a single line: [APPROVED], [REJECTED], or [BLOCKER].

### SPOKEN_SUMMARY
Provide a concise, 2-to-3 sentence spoken voice summary written in active first-person voice as Ornith addressing Carson:
- If REJECTED: State clearly that you are rejecting Antigravity's implementation for violating rule [Rule Name/Number]. State what Antigravity was required to do instead. State that you will not provide approval on the build until the implementation complies.
- If BLOCKER: State clearly that you encountered a blocker requiring Carson's intervention, explaining the specific missing dependency or hardware state.
- If APPROVED: State clearly that you have approved Antigravity's implementation, confirming that all changes comply with project rules and verification requirements.
Keep the SPOKEN_SUMMARY strictly under 60 words, natural for text-to-speech, with zero markdown symbols, bullet points, or code formatting.

### DETAILED_AUDIT
Explain the exact technical reasons, line-by-line violations in the diff, and recommended corrections for Antigravity."""

    user_prompt = f"""Task Summary: {task_summary}

Contract Scan Result:
- Clean: {contract_res.get('clean')}
- Rule Violations: {len(contract_res.get('violations', []))}
- Deployment Status: {deployment_info}
- Pi 500 Daemon Logs: {daemon_log_info}

Contract Violations Detail:
{violations_detail}

Repository Changes (Git Diff):
```diff
{diff_text if diff_text.strip() else 'No unstaged or staged diffs.'}
```

Provide your adversarial audit:"""

    headers = {"Content-Type": "application/json"}
    if active_backend == "nim":
        api_key = ornith_config_loader.get_secret("NVIDIA_API_KEY")
        headers["Authorization"] = f"Bearer {api_key}"

    use_stream = bool(active_backend == "nim")
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": use_stream
    }
    if "reasoning_effort" in b_cfg and b_cfg["reasoning_effort"] is not None:
        payload["reasoning_effort"] = b_cfg["reasoning_effort"]
    if "seed" in b_cfg and b_cfg["seed"] is not None:
        payload["seed"] = b_cfg["seed"]

    _log_debug(f"Querying Ornith via {active_backend} ({model_name}) at {invoke_url} (stream={use_stream}, payload chars: {len(user_prompt)})...")
    try:
        resp = requests.post(invoke_url, headers=headers, json=payload, stream=use_stream, timeout=300)
        if resp.status_code != 200:
            err_body = resp.text
            _log_debug(f"Inference HTTP {resp.status_code}: {err_body}")
            return {
                "status": "error",
                "error": f"Inference backend ({active_backend}) returned HTTP {resp.status_code}: {err_body}",
                "static_contracts": contract_res
            }

        content = ""
        reasoning = ""

        if use_stream:
            content_parts = []
            reasoning_parts = []
            last_log_time = time.time()
            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data: "):
                    continue
                data_str = decoded[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except Exception:
                    continue
                if "choices" not in chunk or not chunk["choices"]:
                    continue
                choice = chunk["choices"][0]
                if "delta" not in choice:
                    continue
                delta = choice["delta"]
                if "content" in delta and delta["content"]:
                    content_parts.append(str(delta["content"]))
                if "reasoning_content" in delta and delta["reasoning_content"]:
                    reasoning_parts.append(str(delta["reasoning_content"]))

                now = time.time()
                if now - last_log_time > 10:
                    _log_debug(f"Streaming from {active_backend}: {len(reasoning_parts)} reasoning chunks, {len(content_parts)} content chunks...")
                    last_log_time = now

            content = "".join(content_parts)
            reasoning = "".join(reasoning_parts)
        else:
            data = resp.json()
            msg_obj = data["choices"][0]["message"]
            if "content" in msg_obj and msg_obj["content"] is not None:
                content = str(msg_obj["content"])
            if "reasoning_content" in msg_obj and msg_obj["reasoning_content"] is not None:
                reasoning = str(msg_obj["reasoning_content"])

        if not content and reasoning:
            content = reasoning
    except Exception as e:
        _log_debug(f"Failed to query inference backend ({active_backend}): {e}")
        return {
            "status": "error",
            "error": f"Failed to communicate with Ornith inference backend ({active_backend} at {invoke_url}): {str(e)}",
            "static_contracts": contract_res
        }

    verdict_text = content.strip()
    # Robust verdict extraction matching ### VERDICT block with or without brackets
    verdict_match = re.search(r'###\s*VERDICT\s*\n\s*\[?(APPROVED|REJECTED|BLOCKER)\]?', verdict_text, re.IGNORECASE)
    if verdict_match:
        verdict_str = verdict_match.group(1).upper()
    else:
        is_rejected = "[REJECTED]" in verdict_text.upper() or "VERDICT: REJECTED" in verdict_text.upper()
        is_blocker = "[BLOCKER]" in verdict_text.upper() or "VERDICT: BLOCKER" in verdict_text.upper()
        is_approved = "[APPROVED]" in verdict_text.upper() or "VERDICT: APPROVED" in verdict_text.upper()
        verdict_str = "APPROVED" if is_approved else ("REJECTED" if is_rejected else ("BLOCKER" if is_blocker else "REVIEW_COMPLETED"))

    # Enforce contract safety: if AST contracts or deployment checks failed, verdict MUST NOT be APPROVED
    if not contract_res.get("clean") and verdict_str == "APPROVED":
        _log_debug("Overriding LLM APPROVED verdict: code contract violations or deployment parity failures exist.")
        verdict_str = "REJECTED"
        spoken_text = "Attention Carson. I am rejecting the build because code contract violations or deployment parity checks failed."
        verdict_text = f"### VERDICT\n[REJECTED]\n\n### CONTRACT_SCAN_OVERRIDE\nCode contracts failed:\n{violations_detail}\n\n### ORIGINAL_MODEL_OUTPUT\n{verdict_text}"
    else:
        spoken_text = extract_spoken_summary(verdict_text, verdict_str, contract_res, task_summary)

    spoken_status = "not_spoken"
    if speak_verdict and spoken_text:
        try:
            tools_speech.speak_laura(spoken_text, target="both")
            spoken_status = f"spoken_{verdict_str.lower()}"
        except Exception as e:
            _log_debug(f"Speech notification error: {e}")

    return {
        "status": "success",
        "task_summary": task_summary,
        "verdict": verdict_str,
        "spoken_summary": spoken_text,
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

def search_workspace_code(
    query: str,
    extensions: list = None,
    repo_path: str = None,
    max_matches: int = 50
) -> dict:
    """
    Fast, read-only search across workspace files.
    Skips .git, __pycache__, .gemini, and binary files.
    """
    if repo_path is None:
        repo_path = os.environ.get("REPO_PATH", r"i:\aux_servo_interface" if os.name == "nt" else "/workspace")

    if not os.path.exists(repo_path):
        return {"status": "error", "error": f"Repo path not found: {repo_path}"}

    if not query or not query.strip():
        return {"status": "error", "error": "Search query cannot be empty"}

    if extensions is None:
        extensions = [".py", ".json", ".js", ".html", ".md", ".sh", ".service"]

    matches = []
    ignored_dirs = {".git", "__pycache__", ".gemini", "node_modules", ".venv", "venv", ".idea"}
    pattern = re.compile(re.escape(query), re.IGNORECASE)

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
                                        return {
                                            "status": "success",
                                            "query": query,
                                            "matches_count": len(matches),
                                            "capped": True,
                                            "matches": matches
                                        }
                    except Exception:
                        continue

        return {
            "status": "success",
            "query": query,
            "matches_count": len(matches),
            "capped": False,
            "matches": matches
        }
    except Exception as e:
        return {"status": "error", "error": f"Search failed: {str(e)}"}
