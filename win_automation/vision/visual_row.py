"""
OCR-assisted numbered row visual detection, row-based scrolling, and row item clicking.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.state.persistence import resolve_target_hwnd
from win_automation.vision.capture import _get_screenshot_size, _scale_coords
from win_automation.input.mouse import click, scroll
from win_automation.ocr.finder import desktop_ocr, ocr_find, run_ocr

def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)

def _normalize_visual_row_number_text(text: str) -> str:
    value = str(text or "").strip()
    if ":" in value or "：" in value:
        return ""
    compact = value.replace(" ", "")
    if len(compact) == 3 and compact[0] in ("1", "l", "I") and compact[1] in ("+", ".") and compact[2].isdigit():
        return "4" + compact[2]
    return "".join(ch for ch in value if ch.isdigit())


def _visual_row_number_candidates(
    ocr_result: Dict[str, Any],
    region: Optional[Any] = None,
    min_row: int = 1,
    max_row: int = 999,
) -> List[Dict[str, Any]]:
    normalized_region = _normalize_ocr_region(region)
    candidates: List[Dict[str, Any]] = []
    seen: set[Tuple[int, int]] = set()
    for word in _ocr_words_list(ocr_result):
        text = str(word.get("text") or "").strip()
        normalized = _normalize_visual_row_number_text(text)
        if not normalized:
            continue
        try:
            row_number = int(normalized)
        except Exception:
            continue
        if row_number < int(min_row) or row_number > int(max_row):
            continue
        rect = _ocr_rect_from_word(word)
        if not rect or not _rect_inside_region(rect, normalized_region):
            continue
        key = (row_number, rect["center_y"])
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "row": row_number,
            "text": text,
            "normalized_text": normalized,
            "rect": rect,
            "center_x": rect["center_x"],
            "center_y": rect["center_y"],
            "confidence": word.get("confidence", -1),
        })
    candidates.sort(key=lambda item: (item["center_y"], item["center_x"]))
    return candidates


def _auto_visual_row_region(candidates: List[Dict[str, Any]], image_width: Optional[int] = None, image_height: Optional[int] = None) -> Tuple[Optional[Dict[str, int]], Dict[str, Any]]:
    """Infer the row-number column from consecutive OCR number anchors."""
    if len(candidates) < 2:
        return None, {"mode": "auto-unavailable", "reason": "insufficient-number-candidates", "candidate_count": len(candidates)}

    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        x_bucket = int(round(float(candidate["center_x"]) / 24.0))
        buckets.setdefault(x_bucket, []).append(candidate)

    best: Optional[Tuple[float, List[Dict[str, Any]], Dict[str, Any]]] = None
    for bucket_items in buckets.values():
        items = sorted(bucket_items, key=lambda item: (int(item["row"]), int(item["center_y"])))
        row_best: List[Dict[str, Any]] = []
        for item in items:
            row = int(item["row"])
            y = int(item["center_y"])
            placed = False
            for idx, existing in enumerate(row_best):
                if int(existing["row"]) == row:
                    if abs(y - int(existing["center_y"])) < 4:
                        row_best[idx] = item
                    placed = True
                    break
            if not placed:
                row_best.append(item)
        row_best.sort(key=lambda item: int(item["row"]))
        if len(row_best) < 2:
            continue

        consecutive_edges = 0
        usable_steps: List[float] = []
        row_gaps: List[int] = []
        inversions = 0
        for left, right in zip(row_best, row_best[1:]):
            row_delta = int(right["row"]) - int(left["row"])
            y_delta = float(right["center_y"]) - float(left["center_y"])
            if row_delta <= 0:
                continue
            if y_delta <= 0:
                inversions += 1
                continue
            row_gaps.append(row_delta)
            step = y_delta / row_delta
            if 8 <= step <= 180:
                usable_steps.append(step)
            if row_delta == 1 and 8 <= y_delta <= 180:
                consecutive_edges += 1
        if not usable_steps:
            continue
        avg_step = sum(usable_steps) / len(usable_steps)
        step_jitter = sum(abs(step - avg_step) for step in usable_steps) / len(usable_steps)
        row_span = int(row_best[-1]["row"]) - int(row_best[0]["row"])
        y_span = int(row_best[-1]["center_y"]) - int(row_best[0]["center_y"])
        if y_span <= 0:
            continue
        avg_row_gap = sum(row_gaps) / len(row_gaps) if row_gaps else row_span
        x_values = [int(item["center_x"]) for item in row_best]
        x_spread = max(x_values) - min(x_values)
        score = (
            len(row_best) * 8.0
            + consecutive_edges * 12.0
            + max(0.0, 6.0 - float(avg_row_gap)) * 3.0
            + min(row_span, 12) * 0.5
            - x_spread * 0.35
            - step_jitter * 0.2
            - inversions * 8.0
        )
        diagnostics = {
            "mode": "auto-number-column",
            "anchor_count": len(row_best),
            "row_span": row_span,
            "consecutive_edges": consecutive_edges,
            "x_spread": x_spread,
            "avg_row_step": round(avg_step, 2),
            "avg_row_gap": round(avg_row_gap, 2),
            "step_jitter": round(step_jitter, 2),
            "score": round(score, 2),
        }
        if best is None or score > best[0]:
            best = (score, row_best, diagnostics)

    if best is None:
        return None, {"mode": "auto-unavailable", "reason": "no-consecutive-number-column", "candidate_count": len(candidates)}

    _, anchors, diagnostics = best
    left = min(int(item["rect"]["left"]) for item in anchors)
    right = max(int(item["rect"]["right"]) for item in anchors)
    top = min(int(item["rect"]["top"]) for item in anchors)
    bottom = max(int(item["rect"]["bottom"]) for item in anchors)
    avg_height = max(1, int(round(sum(int(item["rect"]["height"]) for item in anchors) / len(anchors))))
    avg_width = max(1, int(round(sum(int(item["rect"]["width"]) for item in anchors) / len(anchors))))
    pad_x = max(24, avg_width * 3)
    avg_step = float(diagnostics.get("avg_row_step") or avg_height * 3)
    pad_y = max(24, avg_height * 3, int(round(avg_step * 1.25)))
    if image_width is None:
        image_width = max(right + pad_x, right)
    if image_height is None:
        image_height = max(bottom + pad_y, bottom)
    region = {
        "left": max(0, left - pad_x),
        "top": max(0, top - pad_y),
        "right": min(int(image_width), right + pad_x),
        "bottom": min(int(image_height), bottom + pad_y),
    }
    region["width"] = region["right"] - region["left"]
    region["height"] = region["bottom"] - region["top"]
    region["center_x"] = region["left"] + region["width"] // 2
    region["center_y"] = region["top"] + region["height"] // 2
    diagnostics["rows"] = [int(item["row"]) for item in anchors[:40]]
    return region, diagnostics


def _infer_visual_row_from_numbers(
    candidates: List[Dict[str, Any]],
    row: int,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    exact = [candidate for candidate in candidates if int(candidate.get("row", -1)) == int(row)]
    if exact:
        chosen = sorted(exact, key=lambda item: (item["center_y"], item["center_x"]))[0]
        return dict(chosen), {"mode": "exact-row-number"}

    if len(candidates) < 2:
        return None, {"mode": "insufficient-row-number-anchors", "anchor_count": len(candidates)}

    anchors = sorted(candidates, key=lambda item: int(item["row"]))
    best: Optional[Tuple[float, Dict[str, Any], Dict[str, Any], float]] = None
    for left, right in zip(anchors, anchors[1:]):
        row_delta = int(right["row"]) - int(left["row"])
        y_delta = float(right["center_y"]) - float(left["center_y"])
        if row_delta == 0 or abs(y_delta) < 1:
            continue
        step = y_delta / row_delta
        expected_y = float(left["center_y"]) + (int(row) - int(left["row"])) * step
        min_y = min(float(left["center_y"]), float(right["center_y"])) - abs(step) * 2.5
        max_y = max(float(left["center_y"]), float(right["center_y"])) + abs(step) * 2.5
        if not (min_y <= expected_y <= max_y):
            continue
        row_gap = min(abs(int(row) - int(left["row"])), abs(int(row) - int(right["row"])))
        score = row_gap + abs(float(right["row"]) - float(left["row"])) * 0.01
        if best is None or score < best[0]:
            best = (score, left, right, expected_y)

    if best is None:
        return None, {"mode": "row-outside-visible-anchor-range", "anchor_count": len(candidates)}

    _, left, right, expected_y = best
    inferred = {
        "row": int(row),
        "text": str(row).zfill(max(2, len(str(row)))),
        "normalized_text": str(row),
        "rect": {
            "left": int(left["rect"]["left"]),
            "right": int(left["rect"]["right"]),
            "top": int(round(expected_y - left["rect"]["height"] / 2)),
            "bottom": int(round(expected_y + left["rect"]["height"] / 2)),
            "width": int(left["rect"]["width"]),
            "height": int(left["rect"]["height"]),
            "center_x": int(left["center_x"]),
            "center_y": int(round(expected_y)),
        },
        "center_x": int(left["center_x"]),
        "center_y": int(round(expected_y)),
        "inferred": True,
    }
    inferred["rect"]["height"] = inferred["rect"]["bottom"] - inferred["rect"]["top"]
    return inferred, {"mode": "interpolated-row-number", "anchors": [left, right]}


def visual_row(
    hwnd: int,
    row: int,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    row_region: Optional[Any] = None,
    min_row: int = 1,
    max_row: int = 999,
    reuse_last_screenshot: bool = True,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Locate a visible numbered list/table row from OCR row-number anchors."""
    ocr_result = ocr(hwnd, lang=lang, max_width=max_width, screenshot_id=screenshot_id, engine=engine, reuse_last_screenshot=reuse_last_screenshot, capture_mode=capture_mode)
    if "error" in ocr_result:
        return {"ok": False, "found": False, "row": row, "ocr": ocr_result, "error": ocr_result.get("error")}
    screenshot = ocr_result.get("screenshot") or {}
    normalized_region = _normalize_ocr_region(row_region)
    region_source: Dict[str, Any] = {"mode": "explicit" if normalized_region else "none"}
    if normalized_region is None:
        all_candidates = _visual_row_number_candidates(ocr_result, region=None, min_row=min_row, max_row=max_row)
        normalized_region, region_source = _auto_visual_row_region(
            all_candidates,
            image_width=screenshot.get("width"),
            image_height=screenshot.get("height"),
        )
        candidates = [candidate for candidate in all_candidates if _rect_inside_region(candidate["rect"], normalized_region)]
    else:
        candidates = _visual_row_number_candidates(ocr_result, region=normalized_region, min_row=min_row, max_row=max_row)
    target, inference = _infer_visual_row_from_numbers(candidates, row)
    result = {
        "ok": bool(target),
        "found": bool(target),
        "row": int(row),
        "target": target,
        "inference": inference,
        "row_candidates": candidates[:80],
        "row_region": normalized_region,
        "row_region_source": region_source,
        "screenshot": screenshot,
        "ocr": {
            "engine": ocr_result.get("engine"),
            "language": ocr_result.get("language"),
            "fallback_from": ocr_result.get("fallback_from"),
            "word_count": len(_ocr_words_list(ocr_result)),
        },
    }
    if not target:
        result["error"] = "visual_row_not_found"
    return result


