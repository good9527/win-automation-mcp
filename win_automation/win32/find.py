"""
Win32 window and control search, hierarchy traversal, WinEvent waiting, and selector repair.
"""

from __future__ import annotations

import os
import sys
import time
import math
import difflib
import ctypes
import ctypes.wintypes
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from win_automation.core.win32_structures import *
from win_automation.core.utils import shorten as _shorten
from win_automation.win32.window import _win32_window_info, _window_info, get_process_name, _send_message_timeout, _pump_wait
from win_automation.win32.controls import win32_control_info, _win32_control_wait_match
from win_automation.helper.client import _helper_route_for_hwnd, _helper_post


def _selector_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _selector_norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _selector_text_matches(candidate: Any, expected: Any, match: str = "contains") -> bool:
    c = str(candidate or "").strip().lower()
    e = str(expected or "").strip().lower()
    if not e:
        return True
    if match == "exact":
        return c == e
    if match == "startswith":
        return c.startswith(e)
    if match == "endswith":
        return c.endswith(e)
    if match == "regex":
        import re
        try:
            return bool(re.search(e, c))
        except Exception:
            return False
    return e in c



def related_windows(hwnd: int, include_invisible: bool = False) -> Dict[str, Any]:
    """Return windows related by PID, owner, or root owner for dialog/popup tracking."""
    target = _window_info(hwnd)
    if not target:
        return {"error": f"Window {hwnd} not found"}
    target_pid = target.get("pid")
    target_root_owner = target.get("root_owner_hwnd")
    windows: List[Dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(candidate, _):
        try:
            info = _window_info(int(candidate))
            if not info:
                return True
            if not include_invisible and not info.get("visible", False):
                return True
            if (
                info.get("pid") == target_pid
                or info.get("owner_hwnd") == hwnd
                or info.get("root_owner_hwnd") == target_root_owner
                or info.get("root_hwnd") == hwnd
            ):
                windows.append(info)
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, None)
    windows.sort(key=lambda item: (item.get("pid") != target_pid, item.get("title", "")))
    return {"target": target, "windows": windows}


def _is_usable_window_info(window: Dict[str, Any]) -> bool:
    """Return whether a top-level window is alive, visible, and has real bounds."""
    if not isinstance(window, dict):
        return False
    hwnd = int(window.get("hwnd") or 0)
    if not hwnd or not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return False
    rect = window.get("rect") or {}
    try:
        left = int(rect.get("left", 0) or 0)
        top = int(rect.get("top", 0) or 0)
        right = int(rect.get("right", 0) or 0)
        bottom = int(rect.get("bottom", 0) or 0)
        width = int(rect.get("width", right - left) or 0)
        height = int(rect.get("height", bottom - top) or 0)
    except Exception:
        return False
    if width <= 80 or height <= 40:
        return False
    if left <= -30000 or top <= -30000:
        return False
    return True


def _window_filter_matches(
    window: Dict[str, Any],
    title: Optional[str] = None,
    process: Optional[str] = None,
    pid: Optional[int] = None,
    match: str = "contains",
) -> bool:
    if pid is not None and int(window.get("pid") or 0) != int(pid):
        return False
    if title is not None and not _matches_text(str(window.get("title", "")), title, match):
        return False
    if process is not None:
        proc_text = f'{window.get("process_name", "")} {window.get("process_path", "")}'
        if not _matches_text(proc_text, process, match):
            return False
    return True


def _window_selector_suggestion(window: Dict[str, Any], match: str = "contains") -> Dict[str, Any]:
    suggestion: Dict[str, Any] = {}
    hwnd = int(window.get("hwnd") or 0)
    pid = window.get("pid")
    title = str(window.get("title") or "").strip()
    process_name = str(window.get("process_name") or "").strip()
    process_path = str(window.get("process_path") or "").strip()
    if hwnd:
        suggestion["hwnd"] = hwnd
    if title:
        suggestion["title"] = title
        suggestion["match"] = match or "contains"
    if process_name:
        suggestion["process"] = process_name
    elif process_path:
        suggestion["process"] = os.path.basename(process_path)
    if pid is not None:
        suggestion["pid"] = pid
    return {key: value for key, value in suggestion.items() if value not in (None, "", [], {})}


def _window_filter_misses(
    window: Dict[str, Any],
    *,
    title: Optional[str] = None,
    process: Optional[str] = None,
    pid: Optional[int] = None,
    preferred_hwnd: Optional[int] = None,
    match: str = "contains",
) -> List[Dict[str, Any]]:
    misses: List[Dict[str, Any]] = []
    hwnd = int(window.get("hwnd") or 0)
    if preferred_hwnd and hwnd != int(preferred_hwnd):
        misses.append({"criterion": "hwnd", "expected": int(preferred_hwnd), "actual": hwnd})
    if pid is not None and int(window.get("pid") or 0) != int(pid):
        misses.append({"criterion": "pid", "expected": int(pid), "actual": window.get("pid")})
    if title is not None:
        actual_title = str(window.get("title") or "")
        if not _matches_text(actual_title, title, match):
            misses.append({"criterion": "title", "expected": title, "actual": actual_title})
    if process is not None:
        proc_text = f'{window.get("process_name", "")} {window.get("process_path", "")}'
        if not _matches_text(proc_text, process, match):
            misses.append({"criterion": "process", "expected": process, "actual": proc_text.strip()})
    return misses


def _window_diagnostic_score(
    window: Dict[str, Any],
    *,
    title: Optional[str] = None,
    process: Optional[str] = None,
    pid: Optional[int] = None,
    preferred_hwnd: Optional[int] = None,
    match: str = "contains",
) -> int:
    score = _window_stability_score(
        window,
        preferred_hwnd=preferred_hwnd,
        preferred_pid=pid,
        title=title,
        process=process,
        match=match,
    )
    if title is not None:
        actual_title = str(window.get("title") or "")
        if actual_title:
            score += int(difflib.SequenceMatcher(None, _selector_norm(actual_title), _selector_norm(str(title))).ratio() * 30)
    if process is not None:
        proc_text = f'{window.get("process_name", "")} {window.get("process_path", "")}'
        if proc_text.strip():
            score += int(difflib.SequenceMatcher(None, _selector_norm(proc_text), _selector_norm(str(process))).ratio() * 25)
    if pid is not None and int(window.get("pid") or 0) == int(pid):
        score += 30
    if preferred_hwnd and int(window.get("hwnd") or 0) == int(preferred_hwnd):
        score += 50
    rect = window.get("rect") or {}
    try:
        area = int(rect.get("width", 0) or 0) * int(rect.get("height", 0) or 0)
        if area > 0:
            score += min(10, max(1, int(math.log10(max(area, 1)))))
    except Exception:
        pass
    return score


