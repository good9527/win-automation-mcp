"""
Windows Automation MCP Server
Provides tools for controlling Windows applications via MCP protocol.
"""

import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import sys
import time
import threading
from typing import Any, Optional

# Set DPI awareness before any GUI operations
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import pyautogui
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.utilities.types import Image

# Disable pyautogui failsafe
pyautogui.FAILSAFE = False

# Create server
server = FastMCP(
    name="win-automation",
    instructions="Windows desktop automation tools for controlling applications, capturing screenshots, and simulating user input."
)

# Global element index storage
_element_indices: dict[int, dict[int, Any]] = {}
_element_index_lock = threading.Lock()

# State file path for persistent synchronization with tools.py
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

def _resolve_target(hwnd: Optional[int]) -> int:
    """Resolve hwnd, falling back to state target_hwnd if None."""
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

def _get_dpi_scale(hwnd: int) -> float:
    """Return DPI scale factor relative to 96 DPI (1.0 = no scaling)."""
    try:
        if hasattr(user32, "GetDpiForWindow"):
            user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
            user32.GetDpiForWindow.restype = ctypes.c_uint
            dpi = user32.GetDpiForWindow(hwnd)
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass
    
    # Fallback: Get DC and query LOGPIXELSX
    try:
        hdc = user32.GetDC(hwnd)
        if hdc:
            gdi32 = ctypes.windll.gdi32
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

# Dangerous actions classification for safety checking
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

# Windows API constants
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
MAX_PATH = 265
PW_RENDERFULLCONTENT = 0x00000002

# Windows API functions
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

# Function prototypes
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_bool
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
kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool

gdi32 = ctypes.windll.gdi32
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


def _get_process_name(pid: int) -> str:
    """Get process executable path from PID."""
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


def _enum_windows() -> list[dict[str, Any]]:
    """Enumerate all visible windows."""
    results = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True

            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            # Skip tool windows unless they have app window style
            if (ex_style & WS_EX_TOOLWINDOW) and not (ex_style & WS_EX_APPWINDOW):
                return True

            # Get title
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()

            if not title:
                return True

            # Get PID
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            # Get process path
            proc_path = _get_process_name(pid.value)

            results.append({
                "hwnd": hwnd,
                "title": title,
                "pid": pid.value,
                "process_path": proc_path,
                "process_name": os.path.basename(proc_path) if proc_path else "",
            })
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, None)
    return results


def _capture_window_screenshot(hwnd: int, max_width: int = 1280, format: str = "jpeg") -> bytes:
    """Capture window screenshot using PrintWindow or BitBlt fallback. Returns image bytes."""
    from PIL import Image as PILImage
    import io

    # Physical bounds (visible bounds via DWM)
    rect = _get_window_rect(hwnd)
    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top
    if win_w <= 0 or win_h <= 0:
        raise ValueError(f"Invalid window dimensions: {win_w}x{win_h}")

    # Logical bounds (DPI virtualized bounds via GetWindowRect)
    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    # Create device context and bitmap
    hdc = user32.GetDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc)
    
    # Use logical size for PrintWindow to prevent black/empty borders
    hbitmap = gdi32.CreateCompatibleBitmap(hdc, log_w, log_h)
    old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)

    # Capture window
    captured = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
    if not captured:
        # Fallback: try without PW_RENDERFULLCONTENT
        captured = user32.PrintWindow(hwnd, hdc_mem, 0)

    if captured:
        width = log_w
        height = log_h
    else:
        # Fallback: BitBlt from screen DC (physical size)
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

    # Prepare bitmap info
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # Top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    # Get pixel data
    buf_size = width * height * 4
    buf = ctypes.create_string_buffer(buf_size)
    gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)

    # Convert to PIL Image
    img = PILImage.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)
    img = img.convert("RGB")

    # Scale down if needed
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        img = img.resize((max_width, new_height), PILImage.LANCZOS)

    # Convert to bytes (JPEG is 10x smaller and more compatible, fallback to PNG)
    output = io.BytesIO()
    if format.lower() in ("jpeg", "jpg"):
        img.save(output, format="JPEG", quality=85)
    else:
        img.save(output, format="PNG", optimize=True)
    img_data = output.getvalue()

    # Cleanup
    gdi32.SelectObject(hdc_mem, old_bmp)
    gdi32.DeleteObject(hbitmap)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc)

    return img_data


