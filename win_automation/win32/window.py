"""
Native Win32 window management, enumeration, focus control, placement, and boundary diagnostics.
"""

from __future__ import annotations

import os
import sys
import time
import json
import ctypes
import ctypes.wintypes
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from win_automation.core.types import WindowNotFoundError, ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.core.dpi import get_dpi_scale_for_hwnd
from win_automation.core.utils import is_valid_hwnd, make_lparam, clamp_int, shorten
from win_automation.helper.client import (
    ensure_helper as _prepare_helper,
    _helper_route_for_hwnd,
    _helper_post,
    _helper_get,
)

def _rect_tuple_to_dict(rect: Tuple[int, int, int, int]) -> Dict[str, int]:
    left, top, right, bottom = rect
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
    }

def _get_process_name(pid: int) -> str:
    return get_process_name(pid)

def get_window_info(hwnd: int) -> Optional[Dict[str, Any]]:
    return _window_info(hwnd)

_screenshots: Dict[int, Dict[str, Any]] = {}
_last_screenshot_size: Tuple[int, int] = (1280, 834)
_uia_element_cache: Dict[int, Dict[int, Any]] = {}
_uia_ad_hoc_element_indices: Dict[int, set[int]] = {}
_uia_element_signatures: Dict[int, Dict[int, Dict[str, Any]]] = {}
_uia_scan_options: Dict[int, Dict[str, Any]] = {}
_DESKTOP_UIA_KEY = 0


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def get_process_name(pid: int) -> str:
    """Return the full image path for a process, or empty string on failure."""
    try:
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        size = ctypes.c_ulong(MAX_PATH)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            kernel32.CloseHandle(h)
            return buf.value
        kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def _get_current_process_token_info() -> Dict[str, Any]:
    pid = int(kernel32.GetCurrentProcessId())
    process_path = get_process_name(pid)
    info = _query_process_token_info(pid=pid, process_handle=int(kernel32.GetCurrentProcess() or 0), close_process=False)
    info.update({
        "pid": pid,
        "process_name": os.path.basename(process_path) if process_path else "",
        "process_path": process_path,
        "is_admin_user": _current_user_is_admin(),
    })
    return info


def _current_user_is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def _integrity_level_name(rid: Optional[int]) -> str:
    if rid is None:
        return "unknown"
    if rid >= SECURITY_MANDATORY_PROTECTED_PROCESS_RID:
        return "protected"
    if rid >= SECURITY_MANDATORY_SYSTEM_RID:
        return "system"
    if rid >= SECURITY_MANDATORY_HIGH_RID:
        return "high"
    if rid >= SECURITY_MANDATORY_MEDIUM_PLUS_RID:
        return "medium_plus"
    if rid >= SECURITY_MANDATORY_MEDIUM_RID:
        return "medium"
    if rid >= SECURITY_MANDATORY_LOW_RID:
        return "low"
    return "untrusted"


def _integrity_rank(name: str) -> int:
    return {
        "unknown": -1,
        "untrusted": 0,
        "low": 1,
        "medium": 2,
        "medium_plus": 3,
        "high": 4,
        "system": 5,
        "protected": 6,
    }.get(name, -1)


def _query_token_dword(token: int, info_class: int) -> Optional[int]:
    value = ctypes.c_ulong()
    needed = ctypes.c_ulong()
    ok = advapi32.GetTokenInformation(
        ctypes.c_void_p(token),
        info_class,
        ctypes.byref(value),
        ctypes.sizeof(value),
        ctypes.byref(needed),
    )
    if not ok:
        return None
    return int(value.value)


def _query_token_integrity(token: int) -> Dict[str, Any]:
    needed = ctypes.c_ulong()
    advapi32.GetTokenInformation(ctypes.c_void_p(token), TOKEN_INTEGRITY_LEVEL_CLASS, None, 0, ctypes.byref(needed))
    if needed.value <= 0:
        return {"integrity_level": "unknown", "integrity_rid": None}
    buf = ctypes.create_string_buffer(int(needed.value))
    ok = advapi32.GetTokenInformation(
        ctypes.c_void_p(token),
        TOKEN_INTEGRITY_LEVEL_CLASS,
        buf,
        ctypes.sizeof(buf),
        ctypes.byref(needed),
    )
    if not ok:
        return {"integrity_level": "unknown", "integrity_rid": None}
    label = TOKEN_MANDATORY_LABEL.from_buffer(buf)
    sid = int(label.Label.Sid or 0)
    if not sid:
        return {"integrity_level": "unknown", "integrity_rid": None}
    try:
        sub_authority_count = int(advapi32.GetSidSubAuthorityCount(ctypes.c_void_p(sid)).contents.value)
        rid = int(advapi32.GetSidSubAuthority(ctypes.c_void_p(sid), sub_authority_count - 1).contents.value)
    except Exception:
        return {"integrity_level": "unknown", "integrity_rid": None}
    level = _integrity_level_name(rid)
    return {
        "integrity_level": level,
        "integrity_rank": _integrity_rank(level),
        "integrity_rid": rid,
        "integrity_rid_hex": hex(rid),
    }


def _query_process_token_info(pid: int, process_handle: Optional[int] = None, close_process: bool = True) -> Dict[str, Any]:
    process = int(process_handle or 0)
    opened_process = False
    result: Dict[str, Any] = {"pid": int(pid), "token_readable": False}
    try:
        if not process:
            process = int(kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION, False, int(pid)) or 0)
            if not process:
                process = int(kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)) or 0)
            opened_process = bool(process)
        if not process:
            result["error"] = "OpenProcess failed"
            return result
        if process_handle is None and opened_process:
            path = get_process_name(pid)
            result.update({
                "process_name": os.path.basename(path) if path else "",
                "process_path": path,
            })
        token = ctypes.c_void_p()
        if not advapi32.OpenProcessToken(ctypes.c_void_p(process), TOKEN_QUERY, ctypes.byref(token)):
            result["error"] = "OpenProcessToken failed"
            return result
        try:
            result["token_readable"] = True
            elevation = _query_token_dword(int(token.value or 0), TOKEN_ELEVATION_CLASS)
            uiaccess = _query_token_dword(int(token.value or 0), TOKEN_UIACCESS_CLASS)
            result["elevated"] = bool(elevation) if elevation is not None else None
            result["uiaccess"] = bool(uiaccess) if uiaccess is not None else None
            result.update(_query_token_integrity(int(token.value or 0)))
        finally:
            if token.value:
                kernel32.CloseHandle(token)
    except Exception as e:
        result["error"] = str(e)
    finally:
        if opened_process and process:
            kernel32.CloseHandle(ctypes.c_void_p(process))
    return result


