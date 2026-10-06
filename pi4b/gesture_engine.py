import time
from enum import Enum, auto
from typing import Dict, Any, Callable
from dataclasses import dataclass
from pi4b.joycon_driver import JoyConState

class JoyConEvent(Enum):
    BUTTON_A_HELD_2S = auto()
    BUTTON_B_HOLD_2S = auto()
    BUTTON_B_SINGLE_CLICK = auto()
    BUTTON_B_DOUBLE_CLICK = auto()
    CHORD_ABORT_TRIGGERED = auto()
    BUTTON_Y_CLICK = auto()
    SHAKE_DETECTED = auto()

class GestureEngine:
    """Temporal and spatial state machines for evaluating Joy-Con gestures."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.a_hold_sec = float(config["gestures"]["a_hold_sec"])
        self.b_hold_sec = float(config["gestures"]["b_hold_sec"])
        self.b_double_tap_sec = float(config["gestures"]["b_double_tap_sec"])
        self.chord_abort_sec = float(config["gestures"]["chord_abort_sec"])
        self.chord_click_suppress_sec = float(config["gestures"]["chord_click_suppress_sec"])

        self.btn_a_press_start: float | None = None
        self.a_hold_triggered = False

        self.btn_b_press_start: float | None = None
        self.b_hold_triggered = False
        self.last_btn_b_click_time = 0.0

        self.both_ab_press_start: float | None = None
        self.ab_hold_triggered = False
        self.chord_suppress_until = 0.0

        self.last_btn_y = False
        self.last_btn_b = False

    def process(self, state: JoyConState) -> list[JoyConEvent]:
        now = state.timestamp
        events = []
        btn_a = state.buttons.get("a", False)
        btn_b = state.buttons.get("b", False)
        btn_y = state.buttons.get("y", False)

        # 0. BUTTON Y CLICK
        if btn_y and not self.last_btn_y:
            events.append(JoyConEvent.BUTTON_Y_CLICK)
        self.last_btn_y = btn_y

        # 0.5 CHORD ABORT GESTURE
        if btn_a and btn_b:
            if self.both_ab_press_start is None:
                self.both_ab_press_start = now
            hold_duration_ab = now - self.both_ab_press_start
            if hold_duration_ab >= self.chord_abort_sec and not self.ab_hold_triggered:
                self.ab_hold_triggered = True
                self.chord_suppress_until = now + self.chord_click_suppress_sec
                events.append(JoyConEvent.CHORD_ABORT_TRIGGERED)
        else:
            self.both_ab_press_start = None
            self.ab_hold_triggered = False

        # 1. BUTTON A HOLD
        if btn_a and not btn_b:
            if self.btn_a_press_start is None:
                self.btn_a_press_start = now
            hold_duration_a = now - self.btn_a_press_start
            if hold_duration_a >= self.a_hold_sec and not self.a_hold_triggered:
                self.a_hold_triggered = True
                events.append(JoyConEvent.BUTTON_A_HELD_2S)
        else:
            self.btn_a_press_start = None
            self.a_hold_triggered = False

        # 2. BUTTON B GESTURES
        if btn_b and not btn_a:
            if self.btn_b_press_start is None:
                self.btn_b_press_start = now
            hold_duration_b = now - self.btn_b_press_start
            if hold_duration_b >= self.b_hold_sec and not self.b_hold_triggered:
                self.b_hold_triggered = True
                events.append(JoyConEvent.BUTTON_B_HOLD_2S)
        else:
            if self.btn_b_press_start is not None:
                duration_b = now - self.btn_b_press_start
                if 0.05 <= duration_b < self.b_hold_sec and not self.b_hold_triggered:
                    time_since_last = now - self.last_btn_b_click_time
                    is_double_tap = (time_since_last <= self.b_double_tap_sec)
                    self.last_btn_b_click_time = now
                    
                    if now >= self.chord_suppress_until:
                        if is_double_tap:
                            events.append(JoyConEvent.BUTTON_B_DOUBLE_CLICK)
                        else:
                            events.append(JoyConEvent.BUTTON_B_SINGLE_CLICK)
            self.btn_b_press_start = None
            self.b_hold_triggered = False

        self.last_btn_b = btn_b

        # TODO: Add IMU shake detection
        return events
