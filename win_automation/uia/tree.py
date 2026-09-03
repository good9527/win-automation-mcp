"""
UIAutomation tree traversal, element indexing, selector query execution, and desktop accessibility hierarchy.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ElementNotFoundError, ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.uia.engine import (
    get_uia_client, _uia_element_cache, _uia_ad_hoc_element_indices, _DESKTOP_UIA_KEY,
    _register_uia_elements, _uia_element_brief, _get_supported_patterns, _get_typed_pattern,
    _uia_element_by_index
)
from win_automation.uia.cache import _remember_uia_element_signatures, _remember_uia_scan_options, _last_uia_scan_options
from win_automation.uia.repair import _uia_find_failure_summary, _rank_uia_matches, _selector_similarity_score, _uia_selector_suggestion
from win_automation.helper.client import (
    _helper_route_for_hwnd,
    _helper_post,
    _elevated_helper_required_result,
    _prepare_helper_for_uia,
    _uia_helper_timeout,
    _is_terminal_uia_helper_error,
    _mark_uia_helper_error,
)

def get_element(hwnd: int, index: int) -> Dict[str, Any]:
    elem, info = _uia_element_by_index(hwnd, index)
    return info

def get_desktop_element(index: int) -> Dict[str, Any]:
    return get_element(0, index)

desktop_get_element = get_desktop_element

def build_desktop_tree(max_depth: int = 4, max_elements: int = 500, view: str = "control") -> Dict[str, Any]:
    return desktop_accessibility(max_depth=max_depth, max_elements=max_elements, hydrate=True, view=view)

def build_accessibility_tree(
    hwnd: int,
    max_depth: int = 10,
    max_elements: int = 500,
    hydrate: bool = True,
    view: str = "raw",
) -> Dict[str, Any]:
    """
    Build an accessibility tree rooted at *hwnd*.

    Returns a dict with:
      - tree:     str  (human-readable indented tree)
      - elements: list of dicts with element metadata
      - focused:  dict or None with focused-element info
    """
    boundary_result = _elevated_helper_required_result(hwnd, "/uia_accessibility")
    if boundary_result is not None:
        return boundary_result
    helper_ready, helper_elevated = _prepare_helper_for_uia(hwnd)
    if helper_ready:
        helper_result = _helper_post(
            "/uia_accessibility",
            {
                "hwnd": hwnd,
                "max_depth": max_depth,
                "max_elements": max_elements,
                "hydrate": hydrate,
                "view": view,
                "uia_timeout": _uia_helper_timeout(),
            },
            elevated=helper_elevated,
            timeout=_uia_helper_timeout() + 1.0,
        )
        if "error" not in helper_result:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
        if _is_terminal_uia_helper_error(helper_result):
            return _mark_uia_helper_error(helper_result, helper_elevated)
    try:
        import comtypes
        import comtypes.client
        import comtypes.gen.UIAutomationClient as UIAClient
    except ImportError:
        return {"error": "comtypes not installed - run: pip install comtypes"}

    try:
        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=UIAClient.IUIAutomation,
        )

        root = uia.GetRootElement() if int(hwnd) == _DESKTOP_UIA_KEY else uia.ElementFromHandle(hwnd)
        if not root:
            return {"error": "No accessible content for this window" if int(hwnd) else "No accessible desktop root"}

        lines: List[str] = []
        element_map: List[Dict[str, Any]] = []
        cache: Dict[int, Any] = {}
        counter = [0]
        view = _normalize_uia_view(view)
        walker = uia.CreateTreeWalker(_uia_view_condition(uia, view))

        def walk(elem, depth: int, parent_info: Optional[Dict[str, Any]] = None, ancestor_path: Optional[List[Dict[str, Any]]] = None, sibling_ordinal: int = 0) -> None:
            if depth > max_depth or counter[0] >= max_elements:
                return
            path = ancestor_path or []
            idx = counter[0]
            counter[0] += 1
            cache[idx] = elem

            try:
                info = _element_info(elem, index=idx, depth=depth) if hydrate else _element_basic_info(elem, index=idx, depth=depth)
                info = _decorate_uia_structure_info(info, parent_info, path, sibling_ordinal)
                lines.append(_format_element_line(info))
                element_map.append(info)

                try:
                    child = walker.GetFirstChildElement(elem)
                    child_ordinal = 0
                    child_path = path + [_uia_parent_signature(info)]
                    while child:
                        walk(child, depth + 1, info, child_path, child_ordinal)
                        child_ordinal += 1
                        child = walker.GetNextSiblingElement(child)
                except Exception:
                    pass
            except Exception:
                pass

        walk(root, 0)
        _uia_element_cache[hwnd] = cache
        _uia_ad_hoc_element_indices[hwnd] = set()
        _remember_uia_element_signatures(hwnd, element_map)
        _remember_uia_scan_options(hwnd, max_depth, max_elements, view)

        # --- Item 12: Focused element & selected text ---
        focused_info: Optional[Dict[str, Any]] = None
        try:
            focused_elem = uia.GetFocusedElement()
            if focused_elem:
                f_info = _element_info(focused_elem)
                selected_text = ""
                try:
                    tp = focused_elem.GetCurrentPattern(UIA_PATTERN_IDS["Text"])
                    if tp:
                        selection = tp.GetSelection()
                        if selection and selection.Length > 0:
                            selected_ranges = []
                            for idx_sel in range(selection.Length):
                                r = selection.GetElement(idx_sel)
                                selected_ranges.append(r.GetText(-1))
                            selected_text = "\n".join(selected_ranges)
                except Exception:
                    pass
                try:
                    if not selected_text:
                        vp = focused_elem.GetCurrentPattern(UIA_PATTERN_IDS["Value"])
                        selected_text = vp.CurrentValue or ""
                except Exception:
                    pass
                focused_info = {
                    "name": f_info["name"],
                    "automation_id": f_info["automation_id"],
                    "control_type": f_info["control_type"],
                    "class_name": f_info["class_name"],
                    "selected_text": selected_text,
                }
        except Exception:
            pass

        return {
            "tree": "\n".join(lines) if lines else "No accessible elements found",
            "elements": element_map,
            "focused": focused_info,
            "view": view,
        }

    except Exception as e:
        return {"error": str(e)}




def find_elements(
    hwnd: int,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    value: Optional[str] = None,
    pattern: Optional[str] = None,
    enabled_only: bool = False,
    visible_only: bool = True,
    match: str = "contains",
    limit: int = 25,
    max_depth: int = 10,
    max_elements: int = 500,
    view: str = "raw",
) -> Dict[str, Any]:
    """Find UIA elements by stable selectors."""
    boundary_result = _elevated_helper_required_result(hwnd, "/uia_find")
    if boundary_result is not None:
        return boundary_result
    helper_ready, helper_elevated = _prepare_helper_for_uia(hwnd)
    if helper_ready:
        helper_result = _helper_post(
            "/uia_find",
            {
                "hwnd": hwnd,
                "name": name,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "value": value,
                "pattern": pattern,
                "enabled_only": enabled_only,
                "visible_only": visible_only,
                "match": match,
                "limit": limit,
                "max_depth": max_depth,
                "max_elements": max_elements,
                "view": view,
                "uia_timeout": _uia_helper_timeout(),
            },
            elevated=helper_elevated,
            timeout=_uia_helper_timeout() + 1.0,
        )
        if "error" not in helper_result:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
        if _is_terminal_uia_helper_error(helper_result):
            return _mark_uia_helper_error(helper_result, helper_elevated)
    result = build_accessibility_tree(hwnd, max_depth=max_depth, max_elements=max_elements, hydrate=False, view=view)
    if "error" in result:
        return result
    rank_limit = max(int(limit or 25), 1)
    matches = _filter_elements(
        result.get("elements", []),
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        value=value,
        pattern=pattern,
        enabled_only=enabled_only,
        visible_only=visible_only,
        match=match,
        limit=len(result.get("elements", [])),
        collect_all=True,
    )
    matches = [_hydrate_element_info(hwnd, match_info) for match_info in matches]
    matches = _rank_uia_matches(
        matches,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        value=value,
        pattern=pattern,
        enabled_only=enabled_only,
        visible_only=visible_only,
        match=match,
        limit=rank_limit,
    )
    response = {
        "hwnd": hwnd,
        "desktop": int(hwnd) == _DESKTOP_UIA_KEY,
        "view": result.get("view", _normalize_uia_view(view)),
        "scanned": len(result.get("elements", [])),
        "count": len(matches),
        "matches": matches,
        "focused": result.get("focused"),
    }
    if not matches:
        near_matches = _uia_near_matches(
            result.get("elements", []),
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            value=value,
            pattern=pattern,
            enabled_only=enabled_only,
            visible_only=visible_only,
            match=match,
            limit=min(max(rank_limit, 1), 5),
        )
        response["near_matches"] = near_matches
        response["failure_summary"] = _uia_find_failure_summary(
            result.get("elements", []),
            near_matches,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            value=value,
            pattern=pattern,
            enabled_only=enabled_only,
            visible_only=visible_only,
            match=match,
            scanned=len(result.get("elements", [])),
            view=response.get("view"),
        )
    return response




def desktop_accessibility(max_depth: int = 4, max_elements: int = 500, hydrate: bool = True, view: str = "control") -> Dict[str, Any]:
    """Build a UIA tree rooted at the Windows desktop root element."""
    result = build_accessibility_tree(_DESKTOP_UIA_KEY, max_depth=max_depth, max_elements=max_elements, hydrate=hydrate, view=view)
    result["desktop"] = True
    return result


def desktop_find_elements(
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    value: Optional[str] = None,
    pattern: Optional[str] = None,
    enabled_only: bool = False,
    visible_only: bool = True,
    match: str = "contains",
    limit: int = 25,
    max_depth: int = 4,
    max_elements: int = 500,
    view: str = "control",
) -> Dict[str, Any]:
    """Find UIA elements from the desktop root for taskbar, Start, menus, and cross-window UI."""
    return find_elements(
        _DESKTOP_UIA_KEY,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        value=value,
        pattern=pattern,
        enabled_only=enabled_only,
        visible_only=visible_only,
        match=match,
        limit=limit,
        max_depth=max_depth,
        max_elements=max_elements,
        view=view,
    )


def desktop_wait_for_element(
    selector: Dict[str, Any],
    timeout: float = 10.0,
    interval: float = 0.5,
    *,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
    allow_suggestion_index: bool = False,
) -> Dict[str, Any]:
    """Poll desktop-root UIA until a selector matches."""
    selector = dict(selector)
    selector.setdefault("max_depth", 4)
    selector.setdefault("max_elements", 500)
    selector.setdefault("view", "control")
    return wait_for_element(
        _DESKTOP_UIA_KEY,
        selector,
        timeout=timeout,
        interval=interval,
        repair=repair,
        repair_timeout=repair_timeout,
        allow_suggestion_index=allow_suggestion_index,
    )


def desktop_element(index: int, max_depth: Optional[int] = None, max_elements: Optional[int] = None, view: Optional[str] = None) -> Dict[str, Any]:
    """Return metadata for one desktop-root UIA index."""
    elem, info = _uia_element_by_index(_DESKTOP_UIA_KEY, index, max_depth=max_depth, max_elements=max_elements, view=view)
    return info or {"error": f"Desktop element index {index} not found"}


def desktop_focus_element(index: int, max_depth: Optional[int] = None, max_elements: Optional[int] = None, view: Optional[str] = None) -> Dict[str, Any]:
    """Set keyboard focus to a desktop-root UIA element."""
    return focus_element(_DESKTOP_UIA_KEY, index, max_depth=max_depth, max_elements=max_elements, view=view)


def uia_stable_wait(
    hwnd: int,
    timeout: float = 5.0,
    interval: float = 0.25,
    stable_ticks: int = 2,
    max_depth: int = 10,
    max_elements: int = 500,
    view: str = "control",
    include_values: bool = False,
    rect_bucket: int = 2,
) -> Dict[str, Any]:
    """Poll window UIA until the control tree structure stabilizes."""
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    attempts = 0
    consecutive_stable = 0
    last_sig = None
    required_ticks = max(int(stable_ticks or 1), 1)

    while True:
        attempts += 1
        tree_data = None
        try:
            tree_data = build_accessibility_tree(hwnd, max_depth=max_depth, max_elements=max_elements, hydrate=True, view=view)
            elements = tree_data.get("elements", [])
            sig = (len(elements), tuple((e.get("control_type"), e.get("name"), e.get("automation_id")) for e in elements[:100]))
        except Exception as ex:
            sig = str(ex)

        if sig == last_sig and last_sig is not None:
            consecutive_stable += 1
            if consecutive_stable >= required_ticks:
                return {
                    "ok": True,
                    "stable": True,
                    "attempts": attempts,
                    "consecutive_stable": consecutive_stable,
                    "elapsed": round(time.time() - start, 3),
                    "element_count": len(tree_data.get("elements", [])) if isinstance(tree_data, dict) else 0,
                }
        else:
            consecutive_stable = 1
            last_sig = sig

        if time.time() >= deadline:
            return {
                "ok": consecutive_stable >= required_ticks,
                "stable": consecutive_stable >= required_ticks,
                "attempts": attempts,
                "consecutive_stable": consecutive_stable,
                "elapsed": round(time.time() - start, 3),
                "error": "timeout" if consecutive_stable < required_ticks else None,
            }
        time.sleep(max(float(interval), 0.01))


def desktop_uia_stable_wait(
    timeout: float = 5.0,
    interval: float = 0.25,
    stable_ticks: int = 2,
    max_depth: int = 4,
    max_elements: int = 500,
    view: str = "control",
    include_values: bool = False,
    rect_bucket: int = 2,
) -> Dict[str, Any]:
    """Poll desktop UIA until the control tree structure stabilizes."""
    return uia_stable_wait(
        _DESKTOP_UIA_KEY,
        timeout=timeout,
        interval=interval,
        stable_ticks=stable_ticks,
        max_depth=max_depth,
        max_elements=max_elements,
        view=view,
        include_values=include_values,
        rect_bucket=rect_bucket,
    )

