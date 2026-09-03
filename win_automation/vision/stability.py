"""
Visual frame difference stability polling.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image as PILImage

from win_automation.core.types import ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.vision.capture import capture_window_screenshot, capture_desktop_screenshot
from win_automation.vision.pixel import _prepare_stability_image, _image_diff_ratio
from win_automation.state.persistence import resolve_target_hwnd


def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)

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


def desktop_visual_stable_wait(
    timeout: float = 5.0,
    interval: float = 0.25,
    stable_ticks: int = 2,
    difference_threshold: float = 0.003,
    pixel_threshold: float = 8.0,
    region: Optional[Any] = None,
    max_width: int = 1600,
    comparison_max_width: int = 320,
) -> Dict[str, Any]:
    """Poll fresh desktop screenshots until consecutive frames are visually stable."""
    return _wait_for_visual_stability(
        lambda: capture_desktop_image(max_width=max_width),
        timeout=timeout,
        interval=interval,
        stable_ticks=stable_ticks,
        difference_threshold=difference_threshold,
        pixel_threshold=pixel_threshold,
        region=region,
        max_width=comparison_max_width,
    )


