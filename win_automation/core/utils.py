"""
Shared utility routines for rectangle arithmetic, HWND validation, safe message sending,
RGB color conversions, and message queue pumping.
"""

from __future__ import annotations

import re
import math
import time
import ctypes
import ctypes.wintypes
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from win_automation.core.win32_structures import user32, SMTO_ABORTIFHUNG


def clamp_int(val: int, min_val: int, max_val: int) -> int:
    """Clamp an integer value within [min_val, max_val]."""
    return max(min_val, min(max_val, int(val)))


def is_valid_hwnd(hwnd: Any) -> bool:
    """Check if the given HWND is a valid, live Win32 window."""
    try:
        val = int(hwnd or 0)
        return val != 0 and bool(user32.IsWindow(val))
    except (ValueError, TypeError):
        return False


def make_lparam(low: int, high: int) -> int:
    """Construct an LPARAM from low and high 16-bit words."""
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


def rect_center(rect: Optional[Union[Dict[str, Any], Tuple, List]]) -> Optional[Tuple[int, int]]:
    """Compute the center (x, y) coordinates of a bounding rectangle."""
    if not rect:
        return None
    if isinstance(rect, dict):
        if "center_x" in rect and "center_y" in rect:
            return int(rect["center_x"]), int(rect["center_y"])
        left = int(rect.get("left") or 0)
        top = int(rect.get("top") or 0)
        right = int(rect.get("right") or left)
        bottom = int(rect.get("bottom") or top)
        if right <= left or bottom <= top:
            return None
        return (left + right) // 2, (top + bottom) // 2
    if isinstance(rect, (tuple, list)) and len(rect) >= 4:
        left, top, right, bottom = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
        return (left + right) // 2, (top + bottom) // 2
    return None


_rect_center = rect_center  # Compatibility alias


def rect_to_plain_dict(rect: Any) -> Dict[str, int]:
    """Convert a RECT structure or dictionary to standard dictionary."""
    if hasattr(rect, "left") and hasattr(rect, "top") and hasattr(rect, "right") and hasattr(rect, "bottom"):
        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
    elif isinstance(rect, dict):
        left = int(rect.get("left", 0))
        top = int(rect.get("top", 0))
        right = int(rect.get("right", left))
        bottom = int(rect.get("bottom", top))
    else:
        return {"left": 0, "top": 0, "right": 0, "bottom": 0, "width": 0, "height": 0}

    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
    }


def send_message_timeout(
    hwnd: int,
    msg: int,
    wparam: int = 0,
    lparam: Any = 0,
    timeout_ms: int = 1000,
    flags: int = SMTO_ABORTIFHUNG,
) -> Tuple[bool, int]:
    """
    Safely send a Win32 message with a timeout.
    Returns (success: bool, result: int).
    """
    if not is_valid_hwnd(hwnd):
        return False, 0
    res = ctypes.c_size_t(0)
    ok = user32.SendMessageTimeoutW(
        ctypes.c_void_p(int(hwnd)),
        ctypes.c_uint(int(msg)),
        ctypes.c_size_t(int(wparam)),
        ctypes.c_ssize_t(int(lparam) if isinstance(lparam, int) else 0),
        ctypes.c_uint(flags),
        ctypes.c_uint(max(10, int(timeout_ms))),
        ctypes.byref(res),
    )
    return bool(ok), int(res.value)


def pump_wait(
    predicate: Callable[[], Any],
    timeout: float = 5.0,
    interval: float = 0.05,
) -> Any:
    """
    Wait loop pumping the Win32 message queue while polling a predicate.
    """
    deadline = time.monotonic() + max(0.0, float(timeout))
    msg = ctypes.wintypes.MSG()
    while True:
        res = predicate()
        if res:
            return res
        if time.monotonic() >= deadline:
            return predicate()

        # Pump any pending Windows messages
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE = 1
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        time.sleep(max(0.005, float(interval)))


def shorten(text: str, limit: int = 100) -> str:
    """Truncate text to limit with ellipsis."""
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[:limit - 3] + "..."


def parse_rgb_color(value: Any) -> Tuple[int, int, int]:
    """Parse color into (R, G, B) tuple from hex string, tuple, list, or dict."""
    if isinstance(value, dict):
        if all(key in value for key in ("r", "g", "b")):
            return (
                clamp_int(int(round(float(value["r"]))), 0, 255),
                clamp_int(int(round(float(value["g"]))), 0, 255),
                clamp_int(int(round(float(value["b"]))), 0, 255),
            )
        if "rgb" in value:
            return parse_rgb_color(value["rgb"])
        if "hex" in value:
            return parse_rgb_color(value["hex"])
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (
            clamp_int(int(round(float(value[0]))), 0, 255),
            clamp_int(int(round(float(value[1]))), 0, 255),
            clamp_int(int(round(float(value[2]))), 0, 255),
        )
    text = str(value or "").strip()
    if not text:
        raise ValueError("color is required")
    if text.startswith("#"):
        text = text[1:]
    if text.lower().startswith("0x"):
        text = text[2:]
    if re.fullmatch(r"[0-9a-fA-F]{3}", text):
        text = "".join(ch * 2 for ch in text)
    if re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    parts = [part.strip() for part in re.split(r"[,;\s]+", text) if part.strip()]
    if len(parts) >= 3:
        return (
            clamp_int(int(round(float(parts[0]))), 0, 255),
            clamp_int(int(round(float(parts[1]))), 0, 255),
            clamp_int(int(round(float(parts[2]))), 0, 255),
        )
    raise ValueError(f"Cannot parse color '{value}' - must be #rrggbb, (r,g,b), or dict")


_parse_rgb_color = parse_rgb_color  # Compatibility alias


def rgb_distance(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> float:
    """Compute Euclidean distance between two RGB colors."""
    return math.sqrt(sum((int(a[i]) - int(b[i])) ** 2 for i in range(3)))


_rgb_distance = rgb_distance  # Compatibility alias
