from __future__ import annotations
from win_automation.vision.capture import desktop_point, desktop_pixel
"""
Pixel color sampling, Euclidean color distance matching, and pixel polling waits.
"""


import os
import sys
import time
import math
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.core.utils import parse_rgb_color, rgb_distance, is_valid_hwnd
from win_automation.win32.window import _window_info, activate_window, _get_window_rect
from win_automation.vision.capture import _scale_coords, _get_screenshot_size, _load_screenshot_meta
from win_automation.state.persistence import resolve_target_hwnd
from win_automation.helper.client import _helper_route_for_hwnd, _helper_post, _elevated_helper_required_message, _helper_ok

def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)



def _load_or_capture_desktop_image(screenshot_id: Optional[int] = None, max_width: int = 1600) -> Tuple[PILImage.Image, Dict[str, Any]]:
    meta = _load_screenshot_meta(screenshot_id) if screenshot_id is not None else _load_screenshot_meta()
    if meta and meta.get("desktop") and os.path.exists(str(meta.get("path", ""))):
        return PILImage.open(meta["path"]).convert("RGB"), meta
    return capture_desktop_image(max_width=max_width)


def pixel(hwnd: int, x: int, y: int, screenshot_id: Optional[int] = None) -> Dict[str, Any]:
    """Read one RGB pixel from a persisted screenshot or a fresh capture."""
    meta = _load_screenshot_meta(screenshot_id)
    if meta and os.path.exists(meta.get("path", "")):
        img = PILImage.open(meta["path"]).convert("RGB")
    else:
        img, meta = capture_image(hwnd)
    result = _pixel_from_image(img, int(x), int(y))
    if "error" in result:
        return result
    result["screenshot"] = meta
    return result


def _pixel_from_image(img: PILImage.Image, x: int, y: int) -> Dict[str, Any]:
    if x < 0 or y < 0 or x >= img.width or y >= img.height:
        return {"error": "coordinates_out_of_bounds", "width": img.width, "height": img.height}
    rgb = img.getpixel((x, y))
    return {
        "x": x,
        "y": y,
        "rgb": {"r": rgb[0], "g": rgb[1], "b": rgb[2]},
        "hex": f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}",
    }


def _parse_rgb_color(value: Any) -> Tuple[int, int, int]:
    if isinstance(value, dict):
        if all(key in value for key in ("r", "g", "b")):
            return (
                max(0, min(255, int(round(float(value["r"]))))),
                max(0, min(255, int(round(float(value["g"]))))),
                max(0, min(255, int(round(float(value["b"]))))),
            )
        if "rgb" in value:
            return _parse_rgb_color(value.get("rgb"))
        if "hex" in value:
            return _parse_rgb_color(value.get("hex"))
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (
            max(0, min(255, int(round(float(value[0]))))),
            max(0, min(255, int(round(float(value[1]))))),
            max(0, min(255, int(round(float(value[2]))))),
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
            max(0, min(255, int(round(float(parts[0]))))),
            max(0, min(255, int(round(float(parts[1]))))),
            max(0, min(255, int(round(float(parts[2]))))),
        )
    raise ValueError("color must be #rrggbb, rgb dict/list, or 'r,g,b'")


def _rgb_distance(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> float:
    return math.sqrt(sum((int(a[i]) - int(b[i])) ** 2 for i in range(3)))


def _pixel_match_result(pixel_result: Dict[str, Any], expected_color: Any, tolerance: float = 0.0, mode: str = "equals") -> Dict[str, Any]:
    if "error" in pixel_result:
        return dict(pixel_result)
    expected = _parse_rgb_color(expected_color)
    actual_rgb = pixel_result.get("rgb") or {}
    actual = (
        int(actual_rgb.get("r", 0)),
        int(actual_rgb.get("g", 0)),
        int(actual_rgb.get("b", 0)),
    )
    distance = _rgb_distance(actual, expected)
    normalized_mode = str(mode or "equals").strip().lower().replace("-", "_")
    within = distance <= max(float(tolerance or 0.0), 0.0)
    matched = not within if normalized_mode in ("not", "not_equals", "not_equal", "different", "absent", "gone") else within
    result = dict(pixel_result)
    result.update({
        "ok": bool(matched),
        "matched": bool(matched),
        "mode": normalized_mode,
        "expected_rgb": {"r": expected[0], "g": expected[1], "b": expected[2]},
        "expected_hex": f"#{expected[0]:02x}{expected[1]:02x}{expected[2]:02x}",
        "distance": round(distance, 3),
        "tolerance": max(float(tolerance or 0.0), 0.0),
    })
    return result


def _wait_for_pixel_match_result(
    fetch_pixel_result: Any,
    expected_color: Any,
    tolerance: float = 0.0,
    timeout: float = 10.0,
    interval: float = 0.25,
    mode: str = "equals",
) -> Dict[str, Any]:
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    attempts = 0
    last_result: Dict[str, Any] = {}
    while True:
        attempts += 1
        try:
            result = _pixel_match_result(fetch_pixel_result(), expected_color, tolerance=tolerance, mode=mode)
        except Exception as e:
            result = {"ok": False, "matched": False, "error": str(e)}
        last_result = result
        if result.get("matched"):
            result["ok"] = True
            result["attempts"] = attempts
            result["elapsed"] = round(time.time() - start, 3)
            result["timeout"] = timeout
            result["interval"] = interval
            return result
        if "error" in result and result.get("error") not in ("coordinates_out_of_bounds",):
            result["ok"] = False
            result["attempts"] = attempts
            result["elapsed"] = round(time.time() - start, 3)
            return result
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))
    return {
        "ok": False,
        "matched": False,
        "error": "timeout",
        "attempts": attempts,
        "elapsed": round(time.time() - start, 3),
        "timeout": timeout,
        "interval": interval,
        "last_result": last_result,
    }