def _activate_window(hwnd: int) -> bool:
    """Bring window to foreground."""
    try:
        # Restore if minimized
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)
        return user32.SetForegroundWindow(hwnd)
    except Exception:
        return False


def _get_client_offset(hwnd: int) -> tuple[int, int]:
    """Get client area offset from window rect."""
    window_rect = ctypes.wintypes.RECT()
    client_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(window_rect))
    user32.GetClientRect(hwnd, ctypes.byref(client_rect))
    point = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return (point.x - window_rect.left, point.y - window_rect.top)


def _build_accessibility_tree(hwnd: int, max_depth: int = 10, max_elements: int = 500) -> tuple[str, dict[int, Any], str, str]:
    """Build accessibility tree using UI Automation. Returns (tree_text, index_map, focused_element, selected_text)."""
    try:
        import comtypes
        import comtypes.client
        import comtypes.gen.UIAutomationClient as UIAClient

        # Ensure COM is initialized for the current thread
        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        # Create UI Automation instance
        uia = comtypes.client.CreateObject(
            '{ff48dba4-60ef-4201-aa87-54103eef594e}',
            interface=UIAClient.IUIAutomation
        )

        # Get element from handle
        element = uia.ElementFromHandle(hwnd)
        if not element:
            return "No accessible content", {}, "None", ""

        index_map = {}
        lines = []
        current_index = [0]  # Mutable counter

        def walk(elem, depth, parent_info=""):
            if depth > max_depth or current_index[0] >= max_elements:
                return

            idx = current_index[0]
            current_index[0] += 1
            index_map[idx] = elem

            try:
                name = elem.CurrentName or ""
                control_type = elem.CurrentLocalizedControlType or ""
                class_name = elem.CurrentClassName or ""

                # Get patterns
                patterns = []
                try:
                    # Check for Value pattern
                    vp = elem.GetCurrentPattern(10002)  # UIA_ValuePatternId
                    if vp:
                        patterns.append("Value")
                except Exception:
                    pass

                try:
                    # Check for Invoke pattern
                    ip = elem.GetCurrentPattern(10000)  # UIA_InvokePatternId
                    if ip:
                        patterns.append("Invoke")
                except Exception:
                    pass

                try:
                    # Check for Toggle pattern
                    tp = elem.GetCurrentPattern(10001)  # UIA_TogglePatternId
                    if tp:
                        patterns.append("Toggle")
                except Exception:
                    pass

                try:
                    # Check for SelectionItem pattern
                    sp = elem.GetCurrentPattern(10010)  # UIA_SelectionItemPatternId
                    if sp:
                        patterns.append("SelectionItem")
                except Exception:
                    pass

                # Build line
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
                line = f"{indent}[{idx}] {name_display} ({control_type}){pattern_str}{value_str}"
                lines.append(line)

                # Walk children
                walker = uia.CreateTreeWalker(uia.RawViewCondition)
                try:
                    child = walker.GetFirstChildElement(elem)
                    while child:
                        walk(child, depth + 1)
                        next_child = walker.GetNextSiblingElement(child)
                        child = next_child
                except Exception:
                    pass

            except Exception:
                pass

        walk(element, 0)
        tree_text = "\n".join(lines) if lines else "No accessible elements found"

        # --- Extract focused element and selected text ---
        focused_element_str = "None"
        selected_text_str = ""
        try:
            focused = uia.GetFocusedElement()
            if focused:
                f_name = focused.CurrentName or ""
                f_type = focused.CurrentLocalizedControlType or ""
                f_class = focused.CurrentClassName or ""
                focused_element_str = f'"{f_name}" ({f_type}) Class={f_class}'

                # Try TextPattern first for selection
                try:
                    tp = focused.GetCurrentPattern(10014)  # UIA_TextPatternId
                    if tp:
                        selection = tp.GetSelection()
                        if selection and selection.Length > 0:
                            selected_ranges = []
                            for idx_sel in range(selection.Length):
                                r = selection.GetElement(idx_sel)
                                selected_ranges.append(r.GetText(-1))
                            selected_text_str = "\n".join(selected_ranges)
                except Exception:
                    pass

                # Fallback to ValuePattern if no selection found
                if not selected_text_str:
                    try:
                        vp = focused.GetCurrentPattern(10002)  # UIA_ValuePatternId
                        if vp:
                            selected_text_str = vp.CurrentValue or ""
                    except Exception:
                        pass
        except Exception:
            pass

        return tree_text, index_map, focused_element_str, selected_text_str

    except ImportError:
        return "comtypes not installed - accessibility tree unavailable", {}, "None", ""
    except Exception as e:
        return f"Error building accessibility tree: {e}", {}, "None", ""


