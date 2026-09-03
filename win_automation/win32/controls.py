"""
Native Win32 controls inspection and manipulation: Button, Edit, RichEdit, ComboBox,
ListBox, ListView, TreeView, Header, ToolBar, StatusBar, TrackBar, DateTime, IPAddress, etc.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.win32_structures import *
from win_automation.core.utils import is_valid_hwnd, make_lparam, clamp_int
from win_automation.win32.window import _win32_window_info, _send_message_timeout, _pump_wait
from win_automation.helper.client import _helper_route_for_hwnd, _helper_post

def _win32_text(hwnd: int, timeout_ms: int = 500) -> str:
    res = win32_text(hwnd, timeout_ms=timeout_ms)
    return res.get("text", "") if isinstance(res, dict) else str(res or "")

def _win32_set_text(hwnd: int, text: str, timeout_ms: int = 500) -> Dict[str, Any]:
    return win32_set_text(hwnd, text, timeout_ms=timeout_ms)

def _win32_click(hwnd: int, timeout_ms: int = 500) -> Dict[str, Any]:
    return win32_click(hwnd, timeout_ms=timeout_ms)

def win32_text(hwnd: int, timeout_ms: int = 250) -> Dict[str, Any]:
    """Read text from a native HWND with WM_GETTEXT."""
    info = _win32_window_info(hwnd)
    if not info:
        return {"error": f"Window/control {hwnd} not found"}
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_text")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post("/win32_text", {"hwnd": hwnd, "timeout_ms": timeout_ms}, elevated=helper_elevated)
        if helper_result.get("ok"):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return {"hwnd": hwnd, "window": info, "text": helper_result}
    return {"hwnd": hwnd, "window": info, "text": _get_control_text(hwnd, timeout_ms=timeout_ms)}


def win32_set_text(hwnd: int, text: str, timeout_ms: int = 500) -> Dict[str, Any]:
    """Set text on a native HWND with WM_SETTEXT."""
    info = _win32_window_info(hwnd)
    if not info:
        return {"error": f"Window/control {hwnd} not found"}
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_set_text")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post("/win32_set_text", {"hwnd": hwnd, "text": text, "timeout_ms": timeout_ms}, elevated=helper_elevated)
        if helper_result.get("ok"):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return {"ok": True, "hwnd": hwnd, "result": helper_result.get("result"), "window": info, "text": helper_result.get("text"), "helper": True, "helper_elevated": bool(helper_elevated)}
    buf = ctypes.create_unicode_buffer(text)
    ok, result = _send_message_timeout(
        hwnd,
        WM_SETTEXT,
        0,
        ctypes.addressof(buf),
        timeout_ms=timeout_ms,
    )
    after = _get_control_text(hwnd, timeout_ms=timeout_ms)
    return {"ok": bool(ok and result), "hwnd": hwnd, "result": result, "window": info, "text": after}


def _win32_set_text_direct(hwnd: int, text: str, timeout_ms: int = 500, verify: bool = True) -> Dict[str, Any]:
    info = _win32_window_info(hwnd)
    if not info:
        return {"error": f"Window/control {hwnd} not found"}
    buf = ctypes.create_unicode_buffer(str(text))
    ok, result = _send_message_timeout(
        hwnd,
        WM_SETTEXT,
        0,
        ctypes.addressof(buf),
        timeout_ms=timeout_ms,
    )
    after = _get_control_text(hwnd, timeout_ms=timeout_ms) if verify else {"ok": None, "text": "", "skipped": True}
    verified = None
    if verify and after.get("ok"):
        verified = str(after.get("text") or "") == str(text)
    return {
        "ok": bool(ok and (verified is not False)),
        "hwnd": hwnd,
        "sent": bool(ok),
        "message_return": result,
        "window": info,
        "text": after,
        "verified": verified,
        "direct": True,
    }


def win32_click(hwnd: int, timeout_ms: int = 500) -> Dict[str, Any]:
    """Click a native button-like HWND using BM_CLICK without relying on coordinates."""
    info = _win32_window_info(hwnd)
    if not info:
        return {"error": f"Window/control {hwnd} not found"}
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_click")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post("/win32_click", {"hwnd": hwnd, "timeout_ms": timeout_ms}, elevated=helper_elevated)
        if helper_result.get("ok"):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return {"ok": True, "hwnd": hwnd, "method": helper_result.get("method", "helper"), "result": helper_result.get("result"), "window": info, "helper": True, "helper_elevated": bool(helper_elevated)}
    root = info.get("root_hwnd") or hwnd
    if root:
        activate_window(int(root))
    ok, result = _send_message_timeout(hwnd, BM_CLICK, timeout_ms=timeout_ms)
    if not ok:
        post_ok = bool(user32.PostMessageW(hwnd, BM_CLICK, 0, 0))
        return {"ok": post_ok, "hwnd": hwnd, "method": "PostMessageW", "window": info}
    return {"ok": True, "hwnd": hwnd, "method": "SendMessageTimeoutW", "result": result, "window": info}


def _win32_get_item_text(hwnd: int, msg_len: int, msg_text: int, index: int, timeout_ms: int = 250) -> str:
    ok, length = _send_message_timeout(hwnd, msg_len, int(index), 0, timeout_ms=timeout_ms)
    if not ok or length == MESSAGE_RESULT_ERROR or int(length) < 0 or int(length) > 1_000_000:
        return ""
    buf = ctypes.create_unicode_buffer(int(length) + 1)
    ok, _ = _send_message_timeout(hwnd, msg_text, int(index), ctypes.addressof(buf), timeout_ms=timeout_ms)
    return buf.value if ok else ""


def _win32_notify_parent(info: Dict[str, Any], notification: int) -> bool:
    parent = int(info.get("parent_hwnd") or 0)
    control_id = int(info.get("control_id") or 0)
    hwnd = int(info.get("hwnd") or 0)
    if not parent:
        return False
    wparam = ((int(notification) & 0xFFFF) << 16) | (control_id & 0xFFFF)
    ok, _ = _send_message_timeout(parent, WM_COMMAND, wparam, hwnd, timeout_ms=500)
    if ok:
        return True
    return bool(user32.PostMessageW(parent, WM_COMMAND, wparam, hwnd))


def _win32_notify_parent_nmhdr(info: Dict[str, Any], notification: int, timeout_ms: int = 500) -> Dict[str, Any]:
    parent = int(info.get("parent_hwnd") or 0)
    control_id = int(info.get("control_id") or 0)
    hwnd = int(info.get("hwnd") or 0)
    if not parent:
        return {"ok": False, "error": "control has no parent window", "notification": int(notification)}
    header = NMHDR()
    header.hwndFrom = ctypes.c_void_p(hwnd)
    header.idFrom = ctypes.c_size_t(control_id)
    header.code = int(notification)
    try:
        with _RemoteBuffer(hwnd or parent, ctypes.sizeof(NMHDR)) as remote:
            remote.write_struct(0, header)
            ok, result = _send_message_timeout(parent, WM_NOTIFY, control_id, remote.address, timeout_ms=timeout_ms)
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "notification": int(notification),
            "parent_hwnd": parent,
            "control_id": control_id,
            "hwnd": hwnd,
        }
    return {
        "ok": bool(ok),
        "notification": int(notification),
        "parent_hwnd": parent,
        "control_id": control_id,
        "hwnd": hwnd,
        "result": int(result),
    }


def _win32_button_kind(style: int) -> str:
    low = style & 0xF
    if low in (BS_CHECKBOX, BS_AUTOCHECKBOX):
        return "checkbox"
    if low in (BS_3STATE, BS_AUTO3STATE):
        return "3state"
    if low in (BS_RADIOBUTTON, BS_AUTORADIOBUTTON):
        return "radio"
    return "button"


def _comboboxex_item(hwnd: int, index: int, timeout_ms: int = 500, max_chars: int = 512) -> Optional[Dict[str, Any]]:
    struct_size = ctypes.sizeof(COMBOBOXEXITEMW)
    text_offset = struct_size
    total = struct_size + (max_chars * ctypes.sizeof(ctypes.c_wchar))
    with _RemoteBuffer(hwnd, total) as remote:
        item = COMBOBOXEXITEMW()
        item.mask = CBEIF_TEXT | CBEIF_IMAGE | CBEIF_SELECTEDIMAGE | CBEIF_OVERLAY | CBEIF_INDENT | CBEIF_LPARAM
        item.iItem = int(index)
        item.pszText = remote.address + text_offset
        item.cchTextMax = int(max_chars)
        remote.write_struct(0, item)
        ok, result = _send_message_timeout(hwnd, CBEM_GETITEMW, 0, remote.address, timeout_ms=timeout_ms)
        if not ok or not result:
            return None
        data = remote.read_bytes(0, ctypes.sizeof(COMBOBOXEXITEMW))
        updated = COMBOBOXEXITEMW.from_buffer_copy(data)
        return {
            "index": int(index),
            "text": remote.read_wstring(text_offset, max_chars),
            "image": int(updated.iImage),
            "selected_image": int(updated.iSelectedImage),
            "overlay": int(updated.iOverlay),
            "indent": int(updated.iIndent),
            "lparam": int(updated.lParam),
        }


def _comboboxex_info(hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> Dict[str, Any]:
    ok_combo, combo_hwnd = _send_message_timeout(hwnd, CBEM_GETCOMBOCONTROL, 0, 0, timeout_ms=timeout_ms)
    ok_edit, edit_hwnd = _send_message_timeout(hwnd, CBEM_GETEDITCONTROL, 0, 0, timeout_ms=timeout_ms)
    target = int(combo_hwnd) if ok_combo and combo_hwnd else hwnd
    ok_count, count = _send_message_timeout(target, CB_GETCOUNT, timeout_ms=timeout_ms)
    ok_sel, selected = _send_message_timeout(target, CB_GETCURSEL, timeout_ms=timeout_ms)
    count = int(count) if ok_count and count != MESSAGE_RESULT_ERROR and count >= 0 else 0
    items: List[Dict[str, Any]] = []
    for i in range(min(count, max_items)):
        item = _comboboxex_item(hwnd, i, timeout_ms=timeout_ms)
        if item is None:
            item = {"index": i, "text": _win32_get_item_text(target, CB_GETLBTEXTLEN, CB_GETLBTEXT, i, timeout_ms=timeout_ms)}
        item["selected"] = bool(ok_sel and selected == i)
        items.append(item)
    return {
        "count": count,
        "selected_index": int(selected) if ok_sel and selected != MESSAGE_RESULT_ERROR else -1,
        "items": items,
        "combo_hwnd": int(combo_hwnd) if ok_combo and combo_hwnd else 0,
        "edit_hwnd": int(edit_hwnd) if ok_edit and edit_hwnd else 0,
        "combo_window": _win32_window_info(int(combo_hwnd), include_text=True) if ok_combo and combo_hwnd else None,
        "edit_window": _win32_window_info(int(edit_hwnd), include_text=True) if ok_edit and edit_hwnd else None,
    }


def _comboboxex_set_item_text(hwnd: int, index: int, text: str, timeout_ms: int = 500) -> Tuple[bool, int]:
    encoded = (str(text) + "\x00").encode("utf-16-le")
    struct_size = ctypes.sizeof(COMBOBOXEXITEMW)
    total = struct_size + len(encoded)
    with _RemoteBuffer(hwnd, total) as remote:
        item = COMBOBOXEXITEMW()
        item.mask = CBEIF_TEXT
        item.iItem = int(index)
        item.pszText = remote.address + struct_size
        item.cchTextMax = len(str(text)) + 1
        remote.write_bytes(struct_size, encoded)
        remote.write_struct(0, item)
        return _send_message_timeout(hwnd, CBEM_SETITEMW, 0, remote.address, timeout_ms=timeout_ms)


def _control_text_payload_value(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("text") or "")
    if payload is None:
        return ""
    return str(payload)


def _combobox_style_type(style: int) -> str:
    combo_type = int(style or 0) & CBS_DROPDOWNLIST
    if combo_type == CBS_SIMPLE:
        return "simple"
    if combo_type == CBS_DROPDOWN:
        return "dropdown"
    if combo_type == CBS_DROPDOWNLIST:
        return "dropdownlist"
    return "unknown"


def _combobox_style_is_editable(style: int) -> bool:
    return _combobox_style_type(style) in ("simple", "dropdown")


def _combobox_child_handles(hwnd: int) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "combo_hwnd": int(hwnd),
        "item_hwnd": 0,
        "edit_hwnd": 0,
        "list_hwnd": 0,
        "combo_info_ok": False,
    }
    try:
        info = COMBOBOXINFO()
        info.cbSize = ctypes.sizeof(COMBOBOXINFO)
        if bool(user32.GetComboBoxInfo(ctypes.c_void_p(int(hwnd)), ctypes.byref(info))):
            item_hwnd = int(info.hwndItem or 0)
            item_class = _get_class_name(item_hwnd) if item_hwnd else ""
            result.update({
                "combo_info_ok": True,
                "combo_hwnd": int(info.hwndCombo or hwnd),
                "item_hwnd": item_hwnd,
                "item_class_name": item_class,
                "edit_hwnd": item_hwnd if item_hwnd and _is_edit_class(item_class) else 0,
                "list_hwnd": int(info.hwndList or 0),
                "button_state": int(info.stateButton),
                "item_rect": _rect_to_plain_dict(info.rcItem),
                "button_rect": _rect_to_plain_dict(info.rcButton),
            })
    except Exception as e:
        result["combo_info_error"] = str(e)

    if not result.get("edit_hwnd"):
        found: Dict[str, int] = {"edit_hwnd": 0}
        CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @CALLBACK
        def callback(child_hwnd: int, _lparam: int) -> bool:
            child = int(child_hwnd)
            if _is_edit_class(_get_class_name(child)):
                found["edit_hwnd"] = child
                return False
            return True

        try:
            user32.EnumChildWindows(hwnd, callback, None)
        except Exception as e:
            result["child_enum_error"] = str(e)
        if found.get("edit_hwnd"):
            result["edit_hwnd"] = int(found["edit_hwnd"])
            if not result.get("item_hwnd"):
                result["item_hwnd"] = int(found["edit_hwnd"])
            if not result.get("item_class_name"):
                result["item_class_name"] = _get_class_name(int(found["edit_hwnd"]))
    return result


def _combobox_edit_selection(hwnd: int, edit_hwnd: int = 0, timeout_ms: int = 500) -> Dict[str, int]:
    if edit_hwnd and user32.IsWindow(edit_hwnd):
        return _edit_selection(edit_hwnd, timeout_ms=timeout_ms)
    start = ctypes.c_ulong()
    end = ctypes.c_ulong()
    ok, packed = _send_message_timeout(hwnd, CB_GETEDITSEL, ctypes.addressof(start), ctypes.addressof(end), timeout_ms=timeout_ms)
    if not ok:
        return {"start": 0, "end": 0}
    if (start.value or end.value) or not packed:
        return {"start": int(start.value), "end": int(end.value)}
    return {"start": int(packed) & 0xFFFF, "end": (int(packed) >> 16) & 0xFFFF}


def _combobox_set_edit_selection(hwnd: int, edit_hwnd: int, start: int, end: int, timeout_ms: int = 500) -> Tuple[bool, int]:
    if edit_hwnd and user32.IsWindow(edit_hwnd):
        return _edit_set_selection(edit_hwnd, start, end, timeout_ms=timeout_ms)
    packed = ((int(end) & 0xFFFF) << 16) | (int(start) & 0xFFFF)
    return _send_message_timeout(hwnd, CB_SETEDITSEL, 0, packed, timeout_ms=timeout_ms)


def _combobox_notify_edit_parent(info: Dict[str, Any]) -> Dict[str, bool]:
    return {
        "edit_update": _win32_notify_parent(info, CBN_EDITUPDATE),
        "edit_change": _win32_notify_parent(info, CBN_EDITCHANGE),
    }


def _combobox_info(hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> Dict[str, Any]:
    style = int(user32.GetWindowLongW(hwnd, GWL_STYLE))
    style_type = _combobox_style_type(style)
    handles = _combobox_child_handles(hwnd)
    edit_hwnd = int(handles.get("edit_hwnd") or 0)
    list_hwnd = int(handles.get("list_hwnd") or 0)
    ok_count, count = _send_message_timeout(hwnd, CB_GETCOUNT, timeout_ms=timeout_ms)
    ok_sel, selected = _send_message_timeout(hwnd, CB_GETCURSEL, timeout_ms=timeout_ms)
    count = int(count) if ok_count and count != MESSAGE_RESULT_ERROR and count >= 0 else 0
    selected_index = int(selected) if ok_sel and selected != MESSAGE_RESULT_ERROR else -1
    items = [_win32_get_item_text(hwnd, CB_GETLBTEXTLEN, CB_GETLBTEXT, i, timeout_ms=timeout_ms) for i in range(min(count, max_items))]
    item_details = [{"index": i, "text": item, "selected": i == selected_index} for i, item in enumerate(items)]
    edit_window = _win32_window_info(edit_hwnd, include_text=True) if edit_hwnd and user32.IsWindow(edit_hwnd) else None
    edit_state = _edit_info(edit_hwnd, timeout_ms=timeout_ms) if edit_hwnd and user32.IsWindow(edit_hwnd) else None
    combo_text = _get_control_text(hwnd, timeout_ms=timeout_ms)
    if edit_state is not None:
        current_text = _control_text_payload_value(edit_state.get("text"))
    elif edit_window is not None:
        current_text = _control_text_payload_value((edit_window or {}).get("text"))
    else:
        current_text = _control_text_payload_value(combo_text)
    selected_text = items[selected_index] if 0 <= selected_index < len(items) else ""
    return {
        "count": count,
        "selected_index": selected_index,
        "selected_text": selected_text,
        "items": items,
        "item_details": item_details,
        "combo_style": style_type,
        "editable": bool(edit_hwnd) or _combobox_style_is_editable(style),
        "current_text": current_text,
        "value": current_text,
        "text_state": combo_text,
        "combo_hwnd": int(handles.get("combo_hwnd") or hwnd),
        "item_hwnd": int(handles.get("item_hwnd") or 0),
        "edit_hwnd": edit_hwnd,
        "list_hwnd": list_hwnd,
        "combo_info_ok": bool(handles.get("combo_info_ok")),
        "button_state": handles.get("button_state"),
        "item_rect": handles.get("item_rect"),
        "button_rect": handles.get("button_rect"),
        "item_class_name": handles.get("item_class_name"),
        "edit_window": edit_window,
        "edit": edit_state,
        "edit_selection": _combobox_edit_selection(hwnd, edit_hwnd, timeout_ms=timeout_ms) if bool(edit_hwnd) or _combobox_style_is_editable(style) else None,
        "list_window": _win32_window_info(list_hwnd, include_text=False) if list_hwnd and user32.IsWindow(list_hwnd) else None,
    }


def win32_control_info(hwnd: int, timeout_ms: int = 250, max_items: int = 200) -> Dict[str, Any]:
    """Read common native control state for ComboBox/ComboBoxEx/ListBox/Button controls."""
    info = _win32_window_info(hwnd, include_text=True)
    if not info:
        return {"error": f"Window/control {hwnd} not found", "hwnd": hwnd}
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_control_info")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/win32_control_info",
            {"hwnd": hwnd, "timeout_ms": timeout_ms, "max_items": max_items},
            elevated=helper_elevated,
        )
        if "error" not in helper_result:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
    class_name = (info.get("class_name") or "").lower()
    result: Dict[str, Any] = {"hwnd": hwnd, "window": info, "kind": class_name}
    if "comboboxex32" in class_name:
        result.update({"kind": "comboboxex", **_comboboxex_info(hwnd, timeout_ms=timeout_ms, max_items=max_items)})
    elif "combobox" in class_name:
        result.update({"kind": "combobox", **_combobox_info(hwnd, timeout_ms=timeout_ms, max_items=max_items)})
    elif "listbox" in class_name:
        ok_count, count = _send_message_timeout(hwnd, LB_GETCOUNT, timeout_ms=timeout_ms)
        ok_sel, selected = _send_message_timeout(hwnd, LB_GETCURSEL, timeout_ms=timeout_ms)
        count = count if ok_count and count != MESSAGE_RESULT_ERROR and count >= 0 else 0
        items = []
        for i in range(min(count, max_items)):
            selected_ok, is_selected = _send_message_timeout(hwnd, LB_GETSEL, i, 0, timeout_ms=timeout_ms)
            item_rect = _listbox_item_rect(hwnd, i, timeout_ms=timeout_ms)
            item: Dict[str, Any] = {
                "index": i,
                "text": _win32_get_item_text(hwnd, LB_GETTEXTLEN, LB_GETTEXT, i, timeout_ms=timeout_ms),
                "selected": bool(selected_ok and is_selected > 0),
            }
            if item_rect is not None:
                item["rect"] = item_rect
                try:
                    x, y = _rect_click_point(item_rect)
                    item["point"] = {"x": int(x), "y": int(y)}
                except Exception:
                    pass
            items.append({
                **item,
            })
        result.update({"kind": "listbox", "count": count, "selected_index": selected if ok_sel and selected != MESSAGE_RESULT_ERROR else -1, "items": items})
    elif "button" in class_name:
        ok_check, checked = _send_message_timeout(hwnd, BM_GETCHECK, timeout_ms=timeout_ms)
        result.update({
            "kind": _win32_button_kind(int(info.get("style") or 0)),
            "check_state": checked if ok_check else None,
            "checked": checked == BST_CHECKED if ok_check else None,
        })
    elif class_name == "static":
        result.update({"kind": "static", **_static_info(hwnd, int(info.get("style") or 0), timeout_ms=timeout_ms)})
    elif "msctls_hotkey32" in class_name:
        result.update({"kind": "hotkey", **_hotkey_info(hwnd, timeout_ms=timeout_ms)})
    elif "syslink" in class_name:
        result.update({"kind": "syslink", **_syslink_info(hwnd, timeout_ms=timeout_ms, max_items=max_items)})
    elif _is_edit_class(class_name):
        result.update({"kind": "edit", **_edit_info(hwnd, timeout_ms=timeout_ms)})
    elif "sysheader32" in class_name:
        result.update({"kind": "header", **_header_info(hwnd, timeout_ms=timeout_ms, max_items=max_items)})
    elif class_name == "scrollbar":
        result.update({
            "kind": "scrollbar",
            "orientation": _scrollbar_orientation(int(info.get("style") or 0)),
            **_scrollbar_info(hwnd),
        })
    elif "syslistview32" in class_name:
        ok_count, count = _send_message_timeout(hwnd, LVM_GETITEMCOUNT, timeout_ms=timeout_ms)
        count = count if ok_count and count >= 0 else 0
        ok_ex_style, ex_style = _send_message_timeout(hwnd, LVM_GETEXTENDEDLISTVIEWSTYLE, 0, 0, timeout_ms=timeout_ms)
        ex_style = int(ex_style) if ok_ex_style and ex_style != MESSAGE_RESULT_ERROR else 0
        columns = _listview_columns(hwnd, timeout_ms=timeout_ms, max_columns=32)
        column_count = max(len(columns), 1)
        items = []
        has_state_images = False
        for i in range(min(count, max_items)):
            ok_state, state = _send_message_timeout(hwnd, LVM_GETITEMSTATE, i, LVIS_SELECTED | LVIS_FOCUSED | LVIS_STATEIMAGEMASK, timeout_ms=timeout_ms)
            state = int(state) if ok_state else 0
            state_image = _state_image_index(state, LVIS_STATEIMAGEMASK)
            if state_image:
                has_state_images = True
            cells = [
                {
                    "column": subitem,
                    "column_text": columns[subitem].get("text", "") if subitem < len(columns) else "",
                    "text": _listview_item_text(hwnd, i, subitem=subitem, timeout_ms=timeout_ms),
                }
                for subitem in range(column_count)
            ]
            items.append({
                "index": i,
                "text": cells[0].get("text", "") if cells else "",
                "cells": cells,
                "values": [cell.get("text", "") for cell in cells],
                "selected": bool(ok_state and (state & LVIS_SELECTED)),
                "focused": bool(ok_state and (state & LVIS_FOCUSED)),
                "checked": _checkbox_checked_from_state_image(state_image),
                "check_state": _checkbox_check_state_from_state_image(state_image),
                "state_image": state_image,
                "state": state,
            })
        ok_sel, selected = _send_message_timeout(hwnd, LVM_GETNEXTITEM, -1, LVNI_SELECTED, timeout_ms=timeout_ms)
        if ok_sel and selected == MESSAGE_RESULT_ERROR:
            selected = -1
        result.update({
            "kind": "listview",
            "count": count,
            "column_count": len(columns),
            "columns": columns,
            "selected_index": selected if ok_sel else -1,
            "extended_style": ex_style,
            "has_checkboxes": bool((ex_style & LVS_EX_CHECKBOXES) or has_state_images),
            "items": items,
        })
    elif "systreeview32" in class_name:
        ok_caret, caret = _send_message_timeout(hwnd, TVM_GETNEXTITEM, TVGN_CARET, 0, timeout_ms=timeout_ms)
        children = _treeview_children(hwnd, None, max_items, timeout_ms)
        flat = _flatten_treeview_nodes(children)
        selected = next((i for i, node in enumerate(flat) if node.get("selected")), None)
        has_state_images = any(int(node.get("state_image") or 0) > 0 for node in flat)
        result.update({
            "kind": "treeview",
            "selected_handle": caret if ok_caret else 0,
            "selected_index": selected if selected is not None else -1,
            "count": len(flat),
            "has_checkboxes": bool((int(info.get("style") or 0) & TVS_CHECKBOXES) or has_state_images),
            "nodes": children,
            "flat": flat[:max_items],
        })
    elif "systabcontrol32" in class_name:
        ok_count, count = _send_message_timeout(hwnd, TCM_GETITEMCOUNT, timeout_ms=timeout_ms)
        ok_sel, selected = _send_message_timeout(hwnd, TCM_GETCURSEL, timeout_ms=timeout_ms)
        count = count if ok_count and count >= 0 else 0
        items = [
            {"index": i, "text": _tab_item_text(hwnd, i, timeout_ms=timeout_ms), "selected": ok_sel and selected == i}
            for i in range(min(count, max_items))
        ]
        result.update({"kind": "tab", "count": count, "selected_index": selected if ok_sel else -1, "items": items})
    elif "toolbarwindow32" in class_name:
        ok_count, count = _send_message_timeout(hwnd, TB_BUTTONCOUNT, timeout_ms=timeout_ms)
        count = count if ok_count and count >= 0 else 0
        ok_tip, tooltip_hwnd = _send_message_timeout(hwnd, TB_GETTOOLTIPS, 0, 0, timeout_ms=timeout_ms)
        tooltip_hwnd = int(tooltip_hwnd) if ok_tip and tooltip_hwnd != MESSAGE_RESULT_ERROR else 0
        tooltip_by_command = _tooltip_text_map_for_owner(tooltip_hwnd, hwnd, timeout_ms=timeout_ms, max_items=max_items) if tooltip_hwnd else {}
        buttons = []
        for i in range(min(count, max_items)):
            button = _toolbar_button(hwnd, i, timeout_ms=timeout_ms)
            if button is None:
                continue
            is_separator = bool(button.fsStyle & TBSTYLE_SEP)
            text = "" if is_separator else _toolbar_button_text(hwnd, button.idCommand, timeout_ms=timeout_ms)
            tooltip_text = tooltip_by_command.get(int(button.idCommand), "")
            buttons.append({
                "index": i,
                "command_id": int(button.idCommand),
                "text": text,
                "tooltip_text": tooltip_text,
                "label": text or tooltip_text,
                "rect": _toolbar_button_rect(hwnd, i, timeout_ms=timeout_ms),
                "enabled": bool(button.fsState & TBSTATE_ENABLED),
                "checked": bool(button.fsState & TBSTATE_CHECKED),
                "pressed": bool(button.fsState & TBSTATE_PRESSED),
                "hidden": bool(button.fsState & TBSTATE_HIDDEN),
                "separator": is_separator,
                "state": int(button.fsState),
                "style": int(button.fsStyle),
            })
        result.update({"kind": "toolbar", "count": count, "tooltip_hwnd": tooltip_hwnd, "buttons": buttons, "items": buttons})
    elif "tooltips_class32" in class_name:
        tools = _tooltip_tools(hwnd, timeout_ms=timeout_ms, max_items=max_items)
        result.update({"kind": "tooltip", "count": len(tools), "tools": tools, "items": tools})
    elif "msctls_statusbar32" in class_name:
        parts = _statusbar_parts(hwnd, timeout_ms=timeout_ms, max_items=max_items)
        result.update({"kind": "statusbar", "count": len(parts), "parts": parts, "items": parts})
    elif "msctls_trackbar32" in class_name:
        ok_pos, position = _send_message_timeout(hwnd, TBM_GETPOS, timeout_ms=timeout_ms)
        ok_min, minimum = _send_message_timeout(hwnd, TBM_GETRANGEMIN, timeout_ms=timeout_ms)
        ok_max, maximum = _send_message_timeout(hwnd, TBM_GETRANGEMAX, timeout_ms=timeout_ms)
        ok_line, line_size = _send_message_timeout(hwnd, TBM_GETLINESIZE, timeout_ms=timeout_ms)
        ok_page, page_size = _send_message_timeout(hwnd, TBM_GETPAGESIZE, timeout_ms=timeout_ms)
        vertical = bool(int(info.get("style") or 0) & TBS_VERT)
        result.update({
            "kind": "trackbar",
            "position": position if ok_pos else None,
            "min": minimum if ok_min else None,
            "max": maximum if ok_max else None,
            "line_size": line_size if ok_line else None,
            "page_size": page_size if ok_page else None,
            "orientation": "vertical" if vertical else "horizontal",
        })
    elif "msctls_updown32" in class_name:
        ok_pos, position = _send_message_timeout(hwnd, UDM_GETPOS32, timeout_ms=timeout_ms)
        range_info = _updown_range(hwnd, timeout_ms=timeout_ms)
        ok_buddy, buddy = _send_message_timeout(hwnd, UDM_GETBUDDY, timeout_ms=timeout_ms)
        result.update({
            "kind": "updown",
            "position": position if ok_pos else None,
            "min": range_info.get("min"),
            "max": range_info.get("max"),
            "buddy_hwnd": buddy if ok_buddy else 0,
        })
    elif "msctls_progress32" in class_name:
        ok_pos, position = _send_message_timeout(hwnd, PBM_GETPOS, timeout_ms=timeout_ms)
        range_info = _progress_range(hwnd, timeout_ms=timeout_ms)
        result.update({
            "kind": "progress",
            "position": position if ok_pos else None,
            "min": range_info.get("min"),
            "max": range_info.get("max"),
        })
    elif "sysdatetimepick32" in class_name:
        time_info = _get_systemtime_control(hwnd, DTM_GETSYSTEMTIME, timeout_ms=timeout_ms, datetime_result=True)
        result.update({"kind": "datetime", **time_info})
    elif "sysmonthcal32" in class_name:
        time_info = _get_systemtime_control(hwnd, MCM_GETCURSEL, timeout_ms=timeout_ms, datetime_result=False)
        result.update({"kind": "monthcal", **time_info})
    elif "sysipaddress32" in class_name:
        result.update({"kind": "ipaddress", **_ip_address_info(hwnd, timeout_ms=timeout_ms)})
    elif _is_richedit_class(class_name):
        result.update({"kind": "richedit", **_richedit_info(hwnd, timeout_ms=timeout_ms)})
    return result


def _find_item_index(items: List[Any], text: Optional[str], match: str = "contains") -> Optional[int]:
    if text is None:
        return None
    needle = str(text).lower()
    for i, item in enumerate(items):
        if isinstance(item, dict):
            values = [
                item.get("text", ""),
                item.get("label", ""),
                item.get("tooltip_text", ""),
                item.get("name", ""),
                item.get("title", ""),
                item.get("value", ""),
                item.get("current_text", ""),
            ]
            item_values = item.get("values")
            if isinstance(item_values, (list, tuple)):
                values.extend(item_values)
            cells = item.get("cells")
            if isinstance(cells, list):
                for cell in cells:
                    if isinstance(cell, dict):
                        values.extend([cell.get("text", ""), cell.get("value", "")])
        else:
            values = [str(item)]
        for value in values:
            candidate = str(value or "").lower()
            if not candidate:
                continue
            if match == "exact" and candidate == needle:
                return i
            if match != "exact" and needle in candidate:
                return i
    return None


_WIN32_WAIT_STATE_ALIASES = {
    "check": "checked",
    "is_checked": "checked",
    "checked_state": "check_state",
    "state_image_check": "check_state",
    "selection": "selected",
    "is_selected": "selected",
    "selected_item": "selected",
    "selectedindex": "selected_index",
    "selected_index": "selected_index",
    "index": "selected_index",
    "selectedtext": "selected_text",
    "selection_text": "selected_text",
    "text_selection": "selected_text",
    "selected_range_text": "selected_text",
    "selection_start": "selection_start",
    "selectionstart": "selection_start",
    "sel_start": "selection_start",
    "start": "selection_start",
    "selection_end": "selection_end",
    "selectionend": "selection_end",
    "sel_end": "selection_end",
    "end": "selection_end",
    "caret": "selection_end",
    "caret_position": "selection_end",
    "cursor": "selection_end",
    "cursor_position": "selection_end",
    "selection_length": "selection_length",
    "selectionlength": "selection_length",
    "selection_len": "selection_length",
    "selected_length": "selection_length",
    "exist": "present",
    "exists": "present",
    "is_present": "present",
    "item_present": "present",
    "item_exists": "present",
    "has_item": "present",
    "absent": "absent",
    "missing": "absent",
    "gone": "absent",
    "not_present": "absent",
    "not_exists": "absent",
    "does_not_exist": "absent",
    "item_absent": "absent",
    "item_missing": "absent",
    "expanded_state": "expanded",
    "is_expanded": "expanded",
    "visit": "visited",
    "is_visited": "visited",
    "pos": "position",
    "range_value": "position",
    "hotkey": "value",
    "caption": "text",
    "label": "text",
}

_WIN32_WAIT_BOOL_STATES = {"checked", "selected", "expanded", "visited", "enabled", "pressed", "hidden", "focused", "present", "absent"}
_WIN32_WAIT_TEXT_STATES = {"text", "value", "label", "tooltip_text", "current_text", "selected_text", "date", "datetime", "time", "hotkey"}
_WIN32_WAIT_NUMERIC_STATES = {"selected_index", "position", "min", "max", "count", "state_image", "state", "selection_start", "selection_end", "selection_length"}


def _normalize_win32_wait_state(state: Optional[Any]) -> str:
    text = str(state or "checked").strip().lower().replace("-", "_").replace(" ", "_")
    return _WIN32_WAIT_STATE_ALIASES.get(text, text)


def _coerce_win32_wait_expected(state: str, expected: Any) -> Any:
    if expected is None and state in _WIN32_WAIT_BOOL_STATES:
        return True
    if state in _WIN32_WAIT_BOOL_STATES:
        return _coerce_bool(expected, False)
    if state in _WIN32_WAIT_NUMERIC_STATES and expected is not None:
        try:
            return int(expected)
        except Exception:
            try:
                return float(expected)
            except Exception:
                return expected
    if state == "check_state" and expected is not None:
        text = str(expected).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "true": "checked",
            "yes": "checked",
            "on": "checked",
            "1": "checked",
            "false": "unchecked",
            "no": "unchecked",
            "off": "unchecked",
            "0": "unchecked",
            "none": "none",
            "unknown": "unknown",
            "mixed": "indeterminate",
            "partial": "indeterminate",
        }
        return aliases.get(text, text)
    return expected


def _win32_item_text_values(item: Any) -> List[str]:
    if isinstance(item, dict):
        values = [
            item.get("text", ""),
            item.get("label", ""),
            item.get("tooltip_text", ""),
            item.get("name", ""),
            item.get("title", ""),
            item.get("value", ""),
            item.get("current_text", ""),
        ]
        item_values = item.get("values")
        if isinstance(item_values, (list, tuple)):
            values.extend(str(value or "") for value in item_values)
        cells = item.get("cells")
        if isinstance(cells, list):
            for cell in cells:
                if isinstance(cell, dict):
                    values.extend([cell.get("text", ""), cell.get("value", "")])
        return [str(value) for value in values if value not in (None, "")]
    return [str(item)] if item not in (None, "") else []


def _win32_control_wait_items(info: Dict[str, Any]) -> List[Any]:
    kind = str(info.get("kind") or "").lower()
    if kind == "treeview":
        return list(info.get("flat") or [])
    if kind == "toolbar":
        return list(info.get("buttons") or info.get("items") or [])
    if kind == "syslink":
        return list(info.get("links") or info.get("items") or [])
    for key in ("items", "parts", "tools", "columns"):
        values = info.get(key)
        if isinstance(values, list):
            return values
    return []


def _win32_control_wait_target(
    info: Dict[str, Any],
    *,
    index: Optional[int] = None,
    text: Optional[str] = None,
    match: str = "contains",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    items = _win32_control_wait_items(info)
    target_index = index
    if target_index is None and text is not None:
        target_index = _find_item_index(items, text, match=match)
    if target_index is not None:
        try:
            idx = int(target_index)
        except Exception:
            return None, "index must be an integer"
        if idx < 0 or idx >= len(items):
            return None, f"index {idx} out of range"
        item = items[idx]
        if isinstance(item, dict):
            target = dict(item)
        else:
            target = {"index": idx, "text": item}
        target.setdefault("index", idx)
        return target, None
    if text is not None and items:
        return None, f"text not found: {text}"
    return dict(info), None


def _win32_control_wait_state_value(target: Dict[str, Any], info: Dict[str, Any], state: str) -> Any:
    if state == "selected_index":
        return info.get("selected_index")
    if state in ("selected_text", "selection_start", "selection_end", "selection_length"):
        selection = target.get("selection") if isinstance(target.get("selection"), dict) else None
        if selection is None and isinstance(info.get("selection"), dict):
            selection = info.get("selection")
        selected_text = target.get("selected_text")
        if selected_text is None:
            selected_text = info.get("selected_text")
        if state == "selected_text":
            if selected_text is not None:
                return selected_text
            if selection is not None:
                text_value = target.get("text")
                if isinstance(text_value, dict):
                    text_value = text_value.get("text")
                if text_value is None:
                    text_value = info.get("text")
                    if isinstance(text_value, dict):
                        text_value = text_value.get("text")
                if text_value is not None:
                    start = max(int(selection.get("start", 0) or 0), 0)
                    end = max(int(selection.get("end", start) or start), start)
                    return str(text_value)[start:end]
            return None
        if selection is None:
            return None
        start = int(selection.get("start", 0) or 0)
        end = int(selection.get("end", start) or start)
        if state == "selection_start":
            return start
        if state == "selection_end":
            return end
        return max(0, end - start)
    if state == "text":
        if target.get("current_text") is not None:
            return target.get("current_text")
        values = _win32_item_text_values(target)
        if values:
            return values[0]
        text_value = target.get("text")
        if isinstance(text_value, dict):
            return text_value.get("text")
        if text_value is not None:
            return text_value
        window = info.get("window") if isinstance(info.get("window"), dict) else {}
        window_text = window.get("text")
        if isinstance(window_text, dict):
            return window_text.get("text")
        return window_text
    if state in target:
        return target.get(state)
    if state == "value":
        if target.get("value") is not None:
            return target.get("value")
        if target.get("hotkey") is not None:
            return target.get("hotkey")
        if target.get("date") is not None:
            return target.get("date")
        if target.get("datetime") is not None:
            return target.get("datetime")
        if target.get("text") is not None:
            return target.get("text")
    return info.get(state)


def _win32_control_wait_presence_target(
    info: Dict[str, Any],
    *,
    index: Optional[int] = None,
    text: Optional[str] = None,
    match: str = "contains",
) -> Tuple[Optional[Dict[str, Any]], bool, Optional[str]]:
    items = _win32_control_wait_items(info)
    if index is not None:
        try:
            idx = int(index)
        except Exception:
            return None, False, "index must be an integer"
        if 0 <= idx < len(items):
            item = items[idx]
            target = dict(item) if isinstance(item, dict) else {"index": idx, "text": item}
            target.setdefault("index", idx)
            return target, True, None
        return {"index": idx}, False, None

    if text is not None:
        if items:
            found_index = _find_item_index(items, text, match=match)
            if found_index is not None:
                item = items[int(found_index)]
                target = dict(item) if isinstance(item, dict) else {"index": int(found_index), "text": item}
                target.setdefault("index", int(found_index))
                return target, True, None
            return {"text": text}, False, None
        values = _win32_item_text_values(info)
        for state_name in ("text", "value"):
            value = _win32_control_wait_state_value(info, info, state_name)
            if value not in (None, ""):
                values.append(str(value))
        window = info.get("window") if isinstance(info.get("window"), dict) else {}
        for key in ("title", "text", "name", "class_name"):
            value = window.get(key)
            if isinstance(value, dict):
                value = value.get("text")
            if value not in (None, ""):
                values.append(str(value))
        present = any(_matches_text(str(value or ""), str(text), match) for value in values)
        return dict(info) if present else {"text": text}, bool(present), None

    return dict(info), True, None


def _win32_control_wait_match(actual: Any, expected: Any, state: str, match: str = "contains") -> bool:
    if state in _WIN32_WAIT_BOOL_STATES:
        return _coerce_bool(actual, False) is _coerce_bool(expected, False)
    if state in _WIN32_WAIT_NUMERIC_STATES:
        try:
            return float(actual) == float(expected)
        except Exception:
            return str(actual) == str(expected)
    if state == "check_state":
        actual_norm = _coerce_win32_wait_expected(state, actual)
        expected_norm = _coerce_win32_wait_expected(state, expected)
        return str(actual_norm) == str(expected_norm)
    if state in _WIN32_WAIT_TEXT_STATES or isinstance(expected, str):
        return _matches_text(str(actual or ""), str(expected or ""), match)
    return actual == expected


def _win32_control_wait_item_preview(info: Dict[str, Any], limit: int = 8) -> List[Dict[str, Any]]:
    preview: List[Dict[str, Any]] = []
    for ordinal, item in enumerate(_win32_control_wait_items(info)[: max(int(limit or 0), 0)]):
        if isinstance(item, dict):
            values = _win32_item_text_values(item)
            entry = {
                "index": item.get("index", ordinal),
                "text": values[0] if values else None,
                "values": values[:4] if len(values) > 1 else None,
                "selected": item.get("selected"),
                "checked": item.get("checked"),
                "state": item.get("state"),
                "check_state": item.get("check_state"),
            }
        else:
            entry = {"index": ordinal, "text": str(item)}
        preview.append({key: value for key, value in entry.items() if value not in (None, "", [], {})})
    return preview


def _win32_control_wait_failure_summary(
    last_result: Dict[str, Any],
    *,
    state: Optional[Any] = None,
    expected: Any = None,
    index: Optional[int] = None,
    text: Optional[str] = None,
    match: str = "contains",
) -> Dict[str, Any]:
    if not isinstance(last_result, dict):
        return {}
    normalized_state = _normalize_win32_wait_state(state or last_result.get("state"))
    info = last_result.get("info") if isinstance(last_result.get("info"), dict) else {}
    window = info.get("window") if isinstance(info.get("window"), dict) else {}
    items = _win32_control_wait_items(info)
    expected_value = last_result.get("expected")
    if expected_value is None:
        expected_value = _coerce_win32_wait_expected(normalized_state, expected)
    recommendations: List[str] = []
    if normalized_state == "present" and text is not None and not last_result.get("present"):
        recommendations.append("relax match, verify item text/case, or run win32_control_info to inspect available native item text")
    if normalized_state == "absent" and last_result.get("present"):
        recommendations.append("wait longer or verify the absent selector is not matching the still-present item")
    if text is not None and not items:
        recommendations.append("this control did not expose a native item collection; presence was checked against control/window text")
    if index is not None and items:
        recommendations.append("check the item index against the latest native item count before retrying")
    repair_suggestions: List[Dict[str, Any]] = []
    match_key = str(match or "contains").strip().lower().replace("-", "_")
    target_missing = not isinstance(last_result.get("target"), dict) or not last_result.get("target")
    text_lookup_failed = (
        (normalized_state == "present" and last_result.get("present") is False)
        or (target_missing and "text not found" in str(last_result.get("error") or "").lower())
    )
    if text is not None and normalized_state != "absent" and match_key == "exact" and text_lookup_failed:
        repair_suggestions.append({
            "state": normalized_state,
            "expected": expected_value,
            "text": text,
            "match": "contains",
            "reason": "same target text with relaxed contains match",
        })
    summary = {
        "state": normalized_state,
        "expected": expected_value,
        "actual": last_result.get("actual"),
        "present": last_result.get("present"),
        "target": last_result.get("target"),
        "target_text": text,
        "target_index": index,
        "match": match,
        "kind": info.get("kind"),
        "class_name": window.get("class_name") or info.get("class_name"),
        "control_id": window.get("control_id") or info.get("control_id"),
        "item_count": len(items),
        "reported_count": info.get("count"),
        "max_items": info.get("max_items"),
        "item_preview": _win32_control_wait_item_preview(info),
        "repair_suggestions": repair_suggestions,
        "recommendations": recommendations,
    }
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _win32_control_wait_once(
    hwnd: int,
    *,
    state: Optional[Any] = None,
    expected: Any = None,
    index: Optional[int] = None,
    text: Optional[str] = None,
    match: str = "contains",
    timeout_ms: int = 250,
    max_items: int = 200,
) -> Dict[str, Any]:
    normalized_state = _normalize_win32_wait_state(state)
    normalized_expected = _coerce_win32_wait_expected(normalized_state, expected)
    info = win32_control_info(hwnd, timeout_ms=timeout_ms, max_items=max_items)
    if "error" in info:
        return {"ok": False, "error": info.get("error"), "state": normalized_state, "expected": normalized_expected, "info": info}
    if normalized_state in ("present", "absent"):
        target, present, presence_error = _win32_control_wait_presence_target(info, index=index, text=text, match=match)
        if presence_error:
            return {"ok": False, "error": presence_error, "state": normalized_state, "expected": normalized_expected, "info": info}
        actual = bool(present) if normalized_state == "present" else not bool(present)
        matched = _win32_control_wait_match(actual, normalized_expected, normalized_state, match=match)
        return {
            "ok": bool(matched),
            "matched": bool(matched),
            "state": normalized_state,
            "expected": normalized_expected,
            "actual": actual,
            "present": bool(present),
            "target": target or {},
            "info": info,
        }
    target, target_error = _win32_control_wait_target(info, index=index, text=text, match=match)
    if target_error:
        return {"ok": False, "error": target_error, "state": normalized_state, "expected": normalized_expected, "info": info}
    target = target or {}
    actual = _win32_control_wait_state_value(target, info, normalized_state)
    if actual is None and normalized_state not in target and normalized_state not in info:
        return {
            "ok": False,
            "error": f"state '{normalized_state}' is not available for {info.get('kind')}",
            "state": normalized_state,
            "expected": normalized_expected,
            "actual": actual,
            "target": target,
            "info": info,
        }
    matched = _win32_control_wait_match(actual, normalized_expected, normalized_state, match=match)
    return {
        "ok": bool(matched),
        "matched": bool(matched),
        "state": normalized_state,
        "expected": normalized_expected,
        "actual": actual,
        "target": target,
        "info": info,
    }


def _win32_control_wait_poll(
    hwnd: int,
    *,
    state: Optional[Any] = None,
    expected: Any = None,
    index: Optional[int] = None,
    text: Optional[str] = None,
    match: str = "contains",
    timeout: float = 3.0,
    interval: float = 0.1,
    timeout_ms: int = 250,
    max_items: int = 200,
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
        last_result = _win32_control_wait_once(
            hwnd,
            state=state,
            expected=expected,
            index=index,
            text=text,
            match=match,
            timeout_ms=timeout_ms,
            max_items=max_items,
        )
        if last_result.get("matched"):
            result = dict(last_result)
            result.update({"ok": True, "attempts": attempts, "elapsed": time.time() - started})
            return result
        if last_result.get("error") and not str(last_result.get("error")).startswith("state '"):
            if time.time() - started >= timeout_value:
                break
        elif time.time() - started >= timeout_value:
            break
        time.sleep(interval_value)
    result = {
        "ok": False,
        "matched": False,
        "error": "timeout",
        "hwnd": hwnd,
        "state": _normalize_win32_wait_state(state),
        "expected": _coerce_win32_wait_expected(_normalize_win32_wait_state(state), expected),
        "attempts": attempts,
        "elapsed": time.time() - started,
        "last_result": last_result if diagnostic else {
            key: last_result.get(key)
            for key in ("error", "state", "expected", "actual", "present", "target")
            if key in last_result
        },
    }
    failure_summary = _win32_control_wait_failure_summary(
        last_result,
        state=state,
        expected=expected,
        index=index,
        text=text,
        match=match,
    )
    if failure_summary:
        result["failure_summary"] = failure_summary
    return result


def _win32_control_wait_repair_timeout(repair_timeout: Optional[float], timeout: float) -> float:
    if repair_timeout is not None:
        try:
            return max(float(repair_timeout), 0.0)
        except Exception:
            return 0.0
    try:
        return min(max(float(timeout), 0.0), 1.0)
    except Exception:
        return 1.0


def _win32_control_wait_maybe_repair(
    result: Dict[str, Any],
    hwnd: int,
    *,
    state: Optional[Any] = None,
    expected: Any = None,
    index: Optional[int] = None,
    text: Optional[str] = None,
    match: str = "contains",
    timeout: float = 3.0,
    interval: float = 0.1,
    timeout_ms: int = 250,
    max_items: int = 200,
    diagnostic: bool = False,
    repair: Optional[bool] = None,
    repair_match: str = "contains",
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if result.get("matched") or not _win32_repair_requested(repair, repair_match, repair_timeout):
        return result
    failure_summary = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
    suggestions = failure_summary.get("repair_suggestions") if isinstance(failure_summary.get("repair_suggestions"), list) else []
    suggestion = next((item for item in suggestions if isinstance(item, dict) and item.get("match")), None)
    if not suggestion:
        return result
    repair_match_value = str(repair_match or suggestion.get("match") or "contains").strip().lower().replace("-", "_") or "contains"
    original_match = str(match or "contains").strip().lower().replace("-", "_") or "contains"
    if repair_match_value == original_match:
        return result
    repair_timeout_value = _win32_control_wait_repair_timeout(repair_timeout, timeout)
    repair_result = _win32_control_wait_poll(
        hwnd,
        state=state,
        expected=expected,
        index=index,
        text=text,
        match=repair_match_value,
        timeout=repair_timeout_value,
        interval=interval,
        timeout_ms=timeout_ms,
        max_items=max_items,
        diagnostic=True if diagnostic else False,
    )
    repair_info = {
        "attempted": True,
        "ok": bool(repair_result.get("matched")),
        "original_match": original_match,
        "match": repair_match_value,
        "timeout": repair_timeout_value,
        "reason": suggestion.get("reason"),
    }
    if repair_result.get("matched"):
        repaired = dict(repair_result)
        repaired["repaired"] = True
        repaired["repair"] = repair_info
        repaired["original_failure_summary"] = failure_summary
        return repaired
    updated = dict(result)
    updated["repair"] = {
        **repair_info,
        "result": {
            key: repair_result.get(key)
            for key in ("ok", "matched", "error", "state", "expected", "actual", "present", "attempts", "elapsed", "failure_summary")
            if repair_result.get(key) not in (None, "", [], {})
        },
    }
    return updated


def win32_control_wait(
    hwnd: int,
    state: Optional[Any] = None,
    expected: Any = None,
    index: Optional[int] = None,
    text: Optional[str] = None,
    match: str = "contains",
    timeout: float = 3.0,
    interval: float = 0.1,
    timeout_ms: int = 250,
    max_items: int = 200,
    diagnostic: bool = False,
    repair: Optional[bool] = None,
    repair_match: Optional[str] = None,
    repair_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Poll native Win32 control state until it matches the expected value."""
    repair_enabled = _win32_repair_requested(repair, repair_match, repair_timeout)
    resolved_repair_match = repair_match or "contains"
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_control_wait")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/win32_control_wait",
            {
                "hwnd": hwnd,
                "state": state,
                "expected": expected,
                "index": index,
                "text": text,
                "match": match,
                "timeout": timeout,
                "interval": interval,
                "timeout_ms": timeout_ms,
                "max_items": max_items,
                "diagnostic": diagnostic,
                "repair": repair_enabled,
                "repair_match": resolved_repair_match,
                "repair_timeout": repair_timeout,
            },
            elevated=helper_elevated,
            timeout=max(
                float(timeout or 0)
                + (_win32_control_wait_repair_timeout(repair_timeout, timeout) if repair_enabled else 0.0)
                + 1.0,
                2.0,
            ),
        )
        if _helper_ok(helper_result) or helper_result.get("matched") is True:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
        if helper_result.get("error") is not None:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result

    result = _win32_control_wait_poll(
        hwnd,
        state=state,
        expected=expected,
        index=index,
        text=text,
        match=match,
        timeout=timeout,
        interval=interval,
        timeout_ms=timeout_ms,
        max_items=max_items,
        diagnostic=diagnostic,
    )
    return _win32_control_wait_maybe_repair(
        result,
        hwnd,
        state=state,
        expected=expected,
        index=index,
        text=text,
        match=match,
        timeout=timeout,
        interval=interval,
        timeout_ms=timeout_ms,
        max_items=max_items,
        diagnostic=diagnostic,
        repair=repair_enabled,
        repair_match=resolved_repair_match,
        repair_timeout=repair_timeout,
    )


