"""
Microsoft Active Accessibility (MSAA) / IAccessible inspection and action execution.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.win32_structures import *
from win_automation.core.utils import is_valid_hwnd
from win_automation.win32.window import _win32_window_info
from win_automation.helper.client import (
    _helper_route_for_hwnd,
    _helper_route_for_screen_point,
    _helper_post,
    _elevated_helper_required_message,
    _helper_ok,
    _is_terminal_uia_helper_error,
)
from win_automation.uia.engine import element_from_point


_MSAA_ACCESSIBILITY = None

def msaa_module():
    return _msaa_module()



def _msaa_module():
    """Load the MSAA type library and return comtypes.gen.Accessibility."""
    global _MSAA_ACCESSIBILITY
    if _MSAA_ACCESSIBILITY is not None:
        return _MSAA_ACCESSIBILITY
    try:
        import comtypes
        import comtypes.client
    except ImportError as e:
        raise RuntimeError("comtypes_unavailable") from e
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    try:
        import comtypes.gen.Accessibility as Accessibility
    except Exception:
        comtypes.client.GetModule("oleacc.dll")
        import comtypes.gen.Accessibility as Accessibility
    _MSAA_ACCESSIBILITY = Accessibility
    return Accessibility


def _msaa_variant(child_id: int = MSAA_SELF):
    from comtypes.automation import VARIANT
    return VARIANT(int(child_id))


def _msaa_role_text(role: Any) -> str:
    try:
        role_int = int(role)
    except Exception:
        return str(role) if role is not None else ""
    buf = ctypes.create_unicode_buffer(128)
    try:
        oleacc = ctypes.windll.oleacc
        oleacc.GetRoleTextW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        oleacc.GetRoleTextW.restype = ctypes.c_uint
        oleacc.GetRoleTextW(role_int, buf, 128)
        return buf.value
    except Exception:
        return ""


def _msaa_state_texts(state: Any) -> List[str]:
    try:
        state_int = int(state)
    except Exception:
        return []
    if state_int == 0:
        return ["正常"]
    texts: List[str] = []
    oleacc = ctypes.windll.oleacc
    try:
        oleacc.GetStateTextW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        oleacc.GetStateTextW.restype = ctypes.c_uint
    except Exception:
        pass
    bit = 1
    while bit <= 0x40000000:
        if state_int & bit:
            buf = ctypes.create_unicode_buffer(128)
            try:
                oleacc.GetStateTextW(bit, buf, 128)
                texts.append(buf.value or hex(bit))
            except Exception:
                texts.append(hex(bit))
        bit <<= 1
    return texts


def _msaa_object_from_window(hwnd: int):
    Accessibility = _msaa_module()
    ptr = ctypes.POINTER(Accessibility.IAccessible)()
    hr = ctypes.oledll.oleacc.AccessibleObjectFromWindow(
        ctypes.c_void_p(hwnd),
        ctypes.c_ulong(OBJID_CLIENT),
        ctypes.byref(Accessibility.IAccessible._iid_),
        ctypes.byref(ptr),
    )
    if hr != 0 or not ptr:
        raise RuntimeError(f"AccessibleObjectFromWindow failed: hr={hr}")
    return ptr


def _msaa_object_from_point(screen_x: int, screen_y: int):
    Accessibility = _msaa_module()
    ptr = ctypes.POINTER(Accessibility.IAccessible)()
    child = _msaa_variant()
    point = ctypes.wintypes.POINT(int(screen_x), int(screen_y))
    hr = ctypes.oledll.oleacc.AccessibleObjectFromPoint(point, ctypes.byref(ptr), ctypes.byref(child))
    if hr != 0 or not ptr:
        raise RuntimeError(f"AccessibleObjectFromPoint failed: hr={hr}")
    return ptr, int(child.value or 0)


def _msaa_object_from_path(root_acc: Any, path: List[int]):
    Accessibility = _msaa_module()
    acc = root_acc
    child_id = MSAA_SELF
    for child_index in path:
        children = _msaa_children(acc, max_count=max(int(child_index) + 1, 1))
        matches = [child for child in children if int(child.get("path", [-1])[-1]) == int(child_index)]
        if not matches:
            raise RuntimeError(f"MSAA child path not found: {path}")
        match = matches[0]
        child_obj = match.get("_object")
        if child_obj is not None:
            acc = child_obj.QueryInterface(Accessibility.IAccessible)
            child_id = MSAA_SELF
        else:
            child_id = int(match.get("child_id", MSAA_SELF))
    return acc, child_id


def _msaa_location(acc: Any, child_id: int = MSAA_SELF) -> Dict[str, int]:
    try:
        left, top, width, height = acc.accLocation(_msaa_variant(child_id))
        return {
            "left": int(left),
            "top": int(top),
            "right": int(left + width),
            "bottom": int(top + height),
            "width": int(width),
            "height": int(height),
            "center_x": int(left + width // 2),
            "center_y": int(top + height // 2),
        }
    except Exception:
        return _rect_tuple_to_dict((0, 0, 0, 0))


def _msaa_get_named(acc: Any, name: str, child_id: int = MSAA_SELF) -> Any:
    try:
        return getattr(acc, name)(_msaa_variant(child_id))
    except Exception:
        return None


def _msaa_info(acc: Any, child_id: int = MSAA_SELF, hwnd: Optional[int] = None, path: Optional[List[int]] = None) -> Dict[str, Any]:
    role = _msaa_get_named(acc, "accRole", child_id)
    state = _msaa_get_named(acc, "accState", child_id)
    info = {
        "hwnd": hwnd,
        "child_id": int(child_id),
        "path": path or [],
        "name": _msaa_get_named(acc, "accName", child_id),
        "value": _msaa_get_named(acc, "accValue", child_id),
        "description": _msaa_get_named(acc, "accDescription", child_id),
        "role": role,
        "role_text": _msaa_role_text(role),
        "state": state,
        "state_text": _msaa_state_texts(state),
        "default_action": _msaa_get_named(acc, "accDefaultAction", child_id),
        "keyboard_shortcut": _msaa_get_named(acc, "accKeyboardShortcut", child_id),
        "location": _msaa_location(acc, child_id),
    }
    try:
        info["child_count"] = int(acc.accChildCount) if child_id == MSAA_SELF else 0
    except Exception:
        info["child_count"] = 0
    return info


def _msaa_children(acc: Any, max_count: int = 100, path_prefix: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    Accessibility = _msaa_module()
    from comtypes.automation import VARIANT
    try:
        child_count = int(acc.accChildCount or 0)
    except Exception:
        return []
    count = min(max(child_count, 0), max(int(max_count), 0))
    if count <= 0:
        return []
    arr = (VARIANT * count)()
    obtained = ctypes.c_long()
    hr = ctypes.oledll.oleacc.AccessibleChildren(acc, 0, count, arr, ctypes.byref(obtained))
    if hr != 0:
        return []
    results: List[Dict[str, Any]] = []
    prefix = path_prefix or []
    for i in range(int(obtained.value)):
        variant = arr[i]
        child_path = prefix + [i]
        item: Dict[str, Any]
        if int(variant.vt) == 9 and variant.value is not None:
            child_acc = variant.value.QueryInterface(Accessibility.IAccessible)
            item = _msaa_info(child_acc, MSAA_SELF, path=child_path)
            item["_object"] = child_acc
            item["object_type"] = "IAccessible"
        else:
            child_id = int(variant.value or 0)
            item = _msaa_info(acc, child_id, path=child_path)
            item["object_type"] = "child_id"
        results.append(item)
    return results


def _strip_msaa_private(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _strip_msaa_private(v) for k, v in data.items() if k != "_object"}
    if isinstance(data, list):
        return [_strip_msaa_private(v) for v in data]
    return data


def msaa_window(hwnd: int, max_children: int = 80) -> Dict[str, Any]:
    """Return MSAA/IAccessible metadata for a window client object."""
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/msaa_window")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/msaa_window",
            {"hwnd": hwnd, "max_children": max_children},
            elevated=helper_elevated,
        )
        if "error" not in helper_result:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
        if _is_terminal_uia_helper_error(helper_result):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
    try:
        acc = _msaa_object_from_window(hwnd)
        root = _msaa_info(acc, MSAA_SELF, hwnd=hwnd, path=[])
        children = _msaa_children(acc, max_count=max_children)
        return _strip_msaa_private({"hwnd": hwnd, "root": root, "child_count": root.get("child_count", 0), "children": children})
    except Exception as e:
        return {"error": str(e), "hwnd": hwnd}


def msaa_from_point(
    x: Optional[int] = None,
    y: Optional[int] = None,
    hwnd: Optional[int] = None,
    screenshot_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Return MSAA/IAccessible metadata under a screen or screenshot point."""
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
    helper_ready, helper_elevated, point_hwnd, boundary_result = _helper_route_for_screen_point(screen_x, screen_y, "/msaa_from_point")
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
            "/msaa_from_point",
            {"x": screen_x, "y": screen_y},
            elevated=helper_elevated,
        )
        if "error" not in helper_result:
            helper_result["input"] = {"x": x, "y": y, "hwnd": hwnd, "screenshot_id": screenshot_id}
            helper_result["screen"] = {"x": screen_x, "y": screen_y}
            helper_result["debug"] = debug
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            helper_result["point_hwnd"] = int(point_hwnd or 0)
            return helper_result
    try:
        acc, child_id = _msaa_object_from_point(screen_x, screen_y)
        info = _msaa_info(acc, child_id, hwnd=hwnd, path=[])
        return {
            "input": {"x": x, "y": y, "hwnd": hwnd, "screenshot_id": screenshot_id},
            "screen": {"x": screen_x, "y": screen_y},
            "debug": debug,
            "msaa": info,
            "window": window_from_point(screen_x, screen_y, include_text=True),
        }
    except Exception as e:
        return {"error": str(e), "screen": {"x": screen_x, "y": screen_y}, "debug": debug}