def _get_element_by_index(hwnd: int, index: int) -> Any:
    """Get element from index map."""
    with _element_index_lock:
        hwnd_map = _element_indices.get(hwnd, {})
        return hwnd_map.get(index)


def _set_clipboard_text(text: str) -> None:
    """Set clipboard text using Windows API."""
    CF_UNICODETEXT = 13

    user32.OpenClipboard(0)
    user32.EmptyClipboard()

    # Allocate memory for text
    text_bytes = text.encode("utf-16-le") + b"\x00\x00"
    h_mem = kernel32.GlobalAlloc(0x0042, len(text_bytes))  # GMEM_MOVEABLE | GMEM_ZEROINIT
    p_mem = kernel32.GlobalLock(h_mem)
    ctypes.memmove(p_mem, text_bytes, len(text_bytes))
    kernel32.GlobalUnlock(h_mem)

    user32.SetClipboardData(CF_UNICODETEXT, h_mem)
    user32.CloseClipboard()


def _paste_text(text: str) -> None:
    """Paste text via clipboard."""
    _set_clipboard_text(text)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.05)


def _parse_key_string(key_str: str) -> list[str]:
    """Parse key string like 'Control_L+c' into pyautogui key list."""
    # Map X11 keysym names to pyautogui names
    KEY_MAP = {
        "Control_L": "ctrl",
        "Control_R": "ctrl",
        "Shift_L": "shift",
        "Shift_R": "shift",
        "Alt_L": "alt",
        "Alt_R": "alt",
        "Return": "enter",
        "KP_Enter": "enter",
        "Escape": "escape",
        "Tab": "tab",
        "BackSpace": "backspace",
        "Delete": "delete",
        "space": "space",
        "Up": "up",
        "Down": "down",
        "Left": "left",
        "Right": "right",
        "Home": "home",
        "End": "end",
        "Page_Up": "pageup",
        "Page_Down": "pagedown",
        "F1": "f1",
        "F2": "f2",
        "F3": "f3",
        "F4": "f4",
        "F5": "f5",
        "F6": "f6",
        "F7": "f7",
        "F8": "f8",
        "F9": "f9",
        "F10": "f10",
        "F11": "f11",
        "F12": "f12",
        "period": ".",
        "greater": ">",
        "less": "<",
        "comma": ",",
        "slash": "/",
        "question": "?",
    }

    parts = key_str.replace(" ", "").split("+")
    result = []
    for part in parts:
        result.append(KEY_MAP.get(part, part.lower()))
    return result


# ========== MCP Tools ==========

@server.tool()
async def list_apps() -> str:
    """List running applications with their visible windows.

    Returns a formatted list showing each application's windows with HWND, title, and PID.
    Use the HWND values for other tools like get_window_state, click, etc.
    """
    try:
        windows = _enum_windows()

        # Group by process
        by_process: dict[str, list[dict]] = {}
        for w in windows:
            key = w.get("process_name") or "(unknown)"
            by_process.setdefault(key, []).append(w)

        lines = []
        for proc_name, wins in sorted(by_process.items()):
            lines.append(f"\nApplication: {proc_name}")
            for w in wins:
                lines.append(f"  [{w['hwnd']}] {w['title']} (PID={w['pid']})")

        return "\n".join(lines) if lines else "No visible windows found"

    except Exception as e:
        return f"Error listing apps: {e}"


@server.tool()
async def list_windows() -> str:
    """List all open visible windows.

    Returns a flat list of all visible windows with HWND, title, and process info.
    """
    try:
        windows = _enum_windows()

        lines = []
        for w in windows:
            lines.append(f"[{w['hwnd']}] {w['title']} - {w.get('process_name', 'unknown')} (PID={w['pid']})")

        return "\n".join(lines) if lines else "No visible windows found"

    except Exception as e:
        return f"Error listing windows: {e}"


