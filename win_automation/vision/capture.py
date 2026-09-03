"""
Screen capture pipeline: DXCam DirectX accelerated capture, PrintWindow, BitBlt fallback, and multimodal observation.
"""

from __future__ import annotations

import os
import sys
import time
import json
import tempfile
import base64
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image as PILImage

from win_automation.core.types import ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.core.dpi import get_dpi_scale_for_hwnd, scale_coord, screen_info
from win_automation.core.utils import is_valid_hwnd, shorten as _shorten
from win_automation.vision.dxcam_manager import DXCamManager
from win_automation.win32.window import _window_info, activate_window, _get_window_rect
from win_automation.state.persistence import resolve_target_hwnd, next_screenshot_id, remember_screenshot, load_screenshot_meta
from win_automation.helper.client import _helper_route_for_hwnd, _helper_post, _elevated_helper_required_message, _helper_ok
from win_automation.uia.tree import build_accessibility_tree
from win_automation.uia.cache import _summarize_element

_screenshots: Dict[int, Dict[str, Any]] = {}
_last_screenshot_size: Tuple[int, int] = (1280, 834)

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

def _load_screenshot_meta(screenshot_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    return load_screenshot_meta(screenshot_id)


def _capture_dxcam_rect(
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> Optional[PILImage.Image]:
    """Capture a global desktop rect with dxcam, including multi-monitor windows."""
    try:
        import re
        import dxcam
    except Exception:
        return None

    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None

    try:
        output_info = dxcam.output_info()
        pairs = [
            (int(device_idx), int(output_idx))
            for device_idx, output_idx in re.findall(r"Device\[(\d+)\]\s+Output\[(\d+)\]", output_info)
        ]
        if not pairs:
            pairs = [(0, None)]

        canvas = PILImage.new("RGB", (width, height))
        coverage = PILImage.new("L", (width, height), 0)
        captured_any = False

        for device_idx, output_idx in pairs:
            try:
                camera = DXCamManager.get_camera(device_idx=device_idx, output_idx=output_idx)
                if camera is None:
                    continue
                output = getattr(camera, "_output", None)
                desc = getattr(output, "desc", None)
                coords = getattr(desc, "DesktopCoordinates", None)
                if coords:
                    out_left, out_top = int(coords.left), int(coords.top)
                    out_right, out_bottom = int(coords.right), int(coords.bottom)
                else:
                    out_left, out_top = 0, 0
                    out_right = int(getattr(camera, "width", 0) or 0)
                    out_bottom = int(getattr(camera, "height", 0) or 0)

                overlap_left = max(left, out_left)
                overlap_top = max(top, out_top)
                overlap_right = min(right, out_right)
                overlap_bottom = min(bottom, out_bottom)
                if overlap_right <= overlap_left or overlap_bottom <= overlap_top:
                    continue

                region = (
                    overlap_left - out_left,
                    overlap_top - out_top,
                    overlap_right - out_left,
                    overlap_bottom - out_top,
                )
                frame = camera.grab(region=region, new_frame_only=False) if hasattr(camera, "grab") else None
                if frame is None:
                    continue

                chunk = PILImage.fromarray(frame).convert("RGB")
                paste_x = overlap_left - left
                paste_y = overlap_top - top
                canvas.paste(chunk, (paste_x, paste_y))
                coverage.paste(255, (paste_x, paste_y, paste_x + chunk.width, paste_y + chunk.height))
                captured_any = True
            except Exception:
                continue

        if captured_any and coverage.getextrema() == (255, 255):
            return canvas
    except Exception:
        return None
    return None


def screenshot(
    hwnd: int,
    output_path: str,
    max_width: int = 1280,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """
    Capture a window screenshot and return structured metadata.

    Capture order in auto mode: dxcam -> PrintWindow (PW_RENDERFULLCONTENT) -> PrintWindow (0) -> BitBlt.
    The captured bitmap is down-scaled to *max_width* if wider, then saved as PNG.
    """
    global _screenshot_counter, _screenshots, _last_screenshot_size
    mode = str(capture_mode or "auto").strip().lower().replace("-", "_")
    aliases = {"desktop": "visible", "screen": "visible", "print": "printwindow", "pw": "printwindow", "pw_full": "printwindow"}
    mode = aliases.get(mode, mode)
    if mode not in ("auto", "visible", "window", "printwindow", "bitblt"):
        return {"error": f"Invalid capture_mode {capture_mode!r}. Use auto, visible, window, printwindow, or bitblt."}

    output_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

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
    img = None
    capture_method = "unknown"

    if mode in ("auto", "visible"):
        img = _capture_dxcam_rect(win_left, win_top, win_right, win_bottom)
    if img is not None:
        width = win_w
        height = win_h
        capture_method = "dxcam"

    if img is None and mode not in ("visible", "bitblt"):
        hdc_window = user32.GetDC(hwnd)
        if hdc_window:
            hdc_mem = None
            hbitmap = None
            old_bmp = None
            try:
                hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
                if hdc_mem:
                    hbitmap = gdi32.CreateCompatibleBitmap(hdc_window, log_w, log_h)
                    if hbitmap:
                        old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)
                        result = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
                        if result:
                            capture_method = "printwindow_full"
                        else:
                            result = user32.PrintWindow(hwnd, hdc_mem, 0)
                            if result:
                                capture_method = "printwindow"

                        if result:
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
            finally:
                if hdc_mem and old_bmp:
                    gdi32.SelectObject(hdc_mem, old_bmp)
                if hbitmap:
                    gdi32.DeleteObject(hbitmap)
                if hdc_mem:
                    gdi32.DeleteDC(hdc_mem)
                user32.ReleaseDC(hwnd, hdc_window)

    if img is None and mode in ("auto", "visible", "window", "bitblt"):
        fallback = _capture_bitblt_rect(win_left, win_top, win_w, win_h)
        if fallback is not None:
            img = fallback
            width = win_w
            height = win_h
            capture_method = "bitblt"

    if img is None:
        return {"error": "Failed to capture screenshot"}

    # Convert to RGB and optionally down-scale
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

    # Update global tracking state
    ss_id = _next_screenshot_id()
    _last_screenshot_size = (img.width, img.height)

    meta = {
        "id": ss_id,
        "path": output_path,
        "width": img.width,
        "height": img.height,
        "dpi_scale": dpi_scale,
        "capture_method": capture_method,
        "capture_mode": mode,
        "window_hwnd": hwnd,
        "created_at": time.time(),
    }
    _screenshots[ss_id] = meta
    _remember_screenshot(meta)
    return meta


def capture_image(hwnd: int, max_width: int = 1280, capture_mode: str = "auto") -> Tuple[PILImage.Image, Dict[str, Any]]:
    """Capture a window to a temporary JPEG and return the PIL image plus metadata."""
    output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"capture-{int(time.time() * 1000)}.jpg")
    meta = screenshot(hwnd, output_path, max_width=max_width, capture_mode=capture_mode)
    if "error" in meta:
        raise RuntimeError(meta["error"])
    return PILImage.open(output_path).convert("RGB"), meta


def _capture_bitblt_rect(left: int, top: int, width: int, height: int) -> Optional[PILImage.Image]:
    """Capture a physical desktop rectangle with BitBlt."""
    if width <= 0 or height <= 0:
        return None
    hdc_screen = user32.GetDC(0)
    if not hdc_screen:
        return None
    hdc_mem = None
    hbitmap = None
    old_bmp = None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        if not hdc_mem:
            return None
        hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        if not hbitmap:
            return None
        old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)
        ok = bool(gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, SRCCOPY))
        if not ok:
            return None
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)
        got = gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)
        if not got:
            return None
        return PILImage.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        if hdc_mem and old_bmp:
            gdi32.SelectObject(hdc_mem, old_bmp)
        if hbitmap:
            gdi32.DeleteObject(hbitmap)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)


