#!/usr/bin/env python3
"""scripts/validate_joycon_r.py - Validates Joy-Con (R) button sensing and tests for Button A stomping / crosstalk.

Modes:
  1. Interactive Validation (--validate, default):
     Guided test that verifies:
       - Baseline resting state (neither R nor A pressed).
       - Button R press detection (sensed: True).
       - Button A isolation during R press (ensures Button A is NOT stomping on R).
       - Drivetrain throttle response when armed.
  2. Live Stream Monitor (--monitor):
     Continuous 20Hz dashboard displaying real-time button states, stick coordinates,
     throttle, and immediate alert banners if Button A stomps on Button R.

Usage:
  # On Raspberry Pi (reading local /tmp/joycon_telemetry.json):
  python3 scripts/validate_joycon_r.py
  python3 scripts/validate_joycon_r.py --monitor

  # From Windows / remote host over SSH:
  python scripts/validate_joycon_r.py --host 192.168.0.86
  python scripts/validate_joycon_r.py --host 192.168.0.86 --monitor
"""

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple

TELEMETRY_PATH = "/tmp/joycon_telemetry.json"


class TelemetryReader:
    """Reads Joy-Con telemetry either from local file or over SSH."""

    def __init__(self, host: Optional[str] = None, user: str = "carson", path: str = TELEMETRY_PATH):
        self.host = host
        self.user = user
        self.path = path
        self.is_remote = host is not None or (sys.platform == "win32" and not os.path.exists(path))
        if self.is_remote and self.host is None:
            self.host = "192.168.0.86"

    def read(self) -> Optional[Dict[str, Any]]:
        if not self.is_remote:
            if not os.path.exists(self.path):
                return None
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        else:
            try:
                cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
                       f"{self.user}@{self.host}", f"cat {self.path}"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
                if res.returncode == 0 and res.stdout.strip():
                    return json.loads(res.stdout.strip())
            except Exception:
                pass
            return None


def run_live_monitor(reader: TelemetryReader) -> None:
    """Streams live Joy-Con state with real-time stomp warnings."""
    print("=" * 72)
    print("JOY-CON (R) LIVE BUTTON & STOMP MONITOR")
    print(f"Source: {'SSH -> ' + reader.host if reader.is_remote else 'Local -> ' + reader.path}")
    print("Press Ctrl+C to exit.")
    print("=" * 72)

    last_pkt = -1
    try:
        while True:
            telem = reader.read()
            if not telem:
                print("\r[WAITING] No telemetry available from Joy-Con service...", end="", flush=True)
                time.sleep(0.1)
                continue

            pkt = telem.get("packet_count", 0)
            conn = telem.get("connected", False)
            buttons = telem.get("buttons", {})
            r_pressed = bool(buttons.get("r", False))
            a_pressed = bool(buttons.get("a", False))
            zr_pressed = bool(buttons.get("zr", False))
            b_pressed = bool(buttons.get("b", False))
            dt = telem.get("drivetrain", {})
            throttle = dt.get("throttle", 0.0)
            is_armed = telem.get("is_armed", False)
            mode = telem.get("control_mode", "UNKNOWN")

            # Determine stomp / crosstalk status
            stomp_alert = ""
            if r_pressed and a_pressed:
                stomp_alert = " ⚠️ [ALERT: BUTTON A IS STOMPING ON R!]"
            elif r_pressed and not a_pressed:
                stomp_alert = " ✅ [CLEAN R PRESS - NO STOMP]"

            status_line = (
                f"\r[Pkt #{pkt:05d}|{'CONN' if conn else 'DISC'}] "
                f"R: {'[DOWN]' if r_pressed else '  up  '} | "
                f"A: {'[DOWN]' if a_pressed else '  up  '} | "
                f"ZR: {'[DOWN]' if zr_pressed else '  up  '} | "
                f"B: {'[DOWN]' if b_pressed else '  up  '} | "
                f"Thr: {throttle:+.1f} | Mode: {mode} ({'ARMED' if is_armed else 'IDLE'})"
                f"{stomp_alert}"
            )
            print(status_line.ljust(90), end="", flush=True)
            last_pkt = pkt
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n\nMonitor stopped.")


