"""
Template image matching across window client area and virtual desktop.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image as PILImage

from win_automation.core.types import ActionTimeoutError
from win_automation.vision.capture import capture_window_screenshot, capture_desktop_screenshot, _scale_coords
from win_automation.input.mouse import click, desktop_click
from win_automation.state.persistence import resolve_target_hwnd

def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)

def _normalize_region(region: Optional[Any]) -> Optional[Dict[str, int]]:
    if not region:
        return None
    if isinstance(region, dict):
        return {
            "left": int(region.get("left", 0)),
            "top": int(region.get("top", 0)),
            "width": int(region.get("width", 0)),
            "height": int(region.get("height", 0)),
        }
    return None

def _image_scale_values(scale_min: float, scale_max: float, scale_step: float) -> List[float]:
    lo = float(scale_min or 1.0)
    hi = float(scale_max or lo)
    step = float(scale_step or 0.0)
    if lo <= 0 or hi <= 0:
        raise ValueError("scale values must be positive")
    if hi < lo:
        lo, hi = hi, lo
    if step <= 0 or abs(hi - lo) < 1e-9:
        return [round(lo, 4)]
    values: List[float] = []
    current = lo
    while current <= hi + 1e-9:
        values.append(round(current, 4))
        current += step
    if values[-1] != round(hi, 4):
        values.append(round(hi, 4))
    return values


def _match_template_image(
    haystack: PILImage.Image,
    needle: PILImage.Image,
    confidence: float = 0.85,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
) -> Dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {"error": "opencv_unavailable", "message": "Install opencv-python and numpy to use image matching"}

    normalized_region = _normalize_region(region)
    search = haystack
    offset_x = 0
    offset_y = 0
    if normalized_region:
        left = max(0, min(haystack.width, normalized_region["left"]))
        top = max(0, min(haystack.height, normalized_region["top"]))
        right = max(0, min(haystack.width, normalized_region["right"]))
        bottom = max(0, min(haystack.height, normalized_region["bottom"]))
        if right <= left or bottom <= top:
            return {"found": False, "error": "empty_region", "region": normalized_region, "screenshot": {"width": haystack.width, "height": haystack.height}}
        search = haystack.crop((left, top, right, bottom))
        offset_x = left
        offset_y = top

    scales = _image_scale_values(scale_min, scale_max, scale_step)
    hay = cv2.cvtColor(np.array(search.convert("RGB")), cv2.COLOR_RGB2BGR)
    best: Optional[Dict[str, Any]] = None
    skipped: List[Dict[str, Any]] = []
    for scale in scales:
        width = max(1, int(round(needle.width * scale)))
        height = max(1, int(round(needle.height * scale)))
        if width > search.width or height > search.height:
            skipped.append({"scale": scale, "width": width, "height": height, "reason": "template_larger_than_search_region"})
            continue
        resized = needle.convert("RGB") if abs(scale - 1.0) < 1e-9 else needle.convert("RGB").resize((width, height), PILImage.LANCZOS)
        ned = cv2.cvtColor(np.array(resized), cv2.COLOR_RGB2BGR)
        result = cv2.matchTemplate(hay, ned, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        x, y = max_loc
        candidate = {
            "left": int(offset_x + x),
            "top": int(offset_y + y),
            "width": int(width),
            "height": int(height),
            "right": int(offset_x + x + width),
            "bottom": int(offset_y + y + height),
            "center_x": int(offset_x + x + width / 2),
            "center_y": int(offset_y + y + height / 2),
            "confidence": float(max_val),
            "scale": float(scale),
        }
        if best is None or candidate["confidence"] > best["confidence"]:
            best = candidate

    if best is None:
        return {
            "found": False,
            "error": "template_larger_than_screenshot",
            "screenshot": {"width": haystack.width, "height": haystack.height},
            "search_region": normalized_region,
            "template": {"width": needle.width, "height": needle.height},
            "scales": scales,
            "skipped": skipped,
        }
    found = best["confidence"] >= confidence
    return {
        "found": found,
        "match": best if found else None,
        "best_match": best,
        "threshold": confidence,
        "screenshot": {"width": haystack.width, "height": haystack.height},
        "search_region": normalized_region,
        "template": {"width": needle.width, "height": needle.height},
        "scales": scales,
    }


def locate_image(
    hwnd: int,
    template_path: str,
    confidence: float = 0.85,
    max_width: int = 1280,
    screenshot_id: Optional[int] = None,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Locate a template image inside a window screenshot using OpenCV template matching."""
    if not os.path.exists(template_path):
        return {"error": "template_not_found", "path": template_path}

    meta = _load_screenshot_meta(screenshot_id)
    if meta and os.path.exists(meta.get("path", "")):
        haystack = PILImage.open(meta["path"]).convert("RGB")
    else:
        haystack, meta = capture_image(hwnd, max_width=max_width, capture_mode=capture_mode)
    needle = PILImage.open(template_path).convert("RGB")
    result = _match_template_image(
        haystack,
        needle,
        confidence=confidence,
        region=region,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_step=scale_step,
    )
    result["screenshot"] = {**(result.get("screenshot") or {}), **meta}
    return result


