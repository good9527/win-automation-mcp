"""
Windows Automation Helper Server
Runs as a persistent background process in the desktop session.
Accepts HTTP commands from tools.py and executes them via SendInput.

Usage: python helper.py [--port 18765]
"""

import ctypes
import ctypes.wintypes
import json
import os
import sys
import time
import io
import base64
import threading
import atexit
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Auto-cleanup temporary screenshot file on daemon termination
def _cleanup():
    try:
        import tempfile
        output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
        path = os.path.join(output_dir, "screenshot.png")
        if os.path.exists(path):
            os.remove(path)
        # Clean desktop one if it exists
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop", "win-automation-mcp")
        desktop_path = os.path.join(desktop_dir, "screenshot.png")
        if os.path.exists(desktop_path):
            os.remove(desktop_path)
    except Exception:
        pass

atexit.register(_cleanup)

# ---------------------------------------------------------------------------
# DPI awareness
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
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
SW_RESTORE = 9
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 265
CF_UNICODETEXT = 13
CF_TEXT = 1

# ---------------------------------------------------------------------------
# Windows API handles
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

# ---------------------------------------------------------------------------
# Structs
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
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

# ---------------------------------------------------------------------------
# API prototypes
# ---------------------------------------------------------------------------
user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = ctypes.c_bool
user32.GetCursorPos.argtypes = [ctypes.POINTER(ctypes.wintypes.POINT)]
user32.GetCursorPos.restype = ctypes.c_bool
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_bool
user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
user32.BringWindowToTop.restype = ctypes.c_bool
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
user32.AttachThreadInput.restype = ctypes.c_bool
user32.IsWindow.argtypes = [ctypes.c_void_p]
user32.IsWindow.restype = ctypes.c_bool
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.c_bool
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
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
user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
user32.PrintWindow.restype = ctypes.c_bool
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.restype = ctypes.c_uint

# DWM Frame Bounds API
try:
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
except Exception:
    pass
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int
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


# ---------------------------------------------------------------------------
# Key map: keysym -> Windows scancode
# ---------------------------------------------------------------------------
_KEYMAP = {
    "escape": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "minus": 0x0C, "equal": 0x0D, "backspace": 0x0E, "tab": 0x0F,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14,
    "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "bracketleft": 0x1A, "bracketright": 0x1B, "Return": 0x1C,
    "control_l": 0x1D, "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21,
    "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    "semicolon": 0x27, "apostrophe": 0x28, "grave": 0x29,
    "shift_l": 0x2A, "backslash": 0x2B,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
    "n": 0x31, "m": 0x32, "comma": 0x33, "period": 0x34, "slash": 0x35,
    "shift_r": 0x36, "KP_Multiply": 0x37, "Alt_L": 0x38, "space": 0x39,
    "Caps_Lock": 0x3A,
    "F1": 0x3B, "F2": 0x3C, "F3": 0x3D, "F4": 0x3E,
    "F5": 0x3F, "F6": 0x40, "F7": 0x41, "F8": 0x42,
    "F9": 0x43, "F10": 0x44,
    "Num_Lock": 0x45, "Scroll_Lock": 0x46,
    "KP_7": 0x47, "KP_8": 0x48, "KP_9": 0x49, "KP_Subtract": 0x4A,
    "KP_4": 0x4B, "KP_5": 0x4C, "KP_6": 0x4D, "KP_Add": 0x4E,
    "KP_1": 0x4F, "KP_2": 0x50, "KP_3": 0x51, "KP_0": 0x52,
    "KP_Decimal": 0x53,
    "F11": 0x57, "F12": 0x58,
    "Home": 0xE047, "Up": 0xE048, "Page_Up": 0xE049,
    "Left": 0xE04B, "Right": 0xE04D,
    "End": 0xE04F, "Down": 0xE050, "Page_Down": 0xE051,
    "Insert": 0xE052, "Delete": 0xE053,
    "Menu": 0xE05D,
}

