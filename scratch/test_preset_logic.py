import sys
from pathlib import Path
from unittest.mock import MagicMock
import threading

try:
    import lerobot
except ImportError:
    sys.modules["lerobot"] = MagicMock()
    sys.modules["lerobot.motors"] = MagicMock()
    sys.modules["lerobot.motors.feetech"] = MagicMock()

sys.path.insert(0, str(Path("i:/aux_servo_interface/pi500").resolve()))

from robot_backend import calc_next_s7_preset, degrees_to_ticks_s7, ticks_to_degrees_s7, PEDESTAL_PRESETS, RobotBackend
from telemetry_proxies import MOTOR_NAMES

print("--- 1. Testing calc_next_s7_preset sequence from left to right ---")
curr = -165.0
for expected in [-135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 165.0]:
    next_deg, at_limit = calc_next_s7_preset(curr, "right")
    print(f"From {curr:+6.1f} deg -> Stepped right -> {next_deg:+6.1f} deg (at_limit={at_limit})")
    assert next_deg == expected, f"Expected {expected}, got {next_deg}"
    curr = next_deg
assert at_limit is True, "Expected at_limit=True at 165 deg"

print("\n--- 2. Testing calc_next_s7_preset sequence from right to left ---")
curr = 165.0
for expected in [135.0, 90.0, 45.0, 0.0, -45.0, -90.0, -135.0, -165.0]:
    next_deg, at_limit = calc_next_s7_preset(curr, "left")
    print(f"From {curr:+6.1f} deg -> Stepped left  -> {next_deg:+6.1f} deg (at_limit={at_limit})")
    assert next_deg == expected, f"Expected {expected}, got {next_deg}"
    curr = next_deg
assert at_limit is True, "Expected at_limit=True at -165 deg"

print("\n--- 3. Testing Jitter / Deadband Snapping at Boundaries ---")
for jitter in [163.0, 164.0, 164.8, 165.0, 165.5, 166.2]:
    target, at_limit = calc_next_s7_preset(jitter, "right")
    print(f"Right bump with jitter curr={jitter:5.1f} deg -> target={target:5.1f} deg, at_limit={at_limit}")
    assert target == 165.0 and at_limit is True, f"Failed right bumper with jitter {jitter}"

for jitter in [-163.0, -164.0, -164.8, -165.0, -165.5, -166.2]:
    target, at_limit = calc_next_s7_preset(jitter, "left")
    print(f"Left bump with jitter curr={jitter:5.1f} deg -> target={target:5.1f} deg, at_limit={at_limit}")
    assert target == -165.0 and at_limit is True, f"Failed left bumper with jitter {jitter}"

print("\n--- 4. Testing degrees_to_ticks_s7 hard tick clamping ---")
center = 2048
assert degrees_to_ticks_s7(0.0, center) == 2048
assert degrees_to_ticks_s7(165.0, center) == 3925
assert degrees_to_ticks_s7(-165.0, center) == 171
assert degrees_to_ticks_s7(180.0, center) == 3925, "Must clamp 180 deg to 165 deg tick limit"
assert degrees_to_ticks_s7(210.0, center) == 3925, "Must clamp 210 deg to 165 deg tick limit"
assert degrees_to_ticks_s7(-180.0, center) == 171, "Must clamp -180 deg to -165 deg tick limit"
assert degrees_to_ticks_s7(-210.0, center) == 171, "Must clamp -210 deg to -165 deg tick limit"
print("  [OK] Clamping verified")

print("\n--- 5. Testing step_pedestal_preset behavior in mock backend ---")
backend = RobotBackend.__new__(RobotBackend)
backend.lock = threading.RLock()
backend.servos = {
    i: {
        "id": i,
        "name": MOTOR_NAMES[i],
        "pos": 2800 if i == 8 else 3925,
        "raw": 2800 if i == 8 else 3925,
        "torque": True,
        "is_moving": False,
        "connected": True,
        "error": None,
    }
    for i in range(1, 9)
}
backend.aux_calibration = {"7": {"center_ticks": 2048}, "8": {"min_ticks": 3, "max_ticks": 4800}}
backend.ctrl = MagicMock()
backend.ctrl.write_goal_raw.return_value = True
backend.power_mgr = None
backend.save_state = MagicMock()

# When at 165 deg (tick 3925), stepping right should return limit reached without moving
ok, moved, msg, t_deg, t_ticks, limit = backend.step_pedestal_preset("right")
print(f"At 165 deg step right result: ok={ok}, moved={moved}, msg='{msg}', t_deg={t_deg}, limit={limit}")
assert limit is True
assert moved is False
assert t_deg == 165.0
assert "Pedestal limit reached" in msg
backend.ctrl.write_goal_raw.assert_not_called()
print("  [OK] Right bumper guard stopped move (moved=False)")

# When slightly off (tick 3918 ~ 164.4 deg), stepping right should STILL recognize limit reached and not move!
backend.servos[7]["pos"] = 3918
ok, moved, msg, t_deg, t_ticks, limit = backend.step_pedestal_preset("right")
print(f"At 164.4 deg step right result: ok={ok}, moved={moved}, msg='{msg}', t_deg={t_deg}, limit={limit}")
assert limit is True
assert moved is False
assert t_deg == 165.0
assert "Pedestal limit reached" in msg
backend.ctrl.write_goal_raw.assert_not_called()
print("  [OK] Right bumper deadband snapping stopped move (moved=False)")

# Stepping left from 165 deg should cleanly move to 135 deg (tick 3584)
backend.servos[7]["pos"] = 3925
ok, moved, msg, t_deg, t_ticks, limit = backend.step_pedestal_preset("left")
print(f"From 165 deg step left result: ok={ok}, moved={moved}, msg='{msg}', t_deg={t_deg}, t_ticks={t_ticks}, limit={limit}")
assert t_deg == 135.0
assert moved is True
assert limit is False
backend.ctrl.write_goal_raw.assert_called_once()
print("  [OK] Left step succeeded (moved=True)")

print("\nALL UNIT TESTS PASSED!")
