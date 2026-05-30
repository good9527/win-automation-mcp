"""
Windows Automation Tools - Command Line Interface
Usage: python tools.py <command> [args...]

Improvements over original:
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
import hashlib
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import subprocess
import atexit

# ---------------------------------------------------------------------------
# Helper server client - sends input commands to the persistent background process
# ---------------------------------------------------------------------------
HELPER_URL = "http://127.0.0.1:18765"
_helper_process = None

def _ensure_helper():
    """Auto-start the helper server if not running."""
    global _helper_process
    if _helper_available():
        return
    # Start helper in background
    helper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "helper.py")
    _helper_process = subprocess.Popen(
        [sys.executable, helper_path, "--port", "18765"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for it to be ready
    for _ in range(20):
        time.sleep(0.2)
        if _helper_available():
            return
    # If still not ready, fall back to direct SendInput

def _helper_available() -> bool:
    """Check if the helper server is running."""
    try:
        resp = urllib.request.urlopen(f"{HELPER_URL}/health", timeout=1)
        return resp.status == 200
    except Exception:
        return False

def _helper_post(path: str, data: dict) -> dict:
    """Send POST request to helper server."""
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
    """Send GET request to helper server."""
    try:
        resp = urllib.request.urlopen(f"{HELPER_URL}{path}", timeout=5)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

# ---------------------------------------------------------------------------
# DPI awareness — must be set before any window queries
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor aware v2
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# PIL is required for screenshot bitmap conversion
from PIL import Image as PILImage

# ---------------------------------------------------------------------------
# Windows API constants
# ---------------------------------------------------------------------------
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_RESTORE = 9
SW_SHOWNORMAL = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 265
PW_RENDERFULLCONTENT = 0x00000002
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
SRCCOPY = 0x00CC0020
WHEEL_DELTA = 120

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

# ---------------------------------------------------------------------------
# Windows API handles
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
gdi32 = ctypes.windll.gdi32

# ---------------------------------------------------------------------------
# Function prototypes
# ---------------------------------------------------------------------------
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.IsWindow.argtypes = [ctypes.c_void_p]
user32.IsWindow.restype = ctypes.c_bool
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_bool
user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
user32.BringWindowToTop.restype = ctypes.c_bool
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
user32.AttachThreadInput.restype = ctypes.c_bool
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.c_bool
user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
user32.PrintWindow.restype = ctypes.c_bool
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int
user32.OpenClipboard.argtypes = [ctypes.c_void_p]
user32.OpenClipboard.restype = ctypes.c_bool
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.c_bool
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.c_bool
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = ctypes.c_bool
user32.mouse_event.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
user32.mouse_event.restype = None
user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.restype = ctypes.c_uint

# DWM Frame Bounds API
try:
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
except Exception:
    pass

kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)
]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_bool
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = ctypes.c_ulong

gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = ctypes.c_bool
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = ctypes.c_bool
gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.BitBlt.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong,
]
gdi32.BitBlt.restype = ctypes.c_bool

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_screenshot_counter: int = 0
_screenshots: Dict[int, Dict[str, Any]] = {}
_last_screenshot_size: Tuple[int, int] = (1280, 834)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def get_process_name(pid: int) -> str:
    """Return the full image path for a process, or empty string on failure."""
    try:
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        size = ctypes.c_ulong(MAX_PATH)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            kernel32.CloseHandle(h)
            return buf.value
        kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def enum_windows() -> List[Dict[str, Any]]:
    """Return a list of visible top-level windows with metadata."""
    results: List[Dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if (ex_style & WS_EX_TOOLWINDOW) and not (ex_style & WS_EX_APPWINDOW):
                return True
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()
            if not title:
                return True
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc_path = get_process_name(pid.value)
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            results.append({
                "hwnd": int(hwnd),
                "title": title,
                "pid": pid.value,
                "process_name": os.path.basename(proc_path) if proc_path else "",
                "process_path": proc_path,
                "rect": {"left": rect.left, "top": rect.top,
                         "right": rect.right, "bottom": rect.bottom},
            })
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, None)
    return results


# ---------------------------------------------------------------------------
# Persistent state management (Gap 4)
# ---------------------------------------------------------------------------

STATE_FILE = os.path.join(os.path.expanduser("~"), ".win-auto-state.json")


def _load_state() -> dict:
    """Load persistent state from disk."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    """Save persistent state to disk."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _state_get(key: str | None = None) -> dict:
    """Get state value(s). If key is None, return all state."""
    state = _load_state()
    if key:
        if key in state:
            return {key: state[key]}
        return {"error": f"Key '{key}' not found"}
    return {"state": state}


