"""
UIAutomation control patterns invocation: Invoke, Value, Selection, Toggle, ExpandCollapse,
Scroll, RangeValue, Grid, Table, Transform, ItemContainer, Text, Drag, etc.
"""

from __future__ import annotations

import os
import sys
import time
import json
import ctypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ElementNotFoundError, ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.win32.window import activate_window, focus_hwnd
from win_automation.uia.engine import (
    get_uia_client, _uia_element_by_index, _uia_element_cache, _DESKTOP_UIA_KEY,
    _get_typed_pattern, _normalize_uia_action_name, _normalize_uia_key,
    _is_uia_clear_value_action, _uia_property_id, _uia_property_value,
    _parse_uia_scroll_amount, _parse_uia_text_unit, _parse_uia_sync_input_type
)
from win_automation.uia.cache import _uia_element_signatures, _remember_uia_element_signatures, _uia_relocate_index_from_signatures
from win_automation.uia.repair import _uia_relocation_from_info
from win_automation.helper.client import (
    _helper_route_for_hwnd,
    _helper_post,
    _elevated_helper_required_result,
    _elevated_helper_required_message,
    _prepare_helper_for_uia,
    _uia_helper_timeout,
    _is_terminal_uia_helper_error,
    _mark_uia_helper_error,
)

def _uia_selection_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        sp = _get_typed_pattern(elem, "Selection")
        if not sp:
            return None
        selection = []
        try:
            selection = _uia_element_array_summary(sp.GetCurrentSelection(), max_items=20)
        except Exception:
            pass
        return {
            "can_select_multiple": bool(sp.CurrentCanSelectMultiple),
            "selection_required": bool(sp.CurrentIsSelectionRequired),
            "selected_count": len(selection),
            "selected_items": selection,
        }
    except Exception:
        return None


def _uia_selection_item_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        sp = _get_typed_pattern(elem, "SelectionItem")
        if not sp:
            return None
        info: Dict[str, Any] = {"is_selected": bool(sp.CurrentIsSelected)}
        try:
            container = sp.CurrentSelectionContainer
            if container:
                info["container"] = _uia_element_brief(container)
        except Exception:
            pass
        return info
    except Exception:
        return None


def _uia_grid_info(elem: Any, sample_rows: int = 3, sample_columns: int = 5) -> Optional[Dict[str, Any]]:
    try:
        gp = _get_typed_pattern(elem, "Grid")
        if not gp:
            return None
        rows = int(gp.CurrentRowCount)
        columns = int(gp.CurrentColumnCount)
        sample: List[List[Dict[str, Any]]] = []
        for row in range(min(rows, sample_rows)):
            sample_row: List[Dict[str, Any]] = []
            for column in range(min(columns, sample_columns)):
                try:
                    cell = gp.GetItem(row, column)
                    summary = _uia_element_brief(cell) if cell else {}
                    summary["row"] = row
                    summary["column"] = column
                    sample_row.append(summary)
                except Exception:
                    sample_row.append({"row": row, "column": column, "error": "unavailable"})
            sample.append(sample_row)
        return {"row_count": rows, "column_count": columns, "sample": sample}
    except Exception:
        return None


def _uia_grid_item_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        gp = _get_typed_pattern(elem, "GridItem")
        if not gp:
            return None
        info: Dict[str, Any] = {
            "row": int(gp.CurrentRow),
            "column": int(gp.CurrentColumn),
            "row_span": int(gp.CurrentRowSpan),
            "column_span": int(gp.CurrentColumnSpan),
        }
        try:
            grid = gp.CurrentContainingGrid
            if grid:
                info["containing_grid"] = _uia_element_brief(grid)
        except Exception:
            pass
        return info
    except Exception:
        return None


def _uia_table_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        tp = _get_typed_pattern(elem, "Table")
        if not tp:
            return None
        info: Dict[str, Any] = {"row_or_column_major": int(tp.CurrentRowOrColumnMajor)}
        try:
            info["row_headers"] = _uia_element_array_summary(tp.GetCurrentRowHeaders(), max_items=20)
        except Exception:
            info["row_headers"] = []
        try:
            info["column_headers"] = _uia_element_array_summary(tp.GetCurrentColumnHeaders(), max_items=20)
        except Exception:
            info["column_headers"] = []
        return info
    except Exception:
        return None


def _uia_table_item_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        tp = _get_typed_pattern(elem, "TableItem")
        if not tp:
            return None
        info: Dict[str, Any] = {}
        try:
            info["row_headers"] = _uia_element_array_summary(tp.GetCurrentRowHeaderItems(), max_items=20)
        except Exception:
            info["row_headers"] = []
        try:
            info["column_headers"] = _uia_element_array_summary(tp.GetCurrentColumnHeaderItems(), max_items=20)
        except Exception:
            info["column_headers"] = []
        return info
    except Exception:
        return None


def _uia_multiple_view_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        mp = _get_typed_pattern(elem, "MultipleView")
        if not mp:
            return None
        current = int(mp.CurrentCurrentView)
        views: List[Dict[str, Any]] = []
        try:
            supported = list(mp.GetCurrentSupportedViews())
            for view_id in supported[:20]:
                name = ""
                try:
                    name = str(mp.GetViewName(int(view_id)) or "")
                except Exception:
                    pass
                views.append({"id": int(view_id), "name": name})
        except Exception:
            pass
        return {"current_view": current, "supported_views": views}
    except Exception:
        return None


