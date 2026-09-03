"""
Dynamic UIAutomation selector repair, fuzzy score matching, and repair suggestions.
"""

from __future__ import annotations

import time
import difflib
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ElementNotFoundError, ActionTimeoutError
from win_automation.uia.engine import get_uia_client, _uia_element_cache, _DESKTOP_UIA_KEY
from win_automation.uia.cache import _uia_element_signatures, _remember_uia_element_signatures, _uia_relocation_from_info
from win_automation.helper.client import (
    _helper_route_for_hwnd,
    _helper_post,
    _elevated_helper_required_result,
    _is_terminal_uia_helper_error,
    _mark_uia_helper_error,
)


def _selector_compact(sel: Any) -> str:
    """Compact selector dict, list, or primitive to a canonical compact string representation."""
    if sel is None:
        return ""
    if isinstance(sel, str):
        return sel.strip().lower()
    if isinstance(sel, dict):
        parts = []
        for k in sorted(sel.keys()):
            v = sel[k]
            if v is not None and v != "":
                parts.append(f"{k}={str(v).strip().lower()}")
        return ";".join(parts)
    if isinstance(sel, (list, tuple, set)):
        return ",".join(_selector_compact(x) for x in sel if x is not None)
    return str(sel).strip().lower()


def _selector_similarity_score(candidate: Any, expected: Any) -> int:
    left = _selector_compact(candidate)
    right = _selector_compact(expected)
    if not left or not right:
        return 0
    ratio = difflib.SequenceMatcher(None, left, right).ratio()
    return int(round(ratio * 60))


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




_UIA_CONTROL_TYPE_ALIASES: Dict[str, int] = {
    "button": 50000,
    "calendar": 50001,
    "checkbox": 50002,
    "check_box": 50002,
    "combobox": 50003,
    "combo_box": 50003,
    "edit": 50004,
    "hyperlink": 50005,
    "hyper_link": 50005,
    "image": 50006,
    "listitem": 50007,
    "list_item": 50007,
    "list": 50008,
    "menu": 50009,
    "menubar": 50010,
    "menu_bar": 50010,
    "menuitem": 50011,
    "menu_item": 50011,
    "progressbar": 50012,
    "progress_bar": 50012,
    "radio": 50013,
    "radiobutton": 50013,
    "radio_button": 50013,
    "scrollbar": 50014,
    "scroll_bar": 50014,
    "slider": 50015,
    "spinner": 50016,
    "statusbar": 50017,
    "status_bar": 50017,
    "tab": 50018,
    "tabitem": 50019,
    "tab_item": 50019,
    "text": 50020,
    "toolbar": 50021,
    "tool_bar": 50021,
    "tooltip": 50022,
    "tool_tip": 50022,
    "tree": 50023,
    "treeitem": 50024,
    "tree_item": 50024,
    "custom": 50025,
    "group": 50026,
    "thumb": 50027,
    "datagrid": 50028,
    "data_grid": 50028,
    "dataitem": 50029,
    "data_item": 50029,
    "document": 50030,
    "splitbutton": 50031,
    "split_button": 50031,
    "window": 50032,
    "pane": 50033,
    "header": 50034,
    "headeritem": 50035,
    "header_item": 50035,
    "table": 50036,
    "titlebar": 50037,
    "title_bar": 50037,
    "separator": 50038,
    "semanticzoom": 50039,
    "semantic_zoom": 50039,
    "appbar": 50040,
    "app_bar": 50040,
}


