"""
Windows Automation MCP Server
Provides tools for controlling Windows applications via MCP protocol.
"""

import ctypes
import ctypes.wintypes
import json
import os
import sys
import time
import io
import threading
from typing import Any, Optional
from PIL import Image as PILImage

# Shared constants, structs, utilities
from common import (
    user32, kernel32, shell32, gdi32, dwmapi,
    BITMAPINFOHEADER, BITMAPINFO,
    GWL_STYLE, GWL_EXSTYLE, WS_VISIBLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW,
    SW_RESTORE, SW_SHOW, SW_SHOWNORMAL,
    PROCESS_QUERY_INFORMATION, PROCESS_QUERY_LIMITED_INFORMATION,
    MAX_PATH, PW_RENDERFULLCONTENT, SRCCOPY,
    STATE_FILE, _load_state, _save_state, _resolve_target,
    _get_dpi_scale, _get_window_rect, _get_process_name,
    _enum_windows, _set_clipboard_text, _clipboard_save, _clipboard_restore, _activate_window,
    _check_safety,
)

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


def _capture_window_screenshot(hwnd: int, max_width: int = 1280, format: str = "jpeg") -> bytes:
    """Capture window screenshot using PrintWindow or BitBlt fallback. Returns image bytes."""

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

        hdc = 0  # Mark as already released
        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, win_w, win_h)
        old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)
        gdi32.BitBlt(hdc_mem, 0, 0, win_w, win_h,
                     hdc_screen, rect.left, rect.top, SRCCOPY)
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

    # Convert to bytes
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
    if hdc:
        user32.ReleaseDC(hwnd, hdc)

    return img_data


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

        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        uia = comtypes.client.CreateObject(
            '{ff48dba4-60ef-4201-aa87-54103eef594e}',
            interface=UIAClient.IUIAutomation
        )

        element = uia.ElementFromHandle(hwnd)
        if not element:
            return "No accessible content", {}, "None", ""

        index_map = {}
        lines = []
        current_index = [0]

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

                patterns = []
                try:
                    vp = elem.GetCurrentPattern(10002)  # UIA_ValuePatternId
                    if vp:
                        patterns.append("Value")
                except Exception:
                    pass
                try:
                    ip = elem.GetCurrentPattern(10000)  # UIA_InvokePatternId
                    if ip:
                        patterns.append("Invoke")
                except Exception:
                    pass
                try:
                    tp = elem.GetCurrentPattern(10001)  # UIA_TogglePatternId
                    if tp:
                        patterns.append("Toggle")
                except Exception:
                    pass
                try:
                    sp = elem.GetCurrentPattern(10010)  # UIA_SelectionItemPatternId
                    if sp:
                        patterns.append("SelectionItem")
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
                line = f"{indent}[{idx}] {name_display} ({control_type}){pattern_str}{value_str}"
                lines.append(line)

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

        focused_element_str = "None"
        selected_text_str = ""
        try:
            focused = uia.GetFocusedElement()
            if focused:
                f_name = focused.CurrentName or ""
                f_type = focused.CurrentLocalizedControlType or ""
                f_class = focused.CurrentClassName or ""
                focused_element_str = f'"{f_name}" ({f_type}) Class={f_class}'

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


def _paste_text(text: str) -> None:
    """Paste text via clipboard, preserving user's clipboard."""
    saved = _clipboard_save()
    _set_clipboard_text(text)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.05)
    _clipboard_restore(saved)


def _scale_screenshot_to_screen(hwnd: int, x: int, y: int,
                                screenshot_width: int | None = None,
                                screenshot_height: int | None = None) -> tuple[int, int, int, int]:
    """Scale screenshot-pixel coordinates to physical screen coordinates.
    Uses DWM visible rect consistently for both ratio and offset.
    Returns (screen_x, screen_y, window_x, window_y)."""
    rect = _get_window_rect(hwnd)
    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top

    ss_w = screenshot_width or min(1280, win_w) if win_w > 0 else 1280
    ss_h = screenshot_height or min(int(win_h * 1280 / win_w), win_h) if win_w > 0 else win_h

    # Guard against division by zero
    if ss_w <= 0:
        ss_w = 1
    if ss_h <= 0:
        ss_h = 1

    real_x = int(x * win_w / ss_w)
    real_y = int(y * win_h / ss_h)
    screen_x = rect.left + real_x
    screen_y = rect.top + real_y
    return screen_x, screen_y, real_x, real_y


def _parse_key_string(key_str: str) -> list[str]:
    """Parse key string like 'Control_L+c' into pyautogui key list."""
    KEY_MAP = {
        "Control_L": "ctrl", "Control_R": "ctrl",
        "Shift_L": "shift", "Shift_R": "shift",
        "Alt_L": "alt", "Alt_R": "alt",
        "Return": "enter", "KP_Enter": "enter",
        "Escape": "escape", "Tab": "tab",
        "BackSpace": "backspace", "Delete": "delete",
        "space": "space",
        "Up": "up", "Down": "down", "Left": "left", "Right": "right",
        "Home": "home", "End": "end",
        "Page_Up": "pageup", "Page_Down": "pagedown",
        "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4",
        "F5": "f5", "F6": "f6", "F7": "f7", "F8": "f8",
        "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12",
        "period": ".", "greater": ">", "less": "<",
        "comma": ",", "slash": "/", "question": "?",
    }
    parts = key_str.replace(" ", "").split("+")
    return [KEY_MAP.get(part, part.lower()) for part in parts]


