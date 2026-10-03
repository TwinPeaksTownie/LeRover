# Implementation Plan: Calibrate Gantry Motor 8 Safe Range (100 to 4800 Ticks)

## User Objective
Adjust the LeSlide Gantry (Motor 8) minimum travel limit from 3 ticks to 100 ticks (range: 100 to 4800 ticks) to establish a physical safety buffer off the mechanical hard stop, preventing motor stall overcurrent trips and bus power shutdowns.

---

## 1. JSON Single Source of Truth First (Step 1)
Modify `calibration_aux.json` on disk to set Motor 8's calibrated minimum bound to 100 ticks:
```json
  "8": {
    "center_ticks": 2400,
    "min_ticks": 100,
    "max_ticks": 4800
  }
```

---

## 2. Implementation Scope & Code Changes

### A. Dynamic API Server Enforcement (`pi4b/api_server.py`)
- In `do_POST()` under `/api/slider`:
  Replace hardcoded clamp `val = max(3, min(4800, val))` with dynamic query against backend calibration:
  ```python
  s8_min, s8_max = self.backend.get_s8_bounds()
  val = max(s8_min, min(s8_max, val))
  ```
- This ensures fail-fast alignment with `calibration_aux.json` without hardcoded constants in Python source.

### B. Touch UI Presentation & Dispatch (`pi4b/static/index.html` & `pi4b/static/js/app.js`)
- Update `pi4b/static/index.html`:
  Change the button label on `#gantryMaxLeftBtn` from `(3 TICKS)` to `(100 TICKS)`.
- Update `pi4b/static/js/app.js`:
  In `moveGantryMaxLeft()`: change `sendSliderMove(3)` to `sendSliderMove(100)`.
  In `nudgeSlider(delta)`: clamp using bounds `Math.max(100, Math.min(4800, targetVal))`.

---

## 3. Strict Compliance Checks
- **Rule 13 (Anti-Slop / Zero False Tri-States)**: State machine remains strictly binary (`CONNECTED` vs `DISCONNECTED`), no synthetic third states.
- **Rule 1 (Fail-Fast)**: `get_s8_bounds()` enforces direct dictionary key presence (`aux_calibration["8"]["min_ticks"]`), raising immediate exceptions if corrupt or missing.
- **Rule 3 (Dynamic Arithmetic)**: All range and clamp calculations are resolved dynamically in memory from loaded JSON structures.

---

## 4. Verification & Deployment Pipeline
1. Run local automated regression test suite (`python -m unittest discover tests`).
2. Deploy updated files (`calibration_aux.json`, `pi4b/api_server.py`, `pi4b/static/index.html`, `pi4b/static/js/app.js`) to target Pi 4B (`/home/carson/touch_ui/` and `/home/carson/aux_servo_interface/`).
3. Restart `backend.service` and verify endpoint status on port 8082.
4. Execute Gate 2 Adversarial Review (`invoke_ornith_adversarial_review`).