def _mouse_context_targets(window_result: Dict[str, Any]) -> Dict[str, Any]:
    targets: Dict[str, Any] = {}
    if not isinstance(window_result, dict):
        return targets
    for key in ("window", "child", "real_child", "root", "root_owner"):
        item = window_result.get(key)
        if isinstance(item, dict) and item.get("hwnd"):
            targets[key] = int(item.get("hwnd") or 0)
    return targets


def mouse_context(
    x: Optional[int] = None,
    y: Optional[int] = None,
    hwnd: Optional[int] = None,
    screenshot_id: Optional[int] = None,
    include_text: bool = False,
    include_uia: bool = True,
    include_msaa: bool = True,
) -> Dict[str, Any]:
    """Return a no-click diagnostic bundle for the cursor or a target point."""
    if x is None or y is None:
        pos = mouse_position()
        if "error" in pos:
            return {"ok": False, **pos}
        x, y = int(pos["x"]), int(pos["y"])
        source = "cursor"
    else:
        source = "point"

    if hwnd is not None:
        screen_x, screen_y, debug = _scale_coords(hwnd, int(x), int(y), screenshot_id)
    else:
        screen_x, screen_y = int(x), int(y)
        debug = "current cursor position" if source == "cursor" else "input coordinates treated as screen coordinates"

    window_result = window_from_point(screen_x, screen_y, include_text=include_text)
    result: Dict[str, Any] = {
        "ok": not (isinstance(window_result, dict) and window_result.get("ok") is False),
        "source": source,
        "input": {"x": x, "y": y, "hwnd": hwnd, "screenshot_id": screenshot_id},
        "screen": {"x": screen_x, "y": screen_y},
        "debug": debug,
        "window": window_result,
        "targets": _mouse_context_targets(window_result),
    }

    if include_uia:
        uia_result = element_from_point(screen_x, screen_y)
        result["uia"] = uia_result
        if isinstance(uia_result, dict) and uia_result.get("error"):
            result.setdefault("diagnostics", []).append({"layer": "uia", "error": uia_result.get("error")})

    if include_msaa:
        msaa_result = msaa_from_point(screen_x, screen_y)
        result["msaa"] = msaa_result
        if isinstance(msaa_result, dict) and msaa_result.get("error"):
            result.setdefault("diagnostics", []).append({"layer": "msaa", "error": msaa_result.get("error")})

    if isinstance(window_result, dict) and window_result.get("error") == "elevated_helper_required":
        result.update({
            "ok": False,
            "error": "elevated_helper_required",
            "failure_category": window_result.get("failure_category"),
            "boundary": window_result.get("boundary"),
            "recommendations": window_result.get("recommendations"),
        })
    return result


