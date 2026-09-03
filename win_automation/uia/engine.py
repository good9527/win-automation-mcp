"""
UIAutomation COM client lifecycle management, condition factories, and low-level element retrieval.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
import comtypes
import comtypes.client
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ElementNotFoundError, ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.core.utils import is_valid_hwnd, make_lparam, clamp_int

_uia_client = None
_uia_element_cache: Dict[int, Dict[int, Any]] = {}
_uia_ad_hoc_element_indices: Dict[int, set[int]] = {}
_DESKTOP_UIA_KEY = 0

def get_uia_client():
    global _uia_client
    if _uia_client is None:
        try:
            comtypes.CoInitializeEx(None, comtypes.COINIT_MULTITHREADED)
        except Exception:
            pass
        try:
            _uia_client = comtypes.client.CreateObject("{FF48DBA4-60EF-4201-AA87-54103EEF594E}", interface=None)
        except Exception:
            _uia_client = comtypes.client.CreateObject("{E22FD030-B79F-4188-873F-0534247B6968}", interface=None)
    return _uia_client

_get_uia_client = get_uia_client

def _get_root_element():
    uia = get_uia_client()
    return uia.GetRootElement()

def _element_from_handle(hwnd: int):
    uia = get_uia_client()
    return uia.ElementFromHandle(ctypes.c_void_p(int(hwnd)))

def _get_supported_patterns(elem: Any) -> List[str]:
    return _supported_patterns(elem)

# Accessibility tree (items 7, 12 — staleness check, focused/selected)
# ---------------------------------------------------------------------------

def _validate_element(elem) -> bool:
    """Return True if the UI Automation element is still live (not stale)."""
    try:
        _ = elem.CurrentBoundingRectangle
        return True
    except Exception:
        return False


def _safe_attr(elem: Any, attr: str, default: Any = "") -> Any:
    try:
        value = getattr(elem, attr)
        return default if value is None else value
    except Exception:
        return default


def _rect_to_dict(rect: Any) -> Dict[str, int]:
    try:
        return {
            "left": int(rect.left),
            "top": int(rect.top),
            "right": int(rect.right),
            "bottom": int(rect.bottom),
            "width": int(rect.right - rect.left),
            "height": int(rect.bottom - rect.top),
            "center_x": int((rect.left + rect.right) // 2),
            "center_y": int((rect.top + rect.bottom) // 2),
        }
    except Exception:
        return {
            "left": 0, "top": 0, "right": 0, "bottom": 0,
            "width": 0, "height": 0, "center_x": 0, "center_y": 0,
        }


def _is_visible_rect(rect: Dict[str, int]) -> bool:
    """Return False for empty, minimized, or Windows off-screen sentinel rectangles."""
    if rect.get("width", 0) <= 0 or rect.get("height", 0) <= 0:
        return False
    if rect.get("left", 0) <= -30000 or rect.get("top", 0) <= -30000:
        return False
    return True


def _supported_patterns(elem: Any) -> List[str]:
    patterns: List[str] = []
    for name, pattern_id in UIA_PATTERN_IDS.items():
        try:
            if elem.GetCurrentPattern(pattern_id):
                patterns.append(name)
        except Exception:
            pass
    return patterns


def _get_typed_pattern(elem: Any, pattern_name: str) -> Any:
    """Return a UIA pattern cast from IUnknown to its concrete COM interface."""
    raw = elem.GetCurrentPattern(UIA_PATTERN_IDS[pattern_name])
    if not raw:
        return None
    interface_names = {
        "Invoke": "IUIAutomationInvokePattern",
        "Selection": "IUIAutomationSelectionPattern",
        "Value": "IUIAutomationValuePattern",
        "RangeValue": "IUIAutomationRangeValuePattern",
        "Scroll": "IUIAutomationScrollPattern",
        "ExpandCollapse": "IUIAutomationExpandCollapsePattern",
        "Grid": "IUIAutomationGridPattern",
        "GridItem": "IUIAutomationGridItemPattern",
        "MultipleView": "IUIAutomationMultipleViewPattern",
        "Window": "IUIAutomationWindowPattern",
        "SelectionItem": "IUIAutomationSelectionItemPattern",
        "Dock": "IUIAutomationDockPattern",
        "Table": "IUIAutomationTablePattern",
        "TableItem": "IUIAutomationTableItemPattern",
        "Text": "IUIAutomationTextPattern",
        "Toggle": "IUIAutomationTogglePattern",
        "Transform": "IUIAutomationTransformPattern",
        "LegacyIAccessible": "IUIAutomationLegacyIAccessiblePattern",
        "ScrollItem": "IUIAutomationScrollItemPattern",
        "ItemContainer": "IUIAutomationItemContainerPattern",
        "VirtualizedItem": "IUIAutomationVirtualizedItemPattern",
        "SynchronizedInput": "IUIAutomationSynchronizedInputPattern",
        "ObjectModel": "IUIAutomationObjectModelPattern",
        "Annotation": "IUIAutomationAnnotationPattern",
        "Text2": "IUIAutomationTextPattern2",
        "Styles": "IUIAutomationStylesPattern",
        "Spreadsheet": "IUIAutomationSpreadsheetPattern",
        "SpreadsheetItem": "IUIAutomationSpreadsheetItemPattern",
        "Transform2": "IUIAutomationTransformPattern2",
        "TextChild": "IUIAutomationTextChildPattern",
        "Drag": "IUIAutomationDragPattern",
        "DropTarget": "IUIAutomationDropTargetPattern",
        "TextEdit": "IUIAutomationTextEditPattern",
        "CustomNavigation": "IUIAutomationCustomNavigationPattern",
        "Selection2": "IUIAutomationSelectionPattern2",
    }
    try:
        import comtypes.gen.UIAutomationClient as UIAClient
        interface_name = interface_names.get(pattern_name)
        interface = getattr(UIAClient, interface_name) if interface_name else None
        if interface:
            return raw.QueryInterface(interface)
    except Exception:
        pass
    return raw


def _uia_range_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        rp = _get_typed_pattern(elem, "RangeValue")
        if not rp:
            return None
        return {
            "value": float(rp.CurrentValue),
            "minimum": float(rp.CurrentMinimum),
            "maximum": float(rp.CurrentMaximum),
            "small_change": float(rp.CurrentSmallChange),
            "large_change": float(rp.CurrentLargeChange),
            "readonly": bool(rp.CurrentIsReadOnly),
        }
    except Exception:
        return None


def _uia_scroll_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        sp = _get_typed_pattern(elem, "Scroll")
        if not sp:
            return None
        return {
            "horizontal_percent": float(sp.CurrentHorizontalScrollPercent),
            "vertical_percent": float(sp.CurrentVerticalScrollPercent),
            "horizontal_view_size": float(sp.CurrentHorizontalViewSize),
            "vertical_view_size": float(sp.CurrentVerticalViewSize),
            "horizontally_scrollable": bool(sp.CurrentHorizontallyScrollable),
            "vertically_scrollable": bool(sp.CurrentVerticallyScrollable),
        }
    except Exception:
        return None


def _parse_uia_scroll_amount(value: Any) -> int:
    if value is None:
        return UIA_SCROLL_NO_AMOUNT
    if isinstance(value, (int, float)):
        amount = int(value)
        if amount in (0, 1, 2, 3, 4):
            return amount
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if key in UIA_SCROLL_AMOUNT_VALUES:
        return UIA_SCROLL_AMOUNT_VALUES[key]
    raise ValueError("scroll amount must be one of large-decrement, small-decrement, no-amount, large-increment, small-increment")


def _parse_uia_text_unit(value: Any) -> int:
    if value is None:
        return UIA_TEXT_UNIT_VALUES["character"]
    if isinstance(value, (int, float)):
        unit = int(value)
        if unit in (0, 1, 2, 3, 4, 5, 6):
            return unit
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if key in UIA_TEXT_UNIT_VALUES:
        return UIA_TEXT_UNIT_VALUES[key]
    raise ValueError("text unit must be one of character, format, word, line, paragraph, page, document")


def _parse_uia_zoom_unit(value: Any) -> int:
    if value is None:
        return UIA_ZOOM_UNIT_VALUES["no_amount"]
    if isinstance(value, (int, float)):
        unit = int(value)
        if unit in (0, 1, 2, 3, 4):
            return unit
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if key in UIA_ZOOM_UNIT_VALUES:
        return UIA_ZOOM_UNIT_VALUES[key]
    raise ValueError("zoom unit must be one of no-amount, large-decrement, small-decrement, large-increment, small-increment")


def _parse_uia_dock_position(value: Any) -> int:
    if isinstance(value, (int, float)):
        pos = int(value)
        if pos in UIA_DOCK_POSITION_NAMES:
            return pos
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if key in UIA_DOCK_POSITION_VALUES:
        return UIA_DOCK_POSITION_VALUES[key]
    raise ValueError("dock position must be one of top, left, bottom, right, fill, none")


def _parse_uia_sync_input_type(value: Any) -> int:
    if isinstance(value, (int, float)):
        raw = int(value)
        if raw > 0:
            return raw
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in UIA_SYNC_INPUT_TYPE_VALUES:
        return UIA_SYNC_INPUT_TYPE_VALUES[key]
    raise ValueError("synchronized input type must be one of key-down, key-up, left-mouse-down, left-mouse-up, right-mouse-down, right-mouse-up")


def _parse_uia_navigation_direction(value: Any) -> int:
    if isinstance(value, (int, float)):
        raw = int(value)
        if raw in (0, 1, 2, 3, 4):
            return raw
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in UIA_NAVIGATION_DIRECTION_VALUES:
        return UIA_NAVIGATION_DIRECTION_VALUES[key]
    raise ValueError("navigation direction must be parent, next-sibling, previous-sibling, first-child, or last-child")


def _safe_sequence(value: Any, limit: int = 20) -> List[Any]:
    if value is None:
        return []
    try:
        seq = list(value)
    except Exception:
        return []
    return seq[: max(int(limit), 0)]


def _color_to_hex(value: Any) -> str:
    try:
        raw = int(value)
    except Exception:
        return ""
    return f"#{raw & 0xFFFFFF:06x}"


def _uia_text_range_summary(text_range: Any, max_chars: int = 300) -> Dict[str, Any]:
    text = ""
    rectangles: List[Dict[str, int]] = []
    try:
        text = text_range.GetText(max(int(max_chars), 0))
    except Exception:
        text = ""
    try:
        raw_rects = text_range.GetBoundingRectangles()
        values = list(raw_rects) if raw_rects is not None else []
        for i in range(0, len(values) - 3, 4):
            left, top, width, height = (float(values[i]), float(values[i + 1]), float(values[i + 2]), float(values[i + 3]))
            rectangles.append({
                "left": int(left),
                "top": int(top),
                "right": int(left + width),
                "bottom": int(top + height),
                "width": int(width),
                "height": int(height),
                "center_x": int(left + width / 2),
                "center_y": int(top + height / 2),
            })
    except Exception:
        pass
    return {"text": text or "", "rectangles": rectangles}


def _uia_text_info(elem: Any, max_chars: int = 500, max_ranges: int = 3) -> Optional[Dict[str, Any]]:
    try:
        tp = _get_typed_pattern(elem, "Text")
        if not tp:
            return None
        info: Dict[str, Any] = {
            "supported_selection": int(getattr(tp, "SupportedTextSelection", 0)),
            "document": _uia_text_range_summary(tp.DocumentRange, max_chars=max_chars),
            "selection": [],
            "visible_ranges": [],
        }
        try:
            selection = tp.GetSelection()
            for i in range(min(int(selection.Length), max_ranges)):
                info["selection"].append(_uia_text_range_summary(selection.GetElement(i), max_chars=max_chars))
        except Exception:
            pass
        try:
            visible = tp.GetVisibleRanges()
            for i in range(min(int(visible.Length), max_ranges)):
                info["visible_ranges"].append(_uia_text_range_summary(visible.GetElement(i), max_chars=max_chars))
        except Exception:
            pass
        return info
    except Exception:
        return None


def _uia_text_find(elem: Any, text: str, backward: bool = False, ignore_case: bool = True) -> Optional[Any]:
    tp = _get_typed_pattern(elem, "Text")
    if not tp:
        return None
    return tp.DocumentRange.FindText(str(text), bool(backward), bool(ignore_case))


def _normalize_uia_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


_UIA_CLEAR_VALUE_ACTION_ALIASES = {
    "clear",
    "clear_text",
    "clear_value",
    "empty",
    "empty_text",
    "empty_value",
    "erase_text",
    "delete_text",
    "blank_text",
}


def _is_uia_clear_value_action(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", text)
    return text.lower().replace("-", "_").replace(" ", "_") in _UIA_CLEAR_VALUE_ACTION_ALIASES


def _normalize_uia_action_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", text)
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if normalized in _UIA_CLEAR_VALUE_ACTION_ALIASES:
        return "set_value"
    aliases = {
        "click": "invoke",
        "press": "invoke",
        "button": "invoke",
        "tap": "invoke",
        "activate": "invoke",
        "default": "invoke",
        "do_default": "invoke",
        "set_text": "set_value",
        "text_input": "set_value",
        "input_text": "set_value",
        "write_text": "set_value",
        "type_text": "set_value",
    }
    return aliases.get(normalized, normalized)


def _uia_property_id(name: Any) -> int:
    if isinstance(name, (int, float)):
        return int(name)
    key = _normalize_uia_key(name)
    if key in UIA_PROPERTY_IDS:
        return UIA_PROPERTY_IDS[key]
    raise ValueError(f"Unsupported UIA property: {name}")


def _uia_property_value(property_id: int, value: Any) -> Any:
    if property_id == UIA_PROPERTY_IDS["control_type"] and not isinstance(value, (int, float)):
        key = _normalize_uia_key(value)
        if key in UIA_CONTROL_TYPE_IDS:
            return int(UIA_CONTROL_TYPE_IDS[key])
    if property_id in (UIA_PROPERTY_IDS["control_type"],):
        return int(value)
    if property_id in (UIA_PROPERTY_IDS["is_offscreen"],):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return "" if value is None else str(value)


def _uia_item_container_find(
    elem: Any,
    property_name: Any,
    property_value: Any,
    start_after: Any = None,
    limit: int = 1,
) -> List[Any]:
    ip = _get_typed_pattern(elem, "ItemContainer")
    if not ip:
        return []
    property_id = _uia_property_id(property_name)
    value = _uia_property_value(property_id, property_value)
    found: List[Any] = []
    current = start_after
    for _ in range(max(int(limit), 1)):
        item = ip.FindItemByProperty(current, property_id, value)
        if not item:
            break
        found.append(item)
        current = item
    return found


def _register_uia_elements(hwnd: int, elements: List[Any]) -> List[Dict[str, Any]]:
    """Register ad-hoc provider-returned UIA elements so later actions can target them by index."""
    registered: List[Dict[str, Any]] = []
    hwnd_int = int(hwnd)
    hwnd_map = _uia_element_cache.setdefault(hwnd_int, {})
    ad_hoc_indices = _uia_ad_hoc_element_indices.setdefault(hwnd_int, set())
    signatures = _uia_element_signatures.setdefault(hwnd_int, {})
    next_index = (max(hwnd_map.keys()) + 1) if hwnd_map else 0
    for elem in elements:
        idx = next_index
        next_index += 1
        hwnd_map[idx] = elem
        ad_hoc_indices.add(idx)
        info = _element_info(elem, index=idx)
        signatures[idx] = _uia_index_signature(info)
        registered.append(info)
    return registered


def _register_uia_child_elements(hwnd: int, parent_elem: Any, view: Optional[str] = None, max_children: int = 64) -> List[Dict[str, Any]]:
    try:
        import comtypes
        import comtypes.client
        import comtypes.gen.UIAutomationClient as UIAClient
    except ImportError:
        return []
    try:
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=UIAClient.IUIAutomation,
        )
        walker = uia.CreateTreeWalker(_uia_view_condition(uia, _normalize_uia_view(view or "raw")))
        children: List[Any] = []
        child = walker.GetFirstChildElement(parent_elem)
        while child and len(children) < max(int(max_children), 1):
            children.append(child)
            child = walker.GetNextSiblingElement(child)
        return _register_uia_elements(hwnd, children) if children else []
    except Exception:
        return []


def _uia_element_brief(elem: Any) -> Dict[str, Any]:
    try:
        rect = _rect_to_dict(_safe_attr(elem, "CurrentBoundingRectangle", None))
        return {
            "name": _shorten(_safe_attr(elem, "CurrentName", ""), 120),
            "automation_id": _safe_attr(elem, "CurrentAutomationId", ""),
            "control_type": _safe_attr(elem, "CurrentLocalizedControlType", ""),
            "control_type_id": _safe_attr(elem, "CurrentControlType", 0),
            "class_name": _safe_attr(elem, "CurrentClassName", ""),
            "rect": rect,
            "visible": (not bool(_safe_attr(elem, "CurrentIsOffscreen", False))) and _is_visible_rect(rect),
        }
    except Exception:
        return {}


def _uia_element_array_summary(array: Any, max_items: int = 12) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        length = int(array.Length)
    except Exception:
        return items
    for i in range(min(length, max_items)):
        try:
            item = _uia_element_brief(array.GetElement(i))
            if item:
                item["position"] = i
                items.append(item)
        except Exception:
            pass
    return items


def _uia_element_by_index(
    hwnd: int,
    target_index: int,
    max_depth: Optional[int] = None,
    max_elements: Optional[int] = None,
    view: Optional[str] = None,
) -> Tuple[Any, Dict[str, Any]] | Tuple[None, None]:
    """Rescan a window's UIA tree and return the COM element at target_index, repairing stale indexes when possible."""
    hwnd_int = int(hwnd)
    target_index_int = int(target_index)
    if target_index_int in _uia_ad_hoc_element_indices.get(hwnd_int, set()):
        elem = (_uia_element_cache.get(hwnd_int) or {}).get(target_index_int)
        if elem:
            try:
                return elem, _element_info(elem, index=target_index_int, depth=None)
            except Exception:
                return elem, {"index": target_index_int}
    scan_options = _last_uia_scan_options(hwnd)
    if max_depth is None:
        max_depth = int(scan_options.get("max_depth", 10))
    if max_elements is None:
        max_elements = int(scan_options.get("max_elements", 500))
    if view is None:
        view = scan_options.get("view", "raw")
    view = _normalize_uia_view(view)
    try:
        import comtypes
        import comtypes.client
        import comtypes.gen.UIAutomationClient as UIAClient
    except ImportError:
        return None, None

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
            return None, None
        walker = uia.CreateTreeWalker(_uia_view_condition(uia, view))
        counter = [0]
        cache: Dict[int, Any] = {}
        elements: List[Dict[str, Any]] = []

        def walk(elem, depth: int, parent_info: Optional[Dict[str, Any]] = None, ancestor_path: Optional[List[Dict[str, Any]]] = None, sibling_ordinal: int = 0) -> None:
            if depth > max_depth or counter[0] >= max_elements:
                return
            path = ancestor_path or []
            idx = counter[0]
            counter[0] += 1
            cache[idx] = elem
            try:
                info = _element_info(elem, index=idx, depth=depth)
            except Exception:
                info = _element_basic_info(elem, index=idx, depth=depth)
            info = _decorate_uia_structure_info(info, parent_info, path, sibling_ordinal)
            elements.append(info)
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

        old_signature = (_uia_element_signatures.get(hwnd_int) or {}).get(target_index_int)
        walk(root, 0)
        signatures = {int(info["index"]): _uia_index_signature(info) for info in elements if isinstance(info, dict) and info.get("index") is not None}
        _uia_element_cache[hwnd_int] = cache
        _uia_ad_hoc_element_indices[hwnd_int] = set()
        _uia_element_signatures[hwnd_int] = signatures
        _remember_uia_scan_options(hwnd, max_depth, max_elements, view)
        elem = cache.get(target_index_int)
        info = next((item for item in elements if int(item.get("index") or -1) == target_index_int), None)
        if elem and info:
            if old_signature and not _uia_index_same_identity(old_signature, _uia_index_signature(info)):
                relocated_elem, relocated_info, _relocation = _uia_relocate_index_from_signatures(
                    hwnd_int,
                    target_index_int,
                    old_signature,
                    cache,
                    signatures,
                )
                if relocated_elem and relocated_info:
                    return relocated_elem, relocated_info
            return elem, info
        if old_signature:
            relocated_elem, relocated_info, _relocation = _uia_relocate_index_from_signatures(
                hwnd_int,
                target_index_int,
                old_signature,
                cache,
                signatures,
            )
            if relocated_elem and relocated_info:
                return relocated_elem, relocated_info
        return None, None
    except Exception:
        return None, None