def _matches_control_type(elem: Dict[str, Any], expected: str, mode: str) -> bool:
    normalized = str(expected or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _UIA_CONTROL_TYPE_ALIASES:
        try:
            return int(elem.get("control_type_id") or 0) == _UIA_CONTROL_TYPE_ALIASES[normalized]
        except Exception:
            return False
    return _selector_text_matches(elem.get("control_type", ""), expected, mode)


def _normalize_uia_view(view: Optional[str]) -> str:
    text = str(view or "raw").strip().lower().replace("_", "-")
    aliases = {
        "raw-view": "raw",
        "rawview": "raw",
        "all": "raw",
        "control-view": "control",
        "controlview": "control",
        "controls": "control",
        "content-view": "content",
        "contentview": "content",
        "contents": "content",
    }
    text = aliases.get(text, text)
    if text not in ("raw", "control", "content"):
        raise ValueError("UIA view must be raw, control, or content")
    return text


def _uia_view_condition(uia: Any, view: Optional[str]) -> Any:
    normalized = _normalize_uia_view(view)
    if normalized == "control":
        return uia.ControlViewCondition
    if normalized == "content":
        return uia.ContentViewCondition
    return uia.RawViewCondition




def _uia_selector_score(
    elem: Dict[str, Any],
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    value: Optional[str] = None,
    pattern: Optional[str] = None,
    enabled_only: bool = False,
    visible_only: bool = True,
    match: str = "contains",
) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    name_score, name_reason = _selector_text_score(elem.get("name"), name, match)
    if name is not None:
        score += name_score
        reasons.append(f"name:{name_reason}")
    automation_score, automation_reason = _selector_text_score(elem.get("automation_id"), automation_id, match)
    if automation_id is not None:
        score += automation_score + 20
        reasons.append(f"automation_id:{automation_reason}")
    value_score, value_reason = _selector_text_score(elem.get("value"), value, match)
    if value is not None:
        score += value_score
        reasons.append(f"value:{value_reason}")
    class_score, class_reason = _selector_text_score(elem.get("class_name"), class_name, match)
    if class_name is not None:
        score += class_score + 8
        reasons.append(f"class_name:{class_reason}")
    if control_type is not None:
        if _matches_control_type(elem, control_type, match):
            score += 55
            reasons.append("control_type:match")
        else:
            score -= 1000
            reasons.append("control_type:miss")
    patterns = [str(p).lower() for p in elem.get("patterns", [])]
    if pattern is not None:
        if str(pattern).lower() in patterns:
            score += 45
            reasons.append("pattern:match")
        else:
            score -= 1000
            reasons.append("pattern:miss")
    if elem.get("visible"):
        score += 12
        reasons.append("visible")
    elif visible_only:
        score -= 200
        reasons.append("not_visible")
    if elem.get("enabled"):
        score += 10
        reasons.append("enabled")
    elif enabled_only:
        score -= 200
        reasons.append("disabled")
    if elem.get("has_keyboard_focus"):
        score += 8
        reasons.append("focused")
    if elem.get("keyboard_focusable"):
        score += 3
        reasons.append("focusable")
    if _selector_rect_area(elem.get("rect")) > 0:
        score += 4
        reasons.append("rect")
    return {"score": score, "reasons": reasons}


def _rank_uia_matches(
    matches: List[Dict[str, Any]],
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
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for position, elem in enumerate(matches):
        item = dict(elem)
        diagnostic = _uia_selector_score(
            item,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            value=value,
            pattern=pattern,
            enabled_only=enabled_only,
            visible_only=visible_only,
            match=match,
        )
        item["selector_score"] = diagnostic["score"]
        item["selector_reasons"] = diagnostic["reasons"]
        item["_selector_order"] = position
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            -int(item.get("selector_score") or 0),
            _selector_rect_sort_key(item.get("rect")),
            int(item.get("_selector_order") or 0),
        )
    )
    result = []
    for item in ranked[:limit]:
        item.pop("_selector_order", None)
        result.append(item)
    return result


def _uia_near_match_score(
    elem: Dict[str, Any],
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    value: Optional[str] = None,
    pattern: Optional[str] = None,
    enabled_only: bool = False,
    visible_only: bool = True,
    match: str = "contains",
) -> Dict[str, Any]:
    diagnostic = _uia_selector_score(
        elem,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        value=value,
        pattern=pattern,
        enabled_only=enabled_only,
        visible_only=visible_only,
        match=match,
    )
    score = int(diagnostic.get("score") or 0)
    reasons = list(diagnostic.get("reasons") or [])
    if name is not None:
        text_score = _selector_similarity_score(elem.get("name"), name)
        score += text_score
        reasons.append(f"name_similarity:{text_score}")
    if automation_id is not None:
        text_score = _selector_similarity_score(elem.get("automation_id"), automation_id)
        score += text_score
        reasons.append(f"automation_id_similarity:{text_score}")
    if class_name is not None:
        text_score = _selector_similarity_score(elem.get("class_name"), class_name)
        score += text_score
        reasons.append(f"class_name_similarity:{text_score}")
    if value is not None:
        text_score = _selector_similarity_score(elem.get("value"), value)
        score += text_score
        reasons.append(f"value_similarity:{text_score}")
    return {"score": score, "reasons": reasons}


