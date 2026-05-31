"""
Shared Windows API constants, structs, utilities for win-automation.
Imported by server.py, tools.py, and helper.py.
"""

import ctypes
import ctypes.wintypes
import json
import os
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# DPI awareness — must run before any GUI operations
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Windows API constants
# ---------------------------------------------------------------------------
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_RESTORE = 9
SW_SHOW = 5
SW_SHOWNORMAL = 1
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 260  # Correct Windows constant

PW_RENDERFULLCONTENT = 0x00000002
CF_UNICODETEXT = 13
CF_TEXT = 1
GMEM_MOVEABLE = 0x0002
SRCCOPY = 0x00CC0020
WHEEL_DELTA = 120

# SendInput constants
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
EXTENDEDKEY = 0x0001

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

# ---------------------------------------------------------------------------
# Windows API handles
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
gdi32 = ctypes.windll.gdi32

# ---------------------------------------------------------------------------
# ctypes structs
# ---------------------------------------------------------------------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]

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

# ---------------------------------------------------------------------------
# Function prototypes — union of all three files
# ---------------------------------------------------------------------------
# user32
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.IsWindow.argtypes = [ctypes.c_void_p]
user32.IsWindow.restype = ctypes.c_bool
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
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
user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetClientRect.restype = ctypes.c_bool
user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.POINT)]
user32.ClientToScreen.restype = ctypes.c_bool
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
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
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.c_bool
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = ctypes.c_bool
user32.GetCursorPos.argtypes = [ctypes.POINTER(ctypes.wintypes.POINT)]
user32.GetCursorPos.restype = ctypes.c_bool
user32.mouse_event.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
user32.mouse_event.restype = None
user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.restype = ctypes.c_uint
user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short

# kernel32
kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_bool

# gdi32
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
gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint32]
gdi32.BitBlt.restype = ctypes.c_bool

# dwmapi
try:
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
except Exception:
    dwmapi = None

# ---------------------------------------------------------------------------
# State management — atomic read/write
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
    """Save persistent state to disk atomically."""
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass

def _resolve_target(hwnd: Optional[int]) -> int:
    """Resolve hwnd, falling back to state target_hwnd if None. Persists target."""
    if hwnd is not None:
        state = _load_state()
        state["target_hwnd"] = hwnd
        _save_state(state)
        return hwnd
    state = _load_state()
    target = state.get("target_hwnd")
    if target and user32.IsWindow(target):
        return target
    raise ValueError(
        "No hwnd provided and no valid target_hwnd in state. "
        "Please find the window using list_windows first, then pass its hwnd."
    )

# ---------------------------------------------------------------------------
# DPI / Window rect utilities
# ---------------------------------------------------------------------------
def _get_dpi_scale(hwnd: int) -> float:
    """Return DPI scale factor relative to 96 DPI (1.0 = no scaling)."""
    try:
        if hasattr(user32, "GetDpiForWindow"):
            dpi = user32.GetDpiForWindow(hwnd)
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass

    # Fallback: Get DC and query LOGPIXELSX
    try:
        hdc = user32.GetDC(hwnd)
        if hdc:
            gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
            gdi32.GetDeviceCaps.restype = ctypes.c_int
            dpi = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX = 88
            user32.ReleaseDC(hwnd, hdc)
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass

    return 1.0


def _get_window_rect(hwnd: int) -> ctypes.wintypes.RECT:
    """Get the visible window rect, excluding invisible shadow borders via DWM."""
    rect = ctypes.wintypes.RECT()
    try:
        if dwmapi:
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            hr = dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect), ctypes.sizeof(rect),
            )
            if hr == 0:
                return rect
    except Exception:
        pass
    # Fallback to standard GetWindowRect
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def _get_process_name(pid: int) -> str:
    """Return full image path for a process, or empty string on failure."""
    try:
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        size = ctypes.c_ulong(MAX_PATH)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            result = buf.value
            kernel32.CloseHandle(h)
            return result
        kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""

# ---------------------------------------------------------------------------
# Window enumeration
# ---------------------------------------------------------------------------
def _enum_windows() -> list[dict[str, Any]]:
    """Enumerate all visible top-level windows with metadata."""
    results: list[dict[str, Any]] = []

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
            proc_path = _get_process_name(pid.value)
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
# Clipboard
# ---------------------------------------------------------------------------
def _set_clipboard_text(text: str) -> None:
    """Set clipboard text using Windows API with proper error handling."""
    try:
        user32.OpenClipboard(0)
        user32.EmptyClipboard()
        text_bytes = text.encode("utf-16-le") + b"\x00\x00"
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE | 0x0040, len(text_bytes))
        if not h_mem:
            user32.CloseClipboard()
            return
        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            user32.CloseClipboard()
            return
        ctypes.memmove(p_mem, text_bytes, len(text_bytes))
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        user32.CloseClipboard()
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass


def _clipboard_save() -> Optional[bytes]:
    """Save current clipboard CF_UNICODETEXT; return raw bytes or None."""
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
    """Restore a previously saved CF_UNICODETEXT to the clipboard."""
    if saved is None:
        return
    if not user32.OpenClipboard(0):
        return
    try:
        user32.EmptyClipboard()
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(saved))
        if not h_mem:
            return
        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            return
        ctypes.memmove(p_mem, saved, len(saved))
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
    except Exception:
        pass
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Window activation
# ---------------------------------------------------------------------------
def _activate_window(hwnd: int) -> bool:
    """Bring window to foreground."""
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)
        return user32.SetForegroundWindow(hwnd)
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Safety checking
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