def element_from_point(
    x: Optional[int] = None,
    y: Optional[int] = None,
    hwnd: Optional[int] = None,
    screenshot_width: Optional[int] = None,
    screenshot_height: Optional[int] = None,
    screenshot_id: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Return UI Automation metadata for the element under a screen or window point."""
    if x is None or y is None:
        from win_automation.input.mouse import mouse_position
        pos = mouse_position()
        if "error" in pos:
            return {"ok": False, **pos}
        x, y = int(pos["x"]), int(pos["y"])
        screen_x, screen_y = x, y
    elif hwnd is not None and int(hwnd) != 0:
        from win_automation.vision.capture import _scale_coords
        screen_x, screen_y, _ = _scale_coords(int(hwnd), int(x), int(y), screenshot_id)
    else:
        screen_x, screen_y = int(x), int(y)

    try:
        import comtypes.client
        try:
            import comtypes.gen.UIAutomationClient as UIAClient
        except Exception:
            UIAClient = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject("{FF48DBA4-60EF-4201-AA87-54103EEF594E}", interface=UIAClient.IUIAutomation)
        pt = UIAClient.tagPOINT(screen_x, screen_y)
        elem = uia.ElementFromPoint(pt)
        if not elem:
            return {"ok": False, "error": "No element found at point", "screen": {"x": screen_x, "y": screen_y}}
        from win_automation.core.utils import shorten as _shorten
        rect = _rect_to_dict(elem.CurrentBoundingRectangle)
        info = {
            "name": _shorten(elem.CurrentName or "", 120),
            "automation_id": elem.CurrentAutomationId or "",
            "control_type": elem.CurrentLocalizedControlType or "",
            "control_type_id": elem.CurrentControlType,
            "class_name": elem.CurrentClassName or "",
            "rect": rect,
            "visible": (not bool(elem.CurrentIsOffscreen)) and _is_visible_rect(rect),
        }
        return {
            "ok": True,
            "element": info,
            "screen": {"x": screen_x, "y": screen_y},
            "hwnd": hwnd,
        }
    except Exception as ex:
        return {"ok": False, "error": str(ex), "screen": {"x": screen_x, "y": screen_y}}