def desktop_screenshot(output_path: Optional[str] = None, max_width: int = 1600) -> Dict[str, Any]:
    """Capture the full virtual desktop and persist screenshot metadata."""
    global _last_screenshot_size

    if not output_path:
        output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"desktop-{int(time.time() * 1000)}.jpg")
    output_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    virtual = screen_info()["virtual_screen"]
    left = int(virtual["left"])
    top = int(virtual["top"])
    width = int(virtual["width"])
    height = int(virtual["height"])
    if width <= 0 or height <= 0:
        return {"error": f"Invalid virtual desktop dimensions: {width}x{height}"}

    img = _capture_dxcam_rect(left, top, left + width, top + height)
    capture_method = "dxcam"
    if img is None:
        img = _capture_bitblt_rect(left, top, width, height)
        capture_method = "bitblt"
    if img is None:
        return {"error": "Failed to capture desktop screenshot"}

    img = img.convert("RGB")
    scale = 1.0
    if img.width > max_width:
        scale = max_width / img.width
        img = img.resize((max_width, int(img.height * scale)), PILImage.LANCZOS)

    ext = os.path.splitext(output_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        img.save(output_path, "JPEG", quality=85)
    else:
        img.save(output_path, "PNG", optimize=True)

    ss_id = _next_screenshot_id()
    _last_screenshot_size = (img.width, img.height)
    meta = {
        "id": ss_id,
        "path": output_path,
        "width": img.width,
        "height": img.height,
        "capture_method": capture_method,
        "window_hwnd": 0,
        "desktop": True,
        "virtual_screen": virtual,
        "scale": scale,
        "created_at": time.time(),
    }
    _screenshots[ss_id] = meta
    _remember_screenshot(meta)
    return meta


def capture_desktop_image(max_width: int = 1600) -> Tuple[PILImage.Image, Dict[str, Any]]:
    output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"desktop-{int(time.time() * 1000)}.jpg")
    meta = desktop_screenshot(output_path, max_width=max_width)
    if "error" in meta:
        raise RuntimeError(meta["error"])
    return PILImage.open(output_path).convert("RGB"), meta


