#!/usr/bin/env python3
"""Telemetry proxy classes for SO-101 robot backend.
Provides backward-compatible dynamic dict views over unified RobotBackend.servos state.
"""

from typing import Optional, Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from robot_backend import RobotBackend

MOTOR_NAMES = {
    1: "shoulder_pan",
    2: "shoulder_lift",
    3: "elbow_flex",
    4: "wrist_flex",
    5: "wrist_roll",
    6: "gripper",
    7: "pedestal_spinner",
    8: "gantry_slider",
}


class _ServoFieldProxy(dict):
    """Dynamic dict proxy mapping directly to specific fields in RobotBackend.servos."""

    def __init__(self, backend: Any, field_name: str, target_sids: Optional[List[int]] = None):
        self._backend = backend
        self._field_name = field_name
        self._target_sids = target_sids
        super().__init__()

    def _get_sids(self):
        return self._target_sids if self._target_sids is not None else list(self._backend.servos.keys())

    def __getitem__(self, sid):
        sid = int(sid)
        with self._backend.lock:
            if sid in self._backend.servos:
                return self._backend.servos[sid].get(self._field_name)
            raise KeyError(sid)

    def __setitem__(self, sid, val):
        sid = int(sid)
        with self._backend.lock:
            if sid in self._backend.servos:
                self._backend.servos[sid][self._field_name] = val
            else:
                self._backend.servos[sid] = {self._field_name: val}

    def get(self, sid, default=None):
        sid = int(sid)
        with self._backend.lock:
            if sid in self._backend.servos:
                val = self._backend.servos[sid].get(self._field_name)
                return val if val is not None else default
            return default

    def __contains__(self, sid):
        try:
            sid = int(sid)
            return sid in self._get_sids() and sid in self._backend.servos
        except (ValueError, TypeError):
            return False

    def keys(self):
        with self._backend.lock:
            return [sid for sid in self._get_sids() if sid in self._backend.servos]

    def values(self):
        with self._backend.lock:
            return [self._backend.servos[sid].get(self._field_name) for sid in self.keys()]

    def items(self):
        with self._backend.lock:
            return [(sid, self._backend.servos[sid].get(self._field_name)) for sid in self.keys()]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self.keys())

    def __repr__(self):
        with self._backend.lock:
            return str(dict(self.items()))


class _ServoMotorStatesProxy(dict):
    """Dynamic dict proxy providing {connected, error} dicts for each servo ID."""

    def __init__(self, backend: Any):
        self._backend = backend
        super().__init__()

    def __getitem__(self, sid):
        sid = int(sid)
        with self._backend.lock:
            if sid in self._backend.servos:
                s = self._backend.servos[sid]
                return {"connected": s.get("connected", False), "error": s.get("error")}
            raise KeyError(sid)

    def __setitem__(self, sid, val):
        sid = int(sid)
        with self._backend.lock:
            if sid not in self._backend.servos:
                self._backend.servos[sid] = {"name": MOTOR_NAMES.get(sid, f"motor_{sid}")}
            if isinstance(val, dict):
                self._backend.servos[sid]["connected"] = val.get("connected", False)
                self._backend.servos[sid]["error"] = val.get("error")

    def get(self, sid, default=None):
        sid = int(sid)
        with self._backend.lock:
            if sid in self._backend.servos:
                s = self._backend.servos[sid]
                return {"connected": s.get("connected", False), "error": s.get("error")}
            return default

    def keys(self):
        with self._backend.lock:
            return list(self._backend.servos.keys())

    def values(self):
        with self._backend.lock:
            return [
                {
                    "connected": self._backend.servos[sid].get("connected", False),
                    "error": self._backend.servos[sid].get("error"),
                }
                for sid in self._backend.servos
            ]

    def items(self):
        with self._backend.lock:
            return [
                (
                    sid,
                    {
                        "connected": self._backend.servos[sid].get("connected", False),
                        "error": self._backend.servos[sid].get("error"),
                    },
                )
                for sid in self._backend.servos
            ]

    def __contains__(self, sid):
        try:
            return int(sid) in self._backend.servos
        except (ValueError, TypeError):
            return False

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        with self._backend.lock:
            return len(self._backend.servos)

    def __repr__(self):
        with self._backend.lock:
            return str(dict(self.items()))