def desktop_locate_image(
    template_path: str,
    confidence: float = 0.85,
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
) -> Dict[str, Any]:
    """Locate a template image inside a full virtual desktop screenshot."""
    if not os.path.exists(template_path):
        return {"error": "template_not_found", "path": template_path}
    haystack, meta = _load_or_capture_desktop_image(screenshot_id=screenshot_id, max_width=max_width)
    needle = PILImage.open(template_path).convert("RGB")
    result = _match_template_image(
        haystack,
        needle,
        confidence=confidence,
        region=region,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_step=scale_step,
    )
    result["screenshot"] = {**(result.get("screenshot") or {}), **meta}
    if result.get("match"):
        match = dict(result["match"])
        screen_x, screen_y, debug = _desktop_point_to_screen(match["center_x"], match["center_y"], int(meta["id"]))
        match["screen_x"] = screen_x
        match["screen_y"] = screen_y
        match["debug"] = debug
        result["match"] = match
    if result.get("best_match"):
        best = dict(result["best_match"])
        screen_x, screen_y, debug = _desktop_point_to_screen(best["center_x"], best["center_y"], int(meta["id"]))
        best["screen_x"] = screen_x
        best["screen_y"] = screen_y
        best["debug"] = debug
        result["best_match"] = best
    return result


def _wait_for_image_match_result(
    fetch_match_result: Any,
    timeout: float = 10.0,
    interval: float = 0.5,
) -> Dict[str, Any]:
    """Poll an image-match callback until it returns a found match."""
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    attempts = 0
    last_result: Dict[str, Any] = {}
    while True:
        attempts += 1
        result = fetch_match_result()
        last_result = result if isinstance(result, dict) else {"error": "match_failed", "result": result}
        if isinstance(result, dict) and result.get("found"):
            result["ok"] = True
            result["attempts"] = attempts
            result["elapsed"] = round(time.time() - start, 3)
            result["timeout"] = timeout
            result["interval"] = interval
            return result
        if isinstance(result, dict) and "error" in result and result.get("error") not in ("template_larger_than_screenshot", "empty_region"):
            result["ok"] = False
            result["attempts"] = attempts
            result["elapsed"] = round(time.time() - start, 3)
            return result
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))

    return {
        "ok": False,
        "found": False,
        "error": "timeout",
        "attempts": attempts,
        "elapsed": round(time.time() - start, 3),
        "timeout": timeout,
        "interval": interval,
        "last_result": last_result,
    }