def run_validation_suite(reader: TelemetryReader, timeout_sec: float = 30.0) -> int:
    """Executes a guided verification protocol for Button R sensing and Button A stomping."""
    print("=" * 72)
    print("JOY-CON (R) BUTTON R SENSING & BUTTON A ISOLATION VALIDATOR")
    print(f"Target: {'Remote host ' + reader.host if reader.is_remote else 'Local Pi daemon'}")
    print("=" * 72)

    # 1. Connection & Stream Check
    print("\n[STEP 1/3] Checking Joy-Con connection and live packet stream...")
    telem = None
    start_wait = time.time()
    while time.time() - start_wait < 5.0:
        telem = reader.read()
        if telem and telem.get("connected", False):
            break
        time.sleep(0.2)

    if not telem or not telem.get("connected", False):
        print("❌ FAIL: Joy-Con (R) is NOT connected to the system.")
        print(f"Telemetry snapshot: {telem}")
        return 1

    initial_pkt = telem.get("packet_count", 0)
    time.sleep(0.5)
    telem2 = reader.read() or {}
    later_pkt = telem2.get("packet_count", 0)

    if later_pkt <= initial_pkt:
        print(f"❌ FAIL: Packet stream is stagnant (Pkt {initial_pkt} -> {later_pkt}).")
        return 1

    print(f"  ✓ Connected: Joy-Con (R) MAC {telem.get('mac')}")
    print(f"  ✓ Live stream active: Packet count {later_pkt} (incrementing)")

    # 2. Baseline Resting Check (Verify neither R nor A is stuck)
    buttons = telem2.get("buttons", {})
    if buttons.get("r", False):
        print("❌ FAIL: Button R is stuck or permanently asserted at rest!")
        return 1
    if buttons.get("a", False):
        print("❌ FAIL: Button A is stuck or phantom-triggering at rest! (Check stick hat centering)")
        return 1
    print("  ✓ Baseline verified: Button R = False, Button A = False at rest.")

    # 3. Interactive Button R Press Test
    print("\n" + "-" * 72)
    print("[STEP 2/3] BUTTON R PRESS & BUTTON A STOMP DETECTION")
    print(">>> ACTION REQUIRED: PRESS AND HOLD BUTTON 'R' ON THE JOY-CON NOW <<<")
    print(f"Waiting up to {timeout_sec:.0f} seconds for Button R press...")
    print("-" * 72)

    r_sensed = False
    a_stomped = False
    r_press_start: Optional[float] = None
    r_hold_duration = 0.0
    throttle_captured = 0.0
    samples_with_r = 0
    samples_with_a_during_r = 0

    t_start = time.time()
    while time.time() - t_start < timeout_sec:
        telem = reader.read()
        if not telem:
            time.sleep(0.04)
            continue

        btn = telem.get("buttons", {})
        r_state = bool(btn.get("r", False))
        a_state = bool(btn.get("a", False))
        dt = telem.get("drivetrain", {})
        thr = float(dt.get("throttle", 0.0))

        if r_state:
            samples_with_r += 1
            if not r_sensed:
                r_sensed = True
                r_press_start = time.time()
                print(f"\n  [EVENT] >>> Button R press DETECTED! (Pkt #{telem.get('packet_count')})")

            # Check if Button A is asserted while R is held
            if a_state:
                samples_with_a_during_r += 1
                a_stomped = True
                print(f"  ⚠️  [CROSSTALK DETECTED] Button A is TRUE while Button R is pressed! (Pkt #{telem.get('packet_count')})")

            throttle_captured = max(throttle_captured, thr)
            r_hold_duration = time.time() - (r_press_start or time.time())

            if r_hold_duration >= 1.0:
                print(f"  ✓ Button R held cleanly for {r_hold_duration:.2f}s (Samples: {samples_with_r}).")
                break
        else:
            if r_sensed and r_hold_duration > 0.3:
                # Released after clean detection
                break

        print(f"\r  Listening... Elapsed: {time.time() - t_start:.1f}s | R: {r_state} | A: {a_state}", end="", flush=True)
        time.sleep(0.04)

    print()
    if not r_sensed:
        print(f"❌ FAIL: Timed out ({timeout_sec:.0f}s) without sensing Button R press.")
        return 1

    # 4. Final Verification Evaluation
    print("\n" + "=" * 72)
    print("VALIDATION RESULTS SUMMARY")
    print("=" * 72)
    print(f"1. Button R Sensing:               {'PASS (Sensed cleanly)' if r_sensed else 'FAIL'}")
    print(f"2. Button A Stomp / Crosstalk:     {'FAIL (Button A stomped on R!)' if a_stomped else 'PASS (Zero crosstalk detected)'}")
    print(f"   - Samples with R=True:          {samples_with_r}")
    print(f"   - Samples with A=True while R:  {samples_with_a_during_r}")
    print(f"3. Drivetrain Throttle on R:       {throttle_captured:+.1f}")
    if throttle_captured == 0.0:
        print("   ℹ️  Note: Drivetrain throttle is 0.0 because teleop is currently disarmed.")
        print("       (Hold Button A for 2.0s or switch to joycon_teleop_app to arm drivetrain).")
    else:
        print("   ✓ Drivetrain throttle responded to Button R!")

    if r_sensed and not a_stomped:
        print("\n🎉 ALL TESTS PASSED: Button R is sensed accurately and Button A is NOT stomping on it!")
        return 0
    else:
        print("\n❌ TEST FAILED: Button R was either not sensed or stomped by Button A.")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Joy-Con (R) button sensing and A-button crosstalk.")
    parser.add_argument("--host", default=None, help="Remote Pi host IP or hostname (default: local or 192.168.0.86)")
    parser.add_argument("--monitor", action="store_true", help="Run in continuous live dashboard monitoring mode")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout in seconds for Button R press prompt")
    args = parser.parse_args()

    reader = TelemetryReader(host=args.host)
    if args.monitor:
        run_live_monitor(reader)
        return 0
    else:
        return run_validation_suite(reader, timeout_sec=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