def _init_common_controls() -> bool:
    if comctl32 is None:
        return False
    try:
        icc = INITCOMMONCONTROLSEX()
        icc.dwSize = ctypes.sizeof(INITCOMMONCONTROLSEX)
        icc.dwICC = (
            ICC_LISTVIEW_CLASSES
            | ICC_TREEVIEW_CLASSES
            | ICC_TAB_CLASSES
            | ICC_BAR_CLASSES
            | ICC_UPDOWN_CLASS
            | ICC_PROGRESS_CLASS
            | ICC_DATE_CLASSES
            | ICC_INTERNET_CLASSES
            | ICC_HOTKEY_CLASS
            | ICC_LINK_CLASS
            | ICC_USEREX_CLASSES
        )
        return bool(comctl32.InitCommonControlsEx(ctypes.byref(icc)))
    except Exception:
        try:
            comctl32.InitCommonControls()
            return True
        except Exception:
            return False


class _RemoteBuffer:
    def __init__(self, hwnd: int, size: int):
        self.hwnd = int(hwnd)
        self.size = max(int(size), 1)
        self.process = 0
        self.address = 0

    def __enter__(self):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        self.process = int(kernel32.OpenProcess(
            PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid.value,
        ) or 0)
        if not self.process:
            raise RuntimeError(f"OpenProcess failed for pid {pid.value}")
        self.address = int(kernel32.VirtualAllocEx(
            self.process,
            None,
            self.size,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_READWRITE,
        ) or 0)
        if not self.address:
            raise RuntimeError("VirtualAllocEx failed")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.address and self.process:
            try:
                kernel32.VirtualFreeEx(self.process, ctypes.c_void_p(self.address), 0, MEM_RELEASE)
            except Exception:
                pass
        if self.process:
            try:
                kernel32.CloseHandle(self.process)
            except Exception:
                pass

    def write_bytes(self, offset: int, data: bytes) -> None:
        written = ctypes.c_size_t()
        buf = ctypes.create_string_buffer(data)
        if not kernel32.WriteProcessMemory(
            self.process,
            ctypes.c_void_p(self.address + int(offset)),
            buf,
            len(data),
            ctypes.byref(written),
        ):
            raise RuntimeError("WriteProcessMemory failed")

    def write_struct(self, offset: int, struct_value: ctypes.Structure) -> None:
        self.write_bytes(offset, ctypes.string_at(ctypes.byref(struct_value), ctypes.sizeof(struct_value)))

    def read_bytes(self, offset: int, size: int) -> bytes:
        read = ctypes.c_size_t()
        buf = ctypes.create_string_buffer(size)
        if not kernel32.ReadProcessMemory(
            self.process,
            ctypes.c_void_p(self.address + int(offset)),
            buf,
            int(size),
            ctypes.byref(read),
        ):
            raise RuntimeError("ReadProcessMemory failed")
        return bytes(buf.raw[: int(read.value)])

    def read_wstring(self, offset: int, max_chars: int) -> str:
        data = self.read_bytes(offset, max_chars * ctypes.sizeof(ctypes.c_wchar))
        return data.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]