def _user_object_name(handle: int) -> Dict[str, Any]:
    if not handle:
        return {"name": "", "ok": False, "error": "null handle"}
    needed = ctypes.c_ulong()
    user32.GetUserObjectInformationW(ctypes.c_void_p(handle), UOI_NAME, None, 0, ctypes.byref(needed))
    chars = max(int(needed.value // ctypes.sizeof(ctypes.c_wchar)) + 2, 64)
    buf = ctypes.create_unicode_buffer(chars)
    ok = bool(user32.GetUserObjectInformationW(
        ctypes.c_void_p(handle),
        UOI_NAME,
        buf,
        ctypes.sizeof(buf),
        ctypes.byref(needed),
    ))
    return {"name": buf.value if ok else "", "ok": ok}


def _desktop_boundary_info(target_thread_id: Optional[int] = None) -> Dict[str, Any]:
    current_thread_id = int(kernel32.GetCurrentThreadId())
    process_station = _user_object_name(int(user32.GetProcessWindowStation() or 0))
    thread_desktop = _user_object_name(int(user32.GetThreadDesktop(current_thread_id) or 0))
    input_desktop_handle = int(user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS) or 0)
    input_desktop = _user_object_name(input_desktop_handle)
    if input_desktop_handle:
        user32.CloseDesktop(ctypes.c_void_p(input_desktop_handle))
    target_desktop = None
    if target_thread_id:
        target_desktop = _user_object_name(int(user32.GetThreadDesktop(int(target_thread_id)) or 0))
    current_name = thread_desktop.get("name") or ""
    input_name = input_desktop.get("name") or ""
    target_name = (target_desktop or {}).get("name") or ""
    return {
        "process_window_station": process_station,
        "current_thread_desktop": thread_desktop,
        "input_desktop": input_desktop,
        "target_thread_desktop": target_desktop,
        "input_desktop_mismatch": bool(input_name and current_name and input_name.lower() != current_name.lower()),
        "target_desktop_mismatch": bool(target_name and current_name and target_name.lower() != current_name.lower()),
    }


def control_boundary(hwnd: Optional[int] = None) -> Dict[str, Any]:
    """Diagnose Windows integrity/UIPI/UIAccess boundaries for a target HWND."""
    requested_hwnd = hwnd
    if hwnd is None:
        hwnd = int(user32.GetForegroundWindow() or 0)
    hwnd = int(hwnd or 0)
    if not hwnd or not user32.IsWindow(hwnd):
        return {"ok": False, "error": "target HWND is missing or no longer exists", "hwnd": hwnd, "requested_hwnd": requested_hwnd}
    target = _win32_window_info(hwnd, include_text=False) or _window_info(hwnd) or {"hwnd": hwnd}
    root_hwnd = int(target.get("root_hwnd") or hwnd)
    root_owner_hwnd = int(target.get("root_owner_hwnd") or root_hwnd)
    foreground_hwnd = int(user32.GetForegroundWindow() or 0)
    pid = int(target.get("pid") or 0)
    thread_id = int(target.get("thread_id") or 0)
    current = _get_current_process_token_info()
    target_token = _query_process_token_info(pid) if pid else {"pid": pid, "error": "target PID unavailable", "token_readable": False}
    if not target_token.get("process_path") and target.get("process_path"):
        target_token["process_path"] = target.get("process_path")
        target_token["process_name"] = target.get("process_name")
    desktop = _desktop_boundary_info(thread_id or None)
    current_rank = int(current.get("integrity_rank", -1) or -1)
    target_rank = int(target_token.get("integrity_rank", -1) or -1)
    current_uiaccess = bool(current.get("uiaccess"))
    target_higher = target_rank > current_rank >= 0
    uipi_risk = bool(target_higher and not current_uiaccess)
    secure_desktop_risk = bool(desktop.get("input_desktop_mismatch") or desktop.get("target_desktop_mismatch"))
    target_token_readable = bool(target_token.get("token_readable"))
    reasons: List[str] = []
    if uipi_risk:
        reasons.append("target process has a higher integrity level than this automation process")
    if secure_desktop_risk:
        reasons.append("active input desktop or target thread desktop differs from the automation thread desktop")
    if not target_token_readable:
        reasons.append("target process token could not be read; protected process or access boundary is possible")
    if not reasons:
        reasons.append("no Windows integrity, UIPI, or desktop boundary was detected")
    recommendation = "normal_control_path"
    if secure_desktop_risk:
        recommendation = "wait_for_default_desktop_or_run_from_matching_desktop"
    elif uipi_risk:
        recommendation = "rerun automation elevated_or_with_uiaccess"
    elif not target_token_readable:
        recommendation = "prefer_visual_desktop_controls_and_expect_limited_structured_access"
    return {
        "ok": True,
        "hwnd": hwnd,
        "requested_hwnd": requested_hwnd,
        "foreground_hwnd": foreground_hwnd,
        "foreground_is_target_root": bool(foreground_hwnd and foreground_hwnd == root_hwnd),
        "target_window": target,
        "root_window": _win32_window_info(root_hwnd) if root_hwnd and user32.IsWindow(root_hwnd) else None,
        "root_owner_window": _win32_window_info(root_owner_hwnd) if root_owner_hwnd and user32.IsWindow(root_owner_hwnd) else None,
        "current_process": current,
        "target_process": target_token,
        "desktop": desktop,
        "uipi_risk": uipi_risk,
        "secure_desktop_risk": secure_desktop_risk,
        "needs_elevation": bool(uipi_risk),
        "can_send_input_likely": bool(not uipi_risk and not secure_desktop_risk),
        "win32_messages_likely": bool(not uipi_risk and not secure_desktop_risk),
        "uia_access_likely": bool(not uipi_risk and not secure_desktop_risk and target_token_readable),
        "foreground_repair_likely": bool(not secure_desktop_risk),
        "reason": reasons,
        "recommendation": recommendation,
    }


def _rect_tuple_to_dict(rect: Tuple[int, int, int, int]) -> Dict[str, int]:
    left, top, right, bottom = rect
    return {
        "left": int(left),
        "top": int(top),
        "right": int(right),
        "bottom": int(bottom),
        "width": int(right - left),
        "height": int(bottom - top),
        "center_x": int((left + right) // 2),
        "center_y": int((top + bottom) // 2),
    }


def _rect_to_plain_dict(rect: ctypes.wintypes.RECT) -> Dict[str, int]:
    return _rect_tuple_to_dict((int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)))


def _get_window_text(hwnd: int, limit: int = 512) -> str:
    buf = ctypes.create_unicode_buffer(max(limit, 1))
    try:
        user32.GetWindowTextW(hwnd, buf, limit)
        return buf.value.strip()
    except Exception:
        return ""


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    try:
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def _get_window_rect_dict(hwnd: int) -> Dict[str, int]:
    rect = _get_window_rect(hwnd)
    if rect is None:
        return _rect_tuple_to_dict((0, 0, 0, 0))
    return _rect_tuple_to_dict(rect)


def _get_client_rect_info(hwnd: int) -> Dict[str, Any]:
    client = ctypes.wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        return {"rect": _rect_tuple_to_dict((0, 0, 0, 0)), "screen_origin": {"x": 0, "y": 0}}
    origin = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    rect = _rect_tuple_to_dict((client.left, client.top, client.right, client.bottom))
    return {"rect": rect, "screen_origin": {"x": int(origin.x), "y": int(origin.y)}}


def _get_window_placement_dict(hwnd: int) -> Optional[Dict[str, Any]]:
    placement = WINDOWPLACEMENT()
    placement.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
        return None
    return {
        "flags": int(placement.flags),
        "show_cmd": int(placement.showCmd),
        "show_state": {
            SW_SHOWNORMAL: "normal",
            SW_SHOWMINIMIZED: "minimized",
            SW_SHOWMAXIMIZED: "maximized",
            SW_MINIMIZE: "minimize",
            SW_MAXIMIZE: "maximize",
            SW_RESTORE: "restore",
        }.get(int(placement.showCmd), str(int(placement.showCmd))),
        "min_position": {"x": int(placement.ptMinPosition.x), "y": int(placement.ptMinPosition.y)},
        "max_position": {"x": int(placement.ptMaxPosition.x), "y": int(placement.ptMaxPosition.y)},
        "normal_position": _rect_to_plain_dict(placement.rcNormalPosition),
        "restore_to_maximized": bool(placement.flags & WPF_RESTORETOMAXIMIZED),
        "async_window_placement": bool(placement.flags & WPF_ASYNCWINDOWPLACEMENT),
    }


def _apply_window_placement(
    hwnd: int,
    placement_info: Dict[str, Any],
    show_cmd: Optional[int] = None,
    flags: Optional[int] = None,
) -> Dict[str, Any]:
    current = WINDOWPLACEMENT()
    current.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not user32.GetWindowPlacement(hwnd, ctypes.byref(current)):
        return {"ok": False, "error": "GetWindowPlacement failed before SetWindowPlacement"}
    normal = placement_info.get("normal_position") or placement_info.get("normal") or {}
    min_pos = placement_info.get("min_position") or {}
    max_pos = placement_info.get("max_position") or {}
    if flags is not None:
        current.flags = int(flags)
    elif "flags" in placement_info:
        current.flags = int(placement_info.get("flags") or 0)
    if show_cmd is not None:
        current.showCmd = int(show_cmd)
    elif "show_cmd" in placement_info:
        current.showCmd = int(placement_info.get("show_cmd") or SW_SHOWNORMAL)
    for attr, data in (("ptMinPosition", min_pos), ("ptMaxPosition", max_pos)):
        point = getattr(current, attr)
        if isinstance(data, dict):
            point.x = int(data.get("x", point.x))
            point.y = int(data.get("y", point.y))
    if isinstance(normal, dict) and normal:
        current.rcNormalPosition.left = int(normal.get("left", current.rcNormalPosition.left))
        current.rcNormalPosition.top = int(normal.get("top", current.rcNormalPosition.top))
        current.rcNormalPosition.right = int(normal.get("right", current.rcNormalPosition.right))
        current.rcNormalPosition.bottom = int(normal.get("bottom", current.rcNormalPosition.bottom))
    ok = bool(user32.SetWindowPlacement(hwnd, ctypes.byref(current)))
    return {"ok": ok, "method": "SetWindowPlacement", "placement": _get_window_placement_dict(hwnd)}


def _send_message_timeout(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0, timeout_ms: int = 250) -> Tuple[bool, int]:
    result = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(
        hwnd,
        msg,
        ctypes.c_size_t(wparam),
        ctypes.c_ssize_t(lparam),
        SMTO_ABORTIFHUNG,
        max(int(timeout_ms), 1),
        ctypes.byref(result),
    )
    return bool(ok), int(result.value)


def _pump_wait(predicate, timeout: float = 1.0, interval: float = 0.01) -> bool:
    """Pump this thread's Win32 queue while waiting for a native callback."""
    deadline = time.time() + max(float(timeout), 0.0)
    msg = ctypes.wintypes.MSG()
    while True:
        if predicate():
            return True
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
            if predicate():
                return True
        if time.time() >= deadline:
            return bool(predicate())
        time.sleep(max(float(interval), 0.001))


def _get_control_text(hwnd: int, timeout_ms: int = 250, max_chars: int = 4096) -> Dict[str, Any]:
    """Read text from standard Win32 controls without blocking on hung windows."""
    ok, length = _send_message_timeout(hwnd, WM_GETTEXTLENGTH, timeout_ms=timeout_ms)
    if not ok:
        return {"ok": False, "error": "WM_GETTEXTLENGTH timed out or failed", "text": ""}
    length = min(max(length, 0), max_chars)
    buf = ctypes.create_unicode_buffer(length + 1)
    ok, copied = _send_message_timeout(
        hwnd,
        WM_GETTEXT,
        length + 1,
        ctypes.addressof(buf),
        timeout_ms=timeout_ms,
    )
    if not ok:
        return {"ok": False, "error": "WM_GETTEXT timed out or failed", "text": ""}
    return {"ok": True, "text": buf.value, "length": int(copied)}


def _win32_window_info(hwnd: int, include_text: bool = False) -> Optional[Dict[str, Any]]:
    """Return HWND-level metadata for top-level or child controls."""
    try:
        if not user32.IsWindow(hwnd):
            return None
        pid = ctypes.c_ulong()
        thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_path = get_process_name(pid.value)
        style = int(user32.GetWindowLongW(hwnd, GWL_STYLE))
        ex_style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
        parent = int(user32.GetParent(hwnd) or 0)
        owner = int(user32.GetWindow(hwnd, GW_OWNER) or 0)
        root = int(user32.GetAncestor(hwnd, GA_ROOT) or 0)
        root_owner = int(user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0)
        info: Dict[str, Any] = {
            "hwnd": int(hwnd),
            "title": _get_window_text(hwnd),
            "class_name": _get_class_name(hwnd),
            "control_id": int(user32.GetDlgCtrlID(hwnd)),
            "pid": pid.value,
            "thread_id": int(thread_id),
            "process_name": os.path.basename(proc_path) if proc_path else "",
            "process_path": proc_path,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "enabled": bool(user32.IsWindowEnabled(hwnd)),
            "minimized": bool(user32.IsIconic(hwnd)),
            "maximized": bool(user32.IsZoomed(hwnd)),
            "topmost": bool(ex_style & WS_EX_TOPMOST),
            "is_child": bool(style & WS_CHILD),
            "parent_hwnd": parent,
            "owner_hwnd": owner,
            "root_hwnd": root,
            "root_owner_hwnd": root_owner,
            "style": style,
            "ex_style": ex_style,
            "placement": _get_window_placement_dict(hwnd),
            "rect": _get_window_rect_dict(hwnd),
            "client": _get_client_rect_info(hwnd),
        }
        if include_text:
            info["text"] = _get_control_text(hwnd)
        return info
    except Exception:
        return None


def _window_info(hwnd: int) -> Optional[Dict[str, Any]]:
    """Return structured metadata for a window handle."""
    try:
        if not user32.IsWindow(hwnd):
            return None
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_path = get_process_name(pid.value)
        rect = _get_window_rect(hwnd)
        if rect is None:
            raw_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(raw_rect))
            rect = (raw_rect.left, raw_rect.top, raw_rect.right, raw_rect.bottom)
        left, top, right, bottom = rect
        owner = int(user32.GetWindow(hwnd, GW_OWNER) or 0)
        root = int(user32.GetAncestor(hwnd, GA_ROOT) or 0)
        root_owner = int(user32.GetAncestor(hwnd, GA_ROOTOWNER) or 0)
        ex_style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
        return {
            "hwnd": int(hwnd),
            "title": title,
            "class_name": _get_class_name(hwnd),
            "pid": pid.value,
            "process_name": os.path.basename(proc_path) if proc_path else "",
            "process_path": proc_path,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "enabled": bool(user32.IsWindowEnabled(hwnd)),
            "minimized": bool(user32.IsIconic(hwnd)),
            "maximized": bool(user32.IsZoomed(hwnd)),
            "topmost": bool(ex_style & WS_EX_TOPMOST),
            "owner_hwnd": owner,
            "root_hwnd": root,
            "root_owner_hwnd": root_owner,
            "placement": _get_window_placement_dict(hwnd),
            "rect": {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "width": right - left,
                "height": bottom - top,
            },
        }
    except Exception:
        return None



def enum_windows() -> List[Dict[str, Any]]:
    """Return a list of visible top-level windows with metadata."""
    results: List[Dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if (ex_style & WS_EX_TOOLWINDOW) and not (ex_style & WS_EX_APPWINDOW):
                return True
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()
            if not title:
                return True
            info = _window_info(hwnd)
            if info:
                results.append(info)
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, None)
    return results


# ---------------------------------------------------------------------------
# Persistent state management (Gap 4)
# ---------------------------------------------------------------------------

STATE_FILE = os.path.join(os.path.expanduser("~"), ".win-auto-state.json")


def _load_state() -> dict:
    """Load persistent state from disk."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    """Save persistent state to disk."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _state_get(key: str | None = None) -> dict:
    """Get state value(s). If key is None, return all state."""
    state = _load_state()
    if key:
        if key in state:
            return {key: state[key]}
        return {"error": f"Key '{key}' not found"}
    return {"state": state}


def _state_set(key: str, value: Any) -> dict:
    """Set a state key/value pair."""
    state = _load_state()
    # Try to parse JSON values
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
    state[key] = value
    _save_state(state)
    return {"ok": True, "state": state}


def _state_target(hwnd: int) -> dict:
    """Set the current target window hwnd in state."""
    state = _load_state()
    state["target_hwnd"] = hwnd
    _save_state(state)
    return {"ok": True, "target_hwnd": hwnd}


def _resolve_target(hwnd: int | None) -> int:
    """Resolve hwnd, falling back to state target_hwnd if None."""
    if hwnd is not None:
        return hwnd
    state = _load_state()
    target = state.get("target_hwnd")
    if target:
        return target
    raise RuntimeError(
        "No hwnd provided and no target_hwnd in state. "
        "Run: python tools.py state target <hwnd>"
    )


def _get_screenshot_size(screenshot_id: int | None) -> Dict[str, int]:
    """Get screenshot dimensions for coordinate scaling."""
    if screenshot_id is not None and screenshot_id in _screenshots:
        meta = _screenshots[screenshot_id]
        return {"width": meta["width"], "height": meta["height"]}
    if screenshot_id is not None:
        state = _load_state()
        screenshots = state.get("screenshots", {})
        meta = screenshots.get(str(screenshot_id)) if isinstance(screenshots, dict) else None
        if meta:
            return {"width": meta["width"], "height": meta["height"]}
    state_size = _load_state().get("last_screenshot_size")
    if isinstance(state_size, dict) and "width" in state_size and "height" in state_size:
        return {"width": int(state_size["width"]), "height": int(state_size["height"])}
    return {"width": _last_screenshot_size[0], "height": _last_screenshot_size[1]}


def _next_screenshot_id() -> int:
    """Return a process-safe-ish persistent screenshot id for CLI invocations."""
    global _screenshot_counter
    state = _load_state()
    current = int(state.get("screenshot_counter", 0) or 0)
    next_id = max(current, _screenshot_counter) + 1
    state["screenshot_counter"] = next_id
    _save_state(state)
    _screenshot_counter = next_id
    return next_id


def _remember_screenshot(meta: Dict[str, Any]) -> None:
    """Persist recent screenshot metadata across CLI invocations."""
    state = _load_state()
    screenshots = state.get("screenshots", {})
    if not isinstance(screenshots, dict):
        screenshots = {}
    screenshots[str(meta["id"])] = meta
    recent_ids = sorted(
        screenshots,
        key=lambda key: screenshots[key].get("created_at", 0),
        reverse=True,
    )[:20]
    state["screenshots"] = {key: screenshots[key] for key in recent_ids}
    state["last_screenshot"] = meta
    state["last_screenshot_size"] = {"width": meta["width"], "height": meta["height"]}
    _save_state(state)


def _load_screenshot_meta(screenshot_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    state = _load_state()
    if screenshot_id is None:
        meta = state.get("last_screenshot")
        return meta if isinstance(meta, dict) else None
    screenshots = state.get("screenshots", {})
    if not isinstance(screenshots, dict):
        return None
    return screenshots.get(str(screenshot_id))


def list_apps() -> List[Dict[str, Any]]:
    """Group windows by process and return structured data."""
    if _prepare_helper():
        result = _helper_get("/list_apps")
        if not isinstance(result, dict) or "error" not in result:
            return result
        # Helper doesn't support /list_apps (old version), execute locally

    # Fallback: group locally
    windows = enum_windows()
    apps_map: Dict[str, Dict[str, Any]] = {}
    for w in windows:
        pid = w.get("pid", 0)
        proc_name = w.get("process_name", "")
        proc_path = w.get("process_path", "")
        if not proc_name:
            continue
        key = proc_name
        if key not in apps_map:
            apps_map[key] = {
                "app_name": proc_name,
                "app_path": proc_path,
                "is_running": True,
                "windows": [],
            }
        apps_map[key]["windows"].append({
            "hwnd": w["hwnd"],
            "title": w["title"],
            "pid": pid,
            "rect": w["rect"],
        })
    return list(apps_map.values())


def foreground_window() -> Dict[str, Any]:
    """Return the current foreground window metadata."""
    hwnd = int(user32.GetForegroundWindow() or 0)
    info = _window_info(hwnd)
    return info or {"error": "no_foreground_window", "hwnd": hwnd}



def _gui_thread_info_raw(thread_id: int) -> Tuple[bool, GUITHREADINFO]:
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    ok = bool(user32.GetGUIThreadInfo(ctypes.c_ulong(int(thread_id)), ctypes.byref(info)))
    return ok, info


def gui_thread_info(hwnd: Optional[int] = None, thread_id: Optional[int] = None) -> Dict[str, Any]:
    """Return GetGUIThreadInfo state for a window/thread: focus, active, capture, menu owner, move-size, and caret."""
    target_hwnd = int(hwnd or 0)
    resolved_thread = int(thread_id or 0)
    if resolved_thread <= 0:
        if target_hwnd:
            if not user32.IsWindow(target_hwnd):
                return {"ok": False, "error": f"Window {target_hwnd} not found", "hwnd": target_hwnd}
            resolved_thread = int(user32.GetWindowThreadProcessId(target_hwnd, None))
        else:
            target_hwnd = int(user32.GetForegroundWindow() or 0)
            resolved_thread = int(user32.GetWindowThreadProcessId(target_hwnd, None)) if target_hwnd else 0
    ok, info = _gui_thread_info_raw(resolved_thread)
    if not ok:
        return {"ok": False, "error": "GetGUIThreadInfo failed", "hwnd": target_hwnd, "thread_id": resolved_thread}

    def hwnd_info(value: Any) -> Optional[Dict[str, Any]]:
        handle = int(value or 0)
        if not handle:
            return None
        return _win32_window_info(handle, include_text=True) or {"hwnd": handle, "exists": bool(user32.IsWindow(handle))}

    handles = {
        "active": int(info.hwndActive or 0),
        "focus": int(info.hwndFocus or 0),
        "capture": int(info.hwndCapture or 0),
        "menu_owner": int(info.hwndMenuOwner or 0),
        "move_size": int(info.hwndMoveSize or 0),
        "caret": int(info.hwndCaret or 0),
    }
    return {
        "ok": True,
        "hwnd": target_hwnd,
        "thread_id": resolved_thread,
        "flags": int(info.flags),
        "handles": handles,
        "windows": {name: hwnd_info(handle) for name, handle in handles.items()},
        "caret_rect": _rect_to_plain_dict(info.rcCaret),
    }

def launch_app(path_or_name: str, timeout: float = 10.0) -> Dict[str, Any]:
    """Launch an application and return a newly visible window when one appears."""
    before_windows = enum_windows()
    before = {w["hwnd"] for w in before_windows}
    before_pids = {w.get("pid") for w in before_windows}
    result = shell32.ShellExecuteW(None, "open", path_or_name, None, None, SW_SHOWNORMAL)
    if result <= 32:
        return {"error": f"Failed to launch '{path_or_name}'", "shell_execute_code": result}

    deadline = time.time() + max(timeout, 0.0)
    last_windows: List[Dict[str, Any]] = []
    seen_counts: Dict[int, int] = {}
    command_hint = os.path.basename(path_or_name).lower().replace(".exe", "")

    def score(window: Dict[str, Any]) -> int:
        text = f'{window.get("process_name", "")} {window.get("process_path", "")} {window.get("title", "")}'.lower()
        value = 0
        if window.get("pid") not in before_pids:
            value += 20
        if command_hint and command_hint in text:
            value += 10
        if window.get("hwnd") not in before:
            value += 5
        return value

    while time.time() <= deadline:
        time.sleep(0.25)
        last_windows = enum_windows()
        candidates = [
            w for w in last_windows
            if _is_usable_window_info(w) and (w["hwnd"] not in before or w.get("pid") not in before_pids or command_hint in f'{w.get("process_name", "")} {w.get("process_path", "")} {w.get("title", "")}'.lower())
        ]
        for candidate in candidates:
            hwnd = candidate["hwnd"]
            seen_counts[hwnd] = seen_counts.get(hwnd, 0) + 1
        stable = [w for w in candidates if seen_counts.get(w["hwnd"], 0) >= 2]
        if stable:
            window = sorted(stable, key=score, reverse=True)[0]
            activate_window(window["hwnd"])
            time.sleep(0.2)
            refreshed = _wait_stable_window(
                hwnd=int(window["hwnd"]),
                process=window.get("process_name") or command_hint or None,
                pid=int(window.get("pid") or 0) if window.get("pid") is not None else None,
                timeout=min(2.0, max(0.5, timeout)),
                interval=0.1,
                stable_ticks=2,
            )
            if refreshed.get("ok") and isinstance(refreshed.get("window"), dict):
                window = refreshed["window"]
            _state_target(window["hwnd"])
            return {
                "ok": True,
                "launched": path_or_name,
                "window": window,
                "stable_window": {
                    "attempts": refreshed.get("attempts"),
                    "stable_ticks": refreshed.get("stable_ticks"),
                    "rebound": bool(refreshed.get("rebound")),
                },
            }

    return {
        "ok": True,
        "launched": path_or_name,
        "window": None,
        "message": "Application launch returned success, but no new visible window appeared before timeout.",
        "visible_windows": last_windows,
    }


def _get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Return (left, top, right, bottom) for a window handle, or None using DWM visible bounds."""
    rect = ctypes.wintypes.RECT()
    try:
        dwmapi = ctypes.windll.dwmapi
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect)
        )
        if hr == 0:
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass

    # Fallback to standard GetWindowRect
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (rect.left, rect.top, rect.right, rect.bottom)
    return None


def _get_raw_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Return the Win32 raw window frame from GetWindowRect."""
    rect = ctypes.wintypes.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    return None


def _window_rect_offsets(hwnd: int) -> Tuple[int, int, int, int]:
    """Return raw-minus-visible frame offsets used to move by DWM-visible bounds."""
    visible = _get_window_rect(hwnd)
    raw = _get_raw_window_rect(hwnd)
    if not visible or not raw:
        return (0, 0, 0, 0)
    return (
        int(raw[0] - visible[0]),
        int(raw[1] - visible[1]),
        int(raw[2] - visible[2]),
        int(raw[3] - visible[3]),
    )


def _window_action_name(action: str) -> str:
    return str(action or "").strip().lower().replace("-", "_")


def window_action(
    hwnd: int,
    action: str,
    x: Optional[int] = None,
    y: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    timeout: float = 1.5,
) -> Dict[str, Any]:
    """Move, resize, show, minimize, maximize, restore, or close a native HWND."""
    action_name = _window_action_name(action)
    if not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window {hwnd} not found", "hwnd": hwnd, "action": action}
    before = _window_info(hwnd)
    result: Dict[str, Any] = {"hwnd": int(hwnd), "action": action_name, "before": before}
    try:
        if action_name in ("restore", "normal", "show", "shownormal"):
            ok = bool(user32.ShowWindow(hwnd, SW_RESTORE))
            if action_name == "show" and not ok:
                ok = bool(user32.ShowWindow(hwnd, SW_SHOW))
            result.update({"ok": True, "method": "ShowWindow", "native_result": ok})
        elif action_name in ("minimize", "minimise", "show_minimized"):
            ok = bool(user32.ShowWindow(hwnd, SW_MINIMIZE))
            result.update({"ok": True, "method": "ShowWindow", "native_result": ok})
        elif action_name in ("maximize", "maximise", "show_maximized"):
            ok = bool(user32.ShowWindow(hwnd, SW_MAXIMIZE))
            result.update({"ok": True, "method": "ShowWindow", "native_result": ok})
        elif action_name in ("top", "bring_to_top", "front", "z_top", "topmost", "always_on_top", "not_topmost", "no_topmost", "bottom", "z_bottom"):
            insert_after_map = {
                "top": HWND_TOP,
                "bring_to_top": HWND_TOP,
                "front": HWND_TOP,
                "z_top": HWND_TOP,
                "topmost": HWND_TOPMOST,
                "always_on_top": HWND_TOPMOST,
                "not_topmost": HWND_NOTOPMOST,
                "no_topmost": HWND_NOTOPMOST,
                "bottom": HWND_BOTTOM,
                "z_bottom": HWND_BOTTOM,
            }
            insert_after = insert_after_map[action_name]
            ok = bool(user32.SetWindowPos(
                hwnd,
                ctypes.c_void_p(ctypes.c_ssize_t(insert_after).value),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOOWNERZORDER,
            ))
            result.update({"ok": ok, "method": "SetWindowPos", "insert_after": insert_after})
        elif action_name in ("placement", "get_placement", "window_placement"):
            result.update({"ok": True, "method": "GetWindowPlacement", "placement": _get_window_placement_dict(hwnd)})
        elif action_name in ("restore_placement", "set_placement", "normal_placement"):
            placement_info: Dict[str, Any] = {}
            if x is not None and y is not None and width is not None and height is not None:
                placement_info["normal_position"] = {
                    "left": int(x),
                    "top": int(y),
                    "right": int(x) + int(width),
                    "bottom": int(y) + int(height),
                }
            placement_result = _apply_window_placement(hwnd, placement_info, show_cmd=SW_SHOWNORMAL)
            result.update(placement_result)
        elif action_name in ("move", "resize", "set_rect", "set_position", "position"):
            visible = _get_window_rect(hwnd)
            if not visible:
                return {"ok": False, "error": "Could not read window rect", **result}
            left, top, right, bottom = visible
            target_x = int(x if x is not None else left)
            target_y = int(y if y is not None else top)
            target_w = int(width if width is not None else right - left)
            target_h = int(height if height is not None else bottom - top)
            if target_w <= 0 or target_h <= 0:
                return {"ok": False, "error": "width and height must be positive", **result}
            off_l, off_t, off_r, off_b = _window_rect_offsets(hwnd)
            raw_x = target_x + off_l
            raw_y = target_y + off_t
            raw_w = target_w + (off_r - off_l)
            raw_h = target_h + (off_b - off_t)
            raw_w = max(raw_w, 1)
            raw_h = max(raw_h, 1)
            ok = bool(user32.SetWindowPos(
                hwnd,
                None,
                raw_x,
                raw_y,
                raw_w,
                raw_h,
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            ))
            result.update({
                "ok": ok,
                "method": "SetWindowPos",
                "target_rect": _rect_tuple_to_dict((target_x, target_y, target_x + target_w, target_y + target_h)),
                "raw_rect": _rect_tuple_to_dict((raw_x, raw_y, raw_x + raw_w, raw_y + raw_h)),
                "frame_offsets": {"left": off_l, "top": off_t, "right": off_r, "bottom": off_b},
            })
        elif action_name in ("close", "request_close", "wm_close"):
            ok = bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
            deadline = time.time() + max(float(timeout), 0.0)
            closed = False
            while time.time() <= deadline:
                if not user32.IsWindow(hwnd):
                    closed = True
                    break
                _pump_wait(lambda: not user32.IsWindow(hwnd), timeout=0.05)
            result.update({"ok": ok, "method": "PostMessageW", "closed": closed})
        else:
            result.update({
                "ok": False,
                "error": f"Unsupported window action: {action}",
                "supported": ["move", "resize", "set-rect", "minimize", "maximize", "restore", "show", "close", "top", "bottom", "topmost", "not-topmost", "placement", "restore-placement"],
            })
            return result
    except Exception as e:
        result.update({"ok": False, "error": str(e)})
        return result
    time.sleep(0.05)
    result["after"] = _window_info(hwnd) if user32.IsWindow(hwnd) else None
    return result


def _get_dpi_scale(hwnd: int) -> float:
    """Return DPI scale factor relative to 96 DPI (1.0 = no scaling)."""
    try:
        dpi = user32.GetDpiForWindow(hwnd)
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _scale_coords(
    hwnd: int,
    x: int,
    y: int,
    screenshot_id: Optional[int] = None,
) -> Tuple[int, int, str]:
    """
    Convert screenshot-pixel coordinates to screen-pixel coordinates.

    PrintWindow captures at logical (GetWindowRect) size, so the mapping is:
    screenshot -> logical -> physical screen.

    Returns (screen_x, screen_y, debug_info).
    """
    global _last_screenshot_size

    # Physical bounds (DWM) - used for the final screen position
    rect = _get_window_rect(hwnd)
    if rect is None:
        raise RuntimeError(f"Cannot get window rect for hwnd {hwnd}")
    rect_left, rect_top, _, _ = rect

    # Logical bounds (GetWindowRect) - PrintWindow captures at this size
    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    # Determine screenshot dimensions
    ss_w, ss_h = None, None
    if screenshot_id is not None and screenshot_id in _screenshots:
        meta = _screenshots[screenshot_id]
        ss_w = meta["width"]
        ss_h = meta["height"]
    elif screenshot_id is not None:
        meta = _load_screenshot_meta(screenshot_id)
        if meta:
            ss_w = meta.get("width")
            ss_h = meta.get("height")

    if not ss_w:
        ss_w = 1280 if log_w > 1280 else log_w
    if not ss_h:
        ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

    # DPI scale for coordinate conversion
    scale = _get_dpi_scale(hwnd)

    # Map: screenshot -> logical -> physical screen
    # PrintWindow captures at logical size, so ratio uses logical dims
    # Then add DWM offset to get physical screen position
    real_x = x * log_w / ss_w
    real_y = y * log_h / ss_h
    # DWM rect gives physical screen position; offset is dwm_left - log_left
    phys_x = int(real_x + rect_left)
    phys_y = int(real_y + rect_top)

    return phys_x, phys_y, (
        f"screenshot({x},{y}) -> screen({phys_x},{phys_y}) "
        f"[log {log_w}x{log_h}, ss {ss_w}x{ss_h}, dpi_scale={scale:.2f}]"
    )


# ---------------------------------------------------------------------------
# Window activation (item 2 — AttachThreadInput trick)
# ---------------------------------------------------------------------------

def activate_window(hwnd: int) -> bool:
    """Force-activate a window. Uses helper server if available."""
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/activate")
    if boundary_result is not None:
        return False
    if helper_ready:
        result = _helper_post("/activate", {"hwnd": hwnd}, elevated=helper_elevated)
        if result.get("ok"):
            return True

    # Fallback to direct implementation
    result = _force_foreground_window(hwnd, timeout=0.5)
    if "ok" in result:
        return bool(result.get("ok"))

    # Legacy last resort for old Windows sessions where diagnostics failed early.
    try:
        foreground = user32.GetForegroundWindow()
        foreground_tid = user32.GetWindowThreadProcessId(foreground, None)
        current_tid = kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(current_tid, foreground_tid, True)
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(current_tid, foreground_tid, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _allow_set_foreground_window() -> Dict[str, Any]:
    fn = getattr(user32, "AllowSetForegroundWindow", None)
    if not fn:
        return {"available": False, "ok": False}
    try:
        ok = bool(fn(ctypes.c_ulong(ASFW_ANY)))
        return {"available": True, "ok": ok}
    except Exception as e:
        return {"available": True, "ok": False, "error": str(e)}


def _alt_foreground_pulse() -> Dict[str, Any]:
    """Send a bare Alt press/release; Windows treats this as user input for foreground repair."""
    try:
        down = INPUT()
        down.type = INPUT_KEYBOARD
        down._input.ki.wVk = VK_MENU
        down._input.ki.wScan = 0
        down._input.ki.dwFlags = 0
        down._input.ki.time = 0
        down._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        up = INPUT()
        up.type = INPUT_KEYBOARD
        up._input.ki.wVk = VK_MENU
        up._input.ki.wScan = 0
        up._input.ki.dwFlags = KEYEVENTF_KEYUP
        up._input.ki.time = 0
        up._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        _send_input_checked(down, "foreground alt down")
        time.sleep(0.02)
        _send_input_checked(up, "foreground alt up")
        time.sleep(0.02)
        return {"ok": True, "sent_down": 1, "sent_up": 1}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _switch_to_this_window(hwnd: int) -> Dict[str, Any]:
    fn = getattr(user32, "SwitchToThisWindow", None)
    if not fn:
        return {"available": False, "ok": False}
    try:
        fn(ctypes.c_void_p(hwnd), True)
        return {"available": True, "ok": True}
    except Exception as e:
        return {"available": True, "ok": False, "error": str(e)}


def _thread_ids_for_foreground(root: int, target: Optional[int] = None) -> Tuple[int, int, int, int, List[int]]:
    current_thread = int(kernel32.GetCurrentThreadId())
    foreground = int(user32.GetForegroundWindow() or 0)
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
    root_thread = int(user32.GetWindowThreadProcessId(root, None)) if root else 0
    target_thread = int(user32.GetWindowThreadProcessId(target, None)) if target else root_thread
    unique_threads: List[int] = []
    for tid in (foreground_thread, root_thread, target_thread):
        if tid > 0 and tid != current_thread and tid not in unique_threads:
            unique_threads.append(tid)
    return current_thread, foreground_thread, root_thread, target_thread, unique_threads


def _force_foreground_window(hwnd: int, timeout: float = 1.0, restore: bool = True) -> Dict[str, Any]:
    """Bring a root HWND foreground using foreground-lock repair fallbacks."""
    hwnd = int(hwnd or 0)
    if not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window {hwnd} not found", "hwnd": hwnd}

    root = int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
    foreground_before = int(user32.GetForegroundWindow() or 0)
    current_thread, foreground_thread, root_thread, target_thread, unique_threads = _thread_ids_for_foreground(root, hwnd)
    attached: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []

    def foreground_is_root() -> bool:
        return int(user32.GetForegroundWindow() or 0) == root

    def attach(thread_id: int, attach_flag: bool) -> bool:
        if thread_id <= 0 or thread_id == current_thread:
            return True
        ok = bool(user32.AttachThreadInput(current_thread, thread_id, attach_flag))
        attached.append({"thread_id": int(thread_id), "attach": bool(attach_flag), "ok": ok})
        return ok

    def attempt(name: str, action) -> bool:
        step: Dict[str, Any] = {"name": name}
        try:
            result = action()
            if isinstance(result, dict):
                step.update(result)
            elif result is not None:
                step["result"] = bool(result)
        except Exception as e:
            step["error"] = str(e)
        step["foreground"] = int(user32.GetForegroundWindow() or 0)
        step["foreground_is_root"] = foreground_is_root()
        attempts.append(step)
        return bool(step["foreground_is_root"])

    try:
        for tid in unique_threads:
            attach(tid, True)
        if restore:
            attempt("ShowWindow(SW_RESTORE)", lambda: {"ok": bool(user32.ShowWindow(root, SW_RESTORE))})
        attempt("AllowSetForegroundWindow(ASFW_ANY)", _allow_set_foreground_window)
        attempt("BringWindowToTop", lambda: {"ok": bool(user32.BringWindowToTop(root))})
        if not foreground_is_root():
            attempt("SetForegroundWindow", lambda: {"ok": bool(user32.SetForegroundWindow(root))})
        if not foreground_is_root():
            attempt("SetActiveWindow", lambda: {"previous_active": int(user32.SetActiveWindow(root) or 0)})
        if not foreground_is_root():
            pulse = _alt_foreground_pulse()
            attempts.append({"name": "AltPulse", **pulse, "foreground": int(user32.GetForegroundWindow() or 0), "foreground_is_root": foreground_is_root()})
            attempt("SetForegroundWindowAfterAlt", lambda: {"ok": bool(user32.SetForegroundWindow(root))})
        if not foreground_is_root():
            attempt("SwitchToThisWindow", lambda: _switch_to_this_window(root))
            if not foreground_is_root():
                attempt("SetForegroundWindowAfterSwitch", lambda: {"ok": bool(user32.SetForegroundWindow(root))})
        _pump_wait(foreground_is_root, timeout=max(float(timeout), 0.0), interval=0.01)
    finally:
        for tid in reversed(unique_threads):
            attach(tid, False)

    foreground_after = int(user32.GetForegroundWindow() or 0)
    return {
        "ok": bool(foreground_after == root),
        "hwnd": hwnd,
        "root_hwnd": root,
        "foreground_before": foreground_before,
        "foreground_after": foreground_after,
        "current_thread_id": current_thread,
        "foreground_thread_id": foreground_thread,
        "root_thread_id": root_thread,
        "target_thread_id": target_thread,
        "attached_threads": attached,
        "attempts": attempts,
    }


# ---------------------------------------------------------------------------
# Item 9: Window handle rehydration — find windows belonging to a PID
# ---------------------------------------------------------------------------

def focus_hwnd(hwnd: int, timeout: float = 1.0, restore: bool = True) -> Dict[str, Any]:
    """Set foreground/active/focus for a top-level HWND or one of its child controls."""
    hwnd = int(hwnd or 0)
    if not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window {hwnd} not found", "hwnd": hwnd}

    root = int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
    target_thread = int(user32.GetWindowThreadProcessId(hwnd, None))
    root_thread = int(user32.GetWindowThreadProcessId(root, None))
    current_thread = int(kernel32.GetCurrentThreadId())
    foreground_before = int(user32.GetForegroundWindow() or 0)
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground_before, None)) if foreground_before else 0
    before = {
        "foreground": _window_info(foreground_before) if foreground_before else None,
        "target": _win32_window_info(hwnd, include_text=True),
        "root": _window_info(root),
        "gui_thread_info": gui_thread_info(hwnd=root),
    }
    foreground_repair = _force_foreground_window(root, timeout=timeout, restore=restore)
    foreground_for_focus = int(user32.GetForegroundWindow() or 0)
    foreground_focus_thread = int(user32.GetWindowThreadProcessId(foreground_for_focus, None)) if foreground_for_focus else 0
    attached: List[Dict[str, Any]] = []
    set_foreground_ok = bool(foreground_repair.get("ok"))
    previous_focus = 0

    def attach(thread_id: int, attach_flag: bool) -> bool:
        if thread_id <= 0 or thread_id == current_thread:
            return True
        ok = bool(user32.AttachThreadInput(current_thread, thread_id, attach_flag))
        attached.append({"thread_id": int(thread_id), "attach": bool(attach_flag), "ok": ok})
        return ok

    unique_threads: List[int] = []
    for tid in (foreground_focus_thread, root_thread, target_thread):
        if tid > 0 and tid != current_thread and tid not in unique_threads:
            unique_threads.append(tid)

    try:
        for tid in unique_threads:
            attach(tid, True)
        user32.SetActiveWindow(root)
        previous_focus = int(user32.SetFocus(hwnd) or 0)
        _pump_wait(
            lambda: (
                int(user32.GetForegroundWindow() or 0) == root
                and (
                    hwnd == root
                    or int((gui_thread_info(hwnd=root).get("handles") or {}).get("focus") or 0) == hwnd
                    or int(user32.GetFocus() or 0) == hwnd
                )
            ),
            timeout=max(float(timeout), 0.0),
        )
    finally:
        for tid in reversed(unique_threads):
            attach(tid, False)

    after_gui = gui_thread_info(hwnd=root)
    after_handles = after_gui.get("handles") or {}
    foreground_after = int(user32.GetForegroundWindow() or 0)
    active_after = int(after_handles.get("active") or 0)
    focus_after = int(after_handles.get("focus") or 0)
    ok = bool(foreground_after == root and (hwnd == root or focus_after == hwnd))
    return {
        "ok": ok,
        "hwnd": hwnd,
        "root_hwnd": root,
        "target_thread_id": target_thread,
        "root_thread_id": root_thread,
        "current_thread_id": current_thread,
        "foreground_thread_id": foreground_thread,
        "foreground_focus_thread_id": foreground_focus_thread,
        "set_foreground_ok": set_foreground_ok,
        "foreground_repair": foreground_repair,
        "previous_focus_hwnd": previous_focus,
        "foreground_after": foreground_after,
        "active_after": active_after,
        "focus_after": focus_after,
        "attached_threads": attached,
        "before": before,
        "after": {
            "foreground": _window_info(foreground_after) if foreground_after else None,
            "target": _win32_window_info(hwnd, include_text=True),
            "root": _window_info(root),
            "gui_thread_info": after_gui,
        },
    }


def _foreground_hwnd(hwnd: int, timeout: float = 1.0, restore: bool = True) -> Dict[str, Any]:
    """Bring a root HWND foreground without changing its child keyboard focus."""
    hwnd = int(hwnd or 0)
    if not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window {hwnd} not found", "hwnd": hwnd}

    root = int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
    root_thread = int(user32.GetWindowThreadProcessId(root, None))
    current_thread = int(kernel32.GetCurrentThreadId())
    foreground_before = int(user32.GetForegroundWindow() or 0)
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground_before, None)) if foreground_before else 0
    before_gui = gui_thread_info(hwnd=root)
    foreground_repair = _force_foreground_window(root, timeout=timeout, restore=restore)

    after_gui = gui_thread_info(hwnd=root)
    foreground_after = int(user32.GetForegroundWindow() or 0)
    return {
        "ok": bool(foreground_after == root),
        "hwnd": hwnd,
        "root_hwnd": root,
        "root_thread_id": root_thread,
        "current_thread_id": current_thread,
        "foreground_thread_id": foreground_thread,
        "set_foreground_ok": bool(foreground_repair.get("ok")),
        "foreground_before": foreground_before,
        "foreground_after": foreground_after,
        "attached_threads": foreground_repair.get("attached_threads") or [],
        "foreground_repair": foreground_repair,
        "before_gui_thread_info": before_gui,
        "after_gui_thread_info": after_gui,
    }