def pixel_wait(
    hwnd: int,
    x: int,
    y: int,
    color: Any,
    tolerance: float = 0.0,
    timeout: float = 10.0,
    interval: float = 0.25,
    mode: str = "equals",
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Poll fresh window screenshots until a pixel matches or stops matching a color."""
    return _wait_for_pixel_match_result(
        lambda: _pixel_from_image(capture_image(hwnd, capture_mode=capture_mode)[0], int(x), int(y)),
        color,
        tolerance=tolerance,
        timeout=timeout,
        interval=interval,
        mode=mode,
    )


def desktop_pixel_wait(
    x: int,
    y: int,
    color: Any,
    tolerance: float = 0.0,
    timeout: float = 10.0,
    interval: float = 0.25,
    mode: str = "equals",
    max_width: int = 1600,
) -> Dict[str, Any]:
    """Poll fresh desktop screenshots until a pixel matches or stops matching a color."""
    return _wait_for_pixel_match_result(
        lambda: _pixel_from_image(capture_desktop_image(max_width=max_width)[0], int(x), int(y)),
        color,
        tolerance=tolerance,
        timeout=timeout,
        interval=interval,
        mode=mode,
    )


def _normalize_region(region: Optional[Any]) -> Optional[Dict[str, int]]:
    if region is None or region == "":
        return None
    if isinstance(region, str):
        parts = [part.strip() for part in region.replace(";", ",").split(",") if part.strip()]
        if len(parts) != 4:
            raise ValueError("region must be left,top,right,bottom")
        region = [int(round(float(part))) for part in parts]
    if isinstance(region, dict):
        if all(key in region for key in ("left", "top", "right", "bottom")):
            left = int(round(float(region["left"])))
            top = int(round(float(region["top"])))
            right = int(round(float(region["right"])))
            bottom = int(round(float(region["bottom"])))
        elif all(key in region for key in ("x", "y", "width", "height")):
            left = int(round(float(region["x"])))
            top = int(round(float(region["y"])))
            right = left + int(round(float(region["width"])))
            bottom = top + int(round(float(region["height"])))
        else:
            raise ValueError("region dict needs left/top/right/bottom or x/y/width/height")
    elif isinstance(region, (list, tuple)) and len(region) == 4:
        left, top, right, bottom = [int(round(float(value))) for value in region]
    else:
        raise ValueError("region must be a dict, list, tuple, or left,top,right,bottom string")
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": right - left,
        "height": bottom - top,
        "center_x": left + (right - left) // 2,
        "center_y": top + (bottom - top) // 2,
    }


def _crop_image_region(img: PILImage.Image, region: Optional[Any]) -> Tuple[PILImage.Image, Optional[Dict[str, int]]]:
    normalized_region = _normalize_region(region)
    if not normalized_region:
        return img.convert("RGB"), None
    left = max(0, min(img.width, normalized_region["left"]))
    top = max(0, min(img.height, normalized_region["top"]))
    right = max(0, min(img.width, normalized_region["right"]))
    bottom = max(0, min(img.height, normalized_region["bottom"]))
    if right <= left or bottom <= top:
        raise ValueError("empty_region")
    cropped = img.crop((left, top, right, bottom)).convert("RGB")
    return cropped, {
        **normalized_region,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": right - left,
        "height": bottom - top,
        "center_x": left + (right - left) // 2,
        "center_y": top + (bottom - top) // 2,
    }


def _prepare_stability_image(img: PILImage.Image, region: Optional[Any] = None, max_width: int = 320) -> Tuple[PILImage.Image, Optional[Dict[str, int]], float]:
    prepared, normalized_region = _crop_image_region(img, region)
    scale = 1.0
    max_width_value = int(max_width or 0)
    if max_width_value > 0 and prepared.width > max_width_value:
        scale = max_width_value / max(prepared.width, 1)
        prepared = prepared.resize((max_width_value, max(1, int(round(prepared.height * scale)))), PILImage.BILINEAR)
    return prepared.convert("RGB"), normalized_region, scale


def _image_diff_ratio(a: PILImage.Image, b: PILImage.Image, pixel_threshold: float = 8.0) -> Dict[str, Any]:
    if a.size != b.size:
        b = b.resize(a.size, PILImage.BILINEAR)
    left = a.convert("RGB")
    right = b.convert("RGB")
    threshold = max(float(pixel_threshold or 0.0), 0.0)
    total = max(left.width * left.height, 1)
    changed = 0
    max_distance = 0.0
    sum_distance = 0.0
    for px_a, px_b in zip(left.getdata(), right.getdata()):
        distance = math.sqrt(
            (int(px_a[0]) - int(px_b[0])) ** 2
            + (int(px_a[1]) - int(px_b[1])) ** 2
            + (int(px_a[2]) - int(px_b[2])) ** 2
        )
        if distance > threshold:
            changed += 1
        if distance > max_distance:
            max_distance = distance
        sum_distance += distance
    return {
        "changed_pixels": changed,
        "total_pixels": total,
        "ratio": changed / total,
        "max_distance": round(max_distance, 3),
        "mean_distance": round(sum_distance / total, 3),
        "pixel_threshold": threshold,
    }


def _wait_for_visual_stability(
    fetch_image: Any,
    timeout: float = 5.0,
    interval: float = 0.25,
    stable_ticks: int = 2,
    difference_threshold: float = 0.003,
    pixel_threshold: float = 8.0,
    region: Optional[Any] = None,
    max_width: int = 320,
) -> Dict[str, Any]:
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    attempts = 0
    consecutive_stable = 0
    previous: Optional[PILImage.Image] = None
    last_meta: Dict[str, Any] = {}
    last_diff: Dict[str, Any] = {}
    max_diff_ratio = 0.0
    normalized_region: Optional[Dict[str, int]] = None
    scale = 1.0
    required_ticks = max(int(stable_ticks or 1), 1)
    diff_threshold = max(float(difference_threshold or 0.0), 0.0)

    while True:
        attempts += 1
        try:
            fetched = fetch_image()
            if isinstance(fetched, tuple):
                img, meta = fetched[0], fetched[1] if len(fetched) > 1 and isinstance(fetched[1], dict) else {}
            else:
                img, meta = fetched, {}
            current, normalized_region, scale = _prepare_stability_image(img, region=region, max_width=max_width)
            last_meta = dict(meta or {})
        except Exception as e:
            elapsed = round(time.time() - start, 3)
            return {
                "ok": False,
                "stable": False,
                "error": str(e),
                "attempts": attempts,
                "elapsed": elapsed,
                "timeout": timeout,
                "interval": interval,
            }

        if previous is not None:
            last_diff = _image_diff_ratio(previous, current, pixel_threshold=pixel_threshold)
            ratio = float(last_diff.get("ratio") or 0.0)
            max_diff_ratio = max(max_diff_ratio, ratio)
            if ratio <= diff_threshold:
                consecutive_stable += 1
            else:
                consecutive_stable = 0
            if consecutive_stable >= required_ticks:
                elapsed = round(time.time() - start, 3)
                return {
                    "ok": True,
                    "stable": True,
                    "attempts": attempts,
                    "elapsed": elapsed,
                    "timeout": timeout,
                    "interval": interval,
                    "stable_ticks": consecutive_stable,
                    "required_stable_ticks": required_ticks,
                    "last_diff_ratio": round(ratio, 6),
                    "max_diff_ratio": round(max_diff_ratio, 6),
                    "last_diff": last_diff,
                    "thresholds": {
                        "difference_threshold": diff_threshold,
                        "pixel_threshold": max(float(pixel_threshold or 0.0), 0.0),
                    },
                    "analysis": {
                        "width": current.width,
                        "height": current.height,
                        "scale": round(scale, 6),
                        "region": normalized_region,
                    },
                    "screenshot": last_meta,
                }
        previous = current
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))

    return {
        "ok": False,
        "stable": False,
        "error": "timeout",
        "attempts": attempts,
        "elapsed": round(time.time() - start, 3),
        "timeout": timeout,
        "interval": interval,
        "stable_ticks": consecutive_stable,
        "required_stable_ticks": required_ticks,
        "last_diff_ratio": round(float(last_diff.get("ratio") or 0.0), 6) if last_diff else None,
        "max_diff_ratio": round(max_diff_ratio, 6),
        "last_diff": last_diff,
        "thresholds": {
            "difference_threshold": diff_threshold,
            "pixel_threshold": max(float(pixel_threshold or 0.0), 0.0),
        },
        "analysis": {
            "scale": round(scale, 6),
            "region": normalized_region,
        },
        "screenshot": last_meta,
    }


def visual_stable_wait(
    hwnd: int,
    timeout: float = 5.0,
    interval: float = 0.25,
    stable_ticks: int = 2,
    difference_threshold: float = 0.003,
    pixel_threshold: float = 8.0,
    region: Optional[Any] = None,
    max_width: int = 1280,
    comparison_max_width: int = 320,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Poll fresh window screenshots until consecutive frames are visually stable."""
    return _wait_for_visual_stability(
        lambda: capture_image(hwnd, max_width=max_width, capture_mode=capture_mode),
        timeout=timeout,
        interval=interval,
        stable_ticks=stable_ticks,
        difference_threshold=difference_threshold,
        pixel_threshold=pixel_threshold,
        region=region,
        max_width=comparison_max_width,
    )