def _uia_near_matches(
    elements: List[Dict[str, Any]],
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    value: Optional[str] = None,
    pattern: Optional[str] = None,
    enabled_only: bool = False,
    visible_only: bool = True,
    match: str = "contains",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for position, elem in enumerate(elements):
        item = dict(elem)
        diagnostic = _uia_near_match_score(
            item,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            value=value,
            pattern=pattern,
            enabled_only=enabled_only,
            visible_only=visible_only,
            match=match,
        )
        near_score = int(diagnostic.get("score") or 0)
        if near_score < -900:
            continue
        summary = _summarize_element(item)
        summary["selector_score"] = near_score
        summary["selector_reasons"] = diagnostic.get("reasons") or []
        summary["_selector_order"] = position
        ranked.append(summary)
    ranked.sort(
        key=lambda item: (
            -int(item.get("selector_score") or 0),
            _selector_rect_sort_key(item.get("rect")),
            int(item.get("_selector_order") or 0),
        )
    )
    result: List[Dict[str, Any]] = []
    for item in ranked[: max(int(limit or 5), 0)]:
        item.pop("_selector_order", None)
        result.append(item)
    return result


def _uia_selector_filter_misses(
    elem: Dict[str, Any],
    *,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    value: Optional[str] = None,
    pattern: Optional[str] = None,
    enabled_only: bool = False,
    visible_only: bool = True,
    match: str = "contains",
) -> List[Dict[str, Any]]:
    misses: List[Dict[str, Any]] = []
    if name is not None and not _selector_text_matches(elem.get("name", ""), name, match):
        misses.append({"criterion": "name", "expected": name, "actual": _shorten(elem.get("name", ""), 120)})
    if automation_id is not None and not _selector_text_matches(elem.get("automation_id", ""), automation_id, match):
        misses.append({"criterion": "automation_id", "expected": automation_id, "actual": elem.get("automation_id", "")})
    if control_type is not None and not _matches_control_type(elem, control_type, match):
        misses.append({"criterion": "control_type", "expected": control_type, "actual": elem.get("control_type", "")})
    if class_name is not None and not _selector_text_matches(elem.get("class_name", ""), class_name, match):
        misses.append({"criterion": "class_name", "expected": class_name, "actual": elem.get("class_name", "")})
    if value is not None and not _selector_text_matches(elem.get("value", ""), value, match):
        misses.append({"criterion": "value", "expected": value, "actual": _shorten(elem.get("value", ""), 120)})
    if pattern is not None and str(pattern).lower() not in [str(p).lower() for p in elem.get("patterns", [])]:
        misses.append({"criterion": "pattern", "expected": pattern, "actual": elem.get("patterns", [])})
    if enabled_only and not elem.get("enabled", False):
        misses.append({"criterion": "enabled", "expected": True, "actual": bool(elem.get("enabled", False))})
    if visible_only and not elem.get("visible", False):
        misses.append({"criterion": "visible", "expected": True, "actual": bool(elem.get("visible", False))})
    return misses


def _uia_selector_suggestion(elem: Dict[str, Any], *, requested_pattern: Optional[str] = None, match: str = "contains") -> Dict[str, Any]:
    suggestion: Dict[str, Any] = {}
    for key in ("index", "automation_id", "control_type", "class_name", "name", "value"):
        value = elem.get(key)
        if value not in (None, "", [], {}):
            suggestion[key] = _shorten(value, 120) if key in ("name", "value") else value
    patterns = [str(p) for p in (elem.get("patterns") or [])]
    if requested_pattern and str(requested_pattern).lower() in [p.lower() for p in patterns]:
        suggestion["pattern"] = requested_pattern
    elif patterns:
        for preferred in ("Invoke", "Value", "SelectionItem", "Toggle", "LegacyIAccessible"):
            if preferred.lower() in [p.lower() for p in patterns]:
                suggestion["pattern"] = preferred
                break
    suggestion["match"] = match or "contains"
    return {key: value for key, value in suggestion.items() if value not in (None, "", [], {})}


def _uia_find_failure_summary(
    elements: List[Dict[str, Any]],
    near_matches: List[Dict[str, Any]],
    *,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    value: Optional[str] = None,
    pattern: Optional[str] = None,
    enabled_only: bool = False,
    visible_only: bool = True,
    match: str = "contains",
    scanned: int = 0,
    view: Optional[str] = None,
) -> Dict[str, Any]:
    miss_counts: Dict[str, int] = {}
    control_type_counts: Dict[str, int] = {}
    class_counts: Dict[str, int] = {}
    suggestions: List[Dict[str, Any]] = []
    for elem in elements:
        if not isinstance(elem, dict):
            continue
        control_value = str(elem.get("control_type") or "").strip() or "<unknown>"
        class_value = str(elem.get("class_name") or "").strip() or "<unknown>"
        control_type_counts[control_value] = control_type_counts.get(control_value, 0) + 1
        class_counts[class_value] = class_counts.get(class_value, 0) + 1
        for miss in _uia_selector_filter_misses(
            elem,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            value=value,
            pattern=pattern,
            enabled_only=enabled_only,
            visible_only=visible_only,
            match=match,
        ):
            criterion = str(miss.get("criterion") or "unknown")
            miss_counts[criterion] = miss_counts.get(criterion, 0) + 1

    for elem in near_matches:
        if not isinstance(elem, dict):
            continue
        suggestion = _uia_selector_suggestion(elem, requested_pattern=pattern, match=match)
        if suggestion and suggestion not in suggestions:
            suggestions.append(suggestion)

    def top_counts(values: Dict[str, int]) -> List[Dict[str, Any]]:
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        return [{"value": key, "count": count} for key, count in ranked[:8]]

    recommendations: List[str] = []
    if scanned <= 0:
        recommendations.append("No UIA elements were scanned; retry another view or check whether the provider is blocked.")
    if miss_counts.get("name") or miss_counts.get("value"):
        recommendations.append("Requested UIA text did not match; inspect near_matches and try selector_suggestions with relaxed match or the actual name/value.")
    if miss_counts.get("automation_id"):
        recommendations.append("Requested AutomationId did not match; use selector_suggestions or retry without automation_id if the provider changed it.")
    if miss_counts.get("control_type") or miss_counts.get("class_name") or miss_counts.get("pattern"):
        recommendations.append("Requested type/class/pattern filtered out candidates; inspect observed_control_types, observed_classes, and near_matches.")
    if visible_only and miss_counts.get("visible"):
        recommendations.append("Matching UIA elements may be offscreen or hidden; retry with visible_only=false, ScrollItem, or another UIA view.")
    if not recommendations and near_matches:
        recommendations.append("Near UIA elements were found; use selector_suggestions or near_matches[].index with the same view.")

    return {
        "scanned": scanned,
        "view": view,
        "miss_counts": miss_counts,
        "observed_control_types": top_counts(control_type_counts),
        "observed_classes": top_counts(class_counts),
        "selector_suggestions": suggestions[:5],
        "recommendations": recommendations,
    }




def uia_selector_repair_find(
    hwnd: int,
    suggestion: Dict[str, Any],
    original: Optional[Dict[str, Any]] = None,
    *,
    limit: int = 1,
    max_depth: Optional[int] = None,
    max_elements: Optional[int] = None,
    view: Optional[str] = None,
    allow_suggestion_index: bool = False,
) -> Dict[str, Any]:
    """Retry UIA find using a cleaned selector suggestion from a failed find."""
    if hwnd is None:
        return {"ok": False, "error": "hwnd required"}
    if not isinstance(suggestion, dict) or not suggestion:
        return {"ok": False, "error": "suggestion required"}
    original = dict(original or {})
    selector: Dict[str, Any] = {}
    for key in ("name", "automation_id", "control_type", "class_name", "value", "pattern"):
        value = suggestion.get(key)
        if value not in (None, "", [], {}):
            selector[key] = value
    selector["match"] = suggestion.get("match") or original.get("match") or "contains"
    for key in ("enabled_only", "visible_only"):
        if original.get(key) is not None:
            selector[key] = original.get(key)

    resolved_view = view or original.get("view") or suggestion.get("view") or "raw"
    resolved_max_depth = max_depth if max_depth is not None else original.get("max_depth", 10)
    resolved_max_elements = max_elements if max_elements is not None else original.get("max_elements", 500)
    resolved_limit = max(int(limit or original.get("limit") or 1), 1)

    signal_keys = ("name", "automation_id", "control_type", "class_name", "value", "pattern")
    result: Dict[str, Any] = {}
    if any(selector.get(key) not in (None, "", [], {}) for key in signal_keys):
        result = find_elements(
            hwnd,
            name=selector.get("name"),
            automation_id=selector.get("automation_id"),
            control_type=selector.get("control_type"),
            class_name=selector.get("class_name"),
            value=selector.get("value"),
            pattern=selector.get("pattern"),
            enabled_only=_coerce_bool(selector.get("enabled_only"), False),
            visible_only=_coerce_bool(selector.get("visible_only"), True),
            match=selector.get("match", "contains"),
            limit=resolved_limit,
            max_depth=resolved_max_depth,
            max_elements=resolved_max_elements,
            view=resolved_view,
        )
        result["selector_repair"] = True
        result["suggestion"] = {key: value for key, value in suggestion.items() if key in ("index", "name", "automation_id", "control_type", "class_name", "value", "pattern", "match") and value not in (None, "", [], {})}
        result["ok"] = bool(result.get("matches"))
        if result.get("matches"):
            return result

    if allow_suggestion_index and suggestion.get("index") is not None:
        match = {
            key: value
            for key, value in suggestion.items()
            if key in ("index", "name", "automation_id", "control_type", "class_name", "value", "pattern", "match", "rect", "enabled", "visible")
            and value not in (None, "", [], {})
        }
        return {
            "ok": True,
            "selector_repair": True,
            "suggestion_index_fallback": True,
            "view": result.get("view") or resolved_view,
            "count": 1,
            "matches": [match],
            "suggestion": match,
            **({"last_find": _compact_uia_find_result(result)} if result else {}),
        }

    if result:
        return result
    return {
        "ok": False,
        "error": "selector_suggestion_has_no_searchable_fields",
        "selector_repair": True,
        "view": resolved_view,
        "suggestion": suggestion,
    }


def _uia_cell_repair_selector_from_suggestion(suggestion: Dict[str, Any], original: Dict[str, Any]) -> Dict[str, Any]:
    source = suggestion if isinstance(suggestion, dict) and suggestion else original
    selector: Dict[str, Any] = {}
    for key in ("name", "automation_id", "control_type", "class_name", "value", "pattern"):
        value = source.get(key) if isinstance(source, dict) else None
        if value not in (None, "", [], {}):
            selector[key] = value
    selector["match"] = (source.get("match") if isinstance(source, dict) else None) or original.get("match") or "contains"
    for key in ("enabled_only", "visible_only"):
        if original.get(key) is not None:
            selector[key] = original.get(key)
    return selector


def _uia_cell_repair_patterns(selector: Dict[str, Any], original: Dict[str, Any]) -> List[str]:
    patterns: List[str] = []
    for value in (selector.get("pattern"), original.get("pattern")):
        if value not in (None, "", [], {}) and str(value) not in patterns:
            patterns.append(str(value))
    for value in ("GridItem", "TableItem", "SpreadsheetItem"):
        if value not in patterns:
            patterns.append(value)
    return patterns


def _uia_cell_repair_match(
    item: Dict[str, Any],
    *,
    row: Optional[int],
    column: Optional[int],
    row_text: Optional[str],
    column_name: Optional[str],
    match: str,
) -> bool:
    if not isinstance(item, dict):
        return False
    return _smart_cell_virtualized_item_matches(item, row, column, row_text, column_name, match)


def uia_cell_selector_repair_find(
    hwnd: int,
    suggestion: Optional[Dict[str, Any]] = None,
    original: Optional[Dict[str, Any]] = None,
    *,
    row: Optional[int] = None,
    column: Optional[int] = None,
    row_text: Optional[str] = None,
    column_name: Optional[str] = None,
    limit: int = 1,
    max_depth: Optional[int] = None,
    max_elements: Optional[int] = None,
    view: Optional[str] = None,
) -> Dict[str, Any]:
    """Retry UIA cell lookup with selector suggestions, then prove row/column metadata before acting."""
    if hwnd is None:
        return {"ok": False, "error": "hwnd required"}
    original = dict(original or {})
    suggestion = dict(suggestion or {})
    row = row if row is not None else original.get("row")
    column = column if column is not None else original.get("column")
    row_text = row_text if row_text is not None else original.get("row_text")
    column_name = column_name if column_name is not None else original.get("column_name")
    if (row is None and row_text is None) or (column is None and column_name is None):
        return {
            "ok": False,
            "error": "cell selector repair requires row/row_text and column/column_name",
            "selector_repair": True,
            "cell_selector_repair": True,
        }
    try:
        requested_row = int(row) if row is not None else None
        requested_column = int(column) if column is not None else None
    except Exception:
        return {
            "ok": False,
            "error": "row and column must be integers when provided",
            "selector_repair": True,
            "cell_selector_repair": True,
            "cell": {
                "row": row,
                "column": column,
                "row_text": row_text,
                "column_name": column_name,
            },
        }
    selector = _uia_cell_repair_selector_from_suggestion(suggestion, original)
    resolved_view = view or original.get("view") or suggestion.get("view") or "raw"
    resolved_max_depth = max_depth if max_depth is not None else original.get("max_depth", 12)
    resolved_max_elements = max_elements if max_elements is not None else original.get("max_elements", 1200)
    resolved_limit = max(int(limit or original.get("limit") or 1), 1)
    scan_limit = max(resolved_limit, 250, (requested_row + 1) if requested_row is not None else 1)
    match_mode = selector.get("match", original.get("match", "contains"))
    matches: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []
    last_find: Dict[str, Any] = {}
    for pattern in _uia_cell_repair_patterns(selector, original):
        found = find_elements(
            hwnd,
            name=selector.get("name"),
            automation_id=selector.get("automation_id"),
            control_type=selector.get("control_type"),
            class_name=selector.get("class_name"),
            value=selector.get("value"),
            pattern=pattern,
            enabled_only=_coerce_bool(selector.get("enabled_only"), False),
            visible_only=_coerce_bool(selector.get("visible_only"), True),
            match=match_mode,
            limit=scan_limit,
            max_depth=resolved_max_depth,
            max_elements=resolved_max_elements,
            view=resolved_view,
        )
        if not isinstance(found, dict):
            found = {"error": "invalid_uia_find_result", "result_type": type(found).__name__}
        result_view = found.get("view") or resolved_view
        attempts.append({
            "pattern": pattern,
            "view": result_view,
            "count": found.get("count"),
            **({"error": found.get("error")} if found.get("error") else {}),
        })
        last_find = found
        if _is_terminal_uia_helper_error(found):
            break
        for item in found.get("matches") or []:
            if _uia_cell_repair_match(
                item,
                row=requested_row,
                column=requested_column,
                row_text=row_text,
                column_name=column_name,
                match=match_mode,
            ):
                selected = dict(item)
                selected["uia_view"] = result_view
                if selected not in matches:
                    matches.append(selected)
            if len(matches) >= resolved_limit:
                break
        if len(matches) >= resolved_limit:
            break
    result: Dict[str, Any] = {
        "ok": bool(matches),
        "selector_repair": True,
        "cell_selector_repair": True,
        "hwnd": hwnd,
        "view": (matches[0].get("uia_view") if matches else last_find.get("view") or resolved_view),
        "count": len(matches),
        "matches": matches[:resolved_limit],
        "selector": {key: value for key, value in selector.items() if value not in (None, "", [], {})},
        "cell": {
            "row": requested_row,
            "column": requested_column,
            "row_text": row_text,
            "column_name": column_name,
        },
        "attempts": attempts,
    }
    if suggestion:
        result["suggestion"] = {
            key: value
            for key, value in suggestion.items()
            if key in ("index", "name", "automation_id", "control_type", "class_name", "value", "pattern", "match")
            and value not in (None, "", [], {})
        }
    if not matches:
        result["error"] = "no_matching_uia_cell_after_row_column_filter"
        if last_find:
            result["last_find"] = _compact_uia_find_result(last_find)


def _uia_wait_selector_for_find(selector: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(selector or {})
    cleaned.pop("limit", None)
    for key in (
        "repair",
        "selector_repair",
        "selector-repair",
        "repair_timeout",
        "repair-timeout",
        "selector_repair_timeout",
        "selector-repair-timeout",
        "allow_suggestion_index",
        "allow-suggestion-index",
    ):
        cleaned.pop(key, None)
    cleaned.setdefault("visible_only", True)
    cleaned.setdefault("match", "contains")
    cleaned.setdefault("view", "raw")
    return cleaned


def _uia_wait_repair_timeout(repair_timeout: Optional[float], timeout: float) -> float:
    if repair_timeout is not None:
        try:
            return max(float(repair_timeout), 0.0)
        except Exception:
            return 0.0
    try:
        return min(max(float(timeout), 0.0), 1.0)
    except Exception:
        return 1.0


def _uia_wait_failure_summary_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(result.get("failure_summary"), dict):
        return result.get("failure_summary") or {}
    last_result = result.get("last_result") if isinstance(result.get("last_result"), dict) else {}
    if isinstance(last_result.get("failure_summary"), dict):
        return last_result.get("failure_summary") or {}
    return {}


def _uia_wait_poll(hwnd: int, selector: Dict[str, Any], timeout: float = 10.0, interval: float = 0.5) -> Dict[str, Any]:
    deadline = time.time() + max(timeout, 0.0)
    attempts = 0
    last: Dict[str, Any] = {}
    find_selector = _uia_wait_selector_for_find(selector)
    while True:
        attempts += 1
        last = find_elements(hwnd, limit=1, **find_selector)
        if last.get("matches"):
            return {
                "ok": True,
                "matched": True,
                "hwnd": hwnd,
                "desktop": int(hwnd) == _DESKTOP_UIA_KEY,
                "view": last.get("view", _normalize_uia_view(find_selector.get("view", "raw"))),
                "attempts": attempts,
                "scanned": last.get("scanned", 0),
                "match": last["matches"][0],
            }
        if time.time() >= deadline:
            break
        time.sleep(max(interval, 0.05))
    result = {
        "ok": False,
        "matched": False,
        "error": "timeout",
        "hwnd": hwnd,
        "desktop": int(hwnd) == _DESKTOP_UIA_KEY,
        "view": last.get("view", _normalize_uia_view(find_selector.get("view", "raw"))) if isinstance(last, dict) else _normalize_uia_view(find_selector.get("view", "raw")),
        "attempts": attempts,
        "scanned": last.get("scanned", 0) if isinstance(last, dict) else 0,
        "timeout": timeout,
    }
    if last:
        result["last_result"] = _compact_uia_find_result(last)
    failure_summary = last.get("failure_summary") if isinstance(last, dict) and isinstance(last.get("failure_summary"), dict) else None
    if failure_summary:
        result["failure_summary"] = failure_summary
    return result


def _uia_wait_maybe_repair(
    result: Dict[str, Any],
    hwnd: int,
    selector: Dict[str, Any],
    *,
    timeout: float = 10.0,
    interval: float = 0.5,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
    allow_suggestion_index: bool = False,
) -> Dict[str, Any]:
    if result.get("matched") or result.get("ok") or not _win32_repair_requested(repair, repair_timeout):
        return result
    failure_summary = _uia_wait_failure_summary_from_result(result)
    suggestions = failure_summary.get("selector_suggestions") if isinstance(failure_summary.get("selector_suggestions"), list) else []
    suggestion = next((item for item in suggestions if isinstance(item, dict) and item), None)
    if not suggestion:
        return result
    original = _uia_wait_selector_for_find(selector)
    repair_timeout_value = _uia_wait_repair_timeout(repair_timeout, timeout)
    deadline = time.time() + repair_timeout_value
    repair_attempts = 0
    repair_result: Dict[str, Any] = {}
    while True:
        repair_attempts += 1
        repair_result = uia_selector_repair_find(
            hwnd,
            suggestion,
            original=original,
            limit=1,
            max_depth=original.get("max_depth"),
            max_elements=original.get("max_elements"),
            view=original.get("view"),
            allow_suggestion_index=allow_suggestion_index,
        )
        if repair_result.get("matches"):
            break
        if time.time() >= deadline:
            break
        time.sleep(max(interval, 0.05))
    repair_info = {
        "attempted": True,
        "ok": bool(repair_result.get("matches")),
        "timeout": repair_timeout_value,
        "attempts": repair_attempts,
        "reason": "retry UIA wait with failure_summary.selector_suggestions[0]",
    }
    if isinstance(repair_result.get("selector"), dict):
        repair_info["selector"] = repair_result.get("selector")
    if repair_result.get("matches"):
        matches = list(repair_result.get("matches") or [])
        repaired = {
            "ok": True,
            "matched": True,
            "hwnd": hwnd,
            "desktop": int(hwnd) == _DESKTOP_UIA_KEY,
            "view": repair_result.get("view", original.get("view", "raw")),
            "attempts": int(result.get("attempts", 0) or 0) + repair_attempts,
            "strict_attempts": result.get("attempts"),
            "repair_attempts": repair_attempts,
            "scanned": repair_result.get("scanned", result.get("scanned", 0)),
            "match": matches[0],
            "matches": matches,
            "repaired": True,
            "selector_repair": True,
            "uia_selector_repair": True,
            "repair": repair_info,
            "suggestion": {
                key: value
                for key, value in suggestion.items()
                if key in ("index", "name", "automation_id", "control_type", "class_name", "value", "pattern", "match")
                and value not in (None, "", [], {})
            },
            "original_failure_summary": failure_summary,
        }
        return repaired
    updated = dict(result)
    updated["repair"] = {
        **repair_info,
        "result": _compact_uia_find_result(repair_result),
    }
    return updated


def wait_for_element(
    hwnd: int,
    selector: Dict[str, Any],
    timeout: float = 10.0,
    interval: float = 0.5,
    *,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
    allow_suggestion_index: bool = False,
) -> Dict[str, Any]:
    """Poll until a selector matches at least one UIA element."""
    selector = dict(selector or {})
    repair = _coerce_optional_bool(_dict_get_any(selector, "repair", "selector_repair", "selector-repair", default=repair))
    repair_timeout = _dict_get_any(selector, "repair_timeout", "repair-timeout", "selector_repair_timeout", "selector-repair-timeout", default=repair_timeout)
    allow_suggestion_index = _coerce_bool(_dict_get_any(selector, "allow_suggestion_index", "allow-suggestion-index", default=allow_suggestion_index), False)
    boundary_result = _elevated_helper_required_result(hwnd, "/uia_wait")
    if boundary_result is not None:
        return boundary_result
    helper_ready, helper_elevated = _prepare_helper_for_uia(hwnd)
    if helper_ready:
        payload = dict(selector)
        repair_budget = _uia_wait_repair_timeout(repair_timeout, timeout) if _win32_repair_requested(repair, repair_timeout) else 0.0
        helper_timeout = _uia_helper_timeout(float(timeout or 0.0) + repair_budget)
        payload.update({
            "hwnd": hwnd,
            "selector": selector,
            "timeout": timeout,
            "interval": interval,
            "repair": repair,
            "repair_timeout": repair_timeout,
            "allow_suggestion_index": allow_suggestion_index,
            "uia_timeout": helper_timeout,
        })
        helper_result = _helper_post("/uia_wait", payload, elevated=helper_elevated, timeout=helper_timeout + 1.0)
        if "error" not in helper_result:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
        if _is_terminal_uia_helper_error(helper_result):
            return _mark_uia_helper_error(helper_result, helper_elevated)
    result = _uia_wait_poll(hwnd, selector, timeout=timeout, interval=interval)
    return _uia_wait_maybe_repair(
        result,
        hwnd,
        selector,
        timeout=timeout,
        interval=interval,
        repair=repair,
        repair_timeout=repair_timeout,
        allow_suggestion_index=allow_suggestion_index,
    )