def _is_child_hwnd(hwnd: int) -> bool:
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    try:
        if int(user32.GetParent(hwnd) or 0):
            return True
        return bool(int(user32.GetWindowLongW(hwnd, GWL_STYLE)) & WS_CHILD)
    except Exception:
        return False


def _focused_hwnd_from_root(root_hwnd: int) -> Tuple[int, Dict[str, Any]]:
    thread_id = int(user32.GetWindowThreadProcessId(root_hwnd, None))
    info = gui_thread_info(hwnd=root_hwnd, thread_id=thread_id)
    focus = int((info.get("handles") or {}).get("focus") or 0) if info.get("ok") else 0
    if focus and user32.IsWindow(focus):
        return focus, info
    return int(root_hwnd), info


def _native_text_control_kind(hwnd: int) -> str:
    from win_automation.win32.controls import (
        _is_richedit_class,
        _is_edit_class,
        _edit_info,
        _richedit_info,
    )
    info = _win32_window_info(hwnd)
    class_name = (info or {}).get("class_name", "")
    if _is_richedit_class(class_name):
        return "richedit"
    if _is_edit_class(class_name):
        return "edit"
    if str(class_name).lower() in ("combobox", "comboboxex32"):
        return "combo"
    return ""



def _read_native_text_state(hwnd: int, kind: str, timeout_ms: int = 500) -> Dict[str, Any]:
    from win_automation.win32.controls import _edit_info, _richedit_info
    if not hwnd or not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window/control {hwnd} not found", "text": ""}
    if kind == "edit":
        return {"ok": True, "kind": kind, **_edit_info(hwnd, timeout_ms=timeout_ms)}
    if kind == "richedit":
        return {"ok": True, "kind": kind, **_richedit_info(hwnd, timeout_ms=timeout_ms)}
    text_info = _get_control_text(hwnd, timeout_ms=timeout_ms)
    return {"ok": bool(text_info.get("ok")), "kind": kind or "window", "text": text_info}



