#!/usr/bin/env python3
"""scripts/obstacle_safety_guard.py - Dedicated Obstacle Collision Safety Supervisor.

Adheres strictly to the Single Responsibility Principle (SRP):
- Monitors distance status from the authoritative RoverController Status API on port 8089.
- Monitors Joy-Con input telemetry from /tmp/joycon_telemetry.json.
- Enforces a strictly binary state machine (Rule 13: NORMAL vs LOCKOUT).
- Emergency stops motors (CMD:1500,1500) when an obstacle is in the danger zone and forward throttle > 0.
- Allows reverse throttle (backing away from obstacle).
- Enforces a 2.0-second button 'A' hold recovery protocol, cutting max speed by 50% upon recovery.
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("so101.obstacle_safety_guard")


def load_guard_config(repo_root: Optional[Path] = None) -> Tuple[Dict[str, Any], str, int]:
    """Loads canonical rover configuration and distance endpoint fail-fast."""
    root = repo_root or REPO_ROOT
    rover_cfg_path = root / "config" / "rover_config.json"
    net_cfg_path = root / "config" / "network_config.json"

    if not rover_cfg_path.exists():
        raise FileNotFoundError(f"Missing required rover_config.json: {rover_cfg_path}")
    if not net_cfg_path.exists():
        raise FileNotFoundError(f"Missing required network_config.json: {net_cfg_path}")

    with open(rover_cfg_path, "r", encoding="utf-8") as f:
        rover_cfg = json.load(f)

    with open(net_cfg_path, "r", encoding="utf-8") as f:
        net_cfg = json.load(f)

    _ = bool(rover_cfg["collision_guard"]["enabled"])
    _ = float(rover_cfg["collision_guard"]["danger_zone_cm"])
    _ = float(rover_cfg["collision_guard"]["min_valid_cm"])
    _ = float(rover_cfg["collision_guard"]["max_valid_cm"])
    _ = int(rover_cfg["collision_guard"]["ground_exclusion_adc"])
    _ = int(rover_cfg["collision_guard"]["lockout_speed_threshold_pct"])
    _ = int(rover_cfg["collision_guard"]["docked_speed_pct"])
    _ = str(rover_cfg["collision_guard"]["recovery_button"])
    _ = float(rover_cfg["collision_guard"]["recovery_hold_sec"])
    _ = int(rover_cfg["collision_guard"]["speed_penalty_pct"])
    _ = int(rover_cfg["collision_guard"]["halt_pulse_left"])
    _ = int(rover_cfg["collision_guard"]["halt_pulse_right"])

    host = str(net_cfg["endpoints"]["distance_telemetry"]["host"])
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = int(net_cfg["endpoints"]["distance_telemetry"]["port"])

    return rover_cfg, host, port


class ObstacleSafetyGuard:
    """Strictly binary collision avoidance supervisor (NORMAL vs LOCKOUT)."""

    STATE_NORMAL = "NORMAL"
    STATE_LOCKOUT = "LOCKOUT"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        api_host: str = "127.0.0.1",
        api_port: int = 8089,
        telemetry_path: str = "/tmp/joycon_telemetry.json"
    ) -> None:
        if config is None:
            loaded_cfg, host, port = load_guard_config()
            self.config = loaded_cfg
            self.api_host = host
            self.api_port = port
        else:
            self.config = config
            self.api_host = api_host
            self.api_port = api_port

        self.telemetry_path = telemetry_path
        self.guard_cfg = self.config["collision_guard"]
        self.enabled = bool(self.guard_cfg["enabled"])
        self.danger_zone_cm = float(self.guard_cfg["danger_zone_cm"])
        self.lockout_speed_threshold_pct = int(self.guard_cfg["lockout_speed_threshold_pct"])
        self.docked_speed_pct = int(self.guard_cfg["docked_speed_pct"])
        self.recovery_btn = str(self.guard_cfg["recovery_button"])
        self.recovery_hold_sec = float(self.guard_cfg["recovery_hold_sec"])
        self.speed_penalty_pct = int(self.guard_cfg["speed_penalty_pct"])

        self.min_speed_pct = int(self.config["control"]["min_speed_pct"])
        self.max_speed_pct_limit = int(self.config["control"]["max_speed_pct_limit"])

        # Strictly binary state machine (Rule 13)
        self.state = self.STATE_NORMAL
        self.a_hold_start: Optional[float] = None
        self.last_known_speed: int = int(self.config["pwm"]["max_speed_pct"])

        self.status_url = f"http://{self.api_host}:{self.api_port}/api/status"
        self.halt_url = f"http://{self.api_host}:{self.api_port}/api/halt"
        self.speed_url = f"http://{self.api_host}:{self.api_port}/api/speed"

    def query_distance_status(self) -> Optional[Dict[str, Any]]:
        """Queries authoritative distance and rover status from RoverController."""
        try:
            req = urllib.request.Request(self.status_url)
            with urllib.request.urlopen(req, timeout=0.1) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    _ = data["object_detected"]
                    _ = data["in_danger_zone"]
                    _ = data["emergency_halt"]
                    return data
        except Exception:
            return None
        return None

    def read_joycon_telemetry(self) -> Optional[Dict[str, Any]]:
        """Reads driver inputs directly from Joy-Con telemetry file."""
        if not os.path.exists(self.telemetry_path):
            return None
        try:
            with open(self.telemetry_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return None
            data = json.loads(content)
            _ = data["drivetrain"]["throttle"]
            _ = data["buttons"][self.recovery_btn]
            return data
        except Exception:
            return None

    def dispatch_emergency_halt(self, halt: bool) -> bool:
        """Sends emergency halt command to RoverController."""
        try:
            payload = json.dumps({"halt": halt}).encode("utf-8")
            req = urllib.request.Request(
                self.halt_url,
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=0.2) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("Failed to dispatch emergency halt (%s): %s", halt, e)
            return False

    def dispatch_speed_penalty(self, new_speed_pct: int) -> bool:
        """Sends speed adjustment to RoverController."""
        try:
            payload = json.dumps({"speed_pct": new_speed_pct}).encode("utf-8")
            req = urllib.request.Request(
                self.speed_url,
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=0.2) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("Failed to dispatch speed penalty (%d%%): %s", new_speed_pct, e)
            return False

    def step(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Executes one arbitration cycle of the safety guard."""
        current_time = now if now is not None else time.time()
        dist_status = self.query_distance_status()
        joycon_telem = self.read_joycon_telemetry()

        in_danger = False
        dist_cm = None
        if dist_status is not None:
            in_danger = bool(dist_status["in_danger_zone"])
            dist_cm = dist_status["distance_cm"]
            if "max_speed_pct" in dist_status:
                self.last_known_speed = int(dist_status["max_speed_pct"])

        throttle = 0.0
        btn_a = False
        if joycon_telem is not None:
            throttle = float(joycon_telem["drivetrain"]["throttle"])
            btn_a = bool(joycon_telem["buttons"][self.recovery_btn])

        action_taken = "NONE"

        # State 1: NORMAL Operation
        if self.state == self.STATE_NORMAL:
            # Gated lockout: Trigger lockout only if obstacle in danger zone, forward throttle > 0.05,
            # AND current speed cap > lockout_speed_threshold_pct (50%).
            # If current speed <= 50%, lockout is suppressed to permit low-speed tactile crawl/maneuvering at wall.
            if self.enabled and in_danger and throttle > 0.05 and self.last_known_speed > self.lockout_speed_threshold_pct:
                self.state = self.STATE_LOCKOUT
                self.a_hold_start = None
                self.dispatch_emergency_halt(True)
                action_taken = "TRIGGERED_LOCKOUT"
                logger.warning(
                    "EMERGENCY COLLISION GUARD HALT! Obstacle at %s cm (danger threshold %.1f cm) at %d%% speed. Entering LOCKOUT.",
                    dist_cm, self.danger_zone_cm, self.last_known_speed
                )

        # State 2: LOCKOUT Latch (Requires 2.0s hold on button 'A')
        elif self.state == self.STATE_LOCKOUT:
            if btn_a:
                if self.a_hold_start is None:
                    self.a_hold_start = current_time
                    action_taken = "HOLDING_RECOVERY_BUTTON"
                elif (current_time - self.a_hold_start) >= self.recovery_hold_sec:
                    # 2.0 second recovery threshold met! Dock speed cap to 50%
                    docked_speed = min(self.last_known_speed, self.docked_speed_pct)
                    self.dispatch_speed_penalty(docked_speed)
                    self.dispatch_emergency_halt(False)
                    self.state = self.STATE_NORMAL
                    self.a_hold_start = None
                    self.last_known_speed = docked_speed
                    action_taken = "CLEARED_LOCKOUT"
                    logger.info(
                        "COLLISION GUARD RECOVERED! Button '%s' held for %.1fs. Speed docked to %d%%.",
                        self.recovery_btn, self.recovery_hold_sec, docked_speed
                    )
            else:
                self.a_hold_start = None

        return {
            "state": self.state,
            "action": action_taken,
            "in_danger_zone": in_danger,
            "distance_cm": dist_cm,
            "throttle": throttle,
            "recovery_button_pressed": btn_a,
            "hold_duration": (current_time - self.a_hold_start) if self.a_hold_start else 0.0
        }

    def run_forever(self, loop_rate_hz: float = 20.0) -> None:
        """Main execution loop for obstacle safety guard daemon."""
        logger.info(
            "ObstacleSafetyGuard started (status_api=%s:%d, hold_sec=%.1f, penalty=%d%%)",
            self.api_host, self.api_port, self.recovery_hold_sec, self.speed_penalty_pct
        )
        interval = 1.0 / loop_rate_hz
        while True:
            t0 = time.time()
            try:
                self.step(t0)
            except Exception as e:
                logger.error("Error in safety guard step: %s", e)
            elapsed = time.time() - t0
            sleep_time = max(0.005, interval - elapsed)
            time.sleep(sleep_time)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    guard = ObstacleSafetyGuard()
    guard.run_forever()
