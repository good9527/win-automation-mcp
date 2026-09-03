"""
UIAutomation element signature caching, index relocation, and UI stability detection.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.core.utils import is_valid_hwnd, shorten as _shorten
from win_automation.state.persistence import load_state as _load_state, save_state as _save_state
from win_automation.uia.engine import _uia_element_cache
_uia_element_signatures: Dict[int, Dict[int, Dict[str, Any]]] = {}
_uia_scan_options: Dict[int, Dict[str, Any]] = {}
_DESKTOP_UIA_KEY = 0


def _normalize_uia_view(view: Optional[str]) -> str:
    from win_automation.uia.repair import _normalize_uia_view as _impl
    return _impl(view)


def _matches_control_type(elem: Dict[str, Any], expected: str, mode: str) -> bool:
    from win_automation.uia.repair import _matches_control_type as _impl
    return _impl(elem, expected, mode)


def _selector_similarity_score(a: Any, b: Any) -> float:
    from win_automation.uia.repair import _selector_similarity_score as _impl
    return _impl(a, b)


def _selector_text_matches(value: Any, expected: Any, match: str) -> bool:
    from win_automation.uia.repair import _selector_text_matches as _impl
    return _impl(value, expected, match)


def _element_info(elem: Any, index: Optional[int] = None, depth: Optional[int] = None) -> Dict[str, Any]:
    from win_automation.uia.patterns import _element_info as _patterns_element_info
    return _patterns_element_info(elem, index=index, depth=depth)

def _uia_index_signature(info: Dict[str, Any]) -> Dict[str, Any]:
    """Compact identity hint for repairing stale UIA indexes after tree refreshes."""
    rect = info.get("rect") if isinstance(info.get("rect"), dict) else {}
    parent = info.get("parent_signature") if isinstance(info.get("parent_signature"), dict) else {}
    ancestor_path = info.get("ancestor_path") if isinstance(info.get("ancestor_path"), list) else []
    return {
        "index": info.get("index"),
        "depth": int(info.get("depth") or 0),
        "name": _shorten(info.get("name", ""), 160),
        "automation_id": _shorten(info.get("automation_id", ""), 160),
        "control_type": info.get("control_type", ""),
        "control_type_id": int(info.get("control_type_id") or 0),
        "class_name": _shorten(info.get("class_name", ""), 160),
        "framework_id": info.get("framework_id", ""),
        "native_window_handle": int(info.get("native_window_handle") or 0),
        "patterns": sorted(str(pattern) for pattern in (info.get("patterns") or [])),
        "visible": bool(info.get("visible")),
        "enabled": bool(info.get("enabled")),
        "keyboard_focusable": bool(info.get("keyboard_focusable")),
        "rect": {
            "left": int(rect.get("left") or 0),
            "top": int(rect.get("top") or 0),
            "right": int(rect.get("right") or 0),
            "bottom": int(rect.get("bottom") or 0),
            "width": int(rect.get("width") or 0),
            "height": int(rect.get("height") or 0),
            "center_x": int(rect.get("center_x") or 0),
            "center_y": int(rect.get("center_y") or 0),
        },
        "value": _shorten(info.get("value", ""), 160) if info.get("value") is not None else "",
        "sibling_ordinal": int(info.get("sibling_ordinal") or 0),
        "parent": {
            "name": _shorten(parent.get("name", ""), 120),
            "automation_id": _shorten(parent.get("automation_id", ""), 120),
            "control_type": parent.get("control_type", ""),
            "control_type_id": int(parent.get("control_type_id") or 0),
            "class_name": _shorten(parent.get("class_name", ""), 120),
        },
        "ancestor_path": [
            {
                "name": _shorten(item.get("name", ""), 80),
                "automation_id": _shorten(item.get("automation_id", ""), 80),
                "control_type_id": int(item.get("control_type_id") or 0),
                "class_name": _shorten(item.get("class_name", ""), 80),
            }
            for item in ancestor_path[-4:]
            if isinstance(item, dict)
        ],
    }


def _uia_parent_signature(info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(info, dict):
        return {}
    return {
        "name": _shorten(info.get("name", ""), 120),
        "automation_id": _shorten(info.get("automation_id", ""), 120),
        "control_type": info.get("control_type", ""),
        "control_type_id": int(info.get("control_type_id") or 0),
        "class_name": _shorten(info.get("class_name", ""), 120),
    }


def _decorate_uia_structure_info(
    info: Dict[str, Any],
    parent_info: Optional[Dict[str, Any]],
    ancestor_path: List[Dict[str, Any]],
    sibling_ordinal: int,
) -> Dict[str, Any]:
    info["sibling_ordinal"] = int(sibling_ordinal)
    info["parent_signature"] = _uia_parent_signature(parent_info)
    info["ancestor_path"] = [
        _uia_parent_signature(item)
        for item in ancestor_path[-4:]
        if isinstance(item, dict)
    ]
    return info


def _remember_uia_element_signatures(hwnd: int, elements: List[Dict[str, Any]]) -> None:
    hwnd_int = int(hwnd)
    signatures: Dict[int, Dict[str, Any]] = {}
    for info in elements:
        if not isinstance(info, dict) or info.get("index") is None:
            continue
        try:
            signatures[int(info["index"])] = _uia_index_signature(info)
        except Exception:
            continue
    _uia_element_signatures[hwnd_int] = signatures


def _rect_center_distance(a: Any, b: Any) -> float:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 999999.0
    try:
        return math.hypot(float(a.get("center_x") or 0) - float(b.get("center_x") or 0), float(a.get("center_y") or 0) - float(b.get("center_y") or 0))
    except Exception:
        return 999999.0


def _rect_size_delta(a: Any, b: Any) -> float:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 999999.0
    try:
        return abs(float(a.get("width") or 0) - float(b.get("width") or 0)) + abs(float(a.get("height") or 0) - float(b.get("height") or 0))
    except Exception:
        return 999999.0


def _uia_index_signature_score(old: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    if not old or not current:
        return {"score": -1000, "reasons": ["missing_signature"]}
    if old.get("automation_id") and old.get("automation_id") == current.get("automation_id"):
        score += 120
        reasons.append("automation_id")
    elif old.get("automation_id") or current.get("automation_id"):
        score -= 40
        reasons.append("automation_id_mismatch")
    if int(old.get("control_type_id") or 0) and int(old.get("control_type_id") or 0) == int(current.get("control_type_id") or 0):
        score += 80
        reasons.append("control_type_id")
    elif old.get("control_type") and old.get("control_type") == current.get("control_type"):
        score += 45
        reasons.append("control_type")
    else:
        score -= 80
        reasons.append("control_type_mismatch")
    if old.get("class_name") and old.get("class_name") == current.get("class_name"):
        score += 45
        reasons.append("class_name")
    elif old.get("class_name") or current.get("class_name"):
        score -= 20
        reasons.append("class_name_mismatch")
    if old.get("framework_id") and old.get("framework_id") == current.get("framework_id"):
        score += 20
        reasons.append("framework")
    if int(old.get("native_window_handle") or 0) and int(old.get("native_window_handle") or 0) == int(current.get("native_window_handle") or 0):
        score += 60
        reasons.append("native_hwnd")
    old_patterns = set(str(pattern) for pattern in (old.get("patterns") or []))
    current_patterns = set(str(pattern) for pattern in (current.get("patterns") or []))
    if old_patterns:
        overlap = len(old_patterns & current_patterns)
        score += min(overlap * 12, 60)
        if overlap:
            reasons.append("patterns")
        missing = len(old_patterns - current_patterns)
        if missing:
            score -= min(missing * 8, 40)
            reasons.append("pattern_miss")
    name_score = _selector_similarity_score(current.get("name"), old.get("name"))
    if old.get("name"):
        score += name_score
        reasons.append(f"name_similarity:{name_score}")
    value_score = _selector_similarity_score(current.get("value"), old.get("value"))
    if old.get("value"):
        score += min(value_score, 35)
        reasons.append(f"value_similarity:{value_score}")
    old_parent = old.get("parent") if isinstance(old.get("parent"), dict) else {}
    current_parent = current.get("parent") if isinstance(current.get("parent"), dict) else {}
    parent_score = 0
    if old_parent and current_parent:
        if old_parent.get("automation_id") and old_parent.get("automation_id") == current_parent.get("automation_id"):
            parent_score += 55
            reasons.append("parent_automation_id")
        elif old_parent.get("automation_id") or current_parent.get("automation_id"):
            parent_score -= 25
            reasons.append("parent_automation_id_mismatch")
        if int(old_parent.get("control_type_id") or 0) and int(old_parent.get("control_type_id") or 0) == int(current_parent.get("control_type_id") or 0):
            parent_score += 25
            reasons.append("parent_control_type")
        if old_parent.get("class_name") and old_parent.get("class_name") == current_parent.get("class_name"):
            parent_score += 20
            reasons.append("parent_class")
        parent_name_score = _selector_similarity_score(current_parent.get("name"), old_parent.get("name"))
        if old_parent.get("name"):
            parent_score += min(parent_name_score, 35)
            reasons.append(f"parent_name_similarity:{parent_name_score}")
    score += max(min(parent_score, 95), -35)
    old_path = old.get("ancestor_path") if isinstance(old.get("ancestor_path"), list) else []
    current_path = current.get("ancestor_path") if isinstance(current.get("ancestor_path"), list) else []
    path_matches = 0
    for old_item, current_item in zip(reversed(old_path), reversed(current_path)):
        if not isinstance(old_item, dict) or not isinstance(current_item, dict):
            continue
        item_score = 0
        if old_item.get("automation_id") and old_item.get("automation_id") == current_item.get("automation_id"):
            item_score += 2
        if int(old_item.get("control_type_id") or 0) and int(old_item.get("control_type_id") or 0) == int(current_item.get("control_type_id") or 0):
            item_score += 1
        if old_item.get("class_name") and old_item.get("class_name") == current_item.get("class_name"):
            item_score += 1
        if _selector_similarity_score(current_item.get("name"), old_item.get("name")) >= 45:
            item_score += 1
        if item_score >= 2:
            path_matches += 1
    if path_matches:
        score += min(path_matches * 12, 36)
        reasons.append(f"ancestor_path:{path_matches}")
    old_sibling = int(old.get("sibling_ordinal") or 0)
    current_sibling = int(current.get("sibling_ordinal") or 0)
    if old_sibling == current_sibling:
        score += 10
        reasons.append("sibling_ordinal")
    elif abs(old_sibling - current_sibling) <= 1:
        score += 4
        reasons.append("sibling_ordinal_near")
    else:
        score -= min(abs(old_sibling - current_sibling) * 3, 18)
        reasons.append("sibling_ordinal_delta")
    if int(old.get("depth") or 0) == int(current.get("depth") or 0):
        score += 15
        reasons.append("depth")
    else:
        score -= min(abs(int(old.get("depth") or 0) - int(current.get("depth") or 0)) * 5, 25)
        reasons.append("depth_delta")
    distance = _rect_center_distance(old.get("rect"), current.get("rect"))
    size_delta = _rect_size_delta(old.get("rect"), current.get("rect"))
    if distance <= 8:
        score += 35
        reasons.append("rect_center")
    elif distance <= 80:
        score += 15
        reasons.append("rect_near")
    elif distance < 999999:
        score -= min(int(distance // 100), 35)
        reasons.append("rect_far")
    if size_delta <= 8:
        score += 20
        reasons.append("rect_size")
    elif size_delta <= 80:
        score += 8
        reasons.append("rect_size_near")
    return {"score": score, "reasons": reasons, "distance": round(distance, 3), "size_delta": round(size_delta, 3)}


def _uia_index_hard_mismatch(old: Dict[str, Any], current: Dict[str, Any]) -> bool:
    if not old or not current:
        return True
    old_auto = str(old.get("automation_id") or "")
    current_auto = str(current.get("automation_id") or "")
    if old_auto and old_auto != current_auto:
        return True
    old_type = int(old.get("control_type_id") or 0)
    current_type = int(current.get("control_type_id") or 0)
    if old_type and current_type and old_type != current_type:
        return True
    old_native = int(old.get("native_window_handle") or 0)
    current_native = int(current.get("native_window_handle") or 0)
    same_stable_anchor = bool(old_auto and old_auto == current_auto) or bool(old_native and current_native and old_native == current_native)
    if old_native and current_native and old_native != current_native and not same_stable_anchor:
        return True
    old_name = old.get("name")
    current_name = current.get("name")
    if old_name and current_name and not same_stable_anchor and _selector_similarity_score(current_name, old_name) < 35:
        return True
    old_parent = old.get("parent") if isinstance(old.get("parent"), dict) else {}
    current_parent = current.get("parent") if isinstance(current.get("parent"), dict) else {}
    if old_parent and current_parent and not same_stable_anchor:
        old_parent_auto = str(old_parent.get("automation_id") or "")
        current_parent_auto = str(current_parent.get("automation_id") or "")
        if old_parent_auto and current_parent_auto and old_parent_auto != current_parent_auto:
            return True
        old_parent_type = int(old_parent.get("control_type_id") or 0)
        current_parent_type = int(current_parent.get("control_type_id") or 0)
        if old_parent_type and current_parent_type and old_parent_type != current_parent_type:
            return True
    return False


def _uia_index_same_identity(old: Dict[str, Any], current: Dict[str, Any]) -> bool:
    if _uia_index_hard_mismatch(old, current):
        return False
    diagnostic = _uia_index_signature_score(old, current)
    return int(diagnostic.get("score") or 0) >= 170


def _uia_relocate_index_from_signatures(
    hwnd: int,
    target_index: int,
    old_signature: Dict[str, Any],
    cache: Dict[int, Any],
    signatures: Dict[int, Dict[str, Any]],
) -> Tuple[Any, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    best_index: Optional[int] = None
    best_diag: Dict[str, Any] = {}
    best_score = -100000
    for idx, current_signature in signatures.items():
        if int(idx) == int(target_index):
            continue
        if _uia_index_hard_mismatch(old_signature, current_signature):
            continue
        diagnostic = _uia_index_signature_score(old_signature, current_signature)
        score = int(diagnostic.get("score") or 0)
        if score > best_score:
            best_score = score
            best_index = int(idx)
            best_diag = diagnostic
    if best_index is None or best_score < 150:
        return None, None, None
    elem = cache.get(best_index)
    if not elem:
        return None, None, None
    info = _element_info(elem, index=best_index, depth=signatures.get(best_index, {}).get("depth"))
    info["relocated_from_index"] = int(target_index)
    info["relocation"] = {
        "from_index": int(target_index),
        "to_index": best_index,
        "score": best_score,
        "reasons": best_diag.get("reasons") or [],
    }
    info["relocated"] = True
    _uia_element_cache.setdefault(int(hwnd), {})[int(target_index)] = elem
    _uia_element_signatures.setdefault(int(hwnd), {})[int(target_index)] = _uia_index_signature(info)
    return elem, info, info["relocation"]


def _uia_relocation_from_info(info: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(info, dict):
        return None
    relocation = info.get("relocation")
    if isinstance(relocation, dict):
        return dict(relocation)
    if info.get("relocated_from_index") is not None and info.get("index") is not None:
        try:
            return {
                "from_index": int(info.get("relocated_from_index")),
                "to_index": int(info.get("index")),
            }
        except Exception:
            return None
    return None


def _with_uia_relocation(result: Dict[str, Any], *infos: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return result
    for info in infos:
        relocation = _uia_relocation_from_info(info)
        if relocation:
            result["relocation"] = relocation
            result["relocated"] = True
            return result
    return result


def _hydrate_element_info(hwnd: int, info: Dict[str, Any]) -> Dict[str, Any]:
    idx = info.get("index")
    if idx is None:
        return info
    elem = (_uia_element_cache.get(hwnd) or {}).get(int(idx))
    if not elem:
        return info
    try:
        return _element_info(elem, index=int(idx), depth=info.get("depth"))
    except Exception:
        return info


def _format_element_line(info: Dict[str, Any]) -> str:
    indent = "  " * int(info.get("depth") or 0)
    extras = []
    if info.get("automation_id"):
        extras.append(f'id="{info["automation_id"]}"')
    if info.get("class_name"):
        extras.append(f'class="{info["class_name"]}"')
    if info.get("value"):
        extras.append(f'value="{info["value"]}"')
    if info.get("offscreen"):
        extras.append("offscreen=true")
    pattern_str = f" [{', '.join(info.get('patterns') or [])}]" if info.get("patterns") else ""
    extras_str = (" " + " ".join(extras)) if extras else ""
    return f'{indent}[{info["index"]}] "{info.get("name", "")}" ({info.get("control_type", "")}){pattern_str}{extras_str}'


def _shorten(value: Any, limit: int = 160) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def _summarize_element(info: Dict[str, Any]) -> Dict[str, Any]:
    """Return action-oriented element metadata without huge text/value payloads."""
    summary = {
        "index": info.get("index"),
        "depth": info.get("depth"),
        "name": _shorten(info.get("name", ""), 120),
        "automation_id": info.get("automation_id", ""),
        "control_type": info.get("control_type", ""),
        "class_name": info.get("class_name", ""),
        "enabled": info.get("enabled", False),
        "visible": info.get("visible", False),
        "rect": info.get("rect", {}),
        "patterns": info.get("patterns", []),
    }
    if "value" in info:
        summary["value"] = _shorten(info.get("value", ""), 120)
    if "range_value" in info:
        summary["range_value"] = info.get("range_value")
    if "scroll" in info:
        summary["scroll"] = info.get("scroll")
    if "text" in info:
        text_info = info.get("text") or {}
        summary["text"] = {
            "supported_selection": text_info.get("supported_selection"),
            "document": {
                "text": _shorten(((text_info.get("document") or {}).get("text") or ""), 180),
                "rectangles": (text_info.get("document") or {}).get("rectangles", [])[:3],
            },
            "selection": [
                {"text": _shorten(item.get("text", ""), 120), "rectangles": item.get("rectangles", [])[:3]}
                for item in (text_info.get("selection") or [])[:2]
            ],
            "visible_ranges": [
                {"text": _shorten(item.get("text", ""), 120), "rectangles": item.get("rectangles", [])[:3]}
                for item in (text_info.get("visible_ranges") or [])[:2]
            ],
        }
    if "selection" in info:
        selection = info.get("selection") or {}
        summary["selection"] = {
            "can_select_multiple": selection.get("can_select_multiple"),
            "selection_required": selection.get("selection_required"),
            "selected_count": selection.get("selected_count", 0),
            "selected_items": (selection.get("selected_items") or [])[:5],
        }
    if "selection_item" in info:
        summary["selection_item"] = {
            "is_selected": (info.get("selection_item") or {}).get("is_selected", False)
        }
    if "grid" in info:
        grid = info.get("grid") or {}
        summary["grid"] = {
            "row_count": grid.get("row_count"),
            "column_count": grid.get("column_count"),
            "sample": grid.get("sample", [])[:2],
        }
    if "grid_item" in info:
        summary["grid_item"] = info.get("grid_item")
    if "table" in info:
        table = info.get("table") or {}
        summary["table"] = {
            "row_or_column_major": table.get("row_or_column_major"),
            "row_headers": (table.get("row_headers") or [])[:5],
            "column_headers": (table.get("column_headers") or [])[:5],
        }
    if "table_item" in info:
        summary["table_item"] = info.get("table_item")
    if "multiple_view" in info:
        summary["multiple_view"] = info.get("multiple_view")
    if "item_container" in info:
        summary["item_container"] = info.get("item_container")
    if "selection2" in info:
        summary["selection2"] = info.get("selection2")
    if "annotation" in info:
        summary["annotation"] = info.get("annotation")
    if "styles" in info:
        styles = info.get("styles") or {}
        summary["styles"] = {
            "style_id": styles.get("style_id"),
            "style_name": _shorten(styles.get("style_name", ""), 120),
            "fill_color_hex": styles.get("fill_color_hex", ""),
            "shape": _shorten(styles.get("shape", ""), 120),
        }
    if "spreadsheet" in info:
        summary["spreadsheet"] = info.get("spreadsheet")
    if "spreadsheet_item" in info:
        item = info.get("spreadsheet_item") or {}
        summary["spreadsheet_item"] = {
            "formula": _shorten(item.get("formula", ""), 160),
            "annotation_types": item.get("annotation_types", []),
            "annotation_objects": (item.get("annotation_objects") or [])[:5],
        }
    if "text2" in info:
        summary["text2"] = info.get("text2")
    if "text_child" in info:
        summary["text_child"] = info.get("text_child")
    if "text_edit" in info:
        summary["text_edit"] = info.get("text_edit")
    if "drag" in info:
        summary["drag"] = info.get("drag")
    if "drop_target" in info:
        summary["drop_target"] = info.get("drop_target")
    if "custom_navigation" in info:
        summary["custom_navigation"] = info.get("custom_navigation")
    if "synchronized_input" in info:
        summary["synchronized_input"] = info.get("synchronized_input")
    if "object_model" in info:
        summary["object_model"] = info.get("object_model")
    if "legacy" in info:
        legacy = info.get("legacy") or {}
        summary["legacy"] = {
            "name": _shorten(legacy.get("name", ""), 120),
            "value": _shorten(legacy.get("value", ""), 120),
            "role_text": legacy.get("role_text", ""),
            "state_text": legacy.get("state_text", []),
            "default_action": legacy.get("default_action", ""),
        }
    if "transform" in info:
        summary["transform"] = info.get("transform")
    if "transform2" in info:
        summary["transform2"] = info.get("transform2")
    if "dock" in info:
        summary["dock"] = info.get("dock")
    return summary




def _last_uia_scan_options(hwnd: int) -> Dict[str, Any]:
    hwnd_int = int(hwnd)
    options = dict(_uia_scan_options.get(hwnd_int, {}))
    if options:
        return options
    state = _load_state()
    scans = state.get("uia_scans", {})
    if isinstance(scans, dict):
        stored = scans.get(str(hwnd_int))
        if isinstance(stored, dict):
            return dict(stored)
    return {}


def _remember_uia_scan_options(hwnd: int, max_depth: int, max_elements: int, view: str) -> None:
    hwnd_int = int(hwnd)
    normalized = _normalize_uia_view(view)
    options = {"max_depth": int(max_depth), "max_elements": int(max_elements), "view": normalized}
    _uia_scan_options[hwnd_int] = options
    state = _load_state()
    scans = state.get("uia_scans", {})
    if not isinstance(scans, dict):
        scans = {}
    scans[str(hwnd_int)] = options
    if len(scans) > 20:
        scans = dict(list(scans.items())[-20:])
    state["uia_scans"] = scans
    _save_state(state)


def _parse_uia_scan_args(args: List[str], hwnd: Optional[int] = None) -> Tuple[Dict[str, Any], List[str]]:
    """Parse UIA scan options and return non-option action arguments."""
    base = _last_uia_scan_options(hwnd) if hwnd is not None else {}
    options: Dict[str, Any] = {
        "max_depth": int(base.get("max_depth", 10)),
        "max_elements": int(base.get("max_elements", 500)),
        "view": _normalize_uia_view(base.get("view", "raw")),
    }
    remaining: List[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--view" and i + 1 < len(args):
            options["view"] = _normalize_uia_view(args[i + 1])
            i += 2
        elif arg == "--max-depth" and i + 1 < len(args):
            options["max_depth"] = int(args[i + 1])
            i += 2
        elif arg == "--max-elements" and i + 1 < len(args):
            options["max_elements"] = int(args[i + 1])
            i += 2
        else:
            remaining.append(arg)
            i += 1
    return options, remaining


def _filter_elements(
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
    limit: int = 25,
    collect_all: bool = False,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for elem in elements:
        if name is not None and not _selector_text_matches(elem.get("name", ""), name, match):
            continue
        if automation_id is not None and not _selector_text_matches(elem.get("automation_id", ""), automation_id, match):
            continue
        if control_type is not None and not _matches_control_type(elem, control_type, match):
            continue
        if class_name is not None and not _selector_text_matches(elem.get("class_name", ""), class_name, match):
            continue
        if value is not None and not _selector_text_matches(elem.get("value", ""), value, match):
            continue
        if pattern is not None and pattern.lower() not in [p.lower() for p in elem.get("patterns", [])]:
            continue
        if enabled_only and not elem.get("enabled", False):
            continue
        if visible_only:
            if not elem.get("visible", False):
                continue
        results.append(elem)
        if not collect_all and len(results) >= limit:
            break
    return results