def _check_safety(action: str) -> dict:
    """Check if an action requires user confirmation before proceeding."""
    action_lower = action.lower().replace(" ", "_").replace("-", "_")
    if action_lower in _DANGEROUS_ACTIONS:
        info = _DANGEROUS_ACTIONS[action_lower]
        return {
            "needs_confirmation": True,
            "category": info["category"],
            "description": info["description"],
            "action": action,
        }
    for keyword, info in _DANGEROUS_ACTIONS.items():
        if keyword in action_lower:
            return {
                "needs_confirmation": True,
                "category": info["category"],
                "description": info["description"],
                "action": action,
            }
    return {"needs_confirmation": False, "action": action}

# ---------------------------------------------------------------------------
# Key map: keysym -> Windows scancode (merged from tools.py + helper.py)
# ---------------------------------------------------------------------------
# Numpad digit keys use E0-prefixed scancodes (NumLock ON, default state).
# When NumLock is OFF, they produce navigation keys instead.
_NUMPAD_DIGIT_KEYS = {"KP_0", "KP_1", "KP_2", "KP_3", "KP_4", "KP_5", "KP_6", "KP_7", "KP_8", "KP_9", "KP_Decimal"}
# Mapping from numpad key to its NumLock-OFF scancode (navigation key)
_NUMPAD_NUMLOCK_OFF = {
    "KP_0": 0x52, "KP_1": 0x4F, "KP_2": 0x50, "KP_3": 0x51, "KP_4": 0x4B,
    "KP_5": 0x4C, "KP_6": 0x4D, "KP_7": 0x47, "KP_8": 0x48, "KP_9": 0x49,
    "KP_Decimal": 0x53,
}

def _is_numlock_on() -> bool:
    """Check if NumLock is currently on."""
    try:
        VK_NUMLOCK = 0x90
        return bool(user32.GetKeyState(VK_NUMLOCK) & 0x0001)
    except Exception:
        return True  # Assume NumLock on by default

_KEYMAP: dict[str, int] = {
    "escape": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "minus": 0x0C, "equal": 0x0D, "backspace": 0x0E, "tab": 0x0F,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14,
    "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "bracketleft": 0x1A, "bracketright": 0x1B, "Return": 0x1C,
    "control_l": 0x1D, "Control_L": 0x1D,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21,
    "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    "semicolon": 0x27, "apostrophe": 0x28, "grave": 0x29,
    "shift_l": 0x2A, "Shift_L": 0x2A,
    "backslash": 0x2B,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
    "n": 0x31, "m": 0x32, "comma": 0x33, "period": 0x34, "slash": 0x35,
    "shift_r": 0x36, "Shift_R": 0x36,
    "KP_Multiply": 0x37, "KP_Divide": 0xE035, "Alt_L": 0x38, "space": 0x39,
    "Caps_Lock": 0x3A, "CapsLock": 0x3A,
    "F1": 0x3B, "F2": 0x3C, "F3": 0x3D, "F4": 0x3E,
    "F5": 0x3F, "F6": 0x40, "F7": 0x41, "F8": 0x42,
    "F9": 0x43, "F10": 0x44,
    "Num_Lock": 0x45, "NumLock": 0x45,
    "Scroll_Lock": 0x46, "ScrollLock": 0x46,
    "KP_7": 0xE047, "KP_8": 0xE048, "KP_9": 0xE049, "KP_Subtract": 0x4A,
    "KP_4": 0xE04B, "KP_5": 0xE04C, "KP_6": 0xE04D, "KP_Add": 0x4E,
    "KP_1": 0xE04F, "KP_2": 0xE050, "KP_3": 0xE051, "KP_0": 0xE052,
    "KP_Decimal": 0xE053,
    "F11": 0x57, "F12": 0x58,
    # Extended keys (0xE0 prefix)
    "Home": 0xE047, "Up": 0xE048, "Page_Up": 0xE049,
    "Left": 0xE04B, "Right": 0xE04D,
    "End": 0xE04F, "Down": 0xE050, "Page_Down": 0xE051,
    "Insert": 0xE052, "Delete": 0xE053,
    "PrintScreen": 0xE037, "Menu": 0xE05D,
    "Control_R": 0xE01D, "Alt_R": 0xE038,
    # Aliases
    "ctrl": 0x1D, "shift": 0x2A,
    "Control": 0x1D, "Shift": 0x2A, "Alt": 0x38,
    "enter": 0x1C,
    "Escape": 0x01,
    "BackSpace": 0x0E,
    # Lowercase numpad aliases (for helper.py key lookup)
    "kp_0": 0xE052, "kp_1": 0xE04F, "kp_2": 0xE050, "kp_3": 0xE051,
    "kp_4": 0xE04B, "kp_5": 0xE04C, "kp_6": 0xE04D, "kp_7": 0xE047,
    "kp_8": 0xE048, "kp_9": 0xE049,
    "kp_subtract": 0x4A, "kp_add": 0x4E, "kp_decimal": 0xE053,
    "kp_multiply": 0x37, "kp_divide": 0xE035,
    "num_lock": 0x45, "numlock": 0x45,
}
KEYMAP = _KEYMAP

def _keysym_to_scancode(keysym: str) -> int:
    """Map a keysym name (or single character) to a Windows scancode.
    Numpad digit keys respect NumLock state."""
    if keysym in _NUMPAD_DIGIT_KEYS:
        if _is_numlock_on():
            return _KEYMAP[keysym]  # E0-prefixed (digit)
        else:
            return _NUMPAD_NUMLOCK_OFF[keysym]  # Non-E0 (navigation)
    if keysym in _KEYMAP:
        return _KEYMAP[keysym]
    if len(keysym) == 1 and keysym.isalpha():
        return _KEYMAP[keysym.lower()]
    raise ValueError(f"Unknown key: {keysym}")