def _uia_item_container_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        ip = _get_typed_pattern(elem, "ItemContainer")
        if not ip:
            return None
        return {
            "supports_find_item_by_property": True,
            "properties": ["name", "automation_id", "control_type", "class_name", "framework_id", "item_status", "item_type", "value"],
        }
    except Exception:
        return None


def _uia_selection2_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        sp = _get_typed_pattern(elem, "Selection2")
        if not sp:
            return None
        info: Dict[str, Any] = {"item_count": int(getattr(sp, "CurrentItemCount", 0) or 0)}
        for attr, key in (
            ("CurrentFirstSelectedItem", "first_selected_item"),
            ("CurrentLastSelectedItem", "last_selected_item"),
            ("CurrentCurrentSelectedItem", "current_selected_item"),
        ):
            try:
                item = getattr(sp, attr)
                if item:
                    info[key] = _uia_element_brief(item)
            except Exception:
                pass
        return info
    except Exception:
        return None


def _uia_annotation_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        ap = _get_typed_pattern(elem, "Annotation")
        if not ap:
            return None
        info: Dict[str, Any] = {
            "type_id": int(getattr(ap, "CurrentAnnotationTypeId", 0) or 0),
            "type_name": getattr(ap, "CurrentAnnotationTypeName", "") or "",
            "author": getattr(ap, "CurrentAuthor", "") or "",
            "date_time": getattr(ap, "CurrentDateTime", "") or "",
        }
        try:
            target = ap.CurrentTarget
            if target:
                info["target"] = _uia_element_brief(target)
        except Exception:
            pass
        return info
    except Exception:
        return None


def _uia_styles_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        sp = _get_typed_pattern(elem, "Styles")
        if not sp:
            return None
        fill_color = getattr(sp, "CurrentFillColor", 0) or 0
        fill_pattern_color = getattr(sp, "CurrentFillPatternColor", 0) or 0
        return {
            "style_id": int(getattr(sp, "CurrentStyleId", 0) or 0),
            "style_name": getattr(sp, "CurrentStyleName", "") or "",
            "fill_color": int(fill_color),
            "fill_color_hex": _color_to_hex(fill_color),
            "fill_pattern_style": getattr(sp, "CurrentFillPatternStyle", "") or "",
            "fill_pattern_color": int(fill_pattern_color),
            "fill_pattern_color_hex": _color_to_hex(fill_pattern_color),
            "shape": getattr(sp, "CurrentShape", "") or "",
            "extended_properties": _shorten(getattr(sp, "CurrentExtendedProperties", "") or "", 300),
        }
    except Exception:
        return None


def _uia_spreadsheet_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        sp = _get_typed_pattern(elem, "Spreadsheet")
        if not sp:
            return None
        return {"supports_get_item_by_name": True}
    except Exception:
        return None


def _uia_spreadsheet_item_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        sp = _get_typed_pattern(elem, "SpreadsheetItem")
        if not sp:
            return None
        info: Dict[str, Any] = {"formula": _shorten(getattr(sp, "CurrentFormula", "") or "", 300)}
        try:
            info["annotation_objects"] = _uia_element_array_summary(sp.GetCurrentAnnotationObjects(), max_items=10)
        except Exception:
            info["annotation_objects"] = []
        try:
            info["annotation_types"] = [int(x) for x in _safe_sequence(sp.GetCurrentAnnotationTypes(), limit=20)]
        except Exception:
            info["annotation_types"] = []
        return info
    except Exception:
        return None


def _uia_text2_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        tp = _get_typed_pattern(elem, "Text2")
        if not tp:
            return None
        info: Dict[str, Any] = {"supports_range_from_annotation": True}
        try:
            active, caret = tp.GetCaretRange()
            info["caret_active"] = bool(active)
            if caret:
                info["caret_range"] = _uia_text_range_summary(caret, max_chars=120)
        except Exception:
            pass
        return info
    except Exception:
        return None


def _uia_text_child_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        tp = _get_typed_pattern(elem, "TextChild")
        if not tp:
            return None
        info: Dict[str, Any] = {}
        try:
            container = tp.TextContainer
            if container:
                info["text_container"] = _uia_element_brief(container)
        except Exception:
            pass
        try:
            rng = tp.TextRange
            if rng:
                info["text_range"] = _uia_text_range_summary(rng, max_chars=300)
        except Exception:
            pass
        return info
    except Exception:
        return None


def _uia_text_edit_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        tp = _get_typed_pattern(elem, "TextEdit")
        if not tp:
            return None
        info: Dict[str, Any] = {"supports_active_composition": True, "supports_conversion_target": True}
        try:
            rng = tp.GetActiveComposition()
            if rng:
                info["active_composition"] = _uia_text_range_summary(rng, max_chars=300)
        except Exception:
            pass
        try:
            rng = tp.GetConversionTarget()
            if rng:
                info["conversion_target"] = _uia_text_range_summary(rng, max_chars=300)
        except Exception:
            pass
        return info
    except Exception:
        return None