def _state_set(key: str, value: Any) -> dict:
    """Set a state key/value pair."""
    state = _load_state()
    # Try to parse JSON values
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
    state[key] = value
    _save_state(state)
    return {"ok": True, "state": state}


def _state_target(hwnd: int) -> dict:
    """Set the current target window hwnd in state."""
    state = _load_state()
    state["target_hwnd"] = hwnd
    _save_state(state)
    return {"ok": True, "target_hwnd": hwnd}


def _resolve_target(hwnd: int | None) -> int:
    """Resolve hwnd, falling back to state target_hwnd if None."""
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
    """Get screenshot dimensions for coordinate scaling."""
    if screenshot_id is not None and screenshot_id in _screenshots:
        meta = _screenshots[screenshot_id]
        return {"width": meta["width"], "height": meta["height"]}
    return {"width": _last_screenshot_size[0], "height": _last_screenshot_size[1]}


def list_apps() -> List[Dict[str, Any]]:
    """Group windows by process and return structured data."""
    if _helper_available():
        result = _helper_get("/list_apps")
        if not isinstance(result, dict) or "error" not in result:
            return result
        # Helper doesn't support /list_apps (old version), execute locally

    # Fallback: group locally
    windows = enum_windows()
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
                "app_name": proc_name,
                "app_path": proc_path,
                "is_running": True,
                "windows": [],
            }
        apps_map[key]["windows"].append({
            "hwnd": w["hwnd"],
            "title": w["title"],
            "pid": pid,
            "rect": w["rect"],
        })
    return list(apps_map.values())