def _compact_window_candidate(
    window: Dict[str, Any],
    *,
    title: Optional[str] = None,
    process: Optional[str] = None,
    pid: Optional[int] = None,
    preferred_hwnd: Optional[int] = None,
    match: str = "contains",
    stable_count: Optional[int] = None,
) -> Dict[str, Any]:
    compact = {
        "hwnd": window.get("hwnd"),
        "title": window.get("title"),
        "pid": window.get("pid"),
        "process_name": window.get("process_name"),
        "process_path": window.get("process_path"),
        "rect": window.get("rect"),
        "visible": window.get("visible"),
        "stable_count": stable_count,
        "selector_score": _window_diagnostic_score(
            window,
            title=title,
            process=process,
            pid=pid,
            preferred_hwnd=preferred_hwnd,
            match=match,
        ),
        "selector_filter_misses": _window_filter_misses(
            window,
            title=title,
            process=process,
            pid=pid,
            preferred_hwnd=preferred_hwnd,
            match=match,
        ),
        "selector_suggestion": _window_selector_suggestion(window, match=match),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _window_find_failure_summary(
    windows: List[Dict[str, Any]],
    *,
    title: Optional[str] = None,
    process: Optional[str] = None,
    pid: Optional[int] = None,
    preferred_hwnd: Optional[int] = None,
    match: str = "contains",
    visible_window_count: int = 0,
    matched_candidates: Optional[List[Dict[str, Any]]] = None,
    stable_counts: Optional[Dict[int, int]] = None,
) -> Dict[str, Any]:
    miss_counts: Dict[str, int] = {}
    process_counts: Dict[str, int] = {}
    title_samples: List[str] = []
    suggestions: List[Dict[str, Any]] = []
    stable_counts = stable_counts or {}
    matched_candidates = matched_candidates or []
    compacted: List[Dict[str, Any]] = []
    seen: set = set()
    for window in windows:
        hwnd = int(window.get("hwnd") or 0)
        if not hwnd or hwnd in seen:
            continue
        seen.add(hwnd)
        proc_name = str(window.get("process_name") or "").strip() or "<unknown>"
        process_counts[proc_name] = process_counts.get(proc_name, 0) + 1
        title_value = str(window.get("title") or "").strip()
        if title_value and title_value not in title_samples:
            title_samples.append(title_value)
        compact = _compact_window_candidate(
            window,
            title=title,
            process=process,
            pid=pid,
            preferred_hwnd=preferred_hwnd,
            match=match,
            stable_count=stable_counts.get(hwnd),
        )
        for miss in compact.get("selector_filter_misses") or []:
            if not isinstance(miss, dict):
                continue
            criterion = str(miss.get("criterion") or "unknown")
            miss_counts[criterion] = miss_counts.get(criterion, 0) + 1
        suggestion = compact.get("selector_suggestion")
        if isinstance(suggestion, dict) and suggestion and suggestion not in suggestions:
            suggestions.append(suggestion)
        compacted.append(compact)

    compacted.sort(key=lambda item: int(item.get("selector_score") or 0), reverse=True)

    def top_counts(values: Dict[str, int]) -> List[Dict[str, Any]]:
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        return [{"value": key, "count": count} for key, count in ranked[:8]]

    recommendations: List[str] = []
    if visible_window_count <= 0:
        recommendations.append("No visible top-level windows were enumerated; check desktop/session state or wait longer.")
    if preferred_hwnd and miss_counts.get("hwnd"):
        recommendations.append("The requested HWND did not match a stable usable window; refresh list_windows or use auto_window by title/process.")
    if miss_counts.get("title"):
        recommendations.append("The requested title did not match visible windows; inspect near_windows titles or relax match=contains/regex.")
    if miss_counts.get("process"):
        recommendations.append("The requested process did not match visible windows; inspect observed_processes or use the process_name from near_windows.")
    if miss_counts.get("pid"):
        recommendations.append("The requested PID did not match visible windows; refresh the process/window handle after app restart.")
    if matched_candidates and not any(stable_counts.get(int(item.get("hwnd") or 0), 0) >= 2 for item in matched_candidates):
        recommendations.append("Matching windows were seen but did not remain stable long enough; increase timeout or stable wait interval.")
    if not recommendations and compacted:
        recommendations.append("Near visible windows were found; use selector_suggestions or pass near_windows[].hwnd directly to auto_window.")

    return {
        "visible_window_count": visible_window_count,
        "usable_window_count": len(windows),
        "matched_candidate_count": len(matched_candidates),
        "miss_counts": miss_counts,
        "observed_processes": top_counts(process_counts),
        "observed_titles": title_samples[:8],
        "selector_suggestions": suggestions[:5],
        "recommendations": recommendations,
    }


def _window_stability_signature(window: Dict[str, Any]) -> Tuple[int, int, int, int, int]:
    rect = window.get("rect") or {}
    return (
        int(window.get("hwnd") or 0),
        int(rect.get("left", 0) or 0),
        int(rect.get("top", 0) or 0),
        int(rect.get("right", 0) or 0),
        int(rect.get("bottom", 0) or 0),
    )


def _window_stability_score(
    window: Dict[str, Any],
    preferred_hwnd: Optional[int] = None,
    preferred_pid: Optional[int] = None,
    title: Optional[str] = None,
    process: Optional[str] = None,
    match: str = "contains",
) -> int:
    score = 0
    if preferred_hwnd and int(window.get("hwnd") or 0) == int(preferred_hwnd):
        score += 50
    if preferred_pid is not None and int(window.get("pid") or 0) == int(preferred_pid):
        score += 30
    if process is not None:
        proc_text = f'{window.get("process_name", "")} {window.get("process_path", "")}'
        if _matches_text(proc_text, process, match):
            score += 10
    if title is not None and _matches_text(str(window.get("title", "")), title, match):
        score += 5
    return score


def _wait_stable_window(
    hwnd: Optional[int] = None,
    title: Optional[str] = None,
    process: Optional[str] = None,
    pid: Optional[int] = None,
    timeout: float = 2.0,
    interval: float = 0.1,
    match: str = "contains",
    stable_ticks: int = 2,
) -> Dict[str, Any]:
    """Wait until a matching visible window survives repeated polls with stable bounds."""
    preferred_hwnd = int(hwnd or 0)
    preferred_pid = int(pid) if pid is not None else None
    deadline = time.time() + max(float(timeout), 0.0)
    required_ticks = max(int(stable_ticks), 1)
    attempts = 0
    visible_window_count = 0
    last_candidates: List[Dict[str, Any]] = []
    last_usable_windows: List[Dict[str, Any]] = []
    signatures: Dict[int, Tuple[int, int, int, int, int]] = {}
    stable_counts: Dict[int, int] = {}

    while True:
        attempts += 1
        candidates: List[Dict[str, Any]] = []
        seen_hwnds = set()

        if preferred_hwnd:
            direct = _window_info(preferred_hwnd)
            if (
                direct
                and _is_usable_window_info(direct)
                and _window_filter_matches(direct, title=title, process=process, pid=preferred_pid, match=match)
            ):
                candidates.append(direct)
                seen_hwnds.add(int(direct["hwnd"]))

        windows = enum_windows()
        visible_window_count = len(windows)
        usable_windows: List[Dict[str, Any]] = []
        for window in windows:
            candidate_hwnd = int(window.get("hwnd") or 0)
            if candidate_hwnd in seen_hwnds:
                continue
            if not _is_usable_window_info(window):
                continue
            usable_windows.append(window)
            if not _window_filter_matches(window, title=title, process=process, pid=preferred_pid, match=match):
                continue
            candidates.append(window)
            seen_hwnds.add(candidate_hwnd)

        last_candidates = candidates
        last_usable_windows = usable_windows
        for candidate in candidates:
            candidate_hwnd = int(candidate.get("hwnd") or 0)
            signature = _window_stability_signature(candidate)
            if signatures.get(candidate_hwnd) == signature:
                stable_counts[candidate_hwnd] = stable_counts.get(candidate_hwnd, 1) + 1
            else:
                signatures[candidate_hwnd] = signature
                stable_counts[candidate_hwnd] = 1

        stable = [
            candidate for candidate in candidates
            if stable_counts.get(int(candidate.get("hwnd") or 0), 0) >= required_ticks
        ]
        if stable:
            window = sorted(
                stable,
                key=lambda item: _window_stability_score(
                    item,
                    preferred_hwnd=preferred_hwnd,
                    preferred_pid=preferred_pid,
                    title=title,
                    process=process,
                    match=match,
                ),
                reverse=True,
            )[0]
            return {
                "ok": True,
                "attempts": attempts,
                "stable_ticks": stable_counts.get(int(window.get("hwnd") or 0), required_ticks),
                "window": window,
                "rebound": bool(preferred_hwnd and int(window.get("hwnd") or 0) != preferred_hwnd),
            }

        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))

    ranked_near = [
        _compact_window_candidate(
            window,
            title=title,
            process=process,
            pid=preferred_pid,
            preferred_hwnd=preferred_hwnd,
            match=match,
            stable_count=stable_counts.get(int(window.get("hwnd") or 0)),
        )
        for window in last_usable_windows
    ]
    ranked_near.sort(key=lambda item: int(item.get("selector_score") or 0), reverse=True)
    failure_summary = _window_find_failure_summary(
        last_usable_windows,
        title=title,
        process=process,
        pid=preferred_pid,
        preferred_hwnd=preferred_hwnd,
        match=match,
        visible_window_count=visible_window_count,
        matched_candidates=last_candidates,
        stable_counts=stable_counts,
    )
    return {
        "ok": False,
        "error": "timeout",
        "attempts": attempts,
        "visible_window_count": visible_window_count,
        "candidates": last_candidates[:5],
        "near_windows": ranked_near[:8],
        "failure_summary": failure_summary,
        "preferred_hwnd": preferred_hwnd or None,
        "pid": preferred_pid,
    }


def wait_window(
    title: Optional[str] = None,
    process: Optional[str] = None,
    timeout: float = 10.0,
    interval: float = 0.25,
    match: str = "contains",
) -> Dict[str, Any]:
    """Wait for a visible top-level window matching title and/or process name/path."""
    stable = _wait_stable_window(
        title=title,
        process=process,
        timeout=timeout,
        interval=interval,
        match=match,
        stable_ticks=2,
    )
    if stable.get("ok"):
        return {
            "ok": True,
            "attempts": stable.get("attempts"),
            "stable_ticks": stable.get("stable_ticks"),
            "window": stable.get("window"),
        }
    return stable


