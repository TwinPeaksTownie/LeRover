"""
tools_computer_use.py - Deterministic Desktop Interaction & Feedback Injection
Safely focuses the Antigravity window, targets the chat input area via relative coordinates,
pastes rejection / verification prompts, and triggers message dispatch.
Supports Windows native Win32 API and Docker container via host bridge webhook.
"""

import ctypes
import json
import os
import sys
import time
import urllib.request

def _log_debug(msg: str):
    sys.stderr.write(f"[COMPUTER_USE] {msg}\n")
    sys.stderr.flush()

try:
    import win32gui
    import win32con
    import win32clipboard
    import win32api
    import win32process
    import psutil
    HAS_WIN32 = True
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
except ImportError:
    HAS_WIN32 = False

def get_active_window() -> dict:
    if not HAS_WIN32:
        return {"status": "container_mode", "title": "Docker Container", "process": "python"}

    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return {"status": "success", "hwnd": 0, "title": "None", "process": "None"}
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        pname = "unknown"
        try:
            pname = psutil.Process(pid).name()
        except Exception:
            pass
        return {
            "status": "success",
            "hwnd": hwnd,
            "title": title,
            "pid": pid,
            "process_name": pname
        }
    except Exception as e:
        return {"status": "error", "error": f"Failed to get active window: {str(e)}"}

def find_antigravity_window() -> dict:
    if not HAS_WIN32:
        return {"status": "container_mode", "message": "Running inside Docker container"}

    target_hwnd = None
    target_title = None

    try:
        ag_pids = {p.pid for p in psutil.process_iter(['pid', 'name']) if 'antigravity' in p.info['name'].lower()}
        def enum_cb(hwnd, _):
            nonlocal target_hwnd, target_title
            if target_hwnd:
                return
            if win32gui.IsWindowVisible(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in ag_pids:
                    title = win32gui.GetWindowText(hwnd)
                    if title and not win32gui.GetParent(hwnd):
                        target_hwnd = hwnd
                        target_title = title
        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass
    except Exception as e:
        _log_debug(f"Process window search error: {e}")

    if not target_hwnd:
        keywords = ["antigravity", "gemini", "aux_servo_interface"]
        def title_cb(hwnd, _):
            nonlocal target_hwnd, target_title
            if target_hwnd:
                return
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if any(k in t.lower() for k in keywords):
                    target_hwnd = hwnd
                    target_title = t
        try:
            win32gui.EnumWindows(title_cb, None)
        except Exception:
            pass

    if not target_hwnd:
        return {"status": "error", "error": "Antigravity window not found"}

    try:
        rect = win32gui.GetWindowRect(target_hwnd)
        left, top, right, bottom = rect
        return {
            "status": "success",
            "hwnd": target_hwnd,
            "title": target_title,
            "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
            "width": right - left,
            "height": bottom - top
        }
    except Exception as e:
        return {"status": "error", "error": f"Failed to get window rect: {str(e)}"}

def _set_clipboard_text(text: str) -> bool:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return True
        except Exception:
            time.sleep(0.05)
    return False

def send_feedback_to_antigravity(
    feedback_text: str,
    click_send: bool = True,
    input_ratio_x: float = 0.50,
    input_offset_y: int = -65,
    send_ratio_x: float = 0.64,
    send_offset_y: int = -45
) -> dict:
    """
    Brings Antigravity to the foreground, clicks explicitly into the chat input area,
    pastes the feedback text, and submits the message.
    """
    if not feedback_text or not feedback_text.strip():
        return {"status": "error", "error": "Feedback text cannot be empty"}

    # If running inside Linux container, forward request to Windows host bridge
    if not HAS_WIN32:
        host_bridge_url = os.environ.get("HOST_BRIDGE_URL", "http://host.docker.internal:8059/inject")
        _log_debug(f"Container mode: forwarding feedback injection to host bridge {host_bridge_url}")
        try:
            payload = json.dumps({
                "feedback_text": feedback_text,
                "click_send": click_send
            }).encode("utf-8")
            req = urllib.request.Request(
                host_bridge_url,
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as res:
                return json.loads(res.read())
        except Exception as e:
            _log_debug(f"Host bridge not reachable ({e}). Logged feedback in container.")
            return {
                "status": "container_fallback",
                "message": "Feedback recorded in container logs (host bridge inactive).",
                "feedback_snippet": feedback_text[:200]
            }

    win_info = find_antigravity_window()
    if win_info.get("status") != "success":
        return win_info

    hwnd = win_info["hwnd"]
    title = win_info["title"]
    rect = win_info["rect"]
    left, top, right, bottom = rect["left"], rect["top"], rect["right"], rect["bottom"]
    width = win_info["width"]
    height = win_info["height"]

    _log_debug(f"Targeting window HWND {hwnd} ({title}) - Bounds: ({left}, {top}, {width}x{height})")

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.15)

        click_x = left + int(width * input_ratio_x)
        click_y = bottom + input_offset_y

        win32api.SetCursorPos((click_x, click_y))
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.1)

        if not _set_clipboard_text(feedback_text.strip()):
            return {"status": "error", "error": "Failed to access Windows clipboard"}

        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(ord('A'), 0, 0, 0)
        time.sleep(0.02)
        win32api.keybd_event(ord('A'), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)

        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(ord('V'), 0, 0, 0)
        time.sleep(0.02)
        win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)

        if click_send:
            _log_debug("Sending Return key to dispatch chat message")
            win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
            time.sleep(0.02)
            win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)

        return {
            "status": "success",
            "message": "Feedback successfully staged and dispatched to Antigravity.",
            "target_window": title,
            "target_hwnd": hwnd,
            "input_click_coords": {"x": click_x, "y": click_y},
            "injected_char_count": len(feedback_text)
        }
    except Exception as e:
        return {"status": "error", "error": f"Failed during input injection: {str(e)}"}
