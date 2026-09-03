"""
High-intent smart automation router: smart_click, smart_text_input, smart_select, smart_cell, smart_dialog_action.
Intelligently cascades through UIAutomation, native Win32 controls, and coordinate-based fallbacks.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.core.utils import is_valid_hwnd, rect_center, _rect_center
from win_automation.win32.window import _window_info, activate_window, focus_hwnd, _win32_window_info
from win_automation.win32.controls import win32_click, win32_set_text, win32_control_info, win32_control_action
from win_automation.win32.find import win32_control_find
from win_automation.win32.dialog import file_dialog_info, file_dialog_action, dialog_command_action
from win_automation.uia.engine import get_uia_client, _uia_element_cache, _DESKTOP_UIA_KEY
from win_automation.uia.tree import find_elements, build_accessibility_tree
from win_automation.uia.patterns import click_index, perform_action
from win_automation.uia.repair import uia_selector_repair_find
from win_automation.input.keyboard import type_text, press_key
from win_automation.input.mouse import move_mouse
from win_automation.helper.client import _helper_route_for_hwnd, _helper_post, _elevated_helper_required_result, _is_terminal_uia_helper_error
from win_automation.state.persistence import resolve_target_hwnd

def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)

    return {"ok": not failures, "method": "WM_CHAR", "sent": sent, "failures": failures}


def focused_input(
    hwnd: int | None,
    text: str,
    mode: str = "auto",
    timeout: float = 1.0,
    restore: bool = True,
    timeout_ms: int = 500,
    verify: bool = True,
    diagnostic: bool = False,
    allow_focus_fallback: bool = False,
) -> Dict[str, Any]:
    """Input text into the HWND that truly owns keyboard focus for a window."""
    target = _resolve_target(hwnd)
    if not user32.IsWindow(target):
        return {"ok": False, "error": f"Window {target} no longer exists", "hwnd": target}

    requested_mode = (mode or "auto").lower().replace("-", "_")
    if requested_mode in ("replace_sel", "insert", "type"):
        requested_mode = "replace_selection"
    if requested_mode in ("set", "set_text", "replace_all"):
        requested_mode = "set_text"
    if requested_mode in ("send_input", "unicode"):
        requested_mode = "sendinput"
    if requested_mode not in ("auto", "replace_selection", "set_text", "append", "sendinput", "wm_char"):
        return {
            "ok": False,
            "error": f"Unsupported focused-input mode: {mode}",
            "supported": ["auto", "replace-selection", "set-text", "append", "sendinput", "wm-char"],
        }

    root = int(user32.GetAncestor(target, GA_ROOT) or target)
    target_is_child = target != root or _is_child_hwnd(target)
    activation = focus_hwnd(target, timeout=timeout, restore=restore) if target_is_child else _foreground_hwnd(root, timeout=timeout, restore=restore)

    focus_hwnd_value, before_gui = _focused_hwnd_from_root(root)
    if target_is_child:
        focus_hwnd_value = int(target)
    focus_info = _win32_window_info(focus_hwnd_value, include_text=True) if focus_hwnd_value else None
    kind = _native_text_control_kind(focus_hwnd_value)
    if kind == "combo":
        try:
            combo_info = win32_control_info(focus_hwnd_value, timeout_ms=timeout_ms)
            combo_edit_hwnd = int(combo_info.get("edit_hwnd") or 0)
            if combo_edit_hwnd and user32.IsWindow(combo_edit_hwnd):
                focus_hwnd_value = combo_edit_hwnd
                focus_info = _win32_window_info(focus_hwnd_value, include_text=True)
                kind = _native_text_control_kind(focus_hwnd_value) or "edit"
        except Exception:
            pass
    before_state = _read_native_text_state(focus_hwnd_value, kind, timeout_ms=timeout_ms) if focus_hwnd_value else {}
    before_text = _text_from_state(before_state)
    selection = _selection_from_state(before_state)
    method_result: Dict[str, Any] = {}
    method = ""
    expected_text: Optional[str] = None

    if requested_mode == "auto":
        effective_mode = "replace_selection" if kind in ("edit", "richedit") else "sendinput"
    else:
        effective_mode = requested_mode

    if effective_mode in ("replace_selection", "append") and kind in ("edit", "richedit"):
        if effective_mode == "append":
            end_pos = len(before_text)
            if kind == "richedit":
                sel_ok, sel_result = _richedit_set_selection(focus_hwnd_value, end_pos, end_pos, timeout_ms=timeout_ms)
            else:
                sel_ok, sel_result = _edit_set_selection(focus_hwnd_value, end_pos, end_pos, timeout_ms=timeout_ms)
            selection = {"start": end_pos, "end": end_pos}
            method_result["selection_set"] = {"ok": bool(sel_ok), "result": sel_result}
        if kind == "richedit":
            ok, msg_result = _richedit_replace_selection(focus_hwnd_value, str(text), timeout_ms=timeout_ms)
        else:
            ok, msg_result = _edit_replace_selection(focus_hwnd_value, str(text), timeout_ms=timeout_ms)
        method = f"{kind}.EM_REPLACESEL"
        start = max(int(selection.get("start", 0)), 0)
        end = max(int(selection.get("end", start)), start)
        expected_text = before_text[:start] + str(text) + before_text[end:]
        method_result.update({"ok": bool(ok), "result": msg_result, "selection": selection})
    elif effective_mode == "set_text" and kind in ("edit", "richedit", "combo"):
        set_result = win32_set_text(focus_hwnd_value, str(text), timeout_ms=timeout_ms)
        method = f"{kind or 'window'}.WM_SETTEXT"
        expected_text = str(text)
        method_result.update(set_result)
    elif effective_mode == "wm_char":
        method_result = _send_text_wm_char(focus_hwnd_value, str(text), timeout_ms=min(timeout_ms, 250))
        method = "WM_CHAR"
    else:
        method_result = _send_text_unicode(str(text))
        method = "SendInputUnicode"

    time.sleep(0.05)
    after_gui = gui_thread_info(hwnd=root)
    after_state = _read_native_text_state(focus_hwnd_value, kind, timeout_ms=timeout_ms) if focus_hwnd_value else {}
    after_text = _text_from_state(after_state)
    verified: Optional[bool] = None
    if verify and expected_text is not None:
        verified = after_text == expected_text
    elif verify and method in ("WM_CHAR", "SendInputUnicode") and kind in ("edit", "richedit"):
        verified = after_text != before_text or not text

    ok = bool(method_result.get("ok"))
    if verified is False and expected_text is not None:
        ok = False

    return {
        "ok": ok,
        "hwnd": int(target),
        "root_hwnd": int(root),
        "focus_hwnd": int(focus_hwnd_value or 0),
        "target_is_child": bool(target_is_child),
        "requested_mode": requested_mode,
        "mode": effective_mode,
        "method": method,
        "text_length": len(str(text)),
        "verified": verified,
        "activation": activation if diagnostic else _compact_focus_result(activation),
        "focus_window": focus_info if diagnostic else _compact_window_info(focus_info),
        "native_kind": kind or None,
        "before_gui_thread_info": before_gui if diagnostic else _compact_gui_thread_info(before_gui),
        "after_gui_thread_info": after_gui if diagnostic else _compact_gui_thread_info(after_gui),
        "before_text": before_state,
        "after_text": after_state,
        "expected_text": expected_text,
        "result": method_result,
    }


def _win32_text_input_candidates(
    hwnd: int,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    class_name: Optional[str] = None,
    control_type: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    include_invisible: bool = False,
    timeout_ms: int = 500,
) -> List[Dict[str, Any]]:
    children = _child_windows_direct(hwnd, include_invisible=include_invisible, include_text=True, max_count=1000)
    items = list(children.get("children") or [])
    candidates: List[Dict[str, Any]] = []
    wanted_index = int(index) if index is not None else None
    wanted_kind = str(control_type or "").strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    for child in items:
        child_hwnd = int(child.get("hwnd") or 0)
        child_class = str(child.get("class_name") or "")
        class_lower = child_class.lower()
        kind = _native_text_control_kind(child_hwnd)
        edit_hwnd = child_hwnd
        edit_info: Optional[Dict[str, Any]] = None
        if "comboboxex32" in class_lower or "combobox" in class_lower:
            info = win32_control_info(child_hwnd, timeout_ms=timeout_ms)
            combo_edit_hwnd = int(info.get("edit_hwnd") or 0)
            if combo_edit_hwnd:
                edit_hwnd = combo_edit_hwnd
                kind = _native_text_control_kind(edit_hwnd) or "edit"
                edit_info = _win32_window_info(edit_hwnd, include_text=True)
        if not kind:
            continue
        title = str(child.get("title") or "")
        current_text = str(((edit_info or child).get("text") or {}).get("text") or "")
        control_id = str(child.get("control_id") or "")
        if name is not None and not _selector_any_text_matches([title, current_text], name, match):
            continue
        if automation_id is not None and not _selector_text_matches(control_id, automation_id, match):
            continue
        edit_class = str((edit_info or {}).get("class_name") or "")
        class_values = [child_class, edit_class]
        if class_name is not None and not _selector_any_text_matches(class_values, class_name, match):
            continue
        if wanted_kind:
            normalized_kind = kind.replace("-", "").replace("_", "").replace(" ", "")
            normalized_child_class = child_class.lower().replace("-", "").replace("_", "").replace(" ", "")
            normalized_edit_class = edit_class.lower().replace("-", "").replace("_", "").replace(" ", "")
            if (
                wanted_kind not in (normalized_kind, normalized_child_class, normalized_edit_class)
                and wanted_kind not in normalized_child_class
                and wanted_kind not in normalized_edit_class
            ):
                continue
        ranked_class_name = child_class
        if edit_class and class_name is not None and _selector_text_matches(edit_class, class_name, match):
            ranked_class_name = edit_class
        candidate = {
            "ordinal": len(candidates),
            "hwnd": int(edit_hwnd or child_hwnd),
            "container_hwnd": child_hwnd,
            "kind": kind,
            "class_name": ranked_class_name,
            "container_class_name": child_class if edit_class else None,
            "title": title,
            "current_text": current_text,
            "control_id": child.get("control_id"),
            "rect": (edit_info or child).get("rect"),
            "window": edit_info or child,
            "control": {"kind": kind},
        }
        candidates.append(candidate)
    if wanted_index is not None:
        candidates = [item for item in candidates if int(item.get("ordinal") or 0) == wanted_index]
    return _rank_native_candidates(
        candidates,
        name=name,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        match=match,
    )


def _rect_center(rect: Optional[Dict[str, Any]]) -> Optional[Tuple[int, int]]:
    if not isinstance(rect, dict):
        return None
    if "center_x" in rect and "center_y" in rect:
        return int(rect.get("center_x") or 0), int(rect.get("center_y") or 0)
    left = int(rect.get("left") or 0)
    top = int(rect.get("top") or 0)
    right = int(rect.get("right") or left)
    bottom = int(rect.get("bottom") or top)
    if right <= left or bottom <= top:
        return None
    return (left + right) // 2, (top + bottom) // 2


def _smart_click_uia_patterns(action: str) -> List[str]:
    action_lower = str(action or "invoke").lower().replace("-", "_")
    if action_lower in ("check", "uncheck"):
        return ["Toggle"]
    if action_lower in ("toggle", "check", "uncheck"):
        return ["Toggle", "Invoke", "SelectionItem"]
    if action_lower in ("select", "set_selection", "selection"):
        return ["SelectionItem", "Invoke", "LegacyIAccessible"]
    if action_lower in ("expand", "collapse"):
        return ["ExpandCollapse", "Invoke"]
    return ["Invoke", "SelectionItem", "Toggle", "LegacyIAccessible"]


def _smart_click_uia_action(action: str, element: Dict[str, Any]) -> str:
    action_lower = str(action or "invoke").lower().replace("-", "_")
    patterns = {str(p).lower(): str(p) for p in (element.get("patterns") or [])}
    if action_lower in ("check", "uncheck") and "toggle" in patterns:
        return action_lower
    if action_lower in ("toggle", "check", "uncheck") and "toggle" in patterns:
        return "toggle"
    if action_lower in ("select", "set_selection", "selection") and "selectionitem" in patterns:
        return "select"
    if action_lower in ("select", "set_selection", "selection") and "legacyiaccessible" in patterns:
        return "legacy-select"
    if action_lower in ("expand", "collapse") and "expandcollapse" in patterns:
        return action_lower
    if "invoke" in patterns:
        return "invoke"
    if "selectionitem" in patterns:
        return "select"
    if "toggle" in patterns:
        return "toggle"
    if "legacyiaccessible" in patterns:
        return "legacy-default"
    return action_lower


def _smart_click_uia_action_chain(action: str, element: Dict[str, Any]) -> List[str]:
    action_lower = str(action or "invoke").lower().replace("-", "_")
    patterns = {str(p).lower(): str(p) for p in (element.get("patterns") or [])}
    chain = [_smart_click_uia_action(action, element)]
    if action_lower in ("check", "uncheck"):
        return _dedupe_preserve_order([item for item in chain if item])
    if action_lower in ("toggle",):
        chain.extend(["invoke", "select", "legacy-default"])
    elif action_lower in ("select", "set_selection", "selection"):
        chain.extend(["legacy-select", "invoke"])
    elif action_lower in ("expand", "collapse"):
        chain.extend(["invoke", "legacy-default"])
    else:
        chain.extend(["legacy-default", "select", "toggle"])
    supported: List[str] = []
    for candidate in chain:
        if candidate in ("invoke",) and "invoke" in patterns:
            supported.append(candidate)
        elif candidate in ("select",) and "selectionitem" in patterns:
            supported.append(candidate)
        elif candidate in ("toggle",) and "toggle" in patterns:
            supported.append(candidate)
        elif candidate in ("legacy-default", "legacy-select") and "legacyiaccessible" in patterns:
            supported.append(candidate)
        elif candidate in ("expand", "collapse") and "expandcollapse" in patterns:
            supported.append(candidate)
    return _dedupe_preserve_order(supported)


def _smart_uia_prepare_action_chain(element: Dict[str, Any]) -> List[str]:
    patterns = {str(p).lower(): str(p) for p in (element.get("patterns") or [])}
    chain: List[str] = []
    if "virtualizeditem" in patterns:
        chain.append("realize")
    if "scrollitem" in patterns:
        chain.append("scrollitem")
    return chain


def _smart_uia_prepare_element(
    target: int,
    uia_index: int,
    selected: Dict[str, Any],
    uia_view: str,
    attempts: List[Dict[str, Any]],
    *,
    max_depth: int,
    max_elements: int,
    diagnostic: bool,
) -> Dict[str, Any]:
    prepared = dict(selected)
    for prepare_action in _smart_uia_prepare_action_chain(prepared):
        prepare_result = perform_action(target, uia_index, prepare_action, max_depth=max_depth, max_elements=max_elements, view=uia_view)
        attempts.append({
            "method": f"uia.action.{uia_view}.{prepare_action}",
            "view": uia_view,
            "index": uia_index,
            "target": prepared if diagnostic else _summarize_element(prepared),
            "result": prepare_result if diagnostic else _compact_uia_action_result(prepare_result),
        })
        refreshed = prepare_result.get("element") if isinstance(prepare_result, dict) else None
        if prepare_result.get("ok") and isinstance(refreshed, dict):
            merged = dict(prepared)
            merged.update(refreshed)
            merged.setdefault("patterns", prepared.get("patterns"))
            merged["uia_view"] = uia_view
            prepared = merged
    return prepared


def _smart_click_control_type_filter(control_type: Optional[str], action: str) -> Optional[str]:
    if control_type:
        return control_type
    action_lower = str(action or "invoke").lower().replace("-", "_")
    if action_lower in ("toggle", "check", "uncheck"):
        return None
    if action_lower in ("select", "set_selection", "selection"):
        return None
    return None


def _smart_click_native_action(action: str, candidate: Dict[str, Any]) -> str:
    action_lower = str(action or "invoke").lower().replace("-", "_")
    kind = str(candidate.get("kind") or "").lower()
    if action_lower in ("check", "uncheck", "toggle"):
        if kind in ("checkbox", "3state", "radio", "button", "toolbar", "listview", "treeview"):
            return action_lower
        return "toggle"
    if action_lower in ("select", "set_selection", "selection"):
        return "select"
    if action_lower in ("expand", "collapse"):
        return action_lower
    if kind in ("listbox", "listview", "treeview"):
        return "activate"
    if kind in ("tab", "header", "syslink"):
        return "select"
    if kind == "toolbar":
        return "press"
    return "invoke"


def _native_clickable_kind(kind: str) -> bool:
    return str(kind or "").lower() in {
        "button",
        "checkbox",
        "3state",
        "radio",
        "combobox",
        "comboboxex",
        "static",
        "syslink",
        "listbox",
        "listview",
        "treeview",
        "tab",
        "toolbar",
        "header",
    }


def _native_selectable_kind(kind: str) -> bool:
    return str(kind or "").lower() in {
        "combobox",
        "comboboxex",
        "listbox",
        "listview",
        "treeview",
        "tab",
        "toolbar",
        "header",
        "syslink",
        "checkbox",
        "3state",
        "radio",
        "button",
    }


def _smart_item_sources(info: Dict[str, Any]) -> List[Any]:
    item_sources: List[Any] = []
    for key in ("items", "buttons", "flat", "links", "parts", "columns"):
        value = info.get(key)
        if isinstance(value, list):
            item_sources.extend(value)
    return item_sources


def _native_selector_score(
    candidate: Dict[str, Any],
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    class_name: Optional[str] = None,
    control_type: Optional[str] = None,
    match: str = "contains",
) -> Dict[str, Any]:
    score = 0
    reasons: List[str] = []
    window = candidate.get("window") if isinstance(candidate.get("window"), dict) else {}
    control = candidate.get("control") if isinstance(candidate.get("control"), dict) else {}
    if name is not None:
        values: List[Any] = [candidate.get("title"), window.get("title"), candidate.get("current_text")]
        values.extend(_selector_item_texts(_smart_item_sources(control)))
        name_score, name_reason, name_value = _selector_match_best_text(values, name, match)
        score += name_score
        reasons.append(f"name:{name_reason}")
        if name_value:
            reasons.append(f"name_value:{_shorten(name_value, 80)}")
    if automation_id is not None:
        control_score, control_reason = _selector_text_score(candidate.get("control_id"), automation_id, match)
        score += control_score + (20 if control_score >= 0 else 0)
        reasons.append(f"control_id:{control_reason}")
    if class_name is not None:
        class_score, class_reason = _selector_text_score(candidate.get("class_name"), class_name, match)
        score += class_score + (8 if class_score >= 0 else 0)
        reasons.append(f"class_name:{class_reason}")
    if control_type is not None:
        if _win32_kind_matches(candidate.get("kind"), candidate.get("class_name"), control_type):
            score += 55
            reasons.append("control_type:match")
        else:
            score -= 1000
            reasons.append("control_type:miss")
    if window.get("visible", True):
        score += 8
        reasons.append("visible")
    if window.get("enabled", True):
        score += 8
        reasons.append("enabled")
    if _selector_rect_area(candidate.get("rect")) > 0:
        score += 4
        reasons.append("rect")
    return {"score": score, "reasons": reasons}


def _rank_native_candidates(
    candidates: List[Dict[str, Any]],
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    class_name: Optional[str] = None,
    control_type: Optional[str] = None,
    match: str = "contains",
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for position, candidate in enumerate(candidates):
        item = dict(candidate)
        diagnostic = _native_selector_score(
            item,
            name=name,
            automation_id=automation_id,
            class_name=class_name,
            control_type=control_type,
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
    for item in ranked:
        item.pop("_selector_order", None)
    return ranked


def _win32_select_candidates(
    hwnd: int,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    class_name: Optional[str] = None,
    control_type: Optional[str] = None,
    match: str = "contains",
    include_invisible: bool = False,
    timeout_ms: int = 500,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    wanted_kind = str(control_type or "").strip().lower().replace("-", "").replace("_", "").replace(" ", "")

    def consider(window_info: Dict[str, Any], control_info: Dict[str, Any]) -> None:
        child_hwnd = int(window_info.get("hwnd") or 0)
        if not child_hwnd:
            return
        title = str(window_info.get("title") or "")
        control_id = str(window_info.get("control_id") or "")
        child_class = str(window_info.get("class_name") or "")
        kind = str(control_info.get("kind") or "").lower()
        if not _native_selectable_kind(kind):
            return
        if automation_id is not None and not _selector_text_matches(control_id, automation_id, match):
            return
        if class_name is not None and not _selector_text_matches(child_class, class_name, match):
            return
        if wanted_kind:
            normalized_kind = kind.replace("-", "").replace("_", "").replace(" ", "")
            normalized_class = child_class.lower().replace("-", "").replace("_", "").replace(" ", "")
            if wanted_kind not in (normalized_kind, normalized_class) and wanted_kind not in normalized_class:
                return
        if name is not None:
            values: List[Any] = [title, window_info.get("title"), control_info.get("current_text")]
            values.extend(_selector_item_texts(_smart_item_sources(control_info)))
            if not _selector_any_text_matches(values, name, match):
                return
        candidates.append({
            "ordinal": len(candidates),
            "hwnd": child_hwnd,
            "kind": kind,
            "class_name": child_class,
            "title": title,
            "control_id": window_info.get("control_id"),
            "rect": window_info.get("rect"),
            "window": window_info,
            "control": control_info,
        })

    direct_info = win32_control_info(hwnd, timeout_ms=timeout_ms)
    if "error" not in direct_info:
        consider(direct_info.get("window") or {"hwnd": hwnd}, direct_info)

    children = _child_windows_direct(hwnd, include_invisible=include_invisible, include_text=True, max_count=1000)
    for child in list(children.get("children") or []):
        child_hwnd = int(child.get("hwnd") or 0)
        if not child_hwnd:
            continue
        info = win32_control_info(child_hwnd, timeout_ms=timeout_ms)
        if "error" in info:
            continue
        consider(child, info)
    return _rank_native_candidates(
        candidates,
        name=name,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        match=match,
    )


def _win32_click_candidates(
    hwnd: int,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    class_name: Optional[str] = None,
    control_type: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    include_invisible: bool = False,
    timeout_ms: int = 500,
) -> List[Dict[str, Any]]:
    children = _child_windows_direct(hwnd, include_invisible=include_invisible, include_text=True, max_count=1000)
    items = list(children.get("children") or [])
    candidates: List[Dict[str, Any]] = []
    wanted_index = int(index) if index is not None else None
    wanted_kind = str(control_type or "").strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    for child in items:
        child_hwnd = int(child.get("hwnd") or 0)
        if not child_hwnd:
            continue
        title = str(child.get("title") or "")
        control_id = str(child.get("control_id") or "")
        child_class = str(child.get("class_name") or "")
        if automation_id is not None and not _selector_text_matches(control_id, automation_id, match):
            continue
        if class_name is not None and not _selector_text_matches(child_class, class_name, match):
            continue
        info = win32_control_info(child_hwnd, timeout_ms=timeout_ms)
        if "error" in info:
            continue
        kind = str(info.get("kind") or "").lower()
        if name is not None:
            values: List[Any] = [title, child.get("title"), info.get("current_text")]
            values.extend(_selector_item_texts(_smart_item_sources(info)))
            if not _selector_any_text_matches(values, name, match):
                continue
        if wanted_kind:
            normalized_kind = kind.replace("-", "").replace("_", "").replace(" ", "")
            normalized_class = child_class.lower().replace("-", "").replace("_", "").replace(" ", "")
            if wanted_kind not in (normalized_kind, normalized_class) and wanted_kind not in normalized_class:
                continue
        if not _native_clickable_kind(kind):
            continue
        candidate = {
            "ordinal": len(candidates),
            "hwnd": child_hwnd,
            "kind": kind,
            "class_name": child_class,
            "title": title,
            "control_id": child.get("control_id"),
            "rect": child.get("rect"),
            "window": child,
            "control": info,
        }
        candidates.append(candidate)
    if wanted_index is not None:
        candidates = [item for item in candidates if int(item.get("ordinal") or 0) == wanted_index]
    return _rank_native_candidates(
        candidates,
        name=name,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        match=match,
    )


def _smart_click_coordinate_from_target(target: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    rect = target.get("rect")
    center = _rect_center(rect if isinstance(rect, dict) else None)
    if center:
        return center
    window = target.get("window") if isinstance(target.get("window"), dict) else None
    return _rect_center((window or {}).get("rect") if isinstance(window, dict) else None)


def _uia_smart_views() -> List[str]:
    return ["raw", "control", "content"]


def _compact_uia_find_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep smart-action attempts readable while preserving selector diagnostics."""
    if not isinstance(result, dict):
        return {"error": "invalid_uia_find_result", "result_type": type(result).__name__}
    compact = {
        key: result.get(key)
        for key in ("error", "count", "scanned", "view", "helper", "helper_elevated", "timeout", "worker_killed")
        if key in result
    }
    near_matches = result.get("near_matches")
    if isinstance(near_matches, list) and near_matches:
        compact["near_matches"] = [
            {
                **_summarize_element(item),
                "selector_score": item.get("selector_score"),
                "selector_reasons": item.get("selector_reasons"),
            }
            for item in near_matches[:5]
            if isinstance(item, dict)
        ]
    failure_summary = result.get("failure_summary")
    if isinstance(failure_summary, dict):
        compact["failure_summary"] = {
            key: failure_summary.get(key)
            for key in (
                "scanned", "view", "miss_counts", "observed_control_types",
                "observed_classes", "selector_suggestions", "recommendations",
            )
            if failure_summary.get(key) not in (None, "", [], {})
        }
    return compact


