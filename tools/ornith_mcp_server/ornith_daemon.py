"""
ornith_daemon.py - Autonomous Closed-Loop Supervisor Daemon
Monitors the active Antigravity coding session, automatically captures git diffs when turns complete,
queries Ornith 1.0 35B in LM Studio for adversarial audits, injects rejection feedback back into the chat
via Computer Use, and announces verified milestones aloud via Laura Pocket TTS (port 8057).
"""

import argparse
import json
import logging
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Configure logging
log_file = os.path.join(BASE_DIR, "ornith_daemon.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [DAEMON] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
logger = logging.getLogger("ornith_daemon")

import tools_speech
import tools_audit
import tools_hardware
import tools_computer_use

import ornith_config_loader

_CONFIG = ornith_config_loader.get_ornith_config()

class OrnithSupervisorDaemon:
    def __init__(
        self,
        brain_dir: str = r"C:\Users\carso\.gemini\antigravity\brain",
        repo_path: str = r"i:\aux_servo_interface",
        poll_interval: float = None,
        max_retries: int = None,
        dry_run: bool = False
    ):
        self.brain_dir = brain_dir
        self.repo_path = repo_path
        self.poll_interval = poll_interval if poll_interval is not None else float(_CONFIG["daemon"]["poll_interval_sec"])
        self.max_retries = max_retries if max_retries is not None else int(_CONFIG["daemon"]["max_retries"])
        self.dry_run = dry_run
        
        self.last_reviewed_step = None
        self.last_reviewed_conv_id = None
        self.retry_count = 0
        self.running = True

    def run_cycle(self) -> dict:
        """Executes a single check cycle against the active conversation transcript."""
        # 1. Ingest active conversation transcript
        trans = tools_audit.get_active_conversation_transcript(self.brain_dir)
        if trans.get("status") != "success":
            return {"status": "idle", "reason": trans.get("error", "No active transcript")}

        conv_id = trans.get("conversation_id")
        is_done = trans.get("is_turn_done")
        steps = trans.get("recent_history", [])
        last_step_idx = steps[-1].get("step_index") if steps else None

        # If user switched conversations, reset state
        if conv_id != self.last_reviewed_conv_id:
            logger.info(f"Detected new conversation session: {conv_id}")
            self.last_reviewed_conv_id = conv_id
            self.last_reviewed_step = None
            self.retry_count = 0

        # Only process if Antigravity has completed its turn and step has not been audited
        if not is_done:
            return {"status": "waiting", "reason": "Antigravity turn still in progress"}

        if last_step_idx is not None and last_step_idx == self.last_reviewed_step:
            return {"status": "idle", "reason": f"Step {last_step_idx} already reviewed"}

        # 2. Check for codebase changes
        diff_res = tools_audit.get_git_diff(self.repo_path)
        if not diff_res.get("has_changes"):
            self.last_reviewed_step = last_step_idx
            return {"status": "idle", "reason": "Turn finished with no git diff changes to audit"}

        # Mark step as reviewed
        self.last_reviewed_step = last_step_idx
        task_summary = trans.get("latest_user_request", "Codebase modification").strip()
        logger.info(f"Auditing Step {last_step_idx} for task: '{task_summary[:80]}'")

        if self.dry_run:
            logger.info("[DRY RUN] Would query Ornith in LM Studio for review.")
            return {"status": "dry_run", "task": task_summary}

        # 3. Query Ornith in LM Studio
        audit_res = tools_audit.query_ornith_for_review(
            task_summary=task_summary,
            repo_path=self.repo_path,
            speak_verdict=False  # Centralized speech handling below
        )

        if audit_res.get("status") != "success":
            logger.error(f"Ornith audit query failed: {audit_res.get('error')}")
            return audit_res

        verdict = audit_res.get("verdict", "UNKNOWN")
        verdict_text = audit_res.get("verdict_text", "")
        spoken_summary = audit_res.get("spoken_summary", "")
        logger.info(f"Ornith Verdict for Step {last_step_idx}: [{verdict}]")

        # 4. Actuate based on verdict
        if verdict == "APPROVED":
            self.retry_count = 0
            logger.info("Changes approved by Ornith. Announcing completion.")
            tools_speech.speak_laura(spoken_summary or "I have verified and approved Antigravity's implementation.")
            return {"status": "approved", "verdict_text": verdict_text, "spoken_summary": spoken_summary}

        elif verdict == "BLOCKER":
            logger.warning("Blocker detected by Ornith. Escalating to Carson.")
            tools_speech.speak_laura(spoken_summary or "Attention Carson. I encountered a blocker requiring your input.")
            return {"status": "blocker", "verdict_text": verdict_text, "spoken_summary": spoken_summary}

        elif verdict == "REJECTED":
            self.retry_count += 1
            logger.warning(f"Changes rejected (Attempt {self.retry_count}/{self.max_retries}).")

            if self.retry_count >= self.max_retries:
                logger.error(f"Maximum retries ({self.max_retries}) reached. Alerting Carson.")
                tools_speech.speak_laura(
                    spoken_summary or f"I reached the maximum retry limit of {self.max_retries} attempts on task '{task_summary[:50]}'."
                )
                return {"status": "max_retries_exceeded", "verdict_text": verdict_text, "spoken_summary": spoken_summary}
            else:
                if spoken_summary:
                    tools_speech.speak_laura(spoken_summary)
                else:
                    tools_speech.speak_laura(
                        f"I am rejecting Antigravity's implementation. Dispatching correction prompt {self.retry_count} of {self.max_retries} to Antigravity."
                    )
                feedback_prompt = (
                    f"Ornith Adversarial Review (Attempt {self.retry_count}/{self.max_retries}):\n\n"
                    f"{verdict_text}\n\n"
                    f"Please correct the reported rule violations and re-verify."
                )
                inject_res = tools_computer_use.send_feedback_to_antigravity(
                    feedback_text=feedback_prompt,
                    click_send=True
                )
                logger.info(f"Injected rejection prompt into Antigravity chat: {inject_res.get('status')}")
                return {"status": "rejected_and_injected", "attempt": self.retry_count, "inject_res": inject_res, "spoken_summary": spoken_summary}

        return {"status": "completed", "verdict": verdict, "spoken_summary": spoken_summary}

    def start(self):
        """Starts the continuous polling daemon loop."""
        logger.info("=======================================================")
        logger.info("  ORNITH SUPERVISOR DAEMON ACTIVE")
        logger.info(f"  Repo: {self.repo_path}")
        logger.info(f"  Brain: {self.brain_dir}")
        logger.info(f"  Poll Interval: {self.poll_interval}s | Max Retries: {self.max_retries}")
        logger.info("=======================================================")
        
        try:
            while self.running:
                try:
                    self.run_cycle()
                except Exception as e:
                    logger.error(f"Error in daemon cycle: {e}", exc_info=True)
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("Daemon stopped by operator (Ctrl+C).")

def main():
    parser = argparse.ArgumentParser(description="Ornith Supervisor Autonomous Closed-Loop Daemon")
    parser.add_argument("--repo-path", default=r"i:\aux_servo_interface", help="Target git repository")
    parser.add_argument("--brain-dir", default=r"C:\Users\carso\.gemini\antigravity\brain", help="Antigravity brain path")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds")
    parser.add_argument("--max-retries", type=int, default=3, help="Max automated rejection iterations before alerting user")
    parser.add_argument("--once", action="store_true", help="Run a single evaluation cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="Monitor and log without injecting keystrokes or speaking")
    
    args = parser.parse_args()
    
    daemon = OrnithSupervisorDaemon(
        brain_dir=args.brain_dir,
        repo_path=args.repo_path,
        poll_interval=args.poll_interval,
        max_retries=args.max_retries,
        dry_run=args.dry_run
    )
    
    if args.once:
        res = daemon.run_cycle()
        print(json.dumps(res, indent=2))
    else:
        daemon.start()

if __name__ == "__main__":
    main()
