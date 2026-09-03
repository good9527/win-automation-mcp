"""
DPI awareness, scaling factor computations, and per-window coordinate adjustments.
"""

from __future__ import annotations

import ctypes
from typing import Any, Dict, Optional

from win_automation.core.win32_structures import user32, gdi32, shcore


def init_dpi_awareness() -> bool:
    """
    Initialize process DPI awareness.
    Attempts PerMonitorV2 (2) first, falls back to SystemAware (1), then SetProcessDPIAware.
    """
    if shcore is not None:
        try:
            shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE_V2
            return True
        except Exception:
            try:
                shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
                return True
            except Exception:
                pass

    try:
        user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


# Auto-initialize DPI awareness on import
init_dpi_awareness()


def get_dpi_for_hwnd(hwnd: int) -> int:
    """Return per-window DPI (default 96 if unavailable)."""
    try:
        if hwnd and user32.IsWindow(int(hwnd)):
            dpi = user32.GetDpiForWindow(int(hwnd))
            if dpi > 0:
                return int(dpi)
    except Exception:
        pass

    # Fallback to desktop DC DPI
    try:
        hdc = user32.GetDC(0)
        if hdc:
            try:
                # LOGPIXELSX = 88
                dpi = gdi32.GetDeviceCaps(hdc, 88)
                if dpi > 0:
                    return int(dpi)
            finally:
                user32.ReleaseDC(0, hdc)
    except Exception:
        pass

    return 96


def get_dpi_scale_for_hwnd(hwnd: int) -> float:
    """Return DPI scale factor relative to standard 96 DPI (1.0 = 100%)."""
    return get_dpi_for_hwnd(hwnd) / 96.0


def get_dpi_scale(hwnd: int) -> float:
    """Alias for get_dpi_scale_for_hwnd."""
    return get_dpi_scale_for_hwnd(hwnd)


def get_screen_scale() -> float:
    """Return primary display DPI scaling factor."""
    return get_dpi_for_hwnd(0) / 96.0


def scale_coord(val: int, factor: float) -> int:
    """Scale a coordinate by the given DPI scaling factor."""
    return int(round(val * factor))


def unscale_coord(val: int, factor: float) -> int:
    """Convert a scaled coordinate back to unscaled coordinates."""
    if factor == 0:
        return val
    return int(round(val / factor))


def scale_rect(rect: Dict[str, Any], factor: float) -> Dict[str, int]:
    """Scale a rectangle dictionary by factor."""
    left = scale_coord(rect.get("left", 0), factor)
    top = scale_coord(rect.get("top", 0), factor)
    right = scale_coord(rect.get("right", 0), factor)
    bottom = scale_coord(rect.get("bottom", 0), factor)
    width = scale_coord(rect.get("width", max(0, right - left)), factor)
    height = scale_coord(rect.get("height", max(0, bottom - top)), factor)
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": width,
        "height": height,
    }


def screen_info() -> Dict[str, Any]:
    """Return virtual desktop and primary screen metrics."""
    primary_w = int(user32.GetSystemMetrics(0))   # SM_CXSCREEN
    primary_h = int(user32.GetSystemMetrics(1))   # SM_CYSCREEN
    v_left = int(user32.GetSystemMetrics(76))     # SM_XVIRTUALSCREEN
    v_top = int(user32.GetSystemMetrics(77))      # SM_YVIRTUALSCREEN
    v_width = int(user32.GetSystemMetrics(78))    # SM_CXVIRTUALSCREEN
    v_height = int(user32.GetSystemMetrics(79))   # SM_CYVIRTUALSCREEN
    if v_width <= 0:
        v_width = primary_w
    if v_height <= 0:
        v_height = primary_h
    monitors = int(user32.GetSystemMetrics(80)) or 1  # SM_CMONITORS
    scale = get_screen_scale()
    return {
        "primary_screen": {
            "width": primary_w,
            "height": primary_h,
            "scale": scale,
        },
        "virtual_screen": {
            "left": v_left,
            "top": v_top,
            "width": v_width,
            "height": v_height,
        },
        "monitor_count": monitors,
    }