@server.tool()
async def get_window(hwnd: Optional[int] = None) -> str:
    """Get information about a specific window by HWND.

    Args:
        hwnd: Window handle from list_apps or list_windows. If not provided, falls back to the active target.

    Returns window title, position, size, and state.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        # Get title
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value

        # Get rect
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        # Get PID
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        proc_path = _get_process_name(pid.value)

        return json.dumps({
            "hwnd": hwnd,
            "title": title,
            "pid": pid.value,
            "process_path": proc_path,
            "rect": {
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
            }
        }, indent=2, ensure_ascii=False)

    except Exception as e:
        return f"Error getting window: {e}"


@server.tool()
async def launch_app(path_or_name: str) -> str:
    """Launch an application by name or path.

    Args:
        path_or_name: Application name (e.g. "notepad") or full path (e.g. "C:\\Windows\\notepad.exe")

    Returns the HWND of the launched application's main window, or error message.
    """
    try:
        # Get current windows before launch
        before = {w["hwnd"] for w in _enum_windows()}

        # Launch via ShellExecute
        result = shell32.ShellExecuteW(None, "open", path_or_name, None, None, SW_SHOWNORMAL)

        if result <= 32:
            return f"Failed to launch '{path_or_name}' (error code: {result})"

        # Wait for window to appear
        time.sleep(1.0)

        # Find new windows
        after = _enum_windows()
        new_windows = [w for w in after if w["hwnd"] not in before]

        if new_windows:
            w = new_windows[0]
            return f"Launched '{path_or_name}' -> [{w['hwnd']}] {w['title']}"
        else:
            return f"Launched '{path_or_name}' but no new window detected. Check list_windows."

    except Exception as e:
        return f"Error launching app: {e}"


@server.tool()
async def get_window_state(hwnd: Optional[int] = None, include_screenshot: bool = True, include_accessibility: bool = False, max_screenshot_width: int = 1280) -> list:
    """Capture the current state of a window.

    Args:
        hwnd: Window handle. If not provided, falls back to the active target.
        include_screenshot: Whether to capture a screenshot (default True)
        include_accessibility: Whether to build accessibility tree with element indexes (default False)
        max_screenshot_width: Maximum screenshot width in pixels (default 1280)

    Returns screenshot image and/or accessibility tree with element indexes, focused element, and selected text.
    Element indexes are ephemeral - they're only valid until the next get_window_state call.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return [f"Window {hwnd} no longer exists"]

        result = []

        # Screenshot
        if include_screenshot:
            try:
                img_data = _capture_window_screenshot(hwnd, max_screenshot_width, format="jpeg")
                img = Image(data=img_data, format="jpeg")
                # Add text descriptor to prevent 400 "text is not set" in strict clients/models like MiMo
                result.append("Captured screenshot of target window state:")
                result.append(img)
            except Exception as e:
                result.append(f"Screenshot error: {e}")

        # Accessibility tree
        if include_accessibility:
            try:
                tree_text, index_map, focused_element, selected_text = _build_accessibility_tree(hwnd)

                # Store index map
                with _element_index_lock:
                    _element_indices[hwnd] = index_map

                accessibility_summary = [
                    f"Accessibility Tree (indexes refreshed, {len(index_map)} elements):",
                    f"Focused UI Element: {focused_element}"
                ]
                if selected_text:
                    accessibility_summary.append(f"Selected/Value Text: \"{selected_text}\"")
                accessibility_summary.append("\n" + tree_text)

                result.append("\n".join(accessibility_summary))
            except Exception as e:
                result.append(f"Accessibility tree error: {e}")

        if not result:
            return ["No data captured. Set include_screenshot or include_accessibility to True."]

        return result

    except Exception as e:
        return [f"Error capturing window state: {e}"]