def _get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Return (left, top, right, bottom) for a window handle, or None using DWM visible bounds."""
    rect = ctypes.wintypes.RECT()
    try:
        dwmapi = ctypes.windll.dwmapi
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect)
        )
        if hr == 0:
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass
    
    # Fallback to standard GetWindowRect
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return None


def _get_dpi_scale(hwnd: int) -> float:
    """Return DPI scale factor relative to 96 DPI (1.0 = no scaling)."""
    try:
        dpi = user32.GetDpiForWindow(hwnd)
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _scale_coords(
    hwnd: int,
    x: int,
    y: int,
    screenshot_id: Optional[int] = None,
) -> Tuple[int, int, str]:
    """
    Convert screenshot-pixel coordinates to screen-pixel coordinates.

    PrintWindow captures at logical (GetWindowRect) size, so the mapping is:
    screenshot -> logical -> physical screen.

    Returns (screen_x, screen_y, debug_info).
    """
    global _last_screenshot_size

    # Physical bounds (DWM) - used for the final screen position
    rect = _get_window_rect(hwnd)
    if rect is None:
        raise RuntimeError(f"Cannot get window rect for hwnd {hwnd}")

    # Logical bounds (GetWindowRect) - PrintWindow captures at this size
    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    # Determine screenshot dimensions
    ss_w, ss_h = None, None
    if screenshot_id is not None and screenshot_id in _screenshots:
        meta = _screenshots[screenshot_id]
        ss_w = meta["width"]
        ss_h = meta["height"]

    if not ss_w:
        ss_w = 1280 if log_w > 1280 else log_w
    if not ss_h:
        ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

    # DPI scale for coordinate conversion
    scale = _get_dpi_scale(hwnd)

    # Map: screenshot -> logical -> physical screen
    # PrintWindow captures at logical size, so ratio uses logical dims
    # Then add DWM offset to get physical screen position
    real_x = x * log_w / ss_w
    real_y = y * log_h / ss_h
    # DWM rect gives physical screen position; offset is dwm_left - log_left
    phys_x = int(real_x + rect.left)
    phys_y = int(real_y + rect.top)

    return phys_x, phys_y, (
        f"screenshot({x},{y}) -> screen({phys_x},{phys_y}) "
        f"[log {log_w}x{log_h}, ss {ss_w}x{ss_h}, dpi_scale={scale:.2f}]"
    )


# ---------------------------------------------------------------------------
# Window activation (item 2 — AttachThreadInput trick)
# ---------------------------------------------------------------------------

def activate_window(hwnd: int) -> bool:
    """Force-activate a window. Uses helper server if available."""
    if _helper_available():
        result = _helper_post("/activate", {"hwnd": hwnd})
        if "error" not in result:
            return result.get("ok", False)

    # Fallback to direct implementation
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
# Item 9: Window handle rehydration — find windows belonging to a PID
# ---------------------------------------------------------------------------

def get_windows_for_pid(pid: int) -> List[int]:
    """Return a list of visible window HWNDs belonging to *pid*."""
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
    """
    Validate (and rehydrate) a window handle.
    If the HWND is stale, find another window from the same process.
    Returns JSON with the resolved HWND and metadata.
    """
    if user32.IsWindow(hwnd):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return json.dumps({
            "hwnd": hwnd,
            "title": buf.value.strip(),
            "pid": pid.value,
            "status": "valid",
        }, ensure_ascii=False)

    # Stale handle — try to recover by PID
    # We cannot get the PID from a dead HWND, so scan all windows
    # and find one whose PID matches any we've seen before.
    # Fallback: return an error with guidance.
    return json.dumps({
        "hwnd": hwnd,
        "status": "stale",
        "message": (
            f"HWND {hwnd} is no longer valid. "
            "Call list_windows to get current window handles."
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Expanded keysym -> Windows scancode map (item 11)
# ---------------------------------------------------------------------------

_KEYS: Dict[str, int] = {
    # Letters (a-z)
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12,
    "f": 0x21, "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24,
    "k": 0x25, "l": 0x26, "m": 0x32, "n": 0x31, "o": 0x18,
    "p": 0x19, "q": 0x10, "r": 0x13, "s": 0x1F, "t": 0x14,
    "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D, "y": 0x15, "z": 0x2C,
    # Digits (top row)
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    # Numpad (KP_0 .. KP_9)
    "KP_0": 0x52, "KP_1": 0x4F, "KP_2": 0x50, "KP_3": 0x51,
    "KP_4": 0x4B, "KP_5": 0x4C, "KP_6": 0x4D, "KP_7": 0x47,
    "KP_8": 0x48, "KP_9": 0x49,
    # F-keys (F1-F12)
    "F1": 0x3B, "F2": 0x3C, "F3": 0x3D, "F4": 0x3E,
    "F5": 0x3F, "F6": 0x40, "F7": 0x41, "F8": 0x42,
    "F9": 0x43, "F10": 0x44, "F11": 0x57, "F12": 0x58,
    # Navigation / editing
    "Insert": 0x52, "Delete": 0x53, "Home": 0x47, "End": 0x4F,
    "Page_Up": 0x49, "Page_Down": 0x51,
    "Up": 0x48, "Down": 0x50, "Left": 0x4B, "Right": 0x4D,
    # Control keys
    "Return": 0x1C, "Escape": 0x01, "BackSpace": 0x0E, "Tab": 0x0F,
    "space": 0x39,
    # Modifier keys (scan codes)
    "Control_L": 0x1D, "Control_R": 0xE01D,
    "Shift_L": 0x2A, "Shift_R": 0x36,
    "Alt_L": 0x38, "Alt_R": 0xE038,
    "Menu": 0xE05D,
    # Lock keys
    "CapsLock": 0x3A, "NumLock": 0x45, "ScrollLock": 0x46,
    "PrintScreen": 0xE037, "Pause": 0xE11D45,
    # Misc
    "space": 0x39,
    "minus": 0x0C, "equal": 0x0D, "comma": 0x33, "period": 0x34,
    "bracketleft": 0x1A, "bracketright": 0x1B, "backslash": 0x2B,
    "semicolon": 0x27, "apostrophe": 0x28, "grave": 0x29,
}


def _keysym_to_scancode(keysym: str) -> int:
    """Map a keysym name (or single character) to a Windows scancode."""
    if keysym in _KEYS:
        return _KEYS[keysym]
    # Single uppercase letter -> lowercase scancode
    if len(keysym) == 1 and keysym.isalpha():
        return _KEYS[keysym.lower()]
    raise ValueError(f"Unknown key: {keysym}")


# ---------------------------------------------------------------------------
# Keyboard input via SendInput (item 4 — replaces PyAutoGUI for key/type)
# ---------------------------------------------------------------------------

def _send_key_down(scancode: int) -> None:
    """Send a key-down event using the hardware scancode."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._input.ki.wVk = 0
    inp._input.ki.wScan = scancode
    inp._input.ki.dwFlags = KEYEVENTF_SCANCODE
    inp._input.ki.time = 0
    inp._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def _send_key_up(scancode: int) -> None:
    """Send a key-up event using the hardware scancode."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._input.ki.wVk = 0
    inp._input.ki.wScan = scancode
    inp._input.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    inp._input.ki.time = 0
    inp._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def _send_char(ch: str) -> None:
    """Send a single Unicode character via SendInput."""
    code = ord(ch)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._input.ki.wVk = 0
    inp._input.ki.wScan = code
    inp._input.ki.dwFlags = KEYEVENTF_UNICODE
    inp._input.ki.time = 0
    inp._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))
    time.sleep(0.02)
    inp._input.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def _send_ctrl_v() -> None:
    """Send Ctrl+V via SendInput."""
    vk_control = 0x1D  # Left Control scancode
    vk_v = _KEYS["v"]
    _send_key_down(vk_control)
    time.sleep(0.02)
    _send_key_down(vk_v)
    time.sleep(0.02)
    _send_key_up(vk_v)
    time.sleep(0.02)
    _send_key_up(vk_control)


# ---------------------------------------------------------------------------
# Clipboard save / restore (item 15)
# ---------------------------------------------------------------------------

def _clipboard_save() -> Optional[bytes]:
    """Read current clipboard CF_UNICODETEXT; return raw bytes or None."""
    if not user32.OpenClipboard(0):
        return None
    try:
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return None
        p_data = kernel32.GlobalLock(h_data)
        if not p_data:
            return None
        # Read the wide string until the null terminator
        raw = ctypes.string_at(p_data, 0)
        # string_at with size=0 reads until null — decode to get bytes
        text = ctypes.wstring_at(p_data)
        kernel32.GlobalUnlock(h_data)
        return text.encode("utf-16-le") + b"\x00\x00"
    except Exception:
        return None
    finally:
        user32.CloseClipboard()


def _clipboard_restore(saved: Optional[bytes]) -> None:
    """Restore a previously saved CF_UNICODETEXT to the clipboard."""
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
# Screenshot (items 1, 3, 5, 10 — scaling, IDs, BitBlt fallback, metadata)
# ---------------------------------------------------------------------------

def screenshot(
    hwnd: int,
    output_path: str,
    max_width: int = 1280,
) -> Dict[str, Any]:
    """
    Capture a window screenshot and return structured metadata.

    Capture order: PrintWindow (PW_RENDERFULLCONTENT) -> PrintWindow (0) -> BitBlt.
    The captured bitmap is down-scaled to *max_width* if wider, then saved as PNG.
    """
    global _screenshot_counter, _screenshots, _last_screenshot_size

    # Physical bounds (visible bounds via DWM)
    rect = _get_window_rect(hwnd)
    if rect is None:
        return {"error": f"Cannot get window rect for hwnd {hwnd}"}

    win_left, win_top, win_right, win_bottom = rect
    win_w = win_right - win_left
    win_h = win_bottom - win_top
    if win_w <= 0 or win_h <= 0:
        return {"error": f"Invalid window dimensions: {win_w}x{win_h}"}

    # Logical bounds (DPI virtualized bounds via GetWindowRect)
    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    dpi_scale = _get_dpi_scale(hwnd)

    hdc_window = user32.GetDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    
    # Use logical size for PrintWindow to prevent black/empty borders
    hbitmap = gdi32.CreateCompatibleBitmap(hdc_window, log_w, log_h)
    old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)

    # --- Capture method 1: PrintWindow with full content ---
    result = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
    if not result:
        # --- Capture method 2: PrintWindow default ---
        result = user32.PrintWindow(hwnd, hdc_mem, 0)

    if not result:
        # --- Capture method 3: BitBlt from screen DC (physical size) ---
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
        # PrintWindow succeeded (logical size)
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

    # Convert to RGB and optionally down-scale
    img = img.convert("RGB")
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        img = img.resize((max_width, new_height), PILImage.LANCZOS)

    img.save(output_path, "PNG")

    # Update global tracking state
    _screenshot_counter += 1
    ss_id = _screenshot_counter
    _last_screenshot_size = (img.width, img.height)

    meta = {
        "id": ss_id,
        "path": output_path,
        "width": img.width,
        "height": img.height,
        "dpi_scale": dpi_scale,
        "window_hwnd": hwnd,
    }
    _screenshots[ss_id] = meta
    return meta


# ---------------------------------------------------------------------------
# Click (items 1, 3 — scaling, screenshot_id)
# ---------------------------------------------------------------------------

def click(
    hwnd: int | None,
    x: int,
    y: int,
    button: str = "left",
    screenshot_id: Optional[int] = None,
) -> str:
    """Click at screenshot-pixel coordinates, scaled to real window position.
    Uses helper server for cross-process input (works with NW.js/CEF apps)."""
    hwnd = _resolve_target(hwnd)

    # Try helper server first
    if _helper_available():
        ss_info = _get_screenshot_size(screenshot_id)
        result = _helper_post("/click", {
            "hwnd": hwnd, "x": x, "y": y,
            "button": button, "clicks": 1,
            "activate": True,
            "screenshot_width": ss_info["width"],
            "screenshot_height": ss_info["height"],
        })
        if "error" not in result:
            return f"Clicked ({button}): screen({result.get('screen_x',0)},{result.get('screen_y',0)})"

    # Fallback to direct implementation
    activate_window(hwnd)
    time.sleep(0.1)
    screen_x, screen_y, debug = _scale_coords(hwnd, x, y, screenshot_id)
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)

    if button == "right":
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, None)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, None)
    else:
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)

    return f"Clicked ({button}): {debug}"


# ---------------------------------------------------------------------------
# Type text (items 4, 15 — SendInput, clipboard save/restore)
# ---------------------------------------------------------------------------

def type_text(hwnd: int | None, text: str) -> str:
    """Paste *text* into the focused control via clipboard + Ctrl+V.
    Uses helper server for cross-process input (works with NW.js/CEF apps)."""
    hwnd = _resolve_target(hwnd)
    # Try helper server first
    if _helper_available():
        result = _helper_post("/type_text", {"hwnd": hwnd, "text": text, "activate": True})
        if "error" not in result:
            return f"Pasted {len(text)} characters"

    # Fallback to direct implementation
    activate_window(hwnd)
    time.sleep(0.1)

    saved_clip = _clipboard_save()
    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(0):
        return "Error: Could not open clipboard"
    try:
        user32.EmptyClipboard()
        text_bytes = text.encode("utf-16-le") + b"\x00\x00"
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
        p_mem = kernel32.GlobalLock(h_mem)
        ctypes.memmove(p_mem, text_bytes, len(text_bytes))
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
    finally:
        user32.CloseClipboard()

    time.sleep(0.05)
    _send_ctrl_v()
    time.sleep(0.05)
    _clipboard_restore(saved_clip)

    return f"Pasted {len(text)} characters"


# ---------------------------------------------------------------------------
# Press key (item 4 — SendInput with scancodes)
# ---------------------------------------------------------------------------

def press_key(hwnd: int | None, keys: str) -> str:
    """
    Press one or more keys specified in + separated notation.
    Uses helper server for cross-process input (works with NW.js/CEF apps).
    """
    hwnd = _resolve_target(hwnd)
    # Try helper server first (works across processes, including CEF apps)
    if _helper_available():
        result = _helper_post("/press_key", {"hwnd": hwnd, "keys": keys, "activate": True})
        if "error" not in result:
            return f"Pressed: {keys}"

    # Fallback to direct SendInput
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
# Scroll (items 1, 3, 6 — scaling, screenshot_id, cursor first)
# ---------------------------------------------------------------------------

def scroll(
    hwnd: int | None,
    x: int,
    y: int,
    scroll_y: int,
    screenshot_id: Optional[int] = None,
) -> str:
    """Scroll at screenshot-pixel coordinates. Negative scroll_y = scroll up.
    Uses helper server for cross-process input (works with NW.js/CEF apps)."""
    hwnd = _resolve_target(hwnd)

    # Try helper server first
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

    # Fallback to direct implementation
    activate_window(hwnd)
    time.sleep(0.1)
    screen_x, screen_y, debug = _scale_coords(hwnd, x, y, screenshot_id)
    user32.SetCursorPos(screen_x, screen_y)
    time.sleep(0.05)
    wheel_delta = -scroll_y * WHEEL_DELTA
    user32.mouse_event(0x0800, 0, 0, wheel_delta, None)

    return f"Scrolled: dy={scroll_y} at {debug}"


# ---------------------------------------------------------------------------
# Drag (items 1, 3 — scaling, screenshot_id)
# ---------------------------------------------------------------------------

def drag(
    hwnd: int,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.5,
    screenshot_id: Optional[int] = None,
) -> str:
    """Drag from one set of screenshot-pixel coordinates to another."""
    activate_window(hwnd)
    time.sleep(0.1)

    sx, sy, _ = _scale_coords(hwnd, start_x, start_y, screenshot_id)
    ex, ey, _ = _scale_coords(hwnd, end_x, end_y, screenshot_id)

    user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.05)

    # Interpolate drag path over *duration* seconds
    steps = max(int(duration / 0.02), 1)
    for i in range(1, steps + 1):
        t = i / steps
        ix = int(sx + (ex - sx) * t)
        iy = int(sy + (ey - sy) * t)
        user32.SetCursorPos(ix, iy)
        time.sleep(duration / steps)

    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    return (
        f"Dragged screenshot({start_x},{start_y})->({end_x},{end_y}) "
        f"screen({sx},{sy})->({ex},{ey})"
    )


# ---------------------------------------------------------------------------
# Accessibility tree (items 7, 12 — staleness check, focused/selected)
# ---------------------------------------------------------------------------

def _validate_element(elem) -> bool:
    """Return True if the UI Automation element is still live (not stale)."""
    try:
        _ = elem.CurrentBoundingRectangle
        return True
    except Exception:
        return False


def build_accessibility_tree(
    hwnd: int,
    max_depth: int = 10,
    max_elements: int = 500,
) -> Dict[str, Any]:
    """
    Build an accessibility tree rooted at *hwnd*.

    Returns a dict with:
      - tree:     str  (human-readable indented tree)
      - elements: list of dicts with element metadata
      - focused:  dict or None with focused-element info
    """
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
                    (10002, "Value"),
                    (10000, "Invoke"),
                    (10001, "Toggle"),
                    (10005, "Selection"),
                    (10010, "Scroll"),
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
                lines.append(
                    f"{indent}[{idx}] {name_display} ({control_type})"
                    f"{pattern_str}{value_str}"
                )

                element_map.append({
                    "index": idx,
                    "name": name,
                    "control_type": control_type,
                    "patterns": patterns,
                    "rect": {
                        "left": rect.left if rect else 0,
                        "top": rect.top if rect else 0,
                        "right": rect.right if rect else 0,
                        "bottom": rect.bottom if rect else 0,
                    },
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

        # --- Item 12: Focused element & selected text ---
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
                focused_info = {
                    "name": fname,
                    "control_type": ftype,
                    "selected_text": selected_text,
                }
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
# Safety confirmation checking (Gap 7)
# ---------------------------------------------------------------------------

_DANGEROUS_ACTIONS = {
    "delete": {"category": "Delete data", "description": "This action deletes files, messages, or data"},
    "remove": {"category": "Delete data", "description": "This action deletes files, messages, or data"},
    "uninstall": {"category": "Delete data", "description": "This action uninstalls software"},
    "install": {"category": "Install software", "description": "This action installs new software"},
    "run_setup": {"category": "Install software", "description": "This action runs an installer"},
    "pay": {"category": "Financial", "description": "This action involves monetary transactions"},
    "purchase": {"category": "Financial", "description": "This action involves monetary transactions"},
    "subscribe": {"category": "Financial", "description": "This action creates a subscription"},
    "transfer": {"category": "Financial", "description": "This action transfers funds"},
    "create_account": {"category": "Account creation", "description": "This action creates a new account"},
    "sign_up": {"category": "Account creation", "description": "This action signs up for a new account"},
    "send_message": {"category": "Send messages", "description": "This action sends a message to others"},
    "post_comment": {"category": "Send messages", "description": "This action posts a public comment"},
    "reply": {"category": "Send messages", "description": "This action sends a reply"},
    "change_password": {"category": "System settings", "description": "This action changes security settings"},
    "modify_security": {"category": "System settings", "description": "This action changes security settings"},
    "update_permissions": {"category": "System settings", "description": "This action changes permissions"},
}


def check_safety(action: str) -> dict:
    """Check if an action requires user confirmation before proceeding."""
    action_lower = action.lower().replace(" ", "_").replace("-", "_")
    # Check direct match
    if action_lower in _DANGEROUS_ACTIONS:
        info = _DANGEROUS_ACTIONS[action_lower]
        return {
            "needs_confirmation": True,
            "category": info["category"],
            "description": info["description"],
            "action": action,
        }
    # Check partial matches
    for keyword, info in _DANGEROUS_ACTIONS.items():
        if keyword in action_lower:
            return {
                "needs_confirmation": True,
                "category": info["category"],
                "description": info["description"],
                "action": action,
            }
    return {"needs_confirmation": False, "action": action}


def _batch_execute_local(command_name: str, args: dict) -> dict:
    """Execute a single batch command locally."""
    try:
        if command_name == "activate":
            hwnd = args.get("hwnd")
            if not hwnd:
                return {"error": "hwnd required"}
            return {"ok": activate_window(hwnd)}
        elif command_name == "click":
            hwnd = args.get("hwnd")
            x = args.get("x", 0)
            y = args.get("y", 0)
            button = args.get("button", "left")
            screenshot_id = args.get("screenshot_id")
            result = click(hwnd, x, y, button, screenshot_id)
            return {"ok": True, "message": result}
        elif command_name == "type":
            hwnd = args.get("hwnd")
            text = args.get("text", "")
            result = type_text(hwnd, text)
            return {"ok": True, "message": result}
        elif command_name == "key":
            hwnd = args.get("hwnd")
            keys = args.get("keys", "")
            result = press_key(hwnd, keys)
            return {"ok": True, "message": result}
        elif command_name == "scroll":
            hwnd = args.get("hwnd")
            x = args.get("x", 0)
            y = args.get("y", 0)
            dy = args.get("dy", 0)
            screenshot_id = args.get("screenshot_id")
            result = scroll(hwnd, x, y, dy, screenshot_id)
            return {"ok": True, "message": result}
        elif command_name == "screenshot":
            hwnd = args.get("hwnd")
            output = args.get("output", os.path.join(os.path.dirname(__file__), "screenshot.png"))
            max_w = args.get("max_width", 1280)
            result = screenshot(hwnd, output, max_w)
            return result
        else:
            return {"error": f"Unknown local command: {command_name}"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# CLI entry point (items 9, 10, 16 — get_window cmd, JSON, error msgs)
# ---------------------------------------------------------------------------

def main() -> None:
    # Fix encoding for Windows console
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Auto-start helper server for input commands (click/type/key/scroll/drag)
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
        print("  screenshot <hwnd> [output.png]              Capture window screenshot (returns JSON with id)")
        print("  screenshot_b64 <hwnd>                       Capture screenshot as base64 PNG")
        print("  accessibility <hwnd>                        Get accessibility tree + focused element")
        print("  click <hwnd> <x> <y> [button] [screenshot_id] Click at coordinates")
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

    # ------------------------------------------------------------------
    if cmd == "list_windows":
        windows = enum_windows()
        for w in windows:
            print(json.dumps(w, ensure_ascii=False))

    # ------------------------------------------------------------------
    elif cmd == "get_window":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        print(get_window(hwnd))

    # ------------------------------------------------------------------
    elif cmd == "screenshot":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        output = (
            sys.argv[3]
            if len(sys.argv) > 3
            else os.path.join(os.path.dirname(__file__), "screenshot.png")
        )
        result = screenshot(hwnd, output)
        print(json.dumps(result, ensure_ascii=False))

    # ------------------------------------------------------------------
    elif cmd == "accessibility":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        result = build_accessibility_tree(hwnd)
        print(json.dumps(result, ensure_ascii=False))

    # ------------------------------------------------------------------
    elif cmd == "click":
        if len(sys.argv) < 5:
            print("Error: hwnd, x, y required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x, y = int(sys.argv[3]), int(sys.argv[4])
        button = sys.argv[5] if len(sys.argv) > 5 else "left"
        screenshot_id = int(sys.argv[6]) if len(sys.argv) > 6 else None
        print(click(hwnd, x, y, button, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd == "type":
        if len(sys.argv) < 4:
            print("Error: hwnd and text required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        text = sys.argv[3]
        print(type_text(hwnd, text))

    # ------------------------------------------------------------------
    elif cmd == "key":
        if len(sys.argv) < 4:
            print("Error: hwnd and keys required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        keys = sys.argv[3]
        print(press_key(hwnd, keys))

    # ------------------------------------------------------------------
    elif cmd == "scroll":
        if len(sys.argv) < 6:
            print("Error: hwnd, x, y, dy required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x, y, dy = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
        screenshot_id = int(sys.argv[6]) if len(sys.argv) > 6 else None
        print(scroll(hwnd, x, y, dy, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd == "drag":
        if len(sys.argv) < 7:
            print("Error: hwnd, x1, y1, x2, y2 required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x1, y1 = int(sys.argv[3]), int(sys.argv[4])
        x2, y2 = int(sys.argv[5]), int(sys.argv[6])
        screenshot_id = int(sys.argv[7]) if len(sys.argv) > 7 else None
        print(drag(hwnd, x1, y1, x2, y2, 0.5, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd == "activate":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        if activate_window(hwnd):
            print(f"Activated window {hwnd}")
        else:
            print(f"Failed to activate window {hwnd}")

    # ------------------------------------------------------------------
    elif cmd == "list_apps":
        result = list_apps()
        if isinstance(result, dict) and "error" in result:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "screenshot_b64":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        max_w = int(sys.argv[3]) if len(sys.argv) > 3 else 1280
        if _helper_available():
            result = _helper_get(f"/screenshot_b64?hwnd={hwnd}&max_width={max_w}")
        else:
            # Fallback: capture locally and convert
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            result = screenshot(hwnd, tmp_path, max_w)
            if "error" not in result:
                with open(tmp_path, "rb") as f:
                    png_data = f.read()
                import base64 as _b64
                result = {
                    "base64": _b64.b64encode(png_data).decode("ascii"),
                    "width": result["width"],
                    "height": result["height"],
                    "dpi_scale": result.get("dpi_scale", 1.0),
                }
                os.unlink(tmp_path)
        print(json.dumps(result, ensure_ascii=False))

    # ------------------------------------------------------------------
    elif cmd == "state":
        if len(sys.argv) < 3:
            print("Error: state subcommand required (get/set/target)")
            sys.exit(1)
        subcmd = sys.argv[2]
        if subcmd == "get":
            key = sys.argv[3] if len(sys.argv) > 3 else None
            result = _state_get(key)
            print(json.dumps(result, ensure_ascii=False))
        elif subcmd == "set":
            if len(sys.argv) < 5:
                print("Error: state set requires <key> <value>")
                sys.exit(1)
            key = sys.argv[3]
            value = sys.argv[4]
            result = _state_set(key, value)
            print(json.dumps(result, ensure_ascii=False))
        elif subcmd == "target":
            if len(sys.argv) < 4:
                print("Error: state target requires <hwnd>")
                sys.exit(1)
            target_hwnd = int(sys.argv[3])
            result = _state_target(target_hwnd)
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Error: Unknown state subcommand '{subcmd}'")
            sys.exit(1)

    # ------------------------------------------------------------------
    elif cmd == "batch":
        if len(sys.argv) < 3:
            print("Error: batch requires JSON command list")
            sys.exit(1)
        try:
            commands = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON: {e}")
            sys.exit(1)
        # Try helper server first, fallback to local execution
        if _helper_available():
            result = _helper_post("/batch", {"commands": commands})
            if "error" not in result:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                # Helper doesn't support /batch (old version), execute locally
                results = []
                for cmd_item in commands:
                    command_name = cmd_item.get("command", "")
                    args = cmd_item.get("args", {})
                    r = _batch_execute_local(command_name, args)
                    results.append({"command": command_name, "result": r})
                print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
        else:
            # Fallback: execute locally
            results = []
            for cmd_item in commands:
                command_name = cmd_item.get("command", "")
                args = cmd_item.get("args", {})
                r = _batch_execute_local(command_name, args)
                results.append({"command": command_name, "result": r})
            print(json.dumps({"results": results}, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "confirm":
        if len(sys.argv) < 3:
            print("Error: confirm requires <action>")
            sys.exit(1)
        action = sys.argv[2]
        result = check_safety(action)
        print(json.dumps(result, ensure_ascii=False))

    # ------------------------------------------------------------------
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
