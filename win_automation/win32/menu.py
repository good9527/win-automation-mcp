"""
Win32 classic HMENU hierarchy inspection and command invocation.
"""

from __future__ import annotations

import json
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.win32_structures import *
from win_automation.win32.window import _win32_window_info, _send_message_timeout, activate_window
from win_automation.helper.client import (
    _helper_route_for_hwnd,
    _helper_post,
    _is_terminal_uia_helper_error,
    _helper_ok,
)




def _clean_menu_text(text: str) -> str:
    """Normalize Win32 menu labels for stable matching."""
    value = (text or "").replace("\t", " ").strip()
    value = value.replace("&&", "\0").replace("&", "").replace("\0", "&")
    while "  " in value:
        value = value.replace("  ", " ")
    return value


def _menu_text(menu: int, position: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    try:
        user32.GetMenuStringW(menu, int(position), buf, 512, MF_BYPOSITION)
        return buf.value
    except Exception:
        return ""


def _menu_state(menu: int, position: int) -> int:
    try:
        state = int(user32.GetMenuState(menu, int(position), MF_BYPOSITION))
        return 0 if state == MENU_ID_INVALID else state
    except Exception:
        return 0


def _menu_command_id(menu: int, position: int) -> Optional[int]:
    command_id = int(user32.GetMenuItemID(menu, int(position)))
    if command_id == MENU_ID_INVALID:
        return None
    return command_id


def _menu_children(
    menu: int,
    path_prefix: Optional[List[str]] = None,
    depth: int = 0,
    max_depth: int = 5,
    budget: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    if not menu:
        return []
    path_prefix = path_prefix or []
    budget = budget or [300]
    count = int(user32.GetMenuItemCount(menu))
    items: List[Dict[str, Any]] = []
    if count < 0:
        return items
    for position in range(count):
        if budget[0] <= 0:
            break
        budget[0] -= 1
        raw_text = _menu_text(menu, position)
        text = _clean_menu_text(raw_text)
        state = _menu_state(menu, position)
        submenu = int(user32.GetSubMenu(menu, position) or 0)
        command_id = _menu_command_id(menu, position)
        is_separator = bool(state & MF_SEPARATOR) or (not text and command_id is None and not submenu)
        path = path_prefix + ([text] if text else [f"#{position}"])
        item: Dict[str, Any] = {
            "position": position,
            "path": path,
            "text": text,
            "raw_text": raw_text,
            "command_id": command_id,
            "has_submenu": bool(submenu),
            "enabled": not bool(state & (MF_DISABLED | MF_GRAYED)),
            "checked": bool(state & MF_CHECKED),
            "separator": is_separator,
            "state": state,
            "submenu": submenu,
        }
        if submenu and depth + 1 < max_depth:
            item["children"] = _menu_children(submenu, path, depth + 1, max_depth, budget)
        elif submenu:
            item["children_truncated"] = True
        items.append(item)
    return items


def menu_tree(
    hwnd: int,
    include_system: bool = False,
    max_depth: int = 5,
    max_items: int = 300,
) -> Dict[str, Any]:
    """Return the classic Win32 HMENU tree for a window."""
    info = _win32_window_info(hwnd)
    if not info:
        return {"error": f"Window {hwnd} not found", "hwnd": hwnd}
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/menu_tree")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/menu_tree",
            {
                "hwnd": hwnd,
                "include_system": include_system,
                "max_depth": max_depth,
                "max_items": max_items,
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
    menu = int(user32.GetMenu(hwnd) or 0)
    system_menu = int(user32.GetSystemMenu(hwnd, False) or 0) if include_system else 0
    result: Dict[str, Any] = {
        "hwnd": hwnd,
        "window": info,
        "menu": {
            "handle": menu,
            "present": bool(menu),
            "items": _menu_children(menu, [], 0, max_depth, [max_items]) if menu else [],
        },
    }
    if include_system:
        result["system_menu"] = {
            "handle": system_menu,
            "present": bool(system_menu),
            "items": _menu_children(system_menu, ["system"], 0, max_depth, [max_items]) if system_menu else [],
        }
    return result


def _flatten_menu_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for item in items:
        flat.append(item)
        children = item.get("children") or []
        if children:
            flat.extend(_flatten_menu_items(children))
    return flat


def _normalize_menu_path(path: Any) -> List[str]:
    if path is None:
        return []
    if isinstance(path, str):
        text = path.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [_clean_menu_text(str(part)).lower() for part in parsed]
            except Exception:
                pass
        return [_clean_menu_text(part).lower() for part in text.replace("\\", "/").split("/") if part.strip()]
    if isinstance(path, (list, tuple)):
        return [_clean_menu_text(str(part)).lower() for part in path]
    return [_clean_menu_text(str(path)).lower()]


def _find_menu_item(items: List[Dict[str, Any]], path: Any = None, command_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    flat = _flatten_menu_items(items)
    if command_id is not None:
        for item in flat:
            if item.get("command_id") == int(command_id):
                return item
        return None
    wanted = _normalize_menu_path(path)
    if not wanted:
        return None
    for item in flat:
        candidate = [_clean_menu_text(str(part)).lower() for part in item.get("path", [])]
        if candidate == wanted:
            return item
    leaf = wanted[-1]
    matches = [
        item for item in flat
        if _clean_menu_text(str(item.get("text", ""))).lower() == leaf and item.get("command_id") is not None
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def menu_action(
    hwnd: int,
    path: Any = None,
    command_id: Optional[int] = None,
    include_system: bool = False,
    async_post: bool = False,
    timeout_ms: int = 500,
) -> Dict[str, Any]:
    """Invoke a classic HMENU command with WM_COMMAND/WM_SYSCOMMAND."""
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/menu_action")
    if boundary_result is not None:
        return boundary_result
    if helper_ready:
        helper_result = _helper_post(
            "/menu_action",
            {
                "hwnd": hwnd,
                "path": path,
                "command_id": command_id,
                "include_system": include_system,
                "async_post": async_post,
                "timeout_ms": timeout_ms,
            },
            elevated=helper_elevated,
        )
        if _helper_ok(helper_result):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
        if _is_terminal_uia_helper_error(helper_result):
            helper_result["helper"] = True
            helper_result["helper_elevated"] = bool(helper_elevated)
            return helper_result
    tree = menu_tree(hwnd, include_system=include_system, max_depth=8, max_items=800)
    if "error" in tree:
        return tree
    items = list((tree.get("menu") or {}).get("items") or [])
    if include_system:
        items.extend((tree.get("system_menu") or {}).get("items") or [])
    item = _find_menu_item(items, path=path, command_id=command_id)
    if not item:
        return {
            "error": "menu_item_not_found",
            "hwnd": hwnd,
            "path": path,
            "command_id": command_id,
            "available": [
                {"path": entry.get("path"), "text": entry.get("text"), "command_id": entry.get("command_id")}
                for entry in _flatten_menu_items(items)
                if entry.get("command_id") is not None
            ][:80],
        }
    if item.get("has_submenu") and item.get("command_id") is None:
        return {"error": "menu_path_resolves_to_submenu", "hwnd": hwnd, "item": item}
    if not item.get("enabled", True):
        return {"error": "menu_item_disabled", "hwnd": hwnd, "item": item}
    resolved_id = item.get("command_id")
    if resolved_id is None:
        return {"error": "menu_item_has_no_command_id", "hwnd": hwnd, "item": item}

    root = int((tree.get("window") or {}).get("root_hwnd") or hwnd)
    if root and user32.IsWindow(root):
        activate_window(root)
    message = WM_SYSCOMMAND if item.get("path", [None])[0] == "system" else WM_COMMAND
    if async_post:
        ok = bool(user32.PostMessageW(hwnd, message, int(resolved_id), 0))
        return {"ok": ok, "hwnd": hwnd, "method": "PostMessageW", "message": hex(message), "command_id": int(resolved_id), "item": item}
    ok, result = _send_message_timeout(hwnd, message, int(resolved_id), 0, timeout_ms=timeout_ms)
    if not ok:
        post_ok = bool(user32.PostMessageW(hwnd, message, int(resolved_id), 0))
        return {"ok": post_ok, "hwnd": hwnd, "method": "PostMessageW", "message": hex(message), "command_id": int(resolved_id), "item": item}
    return {"ok": True, "hwnd": hwnd, "method": "SendMessageTimeoutW", "message": hex(message), "command_id": int(resolved_id), "result": result, "item": item}



clean_menu_text = _clean_menu_text
