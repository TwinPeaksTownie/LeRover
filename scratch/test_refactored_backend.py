import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock lerobot if not installed on host machine
try:
    import lerobot
except ImportError:
    sys.modules["lerobot"] = MagicMock()
    sys.modules["lerobot.motors"] = MagicMock()
    sys.modules["lerobot.motors.feetech"] = MagicMock()

sys.path.insert(0, str(Path("i:/aux_servo_interface/pi500").resolve()))

from aux_servo_controller import AuxiliaryServoController
from telemetry_proxies import _ServoFieldProxy, _ServoMotorStatesProxy, MOTOR_NAMES
from robot_backend import RobotBackend

def test_all():
    print("Testing AuxiliaryServoController pure byte codec...")
    assert not hasattr(AuxiliaryServoController, "write_goal_safe"), "write_goal_safe must be completely removed"
    print("  [OK] write_goal_safe is absent")

    print("Testing RobotBackend properties and telemetry_proxies mapping...")
    backend = RobotBackend.__new__(RobotBackend)
    import threading
    backend.port = "/dev/ttyACM0"
    backend.robot_id = "follower"
    backend.lock = threading.Lock()
    backend.ctrl = None
    backend.bus = None
    backend.servos = {
        i: {
            "id": i,
            "name": MOTOR_NAMES[i],
            "pos": None,
            "raw": None,
            "normalized": None,
            "torque": False,
            "is_moving": False,
            "connected": False,
            "error": None,
        }
        for i in range(1, 9)
    }
    backend.arm_calibration = {}
    backend.aux_calibration = {"7": {"center_ticks": 2048}, "8": {"min_ticks": 3, "max_ticks": 4800}}
    backend.hardware_active = False
    backend.follower_active = False
    backend.active_port = "/dev/ttyACM0"
    backend.error_msg = None
    backend.power_mgr = None

    # Test aux_positions getter & setter
    assert backend.aux_positions.get(7) is None
    backend.aux_positions[7] = 2048
    assert backend.servos[7]["pos"] == 2048
    assert backend.aux_positions.get(7) == 2048
    assert backend.aux_positions[7] == 2048
    assert 7 in backend.aux_positions
    print("  [OK] aux_positions getter/setter works with self.servos")

    # Test raw_positions getter & setter
    assert backend.raw_positions.get(7) is None
    backend.raw_positions[7] = 2048
    assert backend.servos[7]["raw"] == 2048
    assert backend.raw_positions.get(7) == 2048
    assert 7 in backend.raw_positions
    print("  [OK] raw_positions getter/setter works with self.servos")

    # Test torque_state getter & setter
    assert backend.torque_state.get(7) is False
    backend.torque_state[7] = True
    assert backend.servos[7]["torque"] is True
    assert backend.torque_state.get(7) is True
    print("  [OK] torque_state getter/setter works with self.servos")

    # Test is_moving getter
    assert backend.is_moving.get(7) is False
    backend.servos[7]["is_moving"] = True
    assert backend.is_moving.get(7) is True
    print("  [OK] is_moving getter works with self.servos")

    # Test motor_states
    backend.motor_states[7] = {"connected": True, "error": None}
    assert backend.servos[7]["connected"] is True
    assert backend.motor_states.get(7)["connected"] is True
    errors = [m.get("error") for m in backend.motor_states.values() if m.get("error")]
    assert len(errors) == 0
    backend.motor_states[8] = {"connected": False, "error": "Test Error"}
    errors = [m.get("error") for m in backend.motor_states.values() if m.get("error")]
    assert errors == ["Test Error"]
    print("  [OK] motor_states proxy works with api_server format")

    # Test last_arm_positions
    backend.last_arm_positions = {"shoulder_pan": 15.5, 2: -10.0}
    assert backend.servos[1]["normalized"] == 15.5
    assert backend.servos[2]["normalized"] == -10.0
    arm_positions = backend.last_arm_positions
    assert arm_positions["shoulder_pan"] == 15.5
    assert arm_positions[1] == 15.5
    print("  [OK] last_arm_positions getter/setter works seamlessly")

    # Test gantry_position
    backend.gantry_position = 2500
    assert backend.servos[8]["pos"] == 2500
    assert backend.servos[8]["raw"] == 2500 % 4096
    assert backend.gantry_position == 2500
    print("  [OK] gantry_position getter/setter works")

    # Test sync_servo8_position without recursion
    res = backend.sync_servo8_position()
    assert res is None
    print("  [OK] sync_servo8_position executed cleanly without recursion")

    print("\nALL REFACTORED BACKEND TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_all()