def _text_from_state(state: Dict[str, Any]) -> str:
    text_info = state.get("text") if isinstance(state, dict) else None
    if isinstance(text_info, dict):
        return str(text_info.get("text") or "")
    if isinstance(text_info, str):
        return text_info
    return ""


def _selection_from_state(state: Dict[str, Any]) -> Dict[str, int]:
    selection = state.get("selection") if isinstance(state, dict) else None
    if not isinstance(selection, dict):
        return {"start": 0, "end": 0}
    return {"start": int(selection.get("start", 0) or 0), "end": int(selection.get("end", 0) or 0)}


def _compact_gui_thread_info(info: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(info, dict):
        return {}
    return {
        "ok": bool(info.get("ok")),
        "error": info.get("error"),
        "hwnd": info.get("hwnd"),
        "thread_id": info.get("thread_id"),
        "flags": info.get("flags"),
        "handles": info.get("handles"),
        "caret_rect": info.get("caret_rect"),
    }


def _compact_focus_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    return {
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
        "hwnd": result.get("hwnd"),
        "root_hwnd": result.get("root_hwnd"),
        "foreground_before": result.get("foreground_before"),
        "foreground_after": result.get("foreground_after"),
        "active_after": result.get("active_after"),
        "focus_after": result.get("focus_after"),
        "set_foreground_ok": result.get("set_foreground_ok"),
        "attached_threads": result.get("attached_threads"),
    }


def _compact_window_info(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(info, dict):
        return None
    return {
        "hwnd": info.get("hwnd"),
        "title": info.get("title"),
        "class_name": info.get("class_name"),
        "control_id": info.get("control_id"),
        "pid": info.get("pid"),
        "thread_id": info.get("thread_id"),
        "process_name": info.get("process_name"),
        "visible": info.get("visible"),
        "enabled": info.get("enabled"),
        "is_child": info.get("is_child"),
        "parent_hwnd": info.get("parent_hwnd"),
        "root_hwnd": info.get("root_hwnd"),
        "root_owner_hwnd": info.get("root_owner_hwnd"),
        "rect": info.get("rect"),
        "text": info.get("text"),
    }



def get_windows_for_pid(pid: int) -> List[int]:
    """Return a list of visible window HWNDs belonging to *pid*."""
    hwnds: List[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            w_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
            if w_pid.value == pid:
                hwnds.append(int(hwnd))
        except Exception:
            pass
        return True

    user32.EnumWindows(callback, None)
    return hwnds


def get_window(hwnd: int) -> str:
    """
    Validate (and rehydrate) a window handle.
    If the HWND is stale, find another window from the same process.
    Returns JSON with the resolved HWND and metadata.
    """
    if user32.IsWindow(hwnd):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return json.dumps({
            "hwnd": hwnd,
            "title": buf.value.strip(),
            "pid": pid.value,
            "status": "valid",
        }, ensure_ascii=False)

    # Stale handle — try to recover by PID
    # We cannot get the PID from a dead HWND, so scan all windows
    # and find one whose PID matches any we've seen before.
    # Fallback: return an error with guidance.
    return json.dumps({
        "hwnd": hwnd,
        "status": "stale",
        "message": (
            f"HWND {hwnd} is no longer valid. "
            "Call list_windows to get current window handles."
        ),
    }, ensure_ascii=False)


def wait_window(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    from win_automation.win32.find import wait_window as _impl
    return _impl(*args, **kwargs)

