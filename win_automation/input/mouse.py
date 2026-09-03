"""
Mouse injection, cursor positioning, window-relative clicks, dragging, scrolling, and desktop-level mouse actions.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.core.dpi import get_dpi_scale_for_hwnd, scale_coord
from win_automation.core.utils import is_valid_hwnd
from win_automation.win32.window import _window_info, activate_window, _get_window_rect
from win_automation.helper.client import _helper_route_for_hwnd, _helper_route_for_screen_point, _helper_post, _elevated_helper_required_message, _helper_ok
from win_automation.state.persistence import resolve_target_hwnd, load_screenshot_meta

def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)

def _get_screenshot_size(screenshot_id: Optional[int] = None) -> Dict[str, int]:
    meta = load_screenshot_meta(screenshot_id)
    if meta and "width" in meta and "height" in meta:
        return {"width": meta["width"], "height": meta["height"]}
    return {"width": 1280, "height": 834}

def _scale_coords(hwnd: int, x: int, y: int, screenshot_id: Optional[int] = None) -> Tuple[int, int, str]:
    rect = _get_window_rect(hwnd)
    if not rect:
        return int(x), int(y), "direct"
    left, top, right, bottom = rect
    return int(left + x), int(top + y), f"window({left},{top})"

def _set_cursor_pos_checked(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))

def mouse_position() -> Dict[str, Any]:
    """Return current cursor position in screen coordinates."""
    point = ctypes.wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return {"error": "GetCursorPos failed"}
    return {"x": point.x, "y": point.y}



def _normalize_mouse_button(button: str = "left") -> str:
    normalized = str(button or "left").strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    normalized = _MOUSE_BUTTON_ALIASES.get(normalized, normalized)
    if normalized not in _MOUSE_BUTTON_EVENTS:
        raise ValueError(f"Unsupported mouse button '{button}'. Use left, right, or middle.")
    return normalized


def _mouse_click_screen(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    button = _normalize_mouse_button(button)
    _set_cursor_pos_checked(int(x), int(y))
    time.sleep(0.05)
    down, up = _MOUSE_BUTTON_EVENTS[button]
    for i in range(max(int(clicks), 1)):
        if i:
            time.sleep(0.05)
        _send_mouse_input(down, label=f"mouse {button} down")
        time.sleep(0.02)
        _send_mouse_input(up, label=f"mouse {button} up")


def _click_absolute_screen(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
    screen_x, screen_y = int(x), int(y)
    helper_ready, helper_elevated, point_hwnd, boundary_result = _helper_route_for_screen_point(screen_x, screen_y, "/click")
    if boundary_result is not None:
        boundary_result.update({
            "screen": {"x": screen_x, "y": screen_y},
            "point_hwnd": int(point_hwnd or 0),
            "button": button,
            "clicks": int(clicks),
        })
        return boundary_result
    if helper_ready:
        result = _helper_post("/click", {"x": screen_x, "y": screen_y, "button": button, "clicks": clicks, "absolute": True}, elevated=helper_elevated)
        if result.get("ok"):
            return {
                "ok": True,
                "screen_x": screen_x,
                "screen_y": screen_y,
                "button": button,
                "clicks": int(clicks),
                "helper": True,
                "helper_elevated": bool(helper_elevated),
                "point_hwnd": point_hwnd,
            }
    _mouse_click_screen(screen_x, screen_y, button=button, clicks=clicks)
    return {
        "ok": True,
        "screen_x": screen_x,
        "screen_y": screen_y,
        "button": button,
        "clicks": int(clicks),
        "helper": False,
        "point_hwnd": point_hwnd,
    }


def _move_absolute_screen(x: int, y: int, duration: float = 0.0, settle: float = 0.05) -> Dict[str, Any]:
    screen_x, screen_y = int(x), int(y)
    helper_ready, helper_elevated, point_hwnd, boundary_result = _helper_route_for_screen_point(screen_x, screen_y, "/move")
    if boundary_result is not None:
        boundary_result.update({
            "screen": {"x": screen_x, "y": screen_y},
            "point_hwnd": int(point_hwnd or 0),
        })
        return boundary_result
    if helper_ready:
        result = _helper_post("/move", {"x": screen_x, "y": screen_y, "duration": duration, "settle": settle, "absolute": True}, elevated=helper_elevated)
        if result.get("ok"):
            return {
                "ok": True,
                "screen_x": int(result.get("screen_x", screen_x)),
                "screen_y": int(result.get("screen_y", screen_y)),
                "helper": True,
                "helper_elevated": bool(helper_elevated),
                "point_hwnd": point_hwnd,
                "settle": settle,
            }
    _set_cursor_pos_checked(screen_x, screen_y)
    if settle and float(settle) > 0:
        time.sleep(float(settle))
    return {
        "ok": True,
        "screen_x": screen_x,
        "screen_y": screen_y,
        "helper": False,
        "point_hwnd": point_hwnd,
        "settle": settle,
    }


def move_mouse(
    hwnd: int | None,
    x: int,
    y: int,
    screenshot_id: Optional[int] = None,
    duration: float = 0.0,
    settle: float = 0.05,
    activate: bool = True,
) -> str:
    """Move the cursor to a window screenshot coordinate without clicking."""
    hwnd = _resolve_target(hwnd)
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/move")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        ss_info = _get_screenshot_size(screenshot_id)
        result = _helper_post("/move", {
            "hwnd": hwnd,
            "x": x,
            "y": y,
            "duration": duration,
            "settle": settle,
            "activate": activate,
            "screenshot_width": ss_info["width"],
            "screenshot_height": ss_info["height"],
        }, elevated=helper_elevated)
        if _helper_ok(result):
            helper_label = "elevated helper" if helper_elevated else "helper"
            return f"Moved via {helper_label}: screen({result.get('screen_x', 0)},{result.get('screen_y', 0)})"
    if activate:
        activate_window(hwnd)
        time.sleep(0.1)
    screen_x, screen_y, debug = _scale_coords(hwnd, x, y, screenshot_id)
    _set_cursor_pos_checked(screen_x, screen_y)
    if settle and float(settle) > 0:
        time.sleep(float(settle))
    return f"Moved: {debug}"


def desktop_move(x: int, y: int, screenshot_id: Optional[int] = None, duration: float = 0.0, settle: float = 0.05) -> str:
    """Move the cursor to a desktop screenshot coordinate without clicking."""
    screen_x, screen_y, debug = _desktop_point_to_screen(x, y, screenshot_id)
    result = _move_absolute_screen(screen_x, screen_y, duration=duration, settle=settle)
    if result.get("ok") and result.get("helper"):
        helper_label = "elevated helper" if result.get("helper_elevated") else "helper"
        return f"Desktop moved via {helper_label}: {debug}"
    if result.get("ok"):
        return f"Desktop moved: {debug}"
    return _elevated_helper_required_message(result) if result.get("error") == "elevated_helper_required" else f"Error: {result.get('error') or result}"


def desktop_click(x: int, y: int, button: str = "left", clicks: int = 1, screenshot_id: Optional[int] = None) -> str:
    screen_x, screen_y, debug = _desktop_point_to_screen(x, y, screenshot_id)
    helper_ready, helper_elevated, point_hwnd, boundary_result = _helper_route_for_screen_point(screen_x, screen_y, "/click")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        result = _helper_post("/click", {"x": screen_x, "y": screen_y, "button": button, "clicks": clicks, "absolute": True}, elevated=helper_elevated)
        if _helper_ok(result):
            helper_label = "elevated helper" if helper_elevated else "helper"
            return f"Desktop clicked via {helper_label} ({button} x{clicks}) at screen({screen_x},{screen_y})"
    _mouse_click_screen(screen_x, screen_y, button=button, clicks=clicks)
    return f"Desktop clicked ({button} x{clicks}): {debug}"


def desktop_scroll(x: int, y: int, scroll_y: int, screenshot_id: Optional[int] = None) -> str:
    screen_x, screen_y, debug = _desktop_point_to_screen(x, y, screenshot_id)
    helper_ready, helper_elevated, point_hwnd, boundary_result = _helper_route_for_screen_point(screen_x, screen_y, "/scroll")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        result = _helper_post("/scroll", {"x": screen_x, "y": screen_y, "delta": -int(scroll_y) * WHEEL_DELTA, "clicks": abs(int(scroll_y)), "absolute": True}, elevated=helper_elevated)
        if _helper_ok(result):
            helper_label = "elevated helper" if helper_elevated else "helper"
            return f"Desktop scrolled via {helper_label} dy={scroll_y} at screen({screen_x},{screen_y})"
    _set_cursor_pos_checked(screen_x, screen_y)
    time.sleep(0.05)
    _send_mouse_input(MOUSEEVENTF_WHEEL, -int(scroll_y) * WHEEL_DELTA, label=f"desktop wheel dy={int(scroll_y)}")
    return f"Desktop scrolled dy={scroll_y}: {debug}"


def desktop_drag(start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5, screenshot_id: Optional[int] = None) -> str:
    sx, sy, start_debug = _desktop_point_to_screen(start_x, start_y, screenshot_id)
    ex, ey, end_debug = _desktop_point_to_screen(end_x, end_y, screenshot_id)
    helper_ready, helper_elevated, point_hwnd, boundary_result = _helper_route_for_screen_point(sx, sy, "/drag")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        result = _helper_post("/drag", {
            "start_x": sx,
            "start_y": sy,
            "end_x": ex,
            "end_y": ey,
            "duration": duration,
            "button": "left",
            "absolute": True,
        }, elevated=helper_elevated)
        if _helper_ok(result):
            helper_label = "elevated helper" if helper_elevated else "helper"
            return f"Desktop dragged via {helper_label} screen({sx},{sy})->({ex},{ey}) [{start_debug}; {end_debug}]"
    _set_cursor_pos_checked(sx, sy)
    time.sleep(0.05)
    pressed = False
    try:
        _send_mouse_input(MOUSEEVENTF_LEFTDOWN, label="desktop drag left down")
        pressed = True
        steps = max(int(float(duration) / 0.02), 1)
        for i in range(1, steps + 1):
            t = i / steps
            _set_cursor_pos_checked(int(sx + (ex - sx) * t), int(sy + (ey - sy) * t))
            time.sleep(float(duration) / steps)
    finally:
        if pressed:
            _send_mouse_input(MOUSEEVENTF_LEFTUP, label="desktop drag left up")
    return f"Desktop dragged screen({sx},{sy})->({ex},{ey}) [{start_debug}; {end_debug}]"



# ---------------------------------------------------------------------------

def click(
    hwnd: int | None,
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
    screenshot_id: Optional[int] = None,
) -> str:
    """Click at screenshot-pixel coordinates, scaled to real window position.
    Uses helper server for cross-process input (works with NW.js/CEF apps).
    Set clicks=2 for double-click (e.g. open file, play song)."""
    hwnd = _resolve_target(hwnd)
    try:
        button = _normalize_mouse_button(button)
    except ValueError as e:
        return f"Error: {e}"

    # Try helper server first
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/click")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        ss_info = _get_screenshot_size(screenshot_id)
        result = _helper_post("/click", {
            "hwnd": hwnd, "x": x, "y": y,
            "button": button, "clicks": clicks,
            "activate": True,
            "screenshot_width": ss_info["width"],
            "screenshot_height": ss_info["height"],
        }, elevated=helper_elevated)
        if _helper_ok(result):
            click_type = "Double-clicked" if clicks == 2 else f"Clicked(x{clicks})" if clicks > 2 else "Clicked"
            return f"{click_type} ({button}): screen({result.get('screen_x',0)},{result.get('screen_y',0)})"

    # Fallback to direct implementation
    activate_window(hwnd)
    time.sleep(0.1)
    screen_x, screen_y, debug = _scale_coords(hwnd, x, y, screenshot_id)
    _mouse_click_screen(screen_x, screen_y, button=button, clicks=clicks)

    click_type = "Double-clicked" if clicks == 2 else f"Clicked(x{clicks})" if clicks > 2 else "Clicked"
    return f"{click_type} ({button}): {debug}"



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
    """Scroll at screenshot-pixel coordinates. Positive scroll_y = scroll down, negative scroll_y = scroll up.
    Uses helper server for cross-process input (works with NW.js/CEF apps)."""
    hwnd = _resolve_target(hwnd)

    # Try helper server first
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/scroll")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        ss_info = _get_screenshot_size(screenshot_id)
        result = _helper_post("/scroll", {
            "hwnd": hwnd, "x": x, "y": y,
            "delta": -scroll_y * 120, "clicks": abs(scroll_y),
            "activate": True,
            "screenshot_width": ss_info["width"],
            "screenshot_height": ss_info["height"],
        }, elevated=helper_elevated)
        if _helper_ok(result):
            return f"Scrolled: dy={scroll_y}"

    # Fallback to direct implementation
    activate_window(hwnd)
    time.sleep(0.1)
    screen_x, screen_y, debug = _scale_coords(hwnd, x, y, screenshot_id)
    _set_cursor_pos_checked(screen_x, screen_y)
    time.sleep(0.05)
    wheel_delta = -scroll_y * WHEEL_DELTA
    _send_mouse_input(MOUSEEVENTF_WHEEL, wheel_delta, label=f"window wheel dy={int(scroll_y)}")

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
    hwnd = _resolve_target(hwnd)
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/drag")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        ss_info = _get_screenshot_size(screenshot_id)
        result = _helper_post("/drag", {
            "hwnd": hwnd,
            "start_x": start_x,
            "start_y": start_y,
            "end_x": end_x,
            "end_y": end_y,
            "duration": duration,
            "button": "left",
            "activate": True,
            "screenshot_width": ss_info["width"],
            "screenshot_height": ss_info["height"],
        }, elevated=helper_elevated)
        if _helper_ok(result):
            helper_label = "elevated helper" if helper_elevated else "helper"
            return (
                f"Dragged via {helper_label} screenshot({start_x},{start_y})->({end_x},{end_y}) "
                f"screen({result.get('screen_start_x')},{result.get('screen_start_y')})->"
                f"({result.get('screen_end_x')},{result.get('screen_end_y')})"
            )

    activate_window(hwnd)
    time.sleep(0.1)

    sx, sy, _ = _scale_coords(hwnd, start_x, start_y, screenshot_id)
    ex, ey, _ = _scale_coords(hwnd, end_x, end_y, screenshot_id)

    _set_cursor_pos_checked(sx, sy)
    time.sleep(0.05)
    pressed = False
    try:
        _send_mouse_input(MOUSEEVENTF_LEFTDOWN, label="window drag left down")
        pressed = True
        time.sleep(0.05)

        # Interpolate drag path over *duration* seconds
        steps = max(int(duration / 0.02), 1)
        for i in range(1, steps + 1):
            t = i / steps
            ix = int(sx + (ex - sx) * t)
            iy = int(sy + (ey - sy) * t)
            _set_cursor_pos_checked(ix, iy)
            time.sleep(duration / steps)
    finally:
        if pressed:
            _send_mouse_input(MOUSEEVENTF_LEFTUP, label="window drag left up")
    return (
        f"Dragged screenshot({start_x},{start_y})->({end_x},{end_y}) "
        f"screen({sx},{sy})->({ex},{ey})"
    )


# ---------------------------------------------------------------------------



desktop_hover = desktop_move
hover = move_mouse