# ========== MCP Tools ==========

@server.tool()
async def list_apps() -> str:
    """List running applications with their visible windows.

    Returns a formatted list showing each application's windows with HWND, title, and PID.
    Use the HWND values for other tools like get_window_state, click, etc.
    """
    try:
        windows = _enum_windows()
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

        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value

        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        proc_path = _get_process_name(pid.value)

        return json.dumps({
            "hwnd": hwnd,
            "title": title,
            "pid": pid.value,
            "process_path": proc_path,
            "rect": {
                "left": rect.left, "top": rect.top,
                "right": rect.right, "bottom": rect.bottom,
                "width": rect.right - rect.left, "height": rect.bottom - rect.top,
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
        before = {w["hwnd"] for w in _enum_windows()}
        result = shell32.ShellExecuteW(None, "open", path_or_name, None, None, SW_SHOWNORMAL)
        if result <= 32:
            return f"Failed to launch '{path_or_name}' (error code: {result})"

        time.sleep(1.0)

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

        if include_screenshot:
            try:
                img_data = _capture_window_screenshot(hwnd, max_screenshot_width, format="jpeg")
                img = Image(data=img_data, format="jpeg")
                result.append("Captured screenshot of target window state:")
                result.append(img)
            except Exception as e:
                result.append(f"Screenshot error: {e}")

        if include_accessibility:
            try:
                tree_text, index_map, focused_element, selected_text = _build_accessibility_tree(hwnd)

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
            elem = _get_element_by_index(hwnd, index)
            if not elem:
                return f"Element index {index} not found. Call get_window_state to refresh indexes."
            try:
                rect = elem.CurrentBoundingRectangle
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                pyautogui.click(cx, cy, button=button, clicks=clicks)
                return f"Clicked element [{index}] at screen ({cx}, {cy})"
            except Exception as e:
                return f"Error clicking element [{index}]: {e}"

        elif x is not None and y is not None:
            screen_x, screen_y, real_x, real_y = _scale_screenshot_to_screen(
                hwnd, x, y, screenshot_width, screenshot_height)

            pyautogui.click(screen_x, screen_y, button=button, clicks=clicks)
            return f"Clicked at window ({real_x}, {real_y}) -> screen ({screen_x}, {screen_y}) [from screenshot ({x}, {y})]"
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

        screen_x, screen_y, real_x, real_y = _scale_screenshot_to_screen(
            hwnd, x, y, screenshot_width, screenshot_height)

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

        sx, sy, rsx, rsy = _scale_screenshot_to_screen(hwnd, start_x, start_y, screenshot_width, screenshot_height)
        ex, ey, rex, rey = _scale_screenshot_to_screen(hwnd, end_x, end_y, screenshot_width, screenshot_height)

        pyautogui.moveTo(sx, sy)
        pyautogui.drag(ex - sx, ey - sy, duration=duration, button=button)

        return f"Dragged from ({rsx},{rsy}) to ({rex},{rey}) [from screenshot ({start_x},{start_y}) to ({end_x},{end_y})]"
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
                return f"Element [{index}] does not support Invoke pattern"
            elif action_lower == "toggle":
                tp = elem.GetCurrentPattern(10001)  # UIA_TogglePatternId
                if tp:
                    tp.Toggle()
                    return f"Toggled element [{index}]"
                return f"Element [{index}] does not support Toggle pattern"
            elif action_lower in ("expand", "collapse"):
                ep = elem.GetCurrentPattern(10005)  # UIA_ExpandCollapsePatternId
                if ep:
                    if action_lower == "expand":
                        ep.Expand()
                    else:
                        ep.Collapse()
                    return f"{action.capitalize()}ed element [{index}]"
                return f"Element [{index}] does not support ExpandCollapse pattern"
            elif action_lower == "select":
                sp = elem.GetCurrentPattern(10010)  # UIA_SelectionItemPatternId
                if sp:
                    sp.Select()
                    return f"Selected element [{index}]"
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
async def check_safety(action: str) -> str:
    """Check if an action requires user confirmation before proceeding.

    Args:
        action: Descriptive action string, e.g. "delete text.txt" or "install chrome"

    Returns safety check status.
    """
    try:
        result = _check_safety(action)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


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
            screen_x, screen_y, real_x, real_y = _scale_screenshot_to_screen(
                hwnd, x, y, screenshot_width, screenshot_height)

            pyautogui.moveTo(screen_x, screen_y)
            return f"Hovered at window ({real_x}, {real_y}) -> screen ({screen_x}, {screen_y}) [from screenshot ({x}, {y})]"
        else:
            return "Must provide either (x, y) coordinates or element index"
    except Exception as e:
        return f"Error hovering: {e}"


def _cleanup_workspace_visuals():
    """Clean up cluttered temporary screenshot files from the workspace folder."""
    try:
        dir_path = os.path.dirname(os.path.abspath(__file__))
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