def msaa_action(
    hwnd: int,
    path: Optional[List[int]] = None,
    child_id: int = MSAA_SELF,
    action: str = "default",
    value: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform an MSAA default/select/focus/set-value action."""
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/msaa_action")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/msaa_action",
            {
                "hwnd": hwnd,
                "path": path or [],
                "child_id": child_id,
                "action": action,
                "value": value,
            },
            elevated=helper_elevated,
        )
        if "error" not in helper_result:
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
        if _is_terminal_uia_helper_error(helper_result):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
    try:
        acc = _msaa_object_from_window(hwnd)
        target, resolved_child = _msaa_object_from_path(acc, path or [])
        if child_id != MSAA_SELF:
            resolved_child = int(child_id)
        action_lower = action.lower().replace("-", "_")
        before = _msaa_info(target, resolved_child, hwnd=hwnd, path=path or [])
        if action_lower in ("default", "do_default", "invoke", "click"):
            result = target.accDoDefaultAction(_msaa_variant(resolved_child))
        elif action_lower in ("focus", "take_focus"):
            result = target.accSelect(MSAA_SELECT_TAKEFOCUS, _msaa_variant(resolved_child))
        elif action_lower in ("select", "take_selection"):
            result = target.accSelect(MSAA_SELECT_TAKESELECTION, _msaa_variant(resolved_child))
        elif action_lower in ("set_value", "setvalue"):
            if value is None:
                return {"error": "value required for set_value", "before": before}
            target.accValue[_msaa_variant(resolved_child)] = str(value)
            result = 0
        else:
            return {
                "error": f"Unknown MSAA action: {action}",
                "supported": ["default", "focus", "select", "set_value"],
                "before": before,
            }
        after = _msaa_info(target, resolved_child, hwnd=hwnd, path=path or [])
        return {"ok": True, "hwnd": hwnd, "path": path or [], "child_id": resolved_child, "action": action_lower, "result": result, "before": before, "after": after}
    except Exception as e:
        return {"error": str(e), "hwnd": hwnd, "path": path or [], "child_id": child_id, "action": action}