def visual_row_click(
    hwnd: int,
    row: int,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    screenshot_id: Optional[int] = None,
    engine: str = "auto",
    row_region: Optional[Any] = None,
    click_x: Optional[int] = None,
    x_offset: int = 120,
    button: str = "left",
    clicks: int = 1,
    min_row: int = 1,
    max_row: int = 999,
    reuse_last_screenshot: bool = True,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Click a visible numbered row, useful for custom-rendered song lists and data tables."""
    result = visual_row(
        hwnd,
        row,
        lang=lang,
        max_width=max_width,
        screenshot_id=screenshot_id,
        engine=engine,
        row_region=row_region,
        min_row=min_row,
        max_row=max_row,
        reuse_last_screenshot=reuse_last_screenshot,
        capture_mode=capture_mode,
    )
    if not result.get("found"):
        result["ok"] = False
        return result
    target = result.get("target") or {}
    screenshot = result.get("screenshot") or {}
    sid = screenshot_id or screenshot.get("id")
    if click_x is not None:
        x = int(click_x)
    elif int(x_offset) != 120:
        x = int(target.get("center_x", 0)) + int(x_offset)
    else:
        width = int(screenshot.get("width") or 0)
        row_x = int(target.get("center_x", 0))
        x = min(row_x + 160, max(row_x + 40, int(width * 0.33))) if width > 0 else row_x + int(x_offset)
    y = int(target.get("center_y", 0))
    message = click(hwnd, x, y, button=button, clicks=clicks, screenshot_id=sid)
    result["ok"] = True
    result["clicked"] = True
    result["click"] = {"x": x, "y": y, "button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
    return result


def _visual_row_scroll_decision(result: Dict[str, Any], row: int) -> Dict[str, Any]:
    candidates = result.get("row_candidates") or []
    rows = sorted({int(candidate.get("row")) for candidate in candidates if candidate.get("row") is not None})
    if not rows:
        return {"direction": 1, "reason": "no-row-anchors", "rows": rows}
    if int(row) > max(rows):
        return {"direction": 1, "reason": "target-after-visible-range", "rows": rows, "min_visible_row": min(rows), "max_visible_row": max(rows)}
    if int(row) < min(rows):
        return {"direction": -1, "reason": "target-before-visible-range", "rows": rows, "min_visible_row": min(rows), "max_visible_row": max(rows)}
    return {"direction": 0, "reason": "target-inside-visible-row-range-but-not-located", "rows": rows, "min_visible_row": min(rows), "max_visible_row": max(rows)}


def visual_row_scroll(
    hwnd: int,
    row: int,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    engine: str = "auto",
    row_region: Optional[Any] = None,
    min_row: int = 1,
    max_row: int = 999,
    max_scrolls: int = 8,
    scroll_amount: int = 5,
    scroll_x: Optional[int] = None,
    scroll_y: Optional[int] = None,
    pause: float = 0.35,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Locate a numbered row, scrolling the visible list/table until it appears."""
    hwnd = _resolve_target(hwnd)
    attempts: List[Dict[str, Any]] = []
    seen_ranges: set[Tuple[Optional[int], Optional[int], Optional[int]]] = set()
    last_result: Dict[str, Any] = {}
    for attempt in range(max(1, int(max_scrolls) + 1)):
        result = visual_row(
            hwnd,
            row,
            lang=lang,
            max_width=max_width,
            screenshot_id=None,
            engine=engine,
            row_region=row_region,
            min_row=min_row,
            max_row=max_row,
            reuse_last_screenshot=False,
            capture_mode=capture_mode,
        )
        last_result = result
        candidates = result.get("row_candidates") or []
        rows = sorted({int(candidate.get("row")) for candidate in candidates if candidate.get("row") is not None})
        attempt_info: Dict[str, Any] = {
            "attempt": attempt + 1,
            "found": bool(result.get("found")),
            "inference": result.get("inference"),
            "row_region": result.get("row_region"),
            "row_region_source": result.get("row_region_source"),
            "visible_rows": rows[:60],
            "screenshot": result.get("screenshot"),
        }
        if rows:
            attempt_info["min_visible_row"] = min(rows)
            attempt_info["max_visible_row"] = max(rows)
        attempts.append(attempt_info)
        if result.get("found"):
            result["ok"] = True
            result["attempts"] = attempts
            result["scrolled"] = attempt
            return result
        if attempt >= int(max_scrolls):
            break

        decision = _visual_row_scroll_decision(result, row)
        direction = int(decision.get("direction") or 0)
        if direction == 0:
            last_result = dict(result)
            last_result["scroll_decision"] = decision
            break

        screenshot = result.get("screenshot") or {}
        width = int(screenshot.get("width") or max_width or 1280)
        height = int(screenshot.get("height") or 900)
        sx = int(scroll_x) if scroll_x is not None else int(width * 0.55)
        sy = int(scroll_y) if scroll_y is not None else int(height * 0.72)
        dy = direction * max(1, int(scroll_amount))
        message = scroll(hwnd, sx, sy, dy, screenshot_id=screenshot.get("id"))
        attempt_info["scroll"] = {"x": sx, "y": sy, "dy": dy, "message": message, "decision": decision}

        key = (decision.get("min_visible_row"), decision.get("max_visible_row"), direction)
        if key in seen_ranges:
            attempt_info["stop_reason"] = "visible-row-range-did-not-change"
            break
        seen_ranges.add(key)
        time.sleep(max(float(pause), 0.05))

    return {
        "ok": False,
        "found": False,
        "row": int(row),
        "error": "visual_row_scroll_not_found",
        "attempts": attempts,
        "last_result": last_result,
    }


def visual_row_scroll_click(
    hwnd: int,
    row: int,
    lang: str = "eng+chi_sim",
    max_width: int = 1600,
    engine: str = "auto",
    row_region: Optional[Any] = None,
    click_x: Optional[int] = None,
    x_offset: int = 120,
    button: str = "left",
    clicks: int = 2,
    min_row: int = 1,
    max_row: int = 999,
    max_scrolls: int = 8,
    scroll_amount: int = 5,
    scroll_x: Optional[int] = None,
    scroll_y: Optional[int] = None,
    pause: float = 0.35,
    capture_mode: str = "auto",
) -> Dict[str, Any]:
    """Scroll to a numbered row and click it."""
    result = visual_row_scroll(
        hwnd,
        row,
        lang=lang,
        max_width=max_width,
        engine=engine,
        row_region=row_region,
        min_row=min_row,
        max_row=max_row,
        max_scrolls=max_scrolls,
        scroll_amount=scroll_amount,
        scroll_x=scroll_x,
        scroll_y=scroll_y,
        pause=pause,
        capture_mode=capture_mode,
    )
    if not result.get("found"):
        result["ok"] = False
        return result
    target = result.get("target") or {}
    screenshot = result.get("screenshot") or {}
    sid = screenshot.get("id")
    if click_x is not None:
        x = int(click_x)
    elif int(x_offset) != 120:
        x = int(target.get("center_x", 0)) + int(x_offset)
    else:
        width = int(screenshot.get("width") or 0)
        row_x = int(target.get("center_x", 0))
        x = min(row_x + 160, max(row_x + 40, int(width * 0.33))) if width > 0 else row_x + int(x_offset)
    y = int(target.get("center_y", 0))
    message = click(hwnd, x, y, button=button, clicks=clicks, screenshot_id=sid)
    result["ok"] = True
    result["clicked"] = True
    result["click"] = {"x": x, "y": y, "button": button, "clicks": clicks, "message": message, "screenshot_id": sid}
    return result