def _window_selector_value(source: Dict[str, Any], aliases: Tuple[str, ...]) -> Any:
    for key in aliases:
        value = source.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _window_selector_int(value: Any) -> Optional[int]:
    if value in (None, "", [], {}):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _window_selector_from_mapping(
    source: Dict[str, Any],
    fallback: Optional[Dict[str, Any]] = None,
    *,
    allow_hwnd: bool = True,
    include_name_alias: bool = False,
) -> Dict[str, Any]:
    """Clean a caller/suggestion mapping into stable top-level window selector fields."""
    source = source if isinstance(source, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    selector: Dict[str, Any] = {}
    title_aliases: Tuple[str, ...] = ("title", "window_title", "window-title")
    if include_name_alias:
        title_aliases = title_aliases + ("name",)
    title = _window_selector_value(source, title_aliases)
    process = _window_selector_value(
        source,
        (
            "process",
            "process_name",
            "process-name",
            "processName",
            "app_name",
            "app-name",
            "app",
            "path_or_name",
            "path-or-name",
        ),
    )
    pid = _window_selector_int(_window_selector_value(source, ("pid", "process_id", "process-id", "processId")))
    hwnd = _window_selector_int(_window_selector_value(source, ("hwnd", "window_hwnd", "window-hwnd", "target_hwnd", "target-hwnd")))
    if title not in (None, "", [], {}):
        selector["title"] = title
    if process not in (None, "", [], {}):
        selector["process"] = process
    if pid is not None:
        selector["pid"] = pid
    if allow_hwnd and hwnd:
        selector["hwnd"] = hwnd
    selector["match"] = source.get("match") or fallback.get("match") or "contains"
    return {key: value for key, value in selector.items() if value not in (None, "", [], {})}


def _compact_window_repair_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    compact = {
        "ok": result.get("ok"),
        "error": result.get("error"),
        "attempts": result.get("attempts"),
        "stable_ticks": result.get("stable_ticks"),
        "visible_window_count": result.get("visible_window_count"),
        "preferred_hwnd": result.get("preferred_hwnd"),
        "pid": result.get("pid"),
        "window": result.get("window"),
        "near_windows": result.get("near_windows"),
        "failure_summary": result.get("failure_summary"),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _window_selector_repair_success(
    stable: Dict[str, Any],
    selector: Dict[str, Any],
    *,
    source: str,
    suggestion: Optional[Dict[str, Any]] = None,
    original_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    window = stable.get("window") if isinstance(stable, dict) else None
    target_hwnd = int((window or {}).get("hwnd") or 0)
    result: Dict[str, Any] = {
        "ok": True,
        "selector_repair": True,
        "window_selector_repair": True,
        "source": source,
        "hwnd": target_hwnd,
        "target_hwnd": target_hwnd,
        "window": window,
        "attempts": stable.get("attempts"),
        "stable_ticks": stable.get("stable_ticks"),
        "selector": selector,
    }
    if stable.get("rebound") is not None:
        result["rebound"] = stable.get("rebound")
    if suggestion:
        result["suggestion"] = {
            key: value
            for key, value in suggestion.items()
            if key in ("hwnd", "title", "name", "process", "process_name", "pid", "match")
            and value not in (None, "", [], {})
        }
    if original_result:
        result["original_result"] = _compact_window_repair_result(original_result)
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def window_selector_repair_find(
    suggestion: Optional[Dict[str, Any]] = None,
    original: Optional[Dict[str, Any]] = None,
    *,
    timeout: Optional[float] = None,
    interval: Optional[float] = None,
    match: Optional[str] = None,
    stable_ticks: Optional[int] = None,
    allow_suggestion_hwnd: bool = False,
    probe_original: bool = True,
) -> Dict[str, Any]:
    """Repair a stale top-level window selector using wait_window diagnostics."""
    original = dict(original or {})
    suggestion = dict(suggestion or {})
    if not original and not suggestion:
        return {
            "ok": False,
            "error": "suggestion or original required",
            "selector_repair": True,
            "window_selector_repair": True,
        }

    resolved_timeout = float(timeout if timeout is not None else original.get("timeout", 10.0) or 10.0)
    resolved_interval = float(interval if interval is not None else original.get("interval", 0.25) or 0.25)
    resolved_stable_ticks = int(stable_ticks if stable_ticks is not None else original.get("stable_ticks", original.get("stable-ticks", 2)) or 2)
    resolved_match = match or suggestion.get("match") or original.get("match") or "contains"
    original_selector = _window_selector_from_mapping(original, allow_hwnd=True, include_name_alias=True)
    if match:
        original_selector["match"] = match

    original_result: Dict[str, Any] = {}
    if _coerce_bool(probe_original, True) and any(
        original_selector.get(key) not in (None, "", [], {})
        for key in ("hwnd", "title", "process", "pid")
    ):
        original_result = _wait_stable_window(
            hwnd=original_selector.get("hwnd"),
            title=original_selector.get("title"),
            process=original_selector.get("process"),
            pid=original_selector.get("pid"),
            timeout=resolved_timeout,
            interval=resolved_interval,
            match=original_selector.get("match", resolved_match),
            stable_ticks=resolved_stable_ticks,
        )
        if original_result.get("ok") and isinstance(original_result.get("window"), dict):
            return _window_selector_repair_success(
                original_result,
                original_selector,
                source="original",
                suggestion=suggestion,
            )
        if not suggestion:
            summary = original_result.get("failure_summary") if isinstance(original_result.get("failure_summary"), dict) else {}
            first_suggestion = (summary.get("selector_suggestions") or [None])[0]
            if isinstance(first_suggestion, dict):
                suggestion = dict(first_suggestion)

    suggestion_has_hwnd = _window_selector_int(_window_selector_value(suggestion, ("hwnd", "window_hwnd", "window-hwnd", "target_hwnd", "target-hwnd"))) is not None
    suggested_without_hwnd = _window_selector_from_mapping(
        suggestion,
        original_selector,
        allow_hwnd=False,
        include_name_alias=True,
    )
    suggestion_has_stable_filter = any(suggested_without_hwnd.get(key) not in (None, "", [], {}) for key in ("title", "process", "pid"))
    suggestion_selector = _window_selector_from_mapping(
        suggestion,
        original_selector,
        allow_hwnd=bool(allow_suggestion_hwnd or suggestion_has_stable_filter),
        include_name_alias=True,
    )
    if match:
        suggestion_selector["match"] = match
    elif suggestion_selector.get("match") is None:
        suggestion_selector["match"] = resolved_match

    if not any(suggestion_selector.get(key) not in (None, "", [], {}) for key in ("hwnd", "title", "process", "pid")):
        error = "window_selector_suggestion_has_no_searchable_fields"
        if suggestion_has_hwnd and not allow_suggestion_hwnd:
            error = "window_selector_suggestion_only_has_hwnd"
        return {
            "ok": False,
            "error": error,
            "selector_repair": True,
            "window_selector_repair": True,
            "selector": suggestion_selector,
            "suggestion": suggestion,
            **({"original_result": _compact_window_repair_result(original_result)} if original_result else {}),
        }

    repaired = _wait_stable_window(
        hwnd=suggestion_selector.get("hwnd"),
        title=suggestion_selector.get("title"),
        process=suggestion_selector.get("process"),
        pid=suggestion_selector.get("pid"),
        timeout=resolved_timeout,
        interval=resolved_interval,
        match=suggestion_selector.get("match", resolved_match),
        stable_ticks=resolved_stable_ticks,
    )
    if repaired.get("ok") and isinstance(repaired.get("window"), dict):
        return _window_selector_repair_success(
            repaired,
            suggestion_selector,
            source="suggestion",
            suggestion=suggestion,
            original_result=original_result,
        )

    repaired["ok"] = False
    repaired.setdefault("error", "no_matching_window_after_selector_repair")
    repaired["selector_repair"] = True
    repaired["window_selector_repair"] = True
    repaired["selector"] = suggestion_selector
    repaired["suggestion"] = {
        key: value
        for key, value in suggestion.items()
        if key in ("hwnd", "title", "name", "process", "process_name", "pid", "match")
        and value not in (None, "", [], {})
    }
    if original_result:
        repaired["original_result"] = _compact_window_repair_result(original_result)
    return repaired


def _auto_window_first_window(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(result, dict):
        return None
    window = result.get("window")
    if isinstance(window, dict) and window.get("hwnd"):
        return window
    value = result.get("value")
    if isinstance(value, dict):
        window = value.get("window")
        if isinstance(window, dict) and window.get("hwnd"):
            return window
    selected_result = result.get("selected_result")
    if isinstance(selected_result, dict):
        return _auto_window_first_window(selected_result.get("result") if isinstance(selected_result.get("result"), dict) else selected_result)
    candidates = result.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict) or not candidate.get("selected"):
                continue
            for item in reversed(candidate.get("results") or []):
                found = _auto_window_first_window(item.get("result") if isinstance(item, dict) else item)
                if found:
                    return found
    return None


def _auto_window_failure_diagnostics(steps: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(steps, dict):
        return {}
    near_windows: List[Dict[str, Any]] = []
    selector_suggestions: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    observed_processes: List[Dict[str, Any]] = []
    observed_titles: List[str] = []
    miss_counts: Dict[str, int] = {}
    visible_window_count = 0
    matched_candidate_count = 0
    for step in steps.values():
        if not isinstance(step, dict):
            continue
        try:
            visible_window_count = max(visible_window_count, int(step.get("visible_window_count") or 0))
        except Exception:
            pass
        for window in step.get("near_windows") or []:
            if isinstance(window, dict) and window and window not in near_windows:
                near_windows.append(window)
        summary = step.get("failure_summary") if isinstance(step.get("failure_summary"), dict) else {}
        if not summary:
            continue
        try:
            matched_candidate_count += int(summary.get("matched_candidate_count") or 0)
        except Exception:
            pass
        for key, value in (summary.get("miss_counts") or {}).items():
            miss_counts[str(key)] = miss_counts.get(str(key), 0) + int(value or 0)
        for process_item in summary.get("observed_processes") or []:
            if isinstance(process_item, dict) and process_item not in observed_processes:
                observed_processes.append(process_item)
        for title_item in summary.get("observed_titles") or []:
            title_text = str(title_item or "")
            if title_text and title_text not in observed_titles:
                observed_titles.append(title_text)
        for suggestion in summary.get("selector_suggestions") or []:
            if isinstance(suggestion, dict) and suggestion and suggestion not in selector_suggestions:
                selector_suggestions.append(suggestion)
        for recommendation in summary.get("recommendations") or []:
            _batch_auto_plan_unique_append(recommendations, recommendation)
    near_windows.sort(key=lambda item: int(item.get("selector_score") or 0), reverse=True)
    result = {
        "visible_window_count": visible_window_count,
        "matched_candidate_count": matched_candidate_count,
        "miss_counts": miss_counts,
        "observed_processes": observed_processes[:8],
        "observed_titles": observed_titles[:8],
        "selector_suggestions": selector_suggestions[:5],
        "near_windows": near_windows[:8],
        "recommendations": recommendations,
    }
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def auto_window(
    hwnd: Optional[int] = None,
    title: Optional[str] = None,
    process: Optional[str] = None,
    app: Optional[str] = None,
    path: Optional[str] = None,
    timeout: float = 10.0,
    interval: float = 0.25,
    match: str = "contains",
    activate: bool = True,
    restore: bool = True,
    boundary: bool = True,
    helper: bool = False,
    observe_window: bool = False,
    include_a11y: bool = False,
    ocr: bool = False,
) -> Dict[str, Any]:
    """Acquire or launch a stable top-level window and optionally repair foreground state."""
    steps: Dict[str, Any] = {}
    window: Optional[Dict[str, Any]] = None
    source = ""
    requested_hwnd = int(hwnd or 0)
    launch_target = app or path

    if requested_hwnd:
        stable = _wait_stable_window(
            hwnd=requested_hwnd,
            title=title,
            process=process,
            timeout=timeout,
            interval=interval,
            match=match,
            stable_ticks=2,
        )
        steps["existing_window"] = stable
        if stable.get("ok") and isinstance(stable.get("window"), dict):
            window = stable.get("window")
            source = "hwnd"

    if window is None and (title is not None or process is not None):
        waited = wait_window(title=title, process=process, timeout=timeout, interval=interval, match=match)
        steps["wait_window"] = waited
        if waited.get("ok") and isinstance(waited.get("window"), dict):
            window = waited.get("window")
            source = "wait_window"

    if window is None and launch_target:
        launched = launch_app(str(launch_target), timeout=timeout)
        steps["launch"] = launched
        launched_window = launched.get("window") if isinstance(launched, dict) else None
        if isinstance(launched_window, dict) and launched_window.get("hwnd"):
            window = launched_window
            source = "launch"
        elif title is not None or process is not None:
            waited_after_launch = wait_window(
                title=title,
                process=process,
                timeout=timeout,
                interval=interval,
                match=match,
            )
            steps["wait_after_launch"] = waited_after_launch
            if waited_after_launch.get("ok") and isinstance(waited_after_launch.get("window"), dict):
                window = waited_after_launch.get("window")
                source = "launch_wait"

    if window is None:
        foreground = foreground_window()
        steps["foreground"] = foreground
        if isinstance(foreground, dict) and foreground.get("hwnd") and not foreground.get("error"):
            if _window_filter_matches(foreground, title=title, process=process, match=match):
                window = foreground
                source = "foreground"

    if not isinstance(window, dict) or not window.get("hwnd"):
        diagnostics = _auto_window_failure_diagnostics(steps)
        return {
            "ok": False,
            "error": "window_not_found",
            "message": "auto_window could not acquire a stable visible window",
            "requested": {
                "hwnd": requested_hwnd or None,
                "title": title,
                "process": process,
                "app": launch_target,
                "timeout": timeout,
                "match": match,
            },
            **({"near_windows": diagnostics.get("near_windows")} if diagnostics.get("near_windows") else {}),
            **({"failure_summary": diagnostics} if diagnostics else {}),
            "steps": steps,
        }

    target_hwnd = int(window.get("hwnd") or 0)
    _state_target(target_hwnd)
    if activate:
        steps["focus_hwnd"] = focus_hwnd(target_hwnd, timeout=min(max(float(timeout), 0.1), 2.0), restore=restore)
        refreshed = _window_info(target_hwnd)
        if refreshed:
            window = refreshed
    boundary = bool(boundary or helper)
    if boundary:
        steps["control_boundary"] = control_boundary(target_hwnd)
    if helper:
        elevated = bool((steps.get("control_boundary") or {}).get("needs_elevation"))
        steps["helper_status"] = helper_status(elevated=elevated, start=elevated)
    if observe_window:
        steps["observe"] = observe(
            target_hwnd,
            include_accessibility=include_a11y,
            include_ocr=ocr,
            ocr_on_accessibility_error=ocr,
        )

    return {
        "ok": True,
        "source": source or "unknown",
        "hwnd": target_hwnd,
        "window": window,
        "target_hwnd": target_hwnd,
        "state_target": target_hwnd,
        "activated": bool(activate),
        "boundary_checked": bool(boundary),
        "helper_checked": bool(helper),
        "observed": bool(observe_window),
        "steps": steps,
    }


WIN_EVENT_NAMES = {
    EVENT_SYSTEM_FOREGROUND: "system-foreground",
    EVENT_SYSTEM_MENUSTART: "system-menu-start",
    EVENT_SYSTEM_MENUEND: "system-menu-end",
    EVENT_SYSTEM_DIALOGSTART: "system-dialog-start",
    EVENT_SYSTEM_DIALOGEND: "system-dialog-end",
    EVENT_OBJECT_CREATE: "object-create",
    EVENT_OBJECT_DESTROY: "object-destroy",
    EVENT_OBJECT_SHOW: "object-show",
    EVENT_OBJECT_HIDE: "object-hide",
    EVENT_OBJECT_REORDER: "object-reorder",
    EVENT_OBJECT_FOCUS: "object-focus",
    EVENT_OBJECT_SELECTION: "object-selection",
    EVENT_OBJECT_LOCATIONCHANGE: "object-location-change",
    EVENT_OBJECT_NAMECHANGE: "object-name-change",
    EVENT_OBJECT_VALUECHANGE: "object-value-change",
}

WIN_EVENT_VALUES = {name: event for event, name in WIN_EVENT_NAMES.items()}
WIN_EVENT_VALUES.update({
    "foreground": EVENT_SYSTEM_FOREGROUND,
    "menu-start": EVENT_SYSTEM_MENUSTART,
    "menu-end": EVENT_SYSTEM_MENUEND,
    "dialog-start": EVENT_SYSTEM_DIALOGSTART,
    "dialog-end": EVENT_SYSTEM_DIALOGEND,
    "create": EVENT_OBJECT_CREATE,
    "destroy": EVENT_OBJECT_DESTROY,
    "show": EVENT_OBJECT_SHOW,
    "hide": EVENT_OBJECT_HIDE,
    "focus": EVENT_OBJECT_FOCUS,
    "selection": EVENT_OBJECT_SELECTION,
    "value-change": EVENT_OBJECT_VALUECHANGE,
    "name-change": EVENT_OBJECT_NAMECHANGE,
    "location-change": EVENT_OBJECT_LOCATIONCHANGE,
})


def _parse_win_event(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().lower().replace("_", "-")
    if text in WIN_EVENT_VALUES:
        return WIN_EVENT_VALUES[text]
    return int(text, 0)


def _event_window_candidates(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for key in ("event_window", "root_window", "root_owner_window", "window"):
        window = event.get(key)
        if isinstance(window, dict) and window:
            candidates.append(window)
    return candidates


def _event_filter_matches(
    event: Dict[str, Any],
    hwnd: Optional[int] = None,
    pid: Optional[int] = None,
    title: Optional[str] = None,
    class_name: Optional[str] = None,
    match: str = "contains",
) -> bool:
    if hwnd is not None:
        candidates = {int(event.get("hwnd") or 0), int(event.get("root_hwnd") or 0), int(event.get("root_owner_hwnd") or 0)}
        if int(hwnd) not in candidates:
            return False
    windows = _event_window_candidates(event)
    if pid is not None and int(event.get("pid") or 0) != int(pid) and not any(int(w.get("pid") or 0) == int(pid) for w in windows):
        return False
    if title is not None and not any(_matches_text(str(w.get("title", "")), title, match) for w in windows):
        return False
    if class_name is not None and not any(_matches_text(str(w.get("class_name", "")), class_name, match) for w in windows):
        return False
    return True


def wait_event(
    event: Optional[Any] = None,
    hwnd: Optional[int] = None,
    pid: Optional[int] = None,
    title: Optional[str] = None,
    class_name: Optional[str] = None,
    timeout: float = 5.0,
    limit: int = 1,
    match: str = "contains",
    include_children: bool = True,
    skip_own_process: bool = True,
) -> Dict[str, Any]:
    """Wait for WinEvent notifications such as focus, show/hide, menu, dialog, or foreground."""
    event_min = EVENT_MIN
    event_max = EVENT_MAX
    if event is not None:
        event_min = event_max = _parse_win_event(event)
    events: List[Dict[str, Any]] = []
    raw_events: List[Dict[str, Any]] = []
    accepted_keys = set()
    callback_refs: List[Any] = []
    target_count = max(int(limit), 1)
    raw_cap = max(target_count * 50, 200)

    def _hydrate_event(item: Dict[str, Any]) -> None:
        event_hwnd_int = int(item.get("hwnd") or 0)
        root_hwnd = int(item.get("root_hwnd") or 0)
        root_owner_hwnd = int(item.get("root_owner_hwnd") or 0)
        event_window = _window_info(event_hwnd_int) if event_hwnd_int else None
        root_window = _window_info(root_hwnd) if root_hwnd else None
        root_owner_window = _window_info(root_owner_hwnd) if root_owner_hwnd else None
        window = root_window or event_window or root_owner_window or {}
        item.update({
            "pid": int(window.get("pid") or 0),
            "window": window,
            "event_window": event_window,
            "root_window": root_window,
            "root_owner_window": root_owner_window,
        })

    def _event_key(item: Dict[str, Any]) -> Tuple[int, int, int, int, int]:
        return (
            int(item.get("event") or 0),
            int(item.get("hwnd") or 0),
            int(item.get("object_id") or 0),
            int(item.get("child_id") or 0),
            int(item.get("time") or 0),
        )

    def _collect_matches() -> None:
        for item in list(raw_events):
            if len(events) >= target_count:
                break
            key = _event_key(item)
            if key in accepted_keys:
                continue
            _hydrate_event(item)
            if _event_filter_matches(item, hwnd=hwnd, pid=pid, title=title, class_name=class_name, match=match):
                accepted_keys.add(key)
                events.append(dict(item))

    def _record(win_event, event_hwnd, object_id, child_id, event_thread, event_time):
        event_hwnd_int = int(event_hwnd or 0)
        root_hwnd = int(user32.GetAncestor(event_hwnd_int, GA_ROOT) or event_hwnd_int or 0) if event_hwnd_int else 0
        root_owner_hwnd = int(user32.GetAncestor(event_hwnd_int, GA_ROOTOWNER) or root_hwnd or 0) if event_hwnd_int else 0
        item = {
            "event": int(win_event),
            "event_name": WIN_EVENT_NAMES.get(int(win_event), hex(int(win_event))),
            "hwnd": event_hwnd_int,
            "root_hwnd": root_hwnd,
            "root_owner_hwnd": root_owner_hwnd,
            "object_id": int(object_id),
            "child_id": int(child_id),
            "thread_id": int(event_thread),
            "time": int(event_time),
        }
        raw_events.append(item)
        if len(raw_events) > raw_cap:
            del raw_events[: len(raw_events) - raw_cap]

    @WinEventProcType
    def callback(_hook, win_event, event_hwnd, object_id, child_id, event_thread, event_time):
        try:
            if not include_children and int(object_id) not in (0, OBJID_CLIENT_SIGNED, OBJID_CLIENT):
                return
            _record(win_event, event_hwnd, object_id, child_id, event_thread, event_time)
        except Exception:
            pass

    callback_refs.append(callback)
    flags = WINEVENT_OUTOFCONTEXT
    if skip_own_process:
        flags |= WINEVENT_SKIPOWNPROCESS
    hook = user32.SetWinEventHook(event_min, event_max, None, callback, 0, 0, flags)
    if not hook:
        return {"error": "SetWinEventHook failed", "event": event}
    deadline = time.time() + max(float(timeout), 0.0)
    msg = ctypes.wintypes.MSG()
    try:
        while len(events) < target_count and time.time() < deadline:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
                _collect_matches()
                if len(events) >= target_count:
                    break
            _collect_matches()
            if len(events) >= target_count:
                break
            time.sleep(0.01)
    finally:
        user32.UnhookWinEvent(hook)
        callback_refs.clear()
    return {
        "ok": bool(events),
        "event": _parse_win_event(event) if event is not None else None,
        "event_name": WIN_EVENT_NAMES.get(_parse_win_event(event), str(event)) if event is not None else "any",
        "count": len(events),
        "raw_count": len(raw_events),
        "events": events[:target_count],
        "timeout": timeout,
    }


def child_windows(
    hwnd: int,
    include_invisible: bool = False,
    include_text: bool = False,
    max_count: int = 500,
) -> Dict[str, Any]:
    """Enumerate native Win32 child HWNDs for legacy controls and dialogs."""
    target = _win32_window_info(hwnd)
    if not target:
        return {"error": f"Window {hwnd} not found"}
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/child_windows")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/child_windows",
            {
                "hwnd": hwnd,
                "include_invisible": include_invisible,
                "include_text": include_text,
                "max_count": max_count,
            },
            elevated=helper_elevated,
        )
        if helper_result.get("ok"):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
    return _child_windows_direct(hwnd, target, include_invisible=include_invisible, include_text=include_text, max_count=max_count)


def _child_windows_direct(
    hwnd: int,
    target: Optional[Dict[str, Any]] = None,
    include_invisible: bool = False,
    include_text: bool = False,
    max_count: int = 500,
) -> Dict[str, Any]:
    """Enumerate child HWNDs without helper routing."""
    target = target or _win32_window_info(hwnd)
    if not target:
        return {"error": f"Window {hwnd} not found"}
    children: List[Dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(child, _):
        try:
            if len(children) >= max_count:
                return False
            info = _win32_window_info(int(child), include_text=include_text)
            if not info:
                return True
            if not include_invisible and not info.get("visible", False):
                return True
            children.append(info)
        except Exception:
            pass
        return True

    user32.EnumChildWindows(hwnd, callback, None)
    return {"target": target, "count": len(children), "children": children}


_WIN32_KIND_ALIASES: Dict[str, Tuple[str, ...]] = {
    "button": ("button",),
    "checkbox": ("checkbox", "3state"),
    "check_box": ("checkbox", "3state"),
    "radio": ("radio",),
    "radiobutton": ("radio",),
    "radio_button": ("radio",),
    "edit": ("edit", "richedit"),
    "text": ("edit", "richedit", "static"),
    "input": ("edit", "richedit", "combobox", "comboboxex"),
    "richedit": ("richedit",),
    "rich_edit": ("richedit",),
    "static": ("static",),
    "label": ("static",),
    "link": ("syslink",),
    "syslink": ("syslink",),
    "hotkey": ("hotkey",),
    "hot_key": ("hotkey",),
    "combobox": ("combobox", "comboboxex"),
    "combo": ("combobox", "comboboxex"),
    "combo_box": ("combobox", "comboboxex"),
    "comboboxex": ("comboboxex",),
    "listbox": ("listbox",),
    "list": ("listbox", "listview"),
    "listview": ("listview",),
    "list_view": ("listview",),
    "tree": ("treeview",),
    "treeview": ("treeview",),
    "tree_view": ("treeview",),
    "tab": ("tab",),
    "tabcontrol": ("tab",),
    "tab_control": ("tab",),
    "toolbar": ("toolbar",),
    "tool_bar": ("toolbar",),
    "header": ("header",),
    "status": ("statusbar",),
    "statusbar": ("statusbar",),
    "status_bar": ("statusbar",),
    "slider": ("trackbar",),
    "trackbar": ("trackbar",),
    "scrollbar": ("scrollbar",),
    "scroll_bar": ("scrollbar",),
    "spinner": ("updown",),
    "updown": ("updown",),
    "up_down": ("updown",),
    "progress": ("progress",),
    "progressbar": ("progress",),
    "progress_bar": ("progress",),
    "datetime": ("datetime",),
    "date_time": ("datetime",),
    "datepicker": ("datetime",),
    "date_picker": ("datetime",),
    "calendar": ("monthcal",),
    "monthcal": ("monthcal",),
    "month_calendar": ("monthcal",),
    "ipaddress": ("ipaddress",),
    "ip_address": ("ipaddress",),
    "tooltip": ("tooltip",),
    "tool_tip": ("tooltip",),
}


def _normalize_win32_kind(value: Optional[Any]) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _win32_kind_matches(kind: Any, class_name: Any, control_type: Optional[Any]) -> bool:
    wanted = _normalize_win32_kind(control_type)
    if not wanted:
        return True
    normalized_kind = _normalize_win32_kind(kind)
    normalized_class = _normalize_win32_kind(class_name)
    accepted = _WIN32_KIND_ALIASES.get(wanted, (wanted,))
    for candidate in accepted:
        normalized_candidate = _normalize_win32_kind(candidate)
        if normalized_candidate in (normalized_kind, normalized_class):
            return True
        if normalized_candidate and normalized_candidate in normalized_class:
            return True
    return False


def _win32_find_text_values(window_info: Dict[str, Any], control_info: Dict[str, Any]) -> List[Any]:
    values: List[Any] = [
        window_info.get("title"),
        window_info.get("class_name"),
        window_info.get("control_id"),
        control_info.get("current_text"),
        control_info.get("text"),
        control_info.get("value"),
        control_info.get("date"),
        control_info.get("datetime"),
        control_info.get("hotkey"),
    ]
    text_info = window_info.get("text")
    if isinstance(text_info, dict):
        values.append(text_info.get("text"))
    elif text_info is not None:
        values.append(text_info)
    values.extend(_selector_item_texts(_smart_item_sources(control_info)))
    return values


def _compact_win32_control_candidate(candidate: Dict[str, Any], diagnostic: bool = False) -> Dict[str, Any]:
    if diagnostic:
        return candidate
    control = candidate.get("control") if isinstance(candidate.get("control"), dict) else {}
    compact_control = {
        key: control.get(key)
        for key in (
            "kind",
            "count",
            "selected_index",
            "checked",
            "check_state",
            "position",
            "value",
            "current_text",
            "date",
            "datetime",
            "hotkey",
            "has_checkboxes",
            "column_count",
        )
        if key in control
    }
    if isinstance(control.get("items"), list):
        compact_control["items_preview"] = control.get("items")[:8]
    if isinstance(control.get("flat"), list):
        compact_control["flat_preview"] = control.get("flat")[:8]
    if isinstance(control.get("buttons"), list):
        compact_control["buttons_preview"] = control.get("buttons")[:8]
    if isinstance(control.get("links"), list):
        compact_control["links_preview"] = control.get("links")[:8]
    return {
        "ordinal": candidate.get("ordinal"),
        "hwnd": candidate.get("hwnd"),
        "kind": candidate.get("kind"),
        "class_name": candidate.get("class_name"),
        "title": candidate.get("title"),
        "control_id": candidate.get("control_id"),
        "rect": candidate.get("rect"),
        "selector_score": candidate.get("selector_score"),
        "selector_reasons": candidate.get("selector_reasons"),
        "selector_filter_misses": candidate.get("selector_filter_misses"),
        "selector_suggestion": candidate.get("selector_suggestion"),
        "text_preview": candidate.get("text_preview"),
        "source": candidate.get("source"),
        "window": _compact_window_info(candidate.get("window") if isinstance(candidate.get("window"), dict) else None),
        "control": compact_control,
    }


def _win32_control_text_preview(window_info: Dict[str, Any], control_info: Dict[str, Any], limit: int = 8) -> List[str]:
    values: List[str] = []
    seen: set[str] = set()
    for value in _win32_find_text_values(window_info, control_info):
        text = _selector_text(value).strip()
        if not text:
            continue
        key = _selector_norm(text)
        if key in seen:
            continue
        seen.add(key)
        values.append(_shorten(text, 120))
        if len(values) >= limit:
            break
    return values


def _win32_control_selector_suggestion(candidate: Dict[str, Any]) -> Dict[str, Any]:
    suggestion: Dict[str, Any] = {}
    control_id = candidate.get("control_id")
    if control_id not in (None, "", 0, "0"):
        suggestion["automation_id"] = control_id
    kind = str(candidate.get("kind") or "").strip()
    if kind:
        suggestion["control_type"] = kind
    class_name = str(candidate.get("class_name") or "").strip()
    if class_name:
        suggestion["class_name"] = class_name
    text_preview = candidate.get("text_preview") if isinstance(candidate.get("text_preview"), list) else []
    if text_preview:
        suggestion["name"] = text_preview[0]
        suggestion["match"] = "exact"
    return suggestion


def _win32_control_find_failure_summary(
    near_ranked: List[Dict[str, Any]],
    *,
    scanned: int,
    matched_before_min_score: int,
    min_score: Optional[int],
) -> Dict[str, Any]:
    miss_counts: Dict[str, int] = {}
    kind_counts: Dict[str, int] = {}
    class_counts: Dict[str, int] = {}
    suggestions: List[Dict[str, Any]] = []
    for candidate in near_ranked:
        kind = str(candidate.get("kind") or "").strip() or "<unknown>"
        class_name = str(candidate.get("class_name") or "").strip() or "<unknown>"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        class_counts[class_name] = class_counts.get(class_name, 0) + 1
        for miss in candidate.get("selector_filter_misses") or []:
            if not isinstance(miss, dict):
                continue
            criterion = str(miss.get("criterion") or "unknown")
            miss_counts[criterion] = miss_counts.get(criterion, 0) + 1
        suggestion = candidate.get("selector_suggestion")
        if isinstance(suggestion, dict) and suggestion and suggestion not in suggestions:
            suggestions.append(suggestion)

    recommendations: List[str] = []
    if scanned <= 0:
        recommendations.append("No visible native HWND controls were scanned; retry with include_invisible=true or inspect child_windows.")
    if matched_before_min_score and min_score is not None:
        recommendations.append("Controls matched the selector before min_score filtering; lower min_score or inspect near_matches selector_score.")
    if miss_counts.get("control_type"):
        recommendations.append("The requested control_type filtered out candidates; inspect observed_kinds/classes or relax --type.")
    if miss_counts.get("name"):
        recommendations.append("The requested name/text did not match candidate text; inspect text_preview or try match=contains/regex.")
    if miss_counts.get("automation_id"):
        recommendations.append("The requested automation_id did not match ControlId values; inspect selector_suggestion automation_id fields.")
    if miss_counts.get("class_name"):
        recommendations.append("The requested class_name did not match candidates; inspect observed_classes or use a broader class match.")
    if miss_counts.get("state"):
        recommendations.append("The requested state/expected value did not match current native control state; inspect control previews before acting.")
    if not recommendations and near_ranked:
        recommendations.append("Near native controls were found; use selector_suggestions or pass a returned near_matches[].hwnd directly to win32_control_info/action.")

    def top_counts(values: Dict[str, int]) -> List[Dict[str, Any]]:
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        return [{"value": key, "count": count} for key, count in ranked[:8]]

    return {
        "scanned": scanned,
        "near_count": len(near_ranked),
        "matched_before_min_score": matched_before_min_score,
        "miss_counts": miss_counts,
        "observed_kinds": top_counts(kind_counts),
        "observed_classes": top_counts(class_counts),
        "selector_suggestions": suggestions[:5],
        "recommendations": recommendations,
    }


def _win32_repair_requested(repair: Any = None, *repair_options: Any) -> bool:
    if repair is not None:
        return _coerce_bool(repair, False)
    return any(value is not None for value in repair_options)


def _win32_control_find_direct(
    hwnd: int,
    *,
    name: Optional[str] = None,
    automation_id: Optional[Any] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    text: Optional[str] = None,
    value: Optional[str] = None,
    state: Optional[Any] = None,
    expected: Any = None,
    match: str = "contains",
    include_invisible: bool = False,
    include_self: bool = True,
    limit: int = 20,
    min_score: Optional[int] = None,
    timeout_ms: int = 250,
    max_items: int = 200,
    max_children: int = 1000,
    diagnostic: bool = False,
) -> Dict[str, Any]:
    target = _win32_window_info(hwnd, include_text=True)
    if not target:
        return {"ok": False, "error": f"Window/control {hwnd} not found", "hwnd": hwnd}

    candidates: List[Dict[str, Any]] = []
    near_pool: List[Dict[str, Any]] = []
    scanned = 0
    effective_name = name if name is not None else text
    state_name = _normalize_win32_wait_state(state) if state is not None else None
    expected_value = _coerce_win32_wait_expected(state_name, expected) if state_name else expected

    def consider(window_info: Dict[str, Any], source: str) -> None:
        nonlocal scanned
        child_hwnd = int(window_info.get("hwnd") or 0)
        if not child_hwnd:
            return
        if not include_invisible and not bool(window_info.get("visible", False)):
            return
        scanned += 1
        control_info = win32_control_info(child_hwnd, timeout_ms=timeout_ms, max_items=max_items)
        if "error" in control_info:
            return
        kind = str(control_info.get("kind") or "").lower()
        child_class = str(window_info.get("class_name") or "")
        control_id = str(window_info.get("control_id") or "")
        text_values = _win32_find_text_values(window_info, control_info)
        filter_misses: List[Dict[str, Any]] = []
        if automation_id is not None and not _selector_text_matches(control_id, automation_id, match):
            filter_misses.append({"criterion": "automation_id", "expected": automation_id, "actual": control_id})
        if class_name is not None and not _selector_text_matches(child_class, class_name, match):
            filter_misses.append({"criterion": "class_name", "expected": class_name, "actual": child_class})
        if not _win32_kind_matches(kind, child_class, control_type):
            filter_misses.append({"criterion": "control_type", "expected": control_type, "actual": kind or child_class})
        if effective_name is not None and not _selector_any_text_matches(
            text_values,
            effective_name,
            match,
        ):
            filter_misses.append({
                "criterion": "name",
                "expected": effective_name,
                "actual_preview": _win32_control_text_preview(window_info, control_info, limit=5),
            })
        if value is not None:
            value_candidates = [
                control_info.get("value"),
                control_info.get("current_text"),
                control_info.get("text"),
                control_info.get("date"),
                control_info.get("datetime"),
                control_info.get("hotkey"),
            ]
            text_info = window_info.get("text")
            if isinstance(text_info, dict):
                value_candidates.append(text_info.get("text"))
            if not _selector_any_text_matches(value_candidates, value, match):
                filter_misses.append({
                    "criterion": "value",
                    "expected": value,
                    "actual_preview": [_shorten(_selector_text(item), 120) for item in value_candidates if _selector_text(item)][:5],
                })
        if state_name:
            actual = _win32_control_wait_state_value(control_info, control_info, state_name)
            if actual is None and state_name not in control_info:
                filter_misses.append({"criterion": "state", "state": state_name, "expected": expected_value, "actual": None, "reason": "missing"})
            elif not _win32_control_wait_match(actual, expected_value, state_name, match=match):
                filter_misses.append({"criterion": "state", "state": state_name, "expected": expected_value, "actual": actual})
        candidate = {
            "ordinal": len(near_pool),
            "hwnd": child_hwnd,
            "kind": kind,
            "class_name": child_class,
            "title": str(window_info.get("title") or ""),
            "control_id": window_info.get("control_id"),
            "rect": window_info.get("rect"),
            "window": window_info,
            "control": control_info,
            "source": source,
            "selector_filter_misses": filter_misses,
        }
        candidate["text_preview"] = _win32_control_text_preview(window_info, control_info)
        candidate["selector_suggestion"] = _win32_control_selector_suggestion(candidate)
        near_pool.append(candidate)
        if not filter_misses:
            matched = dict(candidate)
            matched["ordinal"] = len(candidates)
            candidates.append(matched)

    if include_self:
        consider(target, "self")

    children_result = _child_windows_direct(
        hwnd,
        target=target,
        include_invisible=include_invisible,
        include_text=True,
        max_count=max_children,
    )
    for child in list(children_result.get("children") or []):
        consider(child, "child")

    ranked_before_min_score = _rank_native_candidates(
        candidates,
        name=effective_name,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        match=match,
    )
    ranked = ranked_before_min_score
    threshold_value: Optional[int] = None
    if min_score is not None:
        try:
            threshold = int(min_score)
            threshold_value = threshold
            ranked = [item for item in ranked if int(item.get("selector_score") or 0) >= threshold]
        except Exception:
            pass
    limit_value = max(int(limit or 20), 0)
    matches = [_compact_win32_control_candidate(item, diagnostic=diagnostic) for item in ranked[:limit_value or len(ranked)]]
    near_ranked = _rank_native_candidates(
        near_pool,
        name=effective_name,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        match=match,
    )
    near_limit = min(len(near_ranked), max(limit_value, 5))
    near_matches = [_compact_win32_control_candidate(item, diagnostic=False) for item in near_ranked[:near_limit]]
    result = {
        "ok": bool(matches),
        "hwnd": hwnd,
        "target": target if diagnostic else _compact_window_info(target),
        "count": len(matches),
        "total_candidates": len(candidates),
        "available_candidates": len(near_pool),
        "filtered_candidates": max(len(near_pool) - len(candidates), 0),
        "scanned": scanned,
        "match": match,
        "criteria": {
            "name": name,
            "text": text,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "value": value,
            "state": state_name,
            "expected": expected_value,
            "include_invisible": include_invisible,
            "include_self": include_self,
        },
        "matches": matches,
        "near_matches": near_matches if not matches else [],
    }
    if not matches:
        result["failure_summary"] = _win32_control_find_failure_summary(
            near_ranked,
            scanned=scanned,
            matched_before_min_score=len(ranked_before_min_score),
            min_score=threshold_value,
        )
    return result


def win32_control_find(
    hwnd: int,
    name: Optional[str] = None,
    automation_id: Optional[Any] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    text: Optional[str] = None,
    value: Optional[str] = None,
    state: Optional[Any] = None,
    expected: Any = None,
    match: str = "contains",
    include_invisible: bool = False,
    include_self: bool = True,
    limit: int = 20,
    min_score: Optional[int] = None,
    timeout_ms: int = 250,
    max_items: int = 200,
    max_children: int = 1000,
    diagnostic: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Find native Win32 child controls by HWND metadata, class, text, kind, and state."""
    repair_enabled = _win32_repair_requested(repair, repair_timeout)
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_control_find")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        payload = {
            "hwnd": hwnd,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "text": text,
            "value": value,
            "state": state,
            "expected": expected,
            "match": match,
            "include_invisible": include_invisible,
            "include_self": include_self,
            "limit": limit,
            "min_score": min_score,
            "timeout_ms": timeout_ms,
            "max_items": max_items,
            "max_children": max_children,
            "diagnostic": diagnostic,
            "repair": repair_enabled,
            "repair_timeout": repair_timeout,
        }
        helper_result = _helper_post("/win32_control_find", payload, elevated=helper_elevated)
        if helper_result.get("ok") or "error" in helper_result or "matches" in helper_result or "near_matches" in helper_result:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
    result = _win32_control_find_direct(
        hwnd,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        text=text,
        value=value,
        state=state,
        expected=expected,
        match=match,
        include_invisible=include_invisible,
        include_self=include_self,
        limit=limit,
        min_score=min_score,
        timeout_ms=timeout_ms,
        max_items=max_items,
        max_children=max_children,
        diagnostic=diagnostic,
    )
    return _win32_control_find_maybe_repair(
        result,
        hwnd,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        text=text,
        value=value,
        state=state,
        expected=expected,
        match=match,
        include_invisible=include_invisible,
        include_self=include_self,
        limit=limit,
        min_score=min_score,
        timeout_ms=timeout_ms,
        max_items=max_items,
        max_children=max_children,
        diagnostic=diagnostic,
        repair=repair_enabled,
        repair_timeout=repair_timeout,
    )


def _win32_control_find_maybe_repair(
    result: Dict[str, Any],
    hwnd: int,
    *,
    name: Optional[str] = None,
    automation_id: Optional[Any] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    text: Optional[str] = None,
    value: Optional[str] = None,
    state: Optional[Any] = None,
    expected: Any = None,
    match: str = "contains",
    include_invisible: bool = False,
    include_self: bool = True,
    limit: int = 20,
    min_score: Optional[int] = None,
    timeout_ms: int = 250,
    max_items: int = 200,
    max_children: int = 1000,
    diagnostic: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if result.get("ok") or not _win32_repair_requested(repair, repair_timeout):
        return result
    failure_summary = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
    suggestions = failure_summary.get("selector_suggestions") if isinstance(failure_summary.get("selector_suggestions"), list) else []
    suggestion = next((item for item in suggestions if isinstance(item, dict) and item), None)
    if not suggestion:
        return result
    original = {
        "name": name,
        "automation_id": automation_id,
        "control_type": control_type,
        "class_name": class_name,
        "text": text,
        "value": value,
        "state": state,
        "expected": expected,
        "match": match,
        "include_invisible": include_invisible,
        "include_self": include_self,
        "limit": limit,
        "min_score": min_score,
        "timeout_ms": timeout_ms,
        "max_items": max_items,
        "max_children": max_children,
        "diagnostic": diagnostic,
    }
    repair_timeout_value = _win32_control_wait_repair_timeout(repair_timeout, 0.0)
    started = time.time()
    attempts = 0
    repaired: Dict[str, Any] = {}
    while True:
        attempts += 1
        maybe_repaired = win32_selector_repair_find(
            hwnd,
            suggestion,
            original=original,
            limit=1,
            include_invisible=include_invisible,
            include_self=include_self,
            min_score=min_score,
            timeout_ms=timeout_ms,
            max_items=max_items,
            max_children=max_children,
            diagnostic=diagnostic,
        )
        repaired = maybe_repaired if isinstance(maybe_repaired, dict) else {
            "ok": False,
            "error": "invalid_win32_repair_result",
            "result_type": type(maybe_repaired).__name__,
        }
        if repaired.get("ok"):
            repaired = dict(repaired)
            repaired["repaired"] = True
            repaired["repair"] = {
                "attempted": True,
                "ok": True,
                "timeout": repair_timeout_value,
                "attempts": attempts,
                "elapsed": time.time() - started,
                "reason": "retry native find with failure_summary.selector_suggestions[0]",
            }
            repaired["original_failure_summary"] = failure_summary
            return repaired
        elapsed = time.time() - started
        if elapsed >= repair_timeout_value:
            break
        remaining = max(repair_timeout_value - elapsed, 0.0)
        time.sleep(min(remaining, 0.1))

    updated = dict(result)
    updated["repair"] = {
        "attempted": True,
        "ok": False,
        "timeout": repair_timeout_value,
        "attempts": attempts,
        "elapsed": time.time() - started,
        "result": repaired,
        "reason": "retry native find with failure_summary.selector_suggestions[0]",
    }
    return updated


def _win32_repair_selector_from_suggestion(suggestion: Dict[str, Any], original: Dict[str, Any]) -> Dict[str, Any]:
    source = suggestion if isinstance(suggestion, dict) and suggestion else {}
    selector: Dict[str, Any] = {}
    key_aliases: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
        ("automation_id", ("automation_id", "automationId", "control_id", "controlId", "id")),
        ("control_type", ("control_type", "controlType", "type", "kind")),
        ("class_name", ("class_name", "className", "class")),
        ("name", ("name", "text", "title", "label")),
        ("value", ("value", "current_text", "currentText")),
        ("state", ("state",)),
        ("expected", ("expected", "checked")),
    )
    for target_key, aliases in key_aliases:
        for key in aliases:
            value = source.get(key)
            if value not in (None, "", [], {}):
                selector[target_key] = value
                break
    selector["match"] = source.get("match") or original.get("match") or "contains"
    return {key: value for key, value in selector.items() if value not in (None, "", [], {})}


def win32_selector_repair_find(
    hwnd: int,
    suggestion: Dict[str, Any],
    original: Optional[Dict[str, Any]] = None,
    *,
    limit: int = 1,
    include_invisible: Optional[bool] = None,
    include_self: Optional[bool] = None,
    min_score: Optional[int] = None,
    timeout_ms: Optional[int] = None,
    max_items: Optional[int] = None,
    max_children: Optional[int] = None,
    diagnostic: Optional[bool] = None,
    allow_suggestion_hwnd: bool = False,
) -> Dict[str, Any]:
    """Retry native Win32 control find using a cleaned selector suggestion from a failed find."""
    if hwnd is None:
        return {"ok": False, "error": "hwnd required"}
    if not isinstance(suggestion, dict) or not suggestion:
        return {"ok": False, "error": "suggestion required"}
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_selector_repair_find")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/win32_selector_repair_find",
            {
                "hwnd": hwnd,
                "suggestion": suggestion,
                "original": original or {},
                "limit": limit,
                "include_invisible": include_invisible,
                "include_self": include_self,
                "min_score": min_score,
                "timeout_ms": timeout_ms,
                "max_items": max_items,
                "max_children": max_children,
                "diagnostic": diagnostic,
                "allow_suggestion_hwnd": allow_suggestion_hwnd,
            },
            elevated=helper_elevated,
        )
        if "error" not in helper_result or helper_result.get("ok") is False:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
    original = dict(original or {})
    selector = _win32_repair_selector_from_suggestion(suggestion, original)
    signal_keys = ("name", "automation_id", "control_type", "class_name", "value", "state")
    resolved_limit = max(int(limit or original.get("limit") or 1), 1)
    resolved_include_invisible = _coerce_bool(
        include_invisible if include_invisible is not None else original.get("include_invisible"),
        False,
    )
    resolved_include_self = _coerce_bool(
        include_self if include_self is not None else original.get("include_self"),
        True,
    )
    resolved_min_score = min_score if min_score is not None else original.get("min_score")
    resolved_timeout_ms = int(timeout_ms if timeout_ms is not None else original.get("timeout_ms", 250) or 250)
    resolved_max_items = int(max_items if max_items is not None else original.get("max_items", 200) or 200)
    resolved_max_children = int(max_children if max_children is not None else original.get("max_children", 1000) or 1000)
    resolved_diagnostic = _coerce_bool(
        diagnostic if diagnostic is not None else original.get("diagnostic"),
        False,
    )

    result: Dict[str, Any] = {}
    if any(selector.get(key) not in (None, "", [], {}) for key in signal_keys):
        result = win32_control_find(
            hwnd,
            name=selector.get("name"),
            automation_id=selector.get("automation_id"),
            control_type=selector.get("control_type"),
            class_name=selector.get("class_name"),
            value=selector.get("value"),
            state=selector.get("state"),
            expected=selector.get("expected"),
            match=selector.get("match", "contains"),
            include_invisible=resolved_include_invisible,
            include_self=resolved_include_self,
            limit=resolved_limit,
            min_score=resolved_min_score,
            timeout_ms=resolved_timeout_ms,
            max_items=resolved_max_items,
            max_children=resolved_max_children,
            diagnostic=resolved_diagnostic,
        )
        if not isinstance(result, dict):
            result = {"ok": False, "error": "invalid_win32_find_result", "result_type": type(result).__name__}
        result["selector_repair"] = True
        result["native_selector_repair"] = True
        result["selector"] = selector
        result["suggestion"] = {
            key: value
            for key, value in suggestion.items()
            if key in ("hwnd", "automation_id", "control_id", "control_type", "kind", "class_name", "name", "text", "value", "state", "expected", "match")
            and value not in (None, "", [], {})
        }
        result["ok"] = bool(result.get("matches"))
        if result.get("matches"):
            return result

    if allow_suggestion_hwnd and suggestion.get("hwnd") is not None:
        try:
            suggested_hwnd = int(suggestion.get("hwnd"))
        except Exception:
            suggested_hwnd = 0
        if suggested_hwnd and user32.IsWindow(suggested_hwnd):
            match = {
                key: value
                for key, value in suggestion.items()
                if key in ("hwnd", "automation_id", "control_id", "control_type", "kind", "class_name", "name", "text", "value", "rect", "match")
                and value not in (None, "", [], {})
            }
            match.setdefault("hwnd", suggested_hwnd)
            return {
                "ok": True,
                "hwnd": hwnd,
                "selector_repair": True,
                "native_selector_repair": True,
                "suggestion_hwnd_fallback": True,
                "count": 1,
                "matches": [match],
                "suggestion": match,
                **({"last_find": {
                    "ok": result.get("ok"),
                    "count": result.get("count"),
                    "scanned": result.get("scanned"),
                    "failure_summary": result.get("failure_summary"),
                }} if result else {}),
            }

    if result:
        return result
    return {
        "ok": False,
        "error": "native_selector_suggestion_has_no_searchable_fields",
        "selector_repair": True,
        "native_selector_repair": True,
        "hwnd": hwnd,
        "suggestion": suggestion,
    }


def win32_control_wait_find(
    hwnd: int,
    name: Optional[str] = None,
    automation_id: Optional[Any] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    text: Optional[str] = None,
    value: Optional[str] = None,
    state: Optional[Any] = None,
    expected: Any = None,
    match: str = "contains",
    include_invisible: bool = False,
    include_self: bool = True,
    limit: int = 20,
    min_score: Optional[int] = None,
    timeout: float = 3.0,
    interval: float = 0.1,
    timeout_ms: int = 250,
    max_items: int = 200,
    max_children: int = 1000,
    diagnostic: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Poll until native Win32 controls matching the selector appear."""
    repair_enabled = _win32_repair_requested(repair, repair_timeout)
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_control_wait_find")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        payload = {
            "hwnd": hwnd,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "text": text,
            "value": value,
            "state": state,
            "expected": expected,
            "match": match,
            "include_invisible": include_invisible,
            "include_self": include_self,
            "limit": limit,
            "min_score": min_score,
            "timeout": timeout,
            "interval": interval,
            "timeout_ms": timeout_ms,
            "max_items": max_items,
            "max_children": max_children,
            "diagnostic": diagnostic,
            "repair": repair_enabled,
            "repair_timeout": repair_timeout,
        }
        helper_result = _helper_post(
            "/win32_control_wait_find",
            payload,
            elevated=helper_elevated,
            timeout=max(
                float(timeout or 0)
                + (_win32_control_wait_repair_timeout(repair_timeout, timeout) if repair_enabled else 0.0)
                + 1.0,
                2.0,
            ),
        )
        if helper_result.get("ok") or "error" in helper_result or "last_result" in helper_result or "matches" in helper_result:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result

    result = _win32_control_wait_find_poll(
        hwnd,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        text=text,
        value=value,
        state=state,
        expected=expected,
        match=match,
        include_invisible=include_invisible,
        include_self=include_self,
        limit=limit,
        min_score=min_score,
        timeout=timeout,
        interval=interval,
        timeout_ms=timeout_ms,
        max_items=max_items,
        max_children=max_children,
        diagnostic=diagnostic,
    )
    return _win32_control_wait_find_maybe_repair(
        result,
        hwnd,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        text=text,
        value=value,
        state=state,
        expected=expected,
        match=match,
        include_invisible=include_invisible,
        include_self=include_self,
        limit=limit,
        min_score=min_score,
        timeout=timeout,
        interval=interval,
        timeout_ms=timeout_ms,
        max_items=max_items,
        max_children=max_children,
        diagnostic=diagnostic,
        repair=repair_enabled,
        repair_timeout=repair_timeout,
    )


def _win32_control_wait_find_poll(
    hwnd: int,
    *,
    name: Optional[str] = None,
    automation_id: Optional[Any] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    text: Optional[str] = None,
    value: Optional[str] = None,
    state: Optional[Any] = None,
    expected: Any = None,
    match: str = "contains",
    include_invisible: bool = False,
    include_self: bool = True,
    limit: int = 20,
    min_score: Optional[int] = None,
    timeout: float = 3.0,
    interval: float = 0.1,
    timeout_ms: int = 250,
    max_items: int = 200,
    max_children: int = 1000,
    diagnostic: bool = False,
) -> Dict[str, Any]:
    started = time.time()
    try:
        timeout_value = max(float(timeout), 0.0)
    except Exception:
        timeout_value = 3.0
    try:
        interval_value = max(float(interval), 0.02)
    except Exception:
        interval_value = 0.1
    attempts = 0
    last_result: Dict[str, Any] = {}
    while True:
        attempts += 1
        last_result = _win32_control_find_direct(
            hwnd,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            text=text,
            value=value,
            state=state,
            expected=expected,
            match=match,
            include_invisible=include_invisible,
            include_self=include_self,
            limit=limit,
            min_score=min_score,
            timeout_ms=timeout_ms,
            max_items=max_items,
            max_children=max_children,
            diagnostic=diagnostic,
        )
        if last_result.get("ok"):
            result = dict(last_result)
            result.update({"ok": True, "matched": True, "attempts": attempts, "elapsed": time.time() - started})
            return result
        if time.time() - started >= timeout_value:
            break
        time.sleep(interval_value)
    result = {
        "ok": False,
        "matched": False,
        "error": "timeout",
        "hwnd": hwnd,
        "attempts": attempts,
        "elapsed": time.time() - started,
        "last_result": last_result if diagnostic else {
            key: last_result.get(key)
            for key in ("ok", "error", "count", "total_candidates", "available_candidates", "filtered_candidates", "scanned", "criteria", "near_matches", "failure_summary")
            if key in last_result
        },
    }
    failure_summary = last_result.get("failure_summary") if isinstance(last_result, dict) and isinstance(last_result.get("failure_summary"), dict) else None
    if failure_summary:
        result["failure_summary"] = failure_summary
    return result


def _win32_control_wait_find_failure_summary_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(result.get("failure_summary"), dict):
        return result.get("failure_summary") or {}
    last_result = result.get("last_result") if isinstance(result.get("last_result"), dict) else {}
    if isinstance(last_result.get("failure_summary"), dict):
        return last_result.get("failure_summary") or {}
    return {}


def _win32_control_wait_find_maybe_repair(
    result: Dict[str, Any],
    hwnd: int,
    *,
    name: Optional[str] = None,
    automation_id: Optional[Any] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    text: Optional[str] = None,
    value: Optional[str] = None,
    state: Optional[Any] = None,
    expected: Any = None,
    match: str = "contains",
    include_invisible: bool = False,
    include_self: bool = True,
    limit: int = 20,
    min_score: Optional[int] = None,
    timeout: float = 3.0,
    interval: float = 0.1,
    timeout_ms: int = 250,
    max_items: int = 200,
    max_children: int = 1000,
    diagnostic: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if result.get("matched") or result.get("ok") or not _win32_repair_requested(repair, repair_timeout):
        return result
    failure_summary = _win32_control_wait_find_failure_summary_from_result(result)
    suggestions = failure_summary.get("selector_suggestions") if isinstance(failure_summary.get("selector_suggestions"), list) else []
    suggestion = next((item for item in suggestions if isinstance(item, dict) and item), None)
    if not suggestion:
        return result
    original = {
        "name": name,
        "automation_id": automation_id,
        "control_type": control_type,
        "class_name": class_name,
        "text": text,
        "value": value,
        "state": state,
        "expected": expected,
        "match": match,
        "include_invisible": include_invisible,
        "include_self": include_self,
        "limit": limit,
        "min_score": min_score,
        "timeout_ms": timeout_ms,
        "max_items": max_items,
        "max_children": max_children,
        "diagnostic": diagnostic,
    }
    selector = _win32_repair_selector_from_suggestion(suggestion, original)
    signal_keys = ("name", "automation_id", "control_type", "class_name", "value", "state")
    if not any(selector.get(key) not in (None, "", [], {}) for key in signal_keys):
        return result
    repair_timeout_value = _win32_control_wait_repair_timeout(repair_timeout, timeout)
    repair_result = _win32_control_wait_find_poll(
        hwnd,
        name=selector.get("name"),
        automation_id=selector.get("automation_id"),
        control_type=selector.get("control_type"),
        class_name=selector.get("class_name"),
        value=selector.get("value"),
        state=selector.get("state"),
        expected=selector.get("expected"),
        match=selector.get("match", "contains"),
        include_invisible=_coerce_bool(original.get("include_invisible"), False),
        include_self=_coerce_bool(original.get("include_self"), True),
        limit=max(int(limit or 1), 1),
        min_score=min_score,
        timeout=repair_timeout_value,
        interval=interval,
        timeout_ms=timeout_ms,
        max_items=max_items,
        max_children=max_children,
        diagnostic=diagnostic,
    )
    repair_info = {
        "attempted": True,
        "ok": bool(repair_result.get("ok")),
        "timeout": repair_timeout_value,
        "selector": selector,
        "reason": "retry native wait-find with failure_summary.selector_suggestions[0]",
    }
    if repair_result.get("ok"):
        repaired = dict(repair_result)
        repaired["repaired"] = True
        repaired["selector_repair"] = True
        repaired["native_selector_repair"] = True
        repaired["repair"] = repair_info
        repaired["suggestion"] = {
            key: value
            for key, value in suggestion.items()
            if key in ("hwnd", "automation_id", "control_id", "control_type", "kind", "class_name", "name", "text", "value", "state", "expected", "match")
            and value not in (None, "", [], {})
        }
        repaired["original_failure_summary"] = failure_summary
        return repaired
    updated = dict(result)
    updated["repair"] = {
        **repair_info,
        "result": {
            key: repair_result.get(key)
            for key in ("ok", "matched", "error", "count", "attempts", "elapsed", "failure_summary")
            if repair_result.get(key) not in (None, "", [], {})
        },
    }
    return updated


def window_from_point(
    x: Optional[int] = None,
    y: Optional[int] = None,
    hwnd: Optional[int] = None,
    screenshot_id: Optional[int] = None,
    include_text: bool = False,
) -> Dict[str, Any]:
    """Return the top-level and child HWND under a screen or screenshot point."""
    if x is None or y is None:
        pos = mouse_position()
        if "error" in pos:
            return pos
        x, y = int(pos["x"]), int(pos["y"])

    if hwnd is not None:
        screen_x, screen_y, debug = _scale_coords(hwnd, int(x), int(y), screenshot_id)
    else:
        screen_x, screen_y = int(x), int(y)
        debug = "input coordinates treated as screen coordinates"

    helper_ready, helper_elevated, point_hwnd, boundary_result = _helper_route_for_screen_point(screen_x, screen_y, "/window_from_point")
    if boundary_result is not None:
        boundary_result.update({
            "input": {"x": x, "y": y, "hwnd": hwnd, "screenshot_id": screenshot_id},
            "screen": {"x": screen_x, "y": screen_y},
            "debug": debug,
            "point_hwnd": int(point_hwnd or 0),
        })
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/window_from_point",
            {"x": screen_x, "y": screen_y, "include_text": include_text},
            elevated=helper_elevated,
        )
        if helper_result.get("ok"):
            helper_result["input"] = {"x": x, "y": y, "hwnd": hwnd, "screenshot_id": screenshot_id}
            helper_result["debug"] = debug
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            helper_result["point_hwnd"] = int(point_hwnd or 0)
            return helper_result

    point = ctypes.wintypes.POINT(screen_x, screen_y)
    direct_hwnd = int(user32.WindowFromPoint(point) or 0)
    root_hwnd = int(user32.GetAncestor(direct_hwnd, GA_ROOT) or direct_hwnd or 0)
    root_owner_hwnd = int(user32.GetAncestor(direct_hwnd, GA_ROOTOWNER) or direct_hwnd or 0)

    child_hwnd = 0
    real_child_hwnd = 0
    if root_hwnd:
        client_point = ctypes.wintypes.POINT(screen_x, screen_y)
        user32.ScreenToClient(root_hwnd, ctypes.byref(client_point))
        child_hwnd = int(user32.ChildWindowFromPointEx(
            root_hwnd,
            client_point,
            CWP_SKIPINVISIBLE | CWP_SKIPDISABLED | CWP_SKIPTRANSPARENT,
        ) or 0)
        real_child_hwnd = int(user32.RealChildWindowFromPoint(root_hwnd, client_point) or 0)

    return {
        "input": {"x": x, "y": y, "hwnd": hwnd, "screenshot_id": screenshot_id},
        "screen": {"x": screen_x, "y": screen_y},
        "debug": debug,
        "window": _win32_window_info(direct_hwnd, include_text=include_text) if direct_hwnd else None,
        "root": _win32_window_info(root_hwnd, include_text=include_text) if root_hwnd else None,
        "root_owner": _win32_window_info(root_owner_hwnd, include_text=include_text) if root_owner_hwnd else None,
        "child": _win32_window_info(child_hwnd, include_text=include_text) if child_hwnd else None,
        "real_child": _win32_window_info(real_child_hwnd, include_text=include_text) if real_child_hwnd else None,
    }