def _desktop_point_to_screen(x: int, y: int, screenshot_id: Optional[int] = None) -> Tuple[int, int, str]:
    meta = _load_screenshot_meta(screenshot_id) if screenshot_id is not None else _load_screenshot_meta()
    if not meta or not meta.get("desktop"):
        img, meta = capture_desktop_image()
    virtual = meta.get("virtual_screen") or screen_info()["virtual_screen"]
    ss_w = int(meta.get("width") or virtual.get("width") or 1)
    ss_h = int(meta.get("height") or virtual.get("height") or 1)
    left = int(virtual.get("left") or 0)
    top = int(virtual.get("top") or 0)
    virt_w = int(virtual.get("width") or ss_w)
    virt_h = int(virtual.get("height") or ss_h)
    screen_x = int(round(left + (int(x) * virt_w / max(ss_w, 1))))
    screen_y = int(round(top + (int(y) * virt_h / max(ss_h, 1))))
    return screen_x, screen_y, f"desktop-screenshot({x},{y}) -> screen({screen_x},{screen_y}) [ss {ss_w}x{ss_h}, virtual {left},{top},{virt_w}x{virt_h}]"


def desktop_pixel(x: int, y: int, screenshot_id: Optional[int] = None) -> Dict[str, Any]:
    meta = _load_screenshot_meta(screenshot_id) if screenshot_id is not None else _load_screenshot_meta()
    if not meta or not meta.get("desktop") or not os.path.exists(meta.get("path", "")):
        img, meta = capture_desktop_image()
    else:
        img = PILImage.open(meta["path"]).convert("RGB")
    result = _pixel_from_image(img, int(x), int(y))
    if "error" in result:
        return result
    result["screenshot"] = meta
    return result


def desktop_point(x: int, y: int, screenshot_id: Optional[int] = None) -> Dict[str, Any]:
    screen_x, screen_y, debug = _desktop_point_to_screen(x, y, screenshot_id)
    meta = _load_screenshot_meta(screenshot_id) if screenshot_id is not None else _load_screenshot_meta()
    return {
        "ok": True,
        "x": x,
        "y": y,
        "screen_x": screen_x,
        "screen_y": screen_y,
        "debug": debug,
        "screenshot": meta,
    }





