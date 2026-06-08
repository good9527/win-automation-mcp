"""
Windows Automation Tools - Command Line Interface
Usage: python tools.py <command> [args...]

Features:
  - SendInput for keyboard (no PyAutoGUI dependency for key/type)
  - BitBlt fallback for screenshot capture
  - Clipboard save/restore around paste operations
  - Auto-incrementing screenshot IDs with coordinate reference
  - DPI-aware coordinate scaling
  - Stale element detection in accessibility tree
  - Expanded key map (numpad, F-keys, navigation)
  - get_window command for HWND rehydration
"""

import ctypes
import ctypes.wintypes
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import subprocess

# PIL is required for screenshot bitmap conversion
from PIL import Image as PILImage

# Shared constants, structs, utilities
from common import (
    user32, kernel32, shell32, gdi32,
    INPUT, INPUT_UNION, KEYBDINPUT, MOUSEINPUT,
    BITMAPINFOHEADER, BITMAPINFO,
    GWL_STYLE, GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW,
    SW_RESTORE, SW_SHOWNORMAL,
    PROCESS_QUERY_LIMITED_INFORMATION, MAX_PATH,
    PW_RENDERFULLCONTENT, CF_UNICODETEXT, GMEM_MOVEABLE, SRCCOPY, WHEEL_DELTA,
    INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE,
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP,
    STATE_FILE, _load_state, _save_state,
    _get_dpi_scale, _get_process_name,
    _enum_windows, _set_clipboard_text, _check_safety,
    _KEYMAP, _keysym_to_scancode, KEYMAP,
)

# ---------------------------------------------------------------------------
# Helper server client
# ---------------------------------------------------------------------------
HELPER_URL = "http://127.0.0.1:18765"
_helper_process = None


def _cleanup_helper():
    """Terminate helper process on exit if we spawned it."""
    global _helper_process
    if _helper_process and _helper_process.poll() is None:
        try:
            _helper_process.terminate()
            _helper_process.wait(timeout=2)
        except Exception:
            pass


import atexit
atexit.register(_cleanup_helper)


