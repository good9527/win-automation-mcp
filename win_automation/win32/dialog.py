"""
Standard Win32 Dialogs: File Dialogs, Common Dialogs, and MessageBox manipulation.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.win32_structures import *
from win_automation.win32.window import _win32_window_info, _send_message_timeout, _pump_wait
from win_automation.win32.controls import win32_click, win32_set_text
from win_automation.helper.client import _helper_route_for_hwnd, _helper_post



def _dialog_kind_from_title(title: str) -> str:
    text = (title or "").strip().lower()
    if any(part in text for part in ("save", "保存", "另存", "存储")):
        return "save"
    if any(part in text for part in ("open", "select", "choose", "browse", "打开", "选择", "浏览")):
        return "open"
    return "file_dialog"


def _is_file_dialog_window(info: Dict[str, Any]) -> bool:
    if not isinstance(info, dict):
        return False
    if (info.get("class_name") or "").lower() != "#32770":
        return False
    if not info.get("visible", False):
        return False
    title = str(info.get("title", ""))
    return bool(title) or bool(info.get("root_owner_hwnd"))


def _find_file_dialog(hwnd: Optional[int] = None, timeout: float = 0.0, match: str = "contains") -> Dict[str, Any]:
    """Resolve a top-level file dialog, preferring the supplied/foreground HWND."""
    deadline = time.time() + max(float(timeout), 0.0)
    attempts = 0
    last_candidates: List[Dict[str, Any]] = []
    try:
        preferred = int(hwnd or 0)
    except Exception:
        preferred = 0
    preferred_info = _window_info(preferred) if preferred else None
    preferred_pid = int((preferred_info or {}).get("pid") or 0)
    preferred_root = int((preferred_info or {}).get("root_hwnd") or preferred or 0)
    preferred_root_owner = int((preferred_info or {}).get("root_owner_hwnd") or preferred_root or 0)

    while True:
        attempts += 1
        candidates: List[Dict[str, Any]] = []
        seen = set()

        for handle in (preferred, int(user32.GetForegroundWindow() or 0)):
            if handle and handle not in seen:
                info = _window_info(handle)
                seen.add(handle)
                if info and _is_file_dialog_window(info):
                    candidates.append(info)

        for window in enum_windows():
            handle = int(window.get("hwnd") or 0)
            if handle in seen:
                continue
            if _is_file_dialog_window(window):
                candidates.append(window)
                seen.add(handle)

        last_candidates = candidates
        if candidates:
            def score(window: Dict[str, Any]) -> int:
                value = 0
                candidate_hwnd = int(window.get("hwnd") or 0)
                candidate_owner = int(window.get("owner_hwnd") or 0)
                candidate_root_owner = int(window.get("root_owner_hwnd") or 0)
                candidate_pid = int(window.get("pid") or 0)
                if preferred and candidate_hwnd == preferred:
                    value += 100
                if preferred and candidate_owner == preferred:
                    value += 90
                if preferred_root and candidate_owner == preferred_root:
                    value += 85
                if preferred_root_owner and candidate_root_owner in (preferred, preferred_root, preferred_root_owner):
                    value += 80
                if preferred_pid and candidate_pid == preferred_pid:
                    value += 40
                if candidate_hwnd == int(user32.GetForegroundWindow() or 0):
                    value += 50
                kind = _dialog_kind_from_title(str(window.get("title", "")))
                if kind in ("open", "save"):
                    value += 10
                return value

            return {
                "ok": True,
                "attempts": attempts,
                "window": sorted(candidates, key=score, reverse=True)[0],
                "candidates": candidates[:10],
            }

        if time.time() >= deadline:
            break
        time.sleep(0.1)

    return {
        "ok": False,
        "error": "file_dialog_not_found",
        "attempts": attempts,
        "hwnd": preferred or None,
        "candidates": last_candidates[:10],
    }


def _rank_file_name_controls(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for child in children:
        class_name = (child.get("class_name") or "").lower()
        text_info = child.get("text") if isinstance(child.get("text"), dict) else {}
        text_value = str((text_info or {}).get("text") or child.get("title") or "")
        control_id = int(child.get("control_id") or 0)
        if "comboboxex32" not in class_name and "combobox" not in class_name and not _is_edit_class(class_name):
            continue
        score = 0
        if control_id in (1148, 1152, 1001):
            score += 40
        if "comboboxex32" in class_name:
            score += 35
        elif "combobox" in class_name:
            score += 25
        elif _is_edit_class(class_name):
            score += 15
        if child.get("enabled", False):
            score += 8
        if child.get("visible", False):
            score += 8
        rect = child.get("rect") or {}
        width = int(rect.get("width", 0) or 0)
        height = int(rect.get("height", 0) or 0)
        if width >= 140 and 14 <= height <= 80:
            score += 8
        if text_value and ("\\" in text_value or "/" in text_value or "." in text_value):
            score += 6
        item = dict(child)
        item["_score"] = score
        ranked.append(item)
    ranked.sort(key=lambda item: item.get("_score", 0), reverse=True)
    return ranked


def _rank_file_dialog_buttons(children: List[Dict[str, Any]], action: str) -> List[Dict[str, Any]]:
    action_name = str(action or "confirm").lower().replace("-", "_")
    positive_words = {
        "open", "打开", "save", "保存", "select", "选择", "choose", "确定", "ok", "yes", "是",
    }
    cancel_words = {"cancel", "取消", "关闭", "close", "no", "否"}
    ranked: List[Dict[str, Any]] = []
    for child in children:
        class_name = (child.get("class_name") or "").lower()
        if "button" not in class_name:
            continue
        title = str(child.get("title") or "")
        text_info = child.get("text") if isinstance(child.get("text"), dict) else {}
        text_value = str((text_info or {}).get("text") or title)
        text_lower = text_value.strip().lower().replace("&", "")
        control_id = int(child.get("control_id") or 0)
        score = 0
        if action_name in ("cancel", "close"):
            if control_id == IDCANCEL:
                score += 60
            if any(word in text_lower for word in cancel_words):
                score += 20
        else:
            if control_id == IDOK:
                score += 60
            if any(word in text_lower for word in positive_words):
                score += 20
        if child.get("enabled", False):
            score += 8
        if child.get("visible", False):
            score += 8
        if score > 0:
            item = dict(child)
            item["_score"] = score
            ranked.append(item)
    ranked.sort(key=lambda item: item.get("_score", 0), reverse=True)
    return ranked


def _file_dialog_controls(hwnd: int, include_text: bool = True, timeout_ms: int = 300) -> Dict[str, Any]:
    children_result = child_windows(hwnd, include_invisible=False, include_text=include_text, max_count=900)
    if "error" in children_result:
        return children_result
    children = children_result.get("children") or []
    filename_controls = _rank_file_name_controls(children)
    confirm_buttons = _rank_file_dialog_buttons(children, "confirm")
    cancel_buttons = _rank_file_dialog_buttons(children, "cancel")
    controls: Dict[str, Any] = {
        "children_count": len(children),
        "filename_controls": filename_controls[:8],
        "confirm_buttons": confirm_buttons[:6],
        "cancel_buttons": cancel_buttons[:6],
    }
    primary = filename_controls[0] if filename_controls else None
    if primary:
        primary_hwnd = int(primary.get("hwnd") or 0)
        controls["filename_hwnd"] = primary_hwnd
        controls["filename_control"] = primary
        try:
            controls["filename_info"] = win32_control_info(primary_hwnd, timeout_ms=timeout_ms)
        except Exception as e:
            controls["filename_info_error"] = str(e)
    if confirm_buttons:
        controls["confirm_hwnd"] = int(confirm_buttons[0].get("hwnd") or 0)
        controls["confirm_button"] = confirm_buttons[0]
    if cancel_buttons:
        controls["cancel_hwnd"] = int(cancel_buttons[0].get("hwnd") or 0)
        controls["cancel_button"] = cancel_buttons[0]
    return controls


def file_dialog_info(
    hwnd: Optional[int] = None,
    timeout: float = 0.0,
    timeout_ms: int = 300,
    include_children: bool = False,
) -> Dict[str, Any]:
    """Inspect a standard Windows Open/Save file dialog and its actionable controls."""
    resolved = _find_file_dialog(hwnd=hwnd, timeout=timeout)
    if not resolved.get("ok"):
        return resolved
    window = resolved.get("window") or {}
    dialog_hwnd = int(window.get("hwnd") or 0)
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(dialog_hwnd, "/file_dialog_info")
    if boundary_result is not None:
        boundary_result["preflight"] = {
            "ok": True,
            "hwnd": dialog_hwnd,
            "window": window,
            "attempts": resolved.get("attempts"),
        }
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/file_dialog_info",
            {
                "hwnd": dialog_hwnd,
                "timeout": 0.0,
                "timeout_ms": timeout_ms,
                "include_children": include_children,
            },
            elevated=helper_elevated,
        )
        if helper_result.get("ok"):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            helper_result["attempts"] = resolved.get("attempts")
            return helper_result
    controls = _file_dialog_controls(dialog_hwnd, include_text=True, timeout_ms=timeout_ms)
    result = {
        "ok": True,
        "hwnd": dialog_hwnd,
        "kind": _dialog_kind_from_title(str(window.get("title", ""))),
        "window": window,
        "controls": controls,
        "attempts": resolved.get("attempts"),
    }
    if include_children:
        result["children"] = child_windows(dialog_hwnd, include_invisible=False, include_text=True, max_count=900)
    return result


def _set_file_dialog_filename(hwnd: int, path: str, timeout_ms: int = 500) -> Dict[str, Any]:
    controls = _file_dialog_controls(hwnd, include_text=True, timeout_ms=timeout_ms)
    if "error" in controls:
        return controls
    filename_hwnd = int(controls.get("filename_hwnd") or 0)
    if not filename_hwnd:
        return {"ok": False, "error": "filename_control_not_found", "controls": controls}
    info = controls.get("filename_info") if isinstance(controls.get("filename_info"), dict) else win32_control_info(filename_hwnd, timeout_ms=timeout_ms)
    kind = str((info or {}).get("kind") or "").lower()
    if kind in ("comboboxex", "combobox"):
        set_result = win32_control_action(filename_hwnd, "set-value", text=path, timeout_ms=timeout_ms)
    elif kind in ("combobox", "edit", "richedit"):
        set_result = win32_set_text(filename_hwnd, path, timeout_ms=timeout_ms)
    else:
        set_result = win32_set_text(filename_hwnd, path, timeout_ms=timeout_ms)
    return {
        "ok": bool(set_result.get("ok")),
        "filename_hwnd": filename_hwnd,
        "path": path,
        "method": "win32_control_action" if kind in ("comboboxex", "combobox") else "WM_SETTEXT",
        "control_kind": kind,
        "set_result": set_result,
        "controls": controls,
    }


def _command_dialog(hwnd: int, command_id: int, timeout_ms: int = 500) -> Dict[str, Any]:
    boundary_result = _elevated_helper_required_result(hwnd, "/dialog_command")
    if boundary_result is not None:
        boundary_result["command_id"] = int(command_id)
        return boundary_result
    ok, result = _send_message_timeout(hwnd, WM_COMMAND, int(command_id), 0, timeout_ms=timeout_ms)
    if ok:
        return {"ok": True, "hwnd": hwnd, "method": "SendMessageTimeoutW", "message": "WM_COMMAND", "command_id": int(command_id), "result": result}
    post_ok = bool(user32.PostMessageW(hwnd, WM_COMMAND, int(command_id), 0))
    return {"ok": post_ok, "hwnd": hwnd, "method": "PostMessageW", "message": "WM_COMMAND", "command_id": int(command_id)}


_DIALOG_COMMAND_IDS: Dict[str, int] = {
    "ok": IDOK,
    "okay": IDOK,
    "confirm": IDOK,
    "accept": IDOK,
    "apply": IDOK,
    "open": IDOK,
    "save": IDOK,
    "select": IDOK,
    "choose": IDOK,
    "\u786e\u5b9a": IDOK,
    "\u662f": IDYES,
    "yes": IDYES,
    "y": IDYES,
    "\u5426": IDNO,
    "no": IDNO,
    "n": IDNO,
    "cancel": IDCANCEL,
    "dismiss": IDCANCEL,
    "\u53d6\u6d88": IDCANCEL,
    "abort": IDABORT,
    "\u4e2d\u6b62": IDABORT,
    "retry": IDRETRY,
    "\u91cd\u8bd5": IDRETRY,
    "ignore": IDIGNORE,
    "\u5ffd\u7565": IDIGNORE,
    "close": IDCLOSE,
    "\u5173\u95ed": IDCLOSE,
    "help": IDHELP,
    "\u5e2e\u52a9": IDHELP,
    "tryagain": IDTRYAGAIN,
    "try_again": IDTRYAGAIN,
    "\u518d\u8bd5\u4e00\u6b21": IDTRYAGAIN,
    "continue": IDCONTINUE,
    "\u7ee7\u7eed": IDCONTINUE,
}
_DIALOG_COMMAND_NAMES: Dict[int, str] = {
    IDOK: "ok",
    IDCANCEL: "cancel",
    IDABORT: "abort",
    IDRETRY: "retry",
    IDIGNORE: "ignore",
    IDYES: "yes",
    IDNO: "no",
    IDCLOSE: "close",
    IDHELP: "help",
    IDTRYAGAIN: "try_again",
    IDCONTINUE: "continue",
}


def _normalize_dialog_command_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("&", "").replace("...", "").replace("\u2026", "")
    text = re.sub(r"[\s\-_:/\\|,.;!?\[\]{}()<>\uff08\uff09\uff1a\uff1b\uff01\uff1f]+", "", text)
    return text


def _dialog_command_id_from_value(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except Exception:
        pass
    normalized = _normalize_dialog_command_token(text)
    if normalized in _DIALOG_COMMAND_IDS:
        return _DIALOG_COMMAND_IDS[normalized]
    underscore = str(text).strip().lower().replace("-", "_").replace(" ", "_")
    return _DIALOG_COMMAND_IDS.get(underscore)


def _dialog_command_id_for(
    command_id: Any = None,
    action: Any = None,
    name: Any = None,
    text: Any = None,
) -> Optional[int]:
    for value in (command_id, action, name, text):
        resolved = _dialog_command_id_from_value(value)
        if resolved is not None:
            return resolved
    return None


def _dialog_wait_compact(wait_result: Dict[str, Any], diagnostic: bool = False) -> Dict[str, Any]:
    if diagnostic:
        return wait_result
    return {
        "ok": bool(wait_result.get("ok")),
        "waited": wait_result.get("waited"),
        "wait_attempts": wait_result.get("wait_attempts"),
        "stable_ticks": wait_result.get("stable_ticks"),
        "direct": wait_result.get("direct"),
        "candidates": wait_result.get("candidates"),
    }


def _is_direct_dialog_window(info: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(info, dict):
        return False
    if str(info.get("class_name") or "").lower() == "#32770":
        return True
    hwnd = int(info.get("hwnd") or 0)
    root = int(info.get("root_hwnd") or hwnd or 0)
    root_owner = int(info.get("root_owner_hwnd") or root or 0)
    owner = int(info.get("owner_hwnd") or 0)
    return bool(owner or (root_owner and root_owner != root))


def _wait_or_use_related_dialog(
    hwnd: Optional[int],
    dialog_title: Optional[str] = None,
    dialog_class_name: Optional[str] = None,
    dialog_process: Optional[str] = None,
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.25,
    include_invisible: bool = False,
    diagnostic: bool = False,
) -> Dict[str, Any]:
    target = _resolve_target(hwnd)
    direct_info = _window_info(target)
    if not direct_info:
        return {"ok": False, "error": f"Window {target} not found", "hwnd": target}
    if (
        _is_direct_dialog_window(direct_info)
        and (include_invisible or direct_info.get("visible", False))
        and (include_invisible or _is_usable_window_info(direct_info))
        and _dialog_window_matches(
            direct_info,
            dialog_title=dialog_title,
            dialog_class_name=dialog_class_name,
            dialog_process=dialog_process,
            match=match,
        )
    ):
        return {
            "ok": True,
            "hwnd": target,
            "dialog_hwnd": target,
            "dialog": direct_info,
            "target": direct_info,
            "waited": 0.0,
            "wait_attempts": 0,
            "timeout": float(timeout),
            "interval": max(float(interval), 0.05),
            "stable_ticks": 1,
            "direct": True,
            "candidates": [direct_info if diagnostic else _compact_window_info(direct_info)],
            "wait_polls": [],
        }
    return wait_related_dialog(
        target,
        dialog_title=dialog_title,
        dialog_class_name=dialog_class_name,
        dialog_process=dialog_process,
        match=match,
        timeout=timeout,
        interval=interval,
        include_invisible=include_invisible,
        diagnostic=diagnostic,
    )


def dialog_command_action(
    hwnd: Optional[int],
    action: Optional[str] = None,
    command_id: Any = None,
    name: Optional[str] = None,
    dialog_title: Optional[str] = None,
    dialog_class_name: Optional[str] = None,
    dialog_process: Optional[str] = None,
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.25,
    timeout_ms: int = 500,
    include_invisible: bool = False,
    activate: bool = True,
    verify_close: bool = False,
    diagnostic: bool = False,
) -> Dict[str, Any]:
    """Wait for a related standard dialog and send a WM_COMMAND button id."""
    effective_action = action if action is not None or name is not None else "ok"
    resolved_command_id = _dialog_command_id_for(command_id, effective_action, name)
    if resolved_command_id is None:
        return {
            "ok": False,
            "error": "unsupported_dialog_command",
            "action": effective_action,
            "name": name,
            "command_id": command_id,
            "supported": sorted(_DIALOG_COMMAND_IDS.keys()),
        }

    wait_result = _wait_or_use_related_dialog(
        hwnd,
        dialog_title=dialog_title,
        dialog_class_name=dialog_class_name,
        dialog_process=dialog_process,
        match=match,
        timeout=timeout,
        interval=interval,
        include_invisible=include_invisible,
        diagnostic=diagnostic,
    )
    if not wait_result.get("ok"):
        result = dict(wait_result)
        result["method"] = "dialog_command_action.wait_failed"
        result["action"] = effective_action
        result["command_id"] = resolved_command_id
        return result

    dialog_hwnd = int(wait_result.get("dialog_hwnd") or 0)
    activation_result: Optional[bool] = None

    if os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER") != "1":
        helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(dialog_hwnd, "/dialog_command_action")
        if boundary_result is not None:
            boundary_result.update({
                "action": effective_action,
                "command_id": int(resolved_command_id),
                "dialog_wait": _dialog_wait_compact(wait_result, diagnostic),
            })
            return boundary_result
        if helper_ready:
            helper_result = _helper_post(
                "/dialog_command_action",
                {
                    "hwnd": dialog_hwnd,
                    "action": effective_action,
                    "command_id": resolved_command_id,
                    "name": name,
                    "timeout": 0.0,
                    "interval": interval,
                    "timeout_ms": timeout_ms,
                    "include_invisible": include_invisible,
                    "activate": activate,
                    "verify_close": verify_close,
                    "diagnostic": diagnostic,
                },
                elevated=helper_elevated,
            )
            if _helper_ok(helper_result):
                helper_result["helper"] = True
                helper_result["helper_elevated"] = bool(helper_elevated)
                helper_result.setdefault("dialog_wait", _dialog_wait_compact(wait_result, diagnostic))
                helper_result.setdefault("activated", activation_result)
                return helper_result

    boundary_result = _elevated_helper_required_result(dialog_hwnd, "/dialog_command_action")
    if boundary_result is not None:
        boundary_result.update({
            "action": effective_action,
            "command_id": int(resolved_command_id),
            "dialog_wait": _dialog_wait_compact(wait_result, diagnostic),
        })
        return boundary_result

    if activate and dialog_hwnd:
        activation_result = activate_window(dialog_hwnd)

    command = _command_dialog(dialog_hwnd, int(resolved_command_id), timeout_ms=timeout_ms)
    closed = None
    if verify_close:
        closed = _pump_wait(lambda: not user32.IsWindow(dialog_hwnd), timeout=max(float(timeout), 0.0), interval=0.05)

    ok = bool(command.get("ok"))
    result: Dict[str, Any] = {
        "ok": ok,
        "hwnd": wait_result.get("hwnd"),
        "dialog_hwnd": dialog_hwnd,
        "method": "dialog_command_action.WM_COMMAND" if ok else "dialog_command_action.failed",
        "action": effective_action,
        "command_id": int(resolved_command_id),
        "command_name": _DIALOG_COMMAND_NAMES.get(int(resolved_command_id)),
        "dialog": wait_result.get("dialog"),
        "dialog_wait": _dialog_wait_compact(wait_result, diagnostic),
        "activated": activation_result,
        "command": command,
        "closed": closed,
    }
    if not ok:
        result["error"] = command.get("error", "WM_COMMAND failed")
    if closed is False:
        result["ok"] = False
        result["method"] = "dialog_command_action.not_closed"
        result["error"] = "dialog_did_not_close"
    return result


def file_dialog_action(
    action: str,
    hwnd: Optional[int] = None,
    path: Optional[str] = None,
    timeout: float = 5.0,
    timeout_ms: int = 500,
    verify_close: bool = False,
) -> Dict[str, Any]:
    """Set, confirm, or cancel a standard Windows Open/Save file dialog."""
    action_name = str(action or "").strip().lower().replace("-", "_")
    if action_name in ("open", "save", "select", "choose"):
        action_name = "confirm"
    if action_name in ("set", "set_path", "set_filename", "filename"):
        action_name = "set_filename"
    if action_name in ("ok", "accept"):
        action_name = "confirm"
    if action_name in ("close", "dismiss"):
        action_name = "cancel"
    if action_name not in ("info", "set_filename", "confirm", "cancel"):
        return {"ok": False, "error": f"Unsupported file dialog action: {action}", "supported": ["info", "set-filename", "confirm", "cancel", "open", "save", "select"]}

    preflight = file_dialog_info(hwnd=hwnd, timeout=timeout, timeout_ms=timeout_ms, include_children=False)
    if not preflight.get("ok"):
        return preflight
    dialog_hwnd_preflight = int(preflight.get("hwnd") or 0)
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(dialog_hwnd_preflight, "/file_dialog_action")
    if boundary_result is not None:
        boundary_result["preflight"] = preflight
        boundary_result["action"] = action_name
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/file_dialog_action",
            {
                "action": action,
                "hwnd": dialog_hwnd_preflight,
                "path": path,
                "timeout": 0.0,
                "timeout_ms": timeout_ms,
                "verify_close": verify_close,
            },
            elevated=helper_elevated,
        )
        if _helper_ok(helper_result):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result

    info = preflight
    if not info.get("ok"):
        return info
    dialog_hwnd = int(info.get("hwnd") or 0)
    if not dialog_hwnd or not user32.IsWindow(dialog_hwnd):
        return {"ok": False, "error": "file_dialog_not_found", "info": info}

    result: Dict[str, Any] = {"ok": False, "action": action_name, "hwnd": dialog_hwnd, "before": info}
    if action_name == "info":
        result.update({"ok": True})
        return result

    if dialog_hwnd:
        activate_window(dialog_hwnd)

    if action_name == "set_filename":
        if path is None:
            return {"ok": False, "error": "path required for set-filename", **result}
        set_result = _set_file_dialog_filename(dialog_hwnd, str(path), timeout_ms=timeout_ms)
        after = file_dialog_info(hwnd=dialog_hwnd, timeout=0.0, timeout_ms=timeout_ms)
        result.update({"ok": bool(set_result.get("ok")), "path": str(path), "set_filename": set_result, "after": after})
        return result

    set_result = None
    if path is not None:
        set_result = _set_file_dialog_filename(dialog_hwnd, str(path), timeout_ms=timeout_ms)
        result["set_filename"] = set_result
        if not set_result.get("ok"):
            result.update({"ok": False, "error": "failed_to_set_filename", "path": str(path)})
            return result

    command_id = IDCANCEL if action_name == "cancel" else IDOK
    command = _command_dialog(dialog_hwnd, command_id, timeout_ms=timeout_ms)
    button_fallback = None
    if not command.get("ok"):
        controls = (info.get("controls") or {})
        button_hwnd = int((controls.get("cancel_hwnd") if action_name == "cancel" else controls.get("confirm_hwnd")) or 0)
        if button_hwnd:
            button_fallback = win32_click(button_hwnd, timeout_ms=timeout_ms)
    closed = None
    if verify_close:
        closed = _pump_wait(lambda: not user32.IsWindow(dialog_hwnd), timeout=max(float(timeout), 0.0), interval=0.05)
    result.update({
        "ok": bool(command.get("ok") or (button_fallback or {}).get("ok")),
        "path": str(path) if path is not None else None,
        "command": command,
        "button_fallback": button_fallback,
        "closed": closed,
    })
    if closed is False:
        result["ok"] = False
        result["error"] = "dialog_did_not_close"
    return result



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


def dialog_button_action(
    hwnd: Optional[int],
    name: Optional[str] = None,
    action: Optional[str] = None,
    command_id: Any = None,
    dialog_title: Optional[str] = None,
    dialog_class_name: Optional[str] = None,
    dialog_process: Optional[str] = None,
    automation_id: Optional[str] = None,
    class_name: Optional[str] = None,
    control_type: Optional[str] = None,
    index: Optional[int] = None,
    match: str = "contains",
    timeout: float = 10.0,
    interval: float = 0.25,
    timeout_ms: int = 500,
    include_invisible: bool = False,
    activate: bool = True,
    verify_close: bool = False,
    prefer_command: bool = True,
    diagnostic: bool = False,
) -> Dict[str, Any]:
    """Wait for a related dialog and trigger a native Win32 dialog button."""
    wait_result = _wait_or_use_related_dialog(
        hwnd,
        dialog_title=dialog_title,
        dialog_class_name=dialog_class_name,
        dialog_process=dialog_process,
        match=match,
        timeout=timeout,
        interval=interval,
        include_invisible=include_invisible,
        diagnostic=diagnostic,
    )
    if not wait_result.get("ok"):
        result = dict(wait_result)
        result["method"] = "dialog_button_action.wait_failed"
        return result

    dialog_hwnd = int(wait_result.get("dialog_hwnd") or 0)
    activation_result: Optional[bool] = None

    if os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER") != "1":
        helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(dialog_hwnd, "/dialog_button_action")
        if boundary_result is not None:
            boundary_result.update({
                "action": action,
                "name": name,
                "command_id": command_id,
                "dialog": wait_result.get("dialog"),
                "dialog_wait": _dialog_wait_compact(wait_result, diagnostic),
            })
            return boundary_result
        if helper_ready:
            helper_result = _helper_post(
                "/dialog_button_action",
                {
                    "hwnd": dialog_hwnd,
                    "name": name,
                    "action": action,
                    "command_id": command_id,
                    "dialog_title": None,
                    "dialog_class_name": None,
                    "dialog_process": None,
                    "automation_id": automation_id,
                    "class_name": class_name,
                    "control_type": control_type,
                    "index": index,
                    "match": match,
                    "timeout": 0.0,
                    "interval": interval,
                    "timeout_ms": timeout_ms,
                    "include_invisible": include_invisible,
                    "activate": activate,
                    "verify_close": verify_close,
                    "prefer_command": prefer_command,
                    "diagnostic": diagnostic,
                },
                elevated=helper_elevated,
            )
            if _helper_ok(helper_result):
                helper_result["helper"] = True
                helper_result["helper_elevated"] = bool(helper_elevated)
                helper_result.setdefault("dialog_wait", _dialog_wait_compact(wait_result, diagnostic))
                helper_result.setdefault("activated", activation_result)
                return helper_result

    boundary_result = _elevated_helper_required_result(dialog_hwnd, "/dialog_button_action")
    if boundary_result is not None:
        boundary_result.update({
            "action": action,
            "name": name,
            "command_id": command_id,
            "dialog": wait_result.get("dialog"),
            "dialog_wait": _dialog_wait_compact(wait_result, diagnostic),
        })
        return boundary_result

    if activate and dialog_hwnd:
        activation_result = activate_window(dialog_hwnd)

    attempts: List[Dict[str, Any]] = []
    resolved_command_id = _dialog_command_id_for(command_id, action, name)
    if prefer_command and resolved_command_id is not None:
        command_result = _command_dialog(dialog_hwnd, int(resolved_command_id), timeout_ms=timeout_ms)
        attempts.append({
            "method": "dialog.WM_COMMAND",
            "command_id": int(resolved_command_id),
            "command_name": _DIALOG_COMMAND_NAMES.get(int(resolved_command_id)),
            "result": command_result,
        })
        closed = None
        if verify_close:
            closed = _pump_wait(lambda: not user32.IsWindow(dialog_hwnd), timeout=max(float(timeout), 0.0), interval=0.05)
        if command_result.get("ok") and closed is not False:
            return {
                "ok": True,
                "hwnd": wait_result.get("hwnd"),
                "dialog_hwnd": dialog_hwnd,
                "method": "dialog_button_action.WM_COMMAND",
                "action": action,
                "command_id": int(resolved_command_id),
                "command_name": _DIALOG_COMMAND_NAMES.get(int(resolved_command_id)),
                "dialog": wait_result.get("dialog"),
                "dialog_wait": _dialog_wait_compact(wait_result, diagnostic),
                "activated": activation_result,
                "closed": closed,
                "attempts": attempts,
            }
        if closed is False:
            attempts[-1]["closed"] = closed
            attempts[-1]["error"] = "dialog_did_not_close"

    candidates = _win32_click_candidates(
        dialog_hwnd,
        name=name,
        automation_id=automation_id,
        class_name=class_name,
        control_type=control_type or "button",
        index=index,
        match=match,
        include_invisible=include_invisible,
        timeout_ms=timeout_ms,
    )
    attempts.append({
        "method": "win32.find_dialog_button",
        "count": len(candidates),
        "candidates": candidates if diagnostic else [_compact_window_info(candidate.get("window")) for candidate in candidates[:8]],
    })
    for candidate in candidates:
        button_hwnd = int(candidate.get("hwnd") or 0)
        if not button_hwnd:
            continue
        click_result = win32_click(button_hwnd, timeout_ms=timeout_ms)
        attempts.append({
            "method": "win32.click",
            "target": candidate if diagnostic else _compact_window_info(candidate.get("window")),
            "result": click_result if diagnostic else {key: click_result.get(key) for key in ("ok", "error", "method", "result", "helper", "helper_elevated")},
        })
        if click_result.get("ok"):
            return {
                "ok": True,
                "hwnd": wait_result.get("hwnd"),
                "dialog_hwnd": dialog_hwnd,
                "method": "dialog_button_action.win32_click",
                "button_hwnd": button_hwnd,
                "target": candidate,
                "dialog": wait_result.get("dialog"),
                "dialog_wait": _dialog_wait_compact(wait_result, diagnostic),
                "activated": activation_result,
                "attempts": attempts,
            }

    return {
        "ok": False,
        "hwnd": wait_result.get("hwnd"),
        "dialog_hwnd": dialog_hwnd,
        "method": "dialog_button_action.failed",
        "error": "No matching native Win32 dialog button found or clicked",
        "selector": {
            "name": name,
            "action": action,
            "command_id": command_id,
            "automation_id": automation_id,
            "class_name": class_name,
            "control_type": control_type or "button",
            "index": index,
            "match": match,
        },
        "dialog": wait_result.get("dialog"),
        "dialog_wait": _dialog_wait_compact(wait_result, diagnostic),
        "activated": activation_result,
        "attempts": attempts,
        "failure_summary": _compact_attempt_failure_summary(attempts),
    }



file_dialog = file_dialog_info
dialog_command = dialog_command_action
dialog_button = dialog_button_action