def image_wait(
    hwnd: int,
    template_path: str,
    confidence: float = 0.85,
    max_width: int = 1280,
    timeout: float = 10.0,
    interval: float = 0.5,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Wait until a template image appears in a window screenshot."""
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    attempts = 0
    last_result: Dict[str, Any] = {}
    while True:
        attempts += 1
        result = locate_image(
            hwnd,
            template_path,
            confidence=confidence,
            max_width=max_width,
            screenshot_id=None,
            region=region,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
            capture_mode=capture_mode,
        )
        last_result = result
        if result.get("found"):
            result["ok"] = True
            result["attempts"] = attempts
            result["elapsed"] = round(time.time() - start, 3)
            result["timeout"] = timeout
            result["interval"] = interval
            return result
        if "error" in result and result.get("error") not in ("template_larger_than_screenshot", "empty_region"):
            result["ok"] = False
            result["attempts"] = attempts
            result["elapsed"] = round(time.time() - start, 3)
            return result
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))

    return {
        "ok": False,
        "found": False,
        "error": "timeout",
        "template": template_path,
        "attempts": attempts,
        "elapsed": round(time.time() - start, 3),
        "timeout": timeout,
        "interval": interval,
        "last_result": last_result,
    }


def desktop_image_wait(
    template_path: str,
    confidence: float = 0.85,
    max_width: int = 1600,
    timeout: float = 10.0,
    interval: float = 0.5,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
) -> Dict[str, Any]:
    """Wait until a template image appears in the full virtual desktop screenshot."""
    result = _wait_for_image_match_result(
        lambda: desktop_locate_image(
            template_path,
            confidence=confidence,
            max_width=max_width,
            screenshot_id=None,
            region=region,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
        ),
        timeout=timeout,
        interval=interval,
    )
    result.setdefault("template", template_path)
    return result


def image_click(
    hwnd: int,
    template_path: str,
    confidence: float = 0.85,
    max_width: int = 1280,
    screenshot_id: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
    timeout: float = 0.0,
    interval: float = 0.5,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Click the center of a template image match."""
    if timeout and timeout > 0:
        result = image_wait(
            hwnd,
            template_path,
            confidence=confidence,
            max_width=max_width,
            timeout=timeout,
            interval=interval,
            region=region,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
            capture_mode=capture_mode,
        )
    else:
        result = locate_image(
            hwnd,
            template_path,
            confidence=confidence,
            max_width=max_width,
            screenshot_id=screenshot_id,
            region=region,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
            capture_mode=capture_mode,
        )
    if not result.get("found"):
        result["ok"] = False
        return result
    match = result.get("match") or result.get("best_match") or {}
    screenshot = result.get("screenshot") or {}
    sid = screenshot_id or screenshot.get("id")
    message = click(hwnd, int(match["center_x"]), int(match["center_y"]), button=button, clicks=clicks, screenshot_id=sid)
    result["ok"] = True
    result["clicked"] = True
    result["target"] = match
    result["click"] = {"button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
    return result


def desktop_image_click(
    template_path: str,
    confidence: float = 0.85,
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
    timeout: float = 0.0,
    interval: float = 0.5,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
) -> Dict[str, Any]:
    """Click the center of a template image match on the full virtual desktop."""
    if timeout and timeout > 0:
        result = desktop_image_wait(
            template_path,
            confidence=confidence,
            max_width=max_width,
            timeout=timeout,
            interval=interval,
            region=region,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
        )
    else:
        result = desktop_locate_image(
            template_path,
            confidence=confidence,
            max_width=max_width,
            screenshot_id=screenshot_id,
            region=region,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
        )
    if not result.get("found"):
        result["ok"] = False
        return result
    match = result.get("match") or result.get("best_match") or {}
    screenshot = result.get("screenshot") or {}
    sid = screenshot_id or screenshot.get("id")
    message = desktop_click(int(match["center_x"]), int(match["center_y"]), button=button, clicks=clicks, screenshot_id=sid)
    result["ok"] = True
    result["clicked"] = True
    result["target"] = match
    result["click"] = {"button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
    return result


def image_scroll_click(
    hwnd: int,
    template_path: str,
    confidence: float = 0.85,
    max_width: int = 1280,
    button: str = "left",
    clicks: int = 1,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    max_scrolls: int = 8,
    scroll_amount: int = 5,
    scroll_x: Optional[int] = None,
    scroll_y: Optional[int] = None,
    pause: float = 0.35,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Scroll a window until a template image is visible, then click it."""
    hwnd = _resolve_target(hwnd)
    attempts: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {}
    for attempt in range(max(1, int(max_scrolls) + 1)):
        result = locate_image(
            hwnd,
            template_path,
            confidence=confidence,
            max_width=max_width,
            screenshot_id=None,
            region=region,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
            capture_mode=capture_mode,
        )
        last_result = result
        screenshot = result.get("screenshot") or {}
        attempt_info: Dict[str, Any] = {
            "attempt": attempt + 1,
            "found": bool(result.get("found")),
            "screenshot": screenshot,
            "best_match": result.get("best_match"),
        }
        attempts.append(attempt_info)
        if result.get("found"):
            match = result.get("match") or result.get("best_match") or {}
            sid = screenshot.get("id")
            message = click(hwnd, int(match["center_x"]), int(match["center_y"]), button=button, clicks=clicks, screenshot_id=sid)
            result["ok"] = True
            result["clicked"] = True
            result["target"] = match
            result["attempts"] = attempts
            result["scrolled"] = attempt
            result["click"] = {"button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
            return result
        if "error" in result and result.get("error") not in ("template_larger_than_screenshot", "empty_region"):
            result["ok"] = False
            result["attempts"] = attempts
            return result
        if attempt >= int(max_scrolls):
            break
        width = int(screenshot.get("width") or max_width or 1280)
        height = int(screenshot.get("height") or 900)
        sx = int(scroll_x) if scroll_x is not None else int(width * 0.55)
        sy = int(scroll_y) if scroll_y is not None else int(height * 0.72)
        dy = max(1, int(scroll_amount))
        message = scroll(hwnd, sx, sy, dy, screenshot_id=screenshot.get("id"))
        attempt_info["scroll"] = {"x": sx, "y": sy, "dy": dy, "message": message}
        time.sleep(max(float(pause), 0.05))
    return {
        "ok": False,
        "found": False,
        "error": "image_scroll_click_not_found",
        "template": template_path,
        "attempts": attempts,
        "last_result": last_result,
    }


def desktop_image_scroll_click(
    template_path: str,
    confidence: float = 0.85,
    max_width: int = 1600,
    button: str = "left",
    clicks: int = 1,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    max_scrolls: int = 8,
    scroll_amount: int = 5,
    scroll_x: Optional[int] = None,
    scroll_y: Optional[int] = None,
    pause: float = 0.35,
) -> Dict[str, Any]:
    """Scroll the desktop until a template image is visible, then click it."""
    attempts: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {}
    for attempt in range(max(1, int(max_scrolls) + 1)):
        result = desktop_locate_image(
            template_path,
            confidence=confidence,
            max_width=max_width,
            screenshot_id=None,
            region=region,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_step=scale_step,
        )
        last_result = result
        screenshot = result.get("screenshot") or {}
        attempt_info: Dict[str, Any] = {
            "attempt": attempt + 1,
            "found": bool(result.get("found")),
            "screenshot": screenshot,
            "best_match": result.get("best_match"),
        }
        attempts.append(attempt_info)
        if result.get("found"):
            match = result.get("match") or result.get("best_match") or {}
            sid = screenshot.get("id")
            message = desktop_click(int(match["center_x"]), int(match["center_y"]), button=button, clicks=clicks, screenshot_id=sid)
            result["ok"] = True
            result["clicked"] = True
            result["target"] = match
            result["attempts"] = attempts
            result["scrolled"] = attempt
            result["click"] = {"button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
            return result
        if "error" in result and result.get("error") not in ("template_larger_than_screenshot", "empty_region"):
            result["ok"] = False
            result["attempts"] = attempts
            return result
        if attempt >= int(max_scrolls):
            break
        width = int(screenshot.get("width") or max_width or 1280)
        height = int(screenshot.get("height") or 900)
        sx = int(scroll_x) if scroll_x is not None else int(width * 0.55)
        sy = int(scroll_y) if scroll_y is not None else int(height * 0.72)
        dy = max(1, int(scroll_amount))
        message = desktop_scroll(sx, sy, dy, screenshot_id=screenshot.get("id"))
        attempt_info["scroll"] = {"x": sx, "y": sy, "dy": dy, "message": message}
        time.sleep(max(float(pause), 0.05))
    return {
        "ok": False,
        "found": False,
        "error": "desktop_image_scroll_click_not_found",
        "template": template_path,
        "attempts": attempts,
        "last_result": last_result,
    }


def _normalize_ocr_engine(engine: Optional[str]) -> str:
    value = str(engine or "auto").strip().lower().replace("_", "-")
    aliases = {
        "win": "windows",
        "winrt": "windows",
        "windows-ocr": "windows",
        "builtin": "windows",
        "system": "windows",
        "tess": "tesseract",
    }
    value = aliases.get(value, value)
    if value not in ("auto", "tesseract", "windows"):
        raise ValueError("OCR engine must be auto, tesseract, or windows")
    return value


def _windows_ocr_language_tags(lang: str) -> List[str]:
    aliases = {
        "eng": "en-US",
        "en": "en-US",
        "en-us": "en-US",
        "chi_sim": "zh-Hans-CN",
        "chi-sim": "zh-Hans-CN",
        "chs": "zh-Hans-CN",
        "zh": "zh-Hans-CN",
        "zh-cn": "zh-Hans-CN",
        "zh-hans": "zh-Hans-CN",
        "zh-hans-cn": "zh-Hans-CN",
    }
    tags: List[str] = []
    for part in str(lang or "").replace(";", "+").replace(",", "+").split("+"):
        key = part.strip().lower().replace("_", "-")
        if not key:
            continue
        tag = aliases.get(key, part.strip())
        if tag not in tags:
            tags.append(tag)
    if not tags:
        tags.append("en-US")
    return tags


def _powershell_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_windows_ocr_on_image(image: PILImage.Image, lang: str = "eng+chi_sim") -> Dict[str, Any]:
    """Run Windows built-in WinRT OCR through PowerShell without requiring Tesseract."""
    temp_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(temp_dir, exist_ok=True)
    image_path = os.path.join(temp_dir, f"windows-ocr-{int(time.time() * 1000)}.png")
    script_path = os.path.join(temp_dir, f"windows-ocr-{int(time.time() * 1000)}.ps1")
    tags = _windows_ocr_language_tags(lang)
    image.convert("RGB").save(image_path)
    tags_literal = "@(" + ",".join(_powershell_literal(tag) for tag in tags) + ")"
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] > $null
[Windows.Storage.Streams.RandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime] > $null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] > $null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] > $null
[Windows.Globalization.Language, Windows.Foundation, ContentType=WindowsRuntime] > $null

function AwaitWinRt($Async, $ResultType) {{
    $method = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{
        $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    }})[0]
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Async))
    $task.Wait()
    $task.Result
}}

$path = {_powershell_literal(image_path)}
$requested = {tags_literal}
$available = @()
foreach ($language in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) {{
    $available += $language.LanguageTag
}}
$file = AwaitWinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = AwaitWinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = AwaitWinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = AwaitWinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$candidates = @()

foreach ($tag in $requested) {{
    if ($available -notcontains $tag) {{ continue }}
    $language = [Windows.Globalization.Language]::new($tag)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    if ($null -eq $engine) {{ continue }}
    $ocr = AwaitWinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = @()
    $words = @()
    foreach ($line in $ocr.Lines) {{
        $lines += $line.Text
        foreach ($word in $line.Words) {{
            $rect = $word.BoundingRect
            $words += [pscustomobject]@{{
                text = $word.Text
                confidence = -1
                rect = [pscustomobject]@{{
                    left = [int][math]::Round($rect.X)
                    top = [int][math]::Round($rect.Y)
                    right = [int][math]::Round($rect.X + $rect.Width)
                    bottom = [int][math]::Round($rect.Y + $rect.Height)
                    width = [int][math]::Round($rect.Width)
                    height = [int][math]::Round($rect.Height)
                    center_x = [int][math]::Round($rect.X + ($rect.Width / 2))
                    center_y = [int][math]::Round($rect.Y + ($rect.Height / 2))
                }}
            }}
        }}
    }}
    $text = ($lines -join "`n").Trim()
    $candidates += [pscustomobject]@{{
        language = $tag
        text = $text
        words = $words
        line_count = @($ocr.Lines).Count
        word_count = @($words).Count
        text_length = $text.Length
    }}
}}

if (@($candidates).Count -eq 0) {{
    [pscustomobject]@{{ ok = $false; error = 'windows_ocr_language_unavailable'; requested_languages = $requested; available_languages = $available }} | ConvertTo-Json -Depth 8 -Compress
    exit 0
}}

$best = $candidates | Sort-Object -Property text_length, word_count -Descending | Select-Object -First 1
[pscustomobject]@{{
    ok = $true
    engine = 'windows'
    language = $best.language
    requested_languages = $requested
    available_languages = $available
    text = $best.text
    words = $best.words
    candidates = $candidates | ForEach-Object {{ [pscustomobject]@{{ language = $_.language; text_length = $_.text_length; word_count = $_.word_count; line_count = $_.line_count; text = $_.text }} }}
}} | ConvertTo-Json -Depth 12 -Compress
"""
    try:
        with open(script_path, "w", encoding="utf-8-sig") as f:
            f.write(script)
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if completed.returncode != 0:
            return {
                "error": "windows_ocr_failed",
                "message": completed.stderr.strip() or completed.stdout.strip() or f"PowerShell exited {completed.returncode}",
                "engine": "windows",
            }
        try:
            result = json.loads(completed.stdout.strip())
        except Exception as e:
            return {"error": "windows_ocr_bad_output", "message": str(e), "output": completed.stdout.strip(), "engine": "windows"}
        if not result.get("ok"):
            return {"error": result.get("error", "windows_ocr_failed"), "engine": "windows", **result}
        return result
    except subprocess.TimeoutExpired:
        return {"error": "windows_ocr_timeout", "message": "Windows OCR PowerShell bridge timed out", "engine": "windows"}
    except Exception as e:
        return {"error": "windows_ocr_failed", "message": str(e), "engine": "windows"}
    finally:
        for path in (image_path, script_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def _run_tesseract_ocr_on_image(image: PILImage.Image, lang: str = "eng+chi_sim") -> Dict[str, Any]:
    try:
        import pytesseract
        from pytesseract import TesseractNotFoundError
    except ImportError:
        return {"error": "pytesseract_unavailable", "message": "Install pytesseract to use OCR", "engine": "tesseract"}

    try:
        text = pytesseract.image_to_string(image, lang=lang)
        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    except TesseractNotFoundError:
        return {
            "error": "tesseract_unavailable",
            "message": "Tesseract OCR executable is not installed or not on PATH.",
            "engine": "tesseract",
        }
    except Exception as e:
        return {"error": "ocr_failed", "message": str(e), "engine": "tesseract"}

    words = []
    for i, raw_text in enumerate(data.get("text", [])):
        word = (raw_text or "").strip()
        if not word:
            continue
        try:
            conf = float(data.get("conf", ["-1"])[i])
        except Exception:
            conf = -1.0
        left = int(data["left"][i])
        top = int(data["top"][i])
        width = int(data["width"][i])
        height = int(data["height"][i])
        words.append({
            "text": word,
            "confidence": conf,
            "rect": {
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "width": width,
                "height": height,
                "center_x": left + width // 2,
                "center_y": top + height // 2,
            },
        })
    return {"ok": True, "engine": "tesseract", "language": lang, "text": text.strip(), "words": words}


def ocr(
    hwnd: int,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    reuse_last_screenshot: bool = True,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Run OCR on a window screenshot with Tesseract or Windows built-in OCR."""
    engine = _normalize_ocr_engine(engine)
    meta = _load_screenshot_meta(screenshot_id) if (screenshot_id is not None or reuse_last_screenshot) else None
    if meta and os.path.exists(meta.get("path", "")):
        img = PILImage.open(meta["path"]).convert("RGB")
    else:
        img, meta = capture_image(hwnd, max_width=max_width, capture_mode=capture_mode)

    attempts: List[Dict[str, Any]] = []
    if engine in ("auto", "tesseract"):
        result = _run_tesseract_ocr_on_image(img, lang=lang)
        if result.get("ok") or engine == "tesseract":
            result["screenshot"] = meta
            return result
        attempts.append({"engine": "tesseract", "error": result.get("error"), "message": result.get("message")})

    if engine in ("auto", "windows"):
        result = _run_windows_ocr_on_image(img, lang=lang)
        if result.get("ok") or engine == "windows":
            result["screenshot"] = meta
            if attempts:
                result["fallback_from"] = attempts
            return result
        attempts.append({"engine": "windows", "error": result.get("error"), "message": result.get("message")})

    return {"error": "ocr_unavailable", "engine": engine, "attempts": attempts, "screenshot": meta}


def wait_image(
    template_path: str,
    hwnd: Optional[int] = None,
    confidence: float = 0.85,
    max_screenshot_width: int = 1280,
    timeout: float = 10.0,
    interval: float = 0.5,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    capture_mode: str = "auto",
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Wait for template image in window screenshot with parameter normalization."""
    target_hwnd = _resolve_target(hwnd)
    if target_hwnd is None:
        return {"ok": False, "error": "No target window handle specified"}
    w = max_width if max_width is not None else max_screenshot_width
    return image_wait(
        target_hwnd,
        template_path,
        confidence=confidence,
        max_width=w,
        timeout=timeout,
        interval=interval,
        region=region,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_step=scale_step,
        capture_mode=capture_mode,
    )


def click_image(
    template_path: str,
    hwnd: Optional[int] = None,
    confidence: float = 0.85,
    max_screenshot_width: int = 1280,
    button: str = "left",
    clicks: int = 1,
    timeout: float = 0.0,
    interval: float = 0.5,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    capture_mode: str = "auto",
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Click template image in window screenshot with parameter normalization."""
    target_hwnd = _resolve_target(hwnd)
    if target_hwnd is None:
        return {"ok": False, "error": "No target window handle specified"}
    w = max_width if max_width is not None else max_screenshot_width
    return image_click(
        target_hwnd,
        template_path,
        confidence=confidence,
        max_width=w,
        button=button,
        clicks=clicks,
        timeout=timeout,
        interval=interval,
        region=region,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_step=scale_step,
        capture_mode=capture_mode,
    )


def desktop_wait_image(
    template_path: str,
    confidence: float = 0.85,
    max_screenshot_width: int = 1600,
    timeout: float = 10.0,
    interval: float = 0.5,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Wait for template image in desktop screenshot with parameter normalization."""
    w = max_width if max_width is not None else max_screenshot_width
    return desktop_image_wait(
        template_path,
        confidence=confidence,
        max_width=w,
        timeout=timeout,
        interval=interval,
        region=region,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_step=scale_step,
    )


def desktop_click_image(
    template_path: str,
    confidence: float = 0.85,
    max_screenshot_width: int = 1600,
    screenshot_id: Optional[int] = None,
    button: str = "left",
    clicks: int = 1,
    timeout: float = 0.0,
    interval: float = 0.5,
    region: Optional[Any] = None,
    scale_min: float = 1.0,
    scale_max: float = 1.0,
    scale_step: float = 0.0,
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Click template image in desktop screenshot with parameter normalization."""
    w = max_width if max_width is not None else max_screenshot_width
    return desktop_image_click(
        template_path,
        confidence=confidence,
        max_width=w,
        screenshot_id=screenshot_id,
        button=button,
        clicks=clicks,
        timeout=timeout,
        interval=interval,
        region=region,
        scale_min=scale_min,
        scale_max=scale_max,
        scale_step=scale_step,
    )