def _compact_uia_action_result(result: Dict[str, Any], keys: Tuple[str, ...] = ()) -> Dict[str, Any]:
    """Compact UIA action output without dropping stale-index relocation diagnostics."""
    if not isinstance(result, dict):
        return {"error": "invalid_uia_action_result", "result_type": type(result).__name__}
    compact_keys = (
        "ok",
        "error",
        "action",
        "helper",
        "helper_elevated",
        "timeout",
        "worker_killed",
        "value",
        "relocated",
        "relocation",
    )
    compact = {
        key: result.get(key)
        for key in _dedupe_preserve_order(list(keys or ()) + list(compact_keys))
        if key in result
    }
    element = result.get("element")
    if isinstance(element, dict):
        relocation = _uia_relocation_from_info(element)
        if relocation and "relocation" not in compact:
            compact["relocated"] = True
            compact["relocation"] = relocation
    return compact


def _uia_find_method_name(method_prefix: str, view: str, pattern: Optional[str]) -> str:
    parts = [method_prefix, view]
    if pattern:
        parts.append(str(pattern))
    return ".".join(parts)


def _uia_smart_find(
    find_fn: Any,
    attempts: List[Dict[str, Any]],
    *,
    patterns: List[Optional[str]],
    payload: Dict[str, Any],
    requested_index: Optional[int] = None,
    diagnostic: bool = False,
    method_prefix: str = "uia.find",
    view_order: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Try a selector across UIA views and return the first view with a usable match."""
    views = [_normalize_uia_view(view) for view in (view_order or _uia_smart_views())]
    last_result: Dict[str, Any] = {}
    for pattern in (patterns or [payload.get("pattern")]):
        for view in views:
            query = dict(payload)
            if pattern is not None:
                query["pattern"] = pattern
            query["view"] = view
            result = find_fn(query)
            if not isinstance(result, dict):
                result = {"error": "invalid_uia_find_result", "result_type": type(result).__name__}
            result_view = result.get("view") or view
            try:
                result_view = _normalize_uia_view(result_view)
            except Exception:
                result_view = view
            attempts.append({
                "method": _uia_find_method_name(method_prefix, result_view, pattern),
                "view": result_view,
                "result": result if diagnostic else _compact_uia_find_result(result),
            })
            last_result = result
            if _is_terminal_uia_helper_error(result):
                return {"matches": [], "selected": None, "view": result_view, "pattern": pattern, "result": result}
            matches = list(result.get("matches") or [])
            if requested_index is not None and matches and requested_index >= len(matches):
                attempts.append({
                    "method": f"{method_prefix}.index_out_of_range",
                    "view": result_view,
                    "pattern": pattern,
                    "requested_index": requested_index,
                    "count": len(matches),
                })
                continue
            if matches:
                selected = dict(matches[requested_index] if requested_index is not None else matches[0])
                selected["uia_view"] = result_view
                return {
                    "matches": matches,
                    "selected": selected,
                    "view": result_view,
                    "pattern": pattern,
                    "result": result,
                }
    return {"matches": [], "selected": None, "view": None, "pattern": None, "result": last_result}


def smart_click(
    hwnd: Optional[int],
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    action: str = "invoke",
    button: str = "left",
    clicks: int = 1,
    timeout_ms: int = 500,
    diagnostic: bool = False,
    allow_coordinate_fallback: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Click/trigger a control by stable selectors: UIA pattern, Win32 native action, optional coordinates."""
    target = _resolve_target(hwnd)
    if not user32.IsWindow(target) and int(target) != _DESKTOP_UIA_KEY:
        return {"ok": False, "error": f"Window {target} no longer exists", "hwnd": target}
    attempts: List[Dict[str, Any]] = []
    action_lower = str(action or "invoke").lower().replace("_", "-")
    requested_index = int(index) if index is not None else None
    if requested_index is not None and requested_index < 0:
        return {"ok": False, "error": "index must be >= 0", "hwnd": target, "index": requested_index}
    helper_result = _smart_action_helper_post(
        target,
        "/smart_click",
        {
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "action": action,
            "button": button,
            "clicks": clicks,
            "timeout_ms": timeout_ms,
            "diagnostic": diagnostic,
            "allow_coordinate_fallback": allow_coordinate_fallback,
            "skip_uia": skip_uia,
            "repair": repair,
            "repair_timeout": repair_timeout,
        },
    )
    if helper_result is not None:
        return helper_result
    limit = max(requested_index + 1, 1) if requested_index is not None else 8
    patterns = _smart_click_uia_patterns(action)
    uia_selected: Optional[Dict[str, Any]] = None
    uia_view = "raw"

    if skip_uia:
        attempts.append({"method": "uia.skipped", "reason": "skip_uia requested"})
    else:
        def _find(query: Dict[str, Any]) -> Dict[str, Any]:
            return find_elements(target, **query)

        lookup = _uia_smart_find(
            _find,
            attempts,
            patterns=patterns,
            payload={
                "name": name,
                "automation_id": automation_id,
                "control_type": _smart_click_control_type_filter(control_type, action),
                "class_name": class_name,
                "match": match,
                "enabled_only": True,
                "visible_only": True,
                "limit": limit,
                "max_depth": 10,
                "max_elements": 700,
            },
            requested_index=requested_index,
            diagnostic=diagnostic,
        )
        uia_selected = lookup.get("selected") if isinstance(lookup.get("selected"), dict) else None
        uia_view = str(lookup.get("view") or "raw")

    if uia_selected:
        selected = uia_selected
        uia_index = int(selected.get("index"))
        selected = _smart_uia_prepare_element(target, uia_index, selected, uia_view, attempts, max_depth=10, max_elements=700, diagnostic=diagnostic)
        for uia_action in _smart_click_uia_action_chain(action, selected):
            uia_result = perform_action(target, uia_index, uia_action, max_depth=10, max_elements=700, view=uia_view)
            attempts.append({"method": f"uia.action.{uia_view}.{uia_action}", "view": uia_view, "index": uia_index, "target": selected if diagnostic else _summarize_element(selected), "result": uia_result if diagnostic else _compact_uia_action_result(uia_result)})
            if uia_result.get("ok"):
                return _with_uia_relocation({
                    "ok": True,
                    "hwnd": target,
                    "method": f"uia.action.{uia_view}.{uia_action}",
                    "view": uia_view,
                    "action": uia_action,
                    "target": selected,
                    "attempts": attempts,
                }, uia_result, selected)
        if allow_coordinate_fallback:
            center = _smart_click_coordinate_from_target(selected)
            if center:
                x, y = center
                coord_result = _click_absolute_screen(x, y, button=button, clicks=clicks)
                attempts.append({"method": "uia.coordinate_fallback", "target": selected if diagnostic else _summarize_element(selected), "result": coord_result})
                return {
                    "ok": True,
                    "hwnd": target,
                    "method": "uia.coordinate_fallback",
                    "button": button,
                    "clicks": clicks,
                    "target": selected,
                    "attempts": attempts,
                }

    candidates = _win32_click_candidates(
        target,
        name=name,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        index=requested_index,
        match=match,
        include_invisible=False,
        timeout_ms=timeout_ms,
    )
    attempts.append({"method": "win32.find_click_child", "count": len(candidates), "candidates": candidates if diagnostic else [_compact_window_info(c.get("window")) for c in candidates[:8]]})
    for candidate in candidates:
        child_hwnd = int(candidate.get("hwnd") or 0)
        native_action = _smart_click_native_action(action, candidate)
        text_arg = name if candidate.get("kind") in ("listbox", "listview", "treeview", "tab", "toolbar", "header", "syslink") else None
        result = win32_control_action(
            child_hwnd,
            native_action,
            index=None,
            text=text_arg,
            checked=True if str(action or "").lower().replace("-", "_") == "check" else False if str(action or "").lower().replace("-", "_") == "uncheck" else None,
            match=match,
            timeout_ms=timeout_ms,
        )
        attempts.append({"method": f"win32.control_action.{native_action}", "target": candidate if diagnostic else _compact_window_info(candidate.get("window")), "result": result if diagnostic else {k: result.get(k) for k in ("ok", "error", "kind", "action", "helper", "helper_elevated", "result", "notified_parent")}})
        if _helper_ok(result):
            return {
                "ok": True,
                "hwnd": target,
                "method": f"win32.control_action.{native_action}",
                "action": native_action,
                "target": candidate,
                "attempts": attempts,
            }
        if candidate.get("kind") in ("button", "checkbox", "3state", "radio"):
            click_result = win32_click(child_hwnd, timeout_ms=timeout_ms)
            attempts.append({"method": "win32.click", "target": candidate if diagnostic else _compact_window_info(candidate.get("window")), "result": click_result if diagnostic else {k: click_result.get(k) for k in ("ok", "error", "method", "result", "helper", "helper_elevated")}})
            if click_result.get("ok"):
                return {
                    "ok": True,
                    "hwnd": target,
                    "method": "win32.click",
                    "action": "click",
                    "target": candidate,
                    "attempts": attempts,
                }
        if allow_coordinate_fallback:
            center = _smart_click_coordinate_from_target(candidate)
            if center:
                x, y = center
                coord_result = _click_absolute_screen(x, y, button=button, clicks=clicks)
                attempts.append({"method": "win32.coordinate_fallback", "target": candidate if diagnostic else _compact_window_info(candidate.get("window")), "result": coord_result})
                return {
                    "ok": True,
                    "hwnd": target,
                    "method": "win32.coordinate_fallback",
                    "button": button,
                    "clicks": clicks,
                    "target": candidate,
                    "attempts": attempts,
                }

    failure = {
        "ok": False,
        "hwnd": target,
        "error": "No semantic UIA or native Win32 click path succeeded",
        "selector": {
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "action": action_lower,
        },
        "coordinate_fallback_allowed": bool(allow_coordinate_fallback),
        "attempts": attempts,
        "failure_summary": _compact_attempt_failure_summary(attempts),
    }
    repaired = _smart_wait_click_maybe_repair(
        failure,
        target,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        match=match,
        action=action,
        timeout=0.0,
        interval=0.05,
        button=button,
        clicks=clicks,
        timeout_ms=timeout_ms,
        diagnostic=diagnostic,
        allow_coordinate_fallback=allow_coordinate_fallback,
        skip_uia=skip_uia,
        repair=repair,
        repair_timeout=repair_timeout,
    )
    if repaired is not failure and isinstance(repaired, dict) and repaired.get("smart_wait_repair"):
        repaired = dict(repaired)
        repaired["smart_action_repair"] = True
    return repaired


def _smart_poll_failure_summary(result: Dict[str, Any], attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    if attempts:
        return _compact_attempt_failure_summary(attempts)
    if isinstance(result, dict) and isinstance(result.get("failure_summary"), dict):
        return dict(result.get("failure_summary") or {})
    return {}


def _smart_poll_compact_selector_suggestions(suggestions: Any, limit: int = 3) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    for item in suggestions or []:
        if not isinstance(item, dict):
            continue
        compact = {
            key: item.get(key)
            for key in ("index", "automation_id", "control_type", "class_name", "name", "value", "pattern", "match")
            if item.get(key) not in (None, "", [], {})
        }
        if compact and compact not in compacted:
            compacted.append(compact)
        if len(compacted) >= limit:
            break
    return compacted


def _smart_poll_summary_base(result: Dict[str, Any]) -> Dict[str, Any]:
    attempts = result.get("attempts") if isinstance(result, dict) else []
    if not isinstance(attempts, list):
        attempts = []
    summary: Dict[str, Any] = {
        "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
        "method": result.get("method") if isinstance(result, dict) else None,
        "error": result.get("error") if isinstance(result, dict) else None,
        "attempt_methods": [item.get("method") for item in attempts if isinstance(item, dict)],
    }
    if isinstance(result, dict):
        relocation = result.get("relocation")
        if isinstance(relocation, dict):
            summary["relocated"] = True
            summary["relocation"] = relocation
        elif result.get("relocated") is True:
            summary["relocated"] = True
    failure_summary = _smart_poll_failure_summary(result, attempts if isinstance(attempts, list) else [])
    if failure_summary.get("uia_relocation_count"):
        summary["uia_relocation_count"] = failure_summary.get("uia_relocation_count")
        summary["last_uia_relocation"] = failure_summary.get("last_uia_relocation")
    selector_suggestions = _smart_poll_compact_selector_suggestions(failure_summary.get("selector_suggestions"))
    compact_failure = {
        key: failure_summary.get(key)
        for key in (
            "last_failure_category",
            "last_error",
            "last_uia_error",
            "last_win32_error",
            "last_focus_error",
            "terminal_uia_error",
            "miss_counts",
            "observed_control_types",
            "observed_classes",
            "uia_selector_repair_available",
            "uia_selector_suggestion_count",
            "recommendations",
        )
        if failure_summary.get(key) not in (None, "", [], {})
    }
    if selector_suggestions:
        compact_failure["selector_suggestions"] = selector_suggestions
        summary["uia_selector_repair_available"] = True
        summary["uia_selector_suggestions"] = selector_suggestions
        repair_candidates = [
            {
                "kind": "uia_selector_repair",
                "layer": "semantic",
                "command": "uia_selector_repair_find",
                "source": "smart_poll.failure_summary",
                "suggestion": suggestion,
                "reason": "retry UIA lookup with failure_summary.selector_suggestions[0]",
            }
            for suggestion in selector_suggestions[:3]
        ]
        summary["next_repair_candidates"] = repair_candidates
        repair_steps = _batch_repair_candidate_steps(repair_candidates, limit=3)
        if repair_steps:
            summary["next_repair_steps"] = repair_steps
    if compact_failure:
        summary["failure_summary"] = compact_failure
    return summary


def _smart_click_poll_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    return _smart_poll_summary_base(result)


def _smart_wait_selector_repair_timeout(repair_timeout: Optional[float], timeout: float) -> float:
    if repair_timeout is not None:
        try:
            return max(float(repair_timeout), 0.0)
        except Exception:
            return 0.0
    try:
        return min(max(float(timeout), 0.0), 1.0)
    except Exception:
        return 1.0


def _smart_wait_selector_repair_suggestion(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(result, dict):
        return None
    failure_summary = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
    suggestions = failure_summary.get("selector_suggestions") if isinstance(failure_summary.get("selector_suggestions"), list) else []
    for item in suggestions:
        if isinstance(item, dict) and item:
            return item
    last_result = result.get("last_result") if isinstance(result.get("last_result"), dict) else {}
    last_failure = last_result.get("failure_summary") if isinstance(last_result.get("failure_summary"), dict) else {}
    suggestions = last_failure.get("selector_suggestions") if isinstance(last_failure.get("selector_suggestions"), list) else []
    for item in suggestions:
        if isinstance(item, dict) and item:
            return item
    return None


def _smart_wait_repair_selector_from_suggestion(suggestion: Dict[str, Any], original: Dict[str, Any]) -> Dict[str, Any]:
    selector: Dict[str, Any] = {}
    for key in ("name", "automation_id", "control_type", "class_name"):
        value = suggestion.get(key)
        if value not in (None, "", [], {}):
            selector[key] = value
    selector["match"] = suggestion.get("match") or original.get("match") or "contains"
    return selector


def _smart_wait_click_maybe_repair(
    result: Dict[str, Any],
    hwnd: int,
    *,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    match: str = "contains",
    action: str = "invoke",
    timeout: float = 10.0,
    interval: float = 0.25,
    button: str = "left",
    clicks: int = 1,
    timeout_ms: int = 500,
    diagnostic: bool = False,
    allow_coordinate_fallback: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if result.get("ok") or not _win32_repair_requested(repair, repair_timeout) or _coerce_bool(skip_uia, False):
        return result
    suggestion = _smart_wait_selector_repair_suggestion(result)
    if not suggestion:
        return result
    original = {
        "name": name,
        "automation_id": automation_id,
        "control_type": control_type,
        "class_name": class_name,
        "match": match,
    }
    selector = _smart_wait_repair_selector_from_suggestion(suggestion, original)
    if not any(selector.get(key) not in (None, "", [], {}) for key in ("name", "automation_id", "control_type", "class_name")):
        return result
    repair_timeout_value = _smart_wait_selector_repair_timeout(repair_timeout, timeout)
    deadline = time.time() + repair_timeout_value
    repair_attempts = 0
    repair_result: Dict[str, Any] = {}
    while True:
        repair_attempts += 1
        repair_result = smart_click(
            hwnd,
            name=selector.get("name"),
            automation_id=selector.get("automation_id"),
            control_type=selector.get("control_type"),
            class_name=selector.get("class_name"),
            index=None,
            match=selector.get("match", "contains"),
            action=action,
            button=button,
            clicks=clicks,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            allow_coordinate_fallback=allow_coordinate_fallback,
            skip_uia=False,
        )
        if repair_result.get("ok"):
            break
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))
    repair_info = {
        "attempted": True,
        "ok": bool(repair_result.get("ok")),
        "timeout": repair_timeout_value,
        "attempts": repair_attempts,
        "selector": selector,
        "reason": "retry smart-wait click with failure_summary.selector_suggestions[0]",
    }
    if repair_result.get("ok"):
        repaired = dict(repair_result)
        repaired.update({
            "repaired": True,
            "selector_repair": True,
            "uia_selector_repair": True,
            "smart_wait_repair": True,
            "repair": repair_info,
            "strict_wait_attempts": result.get("wait_attempts"),
            "repair_attempts": repair_attempts,
            "timeout": float(timeout),
            "interval": max(float(interval), 0.05),
            "suggestion": _smart_poll_compact_selector_suggestions([suggestion], limit=1)[0],
            "original_failure_summary": result.get("failure_summary"),
        })
        return repaired
    updated = dict(result)
    updated["repair"] = {
        **repair_info,
        "result": _smart_click_poll_summary(repair_result),
    }
    return updated


def smart_wait_click(
    hwnd: Optional[int],
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    action: str = "invoke",
    timeout: float = 10.0,
    interval: float = 0.25,
    button: str = "left",
    clicks: int = 1,
    timeout_ms: int = 500,
    diagnostic: bool = False,
    allow_coordinate_fallback: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Poll smart_click until a semantic/native action succeeds or the timeout expires."""
    target = _resolve_target(hwnd)
    if not user32.IsWindow(target) and int(target) != _DESKTOP_UIA_KEY:
        return {"ok": False, "error": f"Window {target} no longer exists", "hwnd": target}
    if index is not None and int(index) < 0:
        return {"ok": False, "error": "index must be >= 0", "hwnd": target, "index": int(index)}
    helper_result = _smart_action_helper_post(
        target,
        "/smart_wait_click",
        {
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "action": action,
            "timeout": timeout,
            "interval": interval,
            "button": button,
            "clicks": clicks,
            "timeout_ms": timeout_ms,
            "diagnostic": diagnostic,
            "allow_coordinate_fallback": allow_coordinate_fallback,
            "skip_uia": skip_uia,
            "repair": repair,
            "repair_timeout": repair_timeout,
        },
        timeout=float(timeout or 0.0) + (_smart_wait_selector_repair_timeout(repair_timeout, timeout) if _win32_repair_requested(repair, repair_timeout) else 0.0),
    )
    if helper_result is not None:
        return helper_result
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    interval_value = max(float(interval), 0.05)
    poll_summaries: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {}
    attempts = 0

    while True:
        attempts += 1
        result = smart_click(
            hwnd,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            index=index,
            match=match,
            action=action,
            button=button,
            clicks=clicks,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            allow_coordinate_fallback=allow_coordinate_fallback,
            skip_uia=skip_uia,
        )
        last_result = result
        poll_summaries.append(_smart_click_poll_summary(result))
        if result.get("ok"):
            result = dict(result)
            result.update({
                "waited": round(time.time() - start, 3),
                "wait_attempts": attempts,
                "timeout": float(timeout),
                "interval": interval_value,
            })
            if diagnostic:
                result["wait_polls"] = poll_summaries
            return result

        now = time.time()
        if now >= deadline:
            break
        time.sleep(min(interval_value, max(deadline - now, 0.0)))

    timeout_result = {
        "ok": False,
        "hwnd": last_result.get("hwnd") if isinstance(last_result, dict) else _resolve_target(hwnd),
        "error": "smart_wait_click_timeout",
        "timeout": float(timeout),
        "interval": interval_value,
        "waited": round(time.time() - start, 3),
        "wait_attempts": attempts,
        "selector": {
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "action": str(action or "invoke").lower().replace("_", "-"),
        },
        "last_result": last_result if diagnostic else _smart_click_poll_summary(last_result),
        "failure_summary": _compact_attempt_failure_summary(last_result.get("attempts") or []) if isinstance(last_result, dict) else {},
        "wait_polls": poll_summaries,
    }
    return _smart_wait_click_maybe_repair(
        timeout_result,
        target,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        match=match,
        action=action,
        timeout=timeout,
        interval=interval_value,
        button=button,
        clicks=clicks,
        timeout_ms=timeout_ms,
        diagnostic=diagnostic,
        allow_coordinate_fallback=allow_coordinate_fallback,
        skip_uia=skip_uia,
        repair=repair,
        repair_timeout=repair_timeout,
    )


def _smart_select_mode_key(mode: str) -> str:
    mode_lower = str(mode or "select").lower().replace("-", "_")
    if mode_lower in ("add", "add_to_selection", "addtoselection", "add_selection"):
        return "add"
    if mode_lower in ("remove", "remove_from_selection", "removefromselection", "deselect", "unselect"):
        return "remove"
    if mode_lower in ("check", "checked", "set_check", "set_checked", "on"):
        return "check"
    if mode_lower in ("uncheck", "unchecked", "clear_check", "clear_checked", "off"):
        return "uncheck"
    if mode_lower in ("toggle", "toggle_check", "toggle_checked"):
        return "toggle"
    return "select"


def _smart_select_check_mode(mode: str) -> bool:
    return _smart_select_mode_key(mode) in ("check", "uncheck", "toggle")


def _smart_select_uia_patterns(mode: str) -> List[str]:
    if _smart_select_check_mode(mode):
        return ["Toggle"]
    return ["SelectionItem"]


def _smart_select_legacy_patterns(mode: str) -> List[str]:
    if _smart_select_check_mode(mode):
        return []
    return ["LegacyIAccessible"]


def _smart_select_uia_actions(mode: str) -> List[str]:
    mode_key = _smart_select_mode_key(mode)
    if mode_key == "add":
        return ["add-to-selection", "select"]
    if mode_key == "remove":
        return ["remove-from-selection"]
    if mode_key in ("check", "uncheck", "toggle"):
        return [mode_key]
    return ["select"]


def _smart_select_legacy_flags(mode: str) -> int:
    mode_key = _smart_select_mode_key(mode)
    if mode_key == "add":
        return MSAA_SELECT_ADDSELECTION
    if mode_key == "remove":
        return MSAA_SELECT_REMOVESELECTION
    return MSAA_SELECT_TAKESELECTION


def _smart_select_uia_action_chain(mode: str, element: Dict[str, Any]) -> List[str]:
    patterns = {str(p).lower(): str(p) for p in (element.get("patterns") or [])}
    chain: List[str] = []
    if "selectionitem" in patterns:
        chain.extend(_smart_select_uia_actions(mode))
    if "toggle" in patterns and _smart_select_check_mode(mode):
        chain.extend(_smart_select_uia_actions(mode))
    if "legacyiaccessible" in patterns and not _smart_select_check_mode(mode):
        chain.append("legacy-select")
    supported: List[str] = []
    for candidate in chain:
        if candidate in ("select", "add-to-selection", "remove-from-selection") and "selectionitem" in patterns:
            supported.append(candidate)
        elif candidate in ("check", "uncheck", "toggle") and "toggle" in patterns:
            supported.append(candidate)
        elif candidate == "legacy-select" and "legacyiaccessible" in patterns:
            supported.append(candidate)
    return _dedupe_preserve_order(supported)


def _smart_text_uia_action_chain(element: Dict[str, Any]) -> List[str]:
    patterns = {str(p).lower(): str(p) for p in (element.get("patterns") or [])}
    chain: List[str] = []
    if "value" in patterns:
        chain.append("set-value")
    if "legacyiaccessible" in patterns:
        chain.append("legacy-set-value")
    return chain


def _smart_select_native_action(mode: str, candidate: Dict[str, Any]) -> str:
    mode_key = _smart_select_mode_key(mode)
    kind = str(candidate.get("kind") or "").lower()
    if mode_key == "add":
        return "multi_select" if kind == "listbox" else "select"
    if mode_key == "remove":
        return "multi_select" if kind == "listbox" else "select"
    if mode_key in ("check", "uncheck", "toggle"):
        return mode_key
    if kind == "toolbar":
        return "press"
    if kind in ("checkbox", "3state", "radio", "button"):
        return "check"
    return "select"


def _smart_select_native_checked_arg(mode: str, native_action: str) -> Optional[bool]:
    mode_key = _smart_select_mode_key(mode)
    native_key = str(native_action or "").lower().replace("-", "_")
    if native_key == "multi_select":
        return mode_key != "remove"
    if native_key == "toggle":
        return None
    if native_key == "uncheck":
        return False
    if native_key == "check":
        return mode_key != "uncheck"
    if native_key == "set_check":
        if mode_key == "toggle":
            return None
        return mode_key != "uncheck"
    return None


def _smart_select_item_container_properties(item_text: Optional[str], automation_id: Optional[str], control_type: Optional[str], class_name: Optional[str]) -> List[Tuple[str, Any]]:
    properties: List[Tuple[str, Any]] = []
    if item_text is not None:
        properties.extend([("name", item_text), ("value", item_text)])
    if automation_id is not None:
        properties.append(("automation_id", automation_id))
    if control_type is not None:
        properties.append(("control_type", control_type))
    if class_name is not None:
        properties.append(("class_name", class_name))
    deduped: List[Tuple[str, Any]] = []
    seen = set()
    for key, value in properties:
        marker = (key, _selector_norm(value))
        if marker not in seen:
            seen.add(marker)
            deduped.append((key, value))
    return deduped


def _smart_select_virtualized_find(
    find_fn: Any,
    item_find_fn: Any,
    attempts: List[Dict[str, Any]],
    *,
    item_text: Optional[str],
    automation_id: Optional[str],
    control_type: Optional[str],
    class_name: Optional[str],
    match: str,
    requested_index: Optional[int],
    diagnostic: bool,
    max_depth: int = 10,
    max_elements: int = 900,
) -> Dict[str, Any]:
    if requested_index is not None and item_text is None and automation_id is None:
        return {"selected": None, "view": None, "container": None}
    properties = _smart_select_item_container_properties(item_text, automation_id, control_type, class_name)
    if not properties:
        return {"selected": None, "view": None, "container": None}
    limit = max((requested_index or 0) + 1, 1)
    for view in _uia_smart_views():
        container_result = find_fn({
            "pattern": "ItemContainer",
            "match": match,
            "enabled_only": False,
            "visible_only": True,
            "limit": 24,
            "max_depth": max_depth,
            "max_elements": max_elements,
            "view": view,
        })
        if not isinstance(container_result, dict):
            container_result = {"error": "invalid_uia_find_result", "result_type": type(container_result).__name__}
        result_view = container_result.get("view") or view
        try:
            result_view = _normalize_uia_view(result_view)
        except Exception:
            result_view = view
        attempts.append({
            "method": f"uia.find.{result_view}.ItemContainer",
            "view": result_view,
            "result": container_result if diagnostic else _compact_uia_find_result(container_result),
        })
        if _is_terminal_uia_helper_error(container_result):
            return {"selected": None, "view": result_view, "container": None, "terminal_error": container_result}
        for container in list(container_result.get("matches") or []):
            container_index = container.get("index")
            if container_index is None:
                continue
            for property_name, property_value in properties:
                found = item_find_fn(int(container_index), property_name, property_value, limit, result_view)
                if not isinstance(found, dict):
                    found = {"error": "invalid_item_container_result", "result_type": type(found).__name__}
                attempts.append({
                    "method": f"uia.item_container.{result_view}.{property_name}",
                    "view": result_view,
                    "container_index": int(container_index),
                    "result": found if diagnostic else {
                        key: found.get(key)
                        for key in ("ok", "error", "count", "helper", "helper_elevated", "timeout", "worker_killed")
                        if key in found
                    },
                })
                if _is_terminal_uia_helper_error(found):
                    return {"selected": None, "view": result_view, "container": container, "terminal_error": found}
                matches = list(found.get("matches") or [])
                if requested_index is not None and matches and requested_index >= len(matches):
                    attempts.append({
                        "method": "uia.item_container.index_out_of_range",
                        "view": result_view,
                        "container_index": int(container_index),
                        "property": property_name,
                        "requested_index": requested_index,
                        "count": len(matches),
                    })
                    continue
                if matches:
                    selected = dict(matches[requested_index] if requested_index is not None else matches[0])
                    selected["uia_view"] = result_view
                    selected["container_index"] = int(container_index)
                    selected["item_container_property"] = property_name
                    return {"selected": selected, "view": result_view, "container": container, "result": found}
    return {"selected": None, "view": None, "container": None}


def smart_select(
    hwnd: Optional[int],
    item: Optional[str] = None,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    mode: str = "select",
    timeout_ms: int = 500,
    diagnostic: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Select an item/control by stable selectors using UIA SelectionItem then native Win32 actions."""
    target = _resolve_target(hwnd)
    if not user32.IsWindow(target) and int(target) != _DESKTOP_UIA_KEY:
        return {"ok": False, "error": f"Window {target} no longer exists", "hwnd": target}
    item_text = item if item is not None else name
    requested_index = int(index) if index is not None else None
    if requested_index is not None and requested_index < 0:
        return {"ok": False, "error": "index must be >= 0", "hwnd": target, "index": requested_index}
    helper_result = _smart_action_helper_post(
        target,
        "/smart_select",
        {
            "item": item,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "mode": mode,
            "timeout_ms": timeout_ms,
            "diagnostic": diagnostic,
            "skip_uia": skip_uia,
            "repair": repair,
            "repair_timeout": repair_timeout,
        },
    )
    if helper_result is not None:
        return helper_result
    limit = max(requested_index + 1, 1) if requested_index is not None else 12
    attempts: List[Dict[str, Any]] = []
    uia_selected: Optional[Dict[str, Any]] = None
    uia_view = "raw"

    if skip_uia:
        attempts.append({"method": "uia.skipped", "reason": "skip_uia requested"})
    else:
        def _find(query: Dict[str, Any]) -> Dict[str, Any]:
            return find_elements(target, **query)

        lookup = _uia_smart_find(
            _find,
            attempts,
            patterns=_smart_select_uia_patterns(mode),
            payload={
                "name": item_text,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "match": match,
                "enabled_only": True,
                "visible_only": True,
                "limit": limit,
                "max_depth": 10,
                "max_elements": 900,
            },
            requested_index=requested_index,
            diagnostic=diagnostic,
        )
        uia_selected = lookup.get("selected") if isinstance(lookup.get("selected"), dict) else None
        uia_view = str(lookup.get("view") or "raw")
        legacy_patterns = _smart_select_legacy_patterns(mode)
        if not uia_selected and legacy_patterns:
            legacy_lookup = _uia_smart_find(
                _find,
                attempts,
                patterns=legacy_patterns,
                payload={
                    "name": item_text,
                    "automation_id": automation_id,
                    "control_type": control_type,
                    "class_name": class_name,
                    "match": match,
                    "enabled_only": True,
                    "visible_only": True,
                    "limit": limit,
                    "max_depth": 10,
                    "max_elements": 900,
                },
                requested_index=requested_index,
                diagnostic=diagnostic,
                method_prefix="uia.find.legacy_select",
            )
            uia_selected = legacy_lookup.get("selected") if isinstance(legacy_lookup.get("selected"), dict) else None
            uia_view = str(legacy_lookup.get("view") or uia_view or "raw")
        if not uia_selected:
            def _item_find(container_index: int, property_name: str, property_value: Any, limit_value: int, view_name: str) -> Dict[str, Any]:
                return item_container_find(
                    target,
                    container_index,
                    property_name,
                    property_value,
                    limit=limit_value,
                    max_depth=10,
                    max_elements=900,
                    view=view_name,
                )

            virtualized_lookup = _smart_select_virtualized_find(
                _find,
                _item_find,
                attempts,
                item_text=item_text,
                automation_id=automation_id,
                control_type=control_type,
                class_name=class_name,
                match=match,
                requested_index=requested_index,
                diagnostic=diagnostic,
            )
            uia_selected = virtualized_lookup.get("selected") if isinstance(virtualized_lookup.get("selected"), dict) else None
            uia_view = str(virtualized_lookup.get("view") or uia_view or "raw")

    if uia_selected:
        selected = uia_selected
        uia_index = int(selected.get("index"))
        selected = _smart_uia_prepare_element(target, uia_index, selected, uia_view, attempts, max_depth=10, max_elements=900, diagnostic=diagnostic)
        for uia_action in _smart_select_uia_action_chain(mode, selected):
            action_value = _smart_select_legacy_flags(mode) if uia_action == "legacy-select" else None
            result = perform_action(target, uia_index, uia_action, value=action_value, max_depth=10, max_elements=900, view=uia_view)
            attempts.append({"method": f"uia.action.{uia_view}.{uia_action}", "view": uia_view, "index": uia_index, "target": selected if diagnostic else _summarize_element(selected), "result": result if diagnostic else _compact_uia_action_result(result)})
            if result.get("ok"):
                return _with_uia_relocation({
                    "ok": True,
                    "hwnd": target,
                    "method": f"uia.action.{uia_view}.{uia_action}",
                    "view": uia_view,
                    "action": uia_action,
                    "item": item_text,
                    "target": selected,
                    "attempts": attempts,
                }, result, selected)

    candidates = _win32_select_candidates(
        target,
        name=item_text,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        match=match,
        include_invisible=False,
        timeout_ms=timeout_ms,
    )
    attempts.append({"method": "win32.find_select_child", "count": len(candidates), "candidates": candidates if diagnostic else [_compact_window_info(c.get("window")) for c in candidates[:8]]})
    for candidate in candidates:
        child_hwnd = int(candidate.get("hwnd") or 0)
        native_action = _smart_select_native_action(mode, candidate)
        checked_arg = _smart_select_native_checked_arg(mode, native_action)
        result = win32_control_action(
            child_hwnd,
            native_action,
            text=item_text,
            index=None if item_text is not None else requested_index,
            checked=checked_arg,
            match=match,
            timeout_ms=timeout_ms,
        )
        attempts.append({"method": f"win32.control_action.{native_action}", "target": candidate if diagnostic else _compact_window_info(candidate.get("window")), "result": result if diagnostic else {k: result.get(k) for k in ("ok", "error", "kind", "action", "result", "notified_parent", "index")}})
        if result.get("ok"):
            return {
                "ok": True,
                "hwnd": target,
                "method": f"win32.control_action.{native_action}",
                "action": native_action,
                "item": item_text,
                "target": candidate,
                "attempts": attempts,
            }

    failure = {
        "ok": False,
        "hwnd": target,
        "error": "No UIA SelectionItem/Toggle or native Win32 selection/check path succeeded",
        "selector": {
            "item": item,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "mode": mode,
        },
        "attempts": attempts,
        "failure_summary": _compact_attempt_failure_summary(attempts),
    }
    repaired = _smart_wait_select_maybe_repair(
        failure,
        target,
        item=item,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        match=match,
        mode=mode,
        timeout=0.0,
        interval=0.05,
        timeout_ms=timeout_ms,
        diagnostic=diagnostic,
        skip_uia=skip_uia,
        repair=repair,
        repair_timeout=repair_timeout,
    )
    if repaired is not failure and isinstance(repaired, dict) and repaired.get("smart_wait_repair"):
        repaired = dict(repaired)
        repaired["smart_action_repair"] = True
    return repaired


def _smart_select_poll_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    return _smart_poll_summary_base(result)


def _smart_wait_select_maybe_repair(
    result: Dict[str, Any],
    hwnd: int,
    *,
    item: Optional[str] = None,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    match: str = "contains",
    mode: str = "select",
    timeout: float = 10.0,
    interval: float = 0.25,
    timeout_ms: int = 500,
    diagnostic: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if result.get("ok") or not _win32_repair_requested(repair, repair_timeout) or _coerce_bool(skip_uia, False):
        return result
    suggestion = _smart_wait_selector_repair_suggestion(result)
    if not suggestion:
        return result
    original = {
        "name": item if item is not None else name,
        "automation_id": automation_id,
        "control_type": control_type,
        "class_name": class_name,
        "match": match,
    }
    selector = _smart_wait_repair_selector_from_suggestion(suggestion, original)
    if not any(selector.get(key) not in (None, "", [], {}) for key in ("name", "automation_id", "control_type", "class_name")):
        return result
    repair_timeout_value = _smart_wait_selector_repair_timeout(repair_timeout, timeout)
    deadline = time.time() + repair_timeout_value
    repair_attempts = 0
    repair_result: Dict[str, Any] = {}
    while True:
        repair_attempts += 1
        repair_result = smart_select(
            hwnd,
            item=selector.get("name"),
            name=None,
            automation_id=selector.get("automation_id"),
            control_type=selector.get("control_type"),
            class_name=selector.get("class_name"),
            index=None,
            match=selector.get("match", "contains"),
            mode=mode,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            skip_uia=False,
        )
        if repair_result.get("ok"):
            break
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))
    repair_info = {
        "attempted": True,
        "ok": bool(repair_result.get("ok")),
        "timeout": repair_timeout_value,
        "attempts": repair_attempts,
        "selector": selector,
        "reason": "retry smart-wait select with failure_summary.selector_suggestions[0]",
    }
    if repair_result.get("ok"):
        repaired = dict(repair_result)
        repaired.update({
            "repaired": True,
            "selector_repair": True,
            "uia_selector_repair": True,
            "smart_wait_repair": True,
            "repair": repair_info,
            "strict_wait_attempts": result.get("wait_attempts"),
            "repair_attempts": repair_attempts,
            "timeout": float(timeout),
            "interval": max(float(interval), 0.05),
            "suggestion": _smart_poll_compact_selector_suggestions([suggestion], limit=1)[0],
            "original_failure_summary": result.get("failure_summary"),
        })
        return repaired
    updated = dict(result)
    updated["repair"] = {
        **repair_info,
        "result": _smart_select_poll_summary(repair_result),
    }
    return updated


def smart_wait_select(
    hwnd: Optional[int],
    item: Optional[str] = None,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    mode: str = "select",
    timeout: float = 10.0,
    interval: float = 0.25,
    timeout_ms: int = 500,
    diagnostic: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Poll smart_select until a selectable item/control appears and selection succeeds."""
    target = _resolve_target(hwnd)
    helper_result = _smart_action_helper_post(
        target,
        "/smart_wait_select",
        {
            "item": item,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "mode": mode,
            "timeout": timeout,
            "interval": interval,
            "timeout_ms": timeout_ms,
            "diagnostic": diagnostic,
            "skip_uia": skip_uia,
            "repair": repair,
            "repair_timeout": repair_timeout,
        },
        timeout=float(timeout or 0.0) + (_smart_wait_selector_repair_timeout(repair_timeout, timeout) if _win32_repair_requested(repair, repair_timeout) else 0.0),
    )
    if helper_result is not None:
        return helper_result
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    interval_value = max(float(interval), 0.05)
    poll_summaries: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {}
    attempts = 0

    while True:
        attempts += 1
        result = smart_select(
            hwnd,
            item=item,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            index=index,
            match=match,
            mode=mode,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            skip_uia=skip_uia,
        )
        last_result = result
        poll_summaries.append(_smart_select_poll_summary(result))
        if result.get("ok"):
            result = dict(result)
            result.update({
                "waited": round(time.time() - start, 3),
                "wait_attempts": attempts,
                "timeout": float(timeout),
                "interval": interval_value,
            })
            if diagnostic:
                result["wait_polls"] = poll_summaries
            return result

        now = time.time()
        if now >= deadline:
            break
        time.sleep(min(interval_value, max(deadline - now, 0.0)))

    timeout_result = {
        "ok": False,
        "hwnd": last_result.get("hwnd") if isinstance(last_result, dict) else _resolve_target(hwnd),
        "error": "smart_wait_select_timeout",
        "timeout": float(timeout),
        "interval": interval_value,
        "waited": round(time.time() - start, 3),
        "wait_attempts": attempts,
        "selector": {
            "item": item,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "mode": mode,
        },
        "last_result": last_result if diagnostic else _smart_select_poll_summary(last_result),
        "failure_summary": _compact_attempt_failure_summary(last_result.get("attempts") or []) if isinstance(last_result, dict) else {},
        "wait_polls": poll_summaries,
    }
    return _smart_wait_select_maybe_repair(
        timeout_result,
        target,
        item=item,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        match=match,
        mode=mode,
        timeout=timeout,
        interval=interval_value,
        timeout_ms=timeout_ms,
        diagnostic=diagnostic,
        skip_uia=skip_uia,
        repair=repair,
        repair_timeout=repair_timeout,
    )


def _smart_cell_column_index(columns: List[Dict[str, Any]], column: Optional[int], column_name: Optional[str], match: str) -> Optional[int]:
    if column is not None:
        return int(column)
    if column_name is None:
        return 0
    for idx, item in enumerate(columns or []):
        if _matches_text(str(item.get("text", "")), str(column_name), match):
            return idx
    return None


def _smart_cell_row_index(items: List[Dict[str, Any]], row: Optional[int], row_text: Optional[str], match: str) -> Optional[int]:
    if row is not None:
        return int(row)
    if row_text is None:
        return 0 if items else None
    for item in items or []:
        values = [str(value) for value in (item.get("values") or [])]
        text = str(item.get("text", ""))
        if _matches_text(text, str(row_text), match) or any(_matches_text(value, str(row_text), match) for value in values):
            return int(item.get("index"))
    return None


def _smart_cell_native_candidates(
    hwnd: int,
    automation_id: Optional[str] = None,
    class_name: Optional[str] = None,
    control_type: Optional[str] = None,
    match: str = "contains",
    include_invisible: bool = False,
    timeout_ms: int = 500,
) -> List[Dict[str, Any]]:
    candidates = _win32_select_candidates(
        hwnd,
        name=None,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type or "listview",
        match=match,
        include_invisible=include_invisible,
        timeout_ms=timeout_ms,
    )
    return [candidate for candidate in candidates if str(candidate.get("kind") or "").lower() == "listview"]


def _smart_cell_uia_match(
    hwnd: int,
    row: Optional[int],
    column: Optional[int],
    row_text: Optional[str],
    column_name: Optional[str],
    match: str,
    max_depth: int = 12,
    max_elements: int = 1200,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
    def _find(query: Dict[str, Any]) -> Dict[str, Any]:
        return find_elements(hwnd, **query)

    return _smart_cell_uia_match_from_find(
        _find,
        row=row,
        column=column,
        row_text=row_text,
        column_name=column_name,
        match=match,
        max_depth=max_depth,
        max_elements=max_elements,
    )


def _smart_cell_item_matches(
    item: Dict[str, Any],
    requested_row: Optional[int],
    requested_column: Optional[int],
    row_text: Optional[str],
    column_name: Optional[str],
    match: str,
) -> bool:
    grid_item = item.get("grid_item") or {}
    cell_row = grid_item.get("row")
    cell_column = grid_item.get("column")
    if requested_row is not None and cell_row is not None and int(cell_row) != requested_row:
        return False
    if requested_column is not None and cell_column is not None and int(cell_column) != requested_column:
        return False
    if row_text is not None and not (
        _matches_text(str(item.get("name", "")), str(row_text), match)
        or _matches_text(str(item.get("value", "")), str(row_text), match)
    ):
        return False
    if column_name is not None:
        table_item = item.get("table_item") or {}
        headers = table_item.get("column_headers") or []
        if not any(_matches_text(str(header.get("name", "")), str(column_name), match) for header in headers):
            return False
    return True


def _smart_cell_uia_match_from_find(
    find_fn: Any,
    row: Optional[int],
    column: Optional[int],
    row_text: Optional[str],
    column_name: Optional[str],
    match: str,
    max_depth: int = 12,
    max_elements: int = 1200,
    diagnostic: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], List[Dict[str, Any]]]:
    attempts: List[Dict[str, Any]] = []
    requested_row = int(row) if row is not None else None
    requested_column = int(column) if column is not None else None
    result_limit = max(250, requested_row + 1) if requested_row is not None else 250
    for pattern in ("GridItem", "TableItem", "SpreadsheetItem"):
        for view in _uia_smart_views():
            query = {
                "pattern": pattern,
                "match": match,
                "enabled_only": False,
                "visible_only": True,
                "limit": result_limit,
                "max_depth": max_depth,
                "max_elements": max_elements,
                "view": view,
            }
            found = find_fn(query)
            if not isinstance(found, dict):
                found = {"error": "invalid_uia_find_result", "result_type": type(found).__name__}
            result_view = found.get("view") or view
            try:
                result_view = _normalize_uia_view(result_view)
            except Exception:
                result_view = view
            attempts.append({
                "method": f"uia.find.{result_view}.{pattern}",
                "view": result_view,
                "result": found if diagnostic else _compact_uia_find_result(found),
            })
            if _is_terminal_uia_helper_error(found):
                return None, result_view, attempts
            for item in list(found.get("matches") or []):
                if _smart_cell_item_matches(item, requested_row, requested_column, row_text, column_name, match):
                    selected = dict(item)
                    selected["uia_view"] = result_view
                    return selected, result_view, attempts
    return None, None, attempts


def _smart_cell_item_container_properties(row_text: Optional[str], automation_id: Optional[str]) -> List[Tuple[str, Any]]:
    properties: List[Tuple[str, Any]] = []
    if row_text is not None:
        properties.extend([("name", row_text), ("value", row_text)])
    if automation_id is not None:
        properties.append(("automation_id", automation_id))
    deduped: List[Tuple[str, Any]] = []
    seen = set()
    for key, value in properties:
        marker = (key, _selector_norm(value))
        if marker not in seen:
            seen.add(marker)
            deduped.append((key, value))
    return deduped


def _smart_cell_virtualized_item_matches(
    item: Dict[str, Any],
    requested_row: Optional[int],
    requested_column: Optional[int],
    row_text: Optional[str],
    column_name: Optional[str],
    match: str,
) -> bool:
    if not _smart_cell_item_matches(item, requested_row, requested_column, row_text, column_name, match):
        return False
    grid_item = item.get("grid_item") or {}
    if requested_column is not None and grid_item.get("column") is None:
        return False
    if requested_row is not None and grid_item.get("row") is None and row_text is None:
        return False
    return True


def _smart_cell_row_candidate_matches(
    item: Dict[str, Any],
    requested_row: Optional[int],
    row_text: Optional[str],
    match: str,
) -> bool:
    grid_item = item.get("grid_item") or {}
    item_row = grid_item.get("row")
    if requested_row is not None and item_row is not None and int(item_row) != requested_row:
        return False
    if requested_row is not None and item_row is None and row_text is None:
        return False
    if row_text is not None and not (
        _matches_text(str(item.get("name", "")), str(row_text), match)
        or _matches_text(str(item.get("value", "")), str(row_text), match)
    ):
        return False
    return True


def _smart_cell_child_matches_column(
    item: Dict[str, Any],
    requested_row: Optional[int],
    requested_column: Optional[int],
    column_name: Optional[str],
    match: str,
) -> bool:
    grid_item = item.get("grid_item") or {}
    if requested_row is not None and grid_item.get("row") is not None and int(grid_item.get("row")) != requested_row:
        return False
    if requested_column is not None:
        if grid_item.get("column") is None or int(grid_item.get("column")) != requested_column:
            return False
    if column_name is not None:
        table_item = item.get("table_item") or {}
        headers = table_item.get("column_headers") or []
        if not any(_matches_text(str(header.get("name", "")), str(column_name), match) for header in headers):
            return False
    return requested_column is not None or column_name is not None


def _smart_cell_select_child_from_row(
    row_item: Dict[str, Any],
    child_items: List[Dict[str, Any]],
    requested_row: Optional[int],
    requested_column: Optional[int],
    column_name: Optional[str],
    match: str,
) -> Optional[Dict[str, Any]]:
    if not child_items:
        return None
    row_grid_item = row_item.get("grid_item") or {}
    row_index = requested_row
    if row_index is None and row_grid_item.get("row") is not None:
        row_index = int(row_grid_item.get("row"))
    matches: List[Dict[str, Any]] = []
    for child in child_items:
        if not isinstance(child, dict):
            continue
        if _smart_cell_child_matches_column(child, row_index, requested_column, column_name, match):
            matches.append(child)
    if len(matches) != 1:
        return None
    return matches[0]


def _smart_cell_virtualized_find(
    find_fn: Any,
    item_find_fn: Any,
    attempts: List[Dict[str, Any]],
    *,
    row: Optional[int],
    column: Optional[int],
    row_text: Optional[str],
    column_name: Optional[str],
    automation_id: Optional[str],
    match: str,
    diagnostic: bool,
    max_depth: int = 12,
    max_elements: int = 1200,
) -> Dict[str, Any]:
    properties = _smart_cell_item_container_properties(row_text, automation_id)
    if not properties:
        return {"selected": None, "view": None, "container": None}
    requested_row = int(row) if row is not None else None
    requested_column = int(column) if column is not None else None
    item_limit = 24
    for view in _uia_smart_views():
        container_result = find_fn({
            "pattern": "ItemContainer",
            "match": match,
            "enabled_only": False,
            "visible_only": True,
            "limit": 24,
            "max_depth": max_depth,
            "max_elements": max_elements,
            "view": view,
        })
        if not isinstance(container_result, dict):
            container_result = {"error": "invalid_uia_find_result", "result_type": type(container_result).__name__}
        result_view = container_result.get("view") or view
        try:
            result_view = _normalize_uia_view(result_view)
        except Exception:
            result_view = view
        attempts.append({
            "method": f"uia.find.{result_view}.ItemContainer.cell",
            "view": result_view,
            "result": container_result if diagnostic else _compact_uia_find_result(container_result),
        })
        if _is_terminal_uia_helper_error(container_result):
            return {"selected": None, "view": result_view, "container": None, "terminal_error": container_result}
        for container in list(container_result.get("matches") or []):
            container_index = container.get("index")
            if container_index is None:
                continue
            for property_name, property_value in properties:
                found = item_find_fn(int(container_index), property_name, property_value, item_limit, result_view)
                if not isinstance(found, dict):
                    found = {"error": "invalid_item_container_result", "result_type": type(found).__name__}
                attempts.append({
                    "method": f"uia.item_container.{result_view}.cell.{property_name}",
                    "view": result_view,
                    "container_index": int(container_index),
                    "result": found if diagnostic else {
                        key: found.get(key)
                        for key in ("ok", "error", "count", "helper", "helper_elevated", "timeout", "worker_killed")
                        if key in found
                    },
                })
                if _is_terminal_uia_helper_error(found):
                    return {"selected": None, "view": result_view, "container": container, "terminal_error": found}
                for item in list(found.get("matches") or []):
                    if not isinstance(item, dict):
                        continue
                    if not _smart_cell_virtualized_item_matches(item, requested_row, requested_column, row_text, column_name, match):
                        if _smart_cell_row_candidate_matches(item, requested_row, row_text, match):
                            child_items = list(item.get("children") or item.get("child_matches") or [])
                            selected_child = _smart_cell_select_child_from_row(
                                item,
                                child_items,
                                requested_row,
                                requested_column,
                                column_name,
                                match,
                            )
                            attempts.append({
                                "method": f"uia.item_container.{result_view}.cell.row_children",
                                "view": result_view,
                                "row_index": item.get("index"),
                                "child_count": len(child_items),
                                "selected_index": selected_child.get("index") if isinstance(selected_child, dict) else None,
                                "result": {"ok": bool(selected_child)},
                            })
                            if not selected_child:
                                continue
                            selected = dict(selected_child)
                            selected["uia_view"] = result_view
                            selected["container_index"] = int(container_index)
                            selected["item_container_property"] = property_name
                            selected["item_container_row_index"] = item.get("index")
                            selected["item_container_row_child_match"] = True
                            return {"selected": selected, "view": result_view, "container": container, "result": found}
                        continue
                    selected = dict(item)
                    selected["uia_view"] = result_view
                    selected["container_index"] = int(container_index)
                    selected["item_container_property"] = property_name
                    selected["item_container_cell_match"] = True
                    return {"selected": selected, "view": result_view, "container": container, "result": found}
    return {"selected": None, "view": None, "container": None}


def smart_cell(
    hwnd: Optional[int],
    row: Optional[int] = None,
    column: Optional[int] = None,
    row_text: Optional[str] = None,
    column_name: Optional[str] = None,
    text: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    match: str = "contains",
    action: str = "get",
    timeout_ms: int = 500,
    diagnostic: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Read, select, or set a grid/list-view cell by row/column selectors."""
    target = _resolve_target(hwnd)
    if not user32.IsWindow(target) and int(target) != _DESKTOP_UIA_KEY:
        return {"ok": False, "error": f"Window {target} no longer exists", "hwnd": target}
    action_lower = str(action or "get").lower().replace("-", "_")
    if action_lower in ("read", "value"):
        action_lower = "get"
    if action_lower in ("write", "set_text", "set_value"):
        action_lower = "set"
    if action_lower not in ("get", "select", "set"):
        return {"ok": False, "error": "action must be get, select, or set", "hwnd": target, "action": action}
    if action_lower == "set" and text is None:
        return {"ok": False, "error": "text required for set action", "hwnd": target}
    if row is not None and int(row) < 0:
        return {"ok": False, "error": "row must be >= 0", "hwnd": target, "row": row}
    if column is not None and int(column) < 0:
        return {"ok": False, "error": "column must be >= 0", "hwnd": target, "column": column}
    helper_result = _smart_action_helper_post(
        target,
        "/smart_cell",
        {
            "row": row,
            "column": column,
            "row_text": row_text,
            "column_name": column_name,
            "text": text,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "match": match,
            "action": action,
            "timeout_ms": timeout_ms,
            "diagnostic": diagnostic,
            "skip_uia": skip_uia,
            "repair": repair,
            "repair_timeout": repair_timeout,
        },
    )
    if helper_result is not None:
        return helper_result

    attempts: List[Dict[str, Any]] = []
    if skip_uia:
        attempts.append({"method": "uia.skipped", "reason": "skip_uia requested"})
    else:
        def _find(query: Dict[str, Any]) -> Dict[str, Any]:
            return find_elements(target, **query)

        uia_match, uia_view, uia_attempts = _smart_cell_uia_match(target, row, column, row_text, column_name, match)
        attempts.extend(uia_attempts)
        if not uia_match:
            def _item_find(container_index: int, property_name: str, property_value: Any, limit_value: int, view_name: str) -> Dict[str, Any]:
                return item_container_find(
                    target,
                    container_index,
                    property_name,
                    property_value,
                    limit=limit_value,
                    max_depth=12,
                    max_elements=1200,
                    view=view_name,
                    include_children=bool(column is not None or column_name is not None),
                    max_children=96,
                )

            virtualized_lookup = _smart_cell_virtualized_find(
                _find,
                _item_find,
                attempts,
                row=row,
                column=column,
                row_text=row_text,
                column_name=column_name,
                automation_id=automation_id,
                match=match,
                diagnostic=diagnostic,
            )
            uia_match = virtualized_lookup.get("selected") if isinstance(virtualized_lookup.get("selected"), dict) else None
            uia_view = str(virtualized_lookup.get("view") or uia_view or "raw")
        if uia_match:
            uia_view = uia_view or str(uia_match.get("uia_view") or "raw")
            uia_index = int(uia_match.get("index"))
            uia_match = _smart_uia_prepare_element(target, uia_index, uia_match, uia_view, attempts, max_depth=12, max_elements=1200, diagnostic=diagnostic)
            if action_lower == "get":
                return _with_uia_relocation({"ok": True, "hwnd": target, "method": f"uia.grid_item.{uia_view}.get", "view": uia_view, "row": (uia_match.get("grid_item") or {}).get("row"), "column": (uia_match.get("grid_item") or {}).get("column"), "text": uia_match.get("value") or uia_match.get("name") or "", "target": uia_match, "attempts": attempts}, uia_match)
            if action_lower == "select":
                for uia_action in (_smart_select_uia_action_chain("select", uia_match) or ["select"]):
                    action_value = _smart_select_legacy_flags("select") if uia_action == "legacy-select" else None
                    result = perform_action(target, uia_index, uia_action, value=action_value, max_depth=12, max_elements=1200, view=uia_view)
                    attempts.append({"method": f"uia.action.{uia_view}.{uia_action}", "view": uia_view, "index": uia_index, "result": result if diagnostic else _compact_uia_action_result(result)})
                    if result.get("ok"):
                        return _with_uia_relocation({"ok": True, "hwnd": target, "method": f"uia.action.{uia_view}.{uia_action}", "view": uia_view, "row": (uia_match.get("grid_item") or {}).get("row"), "column": (uia_match.get("grid_item") or {}).get("column"), "target": uia_match, "attempts": attempts}, result, uia_match)
            if action_lower == "set":
                for uia_action in _smart_text_uia_action_chain(uia_match):
                    result = perform_action(target, uia_index, uia_action, value=text, max_depth=12, max_elements=1200, view=uia_view)
                    attempts.append({"method": f"uia.action.{uia_view}.{uia_action}", "view": uia_view, "index": uia_index, "result": result if diagnostic else _compact_uia_action_result(result)})
                    if result.get("ok"):
                        return _with_uia_relocation({"ok": True, "hwnd": target, "method": f"uia.action.{uia_view}.{uia_action}", "view": uia_view, "row": (uia_match.get("grid_item") or {}).get("row"), "column": (uia_match.get("grid_item") or {}).get("column"), "text": text, "target": uia_match, "attempts": attempts}, result, uia_match)
                result = perform_action(target, uia_index, "set-value", value=text, max_depth=12, max_elements=1200, view=uia_view)
                attempts.append({"method": f"uia.action.{uia_view}.set-value", "view": uia_view, "index": uia_index, "result": result if diagnostic else _compact_uia_action_result(result)})
                if result.get("ok"):
                    return _with_uia_relocation({"ok": True, "hwnd": target, "method": f"uia.action.{uia_view}.set-value", "view": uia_view, "row": (uia_match.get("grid_item") or {}).get("row"), "column": (uia_match.get("grid_item") or {}).get("column"), "text": text, "target": uia_match, "attempts": attempts}, result, uia_match)

    candidates = _smart_cell_native_candidates(
        target,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        match=match,
        include_invisible=False,
        timeout_ms=timeout_ms,
    )
    attempts.append({"method": "win32.find_listview", "count": len(candidates), "candidates": candidates if diagnostic else [_compact_window_info(c.get("window")) for c in candidates[:8]]})
    for candidate in candidates:
        child_hwnd = int(candidate.get("hwnd") or 0)
        info = candidate.get("control") or win32_control_info(child_hwnd, timeout_ms=timeout_ms)
        columns = list(info.get("columns") or [])
        items = list(info.get("items") or [])
        row_index = _smart_cell_row_index(items, row, row_text, match)
        column_index = _smart_cell_column_index(columns, column, column_name, match)
        if row_index is None or column_index is None:
            attempts.append({"method": "win32.resolve_cell", "target": _compact_window_info(candidate.get("window")), "row": row_index, "column": column_index, "row_text": row_text, "column_name": column_name})
            continue
        if row_index < 0 or row_index >= int(info.get("count") or len(items)):
            attempts.append({"method": "win32.row_out_of_range", "row": row_index, "count": info.get("count")})
            continue
        cell_text = ""
        row_item = next((item for item in items if int(item.get("index") or 0) == row_index), None)
        if row_item:
            values = list(row_item.get("values") or [])
            if column_index < len(values):
                cell_text = str(values[column_index])
        if action_lower == "get":
            return {"ok": True, "hwnd": target, "method": "win32.listview.get_cell", "row": row_index, "column": column_index, "text": cell_text, "target": candidate, "attempts": attempts}
        native_action = "select" if action_lower == "select" else "set_cell"
        result = win32_control_action(
            child_hwnd,
            native_action,
            index=row_index,
            value=column_index if action_lower == "set" else None,
            text=text if action_lower == "set" else None,
            match=match,
            timeout_ms=timeout_ms,
        )
        attempts.append({"method": f"win32.control_action.{native_action}", "target": candidate if diagnostic else _compact_window_info(candidate.get("window")), "result": result if diagnostic else {k: result.get(k) for k in ("ok", "error", "kind", "action", "index", "column", "text", "result")}})
        if result.get("ok"):
            after_text = text if action_lower == "set" else cell_text
            return {"ok": True, "hwnd": target, "method": f"win32.control_action.{native_action}", "row": row_index, "column": column_index, "text": after_text, "target": candidate, "attempts": attempts}

    failure = {
        "ok": False,
        "hwnd": target,
        "error": "No UIA grid cell or native Win32 ListView cell path succeeded",
        "selector": {
            "row": row,
            "column": column,
            "row_text": row_text,
            "column_name": column_name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "match": match,
            "action": action_lower,
        },
        "attempts": attempts,
        "failure_summary": _compact_attempt_failure_summary(attempts),
    }
    repaired = _smart_wait_cell_maybe_repair(
        failure,
        target,
        row=row,
        column=column,
        row_text=row_text,
        column_name=column_name,
        text=text,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        match=match,
        action=action_lower,
        timeout=0.0,
        interval=0.05,
        timeout_ms=timeout_ms,
        diagnostic=diagnostic,
        skip_uia=skip_uia,
        repair=repair,
        repair_timeout=repair_timeout,
    )
    if repaired is not failure and isinstance(repaired, dict) and repaired.get("smart_wait_repair"):
        repaired = dict(repaired)
        repaired["smart_action_repair"] = True
    return repaired


def _smart_cell_poll_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    summary = _smart_poll_summary_base(result)
    summary.update({
        "row": result.get("row") if isinstance(result, dict) else None,
        "column": result.get("column") if isinstance(result, dict) else None,
        "text": result.get("text") if isinstance(result, dict) else None,
    })
    return summary


def _smart_wait_cell_repair_selector_from_suggestion(suggestion: Dict[str, Any], original: Dict[str, Any]) -> Dict[str, Any]:
    selector: Dict[str, Any] = {}
    for key in ("automation_id", "control_type", "class_name"):
        value = suggestion.get(key)
        if value not in (None, "", [], {}):
            selector[key] = value
    selector["match"] = suggestion.get("match") or original.get("match") or "contains"
    return selector


def _smart_wait_cell_maybe_repair(
    result: Dict[str, Any],
    hwnd: int,
    *,
    row: Optional[int] = None,
    column: Optional[int] = None,
    row_text: Optional[str] = None,
    column_name: Optional[str] = None,
    text: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    match: str = "contains",
    action: str = "get",
    timeout: float = 10.0,
    interval: float = 0.25,
    timeout_ms: int = 500,
    diagnostic: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if result.get("ok") or not _win32_repair_requested(repair, repair_timeout) or _coerce_bool(skip_uia, False):
        return result
    suggestion = _smart_wait_selector_repair_suggestion(result)
    if not suggestion:
        return result
    original = {
        "automation_id": automation_id,
        "control_type": control_type,
        "class_name": class_name,
        "match": match,
    }
    selector = _smart_wait_cell_repair_selector_from_suggestion(suggestion, original)
    if not any(selector.get(key) not in (None, "", [], {}) for key in ("automation_id", "control_type", "class_name")):
        return result
    repair_timeout_value = _smart_wait_selector_repair_timeout(repair_timeout, timeout)
    deadline = time.time() + repair_timeout_value
    repair_attempts = 0
    repair_result: Dict[str, Any] = {}
    while True:
        repair_attempts += 1
        repair_result = smart_cell(
            hwnd,
            row=row,
            column=column,
            row_text=row_text,
            column_name=column_name,
            text=text,
            automation_id=selector.get("automation_id"),
            control_type=selector.get("control_type"),
            class_name=selector.get("class_name"),
            match=selector.get("match", "contains"),
            action=action,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            skip_uia=False,
        )
        if repair_result.get("ok"):
            break
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))
    repair_info = {
        "attempted": True,
        "ok": bool(repair_result.get("ok")),
        "timeout": repair_timeout_value,
        "attempts": repair_attempts,
        "selector": selector,
        "cell": {
            "row": row,
            "column": column,
            "row_text": row_text,
            "column_name": column_name,
        },
        "reason": "retry smart-wait cell with failure_summary.selector_suggestions[0]",
    }
    if repair_result.get("ok"):
        repaired = dict(repair_result)
        repaired.update({
            "repaired": True,
            "selector_repair": True,
            "uia_selector_repair": True,
            "cell_selector_repair": True,
            "smart_wait_repair": True,
            "repair": repair_info,
            "strict_wait_attempts": result.get("wait_attempts"),
            "repair_attempts": repair_attempts,
            "timeout": float(timeout),
            "interval": max(float(interval), 0.05),
            "suggestion": _smart_poll_compact_selector_suggestions([suggestion], limit=1)[0],
            "original_failure_summary": result.get("failure_summary"),
        })
        return repaired
    updated = dict(result)
    updated["repair"] = {
        **repair_info,
        "result": _smart_cell_poll_summary(repair_result),
    }
    return updated


def smart_wait_cell(
    hwnd: Optional[int],
    row: Optional[int] = None,
    column: Optional[int] = None,
    row_text: Optional[str] = None,
    column_name: Optional[str] = None,
    text: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    match: str = "contains",
    action: str = "get",
    timeout: float = 10.0,
    interval: float = 0.25,
    timeout_ms: int = 500,
    diagnostic: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Poll smart_cell until a grid/ListView cell appears and the action succeeds."""
    target = _resolve_target(hwnd)
    helper_result = _smart_action_helper_post(
        target,
        "/smart_wait_cell",
        {
            "row": row,
            "column": column,
            "row_text": row_text,
            "column_name": column_name,
            "text": text,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "match": match,
            "action": action,
            "timeout": timeout,
            "interval": interval,
            "timeout_ms": timeout_ms,
            "diagnostic": diagnostic,
            "skip_uia": skip_uia,
            "repair": repair,
            "repair_timeout": repair_timeout,
        },
        timeout=float(timeout or 0.0) + (_smart_wait_selector_repair_timeout(repair_timeout, timeout) if _win32_repair_requested(repair, repair_timeout) else 0.0),
    )
    if helper_result is not None:
        return helper_result
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    interval_value = max(float(interval), 0.05)
    poll_summaries: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {}
    attempts = 0

    while True:
        attempts += 1
        result = smart_cell(
            hwnd,
            row=row,
            column=column,
            row_text=row_text,
            column_name=column_name,
            text=text,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            match=match,
            action=action,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            skip_uia=skip_uia,
        )
        last_result = result
        poll_summaries.append(_smart_cell_poll_summary(result))
        if result.get("ok"):
            result = dict(result)
            result.update({
                "waited": round(time.time() - start, 3),
                "wait_attempts": attempts,
                "timeout": float(timeout),
                "interval": interval_value,
            })
            if diagnostic:
                result["wait_polls"] = poll_summaries
            return result

        now = time.time()
        if now >= deadline:
            break
        time.sleep(min(interval_value, max(deadline - now, 0.0)))

    timeout_result = {
        "ok": False,
        "hwnd": last_result.get("hwnd") if isinstance(last_result, dict) else _resolve_target(hwnd),
        "error": "smart_wait_cell_timeout",
        "timeout": float(timeout),
        "interval": interval_value,
        "waited": round(time.time() - start, 3),
        "wait_attempts": attempts,
        "selector": {
            "row": row,
            "column": column,
            "row_text": row_text,
            "column_name": column_name,
            "text": text,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "match": match,
            "action": action,
        },
        "last_result": last_result if diagnostic else _smart_cell_poll_summary(last_result),
        "failure_summary": _compact_attempt_failure_summary(last_result.get("attempts") or []) if isinstance(last_result, dict) else {},
        "wait_polls": poll_summaries,
    }
    return _smart_wait_cell_maybe_repair(
        timeout_result,
        target,
        row=row,
        column=column,
        row_text=row_text,
        column_name=column_name,
        text=text,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        match=match,
        action=action,
        timeout=timeout,
        interval=interval_value,
        timeout_ms=timeout_ms,
        diagnostic=diagnostic,
        skip_uia=skip_uia,
        repair=repair,
        repair_timeout=repair_timeout,
    )


def smart_text_input(
    hwnd: Optional[int],
    text: str,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    mode: str = "set-text",
    timeout: float = 1.0,
    timeout_ms: int = 500,
    verify: bool = True,
    diagnostic: bool = False,
    allow_focus_fallback: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Set text using UIA when available, then Win32 child controls, then focused input."""
    target = _resolve_target(hwnd)
    if not user32.IsWindow(target):
        return {"ok": False, "error": f"Window {target} no longer exists", "hwnd": target}
    attempts: List[Dict[str, Any]] = []
    text_value = str(text)
    requested_mode = (mode or "set-text").lower().replace("_", "-")
    requested_index = int(index) if index is not None else None
    if requested_index is not None and requested_index < 0:
        return {"ok": False, "error": "index must be >= 0", "hwnd": target, "index": requested_index}
    helper_result = _smart_action_helper_post(
        target,
        "/smart_text",
        {
            "text": text_value,
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "mode": mode,
            "timeout": timeout,
            "timeout_ms": timeout_ms,
            "verify": verify,
            "diagnostic": diagnostic,
            "allow_focus_fallback": allow_focus_fallback,
            "skip_uia": skip_uia,
            "repair": repair,
            "repair_timeout": repair_timeout,
        },
        timeout=timeout,
    )
    if helper_result is not None:
        return helper_result

    if skip_uia:
        attempts.append({"method": "uia.skipped", "reason": "skip_uia requested"})
    else:
        def _find(query: Dict[str, Any]) -> Dict[str, Any]:
            return find_elements(target, **query)

        lookup = _smart_text_uia_find(
            _find,
            attempts,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            match=match,
            requested_index=requested_index,
            diagnostic=diagnostic,
        )
        selected = lookup.get("selected") if isinstance(lookup.get("selected"), dict) else None
        uia_view = str(lookup.get("view") or "raw")
        uia_strategy = str(lookup.get("strategy") or "value")
        if selected:
            uia_index = int(selected.get("index"))
            selected = _smart_uia_prepare_element(target, uia_index, selected, uia_view, attempts, max_depth=10, max_elements=500, diagnostic=diagnostic)
            actions = _smart_text_uia_action_chain(selected)
            if not actions:
                actions = ["legacy-set-value"] if uia_strategy == "legacy" else ["set-value"]
            for uia_action in actions:
                if uia_action == "legacy-set-value":
                    uia_set = perform_action(target, uia_index, "legacy-set-value", value=text_value, max_depth=10, max_elements=500, view=uia_view)
                    method = f"uia.legacy_set_value.{uia_view}"
                else:
                    uia_set = set_value(target, uia_index, text_value, max_depth=10, max_elements=500, view=uia_view)
                    method = f"uia.set_value.{uia_view}"
                attempts.append({"method": method, "view": uia_view, "index": uia_index, "result": uia_set if diagnostic else _compact_uia_action_result(uia_set)})
                if uia_set.get("ok"):
                    return _with_uia_relocation({
                        "ok": True,
                        "hwnd": target,
                        "method": method,
                        "view": uia_view,
                        "text_length": len(text_value),
                        "target": selected,
                        "attempts": attempts,
                    }, uia_set, selected)

    candidates = _win32_text_input_candidates(
        target,
        name=name,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type,
        index=index,
        match=match,
        include_invisible=False,
        timeout_ms=timeout_ms,
    )
    attempts.append({"method": "win32.find_text_child", "count": len(candidates), "candidates": candidates if diagnostic else [_compact_window_info(c.get("window")) for c in candidates[:8]]})
    for candidate in candidates:
        child_hwnd = int(candidate.get("hwnd") or 0)
        if requested_mode in ("append", "replace-selection", "replace_selection"):
            input_mode = "append" if requested_mode == "append" else "replace-selection"
            result = focused_input(child_hwnd, text_value, mode=input_mode, timeout=timeout, timeout_ms=timeout_ms, verify=verify, diagnostic=diagnostic)
            method = f"win32.focused_input.{input_mode}"
        else:
            result = _win32_set_text_direct(child_hwnd, text_value, timeout_ms=timeout_ms, verify=verify)
            method = "win32.set_text"
        attempts.append({"method": method, "target": candidate, "result": result if diagnostic else {k: result.get(k) for k in ("ok", "error", "hwnd", "helper", "helper_elevated", "verified", "method")}})
        if result.get("ok"):
            return {
                "ok": True,
                "hwnd": target,
                "method": method,
                "text_length": len(text_value),
                "target": candidate,
                "attempts": attempts,
            }
        if allow_focus_fallback:
            focus_mode = "append" if requested_mode == "append" else ("replace-selection" if requested_mode in ("replace-selection", "replace_selection") else "set-text")
            focus_result = focused_input(child_hwnd, text_value, mode=focus_mode, timeout=timeout, timeout_ms=timeout_ms, verify=verify, diagnostic=diagnostic)
            focus_method = f"win32.focused_input.{focus_mode}"
            attempts.append({"method": focus_method, "target": candidate, "result": focus_result if diagnostic else {k: focus_result.get(k) for k in ("ok", "error", "hwnd", "focus_hwnd", "method", "verified", "native_kind")}})
            if focus_result.get("ok"):
                return {
                    "ok": True,
                    "hwnd": target,
                    "method": focus_method,
                    "text_length": len(text_value),
                    "target": candidate,
                    "attempts": attempts,
                }

    if candidates:
        failure = {
            "ok": False,
            "hwnd": target,
            "method": "win32.text_child_failed",
            "text_length": len(text_value),
            "attempts": attempts,
            "failure_summary": _compact_attempt_failure_summary(attempts),
            "error": "text child controls were found but none accepted direct text input",
        }
        repaired = _smart_wait_text_maybe_repair(
            failure,
            target,
            text_value,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            match=match,
            mode=mode,
            timeout=timeout,
            interval=0.05,
            input_timeout=timeout,
            timeout_ms=timeout_ms,
            verify=verify,
            diagnostic=diagnostic,
            allow_focus_fallback=allow_focus_fallback,
            skip_uia=skip_uia,
            repair=repair,
            repair_timeout=repair_timeout,
        )
        if repaired is not failure and isinstance(repaired, dict) and repaired.get("smart_wait_repair"):
            repaired = dict(repaired)
            repaired["smart_action_repair"] = True
        return repaired

    if not allow_focus_fallback:
        failure = {
            "ok": False,
            "hwnd": target,
            "method": "failed",
            "text_length": len(text_value),
            "attempts": attempts,
            "failure_summary": _compact_attempt_failure_summary(attempts),
            "error": "no UIA or Win32 text input path succeeded; focus fallback disabled",
        }
        repaired = _smart_wait_text_maybe_repair(
            failure,
            target,
            text_value,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            match=match,
            mode=mode,
            timeout=timeout,
            interval=0.05,
            input_timeout=timeout,
            timeout_ms=timeout_ms,
            verify=verify,
            diagnostic=diagnostic,
            allow_focus_fallback=allow_focus_fallback,
            skip_uia=skip_uia,
            repair=repair,
            repair_timeout=repair_timeout,
        )
        if repaired is not failure and isinstance(repaired, dict) and repaired.get("smart_wait_repair"):
            repaired = dict(repaired)
            repaired["smart_action_repair"] = True
        return repaired

    fallback = focused_input(target, text_value, mode="set-text" if requested_mode in ("set-text", "set_text", "set") else "auto", timeout=timeout, timeout_ms=timeout_ms, verify=verify, diagnostic=diagnostic)
    attempts.append({"method": "focused_input.fallback", "result": fallback if diagnostic else {k: fallback.get(k) for k in ("ok", "error", "hwnd", "focus_hwnd", "method", "verified", "native_kind")}})
    result = {
        "ok": bool(fallback.get("ok")),
        "hwnd": target,
        "method": "focused_input.fallback" if fallback.get("ok") else "failed",
        "text_length": len(text_value),
        "attempts": attempts,
        "fallback": fallback,
        **({} if fallback.get("ok") else {"failure_summary": _compact_attempt_failure_summary(attempts)}),
    }
    if result.get("ok"):
        return result
    repaired = _smart_wait_text_maybe_repair(
        result,
        target,
        text_value,
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        match=match,
        mode=mode,
        timeout=timeout,
        interval=0.05,
        input_timeout=timeout,
        timeout_ms=timeout_ms,
        verify=verify,
        diagnostic=diagnostic,
        allow_focus_fallback=allow_focus_fallback,
        skip_uia=skip_uia,
        repair=repair,
        repair_timeout=repair_timeout,
    )
    if repaired is not result and isinstance(repaired, dict) and repaired.get("smart_wait_repair"):
        repaired = dict(repaired)
        repaired["smart_action_repair"] = True
    return repaired


def _smart_text_uia_find(
    find_fn: Any,
    attempts: List[Dict[str, Any]],
    *,
    name: Optional[str],
    automation_id: Optional[str],
    control_type: Optional[str],
    class_name: Optional[str],
    match: str,
    requested_index: Optional[int],
    diagnostic: bool,
) -> Dict[str, Any]:
    base_payload = {
        "name": name,
        "automation_id": automation_id,
        "class_name": class_name,
        "match": match,
        "limit": max(requested_index + 1, 1) if requested_index is not None else 1,
        "max_depth": 10,
        "max_elements": 500,
    }
    lookup = _uia_smart_find(
        find_fn,
        attempts,
        patterns=["Value"],
        payload={**base_payload, "control_type": control_type or "edit"},
        requested_index=requested_index,
        diagnostic=diagnostic,
        method_prefix="uia.find.value",
    )
    if isinstance(lookup.get("selected"), dict):
        lookup["strategy"] = "value"
        return lookup
    if control_type is None:
        broad_lookup = _uia_smart_find(
            find_fn,
            attempts,
            patterns=["Value"],
            payload=base_payload,
            requested_index=requested_index,
            diagnostic=diagnostic,
            method_prefix="uia.find.value_any",
        )
        if isinstance(broad_lookup.get("selected"), dict):
            broad_lookup["strategy"] = "value"
            broad_lookup["broad_value_match"] = True
            return broad_lookup
    legacy_lookup = _uia_smart_find(
        find_fn,
        attempts,
        patterns=["LegacyIAccessible"],
        payload={**base_payload, **({"control_type": control_type} if control_type is not None else {})},
        requested_index=requested_index,
        diagnostic=diagnostic,
        method_prefix="uia.find.legacy",
    )
    if isinstance(legacy_lookup.get("selected"), dict):
        legacy_lookup["strategy"] = "legacy"
    return legacy_lookup


def _smart_text_input_poll_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    summary = _smart_poll_summary_base(result)
    summary.update({
        "text_length": result.get("text_length") if isinstance(result, dict) else None,
    })
    return summary


def _smart_wait_text_maybe_repair(
    result: Dict[str, Any],
    hwnd: int,
    text: str,
    *,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    match: str = "contains",
    mode: str = "set-text",
    timeout: float = 10.0,
    interval: float = 0.25,
    input_timeout: float = 1.0,
    timeout_ms: int = 500,
    verify: bool = True,
    diagnostic: bool = False,
    allow_focus_fallback: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if result.get("ok") or not _win32_repair_requested(repair, repair_timeout) or _coerce_bool(skip_uia, False):
        return result
    suggestion = _smart_wait_selector_repair_suggestion(result)
    if not suggestion:
        return result
    original = {
        "name": name,
        "automation_id": automation_id,
        "control_type": control_type,
        "class_name": class_name,
        "match": match,
    }
    selector = _smart_wait_repair_selector_from_suggestion(suggestion, original)
    if not any(selector.get(key) not in (None, "", [], {}) for key in ("name", "automation_id", "control_type", "class_name")):
        return result
    repair_timeout_value = _smart_wait_selector_repair_timeout(repair_timeout, timeout)
    deadline = time.time() + repair_timeout_value
    repair_attempts = 0
    repair_result: Dict[str, Any] = {}
    while True:
        repair_attempts += 1
        repair_result = smart_text_input(
            hwnd,
            text,
            name=selector.get("name"),
            automation_id=selector.get("automation_id"),
            control_type=selector.get("control_type"),
            class_name=selector.get("class_name"),
            index=None,
            match=selector.get("match", "contains"),
            mode=mode,
            timeout=input_timeout,
            timeout_ms=timeout_ms,
            verify=verify,
            diagnostic=diagnostic,
            allow_focus_fallback=allow_focus_fallback,
            skip_uia=False,
        )
        if repair_result.get("ok"):
            break
        if time.time() >= deadline:
            break
        time.sleep(max(float(interval), 0.05))
    repair_info = {
        "attempted": True,
        "ok": bool(repair_result.get("ok")),
        "timeout": repair_timeout_value,
        "attempts": repair_attempts,
        "selector": selector,
        "reason": "retry smart-wait text with failure_summary.selector_suggestions[0]",
    }
    if repair_result.get("ok"):
        repaired = dict(repair_result)
        repaired.update({
            "repaired": True,
            "selector_repair": True,
            "uia_selector_repair": True,
            "smart_wait_repair": True,
            "repair": repair_info,
            "strict_wait_attempts": result.get("wait_attempts"),
            "repair_attempts": repair_attempts,
            "timeout": float(timeout),
            "interval": max(float(interval), 0.05),
            "input_timeout": float(input_timeout),
            "suggestion": _smart_poll_compact_selector_suggestions([suggestion], limit=1)[0],
            "original_failure_summary": result.get("failure_summary"),
        })
        return repaired
    updated = dict(result)
    updated["repair"] = {
        **repair_info,
        "result": _smart_text_input_poll_summary(repair_result),
    }
    return updated


def smart_wait_text_input(
    hwnd: Optional[int],
    text: str,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    mode: str = "set-text",
    timeout: float = 10.0,
    interval: float = 0.25,
    input_timeout: float = 1.0,
    timeout_ms: int = 500,
    verify: bool = True,
    diagnostic: bool = False,
    allow_focus_fallback: bool = False,
    skip_uia: bool = False,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Poll smart_text_input until a matching text input appears and accepts text."""
    target = _resolve_target(hwnd)
    if not user32.IsWindow(target):
        return {"ok": False, "error": f"Window {target} no longer exists", "hwnd": target}
    if index is not None and int(index) < 0:
        return {"ok": False, "error": "index must be >= 0", "hwnd": target, "index": int(index)}
    helper_result = _smart_action_helper_post(
        target,
        "/smart_wait_text",
        {
            "text": str(text),
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "mode": mode,
            "timeout": timeout,
            "interval": interval,
            "input_timeout": input_timeout,
            "timeout_ms": timeout_ms,
            "verify": verify,
            "diagnostic": diagnostic,
            "allow_focus_fallback": allow_focus_fallback,
            "skip_uia": skip_uia,
            "repair": repair,
            "repair_timeout": repair_timeout,
        },
        timeout=float(timeout or 0.0) + (_smart_wait_selector_repair_timeout(repair_timeout, timeout) if _win32_repair_requested(repair, repair_timeout) else 0.0),
    )
    if helper_result is not None:
        return helper_result
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    interval_value = max(float(interval), 0.05)
    poll_summaries: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {}
    attempts = 0

    while True:
        attempts += 1
        result = smart_text_input(
            hwnd,
            text,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            index=index,
            match=match,
            mode=mode,
            timeout=input_timeout,
            timeout_ms=timeout_ms,
            verify=verify,
            diagnostic=diagnostic,
            allow_focus_fallback=allow_focus_fallback,
            skip_uia=skip_uia,
        )
        last_result = result
        poll_summaries.append(_smart_text_input_poll_summary(result))
        if result.get("ok"):
            result = dict(result)
            result.update({
                "waited": round(time.time() - start, 3),
                "wait_attempts": attempts,
                "timeout": float(timeout),
                "interval": interval_value,
                "input_timeout": float(input_timeout),
            })
            if diagnostic:
                result["wait_polls"] = poll_summaries
            return result

        now = time.time()
        if now >= deadline:
            break
        time.sleep(min(interval_value, max(deadline - now, 0.0)))

    timeout_result = {
        "ok": False,
        "hwnd": last_result.get("hwnd") if isinstance(last_result, dict) else _resolve_target(hwnd),
        "error": "smart_wait_text_input_timeout",
        "timeout": float(timeout),
        "interval": interval_value,
        "input_timeout": float(input_timeout),
        "waited": round(time.time() - start, 3),
        "wait_attempts": attempts,
        "selector": {
            "name": name,
            "automation_id": automation_id,
            "control_type": control_type,
            "class_name": class_name,
            "index": index,
            "match": match,
            "mode": mode,
            "text_length": len(str(text)),
            "allow_focus_fallback": allow_focus_fallback,
            "skip_uia": skip_uia,
        },
        "last_result": last_result if diagnostic else _smart_text_input_poll_summary(last_result),
        "failure_summary": _compact_attempt_failure_summary(last_result.get("attempts") or []) if isinstance(last_result, dict) else {},
        "wait_polls": poll_summaries,
    }
    return _smart_wait_text_maybe_repair(
        timeout_result,
        target,
        str(text),
        name=name,
        automation_id=automation_id,
        control_type=control_type,
        class_name=class_name,
        match=match,
        mode=mode,
        timeout=timeout,
        interval=interval_value,
        input_timeout=input_timeout,
        timeout_ms=timeout_ms,
        verify=verify,
        diagnostic=diagnostic,
        allow_focus_fallback=allow_focus_fallback,
        skip_uia=skip_uia,
        repair=repair,
        repair_timeout=repair_timeout,
    )


def _related_dialog_relation(window: Dict[str, Any], base_hwnd: int, base_info: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return whether a top-level window belongs to the same dialog chain."""
    candidate_hwnd = int(window.get("hwnd") or 0)
    if not candidate_hwnd:
        return False, []
    base_root = int(base_info.get("root_hwnd") or base_hwnd)
    base_root_owner = int(base_info.get("root_owner_hwnd") or base_root)
    base_pid = int(base_info.get("pid") or 0)
    base_hwnds = {int(base_hwnd), base_root, base_root_owner}
    candidate_root = int(window.get("root_hwnd") or 0)
    candidate_owner = int(window.get("owner_hwnd") or 0)
    candidate_root_owner = int(window.get("root_owner_hwnd") or 0)
    candidate_pid = int(window.get("pid") or 0)
    relation: List[str] = []
    if candidate_owner in base_hwnds:
        relation.append("owner")
    if candidate_root_owner in base_hwnds:
        relation.append("root-owner")
    if candidate_root in base_hwnds:
        relation.append("root")
    if base_pid and candidate_pid == base_pid:
        relation.append("same-pid")
    return bool(relation), relation


def _related_dialog_score(
    window: Dict[str, Any],
    base_hwnd: int,
    base_info: Dict[str, Any],
    relation: List[str],
    z_order: int,
    dialog_title: Optional[str] = None,
    dialog_class_name: Optional[str] = None,
    dialog_process: Optional[str] = None,
    match: str = "contains",
) -> int:
    score = 100 - min(max(int(z_order), 0), 100)
    class_text = str(window.get("class_name") or "")
    if "owner" in relation:
        score += 100
    if "root-owner" in relation:
        score += 80
    if "root" in relation:
        score += 40
    if "same-pid" in relation:
        score += 30
    if class_text.lower() == "#32770":
        score += 60
    if bool(window.get("topmost")):
        score += 15
    if dialog_title is not None and _matches_text(str(window.get("title", "")), dialog_title, match):
        score += 25
    if dialog_class_name is not None and _matches_text(class_text, dialog_class_name, match):
        score += 25
    if dialog_process is not None:
        proc_text = f'{window.get("process_name", "")} {window.get("process_path", "")}'
        if _matches_text(proc_text, dialog_process, match):
            score += 10
    foreground = int(user32.GetForegroundWindow() or 0)
    if foreground:
        foreground_root = int(user32.GetAncestor(foreground, GA_ROOT) or foreground)
        foreground_root_owner = int(user32.GetAncestor(foreground, GA_ROOTOWNER) or foreground_root)
        candidate_hwnds = {
            int(window.get("hwnd") or 0),
            int(window.get("root_hwnd") or 0),
            int(window.get("root_owner_hwnd") or 0),
        }
        if foreground in candidate_hwnds or foreground_root in candidate_hwnds or foreground_root_owner in candidate_hwnds:
            score += 120
    base_root = int(base_info.get("root_hwnd") or base_hwnd)
    if int(window.get("hwnd") or 0) in {int(base_hwnd), base_root}:
        score -= 500
    return score


def _dialog_window_matches(
    window: Dict[str, Any],
    dialog_title: Optional[str] = None,
    dialog_class_name: Optional[str] = None,
    dialog_process: Optional[str] = None,
    match: str = "contains",
) -> bool:
    if dialog_title is not None and not _matches_text(str(window.get("title", "")), dialog_title, match):
        return False
    if dialog_class_name is not None and not _matches_text(str(window.get("class_name", "")), dialog_class_name, match):
        return False
    if dialog_process is not None:
        proc_text = f'{window.get("process_name", "")} {window.get("process_path", "")}'
        if not _matches_text(proc_text, dialog_process, match):
            return False
    return True


def _related_dialog_candidates(
    hwnd: int,
    dialog_title: Optional[str] = None,
    dialog_class_name: Optional[str] = None,
    dialog_process: Optional[str] = None,
    match: str = "contains",
    include_invisible: bool = False,
) -> Dict[str, Any]:
    base_info = _window_info(hwnd)
    if not base_info:
        return {"ok": False, "error": f"Window {hwnd} not found", "candidates": []}
    base_root = int(base_info.get("root_hwnd") or hwnd)
    excluded = {int(hwnd), base_root}
    candidates: List[Dict[str, Any]] = []
    z_order = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(candidate, _):
        nonlocal z_order
        try:
            candidate_hwnd = int(candidate)
            info = _window_info(candidate_hwnd)
            if not info:
                return True
            if candidate_hwnd in excluded:
                z_order += 1
                return True
            if not include_invisible and not info.get("visible", False):
                z_order += 1
                return True
            if not _dialog_window_matches(
                info,
                dialog_title=dialog_title,
                dialog_class_name=dialog_class_name,
                dialog_process=dialog_process,
                match=match,
            ):
                z_order += 1
                return True
            related, relation = _related_dialog_relation(info, hwnd, base_info)
            if not related:
                z_order += 1
                return True
            if not include_invisible and not _is_usable_window_info(info):
                z_order += 1
                return True
            candidate_info = dict(info)
            candidate_info["relation"] = relation
            candidate_info["z_order"] = z_order
            candidate_info["score"] = _related_dialog_score(
                candidate_info,
                hwnd,
                base_info,
                relation,
                z_order,
                dialog_title=dialog_title,
                dialog_class_name=dialog_class_name,
                dialog_process=dialog_process,
                match=match,
            )
            candidates.append(candidate_info)
            z_order += 1
        except Exception:
            z_order += 1
        return True

    user32.EnumWindows(callback, None)
    candidates.sort(key=lambda item: (int(item.get("score") or 0), -int(item.get("z_order") or 0)), reverse=True)
    return {"ok": True, "target": base_info, "candidates": candidates}


def _smart_dialog_poll_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    candidates = result.get("candidates") if isinstance(result, dict) else []
    summary_candidates = []
    for item in list(candidates or [])[:5]:
        if not isinstance(item, dict):
            continue
        summary_candidates.append({
            "hwnd": item.get("hwnd"),
            "title": item.get("title"),
            "class_name": item.get("class_name"),
            "pid": item.get("pid"),
            "relation": item.get("relation"),
            "score": item.get("score"),
        })
    return {
        "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
        "error": result.get("error") if isinstance(result, dict) else None,
        "candidate_count": len(candidates or []) if isinstance(candidates, list) else 0,
        "candidates": summary_candidates,
    }


def wait_related_dialog(
    hwnd: Optional[int],
    dialog_title: Optional[str] = None,
    dialog_class_name: Optional[str] = None,
    dialog_process: Optional[str] = None,
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.25,
    include_invisible: bool = False,
    stable_ticks: int = 2,
    diagnostic: bool = False,
) -> Dict[str, Any]:
    """Wait for an owner/PID/root-owner related top-level dialog or popup."""
    target = _resolve_target(hwnd)
    base_info = _window_info(target)
    if not base_info:
        return {"ok": False, "error": f"Window {target} not found", "hwnd": target}
    start = time.time()
    deadline = start + max(float(timeout), 0.0)
    interval_value = max(float(interval), 0.05)
    required_ticks = max(int(stable_ticks), 1)
    signatures: Dict[int, Tuple[int, int, int, int, int]] = {}
    stable_counts: Dict[int, int] = {}
    polls: List[Dict[str, Any]] = []
    attempts = 0
    last_result: Dict[str, Any] = {}

    while True:
        attempts += 1
        found = _related_dialog_candidates(
            target,
            dialog_title=dialog_title,
            dialog_class_name=dialog_class_name,
            dialog_process=dialog_process,
            match=match,
            include_invisible=include_invisible,
        )
        last_result = found
        candidates = list(found.get("candidates") or []) if found.get("ok") else []
        for candidate in candidates:
            candidate_hwnd = int(candidate.get("hwnd") or 0)
            signature = _window_stability_signature(candidate)
            if signatures.get(candidate_hwnd) == signature:
                stable_counts[candidate_hwnd] = stable_counts.get(candidate_hwnd, 1) + 1
            else:
                signatures[candidate_hwnd] = signature
                stable_counts[candidate_hwnd] = 1
            candidate["stable_ticks"] = stable_counts.get(candidate_hwnd, 1)
        polls.append(_smart_dialog_poll_summary(found))
        stable = [
            candidate for candidate in candidates
            if stable_counts.get(int(candidate.get("hwnd") or 0), 0) >= required_ticks
        ]
        if stable:
            dialog = sorted(
                stable,
                key=lambda item: (int(item.get("score") or 0), int(item.get("stable_ticks") or 0)),
                reverse=True,
            )[0]
            return {
                "ok": True,
                "hwnd": target,
                "dialog_hwnd": int(dialog.get("hwnd") or 0),
                "dialog": dialog,
                "target": base_info,
                "waited": round(time.time() - start, 3),
                "wait_attempts": attempts,
                "timeout": float(timeout),
                "interval": interval_value,
                "stable_ticks": stable_counts.get(int(dialog.get("hwnd") or 0), required_ticks),
                "candidates": candidates if diagnostic else [
                    _compact_window_info(item) | {
                        "relation": item.get("relation"),
                        "score": item.get("score"),
                        "stable_ticks": item.get("stable_ticks"),
                    }
                    for item in candidates[:5]
                ],
                "wait_polls": polls if diagnostic else polls[-5:],
            }
        now = time.time()
        if now >= deadline:
            break
        time.sleep(min(interval_value, max(deadline - now, 0.0)))

    return {
        "ok": False,
        "hwnd": target,
        "error": "wait_related_dialog_timeout",
        "timeout": float(timeout),
        "interval": interval_value,
        "waited": round(time.time() - start, 3),
        "wait_attempts": attempts,
        "selector": {
            "dialog_title": dialog_title,
            "dialog_class_name": dialog_class_name,
            "dialog_process": dialog_process,
            "match": match,
            "include_invisible": include_invisible,
        },
        "last_result": last_result if diagnostic else _smart_dialog_poll_summary(last_result),
        "wait_polls": polls,
    }


def smart_dialog_action(
    hwnd: Optional[int],
    action_kind: str = "click",
    dialog_title: Optional[str] = None,
    dialog_class_name: Optional[str] = None,
    dialog_process: Optional[str] = None,
    name: Optional[str] = None,
    automation_id: Optional[str] = None,
    control_type: Optional[str] = None,
    class_name: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    text: Optional[str] = None,
    item: Optional[str] = None,
    row: Optional[int] = None,
    column: Optional[int] = None,
    row_text: Optional[str] = None,
    column_name: Optional[str] = None,
    control_action: str = "invoke",
    cell_action: str = "get",
    mode: str = "set-text",
    timeout: float = 10.0,
    action_timeout: float = 5.0,
    interval: float = 0.25,
    input_timeout: float = 1.0,
    timeout_ms: int = 500,
    verify: bool = True,
    diagnostic: bool = False,
    allow_focus_fallback: bool = False,
    allow_coordinate_fallback: bool = False,
    skip_uia: bool = False,
    include_invisible: bool = False,
    stable_ticks: int = 2,
    activate: bool = True,
    button: str = "left",
    clicks: int = 1,
    repair: Optional[bool] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Find a related dialog/popup for a window and run a smart action inside it."""
    kind = str(action_kind or "click").lower().replace("-", "_")
    if kind in ("button", "control", "invoke", "press"):
        kind = "click"
    elif kind in ("input", "text_input", "textinput", "edit", "set_text"):
        kind = "text"
    elif kind in ("choose", "selection", "select_item", "selectitem"):
        kind = "select"
    elif kind in ("grid", "table", "listview", "list_view"):
        kind = "cell"
    if kind not in ("click", "text", "select", "cell"):
        return {"ok": False, "error": "action_kind must be click, text, select, or cell", "action_kind": action_kind}

    wait_result = wait_related_dialog(
        hwnd,
        dialog_title=dialog_title,
        dialog_class_name=dialog_class_name,
        dialog_process=dialog_process,
        match=match,
        timeout=timeout,
        interval=interval,
        include_invisible=include_invisible,
        stable_ticks=stable_ticks,
        diagnostic=diagnostic,
    )
    if not wait_result.get("ok"):
        result = dict(wait_result)
        result["action_kind"] = kind
        return result

    dialog_hwnd = int(wait_result.get("dialog_hwnd") or 0)
    boundary_result = _elevated_helper_required_result(dialog_hwnd, "/smart_dialog_action")
    if boundary_result is not None:
        boundary_result.update({
            "action_kind": kind,
            "dialog": wait_result.get("dialog"),
            "dialog_wait": wait_result if diagnostic else {
                "ok": True,
                "waited": wait_result.get("waited"),
                "wait_attempts": wait_result.get("wait_attempts"),
                "stable_ticks": wait_result.get("stable_ticks"),
                "candidates": wait_result.get("candidates"),
            },
        })
        return boundary_result
    activation_result: Optional[bool] = None
    if activate and dialog_hwnd:
        activation_result = activate_window(dialog_hwnd)

    action_result: Dict[str, Any]
    if kind == "click":
        action_result = smart_wait_click(
            dialog_hwnd,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            index=index,
            match=match,
            action=control_action,
            timeout=action_timeout,
            interval=interval,
            button=button,
            clicks=clicks,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            allow_coordinate_fallback=allow_coordinate_fallback,
            skip_uia=skip_uia,
            repair=repair,
            repair_timeout=repair_timeout,
        )
    elif kind == "text":
        if text is None:
            return {
                "ok": False,
                "hwnd": wait_result.get("hwnd"),
                "dialog_hwnd": dialog_hwnd,
                "dialog": wait_result.get("dialog"),
                "error": "text required for smart_dialog_action text",
                "dialog_wait": wait_result,
            }
        action_result = smart_wait_text_input(
            dialog_hwnd,
            text,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            index=index,
            match=match,
            mode=mode,
            timeout=action_timeout,
            interval=interval,
            input_timeout=input_timeout,
            timeout_ms=timeout_ms,
            verify=verify,
            diagnostic=diagnostic,
            allow_focus_fallback=allow_focus_fallback,
            skip_uia=skip_uia,
            repair=repair,
            repair_timeout=repair_timeout,
        )
    elif kind == "select":
        action_result = smart_wait_select(
            dialog_hwnd,
            item=item if item is not None else text,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            index=index,
            match=match,
            mode=mode,
            timeout=action_timeout,
            interval=interval,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            skip_uia=skip_uia,
            repair=repair,
            repair_timeout=repair_timeout,
        )
    else:
        action_result = smart_wait_cell(
            dialog_hwnd,
            row=row,
            column=column,
            row_text=row_text,
            column_name=column_name,
            text=text,
            automation_id=automation_id,
            control_type=control_type,
            class_name=class_name,
            match=match,
            action=cell_action,
            timeout=action_timeout,
            interval=interval,
            timeout_ms=timeout_ms,
            diagnostic=diagnostic,
            skip_uia=skip_uia,
            repair=repair,
            repair_timeout=repair_timeout,
        )

    return {
        "ok": bool(action_result.get("ok")),
        "hwnd": wait_result.get("hwnd"),
        "dialog_hwnd": dialog_hwnd,
        "method": f"smart_dialog_action.{kind}" if action_result.get("ok") else "smart_dialog_action.failed",
        "action_kind": kind,
        "dialog": wait_result.get("dialog"),
        "dialog_wait": wait_result if diagnostic else {
            "ok": True,
            "waited": wait_result.get("waited"),
            "wait_attempts": wait_result.get("wait_attempts"),
            "stable_ticks": wait_result.get("stable_ticks"),
            "candidates": wait_result.get("candidates"),
        },
        "activated": activation_result,
        "action_result": action_result,
        "error": None if action_result.get("ok") else action_result.get("error", "dialog action failed"),
    }