@server.tool()
async def click(hwnd: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None, index: Optional[int] = None, button: str = "left", clicks: int = 1, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> str:
    """Click in a window at coordinates or on an element by index.

    Args:
        hwnd: Window handle. If not provided, falls back to the active target.
        x: X coordinate in window (client area). Required if index not provided.
        y: Y coordinate in window (client area). Required if index not provided.
        index: Element index from get_window_state accessibility tree. Takes priority over x/y.
        button: Mouse button - "left", "right", or "middle" (default "left")
        clicks: Number of clicks (default 1)
        screenshot_width: Width of screenshot clicked on, for dynamic coordinate scaling.
        screenshot_height: Height of screenshot clicked on, for dynamic coordinate scaling.

    Coordinates are relative to the window's client area.
    Element indexes are ephemeral - refresh with get_window_state if stale.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        _activate_window(hwnd)
        time.sleep(0.1)

        if index is not None:
            # Click by element index
            elem = _get_element_by_index(hwnd, index)
            if not elem:
                return f"Element index {index} not found. Call get_window_state to refresh indexes."

            try:
                rect = elem.CurrentBoundingRectangle
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2

                # In DPI-aware process, pyautogui click expects physical screen coordinates
                pyautogui.click(cx, cy, button=button, clicks=clicks)
                return f"Clicked element [{index}] at screen ({cx}, {cy})"
            except Exception as e:
                return f"Error clicking element [{index}]: {e}"

        elif x is not None and y is not None:
            # Click by coordinates - scale from screenshot space to logical window, then add DWM offset
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            ss_w = screenshot_width
            ss_h = screenshot_height
            if not ss_w:
                ss_w = 1280 if log_w > 1280 else log_w
            if not ss_h:
                ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

            real_x = int(x * log_w / ss_w)
            real_y = int(y * log_h / ss_h)

            screen_x = rect.left + real_x
            screen_y = rect.top + real_y

            # In DPI-aware process, pyautogui click expects physical screen coordinates
            pyautogui.click(screen_x, screen_y, button=button, clicks=clicks)
            return f"Clicked at window logical ({real_x}, {real_y}) -> screen physical ({screen_x}, {screen_y}) [scaled from screenshot ({x}, {y})]"
        else:
            return "Must provide either (x, y) coordinates or element index"

    except Exception as e:
        return f"Error clicking: {e}"


@server.tool()
async def type_text(text: str, hwnd: Optional[int] = None) -> str:
    """Type text into a window.

    Args:
        text: Text to type (supports Unicode/Chinese characters)
        hwnd: Window handle. If not provided, falls back to the active target.

    Activates the window first, then pastes text via clipboard.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        _activate_window(hwnd)
        time.sleep(0.1)

        _paste_text(text)
        return f"Typed {len(text)} characters"

    except Exception as e:
        return f"Error typing text: {e}"


@server.tool()
async def press_key(keys: str, hwnd: Optional[int] = None) -> str:
    """Press a key or keyboard shortcut.

    Args:
        keys: Key combo e.g. "Control_L+c"
        hwnd: Window handle. If not provided, falls back to the active target.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        _activate_window(hwnd)
        time.sleep(0.1)

        key_list = _parse_key_string(keys)

        if len(key_list) == 1:
            pyautogui.press(key_list[0])
        else:
            pyautogui.hotkey(*key_list)

        return f"Pressed: {keys}"

    except Exception as e:
        return f"Error pressing key: {e}"


@server.tool()
async def scroll(x: int, y: int, scroll_y: int, hwnd: Optional[int] = None, scroll_x: int = 0, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> str:
    """Scroll in a window at the specified coordinates.

    Args:
        x: X coordinate to scroll from
        y: Y coordinate to scroll from
        scroll_y: Vertical scroll amount (positive = scroll down, negative = scroll up)
        hwnd: Window handle. If not provided, falls back to the active target.
        scroll_x: Horizontal scroll amount (positive = scroll right, negative = scroll left)
        screenshot_width: Width of screenshot for dynamic coordinate scaling.
        screenshot_height: Height of screenshot for dynamic coordinate scaling.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        _activate_window(hwnd)
        time.sleep(0.1)

        # Convert to screen coords with scaling using logical ratio + DWM offset
        rect = _get_window_rect(hwnd)
        logical_rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
        log_w = logical_rect.right - logical_rect.left
        log_h = logical_rect.bottom - logical_rect.top

        ss_w = screenshot_width
        ss_h = screenshot_height
        if not ss_w:
            ss_w = 1280 if log_w > 1280 else log_w
        if not ss_h:
            ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

        real_x = int(x * log_w / ss_w)
        real_y = int(y * log_h / ss_h)

        screen_x = rect.left + real_x
        screen_y = rect.top + real_y

        # In DPI-aware process, pyautogui expects physical screen coordinates
        if scroll_y != 0:
            pyautogui.scroll(-scroll_y, x=screen_x, y=screen_y)

        if scroll_x != 0:
            pyautogui.hscroll(scroll_x, x=screen_x, y=screen_y)

        return f"Scrolled at window logical ({real_x}, {real_y}) -> screen physical ({screen_x}, {screen_y}) [scaled from screenshot ({x}, {y})]: dx={scroll_x}, dy={scroll_y}"

    except Exception as e:
        return f"Error scrolling: {e}"


@server.tool()
async def drag(start_x: int, start_y: int, end_x: int, end_y: int, hwnd: Optional[int] = None, duration: float = 0.5, button: str = "left", screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> str:
    """Drag from one position to another in a window.

    Args:
        start_x: Starting X coordinate
        start_y: Starting Y coordinate
        end_x: Ending X coordinate
        end_y: Ending Y coordinate
        hwnd: Window handle. If not provided, falls back to the active target.
        duration: Drag duration in seconds (default 0.5)
        button: Mouse button to use (default "left")
        screenshot_width: Width of screenshot for dynamic coordinate scaling.
        screenshot_height: Height of screenshot for dynamic coordinate scaling.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        _activate_window(hwnd)
        time.sleep(0.1)

        # Convert to screen coords with scaling using DWM bounds
        window_rect = _get_window_rect(hwnd)

        win_w = window_rect.right - window_rect.left
        win_h = window_rect.bottom - window_rect.top

        ss_w = screenshot_width
        ss_h = screenshot_height
        if not ss_w:
            ss_w = 1280 if win_w > 1280 else win_w
        if not ss_h:
            ss_h = int(win_h * 1280 / win_w) if win_w > 1280 else win_h

        real_sx = int(start_x * win_w / ss_w)
        real_sy = int(start_y * win_h / ss_h)
        real_ex = int(end_x * win_w / ss_w)
        real_ey = int(end_y * win_h / ss_h)

        sx = window_rect.left + real_sx
        sy = window_rect.top + real_sy
        ex = window_rect.left + real_ex
        ey = window_rect.top + real_ey

        # In DPI-aware process, pyautogui expects physical screen coordinates
        pyautogui.moveTo(sx, sy)
        pyautogui.drag(ex - sx, ey - sy, duration=duration, button=button)

        return f"Dragged from ({real_sx},{real_sy}) to ({real_ex},{real_ey}) [scaled from screenshot start ({start_x},{start_y}) to ({end_x},{end_y})]"

    except Exception as e:
        return f"Error dragging: {e}"


@server.tool()
async def set_value(index: int, value: str, hwnd: Optional[int] = None) -> str:
    """Set the value of an editable element by index.

    Args:
        index: Element index from get_window_state accessibility tree
        value: New value to set
        hwnd: Window handle. If not provided, falls back to the active target.

    Element indexes are ephemeral - refresh with get_window_state if stale.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        elem = _get_element_by_index(hwnd, index)
        if not elem:
            return f"Element index {index} not found. Call get_window_state to refresh indexes."

        try:
            # Try ValuePattern
            vp = elem.GetCurrentPattern(10002)  # UIA_ValuePatternId
            if vp:
                vp.SetValue(value)
                return f"Set value of element [{index}] to: {value}"
            else:
                return f"Element [{index}] does not support Value pattern"
        except Exception as e:
            return f"Error setting value on element [{index}]: {e}"

    except Exception as e:
        return f"Error: {e}"


@server.tool()
async def perform_secondary_action(index: int, action: str, hwnd: Optional[int] = None) -> str:
    """Perform a secondary action on an element by index.

    Args:
        index: Element index from get_window_state accessibility tree
        action: Action to perform. Common actions: Invoke, Toggle, Expand, Collapse, Select
        hwnd: Window handle. If not provided, falls back to the active target.

    Element indexes are ephemeral - refresh with get_window_state if stale.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        elem = _get_element_by_index(hwnd, index)
        if not elem:
            return f"Element index {index} not found. Call get_window_state to refresh indexes."

        action_lower = action.lower()

        try:
            if action_lower == "invoke":
                ip = elem.GetCurrentPattern(10000)  # UIA_InvokePatternId
                if ip:
                    ip.Invoke()
                    return f"Invoked element [{index}]"
                else:
                    return f"Element [{index}] does not support Invoke pattern"

            elif action_lower == "toggle":
                tp = elem.GetCurrentPattern(10001)  # UIA_TogglePatternId
                if tp:
                    tp.Toggle()
                    return f"Toggled element [{index}]"
                else:
                    return f"Element [{index}] does not support Toggle pattern"

            elif action_lower in ("expand", "collapse"):
                ep = elem.GetCurrentPattern(10005)  # UIA_ExpandCollapsePatternId
                if ep:
                    if action_lower == "expand":
                        ep.Expand()
                    else:
                        ep.Collapse()
                    return f"{action.capitalize()}ed element [{index}]"
                else:
                    return f"Element [{index}] does not support ExpandCollapse pattern"

            elif action_lower == "select":
                sp = elem.GetCurrentPattern(10010)  # UIA_SelectionItemPatternId
                if sp:
                    sp.Select()
                    return f"Selected element [{index}]"
                else:
                    return f"Element [{index}] does not support SelectionItem pattern"

            else:
                return f"Unknown action: {action}. Supported: Invoke, Toggle, Expand, Collapse, Select"

        except Exception as e:
            return f"Error performing {action} on element [{index}]: {e}"

    except Exception as e:
        return f"Error: {e}"


@server.tool()
async def activate_window(hwnd: Optional[int] = None) -> str:
    """Bring a window to the foreground.

    Args:
        hwnd: Window handle. If not provided, falls back to the active target.

    Restores the window if minimized and brings it to front.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)

        if _activate_window(hwnd):
            return f"Activated window [{hwnd}]: {buf.value}"
        else:
            return f"Failed to activate window [{hwnd}]: {buf.value}"

    except Exception as e:
        return f"Error activating window: {e}"


@server.tool()
async def check_safety(action: str) -> dict:
    """Check if an action requires user confirmation before proceeding.

    Args:
        action: Descriptive action string, e.g. "delete text.txt" or "install chrome"

    Returns safety check status.
    """
    try:
        return _check_safety(action)
    except Exception as e:
        return {"error": str(e)}





@server.tool()
async def hover(hwnd: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None, index: Optional[int] = None, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> str:
    """Move the mouse cursor over a window coordinate or an accessibility element without clicking.
    This triggers hover states (like play buttons or details panel) that are hidden by default.

    Args:
        hwnd: Window handle. If not provided, falls back to the active target.
        x: X coordinate in window. Required if index not provided.
        y: Y coordinate in window. Required if index not provided.
        index: Element index from get_window_state accessibility tree. Takes priority over x/y.
        screenshot_width: Width of screenshot for dynamic coordinate scaling.
        screenshot_height: Height of screenshot for dynamic coordinate scaling.
    """
    try:
        hwnd = _resolve_target(hwnd)
        if not user32.IsWindow(hwnd):
            return f"Window {hwnd} no longer exists"

        _activate_window(hwnd)
        time.sleep(0.1)

        if index is not None:
            elem = _get_element_by_index(hwnd, index)
            if not elem:
                return f"Element index {index} not found. Call get_window_state to refresh indexes."

            try:
                rect = elem.CurrentBoundingRectangle
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                pyautogui.moveTo(cx, cy)
                return f"Hovered over element [{index}] at screen ({cx}, {cy})"
            except Exception as e:
                return f"Error hovering over element [{index}]: {e}"

        elif x is not None and y is not None:
            window_rect = _get_window_rect(hwnd)
            win_w = window_rect.right - window_rect.left
            win_h = window_rect.bottom - window_rect.top

            ss_w = screenshot_width
            ss_h = screenshot_height
            if not ss_w:
                ss_w = 1280 if win_w > 1280 else win_w
            if not ss_h:
                ss_h = int(win_h * 1280 / win_w) if win_w > 1280 else win_h

            real_x = int(x * win_w / ss_w)
            real_y = int(y * win_h / ss_h)

            screen_x = window_rect.left + real_x
            screen_y = window_rect.top + real_y

            pyautogui.moveTo(screen_x, screen_y)
            return f"Hovered at window ({real_x}, {real_y}) -> screen ({screen_x}, {screen_y}) [scaled from screenshot ({x}, {y})]"
        else:
            return "Must provide either (x, y) coordinates or element index"

    except Exception as e:
        return f"Error hovering: {e}"







def _cleanup_workspace_visuals():
    """Clean up cluttered temporary screenshot files from the workspace folder."""
    try:
        dir_path = os.path.dirname(os.path.abspath(__file__))
        # Only delete known default temp screenshot files, leaving user assets safe
        temp_targets = ["screenshot.png", "screenshot.jpg", "temp.png", "temp.jpg"]
        for target in temp_targets:
            file_path = os.path.join(dir_path, target)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
    except Exception:
        pass


def main():
    """Entry point for the MCP server."""
    _cleanup_workspace_visuals()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