# Aliases
_KEYMAP["ctrl"] = _KEYMAP["control_l"]
_KEYMAP["shift"] = _KEYMAP["shift_l"]
KEYMAP = _KEYMAP


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------
def _send_key(scancode: int, up: bool = False) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = scancode & 0xFF
    inp.union.ki.dwFlags = KEYEVENTF_SCANCODE
    if scancode & 0xE000:
        inp.union.ki.dwFlags |= 0x0001  # EXTENDEDKEY
    if up:
        inp.union.ki.dwFlags |= KEYEVENTF_KEYUP
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _send_char(ch: str) -> None:
    for code in ch:
        cp = ord(code)
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = 0
        inp.union.ki.wScan = cp
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        time.sleep(0.01)
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        time.sleep(0.01)


def _mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.05)

    down_map = {
        "left": MOUSEEVENTF_LEFTDOWN,
        "right": MOUSEEVENTF_RIGHTDOWN,
        "middle": MOUSEEVENTF_MIDDLEDOWN,
    }
    up_map = {
        "left": MOUSEEVENTF_LEFTUP,
        "right": MOUSEEVENTF_RIGHTUP,
        "middle": MOUSEEVENTF_MIDDLEUP,
    }

    for _ in range(clicks):
        user32.mouse_event(down_map[button], 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(up_map[button], 0, 0, 0, 0)
        time.sleep(0.05)


def _mouse_scroll(x: int, y: int, delta: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)


def _activate_window(hwnd: int) -> bool:
    try:
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        my_tid = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(my_tid, fg_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(my_tid, fg_tid, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _clipboard_save() -> bytes | None:
    """Save current clipboard text. Returns bytes or None."""
    try:
        if not user32.OpenClipboard(0):
            return None
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            user32.CloseClipboard()
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            user32.CloseClipboard()
            return None
        # Read as null-terminated wide string
        text = ctypes.c_wchar_p(p).value or ""
        kernel32.GlobalUnlock(h)
        user32.CloseClipboard()
        return text.encode("utf-16-le")
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass
        return None


def _clipboard_restore(data: bytes | None) -> None:
    """Restore clipboard from saved bytes."""
    if data is None:
        return
    try:
        if not user32.OpenClipboard(0):
            return
        user32.EmptyClipboard()
        text_bytes = data + b"\x00\x00"
        h_mem = kernel32.GlobalAlloc(0x0042, len(text_bytes))
        p_mem = kernel32.GlobalLock(h_mem)
        ctypes.memmove(p_mem, text_bytes, len(text_bytes))
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        user32.CloseClipboard()
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# DPI & process helpers
# ---------------------------------------------------------------------------
def _get_dpi_scale(hwnd: int) -> float:
    """Return DPI scale factor relative to 96 DPI (1.0 = no scaling)."""
    try:
        dpi = user32.GetDpiForWindow(hwnd)
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _get_window_rect(hwnd: int) -> ctypes.wintypes.RECT:
    """Get the visible window rect, excluding invisible shadow borders using DWM API."""
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
            return rect
    except Exception:
        pass
    
    # Fallback to standard GetWindowRect
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def _get_process_path(pid: int) -> str:
    """Return full image path for a process, or empty string on failure."""
    try:
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        pbuf = ctypes.create_unicode_buffer(MAX_PATH)
        size = ctypes.c_ulong(MAX_PATH)
        if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
            path = pbuf.value
            kernel32.CloseHandle(h)
            return path
        kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Persistent state
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


def _set_clipboard_text(text: str) -> None:
    """Set clipboard text."""
    try:
        user32.OpenClipboard(0)
        user32.EmptyClipboard()
        text_bytes = text.encode("utf-16-le") + b"\x00\x00"
        h_mem = kernel32.GlobalAlloc(0x0042, len(text_bytes))
        p_mem = kernel32.GlobalLock(h_mem)
        ctypes.memmove(p_mem, text_bytes, len(text_bytes))
        kernel32.GlobalUnlock(h_mem)
        user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        user32.CloseClipboard()
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass


def _capture_screenshot(hwnd: int, max_width: int = 1280) -> dict:
    """Capture window screenshot. Returns dict with path, width, height, dpi_scale."""
    from PIL import Image as PILImage

    # Physical bounds (visible bounds via DWM)
    rect = _get_window_rect(hwnd)
    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top
    if win_w <= 0 or win_h <= 0:
        return {"error": f"Invalid dimensions: {win_w}x{win_h}"}

    # Logical bounds (DPI virtualized bounds via GetWindowRect)
    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    dpi_scale = _get_dpi_scale(hwnd)
    img = None

    # --- Capture method 1: dxcam (fastest, GPU-accelerated) ---
    try:
        import dxcam
        camera = dxcam.create(output_color="BGR")
        if camera:
            region = (rect.left, rect.top, rect.right, rect.bottom)
            dxcam_img = camera.grab(region=region)
            camera.stop()
            if dxcam_img is not None:
                import numpy as np
                rgb = np.flip(dxcam_img[:, :, ::-1], axis=2)
                img = PILImage.fromarray(rgb)
                width = win_w
                height = win_h
    except ImportError:
        pass
    except Exception:
        pass

    # --- Capture method 2: PrintWindow ---
    if img is None:
        hdc = user32.GetDC(hwnd)
        hdc_mem = gdi32.CreateCompatibleDC(hdc)
        
        # Use logical size for PrintWindow to prevent black/empty borders
        hbitmap = gdi32.CreateCompatibleBitmap(hdc, log_w, log_h)
        old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)

        captured = user32.PrintWindow(hwnd, hdc_mem, 0x00000002)
        if not captured:
            captured = user32.PrintWindow(hwnd, hdc_mem, 0)

        if captured:
            # Successfully captured via PrintWindow (logical size)
            width = log_w
            height = log_h
        else:
            # --- Capture method 3: BitBlt from screen DC (physical size) ---
            gdi32.SelectObject(hdc_mem, old_bmp)
            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(hwnd, hdc)

            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, win_w, win_h)
            old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)
            gdi32.BitBlt(hdc_mem, 0, 0, win_w, win_h,
                         hdc_screen, rect.left, rect.top, 0x00CC0020)
            user32.ReleaseDC(0, hdc_screen)
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
        gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)

        img = PILImage.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)

        gdi32.SelectObject(hdc_mem, old_bmp)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc)

    img = img.convert("RGB")

    if max_width and width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        img = img.resize((max_width, new_height), PILImage.LANCZOS)

    # Save to file in system temp directory to prevent Desktop clutter
    import tempfile
    output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "screenshot.png")
    img.save(path, "PNG")

    return {
        "path": path,
        "width": img.width,
        "height": img.height,
        "dpi_scale": dpi_scale,
        "window_hwnd": hwnd,
    }


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
class HelperHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/health":
            self._send_json({"status": "ok"})

        elif path == "/list_windows":
            self._handle_list_windows()

        elif path == "/list_apps":
            self._handle_list_apps()

        elif path == "/get_window":
            hwnd = int(params.get("hwnd", [0])[0])
            self._handle_get_window(hwnd)

        elif path == "/screenshot":
            hwnd = int(params.get("hwnd", [0])[0])
            max_w = int(params.get("max_width", [1280])[0])
            self._handle_screenshot(hwnd, max_w)

        elif path == "/screenshot_b64":
            hwnd = int(params.get("hwnd", [0])[0])
            max_w = int(params.get("max_width", [1280])[0])
            self._handle_screenshot_b64(hwnd, max_w)

        elif path == "/get_state":
            self._handle_get_state(params)

        else:
            self._send_json({"error": f"Unknown path: {path}"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        # Auto-resolve hwnd from state when not provided
        if path in ("/click", "/type_text", "/press_key", "/scroll"):
            if "hwnd" not in data or data["hwnd"] is None:
                target = _load_state().get("target_hwnd")
                if target:
                    data["hwnd"] = target

        if path == "/click":
            self._handle_click(data)
        elif path == "/type_text":
            self._handle_type_text(data)
        elif path == "/press_key":
            self._handle_press_key(data)
        elif path == "/scroll":
            self._handle_scroll(data)
        elif path == "/activate":
            self._handle_activate(data)
        elif path == "/clipboard":
            self._handle_clipboard(data)
        elif path == "/set_clipboard":
            self._handle_set_clipboard(data)
        elif path == "/set_state":
            self._handle_set_state(data)
        elif path == "/batch":
            self._handle_batch(data)
        else:
            self._send_json({"error": f"Unknown path: {path}"}, 404)

    # ----- Handlers -----

    def _handle_list_windows(self):
        results = []

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
                proc_name = ""
                proc_path = ""
                try:
                    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
                    if h:
                        pbuf = ctypes.create_unicode_buffer(MAX_PATH)
                        size = ctypes.c_ulong(MAX_PATH)
                        if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                            proc_path = pbuf.value
                            proc_name = os.path.basename(proc_path)
                        kernel32.CloseHandle(h)
                except Exception:
                    pass
                rect = _get_window_rect(hwnd)
                results.append({
                    "hwnd": hwnd, "title": title, "pid": pid.value,
                    "process_name": proc_name,
                    "process_path": proc_path,
                    "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
                })
            except Exception:
                pass
            return True

        user32.EnumWindows(callback, None)
        self._send_json({"windows": results})

    def _handle_get_window(self, hwnd: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        rect = _get_window_rect(hwnd)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_path = _get_process_path(pid.value)
        self._send_json({
            "hwnd": hwnd, "title": buf.value,
            "pid": pid.value,
            "process_name": os.path.basename(proc_path) if proc_path else "",
            "process_path": proc_path,
            "dpi_scale": _get_dpi_scale(hwnd),
            "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
            "width": rect.right - rect.left, "height": rect.bottom - rect.top,
        })

    def _handle_screenshot(self, hwnd: int, max_width: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        result = _capture_screenshot(hwnd, max_width)
        self._send_json(result)

    def _handle_click(self, data: dict):
        hwnd = data.get("hwnd")
        x = data.get("x", 0)
        y = data.get("y", 0)
        button = data.get("button", "left")
        clicks = data.get("clicks", 1)

        if hwnd:
            # Get both physical (DWM) and logical (GetWindowRect) bounds
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            # Screenshot is captured at logical size, downscaled to max 1280px
            ss_w = data.get("screenshot_width")
            ss_h = data.get("screenshot_height")
            if not ss_w:
                ss_w = 1280 if log_w > 1280 else log_w
            if not ss_h:
                ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

            # Correct mapping: screenshot -> logical -> physical screen
            # PrintWindow captures at logical size, so ratio uses logical dims
            # Then add DWM offset to get physical screen position
            real_x = int(x * log_w / ss_w) + rect.left
            real_y = int(y * log_h / ss_h) + rect.top

            # Auto-activate
            if data.get("activate", True):
                _activate_window(hwnd)
                time.sleep(0.1)

            # In DPI-aware process, SetCursorPos / SendInput expect physical screen coordinates
            _mouse_click(real_x, real_y, button, clicks)
            self._send_json({"ok": True, "screen_x": real_x, "screen_y": real_y})
        else:
            # Absolute screen coords
            _mouse_click(x, y, button, clicks)
            self._send_json({"ok": True})

    def _handle_type_text(self, data: dict):
        hwnd = data.get("hwnd")
        text = data.get("text", "")

        if not text:
            self._send_json({"error": "No text provided"})
            return

        # Activate window if hwnd provided
        if hwnd and data.get("activate", True):
            _activate_window(hwnd)
            time.sleep(0.1)

        # Save clipboard, paste, restore
        saved = _clipboard_save()
        _set_clipboard_text(text)
        time.sleep(0.05)

        # Send Ctrl+V
        ctrl_sc = KEYMAP.get("control_l", 0x1D)
        v_sc = KEYMAP.get("v", 0x2F)
        _send_key(ctrl_sc)
        _send_key(v_sc)
        time.sleep(0.05)
        _send_key(v_sc, up=True)
        _send_key(ctrl_sc, up=True)
        time.sleep(0.1)

        # Restore clipboard
        _clipboard_restore(saved)

        self._send_json({"ok": True, "length": len(text)})

    def _handle_press_key(self, data: dict):
        hwnd = data.get("hwnd")
        keys = data.get("keys", "")

        if not keys:
            self._send_json({"error": "No keys provided"})
            return

        # Activate window if hwnd provided
        if hwnd and data.get("activate", True):
            _activate_window(hwnd)
            time.sleep(0.1)

        parts = keys.replace(" ", "").split("+")
        scancodes = []
        for part in parts:
            sc = KEYMAP.get(part.lower(), KEYMAP.get(part))
            if sc is None:
                if len(part) == 1:
                    sc = KEYMAP.get(part.lower())
                if sc is None:
                    self._send_json({"error": f"Unknown key: {part}"})
                    return
            scancodes.append(sc)

        # Press all down
        for sc in scancodes:
            _send_key(sc)
            time.sleep(0.02)

        # Release in reverse
        for sc in reversed(scancodes):
            _send_key(sc, up=True)
            time.sleep(0.02)

        self._send_json({"ok": True, "keys": keys})

    def _handle_scroll(self, data: dict):
        hwnd = data.get("hwnd")
        x = data.get("x", 0)
        y = data.get("y", 0)
        delta = data.get("delta", 120)
        clicks = data.get("clicks", 3)

        if hwnd:
            # Get both physical (DWM) and logical (GetWindowRect) bounds
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            ss_w = data.get("screenshot_width")
            ss_h = data.get("screenshot_height")
            if not ss_w:
                ss_w = 1280 if log_w > 1280 else log_w
            if not ss_h:
                ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

            # Correct mapping: screenshot -> logical -> physical screen
            real_x = int(x * log_w / ss_w) + rect.left
            real_y = int(y * log_h / ss_h) + rect.top

            if data.get("activate", True):
                _activate_window(hwnd)
                time.sleep(0.1)

            # Move cursor first using physical coordinates
            user32.SetCursorPos(real_x, real_y)
            time.sleep(0.05)

            for _ in range(abs(clicks)):
                _mouse_scroll(real_x, real_y, delta if clicks > 0 else -delta)
                time.sleep(0.05)

            self._send_json({"ok": True, "screen_x": real_x, "screen_y": real_y})
        else:
            user32.SetCursorPos(x, y)
            time.sleep(0.05)
            for _ in range(abs(clicks)):
                _mouse_scroll(x, y, delta if clicks > 0 else -delta)
                time.sleep(0.05)
            self._send_json({"ok": True})

    def _handle_activate(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        result = _activate_window(hwnd)
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        self._send_json({"ok": result, "title": buf.value})

    def _handle_clipboard(self, data: dict):
        action = data.get("action", "get")
        if action == "get":
            saved = _clipboard_save()
            if saved:
                try:
                    text = saved.decode("utf-16-le")
                except Exception:
                    text = ""
                self._send_json({"text": text})
            else:
                self._send_json({"text": ""})
        elif action == "save":
            saved = _clipboard_save()
            # Store in a file for later restore
            save_path = os.path.join(os.path.expanduser("~"), ".win-auto-clipboard")
            with open(save_path, "wb") as f:
                f.write(saved if saved else b"")
            self._send_json({"ok": True})
        elif action == "restore":
            save_path = os.path.join(os.path.expanduser("~"), ".win-auto-clipboard")
            if os.path.exists(save_path):
                with open(save_path, "rb") as f:
                    data = f.read()
                _clipboard_restore(data if data else None)
                os.remove(save_path)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "No saved clipboard"})

    def _handle_set_clipboard(self, data: dict):
        text = data.get("text", "")
        _set_clipboard_text(text)
        self._send_json({"ok": True, "length": len(text)})

    def _handle_list_apps(self):
        windows_by_pid = {}

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
                pid_val = pid.value
                rect = _get_window_rect(hwnd)
                win_info = {
                    "hwnd": hwnd, "title": title, "pid": pid_val,
                    "rect": {"left": rect.left, "top": rect.top,
                             "right": rect.right, "bottom": rect.bottom},
                }
                if pid_val not in windows_by_pid:
                    proc_path = _get_process_path(pid_val)
                    windows_by_pid[pid_val] = {
                        "app_name": os.path.basename(proc_path) if proc_path else "",
                        "app_path": proc_path,
                        "is_running": True,
                        "windows": [],
                    }
                windows_by_pid[pid_val]["windows"].append(win_info)
            except Exception:
                pass
            return True

        user32.EnumWindows(callback, None)
        results = list(windows_by_pid.values())
        self._send_json(results)

    def _handle_screenshot_b64(self, hwnd: int, max_width: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        result = _capture_screenshot(hwnd, max_width)
        if "error" in result:
            self._send_json(result)
            return
        # Read file and convert to base64
        try:
            with open(result["path"], "rb") as f:
                png_data = f.read()
            self._send_json({
                "text": "Captured window screenshot.",
                "base64": base64.b64encode(png_data).decode("ascii"),
                "width": result["width"],
                "height": result["height"],
                "dpi_scale": result.get("dpi_scale", 1.0),
            })
        except Exception as e:
            self._send_json({"error": str(e)})

    def _handle_get_state(self, params: dict):
        state = _load_state()
        key = params.get("key", [None])[0]
        if key:
            if key in state:
                self._send_json({key: state[key]})
            else:
                self._send_json({"error": f"Key '{key}' not found"})
        else:
            self._send_json({"state": state})

    def _handle_set_state(self, data: dict):
        state = _load_state()
        state.update(data)
        _save_state(state)
        self._send_json({"ok": True, "state": state})

    def _handle_batch(self, data: dict):
        commands = data.get("commands", [])
        results = []
        for cmd in commands:
            path = cmd.get("path", "")
            cmd_data = cmd.get("data", {})
            result = self._dispatch_command(path, cmd_data)
            results.append({"path": path, "result": result})
        self._send_json({"results": results})

    def _dispatch_command(self, path: str, data: dict) -> dict:
        """Dispatch a single command for batch processing."""
        dispatch = {
            "/activate": self._handle_activate,
            "/click": self._handle_click,
            "/type_text": self._handle_type_text,
            "/press_key": self._handle_press_key,
            "/scroll": self._handle_scroll,
            "/clipboard": self._handle_clipboard,
            "/set_clipboard": self._handle_set_clipboard,
        }
        handler = dispatch.get(path)
        if not handler:
            return {"error": f"Unknown command path: {path}"}

        # Capture response by temporarily overriding _send_json
        captured = {}
        original_send = self._send_json

        def capturing_send(data_arg, status=200):
            captured["response"] = data_arg

        self._send_json = capturing_send
        try:
            handler(data)
        except Exception as e:
            captured["response"] = {"error": str(e)}
        finally:
            self._send_json = original_send

        return captured.get("response", {"error": "No response"})

    def _resolve_hwnd(self, data: dict) -> int | None:
        """Resolve hwnd from data dict, falling back to stored target_hwnd."""
        hwnd = data.get("hwnd")
        if hwnd:
            return hwnd
        return _load_state().get("target_hwnd")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    port = 18765
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    server = HTTPServer(("127.0.0.1", port), HelperHandler)
    print(f"Helper server running on http://127.0.0.1:{port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