def _uia_drag_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        dp = _get_typed_pattern(elem, "Drag")
        if not dp:
            return None
        info: Dict[str, Any] = {
            "is_grabbed": bool(getattr(dp, "CurrentIsGrabbed", False)),
            "drop_effect": getattr(dp, "CurrentDropEffect", "") or "",
            "drop_effects": [str(x) for x in _safe_sequence(getattr(dp, "CurrentDropEffects", []), limit=20)],
        }
        try:
            info["grabbed_items"] = _uia_element_array_summary(dp.GetCurrentGrabbedItems(), max_items=10)
        except Exception:
            info["grabbed_items"] = []
        return info
    except Exception:
        return None


def _uia_drop_target_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        dp = _get_typed_pattern(elem, "DropTarget")
        if not dp:
            return None
        return {
            "drop_target_effect": getattr(dp, "CurrentDropTargetEffect", "") or "",
            "drop_target_effects": [str(x) for x in _safe_sequence(getattr(dp, "CurrentDropTargetEffects", []), limit=20)],
        }
    except Exception:
        return None


def _uia_custom_navigation_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        cp = _get_typed_pattern(elem, "CustomNavigation")
        if not cp:
            return None
        return {"supports_navigate": True, "directions": ["parent", "next-sibling", "previous-sibling", "first-child", "last-child"]}
    except Exception:
        return None


def _uia_synchronized_input_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        sp = _get_typed_pattern(elem, "SynchronizedInput")
        if not sp:
            return None
        return {"supports_start_listening": True, "input_types": ["key-down", "key-up", "left-mouse-down", "left-mouse-up", "right-mouse-down", "right-mouse-up"]}
    except Exception:
        return None


def _uia_object_model_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        op = _get_typed_pattern(elem, "ObjectModel")
        if not op:
            return None
        return {"supports_underlying_object_model": True}
    except Exception:
        return None


def _uia_legacy_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        lp = _get_typed_pattern(elem, "LegacyIAccessible")
        if not lp:
            return None
        role = int(getattr(lp, "CurrentRole", 0) or 0)
        state = int(getattr(lp, "CurrentState", 0) or 0)
        selection = []
        try:
            selection = _uia_element_array_summary(lp.GetCurrentSelection(), max_items=20)
        except Exception:
            pass
        return {
            "child_id": int(getattr(lp, "CurrentChildId", 0) or 0),
            "name": _shorten(getattr(lp, "CurrentName", "") or "", 160),
            "value": _shorten(getattr(lp, "CurrentValue", "") or "", 160),
            "description": _shorten(getattr(lp, "CurrentDescription", "") or "", 160),
            "role": role,
            "role_text": _msaa_role_text(role),
            "state": state,
            "state_text": _msaa_state_texts(state),
            "help": _shorten(getattr(lp, "CurrentHelp", "") or "", 160),
            "keyboard_shortcut": getattr(lp, "CurrentKeyboardShortcut", "") or "",
            "default_action": getattr(lp, "CurrentDefaultAction", "") or "",
            "selection": selection,
        }
    except Exception:
        return None


def _uia_transform_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        tp = _get_typed_pattern(elem, "Transform")
        if not tp:
            return None
        return {
            "can_move": bool(tp.CurrentCanMove),
            "can_resize": bool(tp.CurrentCanResize),
            "can_rotate": bool(tp.CurrentCanRotate),
        }
    except Exception:
        return None


def _uia_transform2_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        tp = _get_typed_pattern(elem, "Transform2")
        if not tp:
            return None
        return {
            "can_zoom": bool(tp.CurrentCanZoom),
            "zoom_level": float(tp.CurrentZoomLevel),
            "zoom_minimum": float(tp.CurrentZoomMinimum),
            "zoom_maximum": float(tp.CurrentZoomMaximum),
        }
    except Exception:
        return None


def _uia_dock_info(elem: Any) -> Optional[Dict[str, Any]]:
    try:
        dp = _get_typed_pattern(elem, "Dock")
        if not dp:
            return None
        pos = int(dp.CurrentDockPosition)
        return {"position": pos, "position_name": UIA_DOCK_POSITION_NAMES.get(pos, str(pos))}
    except Exception:
        return None


def _element_info(elem: Any, index: Optional[int] = None, depth: Optional[int] = None) -> Dict[str, Any]:
    patterns = _supported_patterns(elem)


def click_index(
    hwnd: int,
    index: int,
    button: str = "left",
    clicks: int = 1,
    max_depth: Optional[int] = None,
    max_elements: Optional[int] = None,
    view: Optional[str] = None,
) -> str:
    """Click the center of a UIA element by its latest accessibility index."""
    boundary_result = _elevated_helper_required_result(hwnd, "/uia_click_index")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    helper_ready, helper_elevated = _prepare_helper_for_uia(hwnd)
    if helper_ready:
        helper_result = _helper_post(
            "/uia_click_index",
            {
                "hwnd": hwnd,
                "index": index,
                "button": button,
                "clicks": clicks,
                "max_depth": max_depth,
                "max_elements": max_elements,
                "view": view,
                "uia_timeout": _uia_helper_timeout(),
            },
            elevated=helper_elevated,
            timeout=_uia_helper_timeout() + 1.0,
        )
        if "error" not in helper_result:
            helper_label = "elevated helper" if helper_elevated else "helper"
            return f"{helper_result.get('message', 'Clicked element')} via {helper_label}"
        if _is_terminal_uia_helper_error(helper_result):
            return f"Error: {helper_result.get('error')} via helper"
    elem, info = _uia_element_by_index(hwnd, index, max_depth=max_depth, max_elements=max_elements, view=view)
    if not elem or not info:
        return f"Error: Element index {index} not found. Run accessibility/find first."
    rect = info["rect"]
    x = rect["center_x"]
    y = rect["center_y"]
    native_hwnd = int(info.get("native_window_handle") or 0)
    if native_hwnd and user32.IsWindow(native_hwnd):
        activate_window(native_hwnd)
    elif int(hwnd) != _DESKTOP_UIA_KEY:
        activate_window(hwnd)
    try:
        from win_automation.input.mouse import _mouse_click_screen
        _mouse_click_screen(x, y, button=button, clicks=clicks)
    except ValueError as e:
        return f"Error: {e}"
    relocation = _uia_relocation_from_info(info)
    if relocation:
        return json.dumps({
            "ok": True,
            "message": f"Clicked element [{index}] at screen({x},{y})",
            "hwnd": hwnd,
            "index": index,
            "x": x,
            "y": y,
            "button": button,
            "clicks": clicks,
            "element": info,
            "relocated": True,
            "relocation": relocation,
        }, ensure_ascii=False)
    return f"Clicked element [{index}] at screen({x},{y})"