def observe(
    hwnd: Optional[int] = None,
    include_screenshot: bool = True,
    include_accessibility: bool = True,
    include_ocr: bool = False,
    ocr_on_accessibility_error: bool = True,
    ocr_engine: str = "auto",
    ocr_lang: str = "eng+chi_sim",
    max_width: int = 1280,
    max_depth: int = 10,
    max_elements: int = 500,
    view: str = "raw",
    output: Optional[str] = None,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Capture a unified point-in-time view of a target window."""
    hwnd = _resolve_target(hwnd)
    try:
        window_info = _window_info(hwnd) if hwnd else None
    except Exception:
        window_info = None
    result: Dict[str, Any] = {"hwnd": hwnd, "window": window_info}

    screenshot_meta: Optional[Dict[str, Any]] = None
    if include_screenshot:
        if output is None:
            output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
            os.makedirs(output_dir, exist_ok=True)
            output = os.path.join(output_dir, f"observe-{int(time.time() * 1000)}.jpg")
        screenshot_meta = screenshot(hwnd, output, max_width=max_width, capture_mode=capture_mode)
        result["screenshot"] = screenshot_meta

    if include_accessibility:
        accessibility = build_accessibility_tree(hwnd, max_depth=max_depth, max_elements=max_elements, view=view)
        if "elements" in accessibility:
            accessibility = dict(accessibility)
            elements = accessibility.get("elements", [])
            accessibility["elements_preview"] = [_summarize_element(element) for element in elements[:80]]
            accessibility["element_count"] = len(elements)
            focused = accessibility.get("focused")
            if isinstance(focused, dict):
                focused = dict(focused)
                focused["name"] = _shorten(focused.get("name", ""), 160)
                focused["selected_text"] = _shorten(focused.get("selected_text", ""), 240)
                accessibility["focused"] = focused
            tree_lines = str(accessibility.get("tree", "")).splitlines()
            accessibility["tree_preview"] = "\n".join(_shorten(line, 240) for line in tree_lines[:120])
            accessibility.pop("tree", None)
            accessibility.pop("elements", None)
        result["accessibility"] = accessibility

    accessibility_failed = isinstance(result.get("accessibility"), dict) and bool(result["accessibility"].get("error"))
    should_run_ocr = include_ocr or (ocr_on_accessibility_error and include_accessibility and accessibility_failed)
    if should_run_ocr:
        if not include_ocr and accessibility_failed:
            activate_window(hwnd)
            screenshot_meta = None
        sid = screenshot_meta.get("id") if screenshot_meta and "error" not in screenshot_meta else None
        from win_automation.ocr.finder import ocr as _ocr_func
        result["ocr"] = _ocr_func(hwnd, lang=ocr_lang, screenshot_id=sid, engine=ocr_engine, capture_mode=capture_mode)
        if not include_ocr:
            result["ocr"]["triggered_by"] = "accessibility_error"

    return result


# ---------------------------------------------------------------------------
# Click (items 1, 3 — scaling, screenshot_id)
# ---------------------------------------------------------------------------

observe_window = observe



capture_window_screenshot = screenshot
capture_desktop_screenshot = desktop_screenshot
_capture_window_screenshot = screenshot
_capture_desktop_screenshot = desktop_screenshot



def screenshot_b64(hwnd: Optional[int] = None, max_width: int = 1280) -> Dict[str, Any]:
    hwnd = _resolve_target(hwnd)
    meta = screenshot(hwnd, max_width=max_width)
    if isinstance(meta, dict) and 'path' in meta and os.path.exists(meta['path']):
        with open(meta['path'], 'rb') as f:
            data = f.read()
        return {
            'ok': True,
            'hwnd': hwnd,
            'base64': base64.b64encode(data).decode('ascii'),
            'width': meta.get('width'),
            'height': meta.get('height'),
        }
    return {'ok': False, 'error': meta.get('error', 'screenshot failed') if isinstance(meta, dict) else 'screenshot failed', 'hwnd': hwnd}


def get_window_state(
    hwnd: Optional[int] = None,
    include_screenshot: bool = True,
    include_accessibility: bool = False,
    max_screenshot_width: int = 1280,
    accessibility_view: str = "raw",
    capture_mode: str = "auto",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Capture the current state of a window (screenshot + optional accessibility tree)."""
    return observe(
        hwnd=hwnd,
        include_screenshot=include_screenshot,
        include_accessibility=include_accessibility,
        max_width=max_screenshot_width,
        view=accessibility_view,
        capture_mode=capture_mode,
    )


