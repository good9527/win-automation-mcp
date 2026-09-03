"""
Optical Character Recognition (OCR) pipeline: WinRT OCR engine & Tesseract fallback.
"""

from __future__ import annotations

import os
import re
import sys
import time
import json
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image as PILImage

from win_automation.core.types import ActionTimeoutError
from win_automation.vision.capture import capture_window_screenshot, capture_desktop_screenshot, _get_screenshot_size, _scale_coords
from win_automation.input.mouse import click, desktop_click, scroll
from win_automation.state.persistence import resolve_target_hwnd, load_screenshot_meta

def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)

def _load_screenshot_meta(screenshot_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    return load_screenshot_meta(screenshot_id)

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


def desktop_ocr(
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
) -> Dict[str, Any]:
    """Run OCR on a full virtual desktop screenshot."""
    engine = _normalize_ocr_engine(engine)
    img, meta = _load_or_capture_desktop_image(screenshot_id=screenshot_id, max_width=max_width)

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


def _normalize_ocr_match_mode(match: str) -> str:
    value = str(match or "contains").strip().lower()
    aliases = {"substring": "contains", "contains_text": "contains", "re": "regex"}
    value = aliases.get(value, value)
    if value not in ("contains", "exact", "regex"):
        raise ValueError("OCR text match must be contains, exact, or regex")
    return value


def _ocr_text_matches(candidate: str, query: str, match: str) -> bool:
    left = str(candidate or "")
    right = str(query or "")
    if not right:
        return False
    if match == "regex":
        import re
        return bool(re.search(right, left, re.IGNORECASE))
    if match == "exact":
        return left.casefold() == right.casefold()
    return right.casefold() in left.casefold()


def _ocr_rect_from_word(word: Dict[str, Any]) -> Optional[Dict[str, int]]:
    rect = word.get("rect") if isinstance(word, dict) else None
    if not isinstance(rect, dict):
        return None
    try:
        left = int(round(float(rect.get("left", 0))))
        top = int(round(float(rect.get("top", 0))))
        width = int(round(float(rect.get("width", 0))))
        height = int(round(float(rect.get("height", 0))))
        right = int(round(float(rect.get("right", left + width))))
        bottom = int(round(float(rect.get("bottom", top + height))))
    except Exception:
        return None
    if right <= left or bottom <= top:
        return None
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


def _ocr_words_list(ocr_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_words = ocr_result.get("words") or []
    if isinstance(raw_words, dict):
        raw_words = [raw_words]
    if not isinstance(raw_words, list):
        return []
    return [word for word in raw_words if isinstance(word, dict)]


def _normalize_ocr_region(region: Optional[Any]) -> Optional[Dict[str, int]]:
    if region is None or region == "":
        return None
    if isinstance(region, str):
        parts = [part.strip() for part in region.replace(";", ",").split(",") if part.strip()]
        if len(parts) != 4:
            raise ValueError("OCR region must be left,top,right,bottom")
        values = [int(round(float(part))) for part in parts]
        region = values
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
            raise ValueError("OCR region dict needs left/top/right/bottom or x/y/width/height")
    elif isinstance(region, (list, tuple)) and len(region) == 4:
        left, top, right, bottom = [int(round(float(value))) for value in region]
    else:
        raise ValueError("OCR region must be a dict, list, tuple, or left,top,right,bottom string")
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


def _rect_inside_region(rect: Dict[str, int], region: Optional[Dict[str, int]]) -> bool:
    if not region:
        return True
    cx = rect.get("center_x", rect["left"] + rect["width"] // 2)
    cy = rect.get("center_y", rect["top"] + rect["height"] // 2)
    return region["left"] <= cx <= region["right"] and region["top"] <= cy <= region["bottom"]


def _union_ocr_rects(rects: List[Dict[str, int]]) -> Dict[str, int]:
    left = min(rect["left"] for rect in rects)
    top = min(rect["top"] for rect in rects)
    right = max(rect["right"] for rect in rects)
    bottom = max(rect["bottom"] for rect in rects)
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


def _find_ocr_text_matches(
    ocr_result: Dict[str, Any],
    text: str,
    match: str = "contains",
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
) -> Dict[str, Any]:
    """Find text inside OCR word boxes and return click-ready screenshot coordinates."""
    match = _normalize_ocr_match_mode(match)
    normalized_region = _normalize_ocr_region(region)
    words: List[Dict[str, Any]] = []
    for idx, word in enumerate(_ocr_words_list(ocr_result)):
        raw = str((word or {}).get("text") or "").strip()
        rect = _ocr_rect_from_word(word)
        if not raw or not rect or not _rect_inside_region(rect, normalized_region):
            continue
        words.append({"index": idx, "text": raw, "rect": rect, "confidence": (word or {}).get("confidence", -1)})

    query = str(text or "").strip()
    if not query:
        return {"ok": True, "found": False, "query": query, "match": match, "matches": [], "word_count": len(words)}

    query_word_count = max(1, len(query.split()))
    span_limit = max_words if max_words is not None else min(16, max(1, query_word_count + 4))
    span_limit = max(1, min(int(span_limit), max(len(words), 1)))
    compact_query = "".join(query.split())
    matches: List[Dict[str, Any]] = []
    seen: set[Tuple[int, int, str]] = set()

    for start in range(len(words)):
        rects: List[Dict[str, int]] = []
        texts: List[str] = []
        confidences: List[float] = []
        for end in range(start, min(len(words), start + span_limit)):
            word = words[end]
            rects.append(word["rect"])
            texts.append(word["text"])
            try:
                confidences.append(float(word.get("confidence", -1)))
            except Exception:
                confidences.append(-1.0)
            candidate = " ".join(texts)
            compact_candidate = "".join(texts)
            if (
                _ocr_text_matches(candidate, query, match)
                or (compact_query and _ocr_text_matches(compact_candidate, compact_query, match))
            ):
                key = (start, end, candidate.casefold())
                if key in seen:
                    continue
                seen.add(key)
                rect = _union_ocr_rects(rects)
                matched_words = [
                    {
                        "index": words[i]["index"],
                        "text": words[i]["text"],
                        "rect": words[i]["rect"],
                        "confidence": words[i].get("confidence", -1),
                    }
                    for i in range(start, end + 1)
                ]
                score = len(query) / max(len(candidate), 1)
                if candidate.casefold() == query.casefold():
                    score += 2.0
                elif query.casefold() in candidate.casefold():
                    score += 1.0
                if compact_candidate.casefold() == compact_query.casefold():
                    score += 1.0
                avg_confidence = sum(confidences) / len(confidences) if confidences else -1.0
                matches.append({
                    "text": candidate,
                    "rect": rect,
                    "center_x": rect["center_x"],
                    "center_y": rect["center_y"],
                    "word_start": start,
                    "word_end": end,
                    "words": matched_words,
                    "confidence": avg_confidence,
                    "score": round(score, 4),
                })

    matches.sort(key=lambda item: (-float(item.get("score", 0)), item["rect"]["top"], item["rect"]["left"]))
    if limit and limit > 0:
        matches = matches[:limit]
    return {
        "ok": True,
        "found": bool(matches),
        "query": query,
        "match": match,
        "region": normalized_region,
        "matches": matches,
        "word_count": len(words),
        "screenshot": ocr_result.get("screenshot"),
        "engine": ocr_result.get("engine"),
        "language": ocr_result.get("language"),
    }


def ocr_find(
    hwnd: int,
    text: str,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    match: str = "contains",
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Find OCR text in a window screenshot and return click-ready coordinates."""
    ocr_result = ocr(hwnd, lang=lang, max_width=max_width, screenshot_id=screenshot_id, engine=engine, capture_mode=capture_mode)
    if "error" in ocr_result:
        return {"ok": False, "found": False, "query": text, "ocr": ocr_result, "error": ocr_result.get("error")}
    matches = _find_ocr_text_matches(ocr_result, text, match=match, limit=limit, region=region, max_words=max_words)
    matches["ocr_text"] = ocr_result.get("text", "")
    matches["ocr"] = {
        "engine": ocr_result.get("engine"),
        "language": ocr_result.get("language"),
        "fallback_from": ocr_result.get("fallback_from"),
    }
    return matches


def _add_desktop_screen_points_to_ocr_matches(result: Dict[str, Any]) -> Dict[str, Any]:
    screenshot = result.get("screenshot") or {}
    sid = screenshot.get("id")
    if not sid:
        return result
    updated: List[Dict[str, Any]] = []
    for item in result.get("matches") or []:
        match = dict(item)
        screen_x, screen_y, debug = _desktop_point_to_screen(int(match["center_x"]), int(match["center_y"]), int(sid))
        match["screen_x"] = screen_x
        match["screen_y"] = screen_y
        match["debug"] = debug
        updated.append(match)
    result["matches"] = updated
    return result


def desktop_ocr_find(
    text: str,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    match: str = "contains",
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
) -> Dict[str, Any]:
    """Find OCR text in the full virtual desktop screenshot."""
    ocr_result = desktop_ocr(lang=lang, max_width=max_width, screenshot_id=screenshot_id, engine=engine)
    if "error" in ocr_result:
        return {"ok": False, "found": False, "query": text, "ocr": ocr_result, "error": ocr_result.get("error")}
    matches = _find_ocr_text_matches(ocr_result, text, match=match, limit=limit, region=region, max_words=max_words)
    matches["ocr_text"] = ocr_result.get("text", "")
    matches["ocr"] = {
        "engine": ocr_result.get("engine"),
        "language": ocr_result.get("language"),
        "fallback_from": ocr_result.get("fallback_from"),
    }
    return _add_desktop_screen_points_to_ocr_matches(matches)


def _wait_for_ocr_text_result(
    fetch_ocr_result: Any,
    text: str,
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.5,
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
) -> Dict[str, Any]:
    """Poll OCR results until visible text is found."""
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    attempts = 0
    last_result: Dict[str, Any] = {}
    while True:
        attempts += 1
        ocr_result = fetch_ocr_result()
        if isinstance(ocr_result, dict) and "error" not in ocr_result:
            result = _find_ocr_text_matches(ocr_result, text, match=match, limit=limit, region=region, max_words=max_words)
            result["ocr_text"] = ocr_result.get("text", "")
            result["ocr"] = {
                "engine": ocr_result.get("engine"),
                "language": ocr_result.get("language"),
                "fallback_from": ocr_result.get("fallback_from"),
            }
            last_result = result
            if result.get("found"):
                result["ok"] = True
                result["attempts"] = attempts
                result["elapsed"] = round(time.time() - start, 3)
                result["timeout"] = timeout
                result["interval"] = interval
                return result
        else:
            last_result = {
                "ok": False,
                "found": False,
                "query": text,
                "ocr": ocr_result,
                "error": (ocr_result or {}).get("error") if isinstance(ocr_result, dict) else "ocr_failed",
            }
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))

    return {
        "ok": False,
        "found": False,
        "error": "timeout",
        "query": text,
        "match": _normalize_ocr_match_mode(match),
        "attempts": attempts,
        "elapsed": round(time.time() - start, 3),
        "timeout": timeout,
        "interval": interval,
        "last_result": last_result,
    }


def ocr_wait(
    hwnd: int,
    text: str,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    engine: str = "auto",
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.5,
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Wait until OCR-visible text appears in a window screenshot."""
    return _wait_for_ocr_text_result(
        lambda: ocr(hwnd, lang=lang, max_width=max_width, screenshot_id=None, engine=engine, reuse_last_screenshot=False, capture_mode=capture_mode),
        text,
        match=match,
        timeout=timeout,
        interval=interval,
        limit=limit,
        region=region,
        max_words=max_words,
    )


def desktop_ocr_wait(
    text: str,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    engine: str = "auto",
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.5,
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
) -> Dict[str, Any]:
    """Wait until OCR-visible text appears in the full virtual desktop screenshot."""
    result = _wait_for_ocr_text_result(
        lambda: desktop_ocr(lang=lang, max_width=max_width, screenshot_id=None, engine=engine),
        text,
        match=match,
        timeout=timeout,
        interval=interval,
        limit=limit,
        region=region,
        max_words=max_words,
    )
    return _add_desktop_screen_points_to_ocr_matches(result)


def ocr_click(
    hwnd: int,
    text: str,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    match: str = "contains",
    index: int = 0,
    button: str = "left",
    clicks: int = 1,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    timeout: float = 0.0,
    interval: float = 0.5,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Click the center of an OCR text match."""
    if timeout and timeout > 0:
        result = ocr_wait(
            hwnd,
            text,
            lang=lang,
            max_width=max_width,
            engine=engine,
            match=match,
            timeout=timeout,
            interval=interval,
            limit=max(index + 1, 1),
            region=region,
            max_words=max_words,
            capture_mode=capture_mode,
        )
    else:
        result = ocr_find(
            hwnd,
            text,
            lang=lang,
            max_width=max_width,
            screenshot_id=screenshot_id,
            engine=engine,
            match=match,
            limit=max(index + 1, 1),
            region=region,
            max_words=max_words,
            capture_mode=capture_mode,
        )
    if not result.get("found"):
        result["ok"] = False
        return result
    matches = result.get("matches") or []
    if index < 0 or index >= len(matches):
        result["ok"] = False
        result["error"] = f"OCR match index {index} out of range"
        return result
    target = matches[index]
    screenshot = result.get("screenshot") or {}
    sid = screenshot_id or screenshot.get("id")
    message = click(hwnd, int(target["center_x"]), int(target["center_y"]), button=button, clicks=clicks, screenshot_id=sid)
    result["ok"] = True
    result["clicked"] = True
    result["target"] = target
    result["click"] = {"button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
    return result


def desktop_ocr_click(
    text: str,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    match: str = "contains",
    index: int = 0,
    button: str = "left",
    clicks: int = 1,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    timeout: float = 0.0,
    interval: float = 0.5,
) -> Dict[str, Any]:
    """Click the center of an OCR text match on the full virtual desktop."""
    if timeout and timeout > 0:
        result = desktop_ocr_wait(
            text,
            lang=lang,
            max_width=max_width,
            engine=engine,
            match=match,
            timeout=timeout,
            interval=interval,
            limit=max(index + 1, 1),
            region=region,
            max_words=max_words,
        )
    else:
        result = desktop_ocr_find(
            text,
            lang=lang,
            max_width=max_width,
            screenshot_id=screenshot_id,
            engine=engine,
            match=match,
            limit=max(index + 1, 1),
            region=region,
            max_words=max_words,
        )
    if not result.get("found"):
        result["ok"] = False
        return result
    matches = result.get("matches") or []
    if index < 0 or index >= len(matches):
        result["ok"] = False
        result["error"] = f"OCR match index {index} out of range"
        return result
    target = matches[index]
    screenshot = result.get("screenshot") or {}
    sid = screenshot_id or screenshot.get("id")
    message = desktop_click(int(target["center_x"]), int(target["center_y"]), button=button, clicks=clicks, screenshot_id=sid)
    result["ok"] = True
    result["clicked"] = True
    result["target"] = target
    result["click"] = {"button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
    return result


def ocr_scroll_click(
    hwnd: int,
    text: str,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    engine: str = "auto",
    match: str = "contains",
    index: int = 0,
    button: str = "left",
    clicks: int = 1,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    max_scrolls: int = 8,
    scroll_amount: int = 5,
    scroll_x: Optional[int] = None,
    scroll_y: Optional[int] = None,
    pause: float = 0.35,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Scroll a window until OCR text is visible, then click it."""
    hwnd = _resolve_target(hwnd)
    attempts: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {}
    for attempt in range(max(1, int(max_scrolls) + 1)):
        result = ocr_find(
            hwnd,
            text,
            lang=lang,
            max_width=max_width,
            screenshot_id=None,
            engine=engine,
            match=match,
            limit=max(index + 1, 1),
            region=region,
            max_words=max_words,
            capture_mode=capture_mode,
        )
        last_result = result
        screenshot = result.get("screenshot") or {}
        attempt_info: Dict[str, Any] = {
            "attempt": attempt + 1,
            "found": bool(result.get("found")),
            "match_count": len(result.get("matches") or []),
            "screenshot": screenshot,
        }
        attempts.append(attempt_info)
        if result.get("found"):
            matches = result.get("matches") or []
            if index < 0 or index >= len(matches):
                result["ok"] = False
                result["error"] = f"OCR match index {index} out of range"
                result["attempts"] = attempts
                return result
            target = matches[index]
            sid = screenshot.get("id")
            message = click(hwnd, int(target["center_x"]), int(target["center_y"]), button=button, clicks=clicks, screenshot_id=sid)
            result["ok"] = True
            result["clicked"] = True
            result["target"] = target
            result["attempts"] = attempts
            result["scrolled"] = attempt
            result["click"] = {"button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
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
        "error": "ocr_scroll_click_not_found",
        "query": text,
        "match": _normalize_ocr_match_mode(match),
        "attempts": attempts,
        "last_result": last_result,
    }


def desktop_ocr_scroll_click(
    text: str,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    engine: str = "auto",
    match: str = "contains",
    index: int = 0,
    button: str = "left",
    clicks: int = 1,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    max_scrolls: int = 8,
    scroll_amount: int = 5,
    scroll_x: Optional[int] = None,
    scroll_y: Optional[int] = None,
    pause: float = 0.35,
) -> Dict[str, Any]:
    """Scroll the desktop until OCR text is visible, then click it."""
    attempts: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {}
    for attempt in range(max(1, int(max_scrolls) + 1)):
        result = desktop_ocr_find(
            text,
            lang=lang,
            max_width=max_width,
            screenshot_id=None,
            engine=engine,
            match=match,
            limit=max(index + 1, 1),
            region=region,
            max_words=max_words,
        )
        last_result = result
        screenshot = result.get("screenshot") or {}
        attempt_info: Dict[str, Any] = {
            "attempt": attempt + 1,
            "found": bool(result.get("found")),
            "match_count": len(result.get("matches") or []),
            "screenshot": screenshot,
        }
        attempts.append(attempt_info)
        if result.get("found"):
            matches = result.get("matches") or []
            if index < 0 or index >= len(matches):
                result["ok"] = False
                result["error"] = f"OCR match index {index} out of range"
                result["attempts"] = attempts
                return result
            target = matches[index]
            sid = screenshot.get("id")
            message = desktop_click(int(target["center_x"]), int(target["center_y"]), button=button, clicks=clicks, screenshot_id=sid)
            result["ok"] = True
            result["clicked"] = True
            result["target"] = target
            result["attempts"] = attempts
            result["scrolled"] = attempt
            result["click"] = {"button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
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
        "error": "desktop_ocr_scroll_click_not_found",
        "query": text,
        "match": _normalize_ocr_match_mode(match),
        "attempts": attempts,
        "last_result": last_result,
    }


def run_ocr(image_or_bytes: Any, lang: str = "zh-Hans-CN") -> List[Dict[str, Any]]:
    """
    Direct in-memory OCR evaluation returning structured word bounding boxes.
    Supports PIL Image, raw image bytes, and byte arrays.
    Returns:
        [
            {
                "text": str,
                "confidence": float,
                "rect": {"x": int, "y": int, "width": int, "height": int}
            }
        ]
    """
    if image_or_bytes is None:
        return []

    # Handle raw bytes / empty checks
    if isinstance(image_or_bytes, (bytes, bytearray)):
        if len(image_or_bytes) == 0:
            return []
        # Attempt to decode as PIL Image
        try:
            import io
            image = PILImage.open(io.BytesIO(image_or_bytes)).convert("RGB")
        except Exception:
            return []
    elif isinstance(image_or_bytes, PILImage.Image):
        image = image_or_bytes.convert("RGB")
    elif isinstance(image_or_bytes, int):
        # Passed an HWND
        res = ocr(hwnd=image_or_bytes, lang=lang)
        words = res.get("words") or []
        formatted = []
        for w in words:
            rect = w.get("rect") or {}
            formatted.append({
                "text": str(w.get("text") or ""),
                "confidence": float(w.get("confidence", 0.9)),
                "rect": {
                    "x": int(rect.get("left", 0)),
                    "y": int(rect.get("top", 0)),
                    "width": int(rect.get("width", 0)),
                    "height": int(rect.get("height", 0)),
                }
            })
        return formatted
    else:
        return []

    if image is None:
        return []

    # Try in-memory WinRT OCR (<35ms latency)
    try:
        from win_automation.ocr.winrt_engine import WinRTOCREngine
        winrt_results = WinRTOCREngine.get_instance().recognize_image(image)
        if winrt_results:
            return winrt_results
    except Exception:
        pass

    # Try in-memory tesseract OCR if available
    try:
        import pytesseract
        from pytesseract import Output
        tess_lang = "chi_sim+eng" if "zh" in lang.lower() or "chi" in lang.lower() else "eng"
        data = pytesseract.image_to_data(image, lang=tess_lang, output_type=Output.DICT)
        results: List[Dict[str, Any]] = []
        n_boxes = len(data.get("text", []))
        for i in range(n_boxes):
            text_str = str(data["text"][i]).strip()
            if not text_str:
                continue
            conf_val = float(data["conf"][i]) if "conf" in data else 90.0
            if conf_val < 0:
                conf_val = 80.0
            results.append({
                "text": text_str,
                "confidence": round(conf_val / 100.0, 2),
                "rect": {
                    "x": int(data["left"][i]),
                    "y": int(data["top"][i]),
                    "width": int(data["width"][i]),
                    "height": int(data["height"][i]),
                }
            })
        if results:
            return results
    except Exception:
        pass

    return []


def run_desktop_ocr(lang: str = "zh-Hans-CN") -> List[Dict[str, Any]]:
    """Capture full desktop and run OCR evaluation."""
    tmp_path = os.path.join(tempfile.gettempdir(), f"desktop_ocr_{int(time.time()*1000)}.png")
    try:
        from win_automation.vision.capture import desktop_screenshot
        meta = desktop_screenshot(tmp_path)
        if os.path.exists(tmp_path):
            img = PILImage.open(tmp_path)
            return run_ocr(img, lang=lang)
    except Exception:
        pass
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return []


def desktop_find_text_ocr(
    text: str,
    lang: str = "eng+chi_sim",
    max_screenshot_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    match: str = "contains",
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    w = max_width if max_width is not None else max_screenshot_width
    return desktop_ocr_find(
        text=text,
        lang=lang,
        max_width=w,
        screenshot_id=screenshot_id,
        engine=engine,
        match=match,
        limit=limit,
        region=region,
        max_words=max_words,
    )


def find_text_ocr(
    text: str,
    hwnd: Optional[int] = None,
    lang: str = "eng+chi_sim",
    max_screenshot_width: int = 1600,
    engine: str = "auto",
    match: str = "contains",
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    capture_mode: str = "auto",
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    target_hwnd = _resolve_target(hwnd)
    if target_hwnd is None:
        return {"ok": False, "error": "No target window handle specified"}
    w = max_width if max_width is not None else max_screenshot_width
    return ocr_find(
        hwnd=target_hwnd,
        text=text,
        lang=lang,
        max_width=w,
        engine=engine,
        match=match,
        limit=limit,
        region=region,
        max_words=max_words,
        capture_mode=capture_mode,
    )


def wait_text_ocr(
    text: str,
    hwnd: Optional[int] = None,
    lang: str = "eng+chi_sim",
    max_screenshot_width: int = 1600,
    engine: str = "auto",
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.5,
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    capture_mode: str = "auto",
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    target_hwnd = _resolve_target(hwnd)
    if target_hwnd is None:
        return {"ok": False, "error": "No target window handle specified"}
    w = max_width if max_width is not None else max_screenshot_width
    return ocr_wait(
        hwnd=target_hwnd,
        text=text,
        lang=lang,
        max_width=w,
        engine=engine,
        match=match,
        timeout=timeout,
        interval=interval,
        limit=limit,
        region=region,
        max_words=max_words,
        capture_mode=capture_mode,
    )


def desktop_wait_text_ocr(
    text: str,
    lang: str = "eng+chi_sim",
    max_screenshot_width: int = 1600,
    engine: str = "auto",
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.5,
    limit: int = 10,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    w = max_width if max_width is not None else max_screenshot_width
    return desktop_ocr_wait(
        text=text,
        lang=lang,
        max_width=w,
        engine=engine,
        match=match,
        timeout=timeout,
        interval=interval,
        limit=limit,
        region=region,
        max_words=max_words,
    )


def click_text_ocr(
    text: str,
    hwnd: Optional[int] = None,
    lang: str = "eng+chi_sim",
    max_screenshot_width: int = 1600,
    engine: str = "auto",
    match: str = "contains",
    index: int = 0,
    button: str = "left",
    clicks: int = 1,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    timeout: float = 0.0,
    interval: float = 0.5,
    capture_mode: str = "auto",
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    target_hwnd = _resolve_target(hwnd)
    if target_hwnd is None:
        return {"ok": False, "error": "No target window handle specified"}
    w = max_width if max_width is not None else max_screenshot_width
    return ocr_click(
        hwnd=target_hwnd,
        text=text,
        lang=lang,
        max_width=w,
        engine=engine,
        match=match,
        index=index,
        button=button,
        clicks=clicks,
        region=region,
        max_words=max_words,
        timeout=timeout,
        interval=interval,
        capture_mode=capture_mode,
    )


def desktop_click_text_ocr(
    text: str,
    lang: str = "eng+chi_sim",
    max_screenshot_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    match: str = "contains",
    index: int = 0,
    button: str = "left",
    clicks: int = 1,
    region: Optional[Any] = None,
    max_words: Optional[int] = None,
    timeout: float = 0.0,
    interval: float = 0.5,
    max_width: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    w = max_width if max_width is not None else max_screenshot_width
    return desktop_ocr_click(
        text=text,
        lang=lang,
        max_width=w,
        screenshot_id=screenshot_id,
        engine=engine,
        match=match,
        index=index,
        button=button,
        clicks=clicks,
        region=region,
        max_words=max_words,
        timeout=timeout,
        interval=interval,
    )