def _ensure_helper():
    """Auto-start the helper server if not running."""
    global _helper_process
    if _helper_available():
        return
    helper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helper.py")
    _helper_process = subprocess.Popen(
        [sys.executable, helper_path, "--port", "18765"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        time.sleep(0.2)
        if _helper_available():
            return


def _helper_available() -> bool:
    try:
        resp = urllib.request.urlopen(f"{HELPER_URL}/health", timeout=1)
        return resp.status == 200
    except Exception:
        return False


def _helper_post(path: str, data: dict) -> dict:
    try:
        req = urllib.request.Request(
            f"{HELPER_URL}{path}",
            data=json.dumps(data).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def _helper_get(path: str) -> dict:
    try:
        resp = urllib.request.urlopen(f"{HELPER_URL}{path}", timeout=5)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Window rect wrapper — common.py returns RECT, tools.py uses tuple
# ---------------------------------------------------------------------------
def _get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Return (left, top, right, bottom) using DWM visible bounds, or None."""
    from common import _get_window_rect as _get_rect
    rect = _get_rect(hwnd)
    if rect:
        return (rect.left, rect.top, rect.right, rect.bottom)
    return None


# ---------------------------------------------------------------------------
# Global state for screenshot tracking
# ---------------------------------------------------------------------------
_screenshot_counter: int = 0
_screenshots: Dict[int, Dict[str, Any]] = {}
_last_screenshot_size: Tuple[int, int] = (1280, 834)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
def _state_get(key: str | None = None) -> dict:
    state = _load_state()
    if key:
        if key in state:
            return {key: state[key]}
        return {"error": f"Key '{key}' not found"}
    return {"state": state}


def _state_set(key: str, value: Any) -> dict:
    state = _load_state()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
    state[key] = value
    _save_state(state)
    return {"ok": True, "state": state}


def _state_target(hwnd: int) -> dict:
    state = _load_state()
    state["target_hwnd"] = hwnd
    _save_state(state)
    return {"ok": True, "target_hwnd": hwnd}


def _resolve_target(hwnd: int | None) -> int:
    if hwnd is not None:
        return hwnd
    state = _load_state()
    target = state.get("target_hwnd")
    if target:
        return target
    raise RuntimeError(
        "No hwnd provided and no target_hwnd in state. "
        "Run: python tools.py state target <hwnd>"
    )


def _get_screenshot_size(screenshot_id: int | None) -> Dict[str, int]:
    if screenshot_id is not None and screenshot_id in _screenshots:
        meta = _screenshots[screenshot_id]
        return {"width": meta["width"], "height": meta["height"]}
    return {"width": _last_screenshot_size[0], "height": _last_screenshot_size[1]}


# ---------------------------------------------------------------------------
# Window list (uses common._enum_windows, adapts format)
# ---------------------------------------------------------------------------
def list_apps() -> List[Dict[str, Any]]:
    if _helper_available():
        result = _helper_get("/list_apps")
        if not isinstance(result, dict) or "error" not in result:
            return result

    windows = _enum_windows()
    apps_map: Dict[str, Dict[str, Any]] = {}
    for w in windows:
        pid = w.get("pid", 0)
        proc_name = w.get("process_name", "")
        proc_path = w.get("process_path", "")
        if not proc_name:
            continue
        key = proc_name
        if key not in apps_map:
            apps_map[key] = {
                "app_name": proc_name, "app_path": proc_path,
                "is_running": True, "windows": [],
            }
        apps_map[key]["windows"].append({
            "hwnd": w["hwnd"], "title": w["title"],
            "pid": pid, "rect": w.get("rect", {}),
        })
    return list(apps_map.values())


def enum_windows() -> List[Dict[str, Any]]:
    return _enum_windows()


# ---------------------------------------------------------------------------
# Coordinate scaling
# ---------------------------------------------------------------------------
def _scale_coords(
    hwnd: int, x: int, y: int, screenshot_id: Optional[int] = None,
) -> Tuple[int, int, str]:
    global _last_screenshot_size

    rect = _get_window_rect(hwnd)
    if rect is None:
        raise RuntimeError(f"Cannot get window rect for hwnd {hwnd}")

    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    ss_w, ss_h = None, None
    if screenshot_id is not None and screenshot_id in _screenshots:
        meta = _screenshots[screenshot_id]
        ss_w = meta["width"]
        ss_h = meta["height"]

    if not ss_w:
        ss_w = 1280 if log_w > 1280 else log_w
    if not ss_h:
        ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

    scale = _get_dpi_scale(hwnd)

    real_x = x * log_w / ss_w
    real_y = y * log_h / ss_h
    phys_x = int(real_x + rect[0])  # rect[0] = left
    phys_y = int(real_y + rect[1])  # rect[1] = top

    return phys_x, phys_y, (
        f"screenshot({x},{y}) -> screen({phys_x},{phys_y}) "
        f"[log {log_w}x{log_h}, ss {ss_w}x{ss_h}, dpi_scale={scale:.2f}]"
    )


# ---------------------------------------------------------------------------
# Window activation
# ---------------------------------------------------------------------------
def activate_window(hwnd: int) -> bool:
    if _helper_available():
        result = _helper_post("/activate", {"hwnd": hwnd})
        if "error" not in result:
            return result.get("ok", False)

    try:
        foreground = user32.GetForegroundWindow()
        foreground_tid = user32.GetWindowThreadProcessId(foreground, None)
        current_tid = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(current_tid, foreground_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(current_tid, foreground_tid, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Window handle rehydration
# ---------------------------------------------------------------------------
def get_windows_for_pid(pid: int) -> List[int]:
    hwnds: List[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            w_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
            if w_pid.value == pid:
                hwnds.append(int(hwnd))
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, None)
    return hwnds


def get_window(hwnd: int) -> str:
    if user32.IsWindow(hwnd):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return json.dumps({
            "hwnd": hwnd, "title": buf.value.strip(),
            "pid": pid.value, "status": "valid",
        }, ensure_ascii=False)

    return json.dumps({
        "hwnd": hwnd, "status": "stale",
        "message": f"HWND {hwnd} is no longer valid. Call list_windows to get current window handles.",
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# SendInput helpers
# ---------------------------------------------------------------------------
def _send_key_down(scancode: int) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = scancode & 0xFF
    inp.union.ki.dwFlags = KEYEVENTF_SCANCODE
    if scancode & 0xE000:
        inp.union.ki.dwFlags |= 0x0001  # EXTENDEDKEY
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def _send_key_up(scancode: int) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = scancode & 0xFF
    inp.union.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    if scancode & 0xE000:
        inp.union.ki.dwFlags |= 0x0001  # EXTENDEDKEY
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def _send_ctrl_v() -> None:
    ctrl_sc = _KEYMAP.get("ctrl", 0x1D)
    v_sc = _KEYMAP.get("v", 0x2F)
    _send_key_down(ctrl_sc)
    time.sleep(0.02)
    _send_key_down(v_sc)
    time.sleep(0.02)
    _send_key_up(v_sc)
    time.sleep(0.02)
    _send_key_up(ctrl_sc)


# ---------------------------------------------------------------------------
# Clipboard save/restore
# ---------------------------------------------------------------------------
def _clipboard_save() -> Optional[bytes]:
    if not user32.OpenClipboard(0):
        return None
    try:
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return None
        p_data = kernel32.GlobalLock(h_data)
        if not p_data:
            return None
        text = ctypes.wstring_at(p_data)
        kernel32.GlobalUnlock(h_data)
        return text.encode("utf-16-le") + b"\x00\x00"
    except Exception:
        return None
    finally:
        user32.CloseClipboard()


def _clipboard_restore(saved: Optional[bytes]) -> None:
    if saved is None:
        return
    if not user32.OpenClipboard(0):
        return
    try:
        user32.EmptyClipboard()
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(saved))
        if h_mem:
            p_mem = kernel32.GlobalLock(h_mem)
            if p_mem:
                ctypes.memmove(p_mem, saved, len(saved))
                kernel32.GlobalUnlock(h_mem)
                user32.SetClipboardData(CF_UNICODETEXT, h_mem)
    except Exception:
        pass
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------
def screenshot(
    hwnd: int, output_path: str, max_width: int = 1280,
) -> Dict[str, Any]:
    global _screenshot_counter, _screenshots, _last_screenshot_size

    rect = _get_window_rect(hwnd)
    if rect is None:
        return {"error": f"Cannot get window rect for hwnd {hwnd}"}

    win_left, win_top, win_right, win_bottom = rect
    win_w = win_right - win_left
    win_h = win_bottom - win_top
    if win_w <= 0 or win_h <= 0:
        return {"error": f"Invalid window dimensions: {win_w}x{win_h}"}

    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    dpi_scale = _get_dpi_scale(hwnd)

    hdc_window = user32.GetDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbitmap = gdi32.CreateCompatibleBitmap(hdc_window, log_w, log_h)
    old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)

    result = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
    if not result:
        result = user32.PrintWindow(hwnd, hdc_mem, 0)

    if not result:
        # BitBlt fallback
        gdi32.SelectObject(hdc_mem, old_bmp)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)

        hdc_screen = user32.GetDC(0)
        hdc_mem2 = gdi32.CreateCompatibleDC(hdc_screen)
        hbitmap2 = gdi32.CreateCompatibleBitmap(hdc_screen, win_w, win_h)
        gdi32.SelectObject(hdc_mem2, hbitmap2)
        gdi32.BitBlt(hdc_mem2, 0, 0, win_w, win_h,
                      hdc_screen, win_left, win_top, SRCCOPY)

        width = win_w
        height = win_h

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)
        gdi32.GetDIBits(hdc_mem2, hbitmap2, 0, height, buf, ctypes.byref(bmi), 0)

        img = PILImage.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)

        gdi32.SelectObject(hdc_mem2, gdi32.GetCurrentObject(hdc_mem2, 7))
        gdi32.DeleteObject(hbitmap2)
        gdi32.DeleteDC(hdc_mem2)
        user32.ReleaseDC(0, hdc_screen)
    else:
        width = log_w
        height = log_h

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)
        gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)

        img = PILImage.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)

        gdi32.SelectObject(hdc_mem, old_bmp)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)

    img = img.convert("RGB")
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        img = img.resize((max_width, new_height), PILImage.LANCZOS)

    ext = os.path.splitext(output_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        img.save(output_path, "JPEG", quality=85)
    else:
        img.save(output_path, "PNG", optimize=True)

    _screenshot_counter += 1
    ss_id = _screenshot_counter
    _last_screenshot_size = (img.width, img.height)

    meta = {
        "id": ss_id, "path": output_path,
        "width": img.width, "height": img.height,
        "dpi_scale": dpi_scale, "window_hwnd": hwnd,
    }
    _screenshots[ss_id] = meta
    return meta


# ---------------------------------------------------------------------------
# Click
# ---------------------------------------------------------------------------
def click(
    hwnd: int | None, x: int, y: int,
    button: str = "left", clicks: int = 1,
    screenshot_id: Optional[int] = None,
) -> str:
    hwnd = _resolve_target(hwnd)

    if _helper_available():
        ss_info = _get_screenshot_size(screenshot_id)
        result = _helper_post("/click", {
            "hwnd": hwnd, "x": x, "y": y,
            "button": button, "clicks": clicks, "activate": True,
            "screenshot_width": ss_info["width"],
            "screenshot_height": ss_info["height"],
        })
        if "error" not in result:
            click_type = "Double-clicked" if clicks == 2 else f"Clicked(x{clicks})" if clicks > 2 else "Clicked"
            return f"{click_type} ({button}): screen({result.get('screen_x',0)},{result.get('screen_y',0)})"

    activate_window(hwnd)
    time.sleep(0.1)
    screen_x, screen_y, debug = _scale_coords(hwnd, x, y, screenshot_id)
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)

    for i in range(clicks):
        if i > 0:
            time.sleep(0.05)
        if button == "right":
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, None)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, None)
        else:
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)

    click_type = "Double-clicked" if clicks == 2 else f"Clicked(x{clicks})" if clicks > 2 else "Clicked"
    return f"{click_type} ({button}): {debug}"


# ---------------------------------------------------------------------------
# Type text
# ---------------------------------------------------------------------------
def type_text(hwnd: int | None, text: str) -> str:
    hwnd = _resolve_target(hwnd)

    if _helper_available():
        result = _helper_post("/type_text", {"hwnd": hwnd, "text": text, "activate": True})
        if "error" not in result:
            return f"Pasted {len(text)} characters"

    activate_window(hwnd)
    time.sleep(0.1)

    saved_clip = _clipboard_save()
    _set_clipboard_text(text)
    time.sleep(0.05)
    _send_ctrl_v()
    time.sleep(0.05)
    _clipboard_restore(saved_clip)

    return f"Pasted {len(text)} characters"


# ---------------------------------------------------------------------------
# Press key
# ---------------------------------------------------------------------------
def press_key(hwnd: int | None, keys: str) -> str:
    hwnd = _resolve_target(hwnd)

    if _helper_available():
        result = _helper_post("/press_key", {"hwnd": hwnd, "keys": keys, "activate": True})
        if "error" not in result:
            return f"Pressed: {keys}"

    activate_window(hwnd)
    time.sleep(0.1)

    parts = keys.replace(" ", "").split("+")
    scancodes = []
    for part in parts:
        try:
            scancodes.append((part, _keysym_to_scancode(part)))
        except ValueError:
            if len(part) == 1:
                scancodes.append((part, _keysym_to_scancode(part.lower())))
            else:
                return f"Error: Unknown key '{part}'"

    for _, sc in scancodes:
        _send_key_down(sc)
        time.sleep(0.02)
    for _, sc in reversed(scancodes):
        _send_key_up(sc)
        time.sleep(0.02)

    return f"Pressed: {keys}"


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------
def scroll(
    hwnd: int | None, x: int, y: int, scroll_y: int,
    screenshot_id: Optional[int] = None,
) -> str:
    hwnd = _resolve_target(hwnd)

    if _helper_available():
        ss_info = _get_screenshot_size(screenshot_id)
        result = _helper_post("/scroll", {
            "hwnd": hwnd, "x": x, "y": y,
            "delta": -scroll_y * 120, "clicks": abs(scroll_y),
            "activate": True,
            "screenshot_width": ss_info["width"],
            "screenshot_height": ss_info["height"],
        })
        if "error" not in result:
            return f"Scrolled: dy={scroll_y}"

    activate_window(hwnd)
    time.sleep(0.1)
    screen_x, screen_y, debug = _scale_coords(hwnd, x, y, screenshot_id)
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    wheel_delta = -scroll_y * WHEEL_DELTA
    user32.mouse_event(0x0800, 0, 0, wheel_delta, None)

    return f"Scrolled: dy={scroll_y} at {debug}"


# ---------------------------------------------------------------------------
# Drag
# ---------------------------------------------------------------------------
def drag(
    hwnd: int, start_x: int, start_y: int, end_x: int, end_y: int,
    duration: float = 0.5, screenshot_id: Optional[int] = None,
) -> str:
    activate_window(hwnd)
    time.sleep(0.1)

    sx, sy, _ = _scale_coords(hwnd, start_x, start_y, screenshot_id)
    ex, ey, _ = _scale_coords(hwnd, end_x, end_y, screenshot_id)

    user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.05)

    steps = max(int(duration / 0.02), 1)
    for i in range(1, steps + 1):
        t = i / steps
        ix = int(sx + (ex - sx) * t)
        iy = int(sy + (ey - sy) * t)
        user32.SetCursorPos(ix, iy)
        time.sleep(duration / steps)

    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    return f"Dragged screenshot({start_x},{start_y})->({end_x},{end_y}) screen({sx},{sy})->({ex},{ey})"


# ---------------------------------------------------------------------------
# Accessibility tree
# ---------------------------------------------------------------------------
def _validate_element(elem) -> bool:
    try:
        _ = elem.CurrentBoundingRectangle
        return True
    except Exception:
        return False


def build_accessibility_tree(
    hwnd: int, max_depth: int = 10, max_elements: int = 500,
) -> Dict[str, Any]:
    try:
        import comtypes
        import comtypes.client
        import comtypes.gen.UIAutomationClient as UIAClient
    except ImportError:
        return {"error": "comtypes not installed - run: pip install comtypes"}

    try:
        uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=UIAClient.IUIAutomation,
        )

        root = uia.ElementFromHandle(hwnd)
        if not root:
            return {"error": "No accessible content for this window"}

        lines: List[str] = []
        element_map: List[Dict[str, Any]] = []
        counter = [0]

        def walk(elem, depth: int) -> None:
            if depth > max_depth or counter[0] >= max_elements:
                return
            idx = counter[0]
            counter[0] += 1

            try:
                name = elem.CurrentName or ""
                control_type = elem.CurrentLocalizedControlType or ""
                rect = elem.CurrentBoundingRectangle
                is_enabled = elem.CurrentIsEnabled

                patterns: List[str] = []
                for pid, pname in [
                    (10002, "Value"), (10000, "Invoke"), (10001, "Toggle"),
                    (10005, "Selection"), (10010, "Scroll"),
                ]:
                    try:
                        if elem.GetCurrentPattern(pid):
                            patterns.append(pname)
                    except Exception:
                        pass

                indent = "  " * depth
                pattern_str = f" [{', '.join(patterns)}]" if patterns else ""

                value_str = ""
                if "Value" in patterns:
                    try:
                        vp = elem.GetCurrentPattern(10002)
                        value_str = f' value="{vp.CurrentValue}"'
                    except Exception:
                        pass

                name_display = f'"{name}"' if name else '""'
                lines.append(f"{indent}[{idx}] {name_display} ({control_type}){pattern_str}{value_str}")

                element_map.append({
                    "index": idx, "name": name, "control_type": control_type,
                    "patterns": patterns,
                    "rect": {"left": rect.left if rect else 0, "top": rect.top if rect else 0,
                             "right": rect.right if rect else 0, "bottom": rect.bottom if rect else 0},
                    "enabled": is_enabled,
                })

                walker = uia.CreateTreeWalker(uia.RawViewCondition)
                try:
                    child = walker.GetFirstChildElement(elem)
                    while child:
                        walk(child, depth + 1)
                        child = walker.GetNextSiblingElement(child)
                except Exception:
                    pass
            except Exception:
                pass

        walk(root, 0)

        focused_info: Optional[Dict[str, Any]] = None
        try:
            focused_elem = uia.GetFocusedElement()
            if focused_elem:
                fname = focused_elem.CurrentName or ""
                ftype = focused_elem.CurrentLocalizedControlType or ""
                selected_text = ""
                try:
                    vp = focused_elem.GetCurrentPattern(10002)
                    selected_text = vp.CurrentValue or ""
                except Exception:
                    pass
                focused_info = {"name": fname, "control_type": ftype, "selected_text": selected_text}
        except Exception:
            pass

        return {
            "tree": "\n".join(lines) if lines else "No accessible elements found",
            "elements": element_map,
            "focused": focused_info,
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Batch execution
# ---------------------------------------------------------------------------
def _batch_execute_local(command_name: str, args: dict) -> dict:
    try:
        if command_name == "activate":
            hwnd = args.get("hwnd")
            if not hwnd:
                return {"error": "hwnd required"}
            return {"ok": activate_window(hwnd)}
        elif command_name == "click":
            result = click(args.get("hwnd"), args.get("x", 0), args.get("y", 0),
                           args.get("button", "left"), args.get("clicks", 1), args.get("screenshot_id"))
            return {"ok": True, "message": result}
        elif command_name == "type":
            result = type_text(args.get("hwnd"), args.get("text", ""))
            return {"ok": True, "message": result}
        elif command_name == "key":
            result = press_key(args.get("hwnd"), args.get("keys", ""))
            return {"ok": True, "message": result}
        elif command_name == "scroll":
            result = scroll(args.get("hwnd"), args.get("x", 0), args.get("y", 0),
                            args.get("dy", 0), args.get("screenshot_id"))
            return {"ok": True, "message": result}
        elif command_name == "screenshot":
            hwnd = args.get("hwnd")
            if not hwnd:
                return {"error": "hwnd required for screenshot"}
            output = args.get("output", os.path.join(os.path.dirname(__file__), "screenshot.jpg"))
            result = screenshot(hwnd, output, args.get("max_width", 1280))
            return result
        else:
            return {"error": f"Unknown local command: {command_name}"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    input_commands = {"click", "type", "key", "scroll", "drag", "activate"}
    if len(sys.argv) > 1 and sys.argv[1] in input_commands:
        _ensure_helper()

    if len(sys.argv) < 2:
        print("Usage: python tools.py <command> [args...]")
        print()
        print("Commands:")
        print("  list_windows                                List all visible windows")
        print("  list_apps                                   List apps grouped by process")
        print("  get_window <hwnd>                           Get/validate a window handle (rehydrate)")
        print("  screenshot <hwnd> [output.jpg]              Capture window screenshot (returns JSON with id)")
        print("  screenshot_b64 <hwnd>                       Capture screenshot as base64 PNG")
        print("  accessibility <hwnd>                        Get accessibility tree + focused element")
        print("  click <hwnd> <x> <y> [button] [clicks] [screenshot_id] Click at coordinates (clicks=2 for double-click)")
        print("  type <hwnd> <text>                          Type/paste text via clipboard")
        print("  key <hwnd> <keys>                           Press key combo (e.g. ctrl+a)")
        print("  scroll <hwnd> <x> <y> <dy> [screenshot_id] Scroll at coordinates")
        print("  drag <hwnd> <x1> <y1> <x2> <y2> [screenshot_id] Drag between coordinates")
        print("  activate <hwnd>                             Bring window to foreground")
        print("  batch '<json_commands>'                     Execute multiple commands in one call")
        print("  state get [key]                             Get state (all or specific key)")
        print("  state set <key> <value>                     Set a state key/value pair")
        print("  state target <hwnd>                         Set current target window")
        print("  confirm <action>                            Check if action needs user confirmation")
        print()
        print("Note: click/type/key/scroll auto-use 'target' from state if no hwnd given.")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list_windows":
        windows = _enum_windows()
        for w in windows:
            print(json.dumps(w, ensure_ascii=False))

    elif cmd == "get_window":
        if len(sys.argv) < 3:
            print("Error: hwnd required"); sys.exit(1)
        print(get_window(int(sys.argv[2])))

    elif cmd == "screenshot":
        if len(sys.argv) < 3:
            print("Error: hwnd required"); sys.exit(1)
        hwnd = int(sys.argv[2])
        output = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(__file__), "screenshot.jpg")
        print(json.dumps(screenshot(hwnd, output), ensure_ascii=False))

    elif cmd == "accessibility":
        if len(sys.argv) < 3:
            print("Error: hwnd required"); sys.exit(1)
        print(json.dumps(build_accessibility_tree(int(sys.argv[2])), ensure_ascii=False))

    elif cmd == "click":
        if len(sys.argv) < 5:
            print("Error: hwnd, x, y required"); sys.exit(1)
        hwnd = int(sys.argv[2])
        x, y = int(sys.argv[3]), int(sys.argv[4])
        button = sys.argv[5] if len(sys.argv) > 5 else "left"
        clicks = int(sys.argv[6]) if len(sys.argv) > 6 else 1
        screenshot_id = int(sys.argv[7]) if len(sys.argv) > 7 else None
        print(click(hwnd, x, y, button, clicks, screenshot_id))

    elif cmd == "type":
        if len(sys.argv) < 4:
            print("Error: hwnd and text required"); sys.exit(1)
        print(type_text(int(sys.argv[2]), sys.argv[3]))

    elif cmd == "key":
        if len(sys.argv) < 4:
            print("Error: hwnd and keys required"); sys.exit(1)
        print(press_key(int(sys.argv[2]), sys.argv[3]))

    elif cmd == "scroll":
        if len(sys.argv) < 6:
            print("Error: hwnd, x, y, dy required"); sys.exit(1)
        hwnd = int(sys.argv[2])
        x, y, dy = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
        screenshot_id = int(sys.argv[6]) if len(sys.argv) > 6 else None
        print(scroll(hwnd, x, y, dy, screenshot_id))

    elif cmd == "drag":
        if len(sys.argv) < 7:
            print("Error: hwnd, x1, y1, x2, y2 required"); sys.exit(1)
        hwnd = int(sys.argv[2])
        x1, y1 = int(sys.argv[3]), int(sys.argv[4])
        x2, y2 = int(sys.argv[5]), int(sys.argv[6])
        screenshot_id = int(sys.argv[7]) if len(sys.argv) > 7 else None
        print(drag(hwnd, x1, y1, x2, y2, 0.5, screenshot_id))

    elif cmd == "activate":
        if len(sys.argv) < 3:
            print("Error: hwnd required"); sys.exit(1)
        hwnd = int(sys.argv[2])
        if activate_window(hwnd):
            print(f"Activated window {hwnd}")
        else:
            print(f"Failed to activate window {hwnd}")

    elif cmd == "list_apps":
        result = list_apps()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "screenshot_b64":
        if len(sys.argv) < 3:
            print("Error: hwnd required"); sys.exit(1)
        hwnd = int(sys.argv[2])
        max_w = int(sys.argv[3]) if len(sys.argv) > 3 else 1280
        if _helper_available():
            result = _helper_get(f"/screenshot_b64?hwnd={hwnd}&max_width={max_w}")
        else:
            import tempfile, base64 as _b64
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                result = screenshot(hwnd, tmp_path, max_w)
                if "error" not in result:
                    with open(tmp_path, "rb") as f:
                        png_data = f.read()
                    result = {
                        "text": "Captured window screenshot.",
                        "base64": _b64.b64encode(png_data).decode("ascii"),
                        "width": result["width"], "height": result["height"],
                        "dpi_scale": result.get("dpi_scale", 1.0),
                    }
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        print(json.dumps(result, ensure_ascii=False))

    elif cmd == "state":
        if len(sys.argv) < 3:
            print("Error: state subcommand required (get/set/target)"); sys.exit(1)
        subcmd = sys.argv[2]
        if subcmd == "get":
            key = sys.argv[3] if len(sys.argv) > 3 else None
            print(json.dumps(_state_get(key), ensure_ascii=False))
        elif subcmd == "set":
            if len(sys.argv) < 5:
                print("Error: state set requires <key> <value>"); sys.exit(1)
            print(json.dumps(_state_set(sys.argv[3], sys.argv[4]), ensure_ascii=False))
        elif subcmd == "target":
            if len(sys.argv) < 4:
                print("Error: state target requires <hwnd>"); sys.exit(1)
            print(json.dumps(_state_target(int(sys.argv[3])), ensure_ascii=False))
        else:
            print(f"Error: Unknown state subcommand '{subcmd}'"); sys.exit(1)

    elif cmd == "batch":
        if len(sys.argv) < 3:
            print("Error: batch requires JSON command list"); sys.exit(1)
        try:
            commands = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON: {e}"); sys.exit(1)
        if _helper_available():
            result = _helper_post("/batch", {"commands": commands})
            if "error" not in result:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                results = []
                for cmd_item in commands:
                    r = _batch_execute_local(cmd_item.get("command", ""), cmd_item.get("args", {}))
                    results.append({"command": cmd_item.get("command", ""), "result": r})
                print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
        else:
            results = []
            for cmd_item in commands:
                r = _batch_execute_local(cmd_item.get("command", ""), cmd_item.get("args", {}))
                results.append({"command": cmd_item.get("command", ""), "result": r})
            print(json.dumps({"results": results}, ensure_ascii=False, indent=2))

    elif cmd == "confirm":
        if len(sys.argv) < 3:
            print("Error: confirm requires action string"); sys.exit(1)
        action = " ".join(sys.argv[2:])
        print(json.dumps(_check_safety(action), ensure_ascii=False))

    else:
        print(f"Error: Unknown command '{cmd}'")
        sys.exit(1)


if __name__ == "__main__":
    main()