def _listview_item_text(hwnd: int, index: int, subitem: int = 0, timeout_ms: int = 500, max_chars: int = 512) -> str:
    struct_size = ctypes.sizeof(LVITEMW)
    text_offset = struct_size
    total = struct_size + (max_chars * ctypes.sizeof(ctypes.c_wchar))
    with _RemoteBuffer(hwnd, total) as remote:
        item = LVITEMW()
        item.mask = LVIF_TEXT
        item.iItem = int(index)
        item.iSubItem = int(subitem)
        item.pszText = remote.address + text_offset
        item.cchTextMax = int(max_chars)
        remote.write_struct(0, item)
        ok, _ = _send_message_timeout(hwnd, LVM_GETITEMTEXTW, int(index), remote.address, timeout_ms=timeout_ms)
        if not ok:
            return ""
        return remote.read_wstring(text_offset, max_chars)


def _make_lparam(x: int, y: int) -> int:
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def _rect_click_point(rect: Dict[str, Any]) -> Tuple[int, int]:
    left = int(rect.get("left", 0))
    right = int(rect.get("right", left))
    top = int(rect.get("top", 0))
    bottom = int(rect.get("bottom", top))
    if right <= left or bottom <= top:
        raise ValueError("empty item rectangle")
    x = max(left, min((left + right) // 2, right - 1))
    y = max(top, min((top + bottom) // 2, bottom - 1))
    return x, y


def _send_client_click_sequence(hwnd: int, x: int, y: int, clicks: int = 2, timeout_ms: int = 500) -> Dict[str, Any]:
    lparam = _make_lparam(x, y)
    sequence: List[Tuple[str, int, int]] = [
        ("WM_LBUTTONDOWN", WM_LBUTTONDOWN, MK_LBUTTON),
        ("WM_LBUTTONUP", WM_LBUTTONUP, 0),
    ]
    if int(clicks) >= 2:
        sequence.extend([
            ("WM_LBUTTONDBLCLK", WM_LBUTTONDBLCLK, MK_LBUTTON),
            ("WM_LBUTTONUP", WM_LBUTTONUP, 0),
        ])
    messages = []
    ok_all = True
    for name, message, wparam in sequence:
        ok = bool(user32.PostMessageW(hwnd, message, int(wparam), int(lparam)))
        ok_all = bool(ok_all and ok)
        messages.append({
            "name": name,
            "message": hex(message),
            "wparam": int(wparam),
            "lparam": int(lparam),
            "ok": bool(ok),
            "method": "PostMessageW",
        })
    target_thread = int(user32.GetWindowThreadProcessId(hwnd, None))
    current_thread = int(kernel32.GetCurrentThreadId())
    pumped = False
    if target_thread and target_thread == current_thread:
        _pump_wait(lambda: False, timeout=min(max(float(timeout_ms) / 1000.0, 0.02), 0.2), interval=0.005)
        pumped = True
    else:
        time.sleep(min(max(float(timeout_ms) / 1000.0, 0.01), 0.03))
    return {
        "ok": ok_all,
        "x": int(x),
        "y": int(y),
        "lparam": int(lparam),
        "clicks": 2 if int(clicks) >= 2 else 1,
        "method": "PostMessageW",
        "pumped_current_thread": pumped,
        "messages": messages,
    }


def _listview_item_rect(hwnd: int, index: int, part: int = LVIR_LABEL, timeout_ms: int = 500) -> Optional[Dict[str, int]]:
    rect = ctypes.wintypes.RECT()
    rect.left = int(part)
    with _RemoteBuffer(hwnd, ctypes.sizeof(ctypes.wintypes.RECT)) as remote:
        remote.write_struct(0, rect)
        ok, result = _send_message_timeout(hwnd, LVM_GETITEMRECT, int(index), remote.address, timeout_ms=timeout_ms)
        if not ok or not result:
            return None
        data = remote.read_bytes(0, ctypes.sizeof(ctypes.wintypes.RECT))
        updated = ctypes.wintypes.RECT.from_buffer_copy(data)
    if updated.right <= updated.left or updated.bottom <= updated.top:
        return None
    return _rect_to_plain_dict(updated)


def _listbox_item_rect(hwnd: int, index: int, timeout_ms: int = 500) -> Optional[Dict[str, int]]:
    rect = ctypes.wintypes.RECT()
    ok, result = _send_message_timeout(hwnd, LB_GETITEMRECT, int(index), ctypes.addressof(rect), timeout_ms=timeout_ms)
    if not ok or result == MESSAGE_RESULT_ERROR:
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return _rect_to_plain_dict(rect)


def _listbox_activate_item(hwnd: int, index: int, info: Dict[str, Any], timeout_ms: int = 500) -> Dict[str, Any]:
    ok_select, select_result = _send_message_timeout(hwnd, LB_SETCURSEL, int(index), 0, timeout_ms=timeout_ms)
    selection_notified = _win32_notify_parent(info, LBN_SELCHANGE)
    rect = _listbox_item_rect(hwnd, int(index), timeout_ms=timeout_ms)
    if rect is None:
        return {
            "ok": False,
            "index": int(index),
            "error": "could not read ListBox item rectangle",
            "select_ok": bool(ok_select),
            "select_result": int(select_result),
            "selection_notified_parent": bool(selection_notified),
        }
    x, y = _rect_click_point(rect)
    click = _send_client_click_sequence(hwnd, x, y, clicks=2, timeout_ms=timeout_ms)
    double_click_notified = _win32_notify_parent(info, LBN_DBLCLK)
    return {
        "ok": bool(ok_select and select_result != MESSAGE_RESULT_ERROR and click.get("ok") and double_click_notified),
        "index": int(index),
        "select_ok": bool(ok_select),
        "select_result": int(select_result),
        "selection_notified_parent": bool(selection_notified),
        "double_click_notified_parent": bool(double_click_notified),
        "rect": rect,
        "point": {"x": int(x), "y": int(y)},
        "click": click,
    }


def _listview_activate_item(hwnd: int, index: int, timeout_ms: int = 500) -> Dict[str, Any]:
    ok_select, select_result = _listview_set_item_state(
        hwnd,
        int(index),
        LVIS_SELECTED | LVIS_FOCUSED,
        LVIS_SELECTED | LVIS_FOCUSED,
        timeout_ms=timeout_ms,
    )
    ok_visible, visible_result = _send_message_timeout(hwnd, LVM_ENSUREVISIBLE, int(index), 0, timeout_ms=timeout_ms)
    rect = _listview_item_rect(hwnd, int(index), part=LVIR_LABEL, timeout_ms=timeout_ms)
    rect_part = "label"
    if rect is None:
        rect = _listview_item_rect(hwnd, int(index), part=LVIR_BOUNDS, timeout_ms=timeout_ms)
        rect_part = "bounds"
    if rect is None:
        return {
            "ok": False,
            "index": int(index),
            "error": "could not read ListView item rectangle",
            "select_ok": bool(ok_select),
            "select_result": int(select_result),
            "ensure_visible_ok": bool(ok_visible),
            "ensure_visible_result": int(visible_result),
        }
    x, y = _rect_click_point(rect)
    click = _send_client_click_sequence(hwnd, x, y, clicks=2, timeout_ms=timeout_ms)
    ok_reselect, reselect_result = _listview_set_item_state(
        hwnd,
        int(index),
        LVIS_SELECTED | LVIS_FOCUSED,
        LVIS_SELECTED | LVIS_FOCUSED,
        timeout_ms=timeout_ms,
    )
    return {
        "ok": bool(ok_select and ok_visible and click.get("ok") and ok_reselect),
        "index": int(index),
        "select_ok": bool(ok_select),
        "select_result": int(select_result),
        "ensure_visible_ok": bool(ok_visible),
        "ensure_visible_result": int(visible_result),
        "reselect_ok": bool(ok_reselect),
        "reselect_result": int(reselect_result),
        "rect_part": rect_part,
        "rect": rect,
        "point": {"x": int(x), "y": int(y)},
        "click": click,
    }


def _listview_column_text(hwnd: int, index: int, timeout_ms: int = 500, max_chars: int = 512) -> Optional[Dict[str, Any]]:
    struct_size = ctypes.sizeof(LVCOLUMNW)
    text_offset = struct_size
    total = struct_size + (max_chars * ctypes.sizeof(ctypes.c_wchar))
    with _RemoteBuffer(hwnd, total) as remote:
        column = LVCOLUMNW()
        column.mask = LVCF_TEXT | LVCF_WIDTH | LVCF_FMT | LVCF_SUBITEM
        column.pszText = remote.address + text_offset
        column.cchTextMax = int(max_chars)
        remote.write_struct(0, column)
        ok, result = _send_message_timeout(hwnd, LVM_GETCOLUMNW, int(index), remote.address, timeout_ms=timeout_ms)
        if not ok or not result:
            return None
        data = remote.read_bytes(0, ctypes.sizeof(LVCOLUMNW))
        updated = LVCOLUMNW.from_buffer_copy(data)
        ok_width, width = _send_message_timeout(hwnd, LVM_GETCOLUMNWIDTH, int(index), 0, timeout_ms=timeout_ms)
        return {
            "index": int(index),
            "text": remote.read_wstring(text_offset, max_chars),
            "width": int(width) if ok_width and width != MESSAGE_RESULT_ERROR else int(updated.cx),
            "format": int(updated.fmt),
            "subitem": int(updated.iSubItem),
        }


def _listview_columns(hwnd: int, timeout_ms: int = 500, max_columns: int = 32) -> List[Dict[str, Any]]:
    ok_header, header = _send_message_timeout(hwnd, LVM_GETHEADER, 0, 0, timeout_ms=timeout_ms)
    count = 0
    if ok_header and header:
        ok_count, header_count = _send_message_timeout(int(header), HDM_GETITEMCOUNT, 0, 0, timeout_ms=timeout_ms)
        if ok_count and header_count > 0:
            count = int(header_count)
    columns: List[Dict[str, Any]] = []
    probe_limit = max(1, min(max_columns, count if count > 0 else max_columns))
    for i in range(probe_limit):
        column = _listview_column_text(hwnd, i, timeout_ms=timeout_ms)
        if column is None:
            if count <= 0:
                break
            continue
        columns.append(column)
    return columns


def _header_item(hwnd: int, index: int, timeout_ms: int = 500, max_chars: int = 512) -> Optional[Dict[str, Any]]:
    struct_size = ctypes.sizeof(HDITEMW)
    text_offset = struct_size
    total = struct_size + (max_chars * ctypes.sizeof(ctypes.c_wchar))
    with _RemoteBuffer(hwnd, total) as remote:
        item = HDITEMW()
        item.mask = HDI_TEXT | HDI_WIDTH | HDI_FORMAT | HDI_ORDER | HDI_IMAGE | HDI_LPARAM | HDI_STATE
        item.pszText = remote.address + text_offset
        item.cchTextMax = int(max_chars)
        remote.write_struct(0, item)
        ok, result = _send_message_timeout(hwnd, HDM_GETITEMW, int(index), remote.address, timeout_ms=timeout_ms)
        if not ok or not result:
            return None
        data = remote.read_bytes(0, ctypes.sizeof(HDITEMW))
        updated = HDITEMW.from_buffer_copy(data)
        rect = ctypes.wintypes.RECT()
        with _RemoteBuffer(hwnd, ctypes.sizeof(ctypes.wintypes.RECT)) as rect_remote:
            rect_ok, _ = _send_message_timeout(hwnd, HDM_GETITEMRECT, int(index), rect_remote.address, timeout_ms=timeout_ms)
            if rect_ok:
                rect_data = rect_remote.read_bytes(0, ctypes.sizeof(ctypes.wintypes.RECT))
                rect = ctypes.wintypes.RECT.from_buffer_copy(rect_data)
        return {
            "index": int(index),
            "text": remote.read_wstring(text_offset, max_chars),
            "width": int(updated.cxy),
            "format": int(updated.fmt),
            "order": int(updated.iOrder),
            "image": int(updated.iImage),
            "state": int(updated.state),
            "lparam": int(updated.lParam),
            "rect": _rect_to_plain_dict(rect) if rect.right or rect.bottom or rect.left or rect.top else None,
        }


def _header_order(hwnd: int, count: int, timeout_ms: int = 500) -> List[int]:
    count = max(int(count), 0)
    if count <= 0:
        return []
    with _RemoteBuffer(hwnd, count * ctypes.sizeof(ctypes.c_int)) as remote:
        ok, result = _send_message_timeout(hwnd, HDM_GETORDERARRAY, count, remote.address, timeout_ms=timeout_ms)
        if not ok or not result:
            return []
        data = remote.read_bytes(0, count * ctypes.sizeof(ctypes.c_int))
        array_type = ctypes.c_int * count
        return [int(value) for value in array_type.from_buffer_copy(data)]


def _header_info(hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> Dict[str, Any]:
    ok_count, count_value = _send_message_timeout(hwnd, HDM_GETITEMCOUNT, 0, 0, timeout_ms=timeout_ms)
    count = int(count_value) if ok_count and count_value >= 0 else 0
    items: List[Dict[str, Any]] = []
    for i in range(min(count, max_items)):
        item = _header_item(hwnd, i, timeout_ms=timeout_ms)
        if item is not None:
            items.append(item)
    order = _header_order(hwnd, count, timeout_ms=timeout_ms)
    return {
        "count": count,
        "order": order,
        "items": items,
    }


def _header_set_item(hwnd: int, index: int, text: Optional[str] = None, width: Optional[int] = None, fmt: Optional[int] = None, timeout_ms: int = 500) -> Tuple[bool, int]:
    item = HDITEMW()
    encoded_text = b""
    if text is not None:
        encoded_text = (str(text) + "\x00").encode("utf-16-le")
        item.mask |= HDI_TEXT
        item.cchTextMax = len(str(text)) + 1
    if width is not None:
        item.mask |= HDI_WIDTH
        item.cxy = int(width)
    if fmt is not None:
        item.mask |= HDI_FORMAT
        item.fmt = int(fmt)
    if not item.mask:
        return False, 0
    struct_size = ctypes.sizeof(HDITEMW)
    total = struct_size + len(encoded_text)
    with _RemoteBuffer(hwnd, total) as remote:
        if encoded_text:
            text_offset = struct_size
            remote.write_bytes(text_offset, encoded_text)
            item.pszText = remote.address + text_offset
        remote.write_struct(0, item)
        return _send_message_timeout(hwnd, HDM_SETITEMW, int(index), remote.address, timeout_ms=timeout_ms)


def _header_set_order(hwnd: int, order: List[int], timeout_ms: int = 500) -> Tuple[bool, int]:
    count = len(order)
    if count <= 0:
        return False, 0
    array_type = ctypes.c_int * count
    values = array_type(*[int(value) for value in order])
    with _RemoteBuffer(hwnd, ctypes.sizeof(values)) as remote:
        remote.write_bytes(0, ctypes.string_at(ctypes.byref(values), ctypes.sizeof(values)))
        return _send_message_timeout(hwnd, HDM_SETORDERARRAY, count, remote.address, timeout_ms=timeout_ms)


def _header_click_item(hwnd: int, item: Dict[str, Any], timeout_ms: int = 500) -> Dict[str, Any]:
    rect = item.get("rect") or {}
    left = int(rect.get("left", 0))
    right = int(rect.get("right", left + max(int(item.get("width") or 1), 1)))
    top = int(rect.get("top", 0))
    bottom = int(rect.get("bottom", top + 20))
    x = max(left, min((left + right) // 2, right - 1))
    y = max(top, min((top + bottom) // 2, bottom - 1))
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    down_ok, down_result = _send_message_timeout(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam, timeout_ms=timeout_ms)
    up_ok, up_result = _send_message_timeout(hwnd, WM_LBUTTONUP, 0, lparam, timeout_ms=timeout_ms)
    return {
        "ok": bool(down_ok and up_ok),
        "x": x,
        "y": y,
        "lparam": lparam,
        "down_result": down_result,
        "up_result": up_result,
    }


def _listview_set_item_text(hwnd: int, index: int, subitem: int, text: str, timeout_ms: int = 500) -> Tuple[bool, int]:
    encoded_text = (str(text) + "\x00").encode("utf-16-le")
    struct_size = ctypes.sizeof(LVITEMW)
    text_offset = struct_size
    total = struct_size + len(encoded_text)
    with _RemoteBuffer(hwnd, total) as remote:
        item = LVITEMW()
        item.mask = LVIF_TEXT
        item.iItem = int(index)
        item.iSubItem = int(subitem)
        item.pszText = remote.address + text_offset
        item.cchTextMax = len(str(text)) + 1
        remote.write_struct(0, item)
        remote.write_bytes(text_offset, encoded_text)
        return _send_message_timeout(hwnd, LVM_SETITEMTEXTW, int(index), remote.address, timeout_ms=timeout_ms)


def _listview_set_item_state(hwnd: int, index: int, state: int, state_mask: int, timeout_ms: int = 500) -> Tuple[bool, int]:
    with _RemoteBuffer(hwnd, ctypes.sizeof(LVITEMW)) as remote:
        item = LVITEMW()
        item.state = int(state)
        item.stateMask = int(state_mask)
        remote.write_struct(0, item)
        return _send_message_timeout(hwnd, LVM_SETITEMSTATE, int(index), remote.address, timeout_ms=timeout_ms)


def _state_image_index(state: Any, mask: int) -> int:
    return (int(state or 0) & int(mask)) >> 12


def _checkbox_checked_from_state_image(state_image: int) -> Optional[bool]:
    normalized = int(state_image)
    if normalized == 1:
        return False
    if normalized == 2:
        return True
    return None


def _checkbox_check_state_from_state_image(state_image: int) -> str:
    normalized = int(state_image)
    if normalized <= 0:
        return "none"
    if normalized == 1:
        return "unchecked"
    if normalized == 2:
        return "checked"
    return "custom"


def _listview_set_check_state(hwnd: int, index: int, checked: bool, timeout_ms: int = 500) -> Tuple[bool, int]:
    state = (2 if checked else 1) << 12
    return _listview_set_item_state(hwnd, index, state, LVIS_STATEIMAGEMASK, timeout_ms=timeout_ms)


def _tab_item_text(hwnd: int, index: int, timeout_ms: int = 500, max_chars: int = 512) -> str:
    struct_size = ctypes.sizeof(TCITEMW)
    text_offset = struct_size
    total = struct_size + (max_chars * ctypes.sizeof(ctypes.c_wchar))
    with _RemoteBuffer(hwnd, total) as remote:
        item = TCITEMW()
        item.mask = TCIF_TEXT
        item.pszText = remote.address + text_offset
        item.cchTextMax = int(max_chars)
        remote.write_struct(0, item)
        ok, _ = _send_message_timeout(hwnd, TCM_GETITEMW, int(index), remote.address, timeout_ms=timeout_ms)
        if not ok:
            return ""
        return remote.read_wstring(text_offset, max_chars)


def _toolbar_button(hwnd: int, index: int, timeout_ms: int = 500) -> Optional[TBBUTTON]:
    with _RemoteBuffer(hwnd, ctypes.sizeof(TBBUTTON)) as remote:
        ok, _ = _send_message_timeout(hwnd, TB_GETBUTTON, int(index), remote.address, timeout_ms=timeout_ms)
        if not ok:
            return None
        data = remote.read_bytes(0, ctypes.sizeof(TBBUTTON))
        return TBBUTTON.from_buffer_copy(data)


def _toolbar_button_text(hwnd: int, command_id: int, timeout_ms: int = 500, max_chars: int = 512) -> str:
    with _RemoteBuffer(hwnd, max_chars * ctypes.sizeof(ctypes.c_wchar)) as remote:
        ok, result = _send_message_timeout(hwnd, TB_GETBUTTONTEXTW, int(command_id), remote.address, timeout_ms=timeout_ms)
        if not ok or result == MESSAGE_RESULT_ERROR:
            return ""
        return remote.read_wstring(0, max_chars)


def _toolbar_button_rect(hwnd: int, index: int, timeout_ms: int = 500) -> Dict[str, int]:
    with _RemoteBuffer(hwnd, ctypes.sizeof(ctypes.wintypes.RECT)) as remote:
        ok, _ = _send_message_timeout(hwnd, TB_GETITEMRECT, int(index), remote.address, timeout_ms=timeout_ms)
        if not ok:
            return _rect_tuple_to_dict((0, 0, 0, 0))
        data = remote.read_bytes(0, ctypes.sizeof(ctypes.wintypes.RECT))
        rect = ctypes.wintypes.RECT.from_buffer_copy(data)
        return _rect_to_plain_dict(rect)


def _toolbar_rect_is_clickable(rect: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(rect, dict):
        return False
    try:
        return int(rect.get("right", 0)) > int(rect.get("left", 0)) and int(rect.get("bottom", 0)) > int(rect.get("top", 0))
    except Exception:
        return False


def _toolbar_button_action(
    hwnd: int,
    index: int,
    command_id: int,
    info: Dict[str, Any],
    *,
    check_target: Optional[bool] = None,
    rect: Optional[Dict[str, Any]] = None,
    timeout_ms: int = 500,
) -> Dict[str, Any]:
    command_id = int(command_id)
    index = int(index)
    if command_id == 0:
        return {"ok": False, "error": "toolbar button has no command id", "index": index, "command_id": command_id}
    button_rect = rect if _toolbar_rect_is_clickable(rect) else _toolbar_button_rect(hwnd, index, timeout_ms=timeout_ms)
    notify_info = {**info, "control_id": command_id}
    if check_target is not None:
        ok_check, check_result = _send_message_timeout(hwnd, TB_CHECKBUTTON, command_id, 1 if check_target else 0, timeout_ms=timeout_ms)
        notified = _win32_notify_parent(notify_info, BN_CLICKED)
        return {
            "ok": bool(ok_check and check_result != MESSAGE_RESULT_ERROR),
            "method": "toolbar.TB_CHECKBUTTON+WM_COMMAND",
            "index": index,
            "command_id": command_id,
            "checked": bool(check_target),
            "result": check_result,
            "notified_parent": bool(notified),
            "rect": button_rect,
        }

    ok_press, press_result = _send_message_timeout(hwnd, TB_PRESSBUTTON, command_id, 1, timeout_ms=timeout_ms)
    click: Dict[str, Any] = {"ok": False, "skipped": True, "reason": "empty toolbar button rectangle"}
    point = None
    if _toolbar_rect_is_clickable(button_rect):
        try:
            x, y = _rect_click_point(button_rect)
            point = {"x": int(x), "y": int(y)}
            click = _send_client_click_sequence(hwnd, x, y, clicks=1, timeout_ms=timeout_ms)
        except Exception as e:
            click = {"ok": False, "error": str(e)}
    notified = False
    notify_fallback = None
    if not click.get("ok"):
        notified = _win32_notify_parent(notify_info, BN_CLICKED)
        notify_fallback = "client_click_unavailable"
    ok_release, release_result = _send_message_timeout(hwnd, TB_PRESSBUTTON, command_id, 0, timeout_ms=timeout_ms)
    ok = bool(click.get("ok") or notified)
    return {
        "ok": ok,
        "method": "toolbar.TB_PRESSBUTTON+client-click-or-WM_COMMAND",
        "index": index,
        "command_id": command_id,
        "press_ok": bool(ok_press),
        "press_result": press_result,
        "release_ok": bool(ok_release),
        "release_result": release_result,
        "notified_parent": bool(notified),
        "notify_fallback": notify_fallback,
        "rect": button_rect,
        "point": point,
        "click": click,
    }


def _tooltip_text(hwnd: int, owner_hwnd: int, tool_id: int, timeout_ms: int = 500, max_chars: int = 1024) -> str:
    struct_size = ctypes.sizeof(TOOLINFOW)
    text_offset = struct_size
    total = struct_size + (max_chars * ctypes.sizeof(ctypes.c_wchar))
    with _RemoteBuffer(hwnd, total) as remote:
        item = TOOLINFOW()
        item.cbSize = struct_size
        item.hwnd = ctypes.c_void_p(int(owner_hwnd))
        item.uId = int(tool_id)
        item.lpszText = ctypes.c_void_p(remote.address + text_offset)
        remote.write_struct(0, item)
        ok, _ = _send_message_timeout(hwnd, TTM_GETTEXTW, 0, remote.address, timeout_ms=timeout_ms)
        if not ok:
            return ""
        return remote.read_wstring(text_offset, max_chars)


def _tooltip_tool_from_remote(remote: _RemoteBuffer) -> TOOLINFOW:
    data = remote.read_bytes(0, ctypes.sizeof(TOOLINFOW))
    return TOOLINFOW.from_buffer_copy(data)


def _tooltip_tools(hwnd: int, timeout_ms: int = 500, max_items: int = 200, max_chars: int = 1024) -> List[Dict[str, Any]]:
    ok_count, raw_count = _send_message_timeout(hwnd, TTM_GETTOOLCOUNT, 0, 0, timeout_ms=timeout_ms)
    count = int(raw_count) if ok_count and raw_count != MESSAGE_RESULT_ERROR and raw_count >= 0 else 0
    tools: List[Dict[str, Any]] = []
    struct_size = ctypes.sizeof(TOOLINFOW)
    text_offset = struct_size
    total = struct_size + (max_chars * ctypes.sizeof(ctypes.c_wchar))
    for index in range(min(count, max_items)):
        try:
            with _RemoteBuffer(hwnd, total) as remote:
                item = TOOLINFOW()
                item.cbSize = struct_size
                item.lpszText = ctypes.c_void_p(remote.address + text_offset)
                remote.write_struct(0, item)
                ok_enum, _ = _send_message_timeout(hwnd, TTM_ENUMTOOLW, int(index), remote.address, timeout_ms=timeout_ms)
                if not ok_enum:
                    continue
                item = _tooltip_tool_from_remote(remote)
                owner_hwnd = int(item.hwnd or 0)
                tool_id = int(item.uId or 0)
                item.lpszText = ctypes.c_void_p(remote.address + text_offset)
                remote.write_struct(0, item)
                ok_text, _ = _send_message_timeout(hwnd, TTM_GETTEXTW, 0, remote.address, timeout_ms=timeout_ms)
                text = remote.read_wstring(text_offset, max_chars) if ok_text else ""
                flags = int(item.uFlags)
                tools.append({
                    "index": index,
                    "hwnd": owner_hwnd,
                    "tool_id": tool_id,
                    "id_is_hwnd": bool(flags & TTF_IDISHWND),
                    "subclass": bool(flags & TTF_SUBCLASS),
                    "flags": flags,
                    "rect": _rect_to_plain_dict(item.rect),
                    "text": text,
                    "lparam": int(item.lParam),
                })
        except Exception as e:
            tools.append({"index": index, "error": str(e)})
    return tools


def _tooltip_text_map_for_owner(tooltip_hwnd: int, owner_hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    for tool in _tooltip_tools(tooltip_hwnd, timeout_ms=timeout_ms, max_items=max_items):
        if int(tool.get("hwnd") or 0) != int(owner_hwnd):
            continue
        text = str(tool.get("text") or "")
        if text:
            mapping[int(tool.get("tool_id") or 0)] = text
    return mapping


def _statusbar_part_text(hwnd: int, index: int, timeout_ms: int = 500) -> Dict[str, Any]:
    ok_len, raw_length = _send_message_timeout(hwnd, SB_GETTEXTLENGTHW, int(index), 0, timeout_ms=timeout_ms)
    if not ok_len or raw_length == MESSAGE_RESULT_ERROR:
        return {"text": "", "length": 0, "type": "normal"}
    length = int(raw_length & 0xFFFF)
    text_type = int((raw_length >> 16) & 0xFFFF)
    max_chars = max(length + 1, 2)
    with _RemoteBuffer(hwnd, max_chars * ctypes.sizeof(ctypes.c_wchar)) as remote:
        ok, _ = _send_message_timeout(hwnd, SB_GETTEXTW, int(index), remote.address, timeout_ms=timeout_ms)
        text = remote.read_wstring(0, max_chars) if ok else ""
    flags = []
    if text_type & SBT_OWNERDRAW:
        flags.append("ownerdraw")
    if text_type & SBT_NOBORDERS:
        flags.append("noborders")
    if text_type & SBT_POPOUT:
        flags.append("popout")
    if text_type & SBT_RTLREADING:
        flags.append("rtl")
    return {"text": text, "length": length, "type": text_type, "flags": flags}


def _statusbar_part_rect(hwnd: int, index: int, timeout_ms: int = 500) -> Dict[str, int]:
    with _RemoteBuffer(hwnd, ctypes.sizeof(ctypes.wintypes.RECT)) as remote:
        ok, _ = _send_message_timeout(hwnd, SB_GETRECT, int(index), remote.address, timeout_ms=timeout_ms)
        if not ok:
            return _rect_tuple_to_dict((0, 0, 0, 0))
        data = remote.read_bytes(0, ctypes.sizeof(ctypes.wintypes.RECT))
        rect = ctypes.wintypes.RECT.from_buffer_copy(data)
        return _rect_tuple_to_dict((rect.left, rect.top, rect.right, rect.bottom))


def _statusbar_parts(hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> List[Dict[str, Any]]:
    ok_count, count = _send_message_timeout(hwnd, SB_GETPARTS, 0, 0, timeout_ms=timeout_ms)
    if not ok_count or count <= 0:
        count = 1
    count = min(int(count), max_items)
    with _RemoteBuffer(hwnd, max(count, 1) * ctypes.sizeof(ctypes.c_int)) as remote:
        ok, _ = _send_message_timeout(hwnd, SB_GETPARTS, count, remote.address, timeout_ms=timeout_ms)
        right_edges: List[int] = []
        if ok:
            data = remote.read_bytes(0, count * ctypes.sizeof(ctypes.c_int))
            right_edges = [int.from_bytes(data[i * 4:(i + 1) * 4], "little", signed=True) for i in range(count)]
    parts = []
    for i in range(count):
        text_info = _statusbar_part_text(hwnd, i, timeout_ms=timeout_ms)
        parts.append({
            "index": i,
            "right_edge": right_edges[i] if i < len(right_edges) else None,
            "rect": _statusbar_part_rect(hwnd, i, timeout_ms=timeout_ms),
            **text_info,
        })
    return parts


def _set_statusbar_part_text(hwnd: int, index: int, text: str, timeout_ms: int = 500) -> Tuple[bool, int]:
    text_buf = ctypes.create_unicode_buffer(str(text))
    return _send_message_timeout(hwnd, SB_SETTEXTW, int(index), ctypes.addressof(text_buf), timeout_ms=timeout_ms)


def _static_type(style: int) -> str:
    low = int(style) & SS_TYPEMASK
    return {
        SS_LEFT: "text_left",
        SS_CENTER: "text_center",
        SS_RIGHT: "text_right",
        SS_ICON: "icon",
        SS_BLACKRECT: "black_rect",
        SS_GRAYRECT: "gray_rect",
        SS_WHITERECT: "white_rect",
        SS_BLACKFRAME: "black_frame",
        SS_GRAYFRAME: "gray_frame",
        SS_WHITEFRAME: "white_frame",
        SS_USERITEM: "user_item",
        SS_SIMPLE: "simple_text",
        SS_LEFTNOWORDWRAP: "text_left_nowordwrap",
        SS_OWNERDRAW: "owner_draw",
        SS_BITMAP: "bitmap",
        SS_ENHMETAFILE: "enhmetafile",
        SS_ETCHEDHORZ: "etched_horizontal",
        SS_ETCHEDVERT: "etched_vertical",
        SS_ETCHEDFRAME: "etched_frame",
    }.get(low, f"type_{low}")


def _static_info(hwnd: int, style: int, timeout_ms: int = 500) -> Dict[str, Any]:
    static_type = _static_type(style)
    image_kind = IMAGE_ICON if (int(style) & SS_TYPEMASK) == SS_ICON else IMAGE_BITMAP if (int(style) & SS_TYPEMASK) == SS_BITMAP else IMAGE_ENHMETAFILE if (int(style) & SS_TYPEMASK) == SS_ENHMETAFILE else None
    image_handle = 0
    if image_kind is not None:
        ok_image, image = _send_message_timeout(hwnd, STM_GETIMAGE, image_kind, 0, timeout_ms=timeout_ms)
        image_handle = int(image) if ok_image else 0
    return {
        "text": _get_control_text(hwnd, timeout_ms=timeout_ms),
        "static_type": static_type,
        "notify": bool(int(style) & SS_NOTIFY),
        "image_kind": image_kind,
        "image_handle": image_handle,
    }


def _progress_range(hwnd: int, timeout_ms: int = 500) -> Dict[str, int]:
    range_struct = PBRANGE()
    ok, _ = _send_message_timeout(hwnd, PBM_GETRANGE, 0, ctypes.addressof(range_struct), timeout_ms=timeout_ms)
    if not ok:
        return {"min": 0, "max": 100}
    return {"min": int(range_struct.iLow), "max": int(range_struct.iHigh)}


def _updown_range(hwnd: int, timeout_ms: int = 500) -> Dict[str, int]:
    low = ctypes.c_int()
    high = ctypes.c_int()
    ok, _ = _send_message_timeout(hwnd, UDM_GETRANGE32, ctypes.addressof(low), ctypes.addressof(high), timeout_ms=timeout_ms)
    if not ok:
        return {"min": 0, "max": 100}
    return {"min": int(low.value), "max": int(high.value)}


def _clamp_int(value: int, minimum: Optional[int], maximum: Optional[int]) -> int:
    result = int(value)
    if minimum is not None:
        result = max(result, int(minimum))
    if maximum is not None:
        result = min(result, int(maximum))
    return result


def _scrollbar_orientation(style: int) -> str:
    return "vertical" if (int(style) & SBS_VERT) else "horizontal"


def _scrollbar_info(hwnd: int) -> Dict[str, Any]:
    si = SCROLLINFO()
    si.cbSize = ctypes.sizeof(SCROLLINFO)
    si.fMask = SIF_ALL
    ok = bool(user32.GetScrollInfo(hwnd, SB_CTL, ctypes.byref(si)))
    return {
        "ok": ok,
        "min": int(si.nMin),
        "max": int(si.nMax),
        "page": int(si.nPage),
        "position": int(si.nPos),
        "track_position": int(si.nTrackPos),
    }


def _scrollbar_set_position(hwnd: int, position: int, redraw: bool = True) -> int:
    si = SCROLLINFO()
    si.cbSize = ctypes.sizeof(SCROLLINFO)
    si.fMask = SIF_POS
    si.nPos = int(position)
    return int(user32.SetScrollInfo(hwnd, SB_CTL, ctypes.byref(si), bool(redraw)))


def _scrollbar_notify_parent(info: Dict[str, Any], code: int, position: Optional[int], timeout_ms: int = 500) -> bool:
    parent = int(info.get("parent_hwnd") or 0)
    hwnd = int(info.get("hwnd") or 0)
    if not parent:
        return False
    vertical = _scrollbar_orientation(int(info.get("style") or 0)) == "vertical"
    message = WM_VSCROLL if vertical else WM_HSCROLL
    pos_part = (int(position or 0) & 0xFFFF) << 16
    wparam = pos_part | (int(code) & 0xFFFF)
    ok, _ = _send_message_timeout(parent, message, wparam, hwnd, timeout_ms=timeout_ms)
    end_ok, _ = _send_message_timeout(parent, message, SB_ENDSCROLL, hwnd, timeout_ms=timeout_ms)
    return bool(ok or end_ok)


def _is_richedit_class(class_name: str) -> bool:
    lowered = (class_name or "").lower()
    return "richedit" in lowered or lowered in ("richtext",)


def _is_edit_class(class_name: str) -> bool:
    return (class_name or "").lower() == "edit"


_VK_NAME_TO_CODE: Dict[str, int] = {
    "backspace": VK_BACK,
    "back": VK_BACK,
    "tab": VK_TAB,
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "escape": VK_ESCAPE,
    "esc": VK_ESCAPE,
    "space": VK_SPACE,
    "pageup": VK_PRIOR,
    "page_up": VK_PRIOR,
    "pagedown": VK_NEXT,
    "page_down": VK_NEXT,
    "end": VK_END,
    "home": VK_HOME,
    "left": VK_LEFT,
    "up": VK_UP,
    "right": VK_RIGHT,
    "down": VK_DOWN,
    "insert": VK_INSERT,
    "ins": VK_INSERT,
    "delete": VK_DELETE,
    "del": VK_DELETE,
}
for _i in range(1, 25):
    _VK_NAME_TO_CODE[f"f{_i}"] = 0x70 + _i - 1
for _i in range(10):
    _VK_NAME_TO_CODE[str(_i)] = ord(str(_i))
for _ch in "abcdefghijklmnopqrstuvwxyz":
    _VK_NAME_TO_CODE[_ch] = ord(_ch.upper())

_VK_CODE_TO_NAME: Dict[int, str] = {}
for _name, _code in _VK_NAME_TO_CODE.items():
    _VK_CODE_TO_NAME.setdefault(int(_code), _name.upper() if len(_name) == 1 else _name)


def _hotkey_word_to_dict(word: int) -> Dict[str, Any]:
    value = int(word) & 0xFFFF
    vk = value & 0xFF
    flags = (value >> 8) & 0xFF
    modifiers: List[str] = []
    if flags & HOTKEYF_CONTROL:
        modifiers.append("ctrl")
    if flags & HOTKEYF_SHIFT:
        modifiers.append("shift")
    if flags & HOTKEYF_ALT:
        modifiers.append("alt")
    if flags & HOTKEYF_EXT:
        modifiers.append("extended")
    key = _VK_CODE_TO_NAME.get(vk, f"vk_{vk:02X}" if vk else "")
    display_parts = [m for m in modifiers if m != "extended"]
    if key:
        display_parts.append(key.upper() if len(key) == 1 else key)
    return {
        "word": value,
        "vk": vk,
        "key": key,
        "modifiers": modifiers,
        "display": "+".join(display_parts),
        "flags": flags,
    }


def _parse_hotkey(value: Any) -> int:
    if isinstance(value, int):
        return int(value) & 0xFFFF
    text = str(value or "").strip()
    if not text:
        return 0
    if text.lower().startswith("0x"):
        return int(text, 16) & 0xFFFF
    if text.isdigit():
        return int(text) & 0xFFFF
    flags = 0
    vk = 0
    for raw_part in text.replace(" ", "").replace("-", "+").split("+"):
        part = raw_part.strip().lower()
        if not part:
            continue
        if part in ("ctrl", "control", "control_l", "control_r"):
            flags |= HOTKEYF_CONTROL
        elif part in ("shift", "shift_l", "shift_r"):
            flags |= HOTKEYF_SHIFT
        elif part in ("alt", "menu", "alt_l", "alt_r"):
            flags |= HOTKEYF_ALT
        elif part in ("extended", "ext"):
            flags |= HOTKEYF_EXT
        else:
            key = _VK_NAME_TO_CODE.get(part)
            if key is None and len(part) == 1:
                key = ord(part.upper())
            if key is None:
                raise ValueError(f"Unknown hotkey key: {raw_part}")
            vk = int(key)
    if not vk:
        raise ValueError("hotkey must include a non-modifier key")
    return ((flags & 0xFF) << 8) | (vk & 0xFF)


def _hotkey_info(hwnd: int, timeout_ms: int = 500) -> Dict[str, Any]:
    ok, word = _send_message_timeout(hwnd, HKM_GETHOTKEY, 0, 0, timeout_ms=timeout_ms)
    parsed = _hotkey_word_to_dict(word if ok else 0)
    parsed["ok"] = bool(ok)
    return parsed


def _syslink_links_from_text(text: str) -> List[Dict[str, Any]]:
    import re

    links: List[Dict[str, Any]] = []
    pattern = re.compile(r"<a(?:\s+[^>]*)?>(.*?)</a>", re.IGNORECASE | re.DOTALL)
    attr_pattern = re.compile(r"(\w+)\s*=\s*(['\"])(.*?)\2", re.IGNORECASE | re.DOTALL)
    for index, match in enumerate(pattern.finditer(text or "")):
        tag = match.group(0)
        attrs = {m.group(1).lower(): m.group(3) for m in attr_pattern.finditer(tag)}
        label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        links.append({
            "index": index,
            "text": label,
            "id": attrs.get("id", ""),
            "href": attrs.get("href", ""),
            "markup": tag,
        })
    return links


def _syslink_item(hwnd: int, index: int, timeout_ms: int = 500) -> Optional[Dict[str, Any]]:
    item = LITEMW()
    item.mask = LIF_ITEMINDEX | LIF_ITEMID | LIF_URL | LIF_STATE
    item.iLink = int(index)
    item.stateMask = LIS_FOCUSED | LIS_ENABLED | LIS_VISITED | LIS_HOTTRACK | LIS_DEFAULTCOLORS
    with _RemoteBuffer(hwnd, ctypes.sizeof(LITEMW)) as remote:
        remote.write_struct(0, item)
        ok, result = _send_message_timeout(hwnd, LM_GETITEM, 0, remote.address, timeout_ms=timeout_ms)
        if not ok or not result:
            return None
        data = remote.read_bytes(0, ctypes.sizeof(LITEMW))
        updated = LITEMW.from_buffer_copy(data)
        return {
            "index": int(index),
            "id": str(updated.szID).rstrip("\x00"),
            "href": str(updated.szUrl).rstrip("\x00"),
            "state": int(updated.state),
            "enabled": bool(updated.state & LIS_ENABLED),
            "visited": bool(updated.state & LIS_VISITED),
            "focused": bool(updated.state & LIS_FOCUSED),
        }


def _syslink_info(hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> Dict[str, Any]:
    text_info = _get_control_text(hwnd, timeout_ms=timeout_ms)
    links = _syslink_links_from_text(str(text_info.get("text") or ""))
    for i, link in enumerate(links[:max_items]):
        item = _syslink_item(hwnd, i, timeout_ms=timeout_ms)
        if item:
            link.update({k: v for k, v in item.items() if k != "index" or "index" not in link})
    ok_height, height = _send_message_timeout(hwnd, LM_GETIDEALHEIGHT, 0, 0, timeout_ms=timeout_ms)
    return {
        "text": text_info,
        "count": len(links),
        "links": links[:max_items],
        "items": links[:max_items],
        "ideal_height": int(height) if ok_height else None,
    }


def _syslink_set_item_visited(hwnd: int, index: int, visited: bool, timeout_ms: int = 500) -> Tuple[bool, int]:
    item = LITEMW()
    item.mask = LIF_ITEMINDEX | LIF_STATE
    item.iLink = int(index)
    item.stateMask = LIS_VISITED
    item.state = LIS_VISITED if visited else 0
    with _RemoteBuffer(hwnd, ctypes.sizeof(LITEMW)) as remote:
        remote.write_struct(0, item)
        return _send_message_timeout(hwnd, LM_SETITEM, 0, remote.address, timeout_ms=timeout_ms)


def _edit_selection(hwnd: int, timeout_ms: int = 500) -> Dict[str, int]:
    start = ctypes.c_ulong()
    end = ctypes.c_ulong()
    ok, _ = _send_message_timeout(hwnd, EM_GETSEL, ctypes.addressof(start), ctypes.addressof(end), timeout_ms=timeout_ms)
    if not ok:
        return {"start": 0, "end": 0}
    return {"start": int(start.value), "end": int(end.value)}


def _edit_set_selection(hwnd: int, start: int, end: int, timeout_ms: int = 500) -> Tuple[bool, int]:
    return _send_message_timeout(hwnd, EM_SETSEL, int(start), int(end), timeout_ms=timeout_ms)


def _edit_replace_selection(hwnd: int, text: str, can_undo: bool = True, timeout_ms: int = 500) -> Tuple[bool, int]:
    buf = ctypes.create_unicode_buffer(str(text))
    return _send_message_timeout(hwnd, EM_REPLACESEL, 1 if can_undo else 0, ctypes.addressof(buf), timeout_ms=timeout_ms)


def _edit_info(hwnd: int, timeout_ms: int = 500, max_chars: int = 8192) -> Dict[str, Any]:
    text_info = _get_control_text(hwnd, timeout_ms=timeout_ms, max_chars=max_chars)
    ok_lines, line_count = _send_message_timeout(hwnd, EM_GETLINECOUNT, 0, 0, timeout_ms=timeout_ms)
    ok_limit, limit = _send_message_timeout(hwnd, EM_GETLIMITTEXT, 0, 0, timeout_ms=timeout_ms)
    selection = _edit_selection(hwnd, timeout_ms=timeout_ms)
    text_value = text_info.get("text") if text_info.get("ok") else ""
    selected_text = ""
    if text_value:
        start = max(selection.get("start", 0), 0)
        end = max(selection.get("end", start), start)
        selected_text = str(text_value)[start:end]
    return {
        "text": text_info,
        "line_count": int(line_count) if ok_lines else None,
        "limit": int(limit) if ok_limit else None,
        "selection": selection,
        "selected_text": selected_text,
    }


def _ensure_richedit_loaded() -> bool:
    for dll_name in ("Msftedit.dll", "Riched20.dll", "Riched32.dll"):
        try:
            if kernel32.LoadLibraryW(dll_name):
                return True
        except Exception:
            pass
    return False


def _richedit_selection(hwnd: int, timeout_ms: int = 500) -> Dict[str, int]:
    char_range = CHARRANGE()
    ok, _ = _send_message_timeout(hwnd, EM_EXGETSEL, 0, ctypes.addressof(char_range), timeout_ms=timeout_ms)
    if ok:
        return {"start": int(char_range.cpMin), "end": int(char_range.cpMax)}
    start = ctypes.c_ulong()
    end = ctypes.c_ulong()
    ok, _ = _send_message_timeout(hwnd, EM_GETSEL, ctypes.addressof(start), ctypes.addressof(end), timeout_ms=timeout_ms)
    if not ok:
        return {"start": 0, "end": 0}
    return {"start": int(start.value), "end": int(end.value)}


def _richedit_set_selection(hwnd: int, start: int, end: int, timeout_ms: int = 500) -> Tuple[bool, int]:
    char_range = CHARRANGE()
    char_range.cpMin = int(start)
    char_range.cpMax = int(end)
    ok, result = _send_message_timeout(hwnd, EM_EXSETSEL, 0, ctypes.addressof(char_range), timeout_ms=timeout_ms)
    if ok:
        return ok, result
    return _send_message_timeout(hwnd, EM_SETSEL, int(start), int(end), timeout_ms=timeout_ms)


def _richedit_replace_selection(hwnd: int, text: str, can_undo: bool = True, timeout_ms: int = 500) -> Tuple[bool, int]:
    buf = ctypes.create_unicode_buffer(str(text))
    return _send_message_timeout(hwnd, EM_REPLACESEL, 1 if can_undo else 0, ctypes.addressof(buf), timeout_ms=timeout_ms)


def _richedit_info(hwnd: int, timeout_ms: int = 500, max_chars: int = 8192) -> Dict[str, Any]:
    text_info = _get_control_text(hwnd, timeout_ms=timeout_ms, max_chars=max_chars)
    ok_lines, line_count = _send_message_timeout(hwnd, EM_GETLINECOUNT, 0, 0, timeout_ms=timeout_ms)
    ok_limit, limit = _send_message_timeout(hwnd, EM_GETLIMITTEXT, 0, 0, timeout_ms=timeout_ms)
    selection = _richedit_selection(hwnd, timeout_ms=timeout_ms)
    text_value = text_info.get("text") if text_info.get("ok") else ""
    selected_text = ""
    if text_value:
        start = max(selection.get("start", 0), 0)
        end = max(selection.get("end", start), start)
        selected_text = str(text_value)[start:end]
    return {
        "text": text_info,
        "line_count": int(line_count) if ok_lines else None,
        "limit": int(limit) if ok_limit else None,
        "selection": selection,
        "selected_text": selected_text,
    }


def _systemtime_to_dict(st: SYSTEMTIME) -> Dict[str, Any]:
    return {
        "year": int(st.wYear),
        "month": int(st.wMonth),
        "day": int(st.wDay),
        "day_of_week": int(st.wDayOfWeek),
        "hour": int(st.wHour),
        "minute": int(st.wMinute),
        "second": int(st.wSecond),
        "millisecond": int(st.wMilliseconds),
        "iso": f"{int(st.wYear):04d}-{int(st.wMonth):02d}-{int(st.wDay):02d}",
        "datetime": f"{int(st.wYear):04d}-{int(st.wMonth):02d}-{int(st.wDay):02d}T{int(st.wHour):02d}:{int(st.wMinute):02d}:{int(st.wSecond):02d}",
    }


def _parse_systemtime(value: Any) -> SYSTEMTIME:
    if isinstance(value, dict):
        year = int(value.get("year"))
        month = int(value.get("month"))
        day = int(value.get("day"))
        hour = int(value.get("hour", 0))
        minute = int(value.get("minute", 0))
        second = int(value.get("second", 0))
        millisecond = int(value.get("millisecond", value.get("milliseconds", 0)))
    else:
        raw = str(value).strip()
        date_part = raw
        time_part = ""
        if "T" in raw:
            date_part, time_part = raw.split("T", 1)
        elif " " in raw:
            date_part, time_part = raw.split(" ", 1)
        pieces = date_part.replace("/", "-").split("-")
        if len(pieces) != 3:
            raise ValueError("date must be YYYY-MM-DD")
        year, month, day = [int(part) for part in pieces]
        hour = minute = second = millisecond = 0
        if time_part:
            time_main = time_part.split(".", 1)
            hms = time_main[0].split(":")
            if len(hms) >= 1 and hms[0]:
                hour = int(hms[0])
            if len(hms) >= 2 and hms[1]:
                minute = int(hms[1])
            if len(hms) >= 3 and hms[2]:
                second = int(hms[2])
            if len(time_main) == 2 and time_main[1]:
                millisecond = int(time_main[1][:3].ljust(3, "0"))
    st = SYSTEMTIME()
    st.wYear = year
    st.wMonth = month
    st.wDay = day
    st.wHour = hour
    st.wMinute = minute
    st.wSecond = second
    st.wMilliseconds = millisecond
    return st


def _get_systemtime_control(hwnd: int, message: int, timeout_ms: int = 500, datetime_result: bool = False) -> Dict[str, Any]:
    with _RemoteBuffer(hwnd, ctypes.sizeof(SYSTEMTIME)) as remote:
        ok, result = _send_message_timeout(hwnd, message, 0, remote.address, timeout_ms=timeout_ms)
        if not ok:
            return {"ok": False, "error": "message failed", "result": result}
        if datetime_result and result == GDT_NONE:
            return {"ok": True, "none": True, "result": result}
        if datetime_result and result not in (GDT_VALID, GDT_NONE):
            return {"ok": False, "error": "invalid datetime result", "result": result}
        if not datetime_result and not result:
            return {"ok": False, "error": "message returned false", "result": result}
        data = remote.read_bytes(0, ctypes.sizeof(SYSTEMTIME))
        st = SYSTEMTIME.from_buffer_copy(data)
        return {"ok": True, "none": False, "result": result, **_systemtime_to_dict(st)}


def _set_systemtime_control(hwnd: int, message: int, value: Any, timeout_ms: int = 500, datetime_picker: bool = False) -> Tuple[bool, int]:
    st = _parse_systemtime(value)
    with _RemoteBuffer(hwnd, ctypes.sizeof(SYSTEMTIME)) as remote:
        remote.write_struct(0, st)
        wparam = GDT_VALID if datetime_picker else 0
        return _send_message_timeout(hwnd, message, wparam, remote.address, timeout_ms=timeout_ms)


def _parse_ip_address(value: Any) -> int:
    if isinstance(value, int):
        return int(value) & 0xFFFFFFFF
    parts = str(value).strip().split(".")
    if len(parts) != 4:
        raise ValueError("IP address must be a.b.c.d")
    octets = [int(part) for part in parts]
    if any(part < 0 or part > 255 for part in octets):
        raise ValueError("IP address octets must be 0..255")
    return ((octets[0] & 0xFF) << 24) | ((octets[1] & 0xFF) << 16) | ((octets[2] & 0xFF) << 8) | (octets[3] & 0xFF)


def _ip_address_to_string(value: int) -> str:
    value = int(value) & 0xFFFFFFFF
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def _ip_address_info(hwnd: int, timeout_ms: int = 500) -> Dict[str, Any]:
    addr = ctypes.c_uint32()
    ok_blank, blank = _send_message_timeout(hwnd, IPM_ISBLANK, 0, 0, timeout_ms=timeout_ms)
    ok, filled = _send_message_timeout(hwnd, IPM_GETADDRESS, 0, ctypes.addressof(addr), timeout_ms=timeout_ms)
    value = int(addr.value)
    return {
        "blank": bool(ok_blank and blank),
        "filled_fields": int(filled) if ok else 0,
        "address_value": value,
        "address": "" if (ok_blank and blank) else _ip_address_to_string(value),
    }


def _treeview_item_text(hwnd: int, hitem: int, timeout_ms: int = 500, max_chars: int = 512) -> str:
    struct_size = ctypes.sizeof(TVITEMW)
    text_offset = struct_size
    total = struct_size + (max_chars * ctypes.sizeof(ctypes.c_wchar))
    with _RemoteBuffer(hwnd, total) as remote:
        item = TVITEMW()
        item.mask = TVIF_TEXT | TVIF_STATE
        item.hItem = ctypes.c_void_p(int(hitem))
        item.stateMask = TVIS_SELECTED | TVIS_EXPANDED
        item.pszText = remote.address + text_offset
        item.cchTextMax = int(max_chars)
        remote.write_struct(0, item)
        ok, _ = _send_message_timeout(hwnd, TVM_GETITEMW, 0, remote.address, timeout_ms=timeout_ms)
        if not ok:
            return ""
        return remote.read_wstring(text_offset, max_chars)


def _treeview_item_state(hwnd: int, hitem: int, timeout_ms: int = 500) -> Dict[str, Any]:
    with _RemoteBuffer(hwnd, ctypes.sizeof(TVITEMW)) as remote:
        item = TVITEMW()
        item.mask = TVIF_STATE
        item.hItem = ctypes.c_void_p(int(hitem))
        item.stateMask = TVIS_SELECTED | TVIS_EXPANDED | TVIS_STATEIMAGEMASK
        remote.write_struct(0, item)
        ok, _ = _send_message_timeout(hwnd, TVM_GETITEMW, 0, remote.address, timeout_ms=timeout_ms)
        if not ok:
            return {"selected": False, "expanded": False, "checked": None, "check_state": "none", "state_image": 0, "state": 0}
        data = remote.read_bytes(0, ctypes.sizeof(TVITEMW))
        updated = TVITEMW.from_buffer_copy(data)
        state_image = _state_image_index(updated.state, TVIS_STATEIMAGEMASK)
        return {
            "selected": bool(updated.state & TVIS_SELECTED),
            "expanded": bool(updated.state & TVIS_EXPANDED),
            "checked": _checkbox_checked_from_state_image(state_image),
            "check_state": _checkbox_check_state_from_state_image(state_image),
            "state_image": state_image,
            "state": int(updated.state),
        }


def _treeview_item_rect(hwnd: int, hitem: int, text_only: bool = True, timeout_ms: int = 500) -> Optional[Dict[str, int]]:
    with _RemoteBuffer(hwnd, ctypes.sizeof(ctypes.wintypes.RECT)) as remote:
        remote.write_bytes(0, bytes(ctypes.sizeof(ctypes.wintypes.RECT)))
        handle_value = ctypes.c_void_p(int(hitem))
        remote.write_bytes(0, ctypes.string_at(ctypes.byref(handle_value), ctypes.sizeof(handle_value)))
        ok, result = _send_message_timeout(hwnd, TVM_GETITEMRECT, 1 if text_only else 0, remote.address, timeout_ms=timeout_ms)
        if not ok or not result:
            return None
        data = remote.read_bytes(0, ctypes.sizeof(ctypes.wintypes.RECT))
        rect = ctypes.wintypes.RECT.from_buffer_copy(data)
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return _rect_to_plain_dict(rect)


def _treeview_activate_item(hwnd: int, hitem: int, index: Optional[int] = None, timeout_ms: int = 500) -> Dict[str, Any]:
    ok_select, select_result = _send_message_timeout(hwnd, TVM_SELECTITEM, TVGN_CARET, int(hitem), timeout_ms=timeout_ms)
    ok_visible, visible_result = _send_message_timeout(hwnd, TVM_ENSUREVISIBLE, 0, int(hitem), timeout_ms=timeout_ms)
    rect = _treeview_item_rect(hwnd, int(hitem), text_only=True, timeout_ms=timeout_ms)
    rect_part = "label"
    if rect is None:
        rect = _treeview_item_rect(hwnd, int(hitem), text_only=False, timeout_ms=timeout_ms)
        rect_part = "bounds"
    if rect is None:
        return {
            "ok": False,
            "index": int(index) if index is not None else None,
            "handle": int(hitem),
            "error": "could not read TreeView item rectangle",
            "select_ok": bool(ok_select),
            "select_result": int(select_result),
            "ensure_visible_ok": bool(ok_visible),
            "ensure_visible_result": int(visible_result),
        }
    x, y = _rect_click_point(rect)
    click = _send_client_click_sequence(hwnd, x, y, clicks=2, timeout_ms=timeout_ms)
    return {
        "ok": bool(ok_select and ok_visible and click.get("ok")),
        "index": int(index) if index is not None else None,
        "handle": int(hitem),
        "select_ok": bool(ok_select),
        "select_result": int(select_result),
        "ensure_visible_ok": bool(ok_visible),
        "ensure_visible_result": int(visible_result),
        "rect_part": rect_part,
        "rect": rect,
        "point": {"x": int(x), "y": int(y)},
        "click": click,
    }


def _treeview_set_check_state(hwnd: int, hitem: int, checked: bool, timeout_ms: int = 500) -> Tuple[bool, int]:
    with _RemoteBuffer(hwnd, ctypes.sizeof(TVITEMW)) as remote:
        item = TVITEMW()
        item.mask = TVIF_STATE
        item.hItem = ctypes.c_void_p(int(hitem))
        item.state = (2 if checked else 1) << 12
        item.stateMask = TVIS_STATEIMAGEMASK
        remote.write_struct(0, item)
        return _send_message_timeout(hwnd, TVM_SETITEMW, 0, remote.address, timeout_ms=timeout_ms)


def _treeview_children(hwnd: int, parent: Optional[int], max_nodes: int, timeout_ms: int, path_prefix: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    if max_nodes <= 0:
        return nodes
    flag = TVGN_CHILD if parent else TVGN_ROOT
    ok, hitem = _send_message_timeout(hwnd, TVM_GETNEXTITEM, flag, int(parent or 0), timeout_ms=timeout_ms)
    path_prefix = path_prefix or []
    position = 0
    while ok and hitem and len(nodes) < max_nodes:
        state = _treeview_item_state(hwnd, hitem, timeout_ms=timeout_ms)
        node_path = path_prefix + [position]
        child_nodes = _treeview_children(hwnd, hitem, max_nodes - len(nodes) - 1, timeout_ms, node_path)
        node = {
            "handle": hitem,
            "position": position,
            "path": node_path,
            "text": _treeview_item_text(hwnd, hitem, timeout_ms=timeout_ms),
            "selected": state.get("selected", False),
            "expanded": state.get("expanded", False),
            "checked": state.get("checked"),
            "check_state": state.get("check_state", "none"),
            "state_image": state.get("state_image", 0),
            "state": state.get("state", 0),
            "children": child_nodes,
        }
        nodes.append(node)
        ok, hitem = _send_message_timeout(hwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem, timeout_ms=timeout_ms)
        position += 1
    return nodes


def _flatten_treeview_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for node in nodes:
        flat.append(node)
        flat.extend(_flatten_treeview_nodes(node.get("children") or []))
    return flat


_WIN32_CONTROL_ACTION_ALIASES = {
    "cleartext": "clear",
    "clear_text": "clear",
    "emptytext": "clear",
    "empty_text": "clear",
    "blanktext": "clear",
    "blank_text": "clear",
    "erasetext": "clear",
    "erase_text": "clear",
    "deletetext": "clear",
    "delete_text": "clear",
    "replaceall": "replace_all",
    "replacealltext": "replace_all",
    "replace_all_text": "replace_all",
    "replacetext": "replace_all",
    "replace_text": "replace_all",
    "selectall": "select_all",
    "select_all_text": "select_all",
    "deleteselection": "delete_selection",
    "delete_selection_text": "delete_selection",
    "clearselection": "delete_selection",
    "clear_selection": "delete_selection",
    "emptyselection": "delete_selection",
    "empty_selection": "delete_selection",
    "inputtext": "input_text",
    "write_text": "input_text",
    "writetext": "input_text",
    "appendtext": "append_text",
}

_WIN32_TEXT_SET_ACTIONS = {"set", "set_text", "set_value", "text", "replace_all"}
_WIN32_TEXT_REPLACE_SELECTION_ACTIONS = {"replace_selection", "replace_sel", "insert", "type", "input", "input_text"}
_WIN32_TEXT_APPEND_ACTIONS = {"append", "append_text"}
_WIN32_ITEM_ACTIVATE_ACTIONS = {"activate", "open", "double_click", "doubleclick", "invoke", "default", "press", "run", "launch"}


def _normalize_win32_control_action_name(action: Any) -> str:
    raw = str(action or "").strip()
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", raw)
    normalized = re.sub(r"[\s\-]+", "_", raw).lower()
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return _WIN32_CONTROL_ACTION_ALIASES.get(normalized, normalized)


def win32_control_action(
    hwnd: int,
    action: str,
    index: Optional[int] = None,
    text: Optional[str] = None,
    value: Optional[int] = None,
    checked: Optional[bool] = None,
    match: str = "contains",
    timeout_ms: int = 500,
) -> Dict[str, Any]:
    """Perform common native ComboBox/ComboBoxEx/ListBox/Button actions without coordinates."""
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/win32_control_action")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/win32_control_action",
            {
                "hwnd": hwnd,
                "action": action,
                "index": index,
                "text": text,
                "value": value,
                "checked": checked,
                "match": match,
                "timeout_ms": timeout_ms,
            },
            elevated=helper_elevated,
        )
        if _helper_ok(helper_result):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
    before = win32_control_info(hwnd, timeout_ms=timeout_ms)
    if "error" in before:
        return before
    info = before.get("window") or {}
    kind = before.get("kind", "")
    action_lower = _normalize_win32_control_action_name(action)
    resolved_index = index
    if resolved_index is None and text is not None:
        resolved_index = _find_item_index(before.get("items", []), text, match=match)
    result: Dict[str, Any] = {"hwnd": hwnd, "action": action_lower, "before": before}

    def _numeric_target(default_delta: int = 0) -> int:
        current = before.get("position")
        target = value
        if target is None and text is not None:
            target = int(text)
        if target is None and index is not None:
            target = int(index)
        if target is None and current is not None:
            target = int(current) + int(default_delta)
        if target is None:
            raise ValueError("value, index, or numeric text required")
        return int(target)

    if kind == "comboboxex" and action_lower in ("select", "set_cur_sel", "set_selection"):
        if resolved_index is None:
            return {"error": "index or text required", **result}
        target_hwnd = int(before.get("combo_hwnd") or hwnd)
        ok, msg_result = _send_message_timeout(target_hwnd, CB_SETCURSEL, int(resolved_index), 0, timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, CBN_SELCHANGE)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result != MESSAGE_RESULT_ERROR), "index": int(resolved_index), "result": msg_result, "combo_hwnd": target_hwnd, "notified_parent": notified, "after": after})
        return result

    if kind == "comboboxex" and action_lower in ("set_item_text", "set_text", "rename"):
        if resolved_index is None:
            selected_index = before.get("selected_index")
            if selected_index is not None and int(selected_index) >= 0:
                resolved_index = int(selected_index)
        if resolved_index is None:
            return {"error": "index required or an item must already be selected", **result}
        if text is None:
            return {"error": "text required", **result}
        ok, msg_result = _comboboxex_set_item_text(hwnd, int(resolved_index), text, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result), "index": int(resolved_index), "text": text, "result": msg_result, "after": after})
        return result

    if kind == "comboboxex" and action_lower in ("set_edit_text", "edit_text", "set_value"):
        edit_hwnd = int(before.get("edit_hwnd") or 0)
        if not edit_hwnd:
            return {"error": "ComboBoxEx has no child edit control", **result}
        if text is None:
            return {"error": "text required", **result}
        set_result = win32_set_text(edit_hwnd, text, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(set_result.get("ok")), "edit_hwnd": edit_hwnd, "set_result": set_result, "after": after})
        return result

    if kind == "combobox" and action_lower in ("select", "set_cur_sel", "set_selection"):
        if resolved_index is None:
            return {"error": "index or text required", **result}
        ok, msg_result = _send_message_timeout(hwnd, CB_SETCURSEL, int(resolved_index), 0, timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, CBN_SELCHANGE)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result != MESSAGE_RESULT_ERROR), "index": int(resolved_index), "result": msg_result, "notified_parent": notified, "after": after})
        return result

    if kind == "combobox" and action_lower in _WIN32_TEXT_SET_ACTIONS | {"clear", "set_edit_text", "edit_text"}:
        target_text = "" if action_lower == "clear" else text
        if target_text is None:
            return {"error": "text required", **result}
        edit_hwnd = int(before.get("edit_hwnd") or 0)
        if not bool(before.get("editable")) and not edit_hwnd:
            return {"error": "ComboBox is not editable; use select for dropdown-list items", **result}
        if edit_hwnd:
            ok_sel, sel_result = _combobox_set_edit_selection(hwnd, edit_hwnd, 0, -1, timeout_ms=timeout_ms)
            ok_replace, replace_result = _edit_replace_selection(edit_hwnd, str(target_text), timeout_ms=timeout_ms)
            action_result = {"selection_result": sel_result, "result": replace_result}
            ok = bool(ok_sel and ok_replace)
            method = "edit.EM_REPLACESEL"
        else:
            set_result = _win32_set_text_direct(hwnd, str(target_text), timeout_ms=timeout_ms)
            action_result = {"set_result": set_result}
            ok = bool(set_result.get("ok"))
            method = "combobox.WM_SETTEXT"
        notifications = _combobox_notify_edit_parent(info)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        after_text = str(after.get("current_text") or "") if isinstance(after, dict) else ""
        verified = after_text == str(target_text) if "error" not in after else None
        result.update({
            "ok": bool(ok and verified is not False),
            "text": str(target_text),
            "edit_hwnd": edit_hwnd,
            "method": method,
            "verified": verified,
            "notified_parent": bool(notifications.get("edit_update") or notifications.get("edit_change")),
            "notifications": notifications,
            **action_result,
            "after": after,
        })
        return result

    if kind == "combobox" and action_lower in ("select_range", "select_all"):
        edit_hwnd = int(before.get("edit_hwnd") or 0)
        if not bool(before.get("editable")) and not edit_hwnd:
            return {"error": "ComboBox is not editable; use select for dropdown-list items", **result}
        if action_lower == "select_all":
            start = 0
            end = -1
        elif index is None:
            return {"error": "index required as selection start", **result}
        else:
            start = int(index)
            end = value if value is not None else index
        ok, msg_result = _combobox_set_edit_selection(hwnd, edit_hwnd, int(start), int(end), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "start": int(start), "end": int(end), "edit_hwnd": edit_hwnd, "result": msg_result, "after": after})
        return result

    if kind == "combobox" and action_lower in _WIN32_TEXT_REPLACE_SELECTION_ACTIONS | {"delete_selection"}:
        target_text = "" if action_lower == "delete_selection" else text
        if target_text is None:
            return {"error": "text required", **result}
        edit_hwnd = int(before.get("edit_hwnd") or 0)
        if not bool(before.get("editable")) and not edit_hwnd:
            return {"error": "ComboBox is not editable; use select for dropdown-list items", **result}
        if edit_hwnd:
            ok, msg_result = _edit_replace_selection(edit_hwnd, str(target_text), timeout_ms=timeout_ms)
            action_result = {"result": msg_result}
            method = "edit.EM_REPLACESEL"
        else:
            before_text = str(before.get("current_text") or "")
            selection = before.get("edit_selection") if isinstance(before.get("edit_selection"), dict) else _combobox_edit_selection(hwnd, 0, timeout_ms=timeout_ms)
            start = max(min(int(selection.get("start", 0)), len(before_text)), 0)
            end = max(min(int(selection.get("end", start)), len(before_text)), start)
            new_text = before_text[:start] + str(target_text) + before_text[end:]
            set_result = _win32_set_text_direct(hwnd, new_text, timeout_ms=timeout_ms)
            ok = bool(set_result.get("ok"))
            action_result = {"set_result": set_result, "selection": {"start": start, "end": end}, "new_text": new_text}
            method = "combobox.WM_SETTEXT"
        notifications = _combobox_notify_edit_parent(info)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({
            "ok": bool(ok),
            "text": str(target_text),
            "edit_hwnd": edit_hwnd,
            "method": method,
            "notified_parent": bool(notifications.get("edit_update") or notifications.get("edit_change")),
            "notifications": notifications,
            **action_result,
            "after": after,
        })
        return result

    if kind == "combobox" and action_lower in _WIN32_TEXT_APPEND_ACTIONS:
        if text is None:
            return {"error": "text required", **result}
        edit_hwnd = int(before.get("edit_hwnd") or 0)
        if not bool(before.get("editable")) and not edit_hwnd:
            return {"error": "ComboBox is not editable; use select for dropdown-list items", **result}
        before_text = str(before.get("current_text") or "")
        length = len(before_text)
        if edit_hwnd:
            ok_sel, sel_result = _combobox_set_edit_selection(hwnd, edit_hwnd, length, length, timeout_ms=timeout_ms)
            ok_replace, replace_result = _edit_replace_selection(edit_hwnd, str(text), timeout_ms=timeout_ms)
            action_result = {"selection_result": sel_result, "result": replace_result}
            ok = bool(ok_sel and ok_replace)
            method = "edit.EM_REPLACESEL"
        else:
            set_result = _win32_set_text_direct(hwnd, before_text + str(text), timeout_ms=timeout_ms)
            action_result = {"set_result": set_result}
            ok = bool(set_result.get("ok"))
            method = "combobox.WM_SETTEXT"
        notifications = _combobox_notify_edit_parent(info)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({
            "ok": bool(ok),
            "start": length,
            "text": str(text),
            "edit_hwnd": edit_hwnd,
            "method": method,
            "notified_parent": bool(notifications.get("edit_update") or notifications.get("edit_change")),
            "notifications": notifications,
            **action_result,
            "after": after,
        })
        return result

    if kind == "listbox" and action_lower in ("select", "set_cur_sel", "set_selection"):
        if resolved_index is None:
            return {"error": "index or text required", **result}
        ok, msg_result = _send_message_timeout(hwnd, LB_SETCURSEL, int(resolved_index), 0, timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, LBN_SELCHANGE)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result != MESSAGE_RESULT_ERROR), "index": int(resolved_index), "result": msg_result, "notified_parent": notified, "after": after})
        return result

    if kind == "listbox" and action_lower in _WIN32_ITEM_ACTIVATE_ACTIONS:
        items = before.get("items") or []
        if resolved_index is None:
            resolved_index = _find_item_index(items, text, match=match)
        if resolved_index is None:
            return {"error": "index or text required", **result}
        if int(resolved_index) < 0 or int(resolved_index) >= int(before.get("count") or len(items)):
            return {"error": "listbox item index out of range", **result}
        activation = _listbox_activate_item(hwnd, int(resolved_index), info, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(activation.get("ok")), "index": int(resolved_index), "activation": activation, "after": after})
        return result

    if kind == "listbox" and action_lower in ("multi_select", "set_sel"):
        if resolved_index is None:
            return {"error": "index or text required", **result}
        set_value = 1 if checked is not False else 0
        ok, msg_result = _send_message_timeout(hwnd, LB_SETSEL, set_value, int(resolved_index), timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, LBN_SELCHANGE)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result != MESSAGE_RESULT_ERROR), "index": int(resolved_index), "selected": bool(set_value), "result": msg_result, "notified_parent": notified, "after": after})
        return result

    if kind == "scrollbar" and action_lower in ("set", "set_pos", "set_position", "position", "increment", "decrement", "page_up", "page_down", "top", "bottom"):
        current = int(before.get("position") or 0)
        minimum = int(before.get("min") or 0)
        maximum = int(before.get("max") if before.get("max") is not None else current)
        page = max(int(before.get("page") or 1), 1)
        code = SB_THUMBPOSITION
        if action_lower in ("increment",):
            target = current + 1
            code = SB_LINEDOWN if before.get("orientation") == "vertical" else SB_LINERIGHT
        elif action_lower in ("decrement",):
            target = current - 1
            code = SB_LINEUP if before.get("orientation") == "vertical" else SB_LINELEFT
        elif action_lower == "page_up":
            target = current - page
            code = SB_PAGEUP if before.get("orientation") == "vertical" else SB_PAGELEFT
        elif action_lower == "page_down":
            target = current + page
            code = SB_PAGEDOWN if before.get("orientation") == "vertical" else SB_PAGERIGHT
        elif action_lower == "top":
            target = minimum
            code = SB_TOP if before.get("orientation") == "vertical" else SB_LEFT
        elif action_lower == "bottom":
            target = maximum
            code = SB_BOTTOM if before.get("orientation") == "vertical" else SB_RIGHT
        else:
            try:
                target = _numeric_target()
            except Exception as e:
                return {"error": str(e), **result}
        target = _clamp_int(target, minimum, maximum)
        previous = _scrollbar_set_position(hwnd, target)
        notified_parent = _scrollbar_notify_parent(info, code, target, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(after.get("position") == target), "value": target, "previous": previous, "notified_parent": notified_parent, "after": after})
        return result

    if kind == "static" and action_lower in ("set", "set_text", "text", "clear"):
        target_text = "" if action_lower == "clear" else text
        if target_text is None:
            return {"error": "text required", **result}
        set_result = win32_set_text(hwnd, str(target_text), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(set_result.get("ok")), "text": target_text, "set_result": set_result, "after": after})
        return result

    if kind == "static" and action_lower in ("click", "press", "invoke"):
        ok, msg_result = _send_message_timeout(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, 0, timeout_ms=timeout_ms)
        up_ok, up_result = _send_message_timeout(hwnd, WM_LBUTTONUP, 0, 0, timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, STN_CLICKED)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and up_ok), "result": msg_result, "up_result": up_result, "notified_parent": notified, "after": after})
        return result

    if kind == "hotkey" and action_lower in ("set", "set_hotkey", "hotkey", "clear"):
        target_value: Any = 0 if action_lower == "clear" else text
        if target_value is None:
            target_value = value
        if target_value is None:
            return {"error": "text or value required as hotkey", **result}
        try:
            hotkey_word = _parse_hotkey(target_value)
        except Exception as e:
            return {"error": str(e), **result}
        ok, msg_result = _send_message_timeout(hwnd, HKM_SETHOTKEY, hotkey_word, 0, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "hotkey": _hotkey_word_to_dict(hotkey_word), "result": msg_result, "after": after})
        return result

    if kind == "syslink" and action_lower in ("set", "set_text", "text", "clear"):
        target_text = "" if action_lower == "clear" else text
        if target_text is None:
            return {"error": "text required", **result}
        set_result = win32_set_text(hwnd, str(target_text), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(set_result.get("ok")), "text": target_text, "set_result": set_result, "after": after})
        return result

    if kind == "syslink" and action_lower in ("select", "click", "press", "invoke"):
        links = before.get("links") or before.get("items") or []
        target_index = resolved_index
        if target_index is None and text is not None:
            target_index = _find_item_index(links, text, match=match)
        if target_index is None:
            return {"error": "index or text required", **result}
        x = 4
        y = 4 + int(target_index) * 16
        lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
        down_ok, down_result = _send_message_timeout(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam, timeout_ms=timeout_ms)
        up_ok, up_result = _send_message_timeout(hwnd, WM_LBUTTONUP, 0, lparam, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(down_ok and up_ok), "index": int(target_index), "lparam": lparam, "down_result": down_result, "up_result": up_result, "after": after})
        return result

    if kind == "syslink" and action_lower in ("set_visited", "visited", "mark_visited"):
        links = before.get("links") or before.get("items") or []
        target_index = resolved_index
        if target_index is None and text is not None:
            target_index = _find_item_index(links, text, match=match)
        if target_index is None:
            return {"error": "index or text required", **result}
        target = True if checked is None else bool(checked)
        ok, msg_result = _syslink_set_item_visited(hwnd, int(target_index), target, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result), "index": int(target_index), "visited": target, "result": msg_result, "after": after})
        return result

    if kind == "header" and action_lower in ("select", "click", "press", "invoke", "sort"):
        items = before.get("items") or []
        target_index = resolved_index
        if target_index is None and text is not None:
            target_index = _find_item_index(items, text, match=match)
        if target_index is None:
            return {"error": "index or text required", **result}
        if int(target_index) < 0 or int(target_index) >= len(items):
            return {"error": "header item index out of range", **result}
        click = _header_click_item(hwnd, items[int(target_index)], timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(click.get("ok")), "index": int(target_index), "click": click, "after": after})
        return result

    if kind == "header" and action_lower in ("set_text", "text", "rename"):
        target_index = int(resolved_index if resolved_index is not None else 0)
        if text is None:
            return {"error": "text required", **result}
        ok, msg_result = _header_set_item(hwnd, target_index, text=text, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result), "index": target_index, "text": text, "result": msg_result, "after": after})
        return result

    if kind == "header" and action_lower in ("set_width", "width", "set_column_width", "column_width"):
        target_index = int(resolved_index if resolved_index is not None else 0)
        width = value
        if width is None and text is not None:
            width = int(text)
        if width is None:
            return {"error": "value required as width", **result}
        ok, msg_result = _header_set_item(hwnd, target_index, width=int(width), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result), "index": target_index, "width": int(width), "result": msg_result, "after": after})
        return result

    if kind == "header" and action_lower in ("set_order", "order"):
        raw_order = text
        if raw_order is None:
            return {"error": "text required as comma-separated or JSON order array", **result}
        try:
            parsed = json.loads(raw_order)
            order = [int(item) for item in parsed] if isinstance(parsed, list) else []
        except Exception:
            order = [int(part.strip()) for part in str(raw_order).split(",") if part.strip()]
        count = int(before.get("count") or len(order))
        if len(order) != count or sorted(order) != list(range(count)):
            return {"error": "order must contain each header index exactly once", "count": count, **result}
        ok, msg_result = _header_set_order(hwnd, order, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result), "order": order, "result": msg_result, "after": after})
        return result

    if kind == "listview" and action_lower in ("select", "set_selection", "focus", "ensure_visible"):
        if resolved_index is None:
            resolved_index = _find_item_index(before.get("items", []), text, match=match)
        if resolved_index is None:
            return {"error": "index or text required", **result}
        if action_lower == "ensure_visible":
            ok, msg_result = _send_message_timeout(hwnd, LVM_ENSUREVISIBLE, int(resolved_index), 0, timeout_ms=timeout_ms)
        else:
            ok, msg_result = _listview_set_item_state(hwnd, int(resolved_index), LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED, timeout_ms=timeout_ms)
            _send_message_timeout(hwnd, LVM_ENSUREVISIBLE, int(resolved_index), 0, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "index": int(resolved_index), "result": msg_result, "after": after})
        return result

    if kind == "listview" and action_lower in _WIN32_ITEM_ACTIVATE_ACTIONS:
        items = before.get("items") or []
        if resolved_index is None:
            resolved_index = _find_item_index(items, text, match=match)
        if resolved_index is None:
            return {"error": "index or text required", **result}
        if int(resolved_index) < 0 or int(resolved_index) >= int(before.get("count") or len(items)):
            return {"error": "listview item index out of range", **result}
        activation = _listview_activate_item(hwnd, int(resolved_index), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(activation.get("ok")), "index": int(resolved_index), "activation": activation, "after": after})
        return result

    if kind == "listview" and action_lower in ("check", "uncheck", "toggle", "set_check"):
        items = before.get("items") or []
        if resolved_index is None:
            resolved_index = _find_item_index(items, text, match=match)
        if resolved_index is None:
            return {"error": "index or text required", **result}
        if int(resolved_index) < 0 or int(resolved_index) >= len(items):
            return {"error": "listview item index out of range", **result}
        current = items[int(resolved_index)].get("checked")
        if checked is not None:
            target = bool(checked)
        elif action_lower == "uncheck":
            target = False
        elif action_lower == "toggle":
            if current is None:
                item = items[int(resolved_index)]
                return {
                    "error": "cannot toggle an unknown/custom ListView checkbox state; use check/uncheck/set_check explicitly",
                    "index": int(resolved_index),
                    "check_state": item.get("check_state"),
                    "state_image": item.get("state_image"),
                    **result,
                }
            target = not bool(current)
        else:
            target = True
        ok, msg_result = _listview_set_check_state(hwnd, int(resolved_index), target, timeout_ms=timeout_ms)
        _send_message_timeout(hwnd, LVM_ENSUREVISIBLE, int(resolved_index), 0, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "index": int(resolved_index), "checked": target, "result": msg_result, "after": after})
        return result

    if kind == "listview" and action_lower in ("set_cell", "set_item_text", "set_subitem_text"):
        if resolved_index is None:
            selected_index = before.get("selected_index")
            if selected_index is not None and int(selected_index) >= 0:
                resolved_index = int(selected_index)
        if resolved_index is None:
            return {"error": "index required or an item must already be selected", **result}
        column_index = int(value if value is not None else 0)
        target_text = text
        if target_text is None:
            return {"error": "text required", **result}
        ok, msg_result = _listview_set_item_text(hwnd, int(resolved_index), column_index, target_text, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "index": int(resolved_index), "column": column_index, "text": target_text, "result": msg_result, "after": after})
        return result

    if kind == "listview" and action_lower in ("set_column_width", "column_width"):
        column_index = int(index if index is not None else 0)
        width = value
        if width is None and text is not None:
            width = int(text)
        if width is None:
            return {"error": "value required as width", **result}
        ok, msg_result = _send_message_timeout(hwnd, LVM_SETCOLUMNWIDTH, column_index, int(width), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "column": column_index, "width": int(width), "result": msg_result, "after": after})
        return result

    if kind == "treeview" and action_lower in ("select", "ensure_visible", "expand", "collapse"):
        flat = before.get("flat") or []
        target_node = None
        target_index = None
        if index is not None and 0 <= int(index) < len(flat):
            target_index = int(index)
            target_node = flat[target_index]
        elif text is not None:
            match_index = _find_item_index(flat, text, match=match)
            if match_index is not None:
                target_index = int(match_index)
                target_node = flat[match_index]
        if target_node is None:
            return {"error": "index or text required", **result}
        handle = int(target_node.get("handle") or 0)
        if action_lower == "expand":
            ok, msg_result = _send_message_timeout(hwnd, TVM_EXPAND, TVE_EXPAND, handle, timeout_ms=timeout_ms)
        elif action_lower == "collapse":
            ok, msg_result = _send_message_timeout(hwnd, TVM_EXPAND, TVE_COLLAPSE, handle, timeout_ms=timeout_ms)
        else:
            ok, msg_result = _send_message_timeout(hwnd, TVM_SELECTITEM, TVGN_CARET, handle, timeout_ms=timeout_ms)
            _send_message_timeout(hwnd, TVM_ENSUREVISIBLE, 0, handle, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "index": target_index, "handle": handle, "result": msg_result, "after": after})
        return result

    if kind == "treeview" and action_lower in _WIN32_ITEM_ACTIVATE_ACTIONS:
        flat = before.get("flat") or []
        target_node = None
        target_index = None
        if index is not None and 0 <= int(index) < len(flat):
            target_index = int(index)
            target_node = flat[target_index]
        elif text is not None:
            match_index = _find_item_index(flat, text, match=match)
            if match_index is not None:
                target_index = int(match_index)
                target_node = flat[match_index]
        if target_node is None:
            return {"error": "index or text required", **result}
        handle = int(target_node.get("handle") or 0)
        activation = _treeview_activate_item(hwnd, handle, index=target_index, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(activation.get("ok")), "index": target_index, "handle": handle, "activation": activation, "after": after})
        return result

    if kind == "treeview" and action_lower in ("check", "uncheck", "toggle", "set_check"):
        flat = before.get("flat") or []
        target_node = None
        target_index = None
        if index is not None and 0 <= int(index) < len(flat):
            target_index = int(index)
            target_node = flat[target_index]
        elif text is not None:
            match_index = _find_item_index(flat, text, match=match)
            if match_index is not None:
                target_index = int(match_index)
                target_node = flat[target_index]
        if target_node is None:
            return {"error": "index or text required", **result}
        handle = int(target_node.get("handle") or 0)
        current = target_node.get("checked")
        if checked is not None:
            target = bool(checked)
        elif action_lower == "uncheck":
            target = False
        elif action_lower == "toggle":
            if current is None:
                return {
                    "error": "cannot toggle an unknown/custom TreeView checkbox state; use check/uncheck/set_check explicitly",
                    "index": target_index,
                    "handle": handle,
                    "check_state": target_node.get("check_state"),
                    "state_image": target_node.get("state_image"),
                    **result,
                }
            target = not bool(current)
        else:
            target = True
        ok, msg_result = _treeview_set_check_state(hwnd, handle, target, timeout_ms=timeout_ms)
        _send_message_timeout(hwnd, TVM_ENSUREVISIBLE, 0, handle, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "index": target_index, "handle": handle, "checked": target, "result": msg_result, "after": after})
        return result

    if kind == "tab" and action_lower in ("select", "set_cur_sel", "set_selection"):
        if resolved_index is None:
            resolved_index = _find_item_index(before.get("items", []), text, match=match)
        if resolved_index is None:
            return {"error": "index or text required", **result}
        changing = _win32_notify_parent_nmhdr(info, TCN_SELCHANGING, timeout_ms=timeout_ms)
        if changing.get("ok") and int(changing.get("result") or 0) != 0:
            after = win32_control_info(hwnd, timeout_ms=timeout_ms)
            result.update({
                "ok": False,
                "index": int(resolved_index),
                "error": "tab selection rejected by parent TCN_SELCHANGING notification",
                "notification_changing": changing,
                "after": after,
            })
            return result
        ok, msg_result = _send_message_timeout(hwnd, TCM_SETCURSEL, int(resolved_index), 0, timeout_ms=timeout_ms)
        changed = _win32_notify_parent_nmhdr(info, TCN_SELCHANGE, timeout_ms=timeout_ms) if ok and msg_result != MESSAGE_RESULT_ERROR else None
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        notification_ok = (not int(info.get("parent_hwnd") or 0)) or bool(changing.get("ok") and (changed or {}).get("ok"))
        result.update({
            "ok": bool(ok and msg_result != MESSAGE_RESULT_ERROR and notification_ok),
            "index": int(resolved_index),
            "result": msg_result,
            "notification_changing": changing,
            "notification_changed": changed,
            "notified_parent": bool(changing.get("ok") and (changed or {}).get("ok")),
            "after": after,
        })
        return result

    if kind == "toolbar" and action_lower in ("press", "click", "invoke", "check", "uncheck", "toggle"):
        buttons = before.get("buttons") or before.get("items") or []
        target_button = None
        target_index = None
        if index is not None and 0 <= int(index) < len(buttons):
            target_index = int(index)
            target_button = buttons[target_index]
        elif text is not None:
            match_index = _find_item_index(buttons, text, match=match)
            if match_index is not None:
                target_index = int(match_index)
                target_button = buttons[match_index]
        if target_button is None:
            return {"error": "index or text required", **result}
        if target_button.get("separator"):
            return {"error": "toolbar target is a separator", "index": target_index, **result}
        if target_button.get("enabled") is False:
            return {"error": "toolbar target is disabled", "index": target_index, **result}
        command_id = int(target_button.get("command_id") or 0)
        if action_lower in ("check", "uncheck", "toggle"):
            target = not bool(target_button.get("checked")) if action_lower == "toggle" else action_lower == "check"
            activation = _toolbar_button_action(
                hwnd,
                int(target_index if target_index is not None else target_button.get("index") or 0),
                command_id,
                info,
                check_target=target,
                rect=target_button.get("rect"),
                timeout_ms=timeout_ms,
            )
        else:
            activation = _toolbar_button_action(
                hwnd,
                int(target_index if target_index is not None else target_button.get("index") or 0),
                command_id,
                info,
                rect=target_button.get("rect"),
                timeout_ms=timeout_ms,
            )
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({
            "ok": bool(activation.get("ok")),
            "index": target_index,
            "command_id": command_id,
            "activation": activation,
            "result": activation.get("result", activation.get("press_result")),
            "notified_parent": bool(activation.get("notified_parent")),
            "after": after,
        })
        return result

    if kind == "statusbar" and action_lower in ("set_text", "set", "text"):
        parts = before.get("parts") or before.get("items") or []
        target_index = int(resolved_index if resolved_index is not None else 0)
        if target_index < 0 or target_index >= max(len(parts), 1):
            return {"error": "statusbar part index out of range", **result}
        if text is None:
            return {"error": "text required", **result}
        ok, msg_result = _set_statusbar_part_text(hwnd, target_index, text, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "index": target_index, "text": text, "result": msg_result, "after": after})
        return result

    if kind == "trackbar" and action_lower in ("set", "set_pos", "set_position", "position", "increment", "decrement"):
        try:
            delta = 1 if action_lower == "increment" else -1 if action_lower == "decrement" else 0
            target = _numeric_target(default_delta=delta)
        except Exception as e:
            return {"error": str(e), **result}
        target = _clamp_int(target, before.get("min"), before.get("max"))
        ok, msg_result = _send_message_timeout(hwnd, TBM_SETPOS, 1, target, timeout_ms=timeout_ms)
        scroll_msg = WM_VSCROLL if (int(info.get("style") or 0) & TBS_VERT) else WM_HSCROLL
        parent = int(info.get("parent_hwnd") or 0)
        notified_parent = False
        if parent:
            wparam = ((target & 0xFFFF) << 16) | TB_THUMBPOSITION
            notify_ok, _ = _send_message_timeout(parent, scroll_msg, wparam, hwnd, timeout_ms=timeout_ms)
            end_ok, _ = _send_message_timeout(parent, scroll_msg, TB_ENDTRACK, hwnd, timeout_ms=timeout_ms)
            notified_parent = bool(notify_ok or end_ok)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "value": target, "result": msg_result, "notified_parent": notified_parent, "after": after})
        return result

    if kind == "updown" and action_lower in ("set", "set_pos", "set_position", "position", "increment", "decrement"):
        try:
            delta = 1 if action_lower == "increment" else -1 if action_lower == "decrement" else 0
            target = _numeric_target(default_delta=delta)
        except Exception as e:
            return {"error": str(e), **result}
        target = _clamp_int(target, before.get("min"), before.get("max"))
        ok, msg_result = _send_message_timeout(hwnd, UDM_SETPOS32, 0, target, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "value": target, "result": msg_result, "after": after})
        return result

    if kind == "progress" and action_lower in ("set", "set_pos", "set_position", "position", "increment", "decrement", "step"):
        if action_lower == "step":
            ok, msg_result = _send_message_timeout(hwnd, PBM_STEPIT, 0, 0, timeout_ms=timeout_ms)
            after = win32_control_info(hwnd, timeout_ms=timeout_ms)
            result.update({"ok": bool(ok), "result": msg_result, "after": after})
            return result
        try:
            delta = 1 if action_lower == "increment" else -1 if action_lower == "decrement" else 0
            target = _numeric_target(default_delta=delta)
        except Exception as e:
            return {"error": str(e), **result}
        target = _clamp_int(target, before.get("min"), before.get("max"))
        ok, msg_result = _send_message_timeout(hwnd, PBM_SETPOS, target, 0, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "value": target, "result": msg_result, "after": after})
        return result

    if kind in ("datetime", "monthcal") and action_lower in ("set", "set_date", "set_time", "set_datetime", "date", "time"):
        target_value = text
        if target_value is None and value is not None:
            target_value = value
        if target_value is None:
            return {"error": "text or value required", **result}
        try:
            message = DTM_SETSYSTEMTIME if kind == "datetime" else MCM_SETCURSEL
            ok, msg_result = _set_systemtime_control(hwnd, message, target_value, timeout_ms=timeout_ms, datetime_picker=(kind == "datetime"))
        except Exception as e:
            return {"error": str(e), **result}
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok and msg_result), "value": target_value, "result": msg_result, "after": after})
        return result

    if kind == "ipaddress" and action_lower in ("set", "set_address", "address", "clear"):
        if action_lower == "clear":
            ok, msg_result = _send_message_timeout(hwnd, IPM_CLEARADDRESS, 0, 0, timeout_ms=timeout_ms)
            after = win32_control_info(hwnd, timeout_ms=timeout_ms)
            result.update({"ok": bool(ok), "result": msg_result, "after": after})
            return result
        target_value = text
        if target_value is None and value is not None:
            target_value = value
        if target_value is None:
            return {"error": "text or value required", **result}
        try:
            address_value = _parse_ip_address(target_value)
        except Exception as e:
            return {"error": str(e), **result}
        ok, msg_result = _send_message_timeout(hwnd, IPM_SETADDRESS, 0, address_value, timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "value": address_value, "address": _ip_address_to_string(address_value), "result": msg_result, "after": after})
        return result

    if kind == "edit" and action_lower in _WIN32_TEXT_SET_ACTIONS | {"clear"}:
        target_text = "" if action_lower == "clear" else text
        if target_text is None:
            return {"error": "text required", **result}
        ok_sel, sel_result = _edit_set_selection(hwnd, 0, -1, timeout_ms=timeout_ms)
        ok_replace, replace_result = _edit_replace_selection(hwnd, str(target_text), timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, EN_CHANGE)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok_sel and ok_replace), "text": str(target_text), "selection_result": sel_result, "result": replace_result, "notified_parent": notified, "after": after})
        return result

    if kind == "edit" and action_lower in ("select", "select_range", "set_selection", "select_all"):
        if action_lower == "select_all":
            start = 0
            end = -1
        elif index is None:
            return {"error": "index required as selection start", **result}
        else:
            start = int(index)
            end = value if value is not None else index
        ok, msg_result = _edit_set_selection(hwnd, int(start), int(end), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "start": int(start), "end": int(end), "result": msg_result, "after": after})
        return result

    if kind == "edit" and action_lower in _WIN32_TEXT_REPLACE_SELECTION_ACTIONS | {"delete_selection"}:
        target_text = "" if action_lower == "delete_selection" else text
        if target_text is None:
            return {"error": "text required", **result}
        ok, msg_result = _edit_replace_selection(hwnd, str(target_text), timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, EN_CHANGE)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "text": str(target_text), "result": msg_result, "notified_parent": notified, "after": after})
        return result

    if kind == "edit" and action_lower in _WIN32_TEXT_APPEND_ACTIONS:
        if text is None:
            return {"error": "text required", **result}
        length = int((before.get("text") or {}).get("length") or len((before.get("text") or {}).get("text") or ""))
        ok_sel, sel_result = _edit_set_selection(hwnd, length, length, timeout_ms=timeout_ms)
        ok_replace, replace_result = _edit_replace_selection(hwnd, str(text), timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, EN_CHANGE)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok_sel and ok_replace), "start": length, "text": str(text), "selection_result": sel_result, "result": replace_result, "notified_parent": notified, "after": after})
        return result

    if kind == "richedit" and action_lower in _WIN32_TEXT_SET_ACTIONS | {"clear"}:
        target_text = "" if action_lower == "clear" else text
        if target_text is None:
            return {"error": "text required", **result}
        ok_sel, sel_result = _richedit_set_selection(hwnd, 0, -1, timeout_ms=timeout_ms)
        ok_replace, replace_result = _richedit_replace_selection(hwnd, str(target_text), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok_sel and ok_replace), "text": str(target_text), "selection_result": sel_result, "result": replace_result, "after": after})
        return result

    if kind == "richedit" and action_lower in ("select", "select_range", "set_selection", "select_all"):
        if action_lower == "select_all":
            start = 0
            end = -1
        elif index is None:
            return {"error": "index required as selection start", **result}
        else:
            start = int(index)
            end = value if value is not None else index
        ok, msg_result = _richedit_set_selection(hwnd, int(start), int(end), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "start": int(start), "end": int(end), "result": msg_result, "after": after})
        return result

    if kind == "richedit" and action_lower in _WIN32_TEXT_REPLACE_SELECTION_ACTIONS | {"delete_selection"}:
        target_text = "" if action_lower == "delete_selection" else text
        if target_text is None:
            return {"error": "text required", **result}
        ok, msg_result = _richedit_replace_selection(hwnd, str(target_text), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "text": str(target_text), "result": msg_result, "after": after})
        return result

    if kind == "richedit" and action_lower in _WIN32_TEXT_APPEND_ACTIONS:
        if text is None:
            return {"error": "text required", **result}
        length = int((before.get("text") or {}).get("length") or len((before.get("text") or {}).get("text") or ""))
        ok_sel, sel_result = _richedit_set_selection(hwnd, length, length, timeout_ms=timeout_ms)
        ok_replace, replace_result = _richedit_replace_selection(hwnd, str(text), timeout_ms=timeout_ms)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok_sel and ok_replace), "start": length, "text": str(text), "selection_result": sel_result, "result": replace_result, "after": after})
        return result

    if kind in ("checkbox", "3state", "radio", "button") and action_lower in ("click", "press", "invoke", "default", "do_default", "default_action"):
        ok, msg_result = _send_message_timeout(hwnd, BM_CLICK, 0, 0, timeout_ms=timeout_ms)
        post_ok = False
        method = "SendMessageTimeoutW"
        if not ok:
            post_ok = bool(user32.PostMessageW(hwnd, BM_CLICK, 0, 0))
            method = "PostMessageW"
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok or post_ok), "method": method, "result": msg_result, "posted": bool(post_ok), "after": after})
        return result

    if kind in ("checkbox", "3state", "radio", "button") and action_lower in ("check", "uncheck", "toggle", "set_check"):
        current = before.get("check_state")
        if action_lower == "toggle":
            target = BST_UNCHECKED if current == BST_CHECKED else BST_CHECKED
        elif checked is not None:
            target = BST_CHECKED if checked else BST_UNCHECKED
        elif action_lower == "uncheck":
            target = BST_UNCHECKED
        else:
            target = BST_CHECKED
        ok, msg_result = _send_message_timeout(hwnd, BM_SETCHECK, target, 0, timeout_ms=timeout_ms)
        notified = _win32_notify_parent(info, BN_CLICKED)
        after = win32_control_info(hwnd, timeout_ms=timeout_ms)
        result.update({"ok": bool(ok), "check_state": target, "result": msg_result, "notified_parent": notified, "after": after})
        return result

    return {
        "error": f"Unsupported control action: {action}",
        "kind": kind,
        "supported": ["select", "multi_select", "set_cell", "set_item_text", "set_edit_text", "set_column_width", "set_width", "set_order", "expand", "collapse", "press", "click", "invoke", "default", "set", "set_text", "set_value", "set_hotkey", "set_visited", "select_range", "select_all", "replace_selection", "delete_selection", "input_text", "append", "set_date", "set_address", "clear", "clear_text", "empty_text", "increment", "decrement", "page_up", "page_down", "top", "bottom", "step", "check", "uncheck", "toggle", "set_check"],
        **result,
    }