def focus_element(
    hwnd: int,
    index: int,
    max_depth: Optional[int] = None,
    max_elements: Optional[int] = None,
    view: Optional[str] = None,
) -> Dict[str, Any]:
    """Set keyboard focus to a UIA element by index."""
    boundary_result = _elevated_helper_required_result(hwnd, "/uia_focus")
    if boundary_result is not None:
        return boundary_result
    helper_ready, helper_elevated = _prepare_helper_for_uia(hwnd)
    if helper_ready:
        helper_result = _helper_post(
            "/uia_focus",
            {
                "hwnd": hwnd,
                "index": index,
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
    elem, info = _uia_element_by_index(hwnd, index, max_depth=max_depth, max_elements=max_elements, view=view)
    if not elem or not info:
        return {"error": f"Element index {index} not found. Run accessibility/find first."}
    native_hwnd = int(info.get("native_window_handle") or 0)
    foreground = (
        focus_hwnd(native_hwnd)
        if native_hwnd and user32.IsWindow(native_hwnd)
        else ({"ok": True, "desktop": True} if int(hwnd) == _DESKTOP_UIA_KEY else focus_hwnd(hwnd))
    )
    try:
        elem.SetFocus()
        native_focus = focus_hwnd(native_hwnd) if native_hwnd and user32.IsWindow(native_hwnd) else None
        _, after = _uia_element_by_index(hwnd, index, max_depth=max_depth, max_elements=max_elements, view=view)
        has_focus = bool((after or info).get("has_keyboard_focus"))
        return _with_uia_relocation({
            "ok": bool(has_focus or (native_focus or {}).get("ok") or (not native_hwnd and foreground.get("ok"))),
            "uia_set_focus": True,
            "desktop": int(hwnd) == _DESKTOP_UIA_KEY,
            "element": after or info,
            "foreground": foreground,
            "native_focus": native_focus,
            "gui_thread_info": gui_thread_info(native_hwnd or None),
        }, after, info)
    except Exception as e:
        return {"error": str(e), "desktop": int(hwnd) == _DESKTOP_UIA_KEY, "element": info, "foreground": foreground, "gui_thread_info": gui_thread_info(native_hwnd or None)}


def set_value(
    hwnd: int,
    index: int,
    value: str,
    max_depth: Optional[int] = None,
    max_elements: Optional[int] = None,
    view: Optional[str] = None,
) -> Dict[str, Any]:
    """Set a UIA ValuePattern element by index."""
    boundary_result = _elevated_helper_required_result(hwnd, "/uia_set_value")
    if boundary_result is not None:
        return boundary_result
    helper_ready, helper_elevated = _prepare_helper_for_uia(hwnd)
    if helper_ready:
        helper_result = _helper_post(
            "/uia_set_value",
            {
                "hwnd": hwnd,
                "index": index,
                "value": value,
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
    elem, info = _uia_element_by_index(hwnd, index, max_depth=max_depth, max_elements=max_elements, view=view)
    if not elem or not info:
        return {"error": f"Element index {index} not found. Run accessibility/find first."}
    try:
        vp = _get_typed_pattern(elem, "Value")
        if not vp:
            return {"error": f"Element {index} does not support Value pattern", "element": info}
        vp.SetValue(value)
        return _with_uia_relocation({"ok": True, "element": info, "value": value}, info)
    except Exception as e:
        return {"error": str(e), "element": info}


def perform_action(
    hwnd: int,
    index: int,
    action: str,
    value: Optional[float] = None,
    horizontal: Any = None,
    vertical: Any = None,
    max_depth: Optional[int] = None,
    max_elements: Optional[int] = None,
    view: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform a UIA pattern action by element index."""
    boundary_result = _elevated_helper_required_result(hwnd, "/uia_action")
    if boundary_result is not None:
        return boundary_result
    helper_ready, helper_elevated = _prepare_helper_for_uia(hwnd)
    if helper_ready:
        clear_value_action = _is_uia_clear_value_action(action)
        action_value = "" if clear_value_action and value is None else value
        helper_action = "set-value" if clear_value_action else action
        helper_result = _helper_post(
            "/uia_action",
            {
                "hwnd": hwnd,
                "index": index,
                "action": helper_action,
                "value": action_value,
                "horizontal": horizontal,
                "vertical": vertical,
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
    elem, info = _uia_element_by_index(hwnd, index, max_depth=max_depth, max_elements=max_elements, view=view)
    if not elem or not info:
        return {"error": f"Element index {index} not found. Run accessibility/find first."}
    action_lower = _normalize_uia_action_name(action)
    try:
        if action_lower == "invoke":
            _get_typed_pattern(elem, "Invoke").Invoke()
        elif action_lower == "toggle":
            _get_typed_pattern(elem, "Toggle").Toggle()
        elif action_lower in ("check", "uncheck"):
            tp = _get_typed_pattern(elem, "Toggle")
            if not tp:
                return {"error": f"Element {index} does not support Toggle pattern", "element": info}
            desired = 1 if action_lower == "check" else 0
            states = []
            for _ in range(3):
                try:
                    current = int(tp.CurrentToggleState)
                except Exception:
                    current = None
                states.append(current)
                if current == desired:
                    _, after = _uia_element_by_index(hwnd, index, max_depth=max_depth, max_elements=max_elements, view=view)
                    return _with_uia_relocation({"ok": True, "action": action, "toggle_state": current, "states": states, "element": after or info}, after, info)
                tp.Toggle()
                time.sleep(0.03)
            _, after = _uia_element_by_index(hwnd, index, max_depth=max_depth, max_elements=max_elements, view=view)
            return _with_uia_relocation({"ok": False, "action": action, "error": "Toggle state did not reach requested value", "desired_toggle_state": desired, "states": states, "element": after or info}, after, info)
        elif action_lower == "expand":
            _get_typed_pattern(elem, "ExpandCollapse").Expand()
        elif action_lower == "collapse":
            _get_typed_pattern(elem, "ExpandCollapse").Collapse()
        elif action_lower == "select":
            _get_typed_pattern(elem, "SelectionItem").Select()
        elif action_lower in ("add_to_selection", "addtoselection", "add_selection", "selection_add"):
            sp = _get_typed_pattern(elem, "SelectionItem")
            if not sp:
                return {"error": f"Element {index} does not support SelectionItem pattern", "element": info}
            sp.AddToSelection()
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "element": after or info}, after, info)
        elif action_lower in ("remove_from_selection", "removefromselection", "remove_selection", "selection_remove", "deselect", "unselect"):
            sp = _get_typed_pattern(elem, "SelectionItem")
            if not sp:
                return {"error": f"Element {index} does not support SelectionItem pattern", "element": info}
            sp.RemoveFromSelection()
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "element": after or info}, after, info)
        elif action_lower == "scrollitem":
            _get_typed_pattern(elem, "ScrollItem").ScrollIntoView()
        elif action_lower in ("set_value", "setvalue", "value"):
            value_to_set = "" if value is None and _is_uia_clear_value_action(action) else value
            if value_to_set is None:
                return {"error": "value required for Value action", "element": info}
            vp = _get_typed_pattern(elem, "Value")
            if not vp:
                return {"error": f"Element {index} does not support Value pattern", "element": info}
            vp.SetValue(str(value_to_set))
            _, after = _uia_element_by_index(hwnd, index, max_depth=max_depth, max_elements=max_elements, view=view)
            return _with_uia_relocation({"ok": True, "action": action, "value": str(value_to_set), "element": after or info}, after, info)
        elif action_lower in ("set_range", "setrange", "range", "rangevalue", "set_range_value"):
            if value is None:
                return {"error": "value required for RangeValue action", "element": info}
            rp = _get_typed_pattern(elem, "RangeValue")
            if not rp:
                return {"error": f"Element {index} does not support RangeValue pattern", "element": info}
            rp.SetValue(float(value))
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "value": float(value), "element": after or info}, after, info)
        elif action_lower == "scroll":
            sp = _get_typed_pattern(elem, "Scroll")
            if not sp:
                return {"error": f"Element {index} does not support Scroll pattern", "element": info}
            horizontal_amount = _parse_uia_scroll_amount(horizontal)
            vertical_amount = _parse_uia_scroll_amount(vertical)
            sp.Scroll(horizontal_amount, vertical_amount)
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({
                "ok": True,
                "action": action,
                "horizontal": horizontal_amount,
                "vertical": vertical_amount,
                "element": after or info,
            }, after, info)
        elif action_lower in ("set_scroll_percent", "setscrollpercent", "scroll_percent"):
            sp = _get_typed_pattern(elem, "Scroll")
            if not sp:
                return {"error": f"Element {index} does not support Scroll pattern", "element": info}
            current = _uia_scroll_info(elem) or {}
            h = float(horizontal) if horizontal is not None else float(current.get("horizontal_percent", -1.0))
            v = float(vertical) if vertical is not None else float(current.get("vertical_percent", -1.0))
            sp.SetScrollPercent(h, v)
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "horizontal_percent": h, "vertical_percent": v, "element": after or info}, after, info)
        elif action_lower in ("text_find", "find_text", "textfind"):
            if value is None:
                return {"error": "value/text required for TextPattern find action", "element": info}
            found = _uia_text_find(elem, str(value))
            if not found:
                return {"ok": False, "action": action, "found": False, "text": str(value), "element": info}
            return _with_uia_relocation({"ok": True, "action": action, "found": True, "text": str(value), "range": _uia_text_range_summary(found, max_chars=500), "element": info}, info)
        elif action_lower in ("text_select", "select_text", "textselect"):
            if value is None:
                return {"error": "value/text required for TextPattern select action", "element": info}
            found = _uia_text_find(elem, str(value))
            if not found:
                return {"ok": False, "action": action, "found": False, "text": str(value), "element": info}
            found.Select()
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "found": True, "text": str(value), "range": _uia_text_range_summary(found, max_chars=500), "element": after or info}, after, info)
        elif action_lower in ("text_scroll_into_view", "scroll_text_into_view", "text_scroll"):
            if value is None:
                return {"error": "value/text required for TextPattern scroll action", "element": info}
            found = _uia_text_find(elem, str(value))
            if not found:
                return {"ok": False, "action": action, "found": False, "text": str(value), "element": info}
            found.ScrollIntoView(True)
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "found": True, "text": str(value), "range": _uia_text_range_summary(found, max_chars=500), "element": after or info}, after, info)
        elif action_lower in ("text_select_range", "select_text_range"):
            tp = _get_typed_pattern(elem, "Text")
            if not tp:
                return {"error": f"Element {index} does not support Text pattern", "element": info}
            start = int(value if value is not None else 0)
            end = int(vertical if vertical is not None else start)
            if end < start:
                start, end = end, start
            rng = tp.DocumentRange.Clone()
            rng.MoveEndpointByRange(UIA_TEXT_ENDPOINT_END, tp.DocumentRange, UIA_TEXT_ENDPOINT_START)
            rng.MoveEndpointByUnit(UIA_TEXT_ENDPOINT_START, UIA_TEXT_UNIT_VALUES["character"], start)
            rng.MoveEndpointByRange(UIA_TEXT_ENDPOINT_END, rng, UIA_TEXT_ENDPOINT_START)
            rng.MoveEndpointByUnit(UIA_TEXT_ENDPOINT_END, UIA_TEXT_UNIT_VALUES["character"], end - start)
            rng.Select()
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "start": start, "end": end, "range": _uia_text_range_summary(rng, max_chars=500), "element": after or info}, after, info)
        elif action_lower in ("set_current_view", "set_view", "view"):
            if value is None:
                return {"error": "value required for MultipleView action", "element": info}
            mp = _get_typed_pattern(elem, "MultipleView")
            if not mp:
                return {"error": f"Element {index} does not support MultipleView pattern", "element": info}
            view_id = int(value)
            mp.SetCurrentView(view_id)
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "view": view_id, "element": after or info}, after, info)
        elif action_lower in ("realize", "virtualized_item_realize", "realize_item"):
            vp = _get_typed_pattern(elem, "VirtualizedItem")
            if not vp:
                return {"error": f"Element {index} does not support VirtualizedItem pattern", "element": info}
            vp.Realize()
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "element": after or info}, after, info)
        elif action_lower in ("item_find", "find_item", "find_item_by_property", "itemcontainer_find"):
            if value is None or horizontal is None:
                return {"error": "ItemContainer find requires value=property_name and horizontal=property_value", "element": info}
            matches = _uia_item_container_find(elem, value, horizontal, limit=int(vertical if vertical is not None else 1))
            registered = _register_uia_elements(hwnd, matches) if matches else []
            return _with_uia_relocation({
                "ok": bool(registered),
                "action": action,
                "property": str(value),
                "value": horizontal,
                "count": len(registered),
                "matches": registered,
                "element": info,
            }, info)
        elif action_lower in ("spreadsheet_get_item", "spreadsheet_get_item_by_name", "get_cell", "cell"):
            if value is None:
                return {"error": "Spreadsheet GetItemByName requires value=name, such as A1", "element": info}
            sp = _get_typed_pattern(elem, "Spreadsheet")
            if not sp:
                return {"error": f"Element {index} does not support Spreadsheet pattern", "element": info}
            item = sp.GetItemByName(str(value))
            registered = _register_uia_elements(hwnd, [item]) if item else []
            return _with_uia_relocation({
                "ok": bool(registered),
                "action": action,
                "name": str(value),
                "item": registered[0] if registered else None,
                "element": info,
            }, info)
        elif action_lower in ("custom_navigate", "navigate"):
            direction_arg = value if value is not None else horizontal
            if direction_arg is None:
                return {"error": "CustomNavigation requires direction value", "element": info}
            cp = _get_typed_pattern(elem, "CustomNavigation")
            if not cp:
                return {"error": f"Element {index} does not support CustomNavigation pattern", "element": info}
            direction = _parse_uia_navigation_direction(direction_arg)
            target = cp.Navigate(direction)
            registered = _register_uia_elements(hwnd, [target]) if target else []
            return _with_uia_relocation({
                "ok": bool(registered),
                "action": action,
                "direction": direction,
                "target": registered[0] if registered else None,
                "element": info,
            }, info)
        elif action_lower in ("sync_start", "synchronized_input_start", "start_listening"):
            sp = _get_typed_pattern(elem, "SynchronizedInput")
            if not sp:
                return {"error": f"Element {index} does not support SynchronizedInput pattern", "element": info}
            input_type = _parse_uia_sync_input_type(value if value is not None else "key-down")
            sp.StartListening(input_type)
            return _with_uia_relocation({"ok": True, "action": action, "input_type": input_type, "element": info}, info)
        elif action_lower in ("sync_cancel", "synchronized_input_cancel", "cancel_listening"):
            sp = _get_typed_pattern(elem, "SynchronizedInput")
            if not sp:
                return {"error": f"Element {index} does not support SynchronizedInput pattern", "element": info}
            sp.Cancel()
            return _with_uia_relocation({"ok": True, "action": action, "element": info}, info)
        elif action_lower in ("legacy_default", "legacy_default_action", "do_default_action", "default_action"):
            lp = _get_typed_pattern(elem, "LegacyIAccessible")
            if not lp:
                return {"error": f"Element {index} does not support LegacyIAccessible pattern", "element": info}
            lp.DoDefaultAction()
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "element": after or info}, after, info)
        elif action_lower in ("legacy_set_value", "legacy_setvalue", "set_legacy_value"):
            if value is None:
                return {"error": "value required for LegacyIAccessible SetValue action", "element": info}
            lp = _get_typed_pattern(elem, "LegacyIAccessible")
            if not lp:
                return {"error": f"Element {index} does not support LegacyIAccessible pattern", "element": info}
            lp.SetValue(str(value))
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "value": str(value), "element": after or info}, after, info)
        elif action_lower in ("legacy_select", "legacy_take_selection"):
            lp = _get_typed_pattern(elem, "LegacyIAccessible")
            if not lp:
                return {"error": f"Element {index} does not support LegacyIAccessible pattern", "element": info}
            flags = int(value if value is not None else MSAA_SELECT_TAKESELECTION)
            lp.Select(flags)
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "flags": flags, "element": after or info}, after, info)
        elif action_lower == "move":
            tp = _get_typed_pattern(elem, "Transform")
            if not tp:
                return {"error": f"Element {index} does not support Transform pattern", "element": info}
            if value is None or horizontal is None:
                return {"error": "move action requires x value and y horizontal argument", "element": info}
            tp.Move(float(value), float(horizontal))
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "x": float(value), "y": float(horizontal), "element": after or info}, after, info)
        elif action_lower == "resize":
            tp = _get_typed_pattern(elem, "Transform")
            if not tp:
                return {"error": f"Element {index} does not support Transform pattern", "element": info}
            if value is None or horizontal is None:
                return {"error": "resize action requires width value and height horizontal argument", "element": info}
            tp.Resize(float(value), float(horizontal))
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "width": float(value), "height": float(horizontal), "element": after or info}, after, info)
        elif action_lower == "rotate":
            tp = _get_typed_pattern(elem, "Transform")
            if not tp:
                return {"error": f"Element {index} does not support Transform pattern", "element": info}
            if value is None:
                return {"error": "rotate action requires degrees value", "element": info}
            tp.Rotate(float(value))
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "degrees": float(value), "element": after or info}, after, info)
        elif action_lower == "zoom":
            tp = _get_typed_pattern(elem, "Transform2")
            if not tp:
                return {"error": f"Element {index} does not support Transform2 pattern", "element": info}
            if value is None:
                return {"error": "zoom action requires zoom value", "element": info}
            tp.Zoom(float(value))
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "zoom": float(value), "element": after or info}, after, info)
        elif action_lower in ("zoom_by_unit", "zoombyunit", "zoom_unit"):
            tp = _get_typed_pattern(elem, "Transform2")
            if not tp:
                return {"error": f"Element {index} does not support Transform2 pattern", "element": info}
            unit = _parse_uia_zoom_unit(value)
            tp.ZoomByUnit(unit)
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "unit": unit, "element": after or info}, after, info)
        elif action_lower in ("set_dock_position", "dock", "set_dock"):
            dp = _get_typed_pattern(elem, "Dock")
            if not dp:
                return {"error": f"Element {index} does not support Dock pattern", "element": info}
            if value is None:
                return {"error": "dock action requires position value", "element": info}
            pos = _parse_uia_dock_position(value)
            dp.SetDockPosition(pos)
            _, after = _uia_element_by_index(hwnd, index)
            return _with_uia_relocation({"ok": True, "action": action, "position": pos, "element": after or info}, after, info)
        elif action_lower in ("close", "maximize", "minimize", "restore"):
            wp = _get_typed_pattern(elem, "Window")
            if action_lower == "close":
                wp.Close()
            elif action_lower == "maximize":
                wp.SetWindowVisualState(1)
            elif action_lower == "minimize":
                wp.SetWindowVisualState(2)
            else:
                wp.SetWindowVisualState(0)
        else:
            return {
                "error": "Unknown action",
                "supported": ["Invoke", "Toggle", "Expand", "Collapse", "Select", "AddToSelection", "RemoveFromSelection", "ScrollItem", "SetValue", "SetRange", "Scroll", "SetScrollPercent", "TextFind", "TextSelect", "TextScrollIntoView", "TextSelectRange", "SetCurrentView", "Realize", "ItemFind", "SpreadsheetGetItem", "CustomNavigate", "SyncStart", "SyncCancel", "LegacyDefault", "LegacySetValue", "LegacySelect", "Move", "Resize", "Rotate", "Zoom", "ZoomByUnit", "SetDockPosition", "Close", "Maximize", "Minimize", "Restore"],
                "element": info,
            }
        return _with_uia_relocation({"ok": True, "action": action, "element": info}, info)
    except Exception as e:
        return {"error": str(e), "action": action, "element": info}






def desktop_click_index(index: int, button: str = "left", clicks: int = 1, max_depth: Optional[int] = None, max_elements: Optional[int] = None, view: Optional[str] = None) -> str:
    """Click a desktop-root UIA element by its screen-space center."""
    return click_index(_DESKTOP_UIA_KEY, index, button=button, clicks=clicks, max_depth=max_depth, max_elements=max_elements, view=view)


def desktop_perform_action(
    index: int,
    action: str,
    value: Optional[float] = None,
    horizontal: Any = None,
    vertical: Any = None,
    max_depth: Optional[int] = None,
    max_elements: Optional[int] = None,
    view: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform a UIA pattern action on a desktop-root element by index."""
    return perform_action(
        _DESKTOP_UIA_KEY,
        index,
        action,
        value=value,
        horizontal=horizontal,
        vertical=vertical,
        max_depth=max_depth,
        max_elements=max_elements,
        view=view,
    )


def _parse_selector_args(args: List[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Parse lightweight selector flags for find/wait commands."""
    selector: Dict[str, Any] = {}
    options: Dict[str, Any] = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--name", "-n") and i + 1 < len(args):
            selector["name"] = args[i + 1]
            i += 2
        elif arg in ("--automation-id", "--id") and i + 1 < len(args):
            selector["automation_id"] = args[i + 1]
            i += 2
        elif arg in ("--control-type", "--type") and i + 1 < len(args):
            selector["control_type"] = args[i + 1]
            i += 2
        elif arg == "--class" and i + 1 < len(args):
            selector["class_name"] = args[i + 1]
            i += 2
        elif arg == "--value" and i + 1 < len(args):
            selector["value"] = args[i + 1]
            i += 2
        elif arg == "--pattern" and i + 1 < len(args):
            selector["pattern"] = args[i + 1]
            i += 2
        elif arg == "--match" and i + 1 < len(args):
            selector["match"] = args[i + 1]
            i += 2
        elif arg == "--exact":
            selector["match"] = "exact"
            i += 1
        elif arg == "--regex":
            selector["match"] = "regex"
            i += 1
        elif arg == "--enabled":
            selector["enabled_only"] = True
            i += 1
        elif arg == "--include-offscreen":
            selector["visible_only"] = False
            i += 1
        elif arg == "--limit" and i + 1 < len(args):
            selector["limit"] = int(args[i + 1])
            i += 2
        elif arg == "--max-depth" and i + 1 < len(args):
            selector["max_depth"] = int(args[i + 1])
            i += 2
        elif arg == "--max-elements" and i + 1 < len(args):
            selector["max_elements"] = int(args[i + 1])
            i += 2
        elif arg == "--view" and i + 1 < len(args):
            selector["view"] = _normalize_uia_view(args[i + 1])
            i += 2
        elif arg == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif arg == "--repair":
            options["repair"] = True
            i += 1
        elif arg == "--no-repair":
            options["repair"] = False
            i += 1
        elif arg == "--repair-timeout" and i + 1 < len(args):
            options["repair_timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--allow-suggestion-index":
            options["allow_suggestion_index"] = True
            i += 1
        else:
            raise ValueError(f"Unknown selector argument: {arg}")
    selector.setdefault("visible_only", True)
    selector.setdefault("match", "contains")
    selector.setdefault("view", "raw")


desktop_click_element = desktop_click_index
desktop_action = desktop_perform_action


def perform_secondary_action(
    index: int,
    action: str,
    hwnd: Optional[int] = None,
    value: Optional[float] = None,
    horizontal: Optional[str] = None,
    vertical: Optional[str] = None,
    text: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Perform a secondary action on an element by index."""
    target_hwnd = int(hwnd) if hwnd is not None else 0
    action_val = text if (value is None and text is not None) else value
    return perform_action(
        target_hwnd,
        index,
        action,
        value=action_val,
        horizontal=horizontal,
        vertical=vertical,
    )


def find_item_in_container(
    index: int,
    property_name: str = "name",
    property_value: str = "",
    hwnd: Optional[int] = None,
    limit: int = 1,
    include_children: bool = False,
    max_children: int = 64,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Find child items through UIA ItemContainer.FindItemByProperty and register returned indexes."""
    target_hwnd = int(hwnd) if hwnd is not None else 0
    elem, info = _uia_element_by_index(target_hwnd, index)
    if not elem or not info:
        return {"ok": False, "error": f"Element index {index} not found", "matches": []}
    from win_automation.uia.engine import _uia_item_container_find, _register_uia_elements, _register_uia_child_elements
    matches = _uia_item_container_find(elem, property_name, property_value, limit=limit)
    registered = _register_uia_elements(target_hwnd, matches) if matches else []
    if include_children and registered:
        for reg_item in registered[:4]:
            idx = reg_item.get("index")
            if idx is not None:
                child_elem, _ = _uia_element_by_index(target_hwnd, idx)
                if child_elem:
                    _register_uia_child_elements(target_hwnd, child_elem, max_children=max_children)
    return {
        "ok": bool(registered),
        "property": property_name,
        "value": property_value,
        "count": len(registered),
        "matches": registered,
        "element": info,
    }


def item_container_find(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Dual-signature adapter for CLI and MCP item container search."""
    if len(args) >= 4:
        hwnd, index, prop_name, prop_val = args[:4]
        return find_item_in_container(
            index=int(index),
            property_name=str(prop_name),
            property_value=str(prop_val),
            hwnd=int(hwnd),
            **kwargs,
        )
    return find_item_in_container(*args, **kwargs)


