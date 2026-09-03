from __future__ import annotations
from PIL import Image as PILImage
"""
Comprehensive internal diagnostic selftests across UI subsystems.
"""


import os
import sys
import time
import json
import ctypes
import tempfile
import subprocess
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.win32.window import (
    enum_windows,
    get_window,
    activate_window,
    _window_info,
    launch_app,
    wait_window,
)
from win_automation.batch.engine import _batch_normalize_result
from win_automation.win32.controls import win32_control_info, win32_control_action, win32_set_text, win32_click
from win_automation.win32.menu import menu_tree, menu_action
from win_automation.win32.dialog import file_dialog_info, file_dialog_action
from win_automation.uia.engine import get_uia_client, _uia_element_cache, _DESKTOP_UIA_KEY
from win_automation.uia.tree import build_accessibility_tree, find_elements, desktop_accessibility
from win_automation.uia.patterns import click_index, perform_action
from win_automation.input.keyboard import type_text, press_key
from win_automation.input.mouse import click, move_mouse
from win_automation.input.clipboard import _clipboard_snapshot, _clipboard_restore_snapshot, _set_clipboard_text
from win_automation.helper.client import _helper_route_for_hwnd, _helper_post, _helper_available, _helper_current
from win_automation.state.persistence import resolve_target_hwnd
from win_automation.ocr.finder import _run_windows_ocr_on_image, _run_tesseract_ocr_on_image, _find_ocr_text_matches, _wait_for_ocr_text_result

def selftest_notepad(timeout: float = 15.0) -> Dict[str, Any]:
    """Exercise a real Notepad window end-to-end using a temporary file."""
    token = f"win-auto-selftest {int(time.time())} ascii OK"
    temp_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(temp_dir, exist_ok=True)
    path = os.path.join(temp_dir, f"selftest-{int(time.time() * 1000)}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("")

    report: Dict[str, Any] = {
        "app": "notepad",
        "file": path,
        "token": token,
        "steps": {},
    }
    hwnd: Optional[int] = None
    try:
        launch = launch_app(path, timeout=timeout)
        report["steps"]["launch"] = launch
        window = launch.get("window") if isinstance(launch, dict) else None
        if not isinstance(window, dict) or not window.get("hwnd"):
            waited = wait_window(process="notepad", timeout=timeout)
            report["steps"]["wait_window"] = waited
            window = waited.get("window") if isinstance(waited, dict) else None
        if not isinstance(window, dict) or not window.get("hwnd"):
            report["ok"] = False
            report["error"] = "Notepad window did not appear"
            return report

        hwnd = int(window["hwnd"])
        stable_window = _wait_stable_window(
            hwnd=hwnd,
            process="notepad",
            pid=int(window.get("pid") or 0) if window.get("pid") is not None else None,
            timeout=min(3.0, max(0.5, timeout)),
            interval=0.1,
            stable_ticks=2,
        )
        report["steps"]["stable_window"] = stable_window
        if stable_window.get("ok") and isinstance(stable_window.get("window"), dict):
            window = stable_window["window"]
            hwnd = int(window["hwnd"])
        else:
            report["ok"] = False
            report["error"] = "Notepad window did not reach stable visible bounds"
            return report

        report["hwnd"] = hwnd
        report["steps"]["activate"] = {"ok": activate_window(hwnd)}
        obs = observe(hwnd, include_screenshot=True, include_accessibility=True, max_width=800, max_depth=5, max_elements=120)
        report["steps"]["observe"] = {
            "screenshot": obs.get("screenshot"),
            "element_count": (obs.get("accessibility") or {}).get("element_count"),
        }

        edit_match = find_elements(hwnd, control_type="edit", visible_only=True, limit=1, max_depth=8, max_elements=200)
        if not edit_match.get("matches"):
            edit_match = find_elements(hwnd, control_type="document", visible_only=True, limit=1, max_depth=8, max_elements=200)
        if not edit_match.get("matches"):
            edit_match = find_elements(hwnd, class_name="RichEdit", visible_only=True, limit=1, max_depth=8, max_elements=200)
        report["steps"]["find_editor"] = edit_match
        matches = edit_match.get("matches") or []
        value_verified = False
        if matches:
            idx = int(matches[0]["index"])
            report["steps"]["focus_edit"] = focus_element(hwnd, idx)
            set_result = set_value(hwnd, idx, token)
            report["steps"]["set_value"] = set_result
            if "error" not in set_result:
                _, updated_info = _uia_element_by_index(hwnd, idx, max_depth=8, max_elements=200)
                current_value = (updated_info or {}).get("value", "")
                value_verified = token in current_value
                report["steps"]["value_readback"] = {"ok": value_verified, "value": current_value}
            else:
                report["steps"]["type_text"] = type_text(hwnd, token)
                time.sleep(0.5)
                _, updated_info = _uia_element_by_index(hwnd, idx, max_depth=8, max_elements=200)
                current_value = (updated_info or {}).get("value", "")
                value_verified = token in current_value
                report["steps"]["value_readback"] = {"ok": value_verified, "value": current_value}
        else:
            meta = obs.get("screenshot") or {}
            click_x = int(meta.get("width", 800) * 0.5)
            click_y = int(meta.get("height", 500) * 0.5)
            report["steps"]["focus_click"] = click(hwnd, click_x, click_y, screenshot_id=meta.get("id"))
            report["steps"]["type_text"] = type_text(hwnd, token)
            time.sleep(0.5)

        if matches:
            report["steps"]["clear_value"] = set_value(hwnd, int(matches[0]["index"]), "")
        report["steps"]["save"] = press_key(hwnd, "Control_L+s")
        time.sleep(0.75)
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            contents = f.read()
        report["steps"]["file_after_cleanup_save"] = {"ok": contents == "", "contents": contents}
        report["ok"] = bool(
            launch.get("ok")
            and report["steps"]["activate"].get("ok")
            and obs.get("screenshot")
            and matches
            and value_verified
        )
        if not report["ok"]:
            report["error"] = "Notepad control-layer selftest did not verify the expected editor value"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if hwnd and user32.IsWindow(hwnd):
            try:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                close_deadline = time.time() + 3.0
                while time.time() <= close_deadline and user32.IsWindow(hwnd):
                    time.sleep(0.1)
            except Exception:
                pass
        try:
            if os.path.exists(path):
                os.remove(path)
                report.setdefault("cleanup", {})["file_removed"] = True
        except Exception as e:
            report.setdefault("cleanup", {})["file_remove_error"] = str(e)


def selftest_win32(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise native HWND enumeration, WM_SETTEXT/GETTEXT, and BM_CLICK."""
    token = f"native-win32-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_win32_probe", "token": token, "steps": {}}
    parent = 0
    try:
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "WinAutoNativeProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            360,
            180,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for probe parent"
            return report

        edit = int(user32.CreateWindowExW(
            0,
            "Edit",
            "seed",
            WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
            20,
            20,
            240,
            24,
            parent,
            ctypes.c_void_p(101),
            None,
            None,
        ) or 0)
        button = int(user32.CreateWindowExW(
            0,
            "Button",
            "toggle",
            WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
            20,
            60,
            140,
            24,
            parent,
            ctypes.c_void_p(102),
            None,
            None,
        ) or 0)

        report["hwnd"] = {"parent": parent, "edit": edit, "button": button}
        if not (edit and button and user32.IsWindow(edit) and user32.IsWindow(button)):
            report["ok"] = False
            report["error"] = "Failed to create native child controls"
            return report

        children = child_windows(parent, include_invisible=True, include_text=True, max_count=20)
        report["steps"]["child_windows"] = {
            "ok": children.get("count", 0) >= 2,
            "count": children.get("count", 0),
            "classes": [c.get("class_name") for c in children.get("children", [])],
        }
        edit_find = win32_control_find(parent, control_type="edit", automation_id=101, include_invisible=True, match="exact")
        button_wait_find = win32_control_wait_find(
            parent,
            name="toggle",
            control_type="checkbox",
            include_invisible=True,
            timeout=0.5,
            interval=0.05,
        )
        missing_find = win32_control_find(
            parent,
            name="definitely-missing-native-control",
            control_type="checkbox",
            include_invisible=True,
            match="exact",
        )

        initial = win32_text(edit)
        set_result = win32_set_text(edit, token)
        after = win32_text(edit)
        edit_initial = win32_control_info(edit)
        edit_select = win32_control_action(edit, "select_range", index=7, value=12)
        edit_selected = win32_control_info(edit)
        expected_replaced = token[:7] + "EDIT" + token[12:]
        edit_replace = win32_control_action(edit, "replace_selection", text="EDIT")
        edit_after_replace = win32_control_info(edit)
        edit_append = win32_control_action(edit, "append", text=" tail")
        edit_after_append = win32_control_info(edit)
        edit_clear = win32_control_action(edit, "clear")
        edit_after_clear = win32_control_info(edit)
        edit_set_value_empty = win32_control_action(edit, "set-value", text="")
        edit_after_set_value_empty = win32_control_info(edit)
        edit_alias_seed = win32_set_text(edit, "alias-seed")
        edit_select_all = win32_control_action(edit, "select-all")
        edit_after_select_all = win32_control_info(edit)
        edit_delete_selection = win32_control_action(edit, "delete-selection")
        edit_after_delete_selection = win32_control_info(edit)
        edit_input_empty_seed = win32_set_text(edit, "input-seed")
        edit_input_empty_select = win32_control_action(edit, "select-all")
        edit_input_empty = win32_control_action(edit, "input-text", text="")
        edit_after_input_empty = win32_control_info(edit)
        click_result = win32_click(button)
        ok_check, checked = _send_message_timeout(button, BM_GETCHECK, timeout_ms=int(timeout * 1000))

        report["steps"]["initial_text"] = initial
        report["steps"]["edit_find"] = edit_find
        report["steps"]["button_wait_find"] = button_wait_find
        report["steps"]["missing_find_diagnostics"] = missing_find
        report["steps"]["set_text"] = set_result
        report["steps"]["readback_text"] = after
        report["steps"]["edit_info"] = edit_initial
        report["steps"]["edit_select"] = edit_select
        report["steps"]["edit_selected"] = edit_selected
        report["steps"]["edit_replace"] = edit_replace
        report["steps"]["edit_after_replace"] = edit_after_replace
        report["steps"]["edit_append"] = edit_append
        report["steps"]["edit_after_append"] = edit_after_append
        report["steps"]["edit_clear"] = edit_clear
        report["steps"]["edit_after_clear"] = edit_after_clear
        report["steps"]["edit_set_value_empty"] = edit_set_value_empty
        report["steps"]["edit_after_set_value_empty"] = edit_after_set_value_empty
        report["steps"]["edit_alias_seed"] = edit_alias_seed
        report["steps"]["edit_select_all"] = edit_select_all
        report["steps"]["edit_after_select_all"] = edit_after_select_all
        report["steps"]["edit_delete_selection"] = edit_delete_selection
        report["steps"]["edit_after_delete_selection"] = edit_after_delete_selection
        report["steps"]["edit_input_empty_seed"] = edit_input_empty_seed
        report["steps"]["edit_input_empty_select"] = edit_input_empty_select
        report["steps"]["edit_input_empty"] = edit_input_empty
        report["steps"]["edit_after_input_empty"] = edit_after_input_empty
        report["steps"]["click_button"] = click_result
        report["steps"]["button_check"] = {"ok": ok_check, "state": checked}

        report["ok"] = bool(
            children.get("count", 0) >= 2
            and initial.get("text", {}).get("text") == "seed"
            and edit_find.get("ok")
            and (edit_find.get("matches") or [{}])[0].get("hwnd") == edit
            and button_wait_find.get("matched")
            and (button_wait_find.get("matches") or [{}])[0].get("hwnd") == button
            and not missing_find.get("ok")
            and bool(missing_find.get("near_matches"))
            and bool(((missing_find.get("failure_summary") or {}).get("miss_counts") or {}).get("name"))
            and bool((missing_find.get("failure_summary") or {}).get("selector_suggestions"))
            and set_result.get("ok")
            and after.get("text", {}).get("text") == token
            and edit_initial.get("kind") == "edit"
            and (edit_initial.get("text") or {}).get("text") == token
            and edit_select.get("ok")
            and edit_selected.get("selected_text") == "win32"
            and edit_selected.get("selection") == {"start": 7, "end": 12}
            and edit_replace.get("ok")
            and (edit_after_replace.get("text") or {}).get("text") == expected_replaced
            and edit_append.get("ok")
            and (edit_after_append.get("text") or {}).get("text") == expected_replaced + " tail"
            and edit_clear.get("ok")
            and (edit_after_clear.get("text") or {}).get("text") == ""
            and edit_set_value_empty.get("ok")
            and edit_set_value_empty.get("text") == ""
            and (edit_after_set_value_empty.get("text") or {}).get("text") == ""
            and edit_alias_seed.get("ok")
            and edit_select_all.get("ok")
            and edit_after_select_all.get("selected_text") == "alias-seed"
            and edit_delete_selection.get("ok")
            and edit_delete_selection.get("text") == ""
            and (edit_after_delete_selection.get("text") or {}).get("text") == ""
            and edit_input_empty_seed.get("ok")
            and edit_input_empty_select.get("ok")
            and edit_input_empty.get("ok")
            and edit_input_empty.get("text") == ""
            and (edit_after_input_empty.get("text") or {}).get("text") == ""
            and click_result.get("ok")
            and checked == BST_CHECKED
        )
        if not report["ok"]:
            report["error"] = "Native Win32 probe did not verify all control operations"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_msaa(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise MSAA value read/write and default action on native controls."""
    token = f"msaa-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_msaa_probe", "token": token, "steps": {}}
    parent = 0
    try:
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "MSAAProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            360,
            180,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for MSAA probe parent"
            return report

        edit = int(user32.CreateWindowExW(
            0,
            "Edit",
            "seed",
            WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
            20,
            20,
            240,
            24,
            parent,
            ctypes.c_void_p(101),
            None,
            None,
        ) or 0)
        button = int(user32.CreateWindowExW(
            0,
            "Button",
            "toggle",
            WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
            20,
            60,
            140,
            24,
            parent,
            ctypes.c_void_p(102),
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "edit": edit, "button": button}
        if not (edit and button and user32.IsWindow(edit) and user32.IsWindow(button)):
            report["ok"] = False
            report["error"] = "Failed to create native MSAA probe controls"
            return report

        edit_msaa = msaa_window(edit, max_children=10)
        button_msaa = msaa_window(button, max_children=10)
        set_value = msaa_action(edit, action="set_value", value=token)
        after_edit = msaa_window(edit, max_children=10)
        button_action = msaa_action(button, action="default")
        ok_check, checked = _send_message_timeout(button, BM_GETCHECK, timeout_ms=int(timeout * 1000))

        report["steps"]["edit_msaa"] = edit_msaa
        report["steps"]["button_msaa"] = button_msaa
        report["steps"]["set_value"] = set_value
        report["steps"]["after_edit"] = after_edit
        report["steps"]["button_default_action"] = button_action
        report["steps"]["button_check"] = {"ok": ok_check, "state": checked}

        report["ok"] = bool(
            "error" not in edit_msaa
            and (edit_msaa.get("root") or {}).get("role_text")
            and (edit_msaa.get("root") or {}).get("value") == "seed"
            and set_value.get("ok")
            and (after_edit.get("root") or {}).get("value") == token
            and "error" not in button_msaa
            and (button_msaa.get("root") or {}).get("default_action")
            and button_action.get("ok")
            and ok_check
        )
        if not report["ok"]:
            report["error"] = "MSAA probe did not verify value/action operations"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_menu(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise classic HMENU enumeration and WM_COMMAND invocation."""
    token = f"menu-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_menu_probe", "token": token, "steps": {}}
    parent = 0
    menu = 0
    received: List[int] = []
    old_proc_value = 0
    wndproc_ref = None
    cmd_run = 41001
    cmd_stop = 41002
    try:
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "MenuProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            360,
            180,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for menu probe parent"
            return report

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

        @WNDPROC
        def probe_proc(hwnd, msg, wparam, lparam):
            if int(msg) == WM_COMMAND:
                received.append(int(wparam) & 0xFFFF)
                return 0
            if old_proc_value:
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc_value), hwnd, msg, wparam, lparam)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_ref = probe_proc
        old_proc_raw = user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.cast(wndproc_ref, ctypes.c_void_p))
        old_proc_value = int(old_proc_raw or 0)

        menu = int(user32.CreateMenu() or 0)
        file_popup = int(user32.CreatePopupMenu() or 0)
        tools_popup = int(user32.CreatePopupMenu() or 0)
        if not (menu and file_popup and tools_popup):
            report["ok"] = False
            report["error"] = "CreateMenu/CreatePopupMenu failed"
            return report
        user32.AppendMenuW(file_popup, MF_STRING, cmd_run, "&Run Probe")
        user32.AppendMenuW(file_popup, MF_STRING, cmd_stop, "S&top Probe")
        user32.AppendMenuW(tools_popup, MF_STRING, 41003, "&Nested")
        user32.AppendMenuW(menu, MF_POPUP, file_popup, "&File")
        user32.AppendMenuW(menu, MF_POPUP, tools_popup, "&Tools")
        if not user32.SetMenu(parent, menu):
            report["ok"] = False
            report["error"] = "SetMenu failed"
            return report
        user32.DrawMenuBar(parent)

        tree = menu_tree(parent, max_depth=5, max_items=50)
        action_path = menu_action(parent, path=["File", "Run Probe"], timeout_ms=int(timeout * 1000))
        action_id = menu_action(parent, command_id=cmd_stop, timeout_ms=int(timeout * 1000))

        report["hwnd"] = {"parent": parent, "menu": menu}
        report["steps"]["menu_tree"] = tree
        report["steps"]["action_by_path"] = action_path
        report["steps"]["action_by_id"] = action_id
        report["steps"]["received_commands"] = list(received)
        flat = _flatten_menu_items((tree.get("menu") or {}).get("items") or [])
        found_paths = [item.get("path") for item in flat if item.get("command_id") in (cmd_run, cmd_stop)]
        report["ok"] = bool(
            "error" not in tree
            and (tree.get("menu") or {}).get("present")
            and ["File", "Run Probe"] in found_paths
            and ["File", "Stop Probe"] in found_paths
            and action_path.get("ok")
            and action_id.get("ok")
            and cmd_run in received
            and cmd_stop in received
        )
        if not report["ok"]:
            report["error"] = "HMENU probe did not verify tree enumeration and WM_COMMAND delivery"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        try:
            if parent and old_proc_value and user32.IsWindow(parent):
                user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.c_void_p(old_proc_value))
        except Exception as e:
            report.setdefault("cleanup", {})["restore_proc_error"] = str(e)
        try:
            if parent and menu and user32.IsWindow(parent):
                user32.SetMenu(parent, None)
                user32.DrawMenuBar(parent)
                user32.DestroyMenu(menu)
        except Exception as e:
            report.setdefault("cleanup", {})["destroy_menu_error"] = str(e)
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_controls(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise native ComboBox/ListBox/Button state and selection messages."""
    token = f"controls-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_controls_probe", "token": token, "steps": {}}
    parent = 0
    notifications: List[Dict[str, Any]] = []
    old_proc_value = 0
    wndproc_ref = None
    previous_no_reenter = os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER")
    try:
        os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = "1"
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "ControlsProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            420,
            240,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for controls probe parent"
            return report

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

        @WNDPROC
        def probe_proc(hwnd, msg, wparam, lparam):
            if int(msg) == WM_COMMAND:
                notifications.append({
                    "control_id": int(wparam) & 0xFFFF,
                    "notification": (int(wparam) >> 16) & 0xFFFF,
                    "hwnd": int(lparam),
                })
                return 0
            if old_proc_value:
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc_value), hwnd, msg, wparam, lparam)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_ref = probe_proc
        old_proc_raw = user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.cast(wndproc_ref, ctypes.c_void_p))
        old_proc_value = int(old_proc_raw or 0)

        combo = int(user32.CreateWindowExW(
            0,
            "ComboBox",
            "",
            WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | CBS_HASSTRINGS,
            20,
            20,
            180,
            120,
            parent,
            ctypes.c_void_p(201),
            None,
            None,
        ) or 0)
        listbox = int(user32.CreateWindowExW(
            0,
            "ListBox",
            "",
            WS_CHILD | WS_VISIBLE | LBS_NOTIFY | WS_VSCROLL,
            20,
            70,
            180,
            80,
            parent,
            ctypes.c_void_p(202),
            None,
            None,
        ) or 0)
        checkbox = int(user32.CreateWindowExW(
            0,
            "Button",
            "agree",
            WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
            220,
            20,
            120,
            24,
            parent,
            ctypes.c_void_p(203),
            None,
            None,
        ) or 0)
        comboex = int(user32.CreateWindowExW(
            0,
            "ComboBoxEx32",
            "",
            WS_CHILD | WS_VISIBLE | CBS_DROPDOWN,
            220,
            60,
            180,
            120,
            parent,
            ctypes.c_void_p(204),
            None,
            None,
        ) or 0)
        editable_combo = int(user32.CreateWindowExW(
            0,
            "ComboBox",
            "",
            WS_CHILD | WS_VISIBLE | CBS_DROPDOWN | CBS_HASSTRINGS,
            20,
            160,
            180,
            120,
            parent,
            ctypes.c_void_p(205),
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "combo": combo, "listbox": listbox, "checkbox": checkbox}
        report["hwnd"]["comboex"] = comboex
        report["hwnd"]["editable_combo"] = editable_combo
        if not (combo and listbox and checkbox and comboex and editable_combo):
            report["ok"] = False
            report["error"] = "Failed to create native controls probe children"
            return report

        for i, item in enumerate(("Alpha", "Beta", "Gamma")):
            buf = ctypes.create_unicode_buffer(item)
            _send_message_timeout(combo, CB_ADDSTRING, 0, ctypes.addressof(buf), timeout_ms=int(timeout * 1000))
            _send_message_timeout(editable_combo, CB_ADDSTRING, 0, ctypes.addressof(buf), timeout_ms=int(timeout * 1000))
            _send_message_timeout(listbox, LB_ADDSTRING, 0, ctypes.addressof(buf), timeout_ms=int(timeout * 1000))
            report["steps"][f"comboex_insert_{i}"] = _comboboxex_insert_item(comboex, i, item, timeout_ms=int(timeout * 1000))

        combo_initial = win32_control_info(combo)
        combo_select = win32_control_action(combo, "select", text="Gamma", match="exact")
        combo_after = win32_control_info(combo)
        comboex_initial = win32_control_info(comboex)
        comboex_select = win32_control_action(comboex, "select", text="Beta", match="exact")
        comboex_rename = win32_control_action(comboex, "set_item_text", index=1, text="Beta Prime")
        comboex_edit = win32_control_action(comboex, "set_edit_text", text="typed value")
        comboex_after = win32_control_info(comboex)
        comboex_set_value = win32_control_action(comboex, "set-value", text="alias value")
        comboex_after_set_value = win32_control_info(comboex)
        editable_combo_initial = win32_control_info(editable_combo)
        editable_combo_set_value = win32_control_action(editable_combo, "set-value", text="free typed")
        editable_combo_after_set_value = win32_control_info(editable_combo)
        editable_combo_select_all = win32_control_action(editable_combo, "select-all")
        editable_combo_after_select_all = win32_control_info(editable_combo)
        editable_combo_delete_selection = win32_control_action(editable_combo, "delete-selection")
        editable_combo_after_delete = win32_control_info(editable_combo)
        editable_combo_append = win32_control_action(editable_combo, "append", text="tail")
        editable_combo_after_append = win32_control_info(editable_combo)
        list_initial = win32_control_info(listbox)
        list_select = win32_control_action(listbox, "select", index=1)
        list_activate = win32_control_action(listbox, "activate", text="Gamma", match="exact")
        list_after = win32_control_info(listbox)
        checkbox_initial = win32_control_info(checkbox)
        checkbox_check = win32_control_action(checkbox, "check")
        checkbox_after = win32_control_info(checkbox)

        report["steps"]["combo_initial"] = combo_initial
        report["steps"]["combo_select"] = combo_select
        report["steps"]["combo_after"] = combo_after
        report["steps"]["comboex_initial"] = comboex_initial
        report["steps"]["comboex_select"] = comboex_select
        report["steps"]["comboex_rename"] = comboex_rename
        report["steps"]["comboex_edit"] = comboex_edit
        report["steps"]["comboex_after"] = comboex_after
        report["steps"]["comboex_set_value"] = comboex_set_value
        report["steps"]["comboex_after_set_value"] = comboex_after_set_value
        report["steps"]["editable_combo_initial"] = editable_combo_initial
        report["steps"]["editable_combo_set_value"] = editable_combo_set_value
        report["steps"]["editable_combo_after_set_value"] = editable_combo_after_set_value
        report["steps"]["editable_combo_select_all"] = editable_combo_select_all
        report["steps"]["editable_combo_after_select_all"] = editable_combo_after_select_all
        report["steps"]["editable_combo_delete_selection"] = editable_combo_delete_selection
        report["steps"]["editable_combo_after_delete"] = editable_combo_after_delete
        report["steps"]["editable_combo_append"] = editable_combo_append
        report["steps"]["editable_combo_after_append"] = editable_combo_after_append
        report["steps"]["list_initial"] = list_initial
        report["steps"]["list_select"] = list_select
        report["steps"]["list_activate"] = list_activate
        report["steps"]["list_after"] = list_after
        report["steps"]["checkbox_initial"] = checkbox_initial
        report["steps"]["checkbox_check"] = checkbox_check
        report["steps"]["checkbox_after"] = checkbox_after
        report["steps"]["notifications"] = list(notifications)
        report["ok"] = bool(
            combo_initial.get("count") == 3
            and combo_select.get("ok")
            and combo_after.get("selected_index") == 2
            and comboex_initial.get("kind") == "comboboxex"
            and comboex_initial.get("count") == 3
            and [item.get("text") for item in comboex_initial.get("items", [])[:3]] == ["Alpha", "Beta", "Gamma"]
            and comboex_select.get("ok")
            and comboex_rename.get("ok")
            and comboex_edit.get("ok")
            and comboex_after.get("selected_index") == 1
            and [item.get("text") for item in comboex_after.get("items", [])[:3]] == ["Alpha", "Beta Prime", "Gamma"]
            and ((comboex_after.get("edit_window") or {}).get("text") or {}).get("text") == "typed value"
            and comboex_set_value.get("ok")
            and [item.get("text") for item in comboex_after_set_value.get("items", [])[:3]] == ["Alpha", "Beta Prime", "Gamma"]
            and ((comboex_after_set_value.get("edit_window") or {}).get("text") or {}).get("text") == "alias value"
            and editable_combo_initial.get("kind") == "combobox"
            and editable_combo_initial.get("editable") is True
            and editable_combo_initial.get("edit_hwnd")
            and editable_combo_set_value.get("ok")
            and editable_combo_after_set_value.get("current_text") == "free typed"
            and editable_combo_select_all.get("ok")
            and ((editable_combo_after_select_all.get("edit") or {}).get("selected_text")) == "free typed"
            and editable_combo_delete_selection.get("ok")
            and editable_combo_after_delete.get("current_text") == ""
            and editable_combo_append.get("ok")
            and editable_combo_after_append.get("current_text") == "tail"
            and list_initial.get("count") == 3
            and list_select.get("ok")
            and list_activate.get("ok")
            and (list_activate.get("activation") or {}).get("rect")
            and (list_activate.get("activation") or {}).get("double_click_notified_parent")
            and list_after.get("selected_index") == 2
            and any(note.get("control_id") == 202 and note.get("notification") == LBN_SELCHANGE and note.get("hwnd") == listbox for note in notifications)
            and any(note.get("control_id") == 202 and note.get("notification") == LBN_DBLCLK and note.get("hwnd") == listbox for note in notifications)
            and checkbox_initial.get("checked") is False
            and checkbox_check.get("ok")
            and checkbox_after.get("checked") is True
        )
        if not report["ok"]:
            report["error"] = "Native controls probe did not verify ComboBox/ComboBoxEx/ListBox/Button state operations"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if previous_no_reenter is None:
            os.environ.pop("WIN_AUTOMATION_HELPER_NO_REENTER", None)
        else:
            os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = previous_no_reenter
        try:
            if parent and old_proc_value and user32.IsWindow(parent):
                user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.c_void_p(old_proc_value))
        except Exception as e:
            report.setdefault("cleanup", {})["restore_proc_error"] = str(e)
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def _listview_insert_column(hwnd: int, index: int, text: str, width: int = 180, timeout_ms: int = 500) -> Dict[str, Any]:
    text_buf = ctypes.create_unicode_buffer(text)
    column = LVCOLUMNW()
    column.mask = LVCF_TEXT | LVCF_WIDTH | LVCF_FMT
    column.fmt = LVCFMT_LEFT
    column.cx = int(width)
    column.pszText = ctypes.addressof(text_buf)
    ok, result = _send_message_timeout(hwnd, LVM_INSERTCOLUMNW, int(index), ctypes.addressof(column), timeout_ms=timeout_ms)
    return {"ok": bool(ok and result != MESSAGE_RESULT_ERROR), "result": result}


def _comboboxex_insert_item(hwnd: int, index: int, text: str, image: int = -1, selected_image: int = -1, timeout_ms: int = 500) -> Dict[str, Any]:
    text_buf = ctypes.create_unicode_buffer(str(text))
    item = COMBOBOXEXITEMW()
    item.mask = CBEIF_TEXT
    item.iItem = int(index)
    item.pszText = ctypes.addressof(text_buf)
    item.cchTextMax = len(str(text)) + 1
    if image >= 0:
        item.mask |= CBEIF_IMAGE
        item.iImage = int(image)
    if selected_image >= 0:
        item.mask |= CBEIF_SELECTEDIMAGE
        item.iSelectedImage = int(selected_image)
    ok, result = _send_message_timeout(hwnd, CBEM_INSERTITEMW, 0, ctypes.addressof(item), timeout_ms=timeout_ms)
    return {"ok": bool(ok and result != MESSAGE_RESULT_ERROR), "result": result}


def _header_insert_item(hwnd: int, index: int, text: str, width: int = 120, timeout_ms: int = 500) -> Dict[str, Any]:
    text_buf = ctypes.create_unicode_buffer(text)
    item = HDITEMW()
    item.mask = HDI_TEXT | HDI_WIDTH | HDI_FORMAT
    item.cxy = int(width)
    item.pszText = ctypes.addressof(text_buf)
    item.cchTextMax = len(text) + 1
    item.fmt = HDF_LEFT | HDF_STRING
    ok, result = _send_message_timeout(hwnd, HDM_INSERTITEMW, int(index), ctypes.addressof(item), timeout_ms=timeout_ms)
    return {"ok": bool(ok and result != MESSAGE_RESULT_ERROR), "result": result}


def _listview_insert_item(hwnd: int, index: int, text: str, timeout_ms: int = 500) -> Dict[str, Any]:
    text_buf = ctypes.create_unicode_buffer(text)
    item = LVITEMW()
    item.mask = LVIF_TEXT
    item.iItem = int(index)
    item.iSubItem = 0
    item.pszText = ctypes.addressof(text_buf)
    ok, result = _send_message_timeout(hwnd, LVM_INSERTITEMW, 0, ctypes.addressof(item), timeout_ms=timeout_ms)
    return {"ok": bool(ok and result != MESSAGE_RESULT_ERROR), "result": result}


def _listview_insert_row(hwnd: int, index: int, values: List[str], timeout_ms: int = 500) -> Dict[str, Any]:
    if not values:
        values = [""]
    result = _listview_insert_item(hwnd, index, values[0], timeout_ms=timeout_ms)
    if not result.get("ok"):
        return result
    inserted_index = int(result.get("result", index))
    subitems = []
    for subitem, value in enumerate(values[1:], start=1):
        ok, msg_result = _listview_set_item_text(hwnd, inserted_index, subitem, value, timeout_ms=timeout_ms)
        subitems.append({"column": subitem, "ok": bool(ok), "result": msg_result})
    result["index"] = inserted_index
    result["subitems"] = subitems
    result["ok"] = bool(result.get("ok") and all(item.get("ok") for item in subitems))
    return result


def _treeview_insert_item(hwnd: int, parent: Optional[int], text: str, timeout_ms: int = 500) -> int:
    text_buf = ctypes.create_unicode_buffer(text)
    insert = TVINSERTSTRUCTW()
    insert.hParent = ctypes.c_void_p(int(parent or TVI_ROOT))
    insert.hInsertAfter = ctypes.c_void_p(int(TVI_LAST))
    insert.item.mask = TVIF_TEXT
    insert.item.pszText = ctypes.addressof(text_buf)
    insert.item.cchTextMax = len(text) + 1
    ok, hitem = _send_message_timeout(hwnd, TVM_INSERTITEMW, 0, ctypes.addressof(insert), timeout_ms=timeout_ms)
    return int(hitem) if ok else 0


def _tab_insert_item(hwnd: int, index: int, text: str, timeout_ms: int = 500) -> Dict[str, Any]:
    text_buf = ctypes.create_unicode_buffer(text)
    item = TCITEMW()
    item.mask = TCIF_TEXT
    item.pszText = ctypes.addressof(text_buf)
    item.cchTextMax = len(text) + 1
    ok, result = _send_message_timeout(hwnd, TCM_INSERTITEMW, int(index), ctypes.addressof(item), timeout_ms=timeout_ms)
    return {"ok": bool(ok and result != MESSAGE_RESULT_ERROR), "result": result}


def _toolbar_add_button(hwnd: int, command_id: int, text: str, timeout_ms: int = 500) -> Dict[str, Any]:
    text_buf = ctypes.create_unicode_buffer(text + "\0")
    ok_text, string_index = _send_message_timeout(hwnd, TB_ADDSTRINGW, 0, ctypes.addressof(text_buf), timeout_ms=timeout_ms)
    button = TBBUTTON()
    button.iBitmap = -1
    button.idCommand = int(command_id)
    button.fsState = TBSTATE_ENABLED
    button.fsStyle = TBSTYLE_BUTTON
    button.iString = int(string_index if ok_text and string_index != MESSAGE_RESULT_ERROR else 0)
    _send_message_timeout(hwnd, TB_BUTTONSTRUCTSIZE, ctypes.sizeof(TBBUTTON), 0, timeout_ms=timeout_ms)
    ok, result = _send_message_timeout(hwnd, TB_ADDBUTTONSW, 1, ctypes.addressof(button), timeout_ms=timeout_ms)
    return {"ok": bool(ok and result), "result": result, "string_index": int(button.iString)}


def _statusbar_set_parts(hwnd: int, right_edges: List[int], timeout_ms: int = 500) -> Dict[str, Any]:
    count = len(right_edges)
    array_type = ctypes.c_int * max(count, 1)
    edges = array_type(*[int(edge) for edge in right_edges])
    ok, result = _send_message_timeout(hwnd, SB_SETPARTS, count, ctypes.addressof(edges), timeout_ms=timeout_ms)
    return {"ok": bool(ok and result), "result": result}


def selftest_common_controls(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise SysListView32 and SysTreeView32 info/action support."""
    token = f"common-controls-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_common_controls_probe", "token": token, "steps": {}}
    parent = 0
    previous_no_reenter = os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER")
    try:
        os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = "1"
        init_ok = _init_common_controls()
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "CommonControlsProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            520,
            320,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for common controls probe parent"
            return report

        listview = int(user32.CreateWindowExW(
            0,
            "SysListView32",
            "",
            WS_CHILD | WS_VISIBLE | LVS_REPORT,
            20,
            20,
            220,
            140,
            parent,
            ctypes.c_void_p(301),
            None,
            None,
        ) or 0)
        treeview = int(user32.CreateWindowExW(
            0,
            "SysTreeView32",
            "",
            WS_CHILD | WS_VISIBLE | TVS_HASBUTTONS | TVS_HASLINES | TVS_LINESATROOT | TVS_CHECKBOXES,
            260,
            20,
            220,
            180,
            parent,
            ctypes.c_void_p(302),
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "listview": listview, "treeview": treeview}
        report["steps"]["init_common_controls"] = {"ok": init_ok}
        if not (listview and treeview):
            report["ok"] = False
            report["error"] = "Failed to create SysListView32/SysTreeView32 controls"
            return report

        ok_ex_style, ex_style_result = _send_message_timeout(
            listview,
            LVM_SETEXTENDEDLISTVIEWSTYLE,
            LVS_EX_CHECKBOXES,
            LVS_EX_CHECKBOXES,
            timeout_ms=int(timeout * 1000),
        )
        report["steps"]["listview_checkboxes"] = {"ok": bool(ok_ex_style), "result": ex_style_result}
        report["steps"]["listview_column_name"] = _listview_insert_column(listview, 0, "Name", width=120, timeout_ms=int(timeout * 1000))
        report["steps"]["listview_column_state"] = _listview_insert_column(listview, 1, "State", width=90, timeout_ms=int(timeout * 1000))
        report["steps"]["listview_column_size"] = _listview_insert_column(listview, 2, "Size", width=80, timeout_ms=int(timeout * 1000))
        rows = (("Alpha", "Ready", "10 KB"), ("Beta", "Idle", "20 KB"), ("Gamma", "Busy", "30 KB"))
        for i, values in enumerate(rows):
            report["steps"][f"listview_insert_{i}"] = _listview_insert_row(listview, i, list(values), timeout_ms=int(timeout * 1000))
        root = _treeview_insert_item(treeview, None, "Root", timeout_ms=int(timeout * 1000))
        child_a = _treeview_insert_item(treeview, root, "Child A", timeout_ms=int(timeout * 1000))
        child_b = _treeview_insert_item(treeview, root, "Child B", timeout_ms=int(timeout * 1000))
        _send_message_timeout(treeview, TVM_EXPAND, TVE_EXPAND, root, timeout_ms=int(timeout * 1000))
        report["steps"]["tree_handles"] = {"root": root, "child_a": child_a, "child_b": child_b}

        list_initial = win32_control_info(listview)
        list_find = win32_control_find(parent, name="Gamma", control_type="listview", include_invisible=True, match="exact")
        list_select = win32_control_action(listview, "select", text="Beta", match="exact")
        list_activate = win32_control_action(listview, "activate", text="Beta", match="exact")
        list_check = win32_control_action(listview, "check", text="Gamma", match="exact")
        list_set_cell = win32_control_action(listview, "set_cell", index=1, value=1, text="Active")
        list_width = win32_control_action(listview, "set_column_width", index=2, value=144)
        list_check_wait = win32_control_wait(listview, state="checked", expected=True, text="Gamma", match="exact", timeout=0.5, interval=0.05)
        list_checked_find = win32_control_wait_find(
            parent,
            control_type="listview",
            state="has_checkboxes",
            expected=True,
            include_invisible=True,
            timeout=0.5,
            interval=0.05,
        )
        list_after = win32_control_info(listview)
        tree_initial = win32_control_info(treeview)
        tree_find = win32_control_find(parent, name="Child A", control_type="treeview", include_invisible=True, match="exact")
        tree_check = win32_control_action(treeview, "check", text="Child A", match="exact")
        tree_select = win32_control_action(treeview, "select", text="Child B", match="exact")
        tree_activate = win32_control_action(treeview, "activate", text="Child B", match="exact")
        tree_check_wait = win32_control_wait(treeview, state="checked", expected=True, text="Child A", match="exact", timeout=0.5, interval=0.05)
        tree_after = win32_control_info(treeview)

        report["steps"]["list_initial"] = list_initial
        report["steps"]["list_find"] = list_find
        report["steps"]["list_select"] = list_select
        report["steps"]["list_activate"] = list_activate
        report["steps"]["list_check"] = list_check
        report["steps"]["list_check_wait"] = list_check_wait
        report["steps"]["list_checked_find"] = list_checked_find
        report["steps"]["list_set_cell"] = list_set_cell
        report["steps"]["list_width"] = list_width
        report["steps"]["list_after"] = list_after
        report["steps"]["tree_initial"] = tree_initial
        report["steps"]["tree_find"] = tree_find
        report["steps"]["tree_check"] = tree_check
        report["steps"]["tree_check_wait"] = tree_check_wait
        report["steps"]["tree_select"] = tree_select
        report["steps"]["tree_activate"] = tree_activate
        report["steps"]["tree_after"] = tree_after
        report["ok"] = bool(
            list_initial.get("kind") == "listview"
            and list_initial.get("count") == 3
            and list_initial.get("has_checkboxes") is True
            and [column.get("text") for column in list_initial.get("columns", [])[:3]] == ["Name", "State", "Size"]
            and [item.get("text") for item in list_initial.get("items", [])[:3]] == ["Alpha", "Beta", "Gamma"]
            and (list_initial.get("items", [])[1].get("values") or [])[1] == "Idle"
            and list_find.get("ok")
            and (list_find.get("matches") or [{}])[0].get("hwnd") == listview
            and list_select.get("ok")
            and list_activate.get("ok")
            and (list_activate.get("activation") or {}).get("rect")
            and any(
                message.get("name") == "WM_LBUTTONDBLCLK"
                for message in (((list_activate.get("activation") or {}).get("click") or {}).get("messages") or [])
            )
            and list_check.get("ok")
            and list_check_wait.get("matched")
            and list_checked_find.get("matched")
            and (list_checked_find.get("matches") or [{}])[0].get("hwnd") == listview
            and list_set_cell.get("ok")
            and list_width.get("ok")
            and list_after.get("selected_index") == 1
            and (list_after.get("items", [])[1].get("values") or [])[1] == "Active"
            and (list_after.get("columns", [])[2].get("width") or 0) == 144
            and (list_after.get("items", [])[2].get("checked") is True)
            and (list_after.get("items", [])[2].get("check_state") == "checked")
            and tree_initial.get("kind") == "treeview"
            and tree_initial.get("has_checkboxes") is True
            and tree_initial.get("count", 0) >= 3
            and any(node.get("text") == "Child B" for node in tree_initial.get("flat", []))
            and tree_find.get("ok")
            and (tree_find.get("matches") or [{}])[0].get("hwnd") == treeview
            and tree_check.get("ok")
            and tree_check_wait.get("matched")
            and tree_select.get("ok")
            and tree_activate.get("ok")
            and (tree_activate.get("activation") or {}).get("rect")
            and any(
                message.get("name") == "WM_LBUTTONDBLCLK"
                for message in (((tree_activate.get("activation") or {}).get("click") or {}).get("messages") or [])
            )
            and (tree_after.get("selected_index") or -1) >= 0
            and any(
                node.get("text") == "Child A"
                and node.get("checked") is True
                and node.get("check_state") == "checked"
                for node in tree_after.get("flat", [])
            )
        )
        if not report["ok"]:
            report["error"] = "Common controls probe did not verify SysListView32/SysTreeView32 operations and checkbox state"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if previous_no_reenter is None:
            os.environ.pop("WIN_AUTOMATION_HELPER_NO_REENTER", None)
        else:
            os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = previous_no_reenter
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_header_controls(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise SysHeader32 item read/write/order and click notification support."""
    token = f"header-controls-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_header_controls_probe", "token": token, "steps": {}}
    parent = 0
    notifications: List[Dict[str, Any]] = []
    old_proc_value = 0
    wndproc_ref = None
    try:
        init_ok = _init_common_controls()
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "HeaderControlsProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            460,
            180,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for header controls probe parent"
            return report

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

        @WNDPROC
        def probe_proc(hwnd, msg, wparam, lparam):
            if int(msg) == WM_NOTIFY and int(lparam):
                try:
                    header = NMHEADERW.from_address(int(lparam))
                    notifications.append({
                        "id": int(header.hdr.idFrom),
                        "code": int(header.hdr.code),
                        "item": int(header.iItem),
                        "button": int(header.iButton),
                    })
                except Exception:
                    pass
                return 0
            if old_proc_value:
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc_value), hwnd, msg, wparam, lparam)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_ref = probe_proc
        old_proc_raw = user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.cast(wndproc_ref, ctypes.c_void_p))
        old_proc_value = int(old_proc_raw or 0)

        header = int(user32.CreateWindowExW(
            0,
            "SysHeader32",
            "",
            WS_CHILD | WS_VISIBLE | HDS_BUTTONS,
            20,
            20,
            360,
            32,
            parent,
            ctypes.c_void_p(801),
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "header": header}
        report["steps"]["init_common_controls"] = {"ok": init_ok}
        if not header:
            report["ok"] = False
            report["error"] = "Failed to create SysHeader32 control"
            return report

        report["steps"]["insert_name"] = _header_insert_item(header, 0, "Name", width=120, timeout_ms=int(timeout * 1000))
        report["steps"]["insert_state"] = _header_insert_item(header, 1, "State", width=90, timeout_ms=int(timeout * 1000))
        report["steps"]["insert_size"] = _header_insert_item(header, 2, "Size", width=80, timeout_ms=int(timeout * 1000))

        initial = win32_control_info(header)
        set_text = win32_control_action(header, "set_text", index=1, text="Status")
        set_width = win32_control_action(header, "set_width", index=2, value=144)
        set_order = win32_control_action(header, "set_order", text="[2,0,1]")
        click = win32_control_action(header, "click", index=2)
        after = win32_control_info(header)

        report["steps"]["initial"] = initial
        report["steps"]["set_text"] = set_text
        report["steps"]["set_width"] = set_width
        report["steps"]["set_order"] = set_order
        report["steps"]["click"] = click
        report["steps"]["after"] = after
        report["steps"]["notifications"] = notifications
        report["ok"] = bool(
            initial.get("kind") == "header"
            and initial.get("count") == 3
            and [item.get("text") for item in initial.get("items", [])[:3]] == ["Name", "State", "Size"]
            and set_text.get("ok")
            and set_width.get("ok")
            and set_order.get("ok")
            and click.get("ok")
            and after.get("order") == [2, 0, 1]
            and (after.get("items", [])[1].get("text") if len(after.get("items", [])) > 1 else None) == "Status"
            and (after.get("items", [])[2].get("width") if len(after.get("items", [])) > 2 else None) == 144
            and any(note.get("item") == 2 for note in notifications)
        )
        if not report["ok"]:
            report["error"] = "Native header probe did not verify SysHeader32 read/write/order/click operations"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        try:
            if parent and old_proc_value and user32.IsWindow(parent):
                user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.c_void_p(old_proc_value))
        except Exception as e:
            report.setdefault("cleanup", {})["restore_proc_error"] = str(e)
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_bars(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise SysTabControl32 and ToolbarWindow32 info/action support."""
    token = f"bars-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_bars_probe", "token": token, "steps": {}}
    parent = 0
    tooltip = 0
    received: List[int] = []
    notifications: List[Dict[str, Any]] = []
    tooltip_text_buffers: List[Any] = []
    old_proc_value = 0
    wndproc_ref = None
    cmd_open = 42001
    cmd_save = 42002
    cmd_export = 42003
    previous_no_reenter = os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER")
    try:
        os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = "1"
        init_ok = _init_common_controls()
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "BarsProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            520,
            260,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for bars probe parent"
            return report

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

        @WNDPROC
        def probe_proc(hwnd, msg, wparam, lparam):
            if int(msg) == WM_COMMAND:
                received.append(int(wparam) & 0xFFFF)
                return 0
            if int(msg) == WM_NOTIFY and int(lparam):
                try:
                    header = NMHDR.from_address(int(lparam))
                    notifications.append({
                        "hwnd": int(header.hwndFrom or 0),
                        "id": int(header.idFrom),
                        "code": int(header.code),
                        "wparam": int(wparam),
                    })
                except Exception:
                    pass
                return 0
            if old_proc_value:
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc_value), hwnd, msg, wparam, lparam)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_ref = probe_proc
        old_proc_raw = user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.cast(wndproc_ref, ctypes.c_void_p))
        old_proc_value = int(old_proc_raw or 0)

        tab = int(user32.CreateWindowExW(
            0,
            "SysTabControl32",
            "",
            WS_CHILD | WS_VISIBLE,
            20,
            20,
            240,
            90,
            parent,
            ctypes.c_void_p(401),
            None,
            None,
        ) or 0)
        toolbar = int(user32.CreateWindowExW(
            0,
            "ToolbarWindow32",
            "",
            WS_CHILD | WS_VISIBLE,
            20,
            130,
            300,
            36,
            parent,
            ctypes.c_void_p(402),
            None,
            None,
        ) or 0)
        tooltip = int(user32.CreateWindowExW(
            WS_EX_TOPMOST,
            "tooltips_class32",
            "",
            WS_POPUP | TTS_ALWAYSTIP | TTS_NOPREFIX,
            0,
            0,
            0,
            0,
            parent,
            None,
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "tab": tab, "toolbar": toolbar, "tooltip": tooltip}
        report["steps"]["init_common_controls"] = {"ok": init_ok}
        if not (tab and toolbar and tooltip):
            report["ok"] = False
            report["error"] = "Failed to create SysTabControl32/ToolbarWindow32/tooltips_class32 controls"
            return report

        report["steps"]["tab_insert_0"] = _tab_insert_item(tab, 0, "General", timeout_ms=int(timeout * 1000))
        report["steps"]["tab_insert_1"] = _tab_insert_item(tab, 1, "Advanced", timeout_ms=int(timeout * 1000))
        report["steps"]["toolbar_open"] = _toolbar_add_button(toolbar, cmd_open, "Open", timeout_ms=int(timeout * 1000))
        report["steps"]["toolbar_save"] = _toolbar_add_button(toolbar, cmd_save, "Save", timeout_ms=int(timeout * 1000))
        report["steps"]["toolbar_export"] = _toolbar_add_button(toolbar, cmd_export, "", timeout_ms=int(timeout * 1000))
        report["steps"]["toolbar_set_tooltips"] = {
            "ok": _send_message_timeout(toolbar, TB_SETTOOLTIPS, tooltip, 0, timeout_ms=int(timeout * 1000))[0],
            "tooltip_hwnd": tooltip,
        }

        def _add_tooltip_tool(tool_id: int, text_value: str, rect: Dict[str, int]) -> Dict[str, Any]:
            text_buf = ctypes.create_unicode_buffer(str(text_value))
            tooltip_text_buffers.append(text_buf)
            item = TOOLINFOW()
            item.cbSize = ctypes.sizeof(TOOLINFOW)
            item.uFlags = TTF_SUBCLASS
            item.hwnd = int(toolbar)
            item.uId = int(tool_id)
            item.rect.left = int(rect.get("left", 0))
            item.rect.top = int(rect.get("top", 0))
            item.rect.right = int(rect.get("right", max(item.rect.left + 1, 1)))
            item.rect.bottom = int(rect.get("bottom", max(item.rect.top + 1, 1)))
            item.lpszText = ctypes.addressof(text_buf)
            ok, msg_result = _send_message_timeout(tooltip, TTM_ADDTOOLW, 0, ctypes.addressof(item), timeout_ms=int(timeout * 1000))
            return {"ok": bool(ok and msg_result), "tool_id": int(tool_id), "text": text_value, "rect": rect, "result": msg_result}

        report["steps"]["tooltip_open"] = _add_tooltip_tool(cmd_open, "Open file", _toolbar_button_rect(toolbar, 0, timeout_ms=int(timeout * 1000)))
        report["steps"]["tooltip_save"] = _add_tooltip_tool(cmd_save, "Save document", _toolbar_button_rect(toolbar, 1, timeout_ms=int(timeout * 1000)))
        report["steps"]["tooltip_export"] = _add_tooltip_tool(cmd_export, "Export Report", _toolbar_button_rect(toolbar, 2, timeout_ms=int(timeout * 1000)))

        tab_initial = win32_control_info(tab)
        tab_select = win32_control_action(tab, "select", text="Advanced", match="exact")
        tab_after = win32_control_info(tab)
        tooltip_initial = win32_control_info(tooltip)
        toolbar_initial = win32_control_info(toolbar)
        toolbar_press = win32_control_action(toolbar, "press", text="Save", match="exact")
        toolbar_tooltip_press = win32_control_action(toolbar, "press", text="Export Report", match="exact")
        toolbar_after = win32_control_info(toolbar)

        report["steps"]["tab_initial"] = tab_initial
        report["steps"]["tab_select"] = tab_select
        report["steps"]["tab_after"] = tab_after
        report["steps"]["tooltip_initial"] = tooltip_initial
        report["steps"]["toolbar_initial"] = toolbar_initial
        report["steps"]["toolbar_press"] = toolbar_press
        report["steps"]["toolbar_tooltip_press"] = toolbar_tooltip_press
        report["steps"]["toolbar_after"] = toolbar_after
        report["steps"]["received_commands"] = list(received)
        report["steps"]["received_notifications"] = list(notifications)
        report["ok"] = bool(
            tab_initial.get("kind") == "tab"
            and [item.get("text") for item in tab_initial.get("items", [])[:2]] == ["General", "Advanced"]
            and tab_select.get("ok")
            and tab_select.get("notified_parent")
            and (tab_select.get("notification_changing") or {}).get("notification") == TCN_SELCHANGING
            and (tab_select.get("notification_changed") or {}).get("notification") == TCN_SELCHANGE
            and tab_after.get("selected_index") == 1
            and any(note.get("hwnd") == tab and note.get("id") == 401 and note.get("code") == TCN_SELCHANGING for note in notifications)
            and any(note.get("hwnd") == tab and note.get("id") == 401 and note.get("code") == TCN_SELCHANGE for note in notifications)
            and tooltip_initial.get("kind") == "tooltip"
            and any(tool.get("text") == "Export Report" for tool in tooltip_initial.get("tools", []))
            and toolbar_initial.get("kind") == "toolbar"
            and any(button.get("text") == "Save" for button in toolbar_initial.get("buttons", []))
            and any(button.get("tooltip_text") == "Export Report" and button.get("label") == "Export Report" for button in toolbar_initial.get("buttons", []))
            and toolbar_press.get("ok")
            and toolbar_tooltip_press.get("ok")
            and cmd_save in received
            and cmd_export in received
        )
        if not report["ok"]:
            report["error"] = "Bars probe did not verify SysTabControl32/ToolbarWindow32/ToolTip operations"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if previous_no_reenter is None:
            os.environ.pop("WIN_AUTOMATION_HELPER_NO_REENTER", None)
        else:
            os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = previous_no_reenter
        try:
            if parent and old_proc_value and user32.IsWindow(parent):
                user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.c_void_p(old_proc_value))
        except Exception as e:
            report.setdefault("cleanup", {})["restore_proc_error"] = str(e)
        if tooltip and user32.IsWindow(tooltip):
            try:
                user32.DestroyWindow(tooltip)
                report.setdefault("cleanup", {})["destroyed_tooltip"] = not bool(user32.IsWindow(tooltip))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_tooltip_error"] = str(e)
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_numeric_controls(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise statusbar, trackbar, updown, progress, and scrollbar controls."""
    token = f"numeric-controls-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_numeric_controls_probe", "token": token, "steps": {}}
    parent = 0
    old_proc_value = 0
    wndproc_ref = None
    scroll_events: List[Dict[str, Any]] = []
    try:
        init_ok = _init_common_controls()
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "NumericControlsProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            560,
            300,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for numeric controls probe parent"
            return report

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

        @WNDPROC
        def probe_proc(hwnd, msg, wparam, lparam):
            if int(msg) in (WM_HSCROLL, WM_VSCROLL):
                scroll_events.append({
                    "message": "WM_VSCROLL" if int(msg) == WM_VSCROLL else "WM_HSCROLL",
                    "code": int(wparam) & 0xFFFF,
                    "position": (int(wparam) >> 16) & 0xFFFF,
                    "hwnd": int(lparam),
                })
                return 0
            if old_proc_value:
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc_value), hwnd, msg, wparam, lparam)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_ref = probe_proc
        old_proc_raw = user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.cast(wndproc_ref, ctypes.c_void_p))
        old_proc_value = int(old_proc_raw or 0)

        status = int(user32.CreateWindowExW(0, "msctls_statusbar32", "", WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, parent, ctypes.c_void_p(501), None, None) or 0)
        trackbar = int(user32.CreateWindowExW(0, "msctls_trackbar32", "", WS_CHILD | WS_VISIBLE, 20, 35, 240, 40, parent, ctypes.c_void_p(502), None, None) or 0)
        updown = int(user32.CreateWindowExW(0, "msctls_updown32", "", WS_CHILD | WS_VISIBLE | UDS_SETBUDDYINT, 300, 35, 28, 80, parent, ctypes.c_void_p(503), None, None) or 0)
        progress = int(user32.CreateWindowExW(0, "msctls_progress32", "", WS_CHILD | WS_VISIBLE, 20, 105, 280, 24, parent, ctypes.c_void_p(504), None, None) or 0)
        scrollbar = int(user32.CreateWindowExW(0, "ScrollBar", "", WS_CHILD | WS_VISIBLE | SBS_VERT, 330, 105, 28, 130, parent, ctypes.c_void_p(505), None, None) or 0)
        report["hwnd"] = {"parent": parent, "statusbar": status, "trackbar": trackbar, "updown": updown, "progress": progress, "scrollbar": scrollbar}
        report["steps"]["init_common_controls"] = {"ok": init_ok}
        if not (status and trackbar and updown and progress and scrollbar):
            report["ok"] = False
            report["error"] = "Failed to create statusbar/trackbar/updown/progress/scrollbar controls"
            return report

        report["steps"]["status_parts"] = _statusbar_set_parts(status, [180, -1], timeout_ms=int(timeout * 1000))
        report["steps"]["status_left"] = {"ok": _set_statusbar_part_text(status, 0, "Ready", timeout_ms=int(timeout * 1000))[0]}
        report["steps"]["status_right"] = {"ok": _set_statusbar_part_text(status, 1, "Idle", timeout_ms=int(timeout * 1000))[0]}
        _send_message_timeout(trackbar, TBM_SETRANGE, 1, (100 << 16) | 0, timeout_ms=int(timeout * 1000))
        _send_message_timeout(trackbar, TBM_SETPOS, 1, 25, timeout_ms=int(timeout * 1000))
        _send_message_timeout(updown, UDM_SETRANGE32, 0, 50, timeout_ms=int(timeout * 1000))
        _send_message_timeout(updown, UDM_SETPOS32, 0, 10, timeout_ms=int(timeout * 1000))
        _send_message_timeout(progress, PBM_SETRANGE32, 0, 100, timeout_ms=int(timeout * 1000))
        _send_message_timeout(progress, PBM_SETPOS, 40, 0, timeout_ms=int(timeout * 1000))
        si = SCROLLINFO()
        si.cbSize = ctypes.sizeof(SCROLLINFO)
        si.fMask = SIF_RANGE | SIF_PAGE | SIF_POS
        si.nMin = 0
        si.nMax = 100
        si.nPage = 10
        si.nPos = 15
        user32.SetScrollInfo(scrollbar, SB_CTL, ctypes.byref(si), True)

        status_initial = win32_control_info(status)
        status_set = win32_control_action(status, "set_text", index=1, text="Busy")
        status_after = win32_control_info(status)
        track_initial = win32_control_info(trackbar)
        track_set = win32_control_action(trackbar, "set", value=70)
        track_after = win32_control_info(trackbar)
        updown_initial = win32_control_info(updown)
        updown_set = win32_control_action(updown, "set", value=33)
        updown_after = win32_control_info(updown)
        progress_initial = win32_control_info(progress)
        progress_set = win32_control_action(progress, "set", value=80)
        progress_after = win32_control_info(progress)
        scrollbar_initial = win32_control_info(scrollbar)
        scrollbar_set = win32_control_action(scrollbar, "set", value=55)
        scrollbar_page = win32_control_action(scrollbar, "page_down")
        scrollbar_after = win32_control_info(scrollbar)

        report["steps"]["status_initial"] = status_initial
        report["steps"]["status_set"] = status_set
        report["steps"]["status_after"] = status_after
        report["steps"]["track_initial"] = track_initial
        report["steps"]["track_set"] = track_set
        report["steps"]["track_after"] = track_after
        report["steps"]["updown_initial"] = updown_initial
        report["steps"]["updown_set"] = updown_set
        report["steps"]["updown_after"] = updown_after
        report["steps"]["progress_initial"] = progress_initial
        report["steps"]["progress_set"] = progress_set
        report["steps"]["progress_after"] = progress_after
        report["steps"]["scrollbar_initial"] = scrollbar_initial
        report["steps"]["scrollbar_set"] = scrollbar_set
        report["steps"]["scrollbar_page"] = scrollbar_page
        report["steps"]["scrollbar_after"] = scrollbar_after
        report["steps"]["scroll_events"] = list(scroll_events)
        report["ok"] = bool(
            status_initial.get("kind") == "statusbar"
            and [part.get("text") for part in status_initial.get("parts", [])[:2]] == ["Ready", "Idle"]
            and status_set.get("ok")
            and [part.get("text") for part in status_after.get("parts", [])[:2]] == ["Ready", "Busy"]
            and track_initial.get("kind") == "trackbar"
            and track_set.get("ok")
            and track_after.get("position") == 70
            and updown_initial.get("kind") == "updown"
            and updown_set.get("ok")
            and updown_after.get("position") == 33
            and progress_initial.get("kind") == "progress"
            and progress_set.get("ok")
            and progress_after.get("position") == 80
            and scrollbar_initial.get("kind") == "scrollbar"
            and scrollbar_initial.get("orientation") == "vertical"
            and scrollbar_initial.get("position") == 15
            and scrollbar_set.get("ok")
            and scrollbar_page.get("ok")
            and scrollbar_after.get("position") == 65
            and any(event.get("hwnd") == scrollbar for event in scroll_events)
        )
        if not report["ok"]:
            report["error"] = "Numeric controls probe did not verify statusbar/trackbar/updown/progress/scrollbar operations"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        try:
            if parent and old_proc_value and user32.IsWindow(parent):
                user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.c_void_p(old_proc_value))
        except Exception as e:
            report.setdefault("cleanup", {})["restore_proc_error"] = str(e)
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_date_ip_controls(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise DateTimePicker, MonthCal, and IPAddress common controls."""
    token = f"date-ip-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_date_ip_probe", "token": token, "steps": {}}
    parent = 0
    try:
        init_ok = _init_common_controls()
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "DateIpProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            560,
            340,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for date/ip probe parent"
            return report

        datetime_hwnd = int(user32.CreateWindowExW(0, "SysDateTimePick32", "", WS_CHILD | WS_VISIBLE, 20, 20, 180, 28, parent, ctypes.c_void_p(601), None, None) or 0)
        monthcal = int(user32.CreateWindowExW(0, "SysMonthCal32", "", WS_CHILD | WS_VISIBLE, 20, 60, 230, 170, parent, ctypes.c_void_p(602), None, None) or 0)
        ipaddress = int(user32.CreateWindowExW(0, "SysIPAddress32", "", WS_CHILD | WS_VISIBLE, 280, 20, 180, 28, parent, ctypes.c_void_p(603), None, None) or 0)
        report["hwnd"] = {"parent": parent, "datetime": datetime_hwnd, "monthcal": monthcal, "ipaddress": ipaddress}
        report["steps"]["init_common_controls"] = {"ok": init_ok}
        if not (datetime_hwnd and monthcal and ipaddress):
            report["ok"] = False
            report["error"] = "Failed to create DateTimePicker/MonthCal/IPAddress controls"
            return report

        datetime_set = win32_control_action(datetime_hwnd, "set", text="2026-06-07T09:30:15")
        month_set = win32_control_action(monthcal, "set", text="2026-12-25")
        ip_set = win32_control_action(ipaddress, "set", text="192.168.1.77")
        datetime_after = win32_control_info(datetime_hwnd)
        month_after = win32_control_info(monthcal)
        ip_after = win32_control_info(ipaddress)
        ip_clear = win32_control_action(ipaddress, "clear")
        ip_cleared = win32_control_info(ipaddress)

        report["steps"]["datetime_set"] = datetime_set
        report["steps"]["datetime_after"] = datetime_after
        report["steps"]["month_set"] = month_set
        report["steps"]["month_after"] = month_after
        report["steps"]["ip_set"] = ip_set
        report["steps"]["ip_after"] = ip_after
        report["steps"]["ip_clear"] = ip_clear
        report["steps"]["ip_cleared"] = ip_cleared
        report["ok"] = bool(
            datetime_set.get("ok")
            and datetime_after.get("kind") == "datetime"
            and datetime_after.get("iso") == "2026-06-07"
            and datetime_after.get("hour") == 9
            and datetime_after.get("minute") == 30
            and month_set.get("ok")
            and month_after.get("kind") == "monthcal"
            and month_after.get("iso") == "2026-12-25"
            and ip_set.get("ok")
            and ip_after.get("kind") == "ipaddress"
            and ip_after.get("address") == "192.168.1.77"
            and ip_clear.get("ok")
            and ip_cleared.get("blank") is True
        )
        if not report["ok"]:
            report["error"] = "Date/IP probe did not verify DateTimePicker/MonthCal/IPAddress operations"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_richedit_controls(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise RichEdit text, selection, replacement, append, and clear actions."""
    token = f"richedit-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_richedit_probe", "token": token, "steps": {}}
    parent = 0
    try:
        load_ok = _ensure_richedit_loaded()
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "RichEditProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            560,
            260,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for RichEdit probe parent"
            return report

        richedit = int(user32.CreateWindowExW(
            0,
            "RICHEDIT50W",
            "alpha beta",
            WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_HSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_AUTOHSCROLL,
            20,
            20,
            480,
            140,
            parent,
            ctypes.c_void_p(701),
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "richedit": richedit}
        report["steps"]["load_richedit"] = {"ok": load_ok}
        if not richedit:
            report["ok"] = False
            report["error"] = "Failed to create RichEdit control"
            return report

        initial = win32_control_info(richedit)
        select_beta = win32_control_action(richedit, "select_range", index=6, value=10)
        selected = win32_control_info(richedit)
        replace = win32_control_action(richedit, "replace_selection", text="BETA")
        append = win32_control_action(richedit, "append", text="\r\nsecond line")
        after_append = win32_control_info(richedit)
        clear = win32_control_action(richedit, "clear")
        after_clear = win32_control_info(richedit)

        report["steps"]["initial"] = initial
        report["steps"]["select_beta"] = select_beta
        report["steps"]["selected"] = selected
        report["steps"]["replace"] = replace
        report["steps"]["append"] = append
        report["steps"]["after_append"] = after_append
        report["steps"]["clear"] = clear
        report["steps"]["after_clear"] = after_clear
        appended_text = ((after_append.get("text") or {}).get("text") or "")
        cleared_text = ((after_clear.get("text") or {}).get("text") or "")
        report["ok"] = bool(
            initial.get("kind") == "richedit"
            and ((initial.get("text") or {}).get("text") == "alpha beta")
            and select_beta.get("ok")
            and (selected.get("selection") or {}).get("start") == 6
            and (selected.get("selection") or {}).get("end") == 10
            and selected.get("selected_text") == "beta"
            and replace.get("ok")
            and append.get("ok")
            and "alpha BETA" in appended_text
            and "second line" in appended_text
            and (after_append.get("line_count") or 0) >= 2
            and clear.get("ok")
            and cleared_text == ""
        )
        if not report["ok"]:
            report["error"] = "RichEdit probe did not verify text/selection/replacement actions"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_light_controls(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise Static, SysLink, and HotKey lightweight native controls."""
    token = f"light-controls-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "native_light_controls_probe", "token": token, "steps": {}}
    parent = 0
    received: List[int] = []
    old_proc_value = 0
    wndproc_ref = None
    try:
        init_ok = _init_common_controls()
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            "LightControlsProbe",
            WS_OVERLAPPEDWINDOW,
            80,
            80,
            560,
            240,
            None,
            None,
            None,
            None,
        ) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for light controls probe parent"
            return report

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

        @WNDPROC
        def probe_proc(hwnd, msg, wparam, lparam):
            if int(msg) == WM_COMMAND:
                received.append(int(wparam) & 0xFFFF)
                return 0
            if old_proc_value:
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc_value), hwnd, msg, wparam, lparam)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_ref = probe_proc
        old_proc_raw = user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.cast(wndproc_ref, ctypes.c_void_p))
        old_proc_value = int(old_proc_raw or 0)

        static = int(user32.CreateWindowExW(0, "Static", "Status: idle", WS_CHILD | WS_VISIBLE | SS_NOTIFY, 20, 20, 220, 24, parent, ctypes.c_void_p(901), None, None) or 0)
        hotkey = int(user32.CreateWindowExW(0, "msctls_hotkey32", "", WS_CHILD | WS_VISIBLE, 20, 60, 180, 24, parent, ctypes.c_void_p(902), None, None) or 0)
        syslink = int(user32.CreateWindowExW(0, "SysLink", 'Visit <a id="home" href="https://example.com">Home</a>', WS_CHILD | WS_VISIBLE, 20, 100, 360, 32, parent, ctypes.c_void_p(903), None, None) or 0)
        report["hwnd"] = {"parent": parent, "static": static, "hotkey": hotkey, "syslink": syslink}
        report["steps"]["init_common_controls"] = {"ok": init_ok}
        if not (static and hotkey and syslink):
            report["ok"] = False
            report["error"] = "Failed to create Static/HotKey/SysLink controls"
            return report

        static_initial = win32_control_info(static)
        static_set = win32_control_action(static, "set_text", text="Status: ready")
        static_click = win32_control_action(static, "click")
        static_after = win32_control_info(static)
        hotkey_initial = win32_control_info(hotkey)
        hotkey_set = win32_control_action(hotkey, "set", text="ctrl+shift+S")
        hotkey_after = win32_control_info(hotkey)
        hotkey_clear = win32_control_action(hotkey, "clear")
        hotkey_cleared = win32_control_info(hotkey)
        syslink_initial = win32_control_info(syslink)
        syslink_visited = win32_control_action(syslink, "set_visited", index=0, checked=True)
        syslink_set = win32_control_action(syslink, "set_text", text='Open <a id="docs" href="https://example.com/docs">Docs</a>')
        syslink_after = win32_control_info(syslink)

        report["steps"]["static_initial"] = static_initial
        report["steps"]["static_set"] = static_set
        report["steps"]["static_click"] = static_click
        report["steps"]["static_after"] = static_after
        report["steps"]["hotkey_initial"] = hotkey_initial
        report["steps"]["hotkey_set"] = hotkey_set
        report["steps"]["hotkey_after"] = hotkey_after
        report["steps"]["hotkey_clear"] = hotkey_clear
        report["steps"]["hotkey_cleared"] = hotkey_cleared
        report["steps"]["syslink_initial"] = syslink_initial
        report["steps"]["syslink_visited"] = syslink_visited
        report["steps"]["syslink_set"] = syslink_set
        report["steps"]["syslink_after"] = syslink_after
        report["steps"]["received_commands"] = list(received)
        report["ok"] = bool(
            static_initial.get("kind") == "static"
            and ((static_initial.get("text") or {}).get("text") == "Status: idle")
            and static_set.get("ok")
            and ((static_after.get("text") or {}).get("text") == "Status: ready")
            and static_click.get("ok")
            and 901 in received
            and hotkey_initial.get("kind") == "hotkey"
            and hotkey_set.get("ok")
            and hotkey_after.get("vk") == ord("S")
            and {"ctrl", "shift"}.issubset(set(hotkey_after.get("modifiers") or []))
            and hotkey_clear.get("ok")
            and hotkey_cleared.get("word") == 0
            and syslink_initial.get("kind") == "syslink"
            and syslink_initial.get("count") == 1
            and (syslink_initial.get("links", [])[0].get("text") if syslink_initial.get("links") else None) == "Home"
            and syslink_visited.get("ok")
            and syslink_set.get("ok")
            and (syslink_after.get("links", [])[0].get("text") if syslink_after.get("links") else None) == "Docs"
        )
        if not report["ok"]:
            report["error"] = "Light controls probe did not verify Static/HotKey/SysLink operations"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        try:
            if parent and old_proc_value and user32.IsWindow(parent):
                user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.c_void_p(old_proc_value))
        except Exception as e:
            report.setdefault("cleanup", {})["restore_proc_error"] = str(e)
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_uia_patterns(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise UIA RangeValue and Scroll patterns against native controls."""
    token = f"uia-patterns-selftest {int(time.time())}"
    report: Dict[str, Any] = {"app": "uia_patterns_probe", "token": token, "steps": {}}
    parent = 0
    old_proc_value = 0
    wndproc_ref = None
    legacy_commands: List[int] = []
    try:
        _init_common_controls()
        parent = int(user32.CreateWindowExW(0, "Static", "UIAProbe", WS_OVERLAPPEDWINDOW, 80, 80, 520, 360, None, None, None, None) or 0)
        if not parent:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for UIA probe parent"
            return report
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
        def _probe_wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_COMMAND:
                legacy_commands.append(int(wparam) & 0xFFFF)
            if old_proc_value:
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc_value), hwnd, msg, wparam, lparam)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_ref = WNDPROC(_probe_wndproc)
        old_proc_raw = user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.cast(wndproc_ref, ctypes.c_void_p))
        old_proc_value = int(old_proc_raw or 0)
        track = int(user32.CreateWindowExW(0, "msctls_trackbar32", "", WS_CHILD | WS_VISIBLE, 20, 20, 240, 40, parent, ctypes.c_void_p(301), None, None) or 0)
        listview = int(user32.CreateWindowExW(0, "SysListView32", "", WS_CHILD | WS_VISIBLE | WS_VSCROLL | LVS_REPORT, 20, 80, 300, 180, parent, ctypes.c_void_p(302), None, None) or 0)
        legacy_button = int(user32.CreateWindowExW(0, "Button", "LegacyAction", WS_CHILD | WS_VISIBLE, 340, 24, 130, 30, parent, ctypes.c_void_p(303), None, None) or 0)
        report["hwnd"] = {"parent": parent, "trackbar": track, "listview": listview, "legacy_button": legacy_button}
        if not (track and listview and legacy_button):
            report["ok"] = False
            report["error"] = "Failed to create UIA RangeValue/Scroll/Legacy probe controls"
            return report

        _send_message_timeout(track, TBM_SETRANGE, 1, (100 << 16) | 0, timeout_ms=int(timeout * 1000))
        _listview_insert_column(listview, 0, "Name", timeout_ms=int(timeout * 1000))
        for i in range(48):
            _listview_insert_row(listview, i, [f"Item {i}"], timeout_ms=int(timeout * 1000))
        user32.ShowWindow(parent, SW_SHOWNORMAL)
        user32.UpdateWindow(parent)
        time.sleep(0.2)

        initial = build_accessibility_tree(parent, max_depth=5, max_elements=160)
        range_match = find_elements(parent, pattern="RangeValue", control_type="slider", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not range_match.get("matches"):
            range_match = find_elements(parent, pattern="RangeValue", class_name="msctls_trackbar32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        scroll_match = find_elements(parent, pattern="Scroll", class_name="SysListView32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not scroll_match.get("matches"):
            scroll_match = find_elements(parent, pattern="Scroll", visible_only=True, limit=1, max_depth=5, max_elements=160)
        selection_match = find_elements(parent, pattern="Selection", class_name="SysListView32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not selection_match.get("matches"):
            selection_match = find_elements(parent, pattern="Selection", visible_only=True, limit=1, max_depth=5, max_elements=160)
        selection_item_match = find_elements(parent, pattern="SelectionItem", control_type="list item", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not selection_item_match.get("matches"):
            selection_item_match = find_elements(parent, pattern="SelectionItem", visible_only=True, limit=1, max_depth=5, max_elements=160)
        transform_match = find_elements(parent, pattern="Transform", class_name="Static", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not transform_match.get("matches"):
            transform_match = find_elements(parent, pattern="Transform", visible_only=True, limit=1, max_depth=5, max_elements=160)
        legacy_match = find_elements(parent, pattern="LegacyIAccessible", name="LegacyAction", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not legacy_match.get("matches"):
            legacy_match = find_elements(parent, pattern="LegacyIAccessible", class_name="Button", visible_only=True, limit=1, max_depth=5, max_elements=160)
        report["steps"]["initial"] = {
            "element_count": len(initial.get("elements", [])),
            "range_match": range_match,
            "scroll_match": scroll_match,
            "selection_match": selection_match,
            "selection_item_match": selection_item_match,
            "transform_match": transform_match,
            "legacy_match": legacy_match,
        }
        if not range_match.get("matches") or not scroll_match.get("matches") or not selection_match.get("matches") or not selection_item_match.get("matches") or not transform_match.get("matches") or not legacy_match.get("matches"):
            report["ok"] = False
            report["error"] = "UIA probe did not expose RangeValue, Scroll, Selection, SelectionItem, Transform, and LegacyIAccessible patterns"
            return report

        legacy_index = int(legacy_match["matches"][0]["index"])
        legacy_default = perform_action(parent, legacy_index, "legacy-default")
        _pump_wait(lambda: 303 in legacy_commands, timeout=1.5)
        report["steps"]["legacy_default"] = legacy_default
        report["steps"]["legacy_commands"] = list(legacy_commands)

        transform_index = int(transform_match["matches"][0]["index"])
        transform_before = transform_match["matches"][0]
        transform_move = perform_action(parent, transform_index, "move", value=96, horizontal=96)
        time.sleep(0.1)
        transform_after_move = find_elements(parent, pattern="Transform", class_name="Static", visible_only=True, limit=1, max_depth=5, max_elements=160)
        transform_index = int(transform_after_move["matches"][0]["index"])
        transform_resize = perform_action(parent, transform_index, "resize", value=560, horizontal=380)
        time.sleep(0.1)
        transform_after_resize = find_elements(parent, pattern="Transform", class_name="Static", visible_only=True, limit=1, max_depth=5, max_elements=160)
        report["steps"]["transform_before"] = transform_before
        report["steps"]["transform_move"] = transform_move
        report["steps"]["transform_after_move"] = transform_after_move
        report["steps"]["transform_resize"] = transform_resize
        report["steps"]["transform_after_resize"] = transform_after_resize

        selection_item_index = int(selection_item_match["matches"][0]["index"])
        select_item = perform_action(parent, selection_item_index, "select")
        selection_after_select = find_elements(parent, pattern="Selection", class_name="SysListView32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        selected_item_after_select = find_elements(parent, pattern="SelectionItem", name="Item 0", visible_only=True, limit=1, max_depth=5, max_elements=160)

        after_select_range_match = find_elements(parent, pattern="RangeValue", class_name="msctls_trackbar32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not after_select_range_match.get("matches"):
            after_select_range_match = find_elements(parent, pattern="RangeValue", visible_only=True, limit=1, max_depth=5, max_elements=160)
        range_index = int(after_select_range_match["matches"][0]["index"])
        set_range = perform_action(parent, range_index, "set-range", value=42)
        after_range = find_elements(parent, pattern="RangeValue", class_name="msctls_trackbar32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not after_range.get("matches"):
            after_range = find_elements(parent, pattern="RangeValue", visible_only=True, limit=1, max_depth=5, max_elements=160)
        scroll_match_after_range = find_elements(parent, pattern="Scroll", class_name="SysListView32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not scroll_match_after_range.get("matches"):
            scroll_match_after_range = find_elements(parent, pattern="Scroll", visible_only=True, limit=1, max_depth=5, max_elements=160)
        scroll_index = int(scroll_match_after_range["matches"][0]["index"])
        set_scroll_percent = perform_action(parent, scroll_index, "set-scroll-percent", vertical=75)
        scroll_match_after_percent = find_elements(parent, pattern="Scroll", class_name="SysListView32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not scroll_match_after_percent.get("matches"):
            scroll_match_after_percent = find_elements(parent, pattern="Scroll", visible_only=True, limit=1, max_depth=5, max_elements=160)
        scroll_index = int(scroll_match_after_percent["matches"][0]["index"])
        scroll_down = perform_action(parent, scroll_index, "scroll", horizontal="no-amount", vertical="small-increment")
        after_scroll = find_elements(parent, pattern="Scroll", class_name="SysListView32", visible_only=True, limit=1, max_depth=5, max_elements=160)
        if not after_scroll.get("matches"):
            after_scroll = find_elements(parent, pattern="Scroll", visible_only=True, limit=1, max_depth=5, max_elements=160)
        report["steps"]["set_range"] = set_range
        report["steps"]["select_item"] = select_item
        report["steps"]["selection_after_select"] = selection_after_select
        report["steps"]["selected_item_after_select"] = selected_item_after_select
        report["steps"]["after_select_range_match"] = after_select_range_match
        report["steps"]["after_range"] = after_range
        report["steps"]["scroll_match_after_range"] = scroll_match_after_range
        report["steps"]["set_scroll_percent"] = set_scroll_percent
        report["steps"]["scroll_match_after_percent"] = scroll_match_after_percent
        report["steps"]["scroll_down"] = scroll_down
        report["steps"]["after_scroll"] = after_scroll

        range_value = (((after_range.get("matches") or [{}])[0].get("range_value") or {}).get("value"))
        selection_state = (((selection_after_select.get("matches") or [{}])[0].get("selection") or {}))
        selected_item_state = (((selected_item_after_select.get("matches") or [{}])[0].get("selection_item") or {}))
        scroll_info = ((after_scroll.get("matches") or [{}])[0].get("scroll") or {})
        moved_rect = ((transform_after_move.get("matches") or [{}])[0].get("rect") or {})
        resized_rect = ((transform_after_resize.get("matches") or [{}])[0].get("rect") or {})
        report["ok"] = bool(
            set_range.get("ok")
            and range_value is not None
            and abs(float(range_value) - 42.0) <= 1.0
            and legacy_default.get("ok")
            and 303 in legacy_commands
            and transform_move.get("ok")
            and transform_resize.get("ok")
            and abs(int(moved_rect.get("left", 0)) - 96) <= 8
            and int(resized_rect.get("width", 0)) >= 540
            and int(resized_rect.get("height", 0)) >= 360
            and select_item.get("ok")
            and int(selection_state.get("selected_count", 0)) >= 1
            and selected_item_state.get("is_selected") is True
            and set_scroll_percent.get("ok")
            and scroll_down.get("ok")
            and scroll_info.get("vertically_scrollable") is True
            and float(scroll_info.get("vertical_percent", 0.0)) >= 0.0
        )
        if not report["ok"]:
            report["error"] = "UIA RangeValue/Scroll/Selection/Legacy/Transform probe did not verify expected state changes"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        try:
            if parent and old_proc_value and user32.IsWindow(parent):
                user32.SetWindowLongPtrW(parent, GWL_WNDPROC, ctypes.c_void_p(old_proc_value))
        except Exception as e:
            report.setdefault("cleanup", {})["restore_proc_error"] = str(e)
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_text_pattern(timeout: float = 15.0) -> Dict[str, Any]:
    """Exercise UIA TextPattern against a real Notepad document surface."""
    token = f"text-pattern-selftest {int(time.time())}"
    text_body = f"alpha beta gamma\r\nsecond line for {token}"
    temp_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(temp_dir, exist_ok=True)
    path = os.path.join(temp_dir, f"textpattern-{int(time.time() * 1000)}.txt")
    report: Dict[str, Any] = {"app": "notepad_textpattern", "file": path, "token": token, "steps": {}}
    hwnd = 0
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text_body)
        launched = launch_app(path, timeout=timeout)
        report["steps"]["launch"] = launched
        hwnd = int((launched.get("window") or {}).get("hwnd") or 0)
        if not hwnd:
            report["ok"] = False
            report["error"] = "Failed to launch Notepad text pattern probe"
            return report
        time.sleep(0.8)

        text_match = find_elements(hwnd, pattern="Text", visible_only=True, limit=5, max_depth=8, max_elements=240)
        report["steps"]["find_text"] = text_match
        matches = text_match.get("matches") or []
        target = None
        for match in matches:
            document_text = (((match.get("text") or {}).get("document") or {}).get("text") or "")
            if "alpha beta gamma" in document_text:
                target = match
                break
        if target is None and matches:
            target = matches[0]
        if not target:
            report["ok"] = False
            report["error"] = "No UIA TextPattern element found in Notepad"
            return report

        idx = int(target["index"])
        text_find = perform_action(hwnd, idx, "text-find", value="beta")
        text_select = perform_action(hwnd, idx, "text-select", value="second")
        _, refreshed = _uia_element_by_index(hwnd, idx, max_depth=8, max_elements=240)
        selection = [
            item.get("text", "")
            for item in ((((refreshed or {}).get("text") or {}).get("selection")) or [])
        ]
        document_text = (((refreshed or {}).get("text") or {}).get("document") or {}).get("text") or ""
        report["steps"]["text_find"] = text_find
        report["steps"]["text_select"] = text_select
        report["steps"]["refreshed"] = refreshed
        report["steps"]["selection"] = selection
        report["ok"] = bool(
            "alpha beta gamma" in document_text
            and text_find.get("ok")
            and (text_find.get("range") or {}).get("text") == "beta"
            and text_select.get("ok")
            and any("second" in item for item in selection)
        )
        if not report["ok"]:
            report["error"] = "UIA TextPattern probe did not verify document text, find, and selection"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if hwnd and user32.IsWindow(hwnd):
            try:
                press_key(hwnd, "Alt_L+F4")
                time.sleep(0.5)
            except Exception as e:
                report.setdefault("cleanup", {})["close_error"] = str(e)
        try:
            if os.path.exists(path):
                os.remove(path)
                report.setdefault("cleanup", {})["file_removed"] = True
        except Exception as e:
            report.setdefault("cleanup", {})["file_remove_error"] = str(e)


def selftest_winevent(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise synchronous SetWinEventHook listening with a short-lived native window."""
    token = f"WinEventProbe {int(time.time() * 1000)}"
    report: Dict[str, Any] = {"app": "native_winevent_probe", "token": token, "steps": {}}
    hwnd = 0

    def show_probe_window() -> None:
        time.sleep(0.2)
        if not hwnd or not user32.IsWindow(hwnd):
            return
        user32.ShowWindow(hwnd, SW_SHOWNORMAL)
        user32.UpdateWindow(hwnd)
        time.sleep(0.5)
        if user32.IsWindow(hwnd):
            user32.DestroyWindow(hwnd)

    try:
        hwnd = int(user32.CreateWindowExW(
            0,
            "Static",
            token,
            WS_OVERLAPPEDWINDOW,
            120,
            120,
            280,
            140,
            None,
            None,
            None,
            None,
        ) or 0)
        report["hwnd"] = hwnd
        report["steps"]["created"] = {"hwnd": hwnd, "window": _window_info(hwnd) if hwnd else None}
        if not hwnd:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed"
            return report
        thread = threading.Thread(target=show_probe_window, daemon=True)
        thread.start()
        observed = wait_event(
            "object-show",
            hwnd=hwnd,
            timeout=timeout,
            limit=1,
            include_children=True,
            skip_own_process=False,
        )
        thread.join(timeout=1.5)
        report["steps"]["wait_event"] = observed
        report["ok"] = bool(observed.get("ok") and observed.get("count", 0) >= 1)
        if not report["ok"]:
            report["error"] = "WinEvent probe did not observe object-show for the created window"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if hwnd and user32.IsWindow(hwnd):
            try:
                user32.DestroyWindow(hwnd)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(hwnd))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_uia_view_modes(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise Raw/Control/Content UIA tree views and view-aware index rescans."""
    token = f"ViewModeProbe {int(time.time() * 1000)}"
    report: Dict[str, Any] = {"app": "uia_view_modes_probe", "token": token, "steps": {}}
    parent = 0
    try:
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            token,
            WS_OVERLAPPEDWINDOW,
            120,
            120,
            380,
            190,
            None,
            None,
            None,
            None,
        ) or 0)
        button = int(user32.CreateWindowExW(
            0,
            "Button",
            "ProbeButton",
            WS_CHILD | WS_VISIBLE,
            20,
            20,
            130,
            32,
            parent,
            ctypes.c_void_p(101),
            None,
            None,
        ) or 0)
        edit = int(user32.CreateWindowExW(
            0,
            "Edit",
            "seed",
            WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
            20,
            66,
            190,
            26,
            parent,
            ctypes.c_void_p(102),
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "button": button, "edit": edit}
        if not (parent and button and edit):
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for UIA view mode probe"
            return report

        user32.ShowWindow(parent, SW_SHOWNORMAL)
        user32.UpdateWindow(parent)
        time.sleep(min(max(timeout, 0.2), 0.5))

        view_results: Dict[str, Any] = {}
        for view_name in ("raw", "control", "content"):
            found = find_elements(
                parent,
                name="ProbeButton",
                match="exact",
                limit=3,
                max_depth=4,
                max_elements=80,
                view=view_name,
            )
            matches = found.get("matches") or []
            first = matches[0] if matches else None
            index_info = None
            if first and first.get("index") is not None:
                _, index_info = _uia_element_by_index(parent, int(first["index"]))
            view_results[view_name] = {
                "returned_view": found.get("view"),
                "scanned": found.get("scanned"),
                "count": found.get("count"),
                "first": first,
                "rescan": index_info,
                "error": found.get("error"),
            }

        report["steps"]["views"] = view_results
        raw_count = int(view_results["raw"].get("scanned") or 0)
        control_count = int(view_results["control"].get("scanned") or 0)
        content_count = int(view_results["content"].get("scanned") or 0)
        report["ok"] = bool(
            all(view_results[name].get("returned_view") == name for name in ("raw", "control", "content"))
            and all(int(view_results[name].get("count") or 0) >= 1 for name in ("raw", "control", "content"))
            and all(((view_results[name].get("rescan") or {}).get("name") == "ProbeButton") for name in ("raw", "control", "content"))
            and raw_count >= control_count >= 1
            and raw_count >= content_count >= 1
        )
        if not report["ok"]:
            report["error"] = "UIA view-mode probe did not verify raw/control/content traversal and index rescan"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_window_management(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise native top-level HWND move/resize/minimize/maximize/restore/close."""
    token = f"WindowActionProbe {int(time.time() * 1000)}"
    report: Dict[str, Any] = {"app": "native_window_action_probe", "token": token, "steps": {}}
    hwnd = 0
    try:
        hwnd = int(user32.CreateWindowExW(
            0,
            "Static",
            token,
            WS_OVERLAPPEDWINDOW,
            140,
            140,
            320,
            180,
            None,
            None,
            None,
            None,
        ) or 0)
        report["hwnd"] = hwnd
        if not hwnd:
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for window action probe"
            return report

        user32.ShowWindow(hwnd, SW_SHOWNORMAL)
        user32.UpdateWindow(hwnd)
        time.sleep(min(max(timeout, 0.2), 0.5))

        activate_window(hwnd)
        gui_initial = gui_thread_info(hwnd)
        placement_initial = window_action(hwnd, "placement")
        move_result = window_action(hwnd, "set-rect", x=180, y=170, width=420, height=260)
        topmost_result = window_action(hwnd, "topmost")
        topmost_info = _window_info(hwnd)
        not_topmost_result = window_action(hwnd, "not-topmost")
        not_topmost_info = _window_info(hwnd)
        bottom_result = window_action(hwnd, "bottom")
        top_result = window_action(hwnd, "top")
        minimize_result = window_action(hwnd, "minimize")
        _pump_wait(lambda: bool(user32.IsIconic(hwnd)), timeout=1.0)
        minimized_info = _window_info(hwnd)
        restore_result = window_action(hwnd, "restore")
        _pump_wait(lambda: not bool(user32.IsIconic(hwnd)), timeout=1.0)
        restored_info = _window_info(hwnd)
        maximize_result = window_action(hwnd, "maximize")
        _pump_wait(lambda: bool(user32.IsZoomed(hwnd)), timeout=1.0)
        maximized_info = _window_info(hwnd)
        restore_after_max = window_action(hwnd, "restore")
        _pump_wait(lambda: not bool(user32.IsZoomed(hwnd)), timeout=1.0)
        close_result = window_action(hwnd, "close", timeout=1.0)

        report["steps"]["gui_thread_info"] = gui_initial
        report["steps"]["placement"] = placement_initial
        report["steps"]["set_rect"] = move_result
        report["steps"]["topmost"] = topmost_result
        report["steps"]["topmost_info"] = topmost_info
        report["steps"]["not_topmost"] = not_topmost_result
        report["steps"]["not_topmost_info"] = not_topmost_info
        report["steps"]["bottom"] = bottom_result
        report["steps"]["top"] = top_result
        report["steps"]["minimize"] = minimize_result
        report["steps"]["minimized_info"] = minimized_info
        report["steps"]["restore"] = restore_result
        report["steps"]["restored_info"] = restored_info
        report["steps"]["maximize"] = maximize_result
        report["steps"]["maximized_info"] = maximized_info
        report["steps"]["restore_after_maximize"] = restore_after_max
        report["steps"]["close"] = close_result

        moved_rect = ((move_result.get("after") or {}).get("rect") or {})
        restored = restored_info or {}
        maximized = maximized_info or {}
        report["ok"] = bool(
            move_result.get("ok")
            and gui_initial.get("ok")
            and placement_initial.get("ok")
            and (placement_initial.get("placement") or {}).get("normal_position")
            and int((gui_initial.get("handles") or {}).get("active") or 0) == hwnd
            and abs(int(moved_rect.get("left", 0)) - 180) <= 12
            and abs(int(moved_rect.get("top", 0)) - 170) <= 12
            and int(moved_rect.get("width", 0)) >= 380
            and int(moved_rect.get("height", 0)) >= 220
            and topmost_result.get("ok")
            and bool((topmost_info or {}).get("topmost"))
            and not_topmost_result.get("ok")
            and not bool((not_topmost_info or {}).get("topmost"))
            and bottom_result.get("ok")
            and top_result.get("ok")
            and minimize_result.get("ok")
            and bool((minimized_info or {}).get("minimized"))
            and restore_result.get("ok")
            and not bool(restored.get("minimized"))
            and maximize_result.get("ok")
            and bool(maximized.get("maximized"))
            and restore_after_max.get("ok")
            and close_result.get("ok")
            and (close_result.get("closed") or not user32.IsWindow(hwnd))
        )
        if not report["ok"]:
            report["error"] = "Window action probe did not verify placement/z-order/set-rect/minimize/restore/maximize/close"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if hwnd and user32.IsWindow(hwnd):
            try:
                user32.DestroyWindow(hwnd)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(hwnd))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_focus_hwnd(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise foreground repair and child-HWND focus with AttachThreadInput + SetFocus."""
    token = f"FocusProbe {int(time.time() * 1000)}"
    report: Dict[str, Any] = {"app": "native_focus_probe", "token": token, "steps": {}}
    parent = 0
    edit = 0
    button = 0
    try:
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            token,
            WS_OVERLAPPEDWINDOW,
            160,
            160,
            420,
            220,
            None,
            None,
            None,
            None,
        ) or 0)
        edit = int(user32.CreateWindowExW(
            0,
            "Edit",
            "focus-seed",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
            24,
            28,
            260,
            28,
            parent,
            ctypes.c_void_p(1101),
            None,
            None,
        ) or 0)
        button = int(user32.CreateWindowExW(
            0,
            "Button",
            "FocusableButton",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP,
            24,
            72,
            160,
            30,
            parent,
            ctypes.c_void_p(1102),
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "edit": edit, "button": button}
        if not (parent and edit and button and user32.IsWindow(parent) and user32.IsWindow(edit)):
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for native focus probe"
            return report

        user32.ShowWindow(parent, SW_SHOWNORMAL)
        user32.UpdateWindow(parent)
        time.sleep(min(max(timeout, 0.2), 0.5))

        parent_focus = focus_hwnd(parent, timeout=1.0)
        edit_focus = focus_hwnd(edit, timeout=1.0)
        edit_gui = gui_thread_info(parent)
        button_focus = focus_hwnd(button, timeout=1.0)
        button_gui = gui_thread_info(parent)
        report["steps"]["parent_focus"] = parent_focus
        report["steps"]["edit_focus"] = edit_focus
        report["steps"]["edit_gui_thread_info"] = edit_gui
        report["steps"]["button_focus"] = button_focus
        report["steps"]["button_gui_thread_info"] = button_gui
        report["ok"] = bool(
            parent_focus.get("ok")
            and edit_focus.get("ok")
            and int((edit_gui.get("handles") or {}).get("focus") or 0) == edit
            and button_focus.get("ok")
            and int((button_gui.get("handles") or {}).get("focus") or 0) == button
        )
        if not report["ok"]:
            report["error"] = "Focus probe did not verify foreground repair and child HWND focus"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_focused_input(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise focused-HWND text insertion, append, set-text, and root-window focus targeting."""
    token = f"FocusedInputProbe {int(time.time() * 1000)}"
    report: Dict[str, Any] = {"app": "native_focused_input_probe", "token": token, "steps": {}}
    parent = 0
    edit = 0
    button = 0
    try:
        parent = int(user32.CreateWindowExW(
            0,
            "Static",
            token,
            WS_OVERLAPPEDWINDOW,
            180,
            180,
            460,
            230,
            None,
            None,
            None,
            None,
        ) or 0)
        edit = int(user32.CreateWindowExW(
            0,
            "Edit",
            "alpha beta",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
            24,
            30,
            300,
            28,
            parent,
            ctypes.c_void_p(1201),
            None,
            None,
        ) or 0)
        button = int(user32.CreateWindowExW(
            0,
            "Button",
            "SideButton",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP,
            24,
            76,
            150,
            30,
            parent,
            ctypes.c_void_p(1202),
            None,
            None,
        ) or 0)
        report["hwnd"] = {"parent": parent, "edit": edit, "button": button}
        if not (parent and edit and button and user32.IsWindow(parent) and user32.IsWindow(edit)):
            report["ok"] = False
            report["error"] = "CreateWindowExW failed for focused input probe"
            return report

        user32.ShowWindow(parent, SW_SHOWNORMAL)
        user32.UpdateWindow(parent)
        time.sleep(min(max(timeout, 0.2), 0.5))

        edit_focus = focus_hwnd(edit, timeout=1.0)
        sel_ok, sel_result = _edit_set_selection(edit, 6, 10, timeout_ms=500)
        replace = focused_input(parent, "BETA", mode="auto", timeout=1.0)
        after_replace = win32_control_info(edit)
        append = focused_input(edit, " tail", mode="append", timeout=1.0)
        after_append = win32_control_info(edit)
        set_text = focused_input(edit, "final text", mode="set-text", timeout=1.0)
        after_set = win32_control_info(edit)
        wm_char_setup = win32_set_text(edit, "", timeout_ms=500)
        wm_char_focus = focus_hwnd(edit, timeout=1.0)
        wm_char = focused_input(parent, "wm", mode="wm-char", timeout=1.0)
        after_wm_char = win32_control_info(edit)

        report["steps"]["edit_focus"] = _compact_focus_result(edit_focus)
        report["steps"]["select_beta"] = {"ok": bool(sel_ok), "result": sel_result}
        report["steps"]["replace_via_root"] = replace
        report["steps"]["after_replace_text"] = (after_replace.get("text") or {}).get("text")
        report["steps"]["append_via_child"] = append
        report["steps"]["after_append_text"] = (after_append.get("text") or {}).get("text")
        report["steps"]["set_text"] = set_text
        report["steps"]["after_set_text"] = (after_set.get("text") or {}).get("text")
        report["steps"]["wm_char_setup"] = wm_char_setup
        report["steps"]["wm_char_focus"] = _compact_focus_result(wm_char_focus)
        report["steps"]["wm_char"] = wm_char
        report["steps"]["after_wm_char_text"] = (after_wm_char.get("text") or {}).get("text")

        report["ok"] = bool(
            edit_focus.get("ok")
            and sel_ok
            and replace.get("ok")
            and replace.get("focus_hwnd") == edit
            and replace.get("method") == "edit.EM_REPLACESEL"
            and (after_replace.get("text") or {}).get("text") == "alpha BETA"
            and append.get("ok")
            and (after_append.get("text") or {}).get("text") == "alpha BETA tail"
            and set_text.get("ok")
            and (after_set.get("text") or {}).get("text") == "final text"
            and wm_char.get("ok")
            and (after_wm_char.get("text") or {}).get("text") == "wm"
        )
        if not report["ok"]:
            report["error"] = "Focused input probe did not verify root-targeted focused control input"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if parent and user32.IsWindow(parent):
            try:
                user32.DestroyWindow(parent)
                report.setdefault("cleanup", {})["destroyed"] = not bool(user32.IsWindow(parent))
            except Exception as e:
                report.setdefault("cleanup", {})["destroy_error"] = str(e)


def selftest_file_dialog(timeout: float = 10.0) -> Dict[str, Any]:
    """Exercise standard Windows file dialog inspection, filename setting, and cancel."""
    temp_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(temp_dir, exist_ok=True)
    path = os.path.join(temp_dir, f"file-dialog-probe-{int(time.time() * 1000)}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("file dialog probe")
    report: Dict[str, Any] = {"app": "native_file_dialog", "file": path, "steps": {}}
    dialog_hwnd = 0
    dialog_done = threading.Event()
    dialog_result: Dict[str, Any] = {}

    def open_dialog() -> None:
        file_buf = ctypes.create_unicode_buffer(path, 4096)
        title = f"WinAuto File Dialog Probe {int(time.time() * 1000)}"
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner = None
        ofn.lpstrFilter = "Text Files\0*.txt\0All Files\0*.*\0\0"
        ofn.lpstrFile = ctypes.cast(file_buf, ctypes.c_wchar_p)
        ofn.nMaxFile = len(file_buf)
        ofn.lpstrInitialDir = temp_dir
        ofn.lpstrTitle = title
        ofn.Flags = OFN_EXPLORER | OFN_HIDEREADONLY | OFN_NOCHANGEDIR
        try:
            ok = bool(comdlg32.GetOpenFileNameW(ctypes.byref(ofn)))
            dialog_result.update({
                "ok": ok,
                "selected": file_buf.value,
                "error_code": int(comdlg32.CommDlgExtendedError()),
                "title": title,
            })
        except Exception as e:
            dialog_result.update({"ok": False, "error": str(e), "title": title})
        finally:
            dialog_done.set()

    try:
        thread = threading.Thread(target=open_dialog, daemon=True)
        thread.start()
        dialog = file_dialog_info(timeout=timeout, timeout_ms=500)
        controls = dialog.get("controls") or {}
        report["steps"]["dialog_info"] = {
            "ok": dialog.get("ok"),
            "hwnd": dialog.get("hwnd"),
            "kind": dialog.get("kind"),
            "window": dialog.get("window"),
            "controls": {
                "filename_hwnd": controls.get("filename_hwnd"),
                "confirm_hwnd": controls.get("confirm_hwnd"),
                "cancel_hwnd": controls.get("cancel_hwnd"),
                "children_count": controls.get("children_count"),
            },
        }
        if not dialog.get("ok"):
            report["ok"] = False
            report["error"] = "File dialog did not appear"
            return report
        dialog_hwnd = int(dialog.get("hwnd") or 0)

        set_result = file_dialog_action("set-filename", hwnd=dialog_hwnd, path=path, timeout=timeout, timeout_ms=500)
        set_core = set_result.get("set_filename") or {}
        report["steps"]["set_filename"] = {
            "ok": set_result.get("ok"),
            "filename_hwnd": set_core.get("filename_hwnd"),
            "control_kind": set_core.get("control_kind"),
            "method": set_core.get("method"),
            "path": set_core.get("path"),
        }
        cancel = file_dialog_action("cancel", hwnd=dialog_hwnd, timeout=timeout, timeout_ms=500, verify_close=True)
        report["steps"]["cancel"] = {
            "ok": cancel.get("ok"),
            "closed": cancel.get("closed"),
            "command": cancel.get("command"),
            "button_fallback": cancel.get("button_fallback"),
        }
        thread.join(timeout=max(float(timeout), 1.0))
        report["steps"]["dialog_thread"] = dialog_result
        report["ok"] = bool(
            dialog.get("ok")
            and controls.get("filename_hwnd")
            and controls.get("confirm_hwnd")
            and set_result.get("ok")
            and cancel.get("ok")
            and cancel.get("closed") is not False
            and dialog_done.is_set()
            and dialog_result.get("ok") is False
            and int(dialog_result.get("error_code") or 0) == 0
        )
        if not report["ok"]:
            report["error"] = "File dialog probe did not verify dialog controls, filename setting, and cancel"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        if dialog_hwnd and user32.IsWindow(dialog_hwnd):
            try:
                _command_dialog(dialog_hwnd, IDCANCEL, timeout_ms=250)
            except Exception:
                pass
        try:
            if os.path.exists(path):
                os.remove(path)
                report.setdefault("cleanup", {})["file_removed"] = True
        except Exception as e:
            report.setdefault("cleanup", {})["file_remove_error"] = str(e)


def selftest_ocr(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise OCR fallback using a generated image and Windows built-in OCR."""
    token = f"Windows OCR Probe 12345 {int(time.time() * 1000)}"
    report: Dict[str, Any] = {"app": "ocr_probe", "token": token, "steps": {}}
    path = os.path.join(tempfile.gettempdir(), "win-automation-mcp", f"ocr-probe-{int(time.time() * 1000)}.png")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from PIL import ImageDraw, ImageFont
        img = PILImage.new("RGB", (900, 260), "white")
        draw = ImageDraw.Draw(img)
        font = None
        for candidate in (
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
        ):
            try:
                if os.path.exists(candidate):
                    font = ImageFont.truetype(candidate, 56)
                    break
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()
        draw.text((40, 50), "WINDOWS OCR PROBE", fill="black", font=font)
        draw.text((40, 130), "CONTROL 12345", fill="black", font=font)
        img.save(path)
        report["image"] = path

        windows_result = _run_windows_ocr_on_image(img, lang="eng")
        auto_result = _run_tesseract_ocr_on_image(img, lang="eng")
        if not auto_result.get("ok"):
            auto_result = _run_windows_ocr_on_image(img, lang="eng")
            auto_result["fallback_from"] = [{"engine": "tesseract", "error": "unavailable_or_failed"}]

        report["steps"]["windows_ocr"] = windows_result
        report["steps"]["auto_path"] = {
            "engine": auto_result.get("engine"),
            "text": auto_result.get("text"),
            "error": auto_result.get("error"),
            "fallback_from": auto_result.get("fallback_from"),
        }
        find_result = _find_ocr_text_matches(windows_result, "CONTROL 12345", match="contains", limit=3)
        report["steps"]["ocr_find"] = find_result
        wait_result = _wait_for_ocr_text_result(
            lambda: windows_result,
            "CONTROL 12345",
            match="contains",
            timeout=1.0,
            interval=0.1,
            limit=1,
        )
        timeout_result = _wait_for_ocr_text_result(
            lambda: windows_result,
            "MISSING OCR TOKEN",
            match="exact",
            timeout=0.1,
            interval=0.05,
            limit=1,
        )
        report["steps"]["ocr_wait"] = wait_result
        report["steps"]["ocr_wait_timeout"] = {
            "ok": timeout_result.get("ok"),
            "found": timeout_result.get("found"),
            "error": timeout_result.get("error"),
            "attempts": timeout_result.get("attempts"),
        }
        text = str(windows_result.get("text") or "").upper()
        first_match = (find_result.get("matches") or [{}])[0]
        rect = first_match.get("rect") or {}
        report["ok"] = bool(
            windows_result.get("ok")
            and ("WINDOWS" in text or "12345" in text)
            and find_result.get("found")
            and wait_result.get("found")
            and timeout_result.get("error") == "timeout"
            and 30 <= int(rect.get("left", 0)) <= 80
            and 120 <= int(rect.get("top", 0)) <= 170
        )
        if not report["ok"]:
            report["error"] = "Windows OCR probe did not recognize, locate, and wait for the generated text"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        try:
            if os.path.exists(path):
                os.remove(path)
                report.setdefault("cleanup", {})["file_removed"] = True
        except Exception as e:
            report.setdefault("cleanup", {})["file_remove_error"] = str(e)


def selftest_image_match(timeout: float = 5.0) -> Dict[str, Any]:
    """Exercise OpenCV template matching with region, scale, wait, and timeout paths."""
    report: Dict[str, Any] = {"app": "image_match_probe", "token": f"image-match {int(time.time() * 1000)}", "steps": {}}
    temp_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    hay_path = os.path.join(temp_dir, f"image-probe-{int(time.time() * 1000)}.jpg")
    template_path = os.path.join(temp_dir, f"image-template-{int(time.time() * 1000)}.png")
    try:
        os.makedirs(temp_dir, exist_ok=True)
        from PIL import ImageDraw
        haystack = PILImage.new("RGB", (420, 260), "#f4f4f4")
        draw = ImageDraw.Draw(haystack)
        draw.rectangle((20, 20, 400, 240), outline="#999999", width=2)
        draw.rounded_rectangle((250, 95, 330, 155), radius=8, fill="#1e88e5", outline="#0d47a1", width=3)
        draw.line((270, 125, 292, 142, 314, 108), fill="white", width=6)
        template = haystack.crop((250, 95, 330, 155))
        haystack.save(hay_path, quality=90)
        template.save(template_path)
        report["image"] = hay_path
        report["template"] = template_path

        exact = _match_template_image(haystack, template, confidence=0.95)
        region = _match_template_image(haystack, template, confidence=0.95, region="220,70,360,180")
        missing_region = _match_template_image(haystack, template, confidence=0.95, region="0,0,120,80")
        scaled_template = template.resize((40, 30), PILImage.LANCZOS)
        scaled = _match_template_image(haystack, scaled_template, confidence=0.85, scale_min=1.0, scale_max=2.0, scale_step=0.25)
        wait_core = _wait_for_image_match_result(
            lambda: _match_template_image(haystack, template, confidence=0.95),
            timeout=0.5,
            interval=0.1,
        )
        timeout_core = _wait_for_image_match_result(
            lambda: _match_template_image(haystack, template, confidence=1.01),
            timeout=0.1,
            interval=0.05,
        )
        pixel_read = _pixel_from_image(haystack, 260, 100)
        pixel_match = _pixel_match_result(pixel_read, "#1e88e5", tolerance=0)
        pixel_tolerance = _pixel_match_result(pixel_read, "30,136,232", tolerance=3)
        pixel_not = _pixel_match_result(pixel_read, "#ffffff", tolerance=10, mode="not_equals")
        pixel_wait_core = _wait_for_pixel_match_result(
            lambda: _pixel_from_image(haystack, 260, 100),
            "#1e88e5",
            tolerance=0,
            timeout=0.5,
            interval=0.1,
        )
        pixel_timeout_core = _wait_for_pixel_match_result(
            lambda: _pixel_from_image(haystack, 260, 100),
            "#ffffff",
            tolerance=0,
            timeout=0.1,
            interval=0.05,
        )
        stable_same = _wait_for_visual_stability(
            lambda: (haystack.copy(), {"source": "same"}),
            timeout=0.3,
            interval=0.01,
            stable_ticks=2,
            difference_threshold=0.0,
            pixel_threshold=0,
            region="220,70,360,180",
            max_width=80,
        )
        moving_frames = []
        for x_offset in (0, 8, 16):
            frame = PILImage.new("RGB", (80, 40), "#f4f4f4")
            frame.paste(template.resize((32, 24), PILImage.LANCZOS), (8 + x_offset, 8))
            moving_frames.append(frame)
        moving_frames.extend([moving_frames[-1].copy(), moving_frames[-1].copy()])
        moving_index = {"i": 0}

        def moving_fetch() -> Tuple[PILImage.Image, Dict[str, Any]]:
            index = min(moving_index["i"], len(moving_frames) - 1)
            moving_index["i"] += 1
            return moving_frames[index].copy(), {"frame": index}

        stable_after_change = _wait_for_visual_stability(
            moving_fetch,
            timeout=0.5,
            interval=0.01,
            stable_ticks=2,
            difference_threshold=0.0,
            pixel_threshold=0,
            max_width=80,
        )
        toggle_index = {"i": 0}

        def toggling_fetch() -> Tuple[PILImage.Image, Dict[str, Any]]:
            toggle_index["i"] += 1
            frame = PILImage.new("RGB", (24, 24), "#ffffff" if toggle_index["i"] % 2 else "#000000")
            return frame, {"frame": toggle_index["i"]}

        stable_timeout = _wait_for_visual_stability(
            toggling_fetch,
            timeout=0.05,
            interval=0.01,
            stable_ticks=2,
            difference_threshold=0.0,
            pixel_threshold=0,
            max_width=24,
        )
        base_snapshot = {
            "view": "control",
            "focused_element": "None",
            "selected_text": "",
            "elements": [
                {
                    "index": 0,
                    "depth": 0,
                    "name": "Root",
                    "automation_id": "root",
                    "control_type": "window",
                    "control_type_id": 50032,
                    "class_name": "ProbeWindow",
                    "framework_id": "Win32",
                    "enabled": True,
                    "visible": True,
                    "offscreen": False,
                    "rect": {"left": 0, "top": 0, "right": 400, "bottom": 260, "width": 400, "height": 260},
                    "patterns": ["Window"],
                },
                {
                    "index": 1,
                    "depth": 1,
                    "name": "Ready",
                    "automation_id": "ready",
                    "control_type": "button",
                    "control_type_id": 50000,
                    "class_name": "Button",
                    "framework_id": "Win32",
                    "enabled": True,
                    "visible": True,
                    "offscreen": False,
                    "rect": {"left": 20, "top": 20, "right": 120, "bottom": 50, "width": 100, "height": 30},
                    "patterns": ["Invoke"],
                },
            ],
        }
        uia_same = _wait_for_uia_stability(
            lambda: copy.deepcopy(base_snapshot),
            timeout=0.3,
            interval=0.01,
            stable_ticks=2,
        )
        uia_frames = [
            {**copy.deepcopy(base_snapshot), "elements": copy.deepcopy(base_snapshot["elements"][:1])},
            copy.deepcopy(base_snapshot),
            copy.deepcopy(base_snapshot),
            copy.deepcopy(base_snapshot),
        ]
        uia_frame_index = {"i": 0}

        def uia_fetch() -> Dict[str, Any]:
            index = min(uia_frame_index["i"], len(uia_frames) - 1)
            uia_frame_index["i"] += 1
            return copy.deepcopy(uia_frames[index])

        uia_after_change = _wait_for_uia_stability(
            uia_fetch,
            timeout=0.3,
            interval=0.01,
            stable_ticks=2,
        )
        uia_toggle_index = {"i": 0}

        def uia_toggle_fetch() -> Dict[str, Any]:
            uia_toggle_index["i"] += 1
            snapshot = copy.deepcopy(base_snapshot)
            snapshot["elements"][1]["name"] = "Ready" if uia_toggle_index["i"] % 2 else "Busy"
            return snapshot

        uia_timeout = _wait_for_uia_stability(
            uia_toggle_fetch,
            timeout=0.05,
            interval=0.01,
            stable_ticks=2,
        )

        report["steps"]["exact"] = exact
        report["steps"]["region"] = region
        report["steps"]["missing_region"] = {"found": missing_region.get("found"), "best_match": missing_region.get("best_match")}
        report["steps"]["scaled"] = scaled
        report["steps"]["wait"] = wait_core
        report["steps"]["wait_timeout"] = {
            "ok": timeout_core.get("ok"),
            "found": timeout_core.get("found"),
            "error": timeout_core.get("error"),
            "attempts": timeout_core.get("attempts"),
        }
        report["steps"]["pixel"] = {
            "read": pixel_read,
            "match": pixel_match,
            "tolerance": pixel_tolerance,
            "not": pixel_not,
            "wait": {
                "ok": pixel_wait_core.get("ok"),
                "matched": pixel_wait_core.get("matched"),
                "attempts": pixel_wait_core.get("attempts"),
            },
            "timeout": {
                "ok": pixel_timeout_core.get("ok"),
                "matched": pixel_timeout_core.get("matched"),
                "error": pixel_timeout_core.get("error"),
                "attempts": pixel_timeout_core.get("attempts"),
            },
        }
        report["steps"]["visual_stability"] = {
            "same": {
                "ok": stable_same.get("ok"),
                "stable": stable_same.get("stable"),
                "attempts": stable_same.get("attempts"),
                "region": (stable_same.get("analysis") or {}).get("region"),
            },
            "after_change": {
                "ok": stable_after_change.get("ok"),
                "stable": stable_after_change.get("stable"),
                "attempts": stable_after_change.get("attempts"),
                "max_diff_ratio": stable_after_change.get("max_diff_ratio"),
            },
            "timeout": {
                "ok": stable_timeout.get("ok"),
                "stable": stable_timeout.get("stable"),
                "error": stable_timeout.get("error"),
                "attempts": stable_timeout.get("attempts"),
            },
        }
        report["steps"]["uia_stability"] = {
            "same": {
                "ok": uia_same.get("ok"),
                "stable": uia_same.get("stable"),
                "attempts": uia_same.get("attempts"),
                "changed": uia_same.get("changed"),
            },
            "after_change": {
                "ok": uia_after_change.get("ok"),
                "stable": uia_after_change.get("stable"),
                "attempts": uia_after_change.get("attempts"),
                "changed": uia_after_change.get("changed"),
            },
            "timeout": {
                "ok": uia_timeout.get("ok"),
                "stable": uia_timeout.get("stable"),
                "error": uia_timeout.get("error"),
                "attempts": uia_timeout.get("attempts"),
            },
        }
        match = exact.get("match") or {}
        scaled_match = scaled.get("match") or {}
        report["ok"] = bool(
            exact.get("found")
            and region.get("found")
            and not missing_region.get("found")
            and scaled.get("found")
            and wait_core.get("found")
            and timeout_core.get("error") == "timeout"
            and pixel_match.get("matched")
            and pixel_tolerance.get("matched")
            and pixel_not.get("matched")
            and pixel_wait_core.get("matched")
            and pixel_timeout_core.get("error") == "timeout"
            and stable_same.get("stable")
            and stable_after_change.get("stable")
            and int(stable_after_change.get("attempts") or 0) >= 4
            and stable_timeout.get("error") == "timeout"
            and uia_same.get("stable")
            and uia_after_change.get("stable")
            and uia_after_change.get("changed")
            and uia_timeout.get("error") == "timeout"
            and 285 <= int(match.get("center_x", 0)) <= 295
            and 120 <= int(match.get("center_y", 0)) <= 135
            and 285 <= int(scaled_match.get("center_x", 0)) <= 295
            and 120 <= int(scaled_match.get("center_y", 0)) <= 135
        )
        if not report["ok"]:
            report["error"] = "Image match probe did not verify exact, region, scale, pixel, visual/UIA stability, wait, and timeout matching"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        for path in (hay_path, template_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
                    report.setdefault("cleanup", {}).setdefault("removed", []).append(path)
            except Exception as e:
                report.setdefault("cleanup", {}).setdefault("errors", []).append(str(e))


def selftest_batch(timeout: float = 1.0) -> Dict[str, Any]:
    """Exercise batch result normalization and stop-on-error semantics without desktop I/O."""
    report: Dict[str, Any] = {"app": "batch_contract_probe", "timeout": timeout, "steps": {}}
    try:
        success_string = _batch_normalize_result("Pressed: enter")
        error_string = _batch_normalize_result("Error: bad key")
        warning_string = _batch_normalize_result("Warning: pasted 3 characters but clipboard restore may be incomplete (restored_formats=0, error=open_clipboard_failed)")
        helper_clipboard_warning = _batch_normalize_result({
            "ok": True,
            "length": 3,
            "clipboard_saved_formats": 2,
            "clipboard_skipped_formats": 1,
            "clipboard_restore_ok": False,
            "clipboard_restored_formats": 1,
            "clipboard_restore_error": "restore failed",
        })
        warning_failure = _batch_result_failure(warning_string, command="type")
        helper_warning_failure = _batch_result_failure(helper_clipboard_warning, command="type")
        value_result = _batch_normalize_result(["probe"])
        empty_result = _batch_normalize_result(None)
        normalized_item = _batch_normalize_item({"command": "message", "result": "OK"}, 7)
        summary = _batch_summary(
            [
                {"index": 0, "command": "success", "result": success_string},
                {"index": 1, "command": "error_string", "result": error_string},
                {"index": 2, "command": "value", "result": value_result},
                {"index": 3, "command": "empty", "result": empty_result},
                {"index": 4, "command": "type", "result": helper_clipboard_warning},
            ],
            total_count=5,
        )
        clipboard_recovery_batch = execute_batch([
            {
                "id": "clipboard_warn",
                "command": "batch_value",
                "args": {"value": helper_clipboard_warning},
                "recover_on_failure": {
                    "clipboard_restore": [
                        {"id": "fallback_text_input", "command": "batch_value", "args": {"value": "retried-with-focused-input"}},
                    ],
                },
            }
        ], trace=True)
        local_all = execute_batch([
            {"command": "unknown_batch_probe_one", "args": {}},
            {"command": "unknown_batch_probe_two", "args": {}},
        ])
        local_stop = execute_batch(
            [
                {"command": "unknown_batch_probe_one", "args": {}},
                {"command": "unknown_batch_probe_two", "args": {}},
            ],
            stop_on_error=True,
        )
        malformed_all = execute_batch([
            "not-an-object",
            {"command": "unknown_batch_probe_three", "args": "not-an-object"},
            {"path": "/unknown_batch_probe_path", "data": ["not", "an", "object"]},
        ])
        malformed_stop = execute_batch(
            [
                "not-an-object",
                {"command": "unknown_batch_probe_three", "args": "not-an-object"},
            ],
            stop_on_error=True,
        )
        retry_fail = execute_batch([
            {"command": "unknown_batch_retry_probe", "args": {}, "retries": 2, "retry_delay": 0},
        ])
        ref_batch = execute_batch([
            {"command": "batch_value", "args": {"value": {"hwnd": 12345, "index": 7}}},
            {"command": "batch_value", "args": {"value": {"copied_hwnd": "$steps.0.result.value.hwnd", "nested": ["$steps.0.result.value.index"]}}},
        ], stop_on_error=True)
        arg_alias_batch = execute_batch([
            {"command": "batch_value", "data": {"value": "command-data"}},
            {"path": "/batch_value", "args": {"value": "path-args"}},
            {"path": "batch-value", "data": {"value": "path-data"}},
        ], stop_on_error=True)
        sleep_batch = execute_batch([
            {"command": "batch_sleep", "args": {"delay": 0}},
            {"command": "sleep", "args": {"seconds": 0}},
        ], stop_on_error=True)
        safety_gate_blocked = execute_batch([
            {
                "id": "delete_probe",
                "command": "batch_value",
                "args": {"action": "delete", "value": "must-not-run"},
            },
        ])
        safety_gate_nested_blocked = execute_batch([
            {
                "id": "nested_plan",
                "command": "batch_value",
                "args": {
                    "value": "parent",
                    "workflow": [
                        {
                            "id": "message_probe",
                            "command": "batch_value",
                            "args": {"action": "send_message", "value": "must-not-run"},
                        },
                    ],
                },
            },
        ])
        safety_gate_confirmed = execute_batch([
            {
                "id": "confirmed_delete_probe",
                "command": "batch_value",
                "args": {"action": "delete", "value": "confirmed"},
            },
        ], confirmed=True)
        batch_alias_cases = [
            ("command_data_alias", {"command": "batch-value", "data": {"value": "cmd-data"}}, "batch_value", "", "cmd-data"),
            ("path_args_alias", {"path": "/batch-value", "args": {"value": "path-args"}}, "batch_value", "/batch_value", "path-args"),
            ("mcp_find_elements", {"command": "find_elements", "args": {"hwnd": 1}}, "uia_find", "", None),
            ("mcp_get_element", {"command": "get_element", "args": {"hwnd": 1, "index": 2}}, "uia_element", "", None),
            ("mcp_click_element", {"command": "click_element", "args": {"hwnd": 1, "index": 2}}, "uia_click_index", "", None),
            ("mcp_perform_secondary_action", {"command": "perform_secondary_action", "args": {"hwnd": 1, "index": 2, "action": "Invoke"}}, "uia_action", "", None),
            ("mcp_desktop_get", {"command": "desktop_get_element", "args": {"index": 2}}, "desktop_element", "", None),
            ("mcp_desktop_click_text_ocr", {"command": "desktop_click_text_ocr", "args": {"text": "OK"}}, "desktop_ocr_click", "", None),
            ("ensure_window_alias", {"command": "ensure-window", "args": {"title": "Demo"}}, "auto_window", "", None),
            ("helper_status_alias", {"command": "helper-status", "args": {"restart": "false"}}, "helper_status", "", None),
            ("local_desktop_path", {"path": "/desktop-click", "data": {"x": 1, "y": 2}}, "desktop_click", "/desktop-click", None),
            ("local_desktop_mcp_path", {"path": "/desktop-get-element", "data": {"index": 2}}, "desktop_element", "/desktop-get-element", None),
            ("local_ocr_mcp_path", {"path": "/click-text-ocr", "data": {"hwnd": 1, "text": "OK"}}, "ocr_click", "/click-text-ocr", None),
            ("local_ocr_scroll_mcp_path", {"path": "/ocr-scroll-click", "data": {"hwnd": 1, "text": "OK"}}, "ocr_scroll_click", "/ocr_scroll_click", None),
            ("local_image_mcp_path", {"path": "/wait-image", "data": {"hwnd": 1, "template": "icon.png"}}, "image_wait", "/wait-image", None),
            ("local_image_scroll_mcp_path", {"path": "/image-scroll-click", "data": {"hwnd": 1, "template": "icon.png"}}, "image_scroll_click", "/image_scroll_click", None),
            ("local_auto_window_path", {"path": "/auto-window", "data": {"title": "Demo"}}, "auto_window", "/auto_window", None),
            ("local_window_repair_alias", {"command": "window-rebind", "args": {"original": {"title": "Demo"}}}, "window_selector_repair_find", "", None),
            ("local_window_repair_path", {"path": "/window-selector-repair-find", "data": {"original": {"title": "Demo"}}}, "window_selector_repair_find", "/window_selector_repair_find", None),
            ("local_helper_status_path", {"path": "/helper-status", "data": {"restart": "false"}}, "helper_status", "/helper_status", None),
            ("local_batch_repair_plan_alias", {"command": "repair-plan", "args": {"diagnostic_summary": {}}}, "batch_repair_plan", "", None),
            ("local_batch_repair_plan_path", {"path": "/batch-repair-plan", "data": {"diagnostic_summary": {}}}, "batch_repair_plan", "/batch_repair_plan", None),
            ("helper_win32_find_alias", {"command": "win32-find-control", "args": {"hwnd": 1, "type": "edit"}}, "win32_control_find", "", None),
            ("helper_win32_find_path", {"path": "/win32-control-find", "data": {"hwnd": 1, "type": "edit"}}, "win32_control_find", "/win32_control_find", None),
            ("helper_win32_wait_find_alias", {"command": "wait-native-control-find", "args": {"hwnd": 1, "type": "button"}}, "win32_control_wait_find", "", None),
            ("helper_win32_wait_find_path", {"path": "/win32-control-wait-find", "data": {"hwnd": 1, "type": "button"}}, "win32_control_wait_find", "/win32_control_wait_find", None),
            ("local_sleep_alias", {"command": "sleep", "args": {"seconds": 0}}, "batch_sleep", "", None),
            ("local_sleep_path", {"path": "/batch-sleep", "data": {"delay": 0}}, "batch_sleep", "/batch_sleep", None),
            ("local_pixel_wait_alias", {"command": "pixel-wait", "args": {"hwnd": 1, "x": 1, "y": 2, "color": "#ffffff"}}, "pixel_wait", "", None),
            ("local_pixel_wait_path", {"path": "/pixel-wait", "data": {"hwnd": 1, "x": 1, "y": 2, "color": "#ffffff"}}, "pixel_wait", "/pixel_wait", None),
            ("local_desktop_pixel_wait_alias", {"command": "desktop-wait-pixel", "args": {"x": 1, "y": 2, "color": "#ffffff"}}, "desktop_pixel_wait", "", None),
            ("local_desktop_pixel_wait_path", {"path": "/desktop-pixel-wait", "data": {"x": 1, "y": 2, "color": "#ffffff"}}, "desktop_pixel_wait", "/desktop_pixel_wait", None),
            ("local_visual_stable_wait_alias", {"command": "wait-visual-stable", "args": {"hwnd": 1}}, "visual_stable_wait", "", None),
            ("local_visual_stable_wait_path", {"path": "/visual-stable-wait", "data": {"hwnd": 1}}, "visual_stable_wait", "/visual_stable_wait", None),
            ("local_desktop_visual_stable_wait_alias", {"command": "desktop-wait-visual-stable", "args": {}}, "desktop_visual_stable_wait", "", None),
            ("local_desktop_visual_stable_wait_path", {"path": "/desktop-visual-stable-wait", "data": {}}, "desktop_visual_stable_wait", "/desktop_visual_stable_wait", None),
            ("local_uia_stable_wait_alias", {"command": "wait-uia-stable", "args": {"hwnd": 1}}, "uia_stable_wait", "", None),
            ("local_uia_stable_wait_path", {"path": "/uia-stable-wait", "data": {"hwnd": 1}}, "uia_stable_wait", "/uia_stable_wait", None),
            ("local_desktop_uia_stable_wait_alias", {"command": "desktop-wait-uia-stable", "args": {}}, "desktop_uia_stable_wait", "", None),
            ("local_desktop_uia_stable_wait_path", {"path": "/desktop-uia-stable-wait", "data": {}}, "desktop_uia_stable_wait", "/desktop_uia_stable_wait", None),
        ]
        batch_alias_contracts = []
        for label, item, expected_command, expected_path, expected_value in batch_alias_cases:
            actual_command, actual_path, actual_args = _batch_command_parts(item)
            expected_args_ok = True if expected_value is None else actual_args.get("value") == expected_value
            batch_alias_contracts.append({
                "label": label,
                "command": actual_command,
                "path": actual_path,
                "args": actual_args,
                "expected_command": expected_command,
                "expected_path": expected_path,
                "ok": actual_command == expected_command and actual_path == expected_path and expected_args_ok,
            })
        expect_pass = execute_batch([
            {
                "command": "batch_value",
                "args": {"value": {"text": "Ready OK", "items": [1, 2, 3], "count": 3}},
                "expect": [
                    {"path": "$result.value.text", "contains": "OK"},
                    {"path": "$result.value.items", "min_len": 3},
                    {"path": "$result.value.count", "equals": 3},
                    {"path": "$result.ok", "equals": True},
                ],
            },
        ])
        expect_fail = execute_batch([
            {
                "command": "batch_value",
                "args": {"value": {"text": "Still loading"}},
                "expect": {"path": "$result.value.text", "contains": "Ready"},
            },
        ])
        expect_retry_fail = execute_batch([
            {
                "command": "batch_value",
                "args": {"value": {"items": []}},
                "expect": {"path": "$result.value.items", "min_len": 1},
                "retries": 2,
                "retry_delay": 0,
            },
        ])
        expect_refs = execute_batch([
            {"command": "batch_value", "args": {"value": {"expected": "Done"}}},
            {
                "command": "batch_value",
                "args": {"value": {"status": "Done"}},
                "expect": {"path": "$result.value.status", "equals": "$steps.0.result.value.expected"},
            },
        ], stop_on_error=True)
        expect_ops = execute_batch([
            {
                "command": "batch_value",
                "args": {"value": {"text": "Ready OK", "items": ["Save", "Open"], "count": 3, "empty": []}},
                "expect": [
                    {"path": "$result.value.items", "contains_any": ["Missing", "Save"]},
                    {"path": "$result.value.items", "contains_all": ["Save", "Open"]},
                    {"path": "$result.value.text", "starts_with": "Ready"},
                    {"path": "$result.value.text", "ends_with": "OK"},
                    {"path": "$result.value.items", "not_empty": True},
                    {"path": "$result.value.empty", "empty": True},
                    {"path": "$result.value.count", "gt": 2},
                    {"path": "$result.value.count", "lte": 3},
                    {"path": "$result.value.items", "type": "list"},
                ],
            },
        ])
        expect_ops_fail = execute_batch([
            {
                "command": "batch_value",
                "args": {"value": {"count": 1}},
                "expect": {"path": "$result.value.count", "gte": 2},
            },
        ])
        extract_batch = execute_batch([
            {
                "id": "raw",
                "command": "batch_value",
                "args": {"value": {"matches": [{"name": "Save", "index": 4}], "count": 1, "blob": ["ignored"]}},
                "extract": {"first": "$result.value.matches.0.name", "count": "$result.value.count"},
                "expect": {"path": "$result.value.matches", "not_empty": True},
            },
            {
                "id": "use_extract",
                "command": "batch_value",
                "args": {"value": "$steps.raw.result.value.first"},
                "expect": {"path": "$result.value", "equals": "Save"},
            },
        ], stop_on_error=True)
        extract_fail = execute_batch([
            {
                "command": "batch_value",
                "args": {"value": {"matches": []}},
                "extract": "$result.value.matches.0.name",
            },
        ])
        conditional_batch = execute_batch([
            {"command": "batch_value", "args": {"value": {"dialog": "absent", "ready": True}}},
            {
                "command": "unknown_batch_should_skip_when",
                "args": {},
                "when": {"path": "$steps.0.result.value.dialog", "equals": "present"},
            },
            {
                "command": "unknown_batch_should_skip_unless",
                "args": {},
                "unless": {"path": "$steps.0.result.value.ready", "equals": True},
            },
            {
                "command": "batch_value",
                "args": {"value": "continued"},
                "when": {"path": "$steps.1.result.skipped", "equals": True},
                "expect": {"path": "$result.value", "equals": "continued"},
            },
        ], stop_on_error=True)
        named_ref_batch = execute_batch([
            {"id": "launch_info", "command": "batch_value", "args": {"value": {"hwnd": 2468, "state": "ready"}}},
            {"as": "copied", "command": "batch_value", "args": {"value": "$steps.launch_info.result.value.hwnd"}},
            {
                "name": "conditional",
                "command": "batch_value",
                "args": {"value": {"state": "$steps.launch_info.result.value.state", "legacy_hwnd": "$steps.0.result.value.hwnd"}},
                "when": {"path": "$steps.copied.result.value", "equals": 2468},
                "expect": [
                    {"path": "$result.value.state", "equals": "ready"},
                    {"path": "$result.value.legacy_hwnd", "equals": 2468},
                ],
            },
            {
                "label": "final",
                "command": "batch_value",
                "args": {"value": "$steps.conditional.result.value.state"},
                "expect": {"path": "$result.value", "equals": "ready"},
            },
        ], stop_on_error=True)
        bracket_ref_batch = execute_batch([
            {
                "id": "probe",
                "command": "batch_value",
                "args": {
                    "value": {
                        "matches": [
                            {"hwnd": 1357, "name": "Primary"},
                        ],
                        "meta": {"state": "ready"},
                    },
                },
                "extract": {
                    "hwnd": "$result['value']['matches'][0]['hwnd']",
                    "state": "$result.value.meta['state']",
                },
            },
            {
                "id": "copied",
                "command": "batch_value",
                "args": {
                    "value": {
                        "hwnd": "$steps['probe']['result']['value']['hwnd']",
                        "state": "$steps.probe.result.value['state']",
                    },
                },
                "when": {"path": "$steps['probe']['result']['value']['state']", "equals": "ready"},
                "expect": [
                    {"path": "$result['value']['hwnd']", "equals": 1357},
                    {"path": "$result.value['state']", "equals": "$steps['probe']['result']['value']['state']"},
                ],
            },
        ], stop_on_error=True)
        optional_batch = execute_batch([
            {
                "id": "uia_probe",
                "command": "unknown_optional_probe",
                "args": {},
                "optional": True,
                "retries": 1,
                "retry_delay": 0,
            },
            {
                "id": "fallback",
                "command": "batch_value",
                "args": {"value": "fallback-used"},
                "when": {"path": "$steps.uia_probe.result.tolerated_failure", "equals": True},
                "expect": {"path": "$result.value", "equals": "fallback-used"},
            },
        ], stop_on_error=True)
        try_batch = execute_batch([
            {"id": "context", "command": "batch_value", "args": {"value": {"target": "win32"}}},
            {
                "id": "layered_action",
                "command": "batch_try",
                "branches": [
                    {"id": "uia", "command": "unknown_try_uia", "args": {}},
                    {
                        "id": "win32",
                        "command": "batch_value",
                        "args": {"value": {"layer": "$steps.context.result.value.target"}},
                        "expect": {"path": "$result.value.layer", "equals": "win32"},
                    },
                    {"id": "visual", "command": "unknown_try_visual", "args": {}},
                ],
                "expect": {"path": "$result.selected_id", "equals": "win32"},
            },
        ], stop_on_error=True)
        try_fail_batch = execute_batch([
            {
                "id": "layered_fail",
                "command": "batch_try",
                "branches": [
                    {"id": "semantic", "command": "unknown_uia_provider_probe", "args": {}},
                    {"id": "visual", "command": "unknown_image_probe", "args": {}},
                ],
            },
        ])
        relocated_batch_result = {
            "ok": True,
            "method": "uia.action.control.invoke",
            "relocated": True,
            "relocation": {
                "from_index": 5,
                "to_index": 9,
                "score": 590,
                "reasons": ["automation_id", "parent_automation_id"],
            },
            "failure_summary": {
                "uia_relocation_count": 1,
                "last_uia_relocation": {
                    "from_index": 5,
                    "to_index": 9,
                    "score": 590,
                    "reasons": ["automation_id", "parent_automation_id"],
                },
            },
        }
        try_relocation_batch = execute_batch([
            {
                "id": "relocated_try",
                "command": "batch_try",
                "branches": [
                    {"id": "semantic", "command": "batch_value", "args": {"value": relocated_batch_result}},
                    {"id": "visual", "command": "unknown_visual_after_relocation", "args": {}},
                ],
            },
        ], stop_on_error=True)
        native_find_suggestion = {
            "automation_id": "101",
            "control_type": "edit",
            "class_name": "Edit",
            "name": "Search",
            "match": "contains",
        }
        native_find_failure_result = {
            "ok": False,
            "error": "no_matching_native_control",
            "hwnd": 24682,
            "failure_summary": {
                "scanned": 4,
                "near_count": 2,
                "matched_before_min_score": 0,
                "miss_counts": {"name": 2},
                "observed_kinds": [{"value": "edit", "count": 2}],
                "observed_classes": [{"value": "Edit", "count": 2}],
                "selector_suggestions": [native_find_suggestion],
                "recommendations": ["The requested name/text did not match candidate text; inspect text_preview or try match=contains/regex."],
            },
            "near_matches": [
                {
                    "hwnd": 4321,
                    "control_id": 101,
                    "kind": "edit",
                    "class_name": "Edit",
                    "name": "Search",
                    "selector_score": 72,
                    "selector_suggestion": native_find_suggestion,
                }
            ],
        }
        native_find_success_result = {
            "ok": True,
            "matches": [
                {
                    "hwnd": 5432,
                    "control_id": 101,
                    "kind": "edit",
                    "class_name": "Edit",
                    "name": "Search",
                    "selector_score": 95,
                }
            ],
        }
        native_repair_branch_diag = _batch_branch_diagnostic_summary({
            "id": "win32_text_selector_repair",
            "selected": True,
            "results": [
                {
                    "id": "win32_text_selector_repair_probe",
                    "command": "win32_control_find",
                    "result": {
                        "ok": True,
                        "tolerated_failure": True,
                        "failure": {"error": "no_matching_native_control"},
                        "original_result": native_find_failure_result,
                    },
                },
                {
                    "id": "win32_text_selector_repair_suggested_find",
                    "command": "win32_control_find",
                    "result": native_find_success_result,
                },
            ],
        })
        native_repair_reports_diag = _batch_reports_diagnostic_summary([
            {
                "id": "win32_text_selector_repair",
                "selected": True,
                "results": [
                    {
                        "id": "win32_text_selector_repair_probe",
                        "command": "win32_control_find",
                        "result": {
                            "ok": True,
                            "tolerated_failure": True,
                            "failure": {"error": "no_matching_native_control"},
                            "original_result": native_find_failure_result,
                        },
                    },
                    {
                        "id": "win32_text_selector_repair_suggested_find",
                        "command": "win32_control_find",
                        "result": native_find_success_result,
                    },
                ],
            }
        ])
        native_wait_failure_result = {
            "ok": False,
            "matched": False,
            "error": "timeout",
            "hwnd": 24683,
            "state": "present",
            "expected": True,
            "attempts": 3,
            "last_result": {
                "state": "present",
                "expected": True,
                "actual": False,
                "present": False,
                "target": {"text": "Delta"},
            },
            "failure_summary": {
                "state": "present",
                "expected": True,
                "actual": False,
                "present": False,
                "target": {"text": "Delta"},
                "target_text": "Delta",
                "match": "exact",
                "kind": "listbox",
                "class_name": "ListBox",
                "control_id": 250,
                "item_count": 2,
                "reported_count": 2,
                "max_items": 200,
                "item_preview": [
                    {"index": 0, "text": "Alpha"},
                    {"index": 1, "text": "Beta"},
                ],
                "repair_suggestions": [
                    {
                        "state": "present",
                        "expected": True,
                        "text": "Delta",
                        "match": "contains",
                        "reason": "same target text with relaxed contains match",
                    }
                ],
                "recommendations": [
                    "relax match, verify item text/case, or run win32_control_info to inspect available native item text"
                ],
            },
        }
        native_wait_branch_diag = _batch_branch_diagnostic_summary({
            "id": "native_presence_verify",
            "selected": True,
            "results": [
                {
                    "id": "verify_present",
                    "command": "win32_control_wait",
                    "result": native_wait_failure_result,
                }
            ],
        })
        native_wait_reports_diag = _batch_reports_diagnostic_summary([
            {
                "id": "native_presence_verify",
                "selected": True,
                "results": [
                    {
                        "id": "verify_present",
                        "command": "win32_control_wait",
                        "result": native_wait_failure_result,
                    }
                ],
            }
        ])
        uia_find_suggestion = {
            "index": 7,
            "automation_id": "saveButton",
            "control_type": "button",
            "class_name": "Button",
            "name": "Save",
            "pattern": "Invoke",
            "match": "contains",
        }
        uia_find_failure_result = {
            "ok": False,
            "error": "no_matching_uia_element",
            "hwnd": 24681,
            "view": "raw",
            "scanned": 5,
            "count": 0,
            "matches": [],
            "near_matches": [
                {
                    "index": 7,
                    "automation_id": "saveButton",
                    "control_type": "button",
                    "class_name": "Button",
                    "name": "Save",
                    "patterns": ["Invoke"],
                    "selector_score": 84,
                    "selector_reasons": ["name_similarity:84", "pattern_match"],
                }
            ],
            "failure_summary": {
                "scanned": 5,
                "view": "raw",
                "miss_counts": {"name": 3},
                "observed_control_types": [{"value": "button", "count": 3}],
                "observed_classes": [{"value": "Button", "count": 3}],
                "selector_suggestions": [uia_find_suggestion],
                "recommendations": ["Requested UIA text did not match; inspect near_matches and retry selector_suggestions."],
            },
        }
        uia_find_success_result = {
            "ok": True,
            "view": "raw",
            "scanned": 5,
            "count": 1,
            "matches": [
                {
                    "index": 7,
                    "automation_id": "saveButton",
                    "control_type": "button",
                    "class_name": "Button",
                    "name": "Save",
                    "patterns": ["Invoke"],
                    "selector_score": 100,
                }
            ],
        }
        uia_find_branch_diag = _batch_branch_diagnostic_summary({
            "id": "uia_selector_repair",
            "selected": True,
            "results": [
                {
                    "id": "uia_selector_repair_probe",
                    "command": "find",
                    "result": {
                        "ok": True,
                        "tolerated_failure": True,
                        "failure": {"error": "no_matching_uia_element"},
                        "original_result": uia_find_failure_result,
                    },
                },
                {
                    "id": "uia_selector_repair_suggested_find",
                    "command": "find",
                    "result": uia_find_success_result,
                },
            ],
        })
        uia_find_reports_diag = _batch_reports_diagnostic_summary([
            {
                "id": "uia_selector_repair",
                "selected": True,
                "results": [
                    {
                        "id": "uia_selector_repair_probe",
                        "command": "find",
                        "result": {
                            "ok": True,
                            "tolerated_failure": True,
                            "failure": {"error": "no_matching_uia_element"},
                            "original_result": uia_find_failure_result,
                        },
                    },
                    {
                        "id": "uia_selector_repair_suggested_find",
                        "command": "find",
                        "result": uia_find_success_result,
                    },
                ],
            }
        ])
        fake_window_primary = {
            "hwnd": 7001,
            "title": "Demo Player - Home",
            "pid": 8100,
            "process_name": "demo-player.exe",
            "process_path": "C:\\Apps\\DemoPlayer\\demo-player.exe",
            "visible": True,
            "rect": {"left": 10, "top": 20, "right": 1010, "bottom": 720, "width": 1000, "height": 700},
        }
        fake_window_secondary = {
            "hwnd": 7002,
            "title": "Settings",
            "pid": 8101,
            "process_name": "other.exe",
            "process_path": "C:\\Apps\\Other\\other.exe",
            "visible": True,
            "rect": {"left": 20, "top": 30, "right": 620, "bottom": 430, "width": 600, "height": 400},
        }
        window_find_failure_summary = _window_find_failure_summary(
            [fake_window_primary, fake_window_secondary],
            title="Demo Music",
            process="player",
            match="contains",
            visible_window_count=2,
            matched_candidates=[],
            stable_counts={7001: 1, 7002: 1},
        )
        window_find_failure_result = {
            "ok": False,
            "error": "window_not_found",
            "near_windows": [
                _compact_window_candidate(
                    fake_window_primary,
                    title="Demo Music",
                    process="player",
                    match="contains",
                    stable_count=1,
                )
            ],
            "failure_summary": window_find_failure_summary,
        }
        window_find_branch_diag = _batch_branch_diagnostic_summary({
            "id": "wait_window",
            "selected": False,
            "results": [
                {"id": "window_wait", "command": "wait_window", "result": window_find_failure_result}
            ],
        })
        window_find_reports_diag = _batch_reports_diagnostic_summary([
            {
                "id": "wait_window",
                "selected": False,
                "results": [
                    {"id": "window_wait", "command": "wait_window", "result": window_find_failure_result}
                ],
            }
        ])
        auto_explicit = execute_batch([
            {
                "id": "auto_probe",
                "command": "batch_auto",
                "args": {"kind": "click"},
                "branches": [
                    {"id": "uia", "command": "unknown_auto_uia", "args": {}},
                    {
                        "id": "win32",
                        "command": "batch_value",
                        "args": {"value": "auto-win32"},
                        "expect": {"path": "$result.value", "equals": "auto-win32"},
                    },
                    {"id": "visual", "command": "unknown_auto_visual", "args": {}},
                ],
                "expect": {"path": "$result.selected_id", "equals": "win32"},
            },
        ], stop_on_error=True, trace=True)
        auto_relocation_batch = execute_batch([
            {
                "id": "auto_relocation_probe",
                "command": "batch_auto",
                "args": {"kind": "click"},
                "branches": [
                    {"id": "smart", "command": "batch_value", "args": {"value": relocated_batch_result}},
                    {"id": "visual", "command": "unknown_visual_after_auto_relocation", "args": {}},
                ],
            },
        ], stop_on_error=True)
        auto_path_explicit = execute_batch([
            {
                "id": "auto_path_probe",
                "path": "/batch-auto",
                "args": {"kind": "click"},
                "alternatives": [
                    {"id": "semantic", "command": "unknown_auto_semantic", "args": {}},
                    {
                        "id": "input",
                        "command": "batch_value",
                        "args": {"value": {"layer": "input"}},
                        "expect": {"path": "$result.value.layer", "equals": "input"},
                    },
                ],
                "expect": {"path": "$result.selected_id", "equals": "input"},
            },
        ], stop_on_error=True)
        auto_click_branch_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "batch_auto"},
                {
                    "kind": "click",
                    "hwnd": 1,
                    "name": "OK",
                    "text": "OK",
                    "image": "icon.png",
                    "x": 3,
                    "y": 4,
                    "timeout": 0.1,
                },
            )
        ]
        auto_click_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {"kind": "click", "hwnd": 1, "name": "OK", "image": "icon.png", "x": 3, "y": 4},
        )
        auto_text_branch_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "auto_action"},
                {"kind": "text", "hwnd": 1, "name": "Search", "text": "query", "timeout": 0.1},
            )
        ]
        auto_select_branch_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "auto_action"},
                {"kind": "select", "hwnd": 1, "name": "Mode", "item": "Normal", "timeout": 0.1},
            )
        ]
        auto_select_check_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "name": "Features",
                "item": "Gamma",
                "mode": "check",
                "match": "exact",
                "timeout-ms": 654,
                "layers": "semantic native",
            },
        )
        auto_select_check_smart = next((branch for branch in auto_select_check_branches if branch.get("id") == "smart_select"), {})
        auto_select_check_native = next((branch for branch in auto_select_check_branches if branch.get("id") == "win32_select"), {})
        auto_select_check_conservative_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "mode": "check",
                "template-path": "gamma.png",
                "layers": "semantic native msaa visual",
            },
        )
        auto_select_check_conservative_ids = [branch.get("id") for branch in auto_select_check_conservative_branches]
        auto_select_check_unverified_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "mode": "check",
                "template-path": "gamma.png",
                "layers": "semantic native msaa visual",
                "allow-unverified-check-fallback": "true",
            },
        )
        auto_select_check_unverified_ids = [branch.get("id") for branch in auto_select_check_unverified_branches]
        auto_select_check_unverified_row_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "mode": "check",
                "row": 7,
                "layers": "semantic native visual",
                "allow-unverified-check-fallback": "true",
            },
        )
        auto_select_check_unverified_row_ids = [branch.get("id") for branch in auto_select_check_unverified_row_branches]
        auto_select_check_verified_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "mode": "check",
                "match": "exact",
                "verify-checked": "true",
                "post-timeout": 0.4,
                "post-interval": 0.05,
                "layers": "semantic native",
            },
        )
        auto_select_check_verified_smart = next((branch for branch in auto_select_check_verified_branches if branch.get("id") == "smart_select"), {})
        auto_select_check_verified_native = next((branch for branch in auto_select_check_verified_branches if branch.get("id") == "win32_select"), {})
        auto_select_check_verified_smart_steps = auto_select_check_verified_smart.get("steps") or []
        auto_select_check_verified_native_steps = auto_select_check_verified_native.get("steps") or []
        auto_select_check_verified_smart_wait = auto_select_check_verified_smart_steps[1] if len(auto_select_check_verified_smart_steps) > 1 else {}
        auto_select_check_verified_native_wait = auto_select_check_verified_native_steps[1] if len(auto_select_check_verified_native_steps) > 1 else {}
        auto_select_check_state_verified_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "mode": "check",
                "verify-win32-state": "check_state",
                "verify-win32-expected": "checked",
                "verify-win32-text": "Gamma",
                "verify-win32-timeout-ms": 333,
                "layers": "native",
            },
        )
        auto_select_check_state_verified_native = next((branch for branch in auto_select_check_state_verified_branches if branch.get("id") == "win32_select"), {})
        auto_select_check_state_verified_steps = auto_select_check_state_verified_native.get("steps") or []
        auto_select_check_state_verified_wait = auto_select_check_state_verified_steps[1] if len(auto_select_check_state_verified_steps) > 1 else {}
        auto_select_present_verified_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "verify-present": "Gamma",
                "verify-native-match": "exact",
                "verify-native-timeout-ms": 222,
                "layers": "native",
            },
        )
        auto_select_present_verified_native = next((branch for branch in auto_select_present_verified_branches if branch.get("id") == "win32_select"), {})
        auto_select_present_verified_steps = auto_select_present_verified_native.get("steps") or []
        auto_select_present_verified_wait = auto_select_present_verified_steps[1] if len(auto_select_present_verified_steps) > 1 else {}
        auto_select_absent_verified_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "verify-item-absent": {
                    "text": "Loading",
                    "match": "exact",
                    "timeout-ms": 444,
                    "max_items": 12,
                },
                "layers": "native",
            },
        )
        auto_select_absent_verified_native = next((branch for branch in auto_select_absent_verified_branches if branch.get("id") == "win32_select"), {})
        auto_select_absent_verified_steps = auto_select_absent_verified_native.get("steps") or []
        auto_select_absent_verified_wait = auto_select_absent_verified_steps[1] if len(auto_select_absent_verified_steps) > 1 else {}
        auto_select_absent_plan_summary = _batch_auto_plan_summary("select", auto_select_absent_verified_branches)
        auto_select_present_repair_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "verify-present": "Gamma",
                "verify-native-match": "exact",
                "auto-recover": "true",
                "recovery-timeout": 0.2,
                "layers": "native",
            },
        )
        auto_select_present_repair_native = next((branch for branch in auto_select_present_repair_branches if branch.get("id") == "win32_select"), {})
        auto_select_present_repair_steps = auto_select_present_repair_native.get("steps") or []
        auto_select_present_repair_wait = auto_select_present_repair_steps[1] if len(auto_select_present_repair_steps) > 1 else {}
        auto_select_present_repair_branch_ids = [branch.get("id") for branch in (auto_select_present_repair_wait.get("branches") or [])]
        auto_select_present_repair_strict = next((branch for branch in (auto_select_present_repair_wait.get("branches") or []) if branch.get("id") == "win32_select_verify_win32_state_strict"), {})
        auto_select_present_repair_relaxed = next((branch for branch in (auto_select_present_repair_wait.get("branches") or []) if branch.get("id") == "win32_select_verify_win32_state_diagnostic_relaxed_retry"), {})
        auto_select_present_repair_probe = (auto_select_present_repair_relaxed.get("steps") or [{}])[0]
        auto_select_present_repair_retry = (auto_select_present_repair_relaxed.get("steps") or [{}, {}])[1] if len(auto_select_present_repair_relaxed.get("steps") or []) > 1 else {}
        auto_select_present_repair_plan_summary = _batch_auto_plan_summary("select", auto_select_present_repair_branches)
        auto_select_present_native_repair_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "verify-present": "Gamma",
                "verify-native-match": "exact",
                "native-wait-repair-match": "contains",
                "native-wait-repair-timeout": 0.4,
                "layers": "native",
            },
        )
        auto_select_present_native_repair_native = next((branch for branch in auto_select_present_native_repair_branches if branch.get("id") == "win32_select"), {})
        auto_select_present_native_repair_steps = auto_select_present_native_repair_native.get("steps") or []
        auto_select_present_native_repair_wait = auto_select_present_native_repair_steps[1] if len(auto_select_present_native_repair_steps) > 1 else {}
        auto_select_present_native_repair_relaxed = next((branch for branch in (auto_select_present_native_repair_wait.get("branches") or []) if branch.get("id") == "win32_select_verify_win32_state_diagnostic_relaxed_retry"), {})
        auto_select_present_native_repair_retry = (auto_select_present_native_repair_relaxed.get("steps") or [{}, {}])[1] if len(auto_select_present_native_repair_relaxed.get("steps") or []) > 1 else {}
        auto_select_present_native_repair_plan_summary = _batch_auto_plan_summary("select", auto_select_present_native_repair_branches)
        auto_select_present_native_repair_disabled_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Gamma",
                "verify-present": "Gamma",
                "verify-native-match": "exact",
                "native-wait-repair": "false",
                "native-wait-repair-match": "contains",
                "native-wait-repair-timeout": 0.4,
                "layers": "native",
            },
        )
        auto_select_present_native_repair_disabled_native = next((branch for branch in auto_select_present_native_repair_disabled_branches if branch.get("id") == "win32_select"), {})
        auto_select_present_native_repair_disabled_steps = auto_select_present_native_repair_disabled_native.get("steps") or []
        auto_select_present_native_repair_disabled_wait = auto_select_present_native_repair_disabled_steps[1] if len(auto_select_present_native_repair_disabled_steps) > 1 else {}
        auto_select_present_native_repair_disabled_plan_summary = _batch_auto_plan_summary("select", auto_select_present_native_repair_disabled_branches)
        auto_cell_branch_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "auto_action"},
                {"kind": "cell", "hwnd": 1, "row": 2, "column": 3, "text": "Done", "timeout": 0.1},
            )
        ]
        auto_key_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "hwnd": 1,
                "shortcut": "ctrl+f",
                "verify-name": "Search",
                "post-timeout": 0.2,
            },
        )
        auto_key_branch_ids = [branch.get("id") for branch in auto_key_branches]
        auto_key_branch = next((branch for branch in auto_key_branches if branch.get("id") == "key_input"), {})
        auto_key_steps = auto_key_branch.get("steps") or []
        auto_key_input = auto_key_steps[0] if len(auto_key_steps) > 0 else {}
        auto_key_post = auto_key_steps[1] if len(auto_key_steps) > 1 else {}
        auto_hover_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {"kind": "hover", "hwnd": 1, "name": "Play", "control-type": "button", "timeout": 0.2, "hover-settle": 0.15},
        )
        auto_hover_branch_ids = [branch.get("id") for branch in auto_hover_branches]
        auto_hover = next((branch for branch in auto_hover_branches if branch.get("id") == "uia_hover"), {})
        auto_hover_steps = auto_hover.get("steps") or []
        auto_hover_find = auto_hover_steps[0] if len(auto_hover_steps) > 0 else {}
        auto_hover_move = auto_hover_steps[1] if len(auto_hover_steps) > 1 else {}
        auto_hover_coord_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {"kind": "hover", "hwnd": 1, "x": 10, "y": 20, "settle": 0.1},
        )
        auto_hover_coord = next((branch for branch in auto_hover_coord_branches if branch.get("id") == "coordinate_hover"), {})
        auto_desktop_hover_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {"kind": "hover", "desktop": True, "x": 10, "y": 20},
        )
        auto_desktop_hover = next((branch for branch in auto_desktop_hover_branches if branch.get("id") == "coordinate_hover"), {})
        auto_scroll_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "hwnd": 1,
                "x": 10,
                "y": 20,
                "wheel": -3,
                "verify-absent-text": "Loading",
            },
        )
        auto_scroll_branch_ids = [branch.get("id") for branch in auto_scroll_branches]
        auto_scroll_wheel = next((branch for branch in auto_scroll_branches if branch.get("id") == "wheel_scroll"), {})
        auto_scroll_keyboard = next((branch for branch in auto_scroll_branches if branch.get("id") == "keyboard_scroll"), {})
        auto_scroll_wheel_steps = auto_scroll_wheel.get("steps") or []
        auto_scroll_keyboard_steps = auto_scroll_keyboard.get("steps") or []
        auto_scroll_wheel_action = auto_scroll_wheel_steps[0] if len(auto_scroll_wheel_steps) > 0 else {}
        auto_scroll_keyboard_action = auto_scroll_keyboard_steps[0] if len(auto_scroll_keyboard_steps) > 0 else {}
        auto_scroll_absent_loop = auto_scroll_wheel_steps[1] if len(auto_scroll_wheel_steps) > 1 else {}
        auto_scroll_absent_probe = (auto_scroll_absent_loop.get("steps") or [{}])[0]
        auto_scroll_no_keyboard_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "auto_action"},
                {"kind": "scroll", "hwnd": 1, "x": 10, "y": 20, "dy": 2, "keyboard-fallback": "false"},
            )
        ]
        auto_desktop_scroll_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {"kind": "scroll", "desktop": True, "x": 10, "y": 20, "dy": 4},
        )
        auto_desktop_scroll_ids = [branch.get("id") for branch in auto_desktop_scroll_branches]
        auto_desktop_scroll = next((branch for branch in auto_desktop_scroll_branches if branch.get("id") == "desktop_scroll"), {})
        auto_desktop_scroll_with_keyboard_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {"kind": "scroll", "desktop": True, "x": 10, "y": 20, "dy": 4, "keyboard-scroll": "true"},
        )
        auto_desktop_scroll_with_keyboard = next((branch for branch in auto_desktop_scroll_with_keyboard_branches if branch.get("id") == "keyboard_scroll"), {})
        auto_drag_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "hwnd": 1,
                "start-x": 1,
                "start-y": 2,
                "end-x": 30,
                "end-y": 40,
                "duration": 0.2,
            },
        )
        auto_drag_branch_ids = [branch.get("id") for branch in auto_drag_branches]
        auto_drag = next((branch for branch in auto_drag_branches if branch.get("id") == "coordinate_drag"), {})
        auto_menu_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "hwnd": 1,
                "menu-path": ["File", "Open"],
                "timeout-ms": 777,
            },
        )
        auto_menu_branch_ids = [branch.get("id") for branch in auto_menu_branches]
        auto_menu = next((branch for branch in auto_menu_branches if branch.get("id") == "menu_action"), {})
        auto_menu_system_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "menu",
                "hwnd": 1,
                "command-id": 0xF030,
                "include-system": "true",
                "async-post": "true",
                "layers": "native",
            },
        )
        auto_menu_system = next((branch for branch in auto_menu_system_branches if branch.get("id") == "menu_action"), {})
        auto_layered_branch_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "auto_action"},
                {"kind": "click", "hwnd": 1, "name": "OK", "text": "OK", "x": 3, "y": 4, "layers": "visual input"},
            )
        ]
        auto_alias_branches = _batch_auto_branches(
            {"command": "auto-action"},
            {
                "kind": "click",
                "hwnd": 1,
                "automation-id": "saveButton",
                "control-type": "button",
                "template-path": "icon2.png",
                "timeout-ms": 321,
                "capture-mode": "visible",
            },
        )
        auto_alias_smart = next((branch for branch in auto_alias_branches if branch.get("id") == "smart_click"), {})
        auto_alias_image = next((branch for branch in auto_alias_branches if branch.get("id") == "image_click"), {})
        auto_selector_repair_click_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "OK",
                "automation-id": "okButton",
                "control-type": "button",
                "class-name": "Button",
                "timeout": 0.1,
            },
        )
        auto_selector_repair_click_ids = [branch.get("id") for branch in auto_selector_repair_click_branches]
        auto_selector_repair_click_stable = next((branch for branch in auto_selector_repair_click_branches if branch.get("id") == "smart_click_selector_repair_1"), {})
        auto_selector_repair_click_named = next((branch for branch in auto_selector_repair_click_branches if branch.get("id") == "smart_click_selector_repair_2"), {})
        auto_uia_repair_click = next((branch for branch in auto_selector_repair_click_branches if branch.get("id") == "uia_click_selector_repair"), {})
        auto_uia_repair_click_steps = auto_uia_repair_click.get("steps") or []
        auto_uia_repair_click_try = auto_uia_repair_click_steps[1] if len(auto_uia_repair_click_steps) > 1 else {}
        auto_uia_repair_click_try_branches = auto_uia_repair_click_try.get("branches") or []
        auto_uia_repair_click_suggested_steps = (auto_uia_repair_click_try_branches[1].get("steps") if len(auto_uia_repair_click_try_branches) > 1 and isinstance(auto_uia_repair_click_try_branches[1], dict) else []) or []
        auto_native_repair_click = next((branch for branch in auto_selector_repair_click_branches if branch.get("id") == "win32_click_selector_repair"), {})
        auto_native_repair_click_steps = auto_native_repair_click.get("steps") or []
        auto_selector_repair_text_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "text",
                "hwnd": 1,
                "name": "Search",
                "automation-id": "searchBox",
                "control-type": "edit",
                "class-name": "SearchBox",
                "text": "query",
                "timeout": 0.1,
            },
        )
        auto_selector_repair_text_ids = [branch.get("id") for branch in auto_selector_repair_text_branches]
        auto_selector_repair_text_stable = next((branch for branch in auto_selector_repair_text_branches if branch.get("id") == "smart_text_selector_repair_1"), {})
        auto_uia_repair_text = next((branch for branch in auto_selector_repair_text_branches if branch.get("id") == "uia_text_selector_repair"), {})
        auto_uia_repair_text_steps = auto_uia_repair_text.get("steps") or []
        auto_uia_repair_text_try = auto_uia_repair_text_steps[1] if len(auto_uia_repair_text_steps) > 1 else {}
        auto_uia_repair_text_try_branches = auto_uia_repair_text_try.get("branches") or []
        auto_uia_repair_text_suggested_steps = (auto_uia_repair_text_try_branches[1].get("steps") if len(auto_uia_repair_text_try_branches) > 1 and isinstance(auto_uia_repair_text_try_branches[1], dict) else []) or []
        auto_native_repair_text = next((branch for branch in auto_selector_repair_text_branches if branch.get("id") == "win32_text_selector_repair"), {})
        auto_native_repair_text_steps = auto_native_repair_text.get("steps") or []
        auto_selector_repair_select_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "name": "Mode",
                "automation-id": "modeList",
                "control-type": "list item",
                "class-name": "ListItem",
                "item": "Normal",
                "timeout": 0.1,
            },
        )
        auto_selector_repair_select_ids = [branch.get("id") for branch in auto_selector_repair_select_branches]
        auto_selector_repair_select_stable = next((branch for branch in auto_selector_repair_select_branches if branch.get("id") == "smart_select_selector_repair_1"), {})
        auto_uia_repair_select = next((branch for branch in auto_selector_repair_select_branches if branch.get("id") == "uia_select_selector_repair"), {})
        auto_uia_repair_select_steps = auto_uia_repair_select.get("steps") or []
        auto_uia_repair_select_try = auto_uia_repair_select_steps[1] if len(auto_uia_repair_select_steps) > 1 else {}
        auto_uia_repair_select_try_branches = auto_uia_repair_select_try.get("branches") or []
        auto_uia_repair_select_suggested_steps = (auto_uia_repair_select_try_branches[1].get("steps") if len(auto_uia_repair_select_try_branches) > 1 and isinstance(auto_uia_repair_select_try_branches[1], dict) else []) or []
        auto_native_repair_select = next((branch for branch in auto_selector_repair_select_branches if branch.get("id") == "win32_select_selector_repair"), {})
        auto_native_repair_select_steps = auto_native_repair_select.get("steps") or []
        auto_native_repair_cell_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "cell",
                "hwnd": 1,
                "name": "Results",
                "control-type": "listview",
                "row": 2,
                "column": 3,
                "text": "Done",
                "layers": "native",
            },
        )
        auto_native_repair_cell_ids = [branch.get("id") for branch in auto_native_repair_cell_branches]
        auto_native_repair_cell = next((branch for branch in auto_native_repair_cell_branches if branch.get("id") == "win32_cell_selector_repair"), {})
        auto_native_repair_cell_steps = auto_native_repair_cell.get("steps") or []
        auto_uia_repair_cell_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "cell",
                "hwnd": 1,
                "automation-id": "resultsGrid",
                "control-type": "data item",
                "row": 2,
                "column": 3,
                "row-text": "Beta",
                "column-name": "State",
                "text": "Done",
                "action": "set",
                "layers": "semantic",
                "max_depth": 4,
                "max_elements": 40,
                "view": "control",
            },
        )
        auto_uia_repair_cell_ids = [branch.get("id") for branch in auto_uia_repair_cell_branches]
        auto_uia_repair_cell = next((branch for branch in auto_uia_repair_cell_branches if branch.get("id") == "uia_cell_selector_repair"), {})
        auto_uia_repair_cell_steps = auto_uia_repair_cell.get("steps") or []
        auto_uia_repair_cell_probe = auto_uia_repair_cell_steps[0] if auto_uia_repair_cell_steps else {}
        auto_uia_repair_cell_try = auto_uia_repair_cell_steps[1] if len(auto_uia_repair_cell_steps) > 1 else {}
        auto_uia_repair_cell_try_branches = auto_uia_repair_cell_try.get("branches") or []
        auto_uia_repair_cell_direct_steps = (auto_uia_repair_cell_try_branches[0].get("steps") if auto_uia_repair_cell_try_branches and isinstance(auto_uia_repair_cell_try_branches[0], dict) else []) or []
        auto_uia_repair_cell_suggested_steps = (auto_uia_repair_cell_try_branches[1].get("steps") if len(auto_uia_repair_cell_try_branches) > 1 and isinstance(auto_uia_repair_cell_try_branches[1], dict) else []) or []
        auto_uia_repair_cell_get_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "cell",
                "hwnd": 1,
                "row": 2,
                "column": 3,
                "action": "get",
                "layers": "semantic",
            },
        )
        auto_uia_repair_cell_get = next((branch for branch in auto_uia_repair_cell_get_branches if branch.get("id") == "uia_cell_selector_repair"), {})
        auto_uia_repair_cell_get_steps = auto_uia_repair_cell_get.get("steps") or []
        auto_uia_repair_cell_get_try = auto_uia_repair_cell_get_steps[1] if len(auto_uia_repair_cell_get_steps) > 1 else {}
        auto_uia_repair_cell_get_try_branches = auto_uia_repair_cell_get_try.get("branches") or []
        auto_uia_repair_cell_get_direct_steps = (auto_uia_repair_cell_get_try_branches[0].get("steps") if auto_uia_repair_cell_get_try_branches and isinstance(auto_uia_repair_cell_get_try_branches[0], dict) else []) or []
        auto_smart_wait_repair_click_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "OK",
                "control-type": "button",
                "timeout": 0.1,
                "repair": "true",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_click = next((branch for branch in auto_smart_wait_repair_click_branches if branch.get("id") == "smart_wait_click"), {})
        auto_smart_wait_repair_click_plan_summary = _batch_auto_plan_summary("click", auto_smart_wait_repair_click_branches)
        auto_smart_wait_repair_uia_alias_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "OK",
                "control-type": "button",
                "timeout": 0.1,
                "uia-selector-repair": "true",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_uia_alias = next((branch for branch in auto_smart_wait_repair_uia_alias_branches if branch.get("id") == "smart_wait_click"), {})
        auto_smart_wait_repair_uia_alias_plan_summary = _batch_auto_plan_summary("click", auto_smart_wait_repair_uia_alias_branches)
        auto_smart_wait_repair_cell_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "cell",
                "hwnd": 1,
                "row": 2,
                "column": 3,
                "timeout": 0.1,
                "selector-repair": "true",
                "selector-repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_cell = next((branch for branch in auto_smart_wait_repair_cell_branches if branch.get("id") == "smart_wait_cell"), {})
        auto_smart_wait_repair_cell_plan_summary = _batch_auto_plan_summary("cell", auto_smart_wait_repair_cell_branches)
        auto_smart_wait_repair_no_timeout_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "OK",
                "control-type": "button",
                "repair": "true",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_no_timeout = next((branch for branch in auto_smart_wait_repair_no_timeout_branches if branch.get("id") == "smart_wait_click"), {})
        auto_smart_wait_repair_no_timeout_plan_summary = _batch_auto_plan_summary("click", auto_smart_wait_repair_no_timeout_branches)
        auto_smart_wait_repair_text_no_timeout_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "text",
                "hwnd": 1,
                "name": "Search",
                "text": "query",
                "action-repair": "true",
                "action-repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_text_no_timeout = next((branch for branch in auto_smart_wait_repair_text_no_timeout_branches if branch.get("id") == "smart_wait_text"), {})
        auto_smart_wait_repair_text_no_timeout_plan_summary = _batch_auto_plan_summary("text", auto_smart_wait_repair_text_no_timeout_branches)
        auto_smart_wait_repair_select_no_timeout_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Beta",
                "uia-selector-repair": "true",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_select_no_timeout = next((branch for branch in auto_smart_wait_repair_select_no_timeout_branches if branch.get("id") == "smart_wait_select"), {})
        auto_smart_wait_repair_select_no_timeout_plan_summary = _batch_auto_plan_summary("select", auto_smart_wait_repair_select_no_timeout_branches)
        auto_smart_wait_repair_cell_no_timeout_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "cell",
                "hwnd": 1,
                "row": 2,
                "column": 3,
                "selector-repair": "true",
                "selector-repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_cell_no_timeout = next((branch for branch in auto_smart_wait_repair_cell_no_timeout_branches if branch.get("id") == "smart_wait_cell"), {})
        auto_smart_wait_repair_cell_no_timeout_plan_summary = _batch_auto_plan_summary("cell", auto_smart_wait_repair_cell_no_timeout_branches)
        auto_smart_wait_repair_timeout_only_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "OK",
                "control-type": "button",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_timeout_only = next((branch for branch in auto_smart_wait_repair_timeout_only_branches if branch.get("id") == "smart_wait_click"), {})
        auto_smart_wait_repair_timeout_only_plan_summary = _batch_auto_plan_summary("click", auto_smart_wait_repair_timeout_only_branches)
        auto_smart_wait_repair_timeout_only_disabled_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "OK",
                "control-type": "button",
                "repair": "false",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_smart_wait_repair_timeout_only_disabled = next((branch for branch in auto_smart_wait_repair_timeout_only_disabled_branches if branch.get("id") == "smart_wait_click"), {})
        auto_smart_wait_repair_timeout_only_disabled_plan_summary = _batch_auto_plan_summary("click", auto_smart_wait_repair_timeout_only_disabled_branches)
        auto_selector_repair_disabled_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "batch_auto"},
                {
                    "kind": "click",
                    "hwnd": 1,
                    "name": "OK",
                    "automation-id": "okButton",
                    "control-type": "button",
                    "class-name": "Button",
                    "timeout": 0.1,
                    "selector-repair": "false",
                },
            )
        ]
        auto_native_repair_disabled_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "batch_auto"},
                {
                    "kind": "click",
                    "hwnd": 1,
                    "name": "OK",
                    "control-type": "button",
                    "layers": "native",
                    "native-selector-repair": "false",
                },
            )
        ]
        auto_uia_repair_disabled_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "batch_auto"},
                {
                    "kind": "click",
                    "hwnd": 1,
                    "name": "OK",
                    "automation-id": "okButton",
                    "control-type": "button",
                    "class-name": "Button",
                    "timeout": 0.1,
                    "uia-selector-repair": "false",
                },
            )
        ]
        auto_uia_repair_cell_disabled_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "batch_auto"},
                {
                    "kind": "cell",
                    "hwnd": 1,
                    "row": 2,
                    "column": 3,
                    "layers": "semantic",
                    "uia-selector-repair": "false",
                },
            )
        ]
        auto_visual_row_click_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "click",
                "hwnd": 1,
                "row-number": 16,
                "row-region": {"x": 0, "y": 40, "width": 80, "height": 400},
                "click-x": 320,
                "clicks": 2,
                "max-scrolls": 9,
                "capture-mode": "visible",
                "layers": "visual",
            },
        )
        auto_visual_row_click = next((branch for branch in auto_visual_row_click_branches if branch.get("id") == "visual_row_scroll_click"), {})
        auto_ocr_scroll_click_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "click",
                "hwnd": 1,
                "text": "Hidden Item",
                "max-scrolls": 6,
                "scroll-amount": 4,
                "scroll-x": 300,
                "scroll-y": 500,
                "pause": 0.1,
                "capture-mode": "visible",
                "layers": "visual",
            },
        )
        auto_ocr_scroll_click = next((branch for branch in auto_ocr_scroll_click_branches if branch.get("id") == "ocr_scroll_click"), {})
        auto_image_scroll_click_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "click",
                "hwnd": 1,
                "template-path": "hidden-icon.png",
                "confidence": 0.9,
                "max-scrolls": 5,
                "scroll-amount": 3,
                "scroll-x": 280,
                "scroll-y": 520,
                "capture-mode": "visible",
                "layers": "visual",
            },
        )
        auto_image_scroll_click = next((branch for branch in auto_image_scroll_click_branches if branch.get("id") == "image_scroll_click"), {})
        auto_visual_row_select_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {"kind": "select", "hwnd": 1, "row": 7, "layers": "visual"},
        )
        auto_visual_row_select = next((branch for branch in auto_visual_row_select_branches if branch.get("id") == "visual_row_select"), {})
        auto_visual_select_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "select",
                "hwnd": 1,
                "item": "Hidden Option",
                "template-path": "option-icon.png",
                "confidence": 0.91,
                "max-scrolls": 6,
                "scroll-amount": 4,
                "scroll-x": 300,
                "scroll-y": 500,
                "capture-mode": "visible",
                "layers": "visual",
            },
        )
        auto_visual_select_ids = [branch.get("id") for branch in auto_visual_select_branches]
        auto_visual_select_image = next((branch for branch in auto_visual_select_branches if branch.get("id") == "image_select"), {})
        auto_visual_select_image_scroll = next((branch for branch in auto_visual_select_branches if branch.get("id") == "image_scroll_select"), {})
        auto_visual_select_ocr = next((branch for branch in auto_visual_select_branches if branch.get("id") == "ocr_select"), {})
        auto_visual_select_ocr_scroll = next((branch for branch in auto_visual_select_branches if branch.get("id") == "ocr_scroll_select"), {})
        auto_visual_text_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "text",
                "hwnd": 1,
                "text": "typed value",
                "placeholder": "Search here",
                "template-path": "search-box.png",
                "confidence": 0.92,
                "max-scrolls": 4,
                "scroll-amount": 2,
                "scroll-x": 260,
                "scroll-y": 480,
                "capture-mode": "visible",
                "input-timeout": 0.7,
                "timeout-ms": 333,
                "verify": "false",
                "layers": "visual",
            },
        )
        auto_visual_text_ids = [branch.get("id") for branch in auto_visual_text_branches]
        auto_visual_text_image = next((branch for branch in auto_visual_text_branches if branch.get("id") == "image_text_input"), {})
        auto_visual_text_image_steps = auto_visual_text_image.get("steps") or []
        auto_visual_text_image_focus = auto_visual_text_image_steps[0] if len(auto_visual_text_image_steps) > 0 else {}
        auto_visual_text_image_input = auto_visual_text_image_steps[1] if len(auto_visual_text_image_steps) > 1 else {}
        auto_visual_text_image_scroll = next((branch for branch in auto_visual_text_branches if branch.get("id") == "image_scroll_text_input"), {})
        auto_visual_text_image_scroll_steps = auto_visual_text_image_scroll.get("steps") or []
        auto_visual_text_image_scroll_focus = auto_visual_text_image_scroll_steps[0] if len(auto_visual_text_image_scroll_steps) > 0 else {}
        auto_visual_text_ocr = next((branch for branch in auto_visual_text_branches if branch.get("id") == "ocr_text_input"), {})
        auto_visual_text_ocr_steps = auto_visual_text_ocr.get("steps") or []
        auto_visual_text_ocr_focus = auto_visual_text_ocr_steps[0] if len(auto_visual_text_ocr_steps) > 0 else {}
        auto_visual_text_ocr_input = auto_visual_text_ocr_steps[1] if len(auto_visual_text_ocr_steps) > 1 else {}
        auto_visual_text_ocr_scroll = next((branch for branch in auto_visual_text_branches if branch.get("id") == "ocr_scroll_text_input"), {})
        auto_visual_text_ocr_scroll_steps = auto_visual_text_ocr_scroll.get("steps") or []
        auto_visual_text_ocr_scroll_focus = auto_visual_text_ocr_scroll_steps[0] if len(auto_visual_text_ocr_scroll_steps) > 0 else {}
        auto_visual_text_desktop_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "text",
                "text": "global query",
                "placeholder": "Global Search",
                "desktop": True,
                "layers": "visual",
            },
        )
        auto_visual_text_desktop_ocr = next((branch for branch in auto_visual_text_desktop_branches if branch.get("id") == "ocr_text_input"), {})
        auto_visual_text_desktop_ocr_steps = auto_visual_text_desktop_ocr.get("steps") or []
        auto_visual_text_desktop_ocr_focus = auto_visual_text_desktop_ocr_steps[0] if len(auto_visual_text_desktop_ocr_steps) > 0 else {}
        auto_visual_text_desktop_ocr_input = auto_visual_text_desktop_ocr_steps[1] if len(auto_visual_text_desktop_ocr_steps) > 1 else {}
        auto_pre_visual_click_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "click",
                "hwnd": 1,
                "text": "OK",
                "template-path": "ok.png",
                "pre-visual-stable": "true",
                "pre-stable-timeout": 0.4,
                "pre-stable-interval": 0.08,
                "pre-stable-ticks": 3,
                "pre-stable-region": "1,2,300,220",
                "pre-stable-max-width": 80,
                "capture-mode": "visible",
                "layers": "visual",
            },
        )
        auto_pre_visual_click_image = next((branch for branch in auto_pre_visual_click_branches if branch.get("id") == "image_click"), {})
        auto_pre_visual_click_image_steps = auto_pre_visual_click_image.get("steps") or []
        auto_pre_visual_click_stable = auto_pre_visual_click_image_steps[0] if len(auto_pre_visual_click_image_steps) > 0 else {}
        auto_pre_visual_click_action = auto_pre_visual_click_image_steps[1] if len(auto_pre_visual_click_image_steps) > 1 else {}
        auto_pre_visual_dialog_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "dialog",
                "dialog-action-kind": "click",
                "text": "OK",
                "pre-visual-stable": "true",
                "pre-stable-timeout": 0.35,
                "layers": "visual",
            },
        )
        auto_pre_visual_dialog_ocr = next((branch for branch in auto_pre_visual_dialog_branches if branch.get("id") == "desktop_dialog_ocr"), {})
        auto_pre_visual_dialog_ocr_steps = auto_pre_visual_dialog_ocr.get("steps") or []
        auto_pre_visual_dialog_stable = auto_pre_visual_dialog_ocr_steps[0] if len(auto_pre_visual_dialog_ocr_steps) > 0 else {}
        auto_pre_visual_dialog_action = auto_pre_visual_dialog_ocr_steps[1] if len(auto_pre_visual_dialog_ocr_steps) > 1 else {}
        auto_pre_uia_click_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "Save",
                "control-type": "button",
                "timeout": 0.2,
                "pre-uia-stable": "true",
                "pre-uia-stable-timeout": 0.45,
                "pre-uia-stable-interval": 0.07,
                "pre-uia-stable-ticks": 3,
                "pre-uia-stable-max-depth": 6,
                "pre-uia-stable-max-elements": 120,
                "pre-uia-stable-view": "content",
                "pre-uia-stable-include-values": "true",
                "pre-uia-stable-rect-bucket": 4,
                "layers": "semantic",
            },
        )
        auto_pre_uia_click_smart = next((branch for branch in auto_pre_uia_click_branches if branch.get("id") == "smart_wait_click"), {})
        auto_pre_uia_click_smart_steps = auto_pre_uia_click_smart.get("steps") or []
        auto_pre_uia_click_stable = auto_pre_uia_click_smart_steps[0] if len(auto_pre_uia_click_smart_steps) > 0 else {}
        auto_pre_uia_click_action = auto_pre_uia_click_smart_steps[1] if len(auto_pre_uia_click_smart_steps) > 1 else {}
        auto_pre_uia_dialog_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "dialog",
                "dialog-action-kind": "click",
                "name": "Allow",
                "pre-uia-stable": "true",
                "pre-uia-stable-timeout": 0.5,
                "layers": "semantic",
            },
        )
        auto_pre_uia_dialog_uia = next((branch for branch in auto_pre_uia_dialog_branches if branch.get("id") == "desktop_dialog_uia"), {})
        auto_pre_uia_dialog_uia_steps = auto_pre_uia_dialog_uia.get("steps") or []
        auto_pre_uia_dialog_stable = auto_pre_uia_dialog_uia_steps[0] if len(auto_pre_uia_dialog_uia_steps) > 0 else {}
        auto_pre_uia_dialog_wait = auto_pre_uia_dialog_uia_steps[1] if len(auto_pre_uia_dialog_uia_steps) > 1 else {}
        auto_post_click_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "Play",
                "control-type": "button",
                "post-delay": 0.02,
                "post-stable": "true",
                "post-stable-ticks": 3,
                "post-stable-max-width": 96,
                "post-difference-threshold": 0.002,
                "post-pixel-threshold": 7,
                "post-stable-region": "10,20,300,220",
                "post-uia-stable": "true",
                "post-uia-stable-ticks": 2,
                "post-uia-stable-max-depth": 6,
                "post-uia-stable-max-elements": 160,
                "post-uia-stable-view": "content",
                "post-uia-stable-include-values": "true",
                "post-uia-stable-rect-bucket": 5,
                "verify-name": "Pause",
                "verify-control-type": "button",
                "verify-text": "Playing",
                "verify-image": "playing.png",
                "post-observe": "true",
                "post-timeout": 0.4,
                "post-interval": 0.05,
                "capture-mode": "visible",
                "layers": "semantic",
            },
        )
        auto_post_click_smart = next((branch for branch in auto_post_click_branches if branch.get("id") == "smart_click"), {})
        auto_post_click_steps = auto_post_click_smart.get("steps") or []
        auto_post_click_commands = [step.get("command") for step in auto_post_click_steps]
        auto_post_click_stable = auto_post_click_steps[2] if len(auto_post_click_steps) > 2 else {}
        auto_post_click_uia_stable = auto_post_click_steps[3] if len(auto_post_click_steps) > 3 else {}
        auto_post_click_plan_summary = _batch_auto_plan_summary("click", auto_post_click_branches)
        auto_post_absent_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "Close",
                "verify-absent-name": "Loading",
                "verify-absent-control-type": "text",
                "verify-absent-text": "Loading",
                "verify-absent-image": "spinner.png",
                "post-timeout": 0.3,
                "post-interval": 0.1,
                "capture-mode": "visible",
                "layers": "semantic",
            },
        )
        auto_post_absent_smart = next((branch for branch in auto_post_absent_branches if branch.get("id") == "smart_click"), {})
        auto_post_absent_steps = auto_post_absent_smart.get("steps") or []
        auto_post_absent_commands = [step.get("command") for step in auto_post_absent_steps]
        auto_post_absent_selector_loop = auto_post_absent_steps[1] if len(auto_post_absent_steps) > 1 else {}
        auto_post_absent_selector_probe = (auto_post_absent_selector_loop.get("steps") or [{}])[0]
        auto_post_absent_image_loop = auto_post_absent_steps[2] if len(auto_post_absent_steps) > 2 else {}
        auto_post_absent_image_probe = (auto_post_absent_image_loop.get("steps") or [{}])[0]
        auto_post_absent_text_loop = auto_post_absent_steps[3] if len(auto_post_absent_steps) > 3 else {}
        auto_post_absent_text_probe = (auto_post_absent_text_loop.get("steps") or [{}])[0]
        auto_post_absent_plan_summary = _batch_auto_plan_summary("click", auto_post_absent_branches)
        auto_post_pixel_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "click",
                "hwnd": 1,
                "name": "Toggle",
                "verify-pixel": {"x": 12, "y": 34, "color": "#00aa55", "tolerance": 6},
                "verify-absent-pixel": {"x": 12, "y": 34, "color": "#777777", "tolerance": 4},
                "post-timeout": 0.3,
                "post-interval": 0.1,
                "capture-mode": "visible",
                "layers": "semantic",
            },
        )
        auto_post_pixel_smart = next((branch for branch in auto_post_pixel_branches if branch.get("id") == "smart_click"), {})
        auto_post_pixel_steps = auto_post_pixel_smart.get("steps") or []
        auto_post_pixel_commands = [step.get("command") for step in auto_post_pixel_steps]
        auto_post_pixel_positive = auto_post_pixel_steps[1] if len(auto_post_pixel_steps) > 1 else {}
        auto_post_pixel_negative = auto_post_pixel_steps[2] if len(auto_post_pixel_steps) > 2 else {}
        auto_post_pixel_plan_summary = _batch_auto_plan_summary("click", auto_post_pixel_branches)
        auto_desktop_post_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "dialog",
                "text": "OK",
                "post-observe": "true",
                "verify-text": "Done",
                "include-screenshot": "false",
                "layers": "visual",
            },
        )
        auto_desktop_post_ocr = next((branch for branch in auto_desktop_post_branches if branch.get("id") == "desktop_dialog_ocr"), {})
        auto_desktop_post_steps = auto_desktop_post_ocr.get("steps") or []
        auto_desktop_post_commands = [step.get("command") for step in auto_desktop_post_steps]
        auto_desktop_absent_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "dialog",
                "text": "Cancel",
                "verify-absent-text": "Working",
                "verify-absent-name": "Progress",
                "desktop": True,
                "post-timeout": 0.2,
                "post-interval": 0.1,
                "layers": "visual",
            },
        )
        auto_desktop_absent_ocr = next((branch for branch in auto_desktop_absent_branches if branch.get("id") == "desktop_dialog_ocr"), {})
        auto_desktop_absent_steps = auto_desktop_absent_ocr.get("steps") or []
        auto_desktop_absent_commands = [step.get("command") for step in auto_desktop_absent_steps]
        auto_desktop_absent_selector_probe = ((auto_desktop_absent_steps[1] if len(auto_desktop_absent_steps) > 1 else {}).get("steps") or [{}])[0]
        auto_desktop_absent_text_probe = ((auto_desktop_absent_steps[2] if len(auto_desktop_absent_steps) > 2 else {}).get("steps") or [{}])[0]
        auto_desktop_pixel_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "dialog",
                "text": "OK",
                "post-stable": "true",
                "post-stable-ticks": 2,
                "post-uia-stable": "true",
                "post-uia-stable-max-depth": 3,
                "post-uia-stable-view": "control",
                "verify-pixel": {"x": 20, "y": 40, "color": "#00aa55"},
                "desktop": True,
                "layers": "visual",
            },
        )
        auto_desktop_pixel_ocr = next((branch for branch in auto_desktop_pixel_branches if branch.get("id") == "desktop_dialog_ocr"), {})
        auto_desktop_pixel_steps = auto_desktop_pixel_ocr.get("steps") or []
        auto_desktop_pixel_commands = [step.get("command") for step in auto_desktop_pixel_steps]
        auto_desktop_pixel_stable = auto_desktop_pixel_steps[1] if len(auto_desktop_pixel_steps) > 1 else {}
        auto_desktop_pixel_uia_stable = auto_desktop_pixel_steps[2] if len(auto_desktop_pixel_steps) > 2 else {}
        auto_visual_row_cell_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {"kind": "cell", "hwnd": 1, "row": 3, "action": "click", "layers": "visual"},
        )
        auto_visual_row_cell = next((branch for branch in auto_visual_row_cell_branches if branch.get("id") == "visual_row_cell"), {})
        auto_visual_row_disabled_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "auto_action"},
                {"kind": "click", "hwnd": 1, "row": 8, "layers": "visual", "visual-row-fallback": "false"},
            )
        ]
        visual_row_path_item = _batch_item_for_helper({"path": "/visual-row-scroll-click", "data": {"hwnd": 1, "row": 5}})
        auto_dialog_explicit = execute_batch([
            {
                "id": "auto_dialog_probe",
                "command": "batch_auto",
                "args": {"kind": "dialog", "dialog_action_kind": "click"},
                "branches": [
                    {"id": "related_dialog", "command": "unknown_dialog_semantic", "args": {}},
                    {
                        "id": "desktop_ocr",
                        "command": "batch_value",
                        "args": {"value": {"layer": "desktop_ocr"}},
                        "expect": {"path": "$result.value.layer", "equals": "desktop_ocr"},
                    },
                ],
                "expect": {"path": "$result.selected_id", "equals": "desktop_ocr"},
            },
        ], stop_on_error=True, trace=True)
        auto_dialog_branch_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "auto_action"},
                {
                    "kind": "dialog",
                    "hwnd": 1,
                    "dialog-title": "Confirm",
                    "name": "OK",
                    "text": "OK",
                    "template": "ok.png",
                    "x": 10,
                    "y": 20,
                    "timeout": 0.1,
                    "action-timeout": 0.1,
                },
            )
        ]
        auto_dialog_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "dialog",
                "hwnd": 1,
                "dialog-title": "Confirm",
                "name": "OK",
                "control-type": "button",
                "automation-id": "okButton",
                "text": "OK",
                "template-path": "ok.png",
                "x": 10,
                "y": 20,
                "timeout": 0.1,
                "action-timeout": 0.1,
            },
        )
        auto_dialog_command = next((branch for branch in auto_dialog_branches if branch.get("id") == "native_dialog_command"), {})
        auto_dialog_native = next((branch for branch in auto_dialog_branches if branch.get("id") == "native_dialog_button"), {})
        auto_dialog_smart = next((branch for branch in auto_dialog_branches if branch.get("id") == "smart_dialog"), {})
        auto_dialog_desktop = next((branch for branch in auto_dialog_branches if branch.get("id") == "desktop_dialog_uia"), {})
        auto_dialog_desktop_repair = next((branch for branch in auto_dialog_branches if branch.get("id") == "desktop_dialog_uia_selector_repair"), {})
        auto_dialog_desktop_repair_steps = auto_dialog_desktop_repair.get("steps") or []
        auto_dialog_desktop_repair_try = auto_dialog_desktop_repair_steps[1] if len(auto_dialog_desktop_repair_steps) > 1 else {}
        auto_dialog_desktop_repair_try_branches = auto_dialog_desktop_repair_try.get("branches") or []
        auto_dialog_desktop_repair_suggested = next((branch for branch in auto_dialog_desktop_repair_try_branches if branch.get("id") == "desktop_dialog_uia_selector_repair_suggested"), {})
        auto_dialog_desktop_repair_suggested_steps = auto_dialog_desktop_repair_suggested.get("steps") or []
        auto_dialog_ocr = next((branch for branch in auto_dialog_branches if branch.get("id") == "desktop_dialog_ocr"), {})
        auto_dialog_image = next((branch for branch in auto_dialog_branches if branch.get("id") == "desktop_dialog_image"), {})
        auto_dialog_coordinate = next((branch for branch in auto_dialog_branches if branch.get("id") == "desktop_dialog_coordinate"), {})
        auto_dialog_repair_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "dialog",
                "hwnd": 1,
                "dialog-action-kind": "select",
                "name": "Choices",
                "item": "Beta",
                "action-repair": "true",
                "action-repair-timeout": 0.0,
                "dialog-stable-ticks": 3,
                "layers": "semantic",
            },
        )
        auto_dialog_repair_smart = next((branch for branch in auto_dialog_repair_branches if branch.get("id") == "smart_dialog"), {})
        auto_dialog_repair_plan_summary = _batch_auto_plan_summary("dialog", auto_dialog_repair_branches)
        auto_dialog_repair_plan_smart = next((branch for branch in (auto_dialog_repair_plan_summary.get("branches") or []) if branch.get("id") == "smart_dialog"), {})
        auto_dialog_repair_plan_preview = (auto_dialog_repair_plan_smart.get("preview") or [{}])[0]
        auto_dialog_stable_alias_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "dialog",
                "hwnd": 1,
                "dialog-action-kind": "click",
                "name": "OK",
                "stable-ticks": 4,
                "layers": "semantic",
            },
        )
        auto_dialog_stable_alias_smart = next((branch for branch in auto_dialog_stable_alias_branches if branch.get("id") == "smart_dialog"), {})
        auto_dialog_uia_repair_alias_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "dialog",
                "hwnd": 1,
                "dialog-action-kind": "click",
                "name": "OK",
                "uia-selector-repair": "true",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_dialog_uia_repair_alias_smart = next((branch for branch in auto_dialog_uia_repair_alias_branches if branch.get("id") == "smart_dialog"), {})
        auto_dialog_uia_repair_alias_plan_summary = _batch_auto_plan_summary("dialog", auto_dialog_uia_repair_alias_branches)
        auto_dialog_repair_timeout_only_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "dialog",
                "hwnd": 1,
                "dialog-action-kind": "click",
                "name": "OK",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_dialog_repair_timeout_only_smart = next((branch for branch in auto_dialog_repair_timeout_only_branches if branch.get("id") == "smart_dialog"), {})
        auto_dialog_repair_timeout_only_plan_summary = _batch_auto_plan_summary("dialog", auto_dialog_repair_timeout_only_branches)
        auto_dialog_repair_timeout_only_disabled_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "dialog",
                "hwnd": 1,
                "dialog-action-kind": "click",
                "name": "OK",
                "repair": "false",
                "repair-timeout": 0.0,
                "layers": "semantic",
            },
        )
        auto_dialog_repair_timeout_only_disabled_smart = next((branch for branch in auto_dialog_repair_timeout_only_disabled_branches if branch.get("id") == "smart_dialog"), {})
        auto_dialog_repair_timeout_only_disabled_plan_summary = _batch_auto_plan_summary("dialog", auto_dialog_repair_timeout_only_disabled_branches)
        auto_file_dialog_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "file_dialog",
                "hwnd": 1,
                "file-dialog-action": "open",
                "file-dialog-path": "C:\\Temp\\demo.txt",
                "verify-close": "true",
                "timeout-ms": 666,
                "layers": "native",
            },
        )
        auto_file_dialog_branch_ids = [branch.get("id") for branch in auto_file_dialog_branches]
        auto_file_dialog = next((branch for branch in auto_file_dialog_branches if branch.get("id") == "file_dialog_action"), {})
        auto_file_dialog_info_branches = _batch_auto_branches(
            {"command": "batch_auto"},
            {
                "kind": "file_dialog",
                "hwnd": 1,
                "file-dialog-action": "info",
                "include-children": "true",
                "timeout-ms": 444,
                "layers": "native",
            },
        )
        auto_file_dialog_info = next((branch for branch in auto_file_dialog_info_branches if branch.get("id") == "file_dialog_info"), {})
        auto_window_plan = execute_batch([
            {
                "id": "auto_window_plan",
                "command": "batch_auto",
                "args": {
                    "kind": "window",
                    "name": "Demo App",
                    "process-name": "demo.exe",
                    "path-or-name": "demo.exe",
                    "timeout": 0.1,
                    "activate": "false",
                    "boundary": "false",
                    "plan-only": "true",
                },
                "expect": [
                    {"path": "$result.planned", "equals": True},
                    {"path": "$result.kind", "equals": "window"},
                    {"path": "$result.branches", "min_len": 3},
                    {"path": "$result.plan_summary.branch_count", "equals": 4},
                    {"path": "$result.plan_summary.has_window_selector_repair", "equals": True},
                    {"path": "$result.plan_summary.layers", "contains": "semantic"},
                    {"path": "$result.plan_summary.layers", "contains": "native"},
                ],
            },
        ], stop_on_error=True)
        auto_window_plan_summary = ((auto_window_plan.get("results") or [{}])[0].get("result") or {}).get("plan_summary") or {}
        auto_selector_repair_plan = execute_batch([
            {
                "id": "auto_selector_repair_plan",
                "command": "batch_auto",
                "args": {
                    "kind": "click",
                    "hwnd": 1,
                    "name": "OK",
                    "automation-id": "okButton",
                    "control-type": "button",
                    "class-name": "Button",
                    "timeout": 0.1,
                    "plan-only": "true",
                },
                "expect": [
                    {"path": "$result.planned", "equals": True},
                    {"path": "$result.plan_summary.has_selector_repair", "equals": True},
                    {"path": "$result.plan_summary.has_uia_selector_repair", "equals": True},
                    {"path": "$result.plan_summary.has_native_selector_repair", "equals": True},
                    {"path": "$result.plan_summary.branch_ids", "contains": "uia_click_selector_repair"},
                    {"path": "$result.plan_summary.branch_ids", "contains": "win32_click_selector_repair"},
                ],
            },
        ], stop_on_error=True)
        auto_selector_repair_plan_summary = ((auto_selector_repair_plan.get("results") or [{}])[0].get("result") or {}).get("plan_summary") or {}
        auto_cell_selector_repair_plan = execute_batch([
            {
                "id": "auto_cell_selector_repair_plan",
                "command": "batch_auto",
                "args": {
                    "kind": "cell",
                    "hwnd": 1,
                    "row": 2,
                    "column": 3,
                    "column-name": "State",
                    "action": "get",
                    "layers": "semantic",
                    "plan-only": "true",
                },
                "expect": [
                    {"path": "$result.planned", "equals": True},
                    {"path": "$result.plan_summary.has_selector_repair", "equals": True},
                    {"path": "$result.plan_summary.has_uia_selector_repair", "equals": True},
                    {"path": "$result.plan_summary.branch_ids", "contains": "uia_cell_selector_repair"},
                    {"path": "$result.plan_summary.layers", "contains": "semantic"},
                ],
            },
        ], stop_on_error=True)
        auto_cell_selector_repair_plan_summary = ((auto_cell_selector_repair_plan.get("results") or [{}])[0].get("result") or {}).get("plan_summary") or {}
        auto_window_branch_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "auto_action"},
                {
                    "kind": "window",
                    "name": "Demo App",
                    "process-name": "demo.exe",
                    "path-or-name": "demo.exe",
                    "timeout": 0.1,
                    "activate": "false",
                    "boundary": "false",
                    "helper-status": "false",
                    "observe-window": "true",
                    "include-a11y": "false",
                    "ocr": "false",
                },
            )
        ]
        auto_window_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "window",
                "name": "Demo App",
                "process-name": "demo.exe",
                "path-or-name": "demo.exe",
                "timeout": 0.1,
                "activate": "false",
                "boundary": "false",
                "observe-window": "true",
                "include-a11y": "false",
                "ocr": "false",
            },
        )
        auto_window_smart = next((branch for branch in auto_window_branches if branch.get("id") == "auto_window"), {})
        auto_window_wait = next((branch for branch in auto_window_branches if branch.get("id") == "wait_window"), {})
        auto_window_repair = next((branch for branch in auto_window_branches if branch.get("id") == "window_selector_repair"), {})
        auto_window_launch = next((branch for branch in auto_window_branches if branch.get("id") == "launch_window"), {})
        auto_window_wait_steps = auto_window_wait.get("steps") or []
        auto_window_repair_steps = auto_window_repair.get("steps") or []
        auto_window_repair_pick = auto_window_repair_steps[1] if len(auto_window_repair_steps) > 1 else {}
        auto_window_repair_pick_branches = auto_window_repair_pick.get("branches") or []
        auto_window_repair_direct = next((branch for branch in auto_window_repair_pick_branches if branch.get("id") == "window_selector_repair_direct"), {})
        auto_window_repair_suggested = next((branch for branch in auto_window_repair_pick_branches if branch.get("id") == "window_selector_repair_suggested"), {})
        auto_window_repair_suggested_steps = auto_window_repair_suggested.get("steps") or []
        auto_window_repair_suggested_find = auto_window_repair_suggested_steps[0] if auto_window_repair_suggested_steps else {}
        auto_window_launch_steps = auto_window_launch.get("steps") or []
        auto_window_helper_branches = _batch_auto_branches(
            {"command": "auto_action"},
            {
                "kind": "window",
                "name": "Demo App",
                "process-name": "demo.exe",
                "path-or-name": "demo.exe",
                "timeout": 0.1,
                "activate": "false",
                "boundary": "false",
                "helper-status": "true",
                "layers": "semantic native input",
            },
        )
        auto_window_helper_smart = next((branch for branch in auto_window_helper_branches if branch.get("id") == "auto_window"), {})
        auto_window_helper_wait = next((branch for branch in auto_window_helper_branches if branch.get("id") == "wait_window"), {})
        auto_window_helper_launch = next((branch for branch in auto_window_helper_branches if branch.get("id") == "launch_window"), {})
        auto_window_helper_wait_steps = auto_window_helper_wait.get("steps") or []
        auto_window_helper_launch_steps = auto_window_helper_launch.get("steps") or []
        auto_window_helper_wait_boundary = next((step for step in auto_window_helper_wait_steps if step.get("id") == "window_boundary"), {})
        auto_window_helper_wait_helper = next((step for step in auto_window_helper_wait_steps if step.get("id") == "window_helper"), {})
        auto_window_helper_launch_boundary = next((step for step in auto_window_helper_launch_steps if step.get("id") == "launch_boundary"), {})
        auto_window_helper_launch_helper = next((step for step in auto_window_helper_launch_steps if step.get("id") == "launch_helper"), {})
        auto_window_action_plan = execute_batch([
            {
                "id": "auto_window_action_plan",
                "command": "batch_auto",
                "args": {
                    "kind": "window_action",
                    "action-kind": "click",
                    "window-title": "Demo App",
                    "process-name": "demo.exe",
                    "path-or-name": "demo.exe",
                    "name": "Play",
                    "control-type": "button",
                    "timeout": 0.1,
                    "action-timeout": 0.2,
                    "activate": "false",
                    "boundary": "false",
                    "plan-only": "true",
                },
                "expect": [
                    {"path": "$result.planned", "equals": True},
                    {"path": "$result.kind", "equals": "window_action"},
                    {"path": "$result.branches", "min_len": 3},
                    {"path": "$result.plan_summary.branch_count", "equals": 4},
                    {"path": "$result.plan_summary.has_window_selector_repair", "equals": True},
                    {"path": "$result.plan_summary.commands", "contains": "batch_try"},
                    {"path": "$result.plan_summary.has_wait", "equals": True},
                ],
            },
        ], stop_on_error=True)
        auto_window_action_plan_summary = ((auto_window_action_plan.get("results") or [{}])[0].get("result") or {}).get("plan_summary") or {}
        auto_window_action_preflight_plan = execute_batch([
            {
                "id": "auto_window_action_preflight_plan",
                "command": "batch_auto",
                "args": {
                    "kind": "window_action",
                    "action-kind": "click",
                    "window-title": "Demo App",
                    "process-name": "demo.exe",
                    "name": "Play",
                    "control-type": "button",
                    "timeout": 0.1,
                    "action-timeout": 0.2,
                    "activate": "false",
                    "boundary": "false",
                    "pre-boundary": "true",
                    "pre-helper": "true",
                    "window-layers": "semantic",
                    "action-layers": "semantic",
                    "plan-only": "true",
                },
                "expect": [
                    {"path": "$result.planned", "equals": True},
                    {"path": "$result.plan_summary.has_boundary_preflight", "equals": True},
                    {"path": "$result.plan_summary.has_conditional_helper", "equals": True},
                    {"path": "$result.plan_summary.commands", "contains": "control_boundary"},
                    {"path": "$result.plan_summary.commands", "contains": "helper_status"},
                ],
            },
        ], stop_on_error=True)
        auto_window_action_preflight_plan_summary = ((auto_window_action_preflight_plan.get("results") or [{}])[0].get("result") or {}).get("plan_summary") or {}
        auto_window_action_preflight_branches = _batch_auto_branches(
            {"command": "app_action"},
            {
                "action-kind": "click",
                "window-title": "Demo App",
                "process-name": "demo.exe",
                "name": "Play",
                "control-type": "button",
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "pre-boundary": "true",
                "pre-helper": "true",
                "window-layers": "semantic",
                "action-layers": "semantic",
            },
        )
        auto_window_action_preflight_auto = next((branch for branch in auto_window_action_preflight_branches if branch.get("id") == "auto_window_click"), {})
        auto_window_action_preflight_steps = auto_window_action_preflight_auto.get("steps") or []
        auto_window_action_preflight_boundary = next((step for step in auto_window_action_preflight_steps if step.get("id") == "auto_window_pre_boundary"), {})
        auto_window_action_preflight_helper = next((step for step in auto_window_action_preflight_steps if step.get("id") == "auto_window_pre_helper"), {})
        auto_window_action_preflight_action = next((step for step in auto_window_action_preflight_steps if step.get("id") == "click_action"), {})
        risky_plan_summary = _batch_auto_plan_summary(
            "click",
            _batch_auto_branches(
                {"command": "batch_auto"},
                {
                    "kind": "click",
                    "name": "Delete",
                    "x": 10,
                    "y": 20,
                    "layers": "semantic input",
                },
            ),
        )
        manual_plan_summary = _batch_auto_plan_summary(
            "manual",
            [
                {
                    "id": "manual",
                    "steps": [
                        {
                            "id": "manual_smart_wait",
                            "command": "smart_wait_click",
                            "args": {"hwnd": 1, "name": "OK", "repair-timeout": 0.0, "allow-suggestion-index": "true"},
                        },
                        {
                            "id": "manual_dialog",
                            "command": "smart_dialog_action",
                            "args": {"hwnd": 1, "name": "Allow", "action-kind": "click", "repair-timeout": 0.0},
                        },
                        {
                            "id": "manual_native_wait",
                            "command": "win32_control_wait",
                            "args": {"hwnd": 1, "state": "present", "text": "Ready", "native-wait-repair-timeout": 0.0},
                        },
                    ],
                }
            ],
        )
        manual_plan_summary_disabled = _batch_auto_plan_summary(
            "manual",
            [
                {
                    "id": "manual_disabled",
                    "steps": [
                        {
                            "id": "manual_smart_wait_disabled",
                            "command": "smart_wait_click",
                            "args": {"hwnd": 1, "name": "OK", "repair": "false", "repair-timeout": 0.0},
                        },
                        {
                            "id": "manual_dialog_disabled",
                            "command": "smart_dialog_action",
                            "args": {"hwnd": 1, "name": "Allow", "repair": "false", "repair-timeout": 0.0},
                        },
                        {
                            "id": "manual_native_wait_disabled",
                            "command": "win32_control_wait",
                            "args": {"hwnd": 1, "state": "present", "text": "Ready", "native-wait-repair": "false", "native-wait-repair-timeout": 0.0},
                        },
                    ],
                }
            ],
        )
        manual_plan_preview = ((manual_plan_summary.get("branches") or [{}])[0].get("preview") or [{}])[0]
        auto_window_action_branch_ids = [
            branch.get("id")
            for branch in _batch_auto_branches(
                {"command": "app_action"},
                {
                    "action-kind": "click",
                    "window-title": "Demo App",
                    "process-name": "demo.exe",
                    "path-or-name": "demo.exe",
                    "name": "Play",
                    "control-type": "button",
                    "template-path": "play.png",
                    "x": 10,
                    "y": 20,
                    "timeout": 0.1,
                    "action-timeout": 0.2,
                    "activate": "false",
                    "boundary": "false",
                    "window-layers": "semantic native input",
                    "action-layers": "semantic visual input",
                },
            )
        ]
        auto_window_action_branches = _batch_auto_branches(
            {"command": "app_action"},
            {
                "action-kind": "click",
                "window-title": "Demo App",
                "process-name": "demo.exe",
                "path-or-name": "demo.exe",
                "name": "Play",
                "control-type": "button",
                "template-path": "play.png",
                "x": 10,
                "y": 20,
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "sequence-focus": "true",
                "step-delay": 0.05,
                "window-layers": "semantic native input",
                "action-layers": "semantic visual input",
            },
        )
        auto_window_action_auto = next((branch for branch in auto_window_action_branches if branch.get("id") == "auto_window_click"), {})
        auto_window_action_wait = next((branch for branch in auto_window_action_branches if branch.get("id") == "wait_window_click"), {})
        auto_window_action_launch = next((branch for branch in auto_window_action_branches if branch.get("id") == "launch_window_click"), {})
        auto_window_action_auto_steps = auto_window_action_auto.get("steps") or []
        auto_window_action_action_try = next((step for step in auto_window_action_auto_steps if step.get("id") == "click_action"), {})
        auto_window_action_inner_branches = auto_window_action_action_try.get("branches") or []
        auto_window_action_smart = next((branch for branch in auto_window_action_inner_branches if branch.get("id") == "click_smart_wait_click"), {})
        auto_window_action_image = next((branch for branch in auto_window_action_inner_branches if branch.get("id") == "click_image_click"), {})
        auto_window_action_coordinate = next((branch for branch in auto_window_action_inner_branches if branch.get("id") == "click_coordinate_click"), {})
        auto_window_action_text_branches = _batch_auto_branches(
            {"path": "/app-action"},
            {
                "action-kind": "text",
                "window-title": "Demo App",
                "path-or-name": "demo.exe",
                "name": "Search",
                "text": "query",
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "action-layers": "semantic input",
            },
        )
        auto_window_action_text_auto = next((branch for branch in auto_window_action_text_branches if branch.get("id") == "auto_window_text"), {})
        auto_window_action_text_try = next((step for step in (auto_window_action_text_auto.get("steps") or []) if step.get("id") == "text_action"), {})
        auto_window_action_text_inner = auto_window_action_text_try.get("branches") or []
        auto_window_action_text_smart = next((branch for branch in auto_window_action_text_inner if branch.get("id") == "text_smart_wait_text"), {})
        auto_window_action_repair_no_timeout_branches = _batch_auto_branches(
            {"command": "app_action"},
            {
                "action-kind": "click",
                "window-title": "Demo App",
                "process-name": "demo.exe",
                "name": "Play",
                "control-type": "button",
                "window-timeout": 0.1,
                "repair": "true",
                "repair-timeout": 0.0,
                "activate": "false",
                "boundary": "false",
                "window-layers": "semantic",
                "action-layers": "semantic",
            },
        )
        auto_window_action_repair_no_timeout_auto = next((branch for branch in auto_window_action_repair_no_timeout_branches if branch.get("id") == "auto_window_click"), {})
        auto_window_action_repair_no_timeout_steps = auto_window_action_repair_no_timeout_auto.get("steps") or []
        auto_window_action_repair_no_timeout_try = next((step for step in auto_window_action_repair_no_timeout_steps if step.get("id") == "click_action"), {})
        auto_window_action_repair_no_timeout_smart = next((branch for branch in (auto_window_action_repair_no_timeout_try.get("branches") or []) if branch.get("id") == "click_smart_wait_click"), {})
        auto_window_action_repair_no_timeout_plan_summary = _batch_auto_plan_summary("window_action", auto_window_action_repair_no_timeout_branches)
        auto_window_action_key_branches = _batch_auto_branches(
            {"command": "app_action"},
            {
                "action-kind": "key",
                "window-title": "Demo App",
                "path-or-name": "demo.exe",
                "keys": "ctrl+s",
                "verify-name": "Saved",
                "post-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "action-layers": "input",
            },
        )
        auto_window_action_key_branch_ids = [branch.get("id") for branch in auto_window_action_key_branches]
        auto_window_action_key_auto = next((branch for branch in auto_window_action_key_branches if branch.get("id") == "auto_window_key"), {})
        auto_window_action_key_try = next((step for step in (auto_window_action_key_auto.get("steps") or []) if step.get("id") == "key_action"), {})
        auto_window_action_key_inner = auto_window_action_key_try.get("branches") or []
        auto_window_action_key_branch = next((branch for branch in auto_window_action_key_inner if branch.get("id") == "key_key_input"), {})
        auto_window_action_key_steps = auto_window_action_key_branch.get("steps") or []
        auto_window_action_key_input = auto_window_action_key_steps[0] if len(auto_window_action_key_steps) > 0 else {}
        auto_window_action_key_post = auto_window_action_key_steps[1] if len(auto_window_action_key_steps) > 1 else {}
        auto_window_action_menu_branches = _batch_auto_branches(
            {"command": "app_action"},
            {
                "action-kind": "menu",
                "window-title": "Demo App",
                "path-or-name": "demo.exe",
                "menu-path": ["File", "Save"],
                "activate": "false",
                "boundary": "false",
                "action-layers": "native",
            },
        )
        auto_window_action_menu_branch_ids = [branch.get("id") for branch in auto_window_action_menu_branches]
        auto_window_action_menu_auto = next((branch for branch in auto_window_action_menu_branches if branch.get("id") == "auto_window_menu"), {})
        auto_window_action_menu_action = next((step for step in (auto_window_action_menu_auto.get("steps") or []) if step.get("id") == "menu_action"), {})
        auto_window_action_file_dialog_branches = _batch_auto_branches(
            {"command": "app_action"},
            {
                "action-kind": "file_dialog",
                "window-title": "Demo App",
                "path-or-name": "demo.exe",
                "file-dialog-action": "save",
                "file-dialog-path": "C:\\Temp\\demo.txt",
                "verify-close": "true",
                "activate": "false",
                "boundary": "false",
                "action-layers": "native",
            },
        )
        auto_window_action_file_dialog_branch_ids = [branch.get("id") for branch in auto_window_action_file_dialog_branches]
        auto_window_action_file_dialog_auto = next((branch for branch in auto_window_action_file_dialog_branches if branch.get("id") == "auto_window_file_dialog"), {})
        auto_window_action_file_dialog_action = next((step for step in (auto_window_action_file_dialog_auto.get("steps") or []) if step.get("id") == "file_dialog_action"), {})
        auto_window_action_recover_branches = _batch_auto_branches(
            {"command": "app_action"},
            {
                "action-kind": "click",
                "window-title": "Demo App",
                "path-or-name": "demo.exe",
                "name": "Play",
                "control-type": "button",
                "template-path": "play.png",
                "x": 10,
                "y": 20,
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "auto-recover": "true",
                "window-layers": "semantic native input",
                "action-layers": "semantic visual input",
            },
        )
        auto_window_action_recover_auto = next((branch for branch in auto_window_action_recover_branches if branch.get("id") == "auto_window_click"), {})
        auto_window_action_recover_steps = auto_window_action_recover_auto.get("steps") or []
        auto_window_action_recover_try = next((step for step in auto_window_action_recover_steps if step.get("id") == "click_action"), {})
        auto_window_action_recover_policy = auto_window_action_recover_try.get("recover_on_failure") or {}
        auto_window_action_recover_selector = auto_window_action_recover_policy.get("selector") or []
        auto_window_action_recover_selector_stable = next((step for step in auto_window_action_recover_selector if step.get("id") == "recover_uia_stable"), {})
        auto_window_action_recover_visual = auto_window_action_recover_policy.get("visual") or []
        auto_window_action_recover_visual_stable = next((step for step in auto_window_action_recover_visual if step.get("id") == "recover_visual_stable"), {})
        auto_window_action_recover_timeout = auto_window_action_recover_policy.get("timeout") or []
        auto_window_action_recover_timeout_uia = next((step for step in auto_window_action_recover_timeout if step.get("id") == "recover_uia_stable"), {})
        auto_window_action_recover_timeout_visual = next((step for step in auto_window_action_recover_timeout if step.get("id") == "recover_visual_stable"), {})
        auto_window_action_recover_plan_summary = _batch_auto_plan_summary("window_action", auto_window_action_recover_branches)
        auto_window_action_text_recover_branches = _batch_auto_branches(
            {"command": "app_action"},
            {
                "action-kind": "text",
                "window-title": "Demo App",
                "path-or-name": "demo.exe",
                "name": "Search",
                "text": "query",
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "auto-recover": "true",
                "action-layers": "input",
            },
        )
        auto_window_action_text_recover_auto = next((branch for branch in auto_window_action_text_recover_branches if branch.get("id") == "auto_window_text"), {})
        auto_window_action_text_recover_steps = auto_window_action_text_recover_auto.get("steps") or []
        auto_window_action_text_recover_try = next((step for step in auto_window_action_text_recover_steps if step.get("id") == "text_action"), {})
        auto_window_action_text_recover_policy = auto_window_action_text_recover_try.get("recover_on_failure") or {}
        auto_window_action_text_recover_clipboard = auto_window_action_text_recover_policy.get("clipboard_restore") or []
        auto_window_action_text_recover_clipboard_focus = next((step for step in auto_window_action_text_recover_clipboard if step.get("id") == "recover_focus"), {})
        auto_window_action_text_recover_clipboard_input = next((step for step in auto_window_action_text_recover_clipboard if step.get("id") == "recover_clipboard_focused_input"), {})
        auto_window_action_text_recover_plan_summary = _batch_auto_plan_summary("window_action", auto_window_action_text_recover_branches)
        auto_window_sequence_plan = execute_batch([
            {
                "id": "auto_window_sequence_plan",
                "command": "batch_auto",
                "args": {
                    "kind": "window_sequence",
                    "window-title": "Demo App",
                    "process-name": "demo.exe",
                    "path-or-name": "demo.exe",
                    "steps": [
                        {"id": "search", "kind": "text", "name": "Search", "text": "query"},
                        {"id": "play", "kind": "click", "name": "Play", "control-type": "button"},
                    ],
                    "timeout": 0.1,
                    "action-timeout": 0.2,
                    "activate": "false",
                    "boundary": "false",
                    "plan-only": "true",
                },
                "expect": [
                    {"path": "$result.planned", "equals": True},
                    {"path": "$result.kind", "equals": "window_sequence"},
                    {"path": "$result.branches", "min_len": 3},
                    {"path": "$result.plan_summary.branch_count", "equals": 4},
                    {"path": "$result.plan_summary.has_window_selector_repair", "equals": True},
                    {"path": "$result.plan_summary.commands", "contains": "batch_try"},
                    {"path": "$result.plan_summary.layers", "contains": "semantic"},
                ],
            },
        ], stop_on_error=True)
        auto_window_sequence_plan_summary = ((auto_window_sequence_plan.get("results") or [{}])[0].get("result") or {}).get("plan_summary") or {}
        auto_window_sequence_preflight_branches = _batch_auto_branches(
            {"command": "app_sequence"},
            {
                "window-title": "Demo App",
                "process-name": "demo.exe",
                "steps": [
                    {"id": "play", "kind": "click", "name": "Play", "control-type": "button"},
                ],
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "pre-boundary": "true",
                "pre-helper": "true",
                "window-layers": "semantic",
                "action-layers": "semantic",
            },
        )
        auto_window_sequence_preflight_plan_summary = _batch_auto_plan_summary("window_sequence", auto_window_sequence_preflight_branches)
        auto_window_sequence_preflight_auto = next((branch for branch in auto_window_sequence_preflight_branches if branch.get("id") == "auto_window_sequence"), {})
        auto_window_sequence_preflight_steps = auto_window_sequence_preflight_auto.get("steps") or []
        auto_window_sequence_preflight_boundary = next((step for step in auto_window_sequence_preflight_steps if step.get("id") == "auto_window_pre_boundary"), {})
        auto_window_sequence_preflight_helper = next((step for step in auto_window_sequence_preflight_steps if step.get("id") == "auto_window_pre_helper"), {})
        auto_window_sequence_preflight_play = next((step for step in auto_window_sequence_preflight_steps if step.get("id") == "play"), {})
        auto_window_sequence_branches = _batch_auto_branches(
            {"command": "app_sequence"},
            {
                "window-title": "Demo App",
                "process-name": "demo.exe",
                "path-or-name": "demo.exe",
                "steps": [
                    {"id": "search", "kind": "text", "name": "Search", "text": "query"},
                    {"id": "play", "kind": "click", "name": "Play", "control-type": "button", "template-path": "play.png"},
                    {"id": "save_key", "command": "key", "args": {"keys": "ctrl+s"}},
                ],
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "sequence-focus": "true",
                "step-delay": 0.05,
                "window-layers": "semantic native input",
                "action-layers": "semantic visual input",
            },
        )
        auto_window_sequence_branch_ids = [branch.get("id") for branch in auto_window_sequence_branches]
        auto_window_sequence_auto = next((branch for branch in auto_window_sequence_branches if branch.get("id") == "auto_window_sequence"), {})
        auto_window_sequence_wait = next((branch for branch in auto_window_sequence_branches if branch.get("id") == "wait_window_sequence"), {})
        auto_window_sequence_launch = next((branch for branch in auto_window_sequence_branches if branch.get("id") == "launch_window_sequence"), {})
        auto_window_sequence_steps = auto_window_sequence_auto.get("steps") or []
        auto_window_sequence_search = next((step for step in auto_window_sequence_steps if step.get("id") == "search"), {})
        auto_window_sequence_play = next((step for step in auto_window_sequence_steps if step.get("id") == "play"), {})
        auto_window_sequence_key = next((step for step in auto_window_sequence_steps if step.get("id") == "save_key"), {})
        auto_window_sequence_focus1 = next((step for step in auto_window_sequence_steps if step.get("id") == "sequence_1_focus"), {})
        auto_window_sequence_focus2 = next((step for step in auto_window_sequence_steps if step.get("id") == "sequence_2_focus"), {})
        auto_window_sequence_delay1 = next((step for step in auto_window_sequence_steps if step.get("id") == "sequence_1_delay"), {})
        auto_window_sequence_delay2 = next((step for step in auto_window_sequence_steps if step.get("id") == "sequence_2_delay"), {})
        auto_window_sequence_search_branch = next((branch for branch in (auto_window_sequence_search.get("branches") or []) if branch.get("id") == "step1_smart_wait_text"), {})
        auto_window_sequence_play_branch = next((branch for branch in (auto_window_sequence_play.get("branches") or []) if branch.get("id") == "step2_smart_wait_click"), {})
        auto_window_sequence_repair_branches = _batch_auto_branches(
            {"command": "app_sequence"},
            {
                "window-title": "Demo App",
                "process-name": "demo.exe",
                "steps": [
                    {"id": "play", "kind": "click", "name": "Play", "control-type": "button"},
                ],
                "timeout": 0.1,
                "action-timeout": 0.2,
                "repair": "true",
                "repair-timeout": 0.0,
                "activate": "false",
                "boundary": "false",
                "window-layers": "semantic",
                "action-layers": "semantic",
            },
        )
        auto_window_sequence_repair_auto = next((branch for branch in auto_window_sequence_repair_branches if branch.get("id") == "auto_window_sequence"), {})
        auto_window_sequence_repair_steps = auto_window_sequence_repair_auto.get("steps") or []
        auto_window_sequence_repair_play = next((step for step in auto_window_sequence_repair_steps if step.get("id") == "play"), {})
        auto_window_sequence_repair_play_branch = next((branch for branch in (auto_window_sequence_repair_play.get("branches") or []) if branch.get("id") == "step1_smart_wait_click"), {})
        auto_window_sequence_repair_plan_summary = _batch_auto_plan_summary("window_sequence", auto_window_sequence_repair_branches)
        auto_window_sequence_auto_kind_branches = _batch_auto_branches(
            {"command": "app_sequence"},
            {
                "window-title": "Demo App",
                "path-or-name": "demo.exe",
                "steps": [
                    {"id": "shortcut", "kind": "key", "keys": "ctrl+f"},
                    {"id": "wheel", "kind": "scroll", "x": 10, "y": 20, "dy": -2},
                    {"id": "drag_it", "kind": "drag", "start-x": 1, "start-y": 2, "end-x": 30, "end-y": 40},
                    {"id": "open_menu", "kind": "menu", "menu-path": ["File", "Open"]},
                    {"id": "open_file", "kind": "file_dialog", "file-dialog-action": "open", "file-dialog-path": "C:\\Temp\\open.txt", "verify-close": "true"},
                ],
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "action-layers": "input native",
            },
        )
        auto_window_sequence_auto_kind = next((branch for branch in auto_window_sequence_auto_kind_branches if branch.get("id") == "auto_window_sequence"), {})
        auto_window_sequence_auto_kind_steps = auto_window_sequence_auto_kind.get("steps") or []
        auto_window_sequence_auto_kind_shortcut = next((step for step in auto_window_sequence_auto_kind_steps if step.get("id") == "shortcut"), {})
        auto_window_sequence_auto_kind_wheel = next((step for step in auto_window_sequence_auto_kind_steps if step.get("id") == "wheel"), {})
        auto_window_sequence_auto_kind_drag = next((step for step in auto_window_sequence_auto_kind_steps if step.get("id") == "drag_it"), {})
        auto_window_sequence_auto_kind_menu = next((step for step in auto_window_sequence_auto_kind_steps if step.get("id") == "open_menu"), {})
        auto_window_sequence_auto_kind_file_dialog = next((step for step in auto_window_sequence_auto_kind_steps if step.get("id") == "open_file"), {})
        auto_window_sequence_auto_kind_shortcut_branch = next((branch for branch in (auto_window_sequence_auto_kind_shortcut.get("branches") or []) if branch.get("id") == "step1_key_input"), {})
        auto_window_sequence_auto_kind_wheel_branch = next((branch for branch in (auto_window_sequence_auto_kind_wheel.get("branches") or []) if branch.get("id") == "step2_wheel_scroll"), {})
        auto_window_sequence_auto_kind_drag_branch = next((branch for branch in (auto_window_sequence_auto_kind_drag.get("branches") or []) if branch.get("id") == "step3_coordinate_drag"), {})
        auto_window_sequence_auto_kind_menu_branch = next((branch for branch in (auto_window_sequence_auto_kind_menu.get("branches") or []) if branch.get("id") == "step4_menu_action"), {})
        auto_window_sequence_auto_kind_file_dialog_branch = next((branch for branch in (auto_window_sequence_auto_kind_file_dialog.get("branches") or []) if branch.get("id") == "step5_file_dialog_action"), {})
        auto_window_sequence_auto_kind_shortcut_action = (auto_window_sequence_auto_kind_shortcut_branch.get("steps") or [{}])[0]
        auto_window_sequence_auto_kind_wheel_action = (auto_window_sequence_auto_kind_wheel_branch.get("steps") or [{}])[0]
        auto_window_sequence_auto_kind_drag_action = (auto_window_sequence_auto_kind_drag_branch.get("steps") or [{}])[0]
        auto_window_sequence_auto_kind_menu_action = (auto_window_sequence_auto_kind_menu_branch.get("steps") or [{}])[0]
        auto_window_sequence_auto_kind_file_dialog_action = (auto_window_sequence_auto_kind_file_dialog_branch.get("steps") or [{}])[0]
        auto_window_sequence_autorecover_branches = _batch_auto_branches(
            {"command": "app-sequence"},
            {
                "window-title": "Demo App",
                "process-name": "demo.exe",
                "path-or-name": "demo.exe",
                "steps": [
                    {"id": "search", "kind": "text", "name": "Search", "text": "query"},
                    {"id": "play", "kind": "click", "name": "Play", "control-type": "button", "template-path": "play.png"},
                ],
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "auto-recover": "true",
                "window-layers": "semantic native input",
                "action-layers": "semantic visual input",
            },
        )
        auto_window_sequence_autorecover_auto = next((branch for branch in auto_window_sequence_autorecover_branches if branch.get("id") == "auto_window_sequence"), {})
        auto_window_sequence_autorecover_steps = auto_window_sequence_autorecover_auto.get("steps") or []
        auto_window_sequence_autorecover_search = next((step for step in auto_window_sequence_autorecover_steps if step.get("id") == "search"), {})
        auto_window_sequence_autorecover_play = next((step for step in auto_window_sequence_autorecover_steps if step.get("id") == "play"), {})
        auto_window_sequence_autorecover_plan_summary = _batch_auto_plan_summary("window_sequence", auto_window_sequence_autorecover_branches)
        auto_window_sequence_recovery_branches = _batch_auto_branches(
            {"command": "app-sequence"},
            {
                "window-title": "Demo App",
                "process-name": "demo.exe",
                "path-or-name": "demo.exe",
                "steps": [
                    {"id": "search", "kind": "text", "name": "Search", "text": "query"},
                    {
                        "id": "play",
                        "kind": "click",
                        "name": "Play",
                        "control-type": "button",
                        "on-step-failure": [
                            {"id": "close_popup", "kind": "dialog", "name": "OK"},
                        ],
                    },
                ],
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "recovery-delay": 0.03,
                "sequence-recovery-focus": "true",
                "window-layers": "semantic native input",
                "action-layers": "semantic visual input",
            },
        )
        auto_window_sequence_recovery_auto = next((branch for branch in auto_window_sequence_recovery_branches if branch.get("id") == "auto_window_sequence"), {})
        auto_window_sequence_recovery_steps = auto_window_sequence_recovery_auto.get("steps") or []
        auto_window_sequence_recovery_play = next((step for step in auto_window_sequence_recovery_steps if step.get("id") == "play"), {})
        auto_window_sequence_recovery_primary = next((branch for branch in (auto_window_sequence_recovery_play.get("branches") or []) if branch.get("id") == "play_primary"), {})
        auto_window_sequence_recovery_branch = next((branch for branch in (auto_window_sequence_recovery_play.get("branches") or []) if branch.get("id") == "play_recover"), {})
        auto_window_sequence_recovery_branch_steps = auto_window_sequence_recovery_branch.get("steps") or []
        auto_window_sequence_recovery_focus = next((step for step in auto_window_sequence_recovery_branch_steps if step.get("id") == "sequence_2_recovery_focus"), {})
        auto_window_sequence_recovery_dialog = next((step for step in auto_window_sequence_recovery_branch_steps if str(step.get("id") or "").startswith("sequence_2_recovery_1_")), {})
        auto_window_sequence_recovery_delay = next((step for step in auto_window_sequence_recovery_branch_steps if step.get("id") == "sequence_2_recovery_delay"), {})
        auto_window_sequence_recovery_retry = next((step for step in auto_window_sequence_recovery_branch_steps if step.get("id") == "play_retry"), {})
        auto_window_sequence_recovery_retry_branch = next((branch for branch in (auto_window_sequence_recovery_retry.get("branches") or []) if branch.get("id") == "step2_smart_wait_click"), {})
        auto_window_sequence_recovery_plan_summary = _batch_auto_plan_summary("window_sequence", auto_window_sequence_recovery_branches)
        auto_window_sequence_recovery_plan_auto = next((branch for branch in (auto_window_sequence_recovery_plan_summary.get("branches") or []) if branch.get("id") == "auto_window_sequence"), {})
        auto_window_sequence_post_branches = _batch_auto_branches(
            {"command": "app-sequence"},
            {
                "window-title": "Demo App",
                "path-or-name": "demo.exe",
                "steps": [
                    {
                        "id": "play",
                        "kind": "click",
                        "name": "Play",
                        "control-type": "button",
                        "verify-text": "Playing",
                        "post-timeout": 0.5,
                    },
                    {
                        "id": "save_key",
                        "command": "key",
                        "args": {"keys": "ctrl+s"},
                        "verify-name": "Saved",
                        "verify-control-type": "text",
                        "verify-absent-text": "Saving",
                    },
                ],
                "timeout": 0.1,
                "action-timeout": 0.2,
                "activate": "false",
                "boundary": "false",
                "window-layers": "semantic",
                "action-layers": "semantic",
            },
        )
        auto_window_sequence_post_auto = next((branch for branch in auto_window_sequence_post_branches if branch.get("id") == "auto_window_sequence"), {})
        auto_window_sequence_post_steps = auto_window_sequence_post_auto.get("steps") or []
        auto_window_sequence_post_play = next((step for step in auto_window_sequence_post_steps if step.get("id") == "play"), {})
        auto_window_sequence_post_play_branch = next((branch for branch in (auto_window_sequence_post_play.get("branches") or []) if branch.get("id") == "step1_smart_wait_click"), {})
        auto_window_sequence_post_play_commands = [step.get("command") for step in (auto_window_sequence_post_play_branch.get("steps") or [])]
        auto_window_sequence_post_key = next((step for step in auto_window_sequence_post_steps if step.get("id") == "save_key"), {})
        auto_window_sequence_post_key_branch = (auto_window_sequence_post_key.get("branches") or [{}])[0]
        auto_window_sequence_post_key_commands = [step.get("command") for step in (auto_window_sequence_post_key_branch.get("steps") or [])]
        auto_window_sequence_post_key_absent_loop = (auto_window_sequence_post_key_branch.get("steps") or [{}, {}, {}])[2] if len(auto_window_sequence_post_key_branch.get("steps") or []) > 2 else {}
        auto_window_sequence_post_key_absent_probe = (auto_window_sequence_post_key_absent_loop.get("steps") or [{}])[0]
        auto_window_sequence_post_plan_summary = _batch_auto_plan_summary("window_sequence", auto_window_sequence_post_branches)
        auto_generation_ok = bool(
            {"smart_wait_click", "smart_click", "win32_click", "msaa_default", "image_click", "ocr_click", "coordinate_click"}.issubset(set(auto_click_branch_ids))
            and {"smart_wait_text", "smart_text", "win32_set_text", "msaa_set_value", "focused_input", "type_text"}.issubset(set(auto_text_branch_ids))
            and {"smart_wait_select", "smart_select", "win32_select", "msaa_select"}.issubset(set(auto_select_branch_ids))
            and auto_select_check_smart.get("command") == "smart_select"
            and (auto_select_check_smart.get("args") or {}).get("hwnd") == 1
            and (auto_select_check_smart.get("args") or {}).get("item") == "Gamma"
            and (auto_select_check_smart.get("args") or {}).get("mode") == "check"
            and (auto_select_check_smart.get("args") or {}).get("match") == "exact"
            and (auto_select_check_smart.get("args") or {}).get("timeout_ms") == 654
            and auto_select_check_native.get("command") == "win32_control_action"
            and (auto_select_check_native.get("args") or {}).get("hwnd") == 1
            and (auto_select_check_native.get("args") or {}).get("action") == "check"
            and (auto_select_check_native.get("args") or {}).get("text") == "Gamma"
            and (auto_select_check_native.get("args") or {}).get("checked") is True
            and (auto_select_check_native.get("args") or {}).get("match") == "exact"
            and (auto_select_check_native.get("args") or {}).get("timeout_ms") == 654
            and {"smart_select", "win32_select"}.issubset(set(auto_select_check_conservative_ids))
            and not ({"msaa_select", "visual_row_select", "image_select", "image_scroll_select", "ocr_select", "ocr_scroll_select"} & set(auto_select_check_conservative_ids))
            and {"msaa_select", "image_select", "image_scroll_select", "ocr_select", "ocr_scroll_select"}.issubset(set(auto_select_check_unverified_ids))
            and "visual_row_select" not in set(auto_select_check_unverified_ids)
            and "visual_row_select" in set(auto_select_check_unverified_row_ids)
            and [step.get("command") for step in auto_select_check_verified_smart_steps] == ["smart_select", "win32_control_wait"]
            and (auto_select_check_verified_smart_wait.get("args") or {}).get("hwnd") == 1
            and (auto_select_check_verified_smart_wait.get("args") or {}).get("state") == "checked"
            and (auto_select_check_verified_smart_wait.get("args") or {}).get("expected") == "true"
            and (auto_select_check_verified_smart_wait.get("args") or {}).get("text") == "Gamma"
            and (auto_select_check_verified_smart_wait.get("args") or {}).get("match") == "exact"
            and (auto_select_check_verified_smart_wait.get("args") or {}).get("timeout") == 0.4
            and (auto_select_check_verified_smart_wait.get("args") or {}).get("interval") == 0.05
            and [step.get("command") for step in auto_select_check_verified_native_steps] == ["win32_control_action", "win32_control_wait"]
            and (auto_select_check_verified_native_wait.get("args") or {}).get("state") == "checked"
            and (auto_select_check_verified_native_wait.get("expect") or {}).get("path") == "$result.matched"
            and [step.get("command") for step in auto_select_check_state_verified_steps] == ["win32_control_action", "win32_control_wait"]
            and (auto_select_check_state_verified_wait.get("args") or {}).get("state") == "check_state"
            and (auto_select_check_state_verified_wait.get("args") or {}).get("expected") == "checked"
            and (auto_select_check_state_verified_wait.get("args") or {}).get("text") == "Gamma"
            and (auto_select_check_state_verified_wait.get("args") or {}).get("timeout_ms") == 333
            and [step.get("command") for step in auto_select_present_verified_steps] == ["win32_control_action", "win32_control_wait"]
            and (auto_select_present_verified_wait.get("args") or {}).get("state") == "present"
            and (auto_select_present_verified_wait.get("args") or {}).get("text") == "Gamma"
            and (auto_select_present_verified_wait.get("args") or {}).get("match") == "exact"
            and (auto_select_present_verified_wait.get("args") or {}).get("timeout_ms") == 222
            and [step.get("command") for step in auto_select_absent_verified_steps] == ["win32_control_action", "win32_control_wait"]
            and (auto_select_absent_verified_wait.get("args") or {}).get("state") == "absent"
            and (auto_select_absent_verified_wait.get("args") or {}).get("text") == "Loading"
            and (auto_select_absent_verified_wait.get("args") or {}).get("match") == "exact"
            and (auto_select_absent_verified_wait.get("args") or {}).get("timeout_ms") == 444
            and (auto_select_absent_verified_wait.get("args") or {}).get("max_items") == 12
            and auto_select_absent_plan_summary.get("has_negative_post_verification") is True
            and auto_select_present_repair_wait.get("command") == "batch_try"
            and {
                "win32_select_verify_win32_state_strict",
                "win32_select_verify_win32_state_diagnostic_relaxed_retry",
            }.issubset(set(auto_select_present_repair_branch_ids))
            and ((auto_select_present_repair_strict.get("steps") or [{}])[0].get("command") == "win32_control_wait")
            and auto_select_present_repair_probe.get("command") == "win32_control_wait"
            and (auto_select_present_repair_probe.get("allow_failure") is True)
            and (auto_select_present_repair_probe.get("args") or {}).get("diagnostic") is True
            and (auto_select_present_repair_probe.get("args") or {}).get("timeout") == 0.0
            and auto_select_present_repair_retry.get("command") == "win32_control_wait"
            and (auto_select_present_repair_retry.get("args") or {}).get("match") == "contains"
            and (auto_select_present_repair_retry.get("args") or {}).get("text") == "Gamma"
            and (auto_select_present_repair_retry.get("args") or {}).get("timeout") == 0.2
            and ((auto_select_present_repair_retry.get("when") or [{}])[0].get("path") == "$steps.win32_select_verify_win32_state_diagnostic_probe.result.original_result.failure_summary.target_text")
            and auto_select_present_repair_plan_summary.get("has_retry") is True
            and auto_select_present_repair_plan_summary.get("has_native_wait_repair") is True
            and auto_select_present_native_repair_wait.get("command") == "batch_try"
            and auto_select_present_native_repair_retry.get("command") == "win32_control_wait"
            and (auto_select_present_native_repair_retry.get("args") or {}).get("match") == "contains"
            and (auto_select_present_native_repair_retry.get("args") or {}).get("text") == "Gamma"
            and (auto_select_present_native_repair_retry.get("args") or {}).get("timeout") == 0.4
            and auto_select_present_native_repair_plan_summary.get("has_native_wait_repair") is True
            and auto_select_present_native_repair_plan_summary.get("has_retry") is True
            and auto_select_present_native_repair_disabled_wait.get("command") == "win32_control_wait"
            and auto_select_present_native_repair_disabled_plan_summary.get("has_native_wait_repair") is not True
            and {"smart_wait_cell", "smart_cell", "win32_cell"}.issubset(set(auto_cell_branch_ids))
            and "key_input" in auto_key_branch_ids
            and auto_key_input.get("command") == "key"
            and (auto_key_input.get("args") or {}).get("hwnd") == 1
            and (auto_key_input.get("args") or {}).get("keys") == "ctrl+f"
            and auto_key_post.get("command") == "uia_wait"
            and (auto_key_post.get("args") or {}).get("name") == "Search"
            and (auto_key_post.get("args") or {}).get("hwnd") == 1
            and (auto_key_post.get("args") or {}).get("timeout") == 0.2
            and "uia_hover" in auto_hover_branch_ids
            and auto_hover_find.get("command") == "uia_wait"
            and (auto_hover_find.get("args") or {}).get("name") == "Play"
            and (auto_hover_find.get("args") or {}).get("control_type") == "button"
            and auto_hover_move.get("command") == "move"
            and (auto_hover_move.get("args") or {}).get("hwnd") == 1
            and (auto_hover_move.get("args") or {}).get("x") == "$steps.hover_find.result.match.rect.center_x"
            and (auto_hover_move.get("args") or {}).get("y") == "$steps.hover_find.result.match.rect.center_y"
            and (auto_hover_move.get("args") or {}).get("settle") == 0.15
            and len(auto_hover_coord_branches) == 1
            and auto_hover_coord.get("command") == "move"
            and (auto_hover_coord.get("args") or {}).get("x") == 10
            and (auto_hover_coord.get("args") or {}).get("y") == 20
            and (auto_hover_coord.get("args") or {}).get("settle") == 0.1
            and auto_desktop_hover.get("command") == "desktop_move"
            and {"wheel_scroll", "keyboard_scroll"}.issubset(set(auto_scroll_branch_ids))
            and auto_scroll_wheel_action.get("command") == "scroll"
            and (auto_scroll_wheel_action.get("args") or {}).get("hwnd") == 1
            and (auto_scroll_wheel_action.get("args") or {}).get("x") == 10
            and (auto_scroll_wheel_action.get("args") or {}).get("y") == 20
            and (auto_scroll_wheel_action.get("args") or {}).get("dy") == -3
            and auto_scroll_keyboard_action.get("command") == "key"
            and (auto_scroll_keyboard_action.get("args") or {}).get("hwnd") == 1
            and (auto_scroll_keyboard_action.get("args") or {}).get("keys") == "pageup"
            and auto_scroll_absent_probe.get("command") == "ocr_find"
            and (auto_scroll_absent_probe.get("args") or {}).get("text") == "Loading"
            and (auto_scroll_absent_probe.get("args") or {}).get("hwnd") == 1
            and "keyboard_scroll" not in auto_scroll_no_keyboard_ids
            and auto_desktop_scroll.get("command") == "desktop_scroll"
            and (auto_desktop_scroll.get("args") or {}).get("scroll_y") == 4
            and "keyboard_scroll" not in auto_desktop_scroll_ids
            and auto_desktop_scroll_with_keyboard.get("command") == "key"
            and (auto_desktop_scroll_with_keyboard.get("args") or {}).get("keys") == "pagedown"
            and "hwnd" not in (auto_desktop_scroll_with_keyboard.get("args") or {})
            and "coordinate_drag" in auto_drag_branch_ids
            and auto_drag.get("command") == "drag"
            and (auto_drag.get("args") or {}).get("hwnd") == 1
            and (auto_drag.get("args") or {}).get("start_x") == 1
            and (auto_drag.get("args") or {}).get("end_y") == 40
            and (auto_drag.get("args") or {}).get("duration") == 0.2
            and "menu_action" in auto_menu_branch_ids
            and auto_menu.get("command") == "menu_action"
            and (auto_menu.get("args") or {}).get("hwnd") == 1
            and (auto_menu.get("args") or {}).get("path") == ["File", "Open"]
            and (auto_menu.get("args") or {}).get("timeout_ms") == 777
            and auto_menu_system.get("command") == "menu_action"
            and (auto_menu_system.get("args") or {}).get("hwnd") == 1
            and (auto_menu_system.get("args") or {}).get("command_id") == 0xF030
            and (auto_menu_system.get("args") or {}).get("include_system") is True
            and (auto_menu_system.get("args") or {}).get("async_post") is True
            and "file_dialog_action" in auto_file_dialog_branch_ids
            and auto_file_dialog.get("command") == "file_dialog_action"
            and (auto_file_dialog.get("args") or {}).get("hwnd") == 1
            and (auto_file_dialog.get("args") or {}).get("action") == "confirm"
            and (auto_file_dialog.get("args") or {}).get("path") == "C:\\Temp\\demo.txt"
            and (auto_file_dialog.get("args") or {}).get("verify_close") is True
            and (auto_file_dialog.get("args") or {}).get("timeout_ms") == 666
            and auto_file_dialog_info.get("command") == "file_dialog_info"
            and (auto_file_dialog_info.get("args") or {}).get("hwnd") == 1
            and (auto_file_dialog_info.get("args") or {}).get("include_children") is True
            and (auto_file_dialog_info.get("args") or {}).get("timeout_ms") == 444
            and {"native_dialog_command", "native_dialog_button", "smart_dialog", "desktop_dialog_uia", "desktop_dialog_uia_selector_repair", "desktop_dialog_ocr", "desktop_dialog_image", "desktop_dialog_coordinate"}.issubset(set(auto_dialog_branch_ids))
            and auto_dialog_branch_ids.index("native_dialog_command") < auto_dialog_branch_ids.index("native_dialog_button")
            and {"auto_window", "wait_window", "window_selector_repair", "launch_window"}.issubset(set(auto_window_branch_ids))
            and {"auto_window_click", "wait_window_click", "window_selector_repair_click", "launch_window_click"}.issubset(set(auto_window_action_branch_ids))
            and {"auto_window_key", "wait_window_key", "window_selector_repair_key", "launch_window_key"}.issubset(set(auto_window_action_key_branch_ids))
            and {"auto_window_menu", "wait_window_menu", "window_selector_repair_menu", "launch_window_menu"}.issubset(set(auto_window_action_menu_branch_ids))
            and {"auto_window_file_dialog", "wait_window_file_dialog", "window_selector_repair_file_dialog", "launch_window_file_dialog"}.issubset(set(auto_window_action_file_dialog_branch_ids))
            and {"auto_window_sequence", "wait_window_sequence", "window_selector_repair_sequence", "launch_window_sequence"}.issubset(set(auto_window_sequence_branch_ids))
            and (auto_window_repair_steps[0].get("command") == "wait_window")
            and (auto_window_repair_steps[0].get("optional") is True)
            and auto_window_repair_pick.get("command") == "batch_try"
            and (auto_window_repair_direct.get("args") or {}).get("value", {}).get("hwnd") == "$steps.window_selector_repair_probe.result.window.hwnd"
            and auto_window_repair_suggested_find.get("command") == "window_selector_repair_find"
            and (auto_window_repair_suggested_find.get("args") or {}).get("suggestion") == "$steps.window_selector_repair_probe.result.original_result.failure_summary.selector_suggestions.0"
            and (auto_window_repair_suggested_find.get("args") or {}).get("original", {}).get("title") == "Demo App"
            and (auto_window_repair_suggested_find.get("args") or {}).get("probe_original") is False
            and (auto_window_repair_steps[-1].get("args") or {}).get("value", {}).get("hwnd") == "$steps.window_selector_repair_pick.result.value.hwnd"
            and "smart_click" not in auto_layered_branch_ids
            and "win32_click" not in auto_layered_branch_ids
            and "msaa_default" not in auto_layered_branch_ids
            and {"ocr_click", "ocr_scroll_click", "coordinate_click"}.issubset(set(auto_layered_branch_ids))
            and next((branch for branch in auto_click_branches if branch.get("id") == "image_click"), {}).get("args", {}).get("template") == "icon.png"
            and auto_alias_smart.get("args", {}).get("automation_id") == "saveButton"
            and auto_alias_smart.get("args", {}).get("control_type") == "button"
            and auto_alias_smart.get("args", {}).get("timeout_ms") == 321
            and auto_alias_image.get("args", {}).get("template_path") == "icon2.png"
            and auto_alias_image.get("args", {}).get("capture_mode") == "visible"
            and {"smart_click_selector_repair_1", "smart_click_selector_repair_2", "smart_click_selector_repair_3", "smart_click_selector_repair_4"}.issubset(set(auto_selector_repair_click_ids))
            and {"smart_text_selector_repair_1", "smart_text_selector_repair_2", "smart_text_selector_repair_3", "smart_text_selector_repair_4"}.issubset(set(auto_selector_repair_text_ids))
            and {"smart_select_selector_repair_1", "smart_select_selector_repair_2", "smart_select_selector_repair_3", "smart_select_selector_repair_4"}.issubset(set(auto_selector_repair_select_ids))
            and {"uia_click_selector_repair", "uia_text_selector_repair", "uia_select_selector_repair", "uia_cell_selector_repair"}.issubset(
                set(auto_selector_repair_click_ids + auto_selector_repair_text_ids + auto_selector_repair_select_ids + auto_uia_repair_cell_ids)
            )
            and (auto_selector_repair_click_stable.get("args") or {}).get("automation_id") == "okButton"
            and "name" not in (auto_selector_repair_click_stable.get("args") or {})
            and (auto_selector_repair_click_named.get("args") or {}).get("name") == "OK"
            and (auto_selector_repair_click_named.get("args") or {}).get("control_type") == "button"
            and (auto_selector_repair_text_stable.get("args") or {}).get("text") == "query"
            and (auto_selector_repair_text_stable.get("args") or {}).get("automation_id") == "searchBox"
            and (auto_selector_repair_select_stable.get("args") or {}).get("item") == "Normal"
            and (auto_selector_repair_select_stable.get("args") or {}).get("automation_id") == "modeList"
            and len(auto_uia_repair_click_steps) == 2
            and (auto_uia_repair_click_steps[0].get("command") == "uia_find")
            and (auto_uia_repair_click_steps[0].get("optional") is True)
            and (auto_uia_repair_click_try.get("command") == "batch_try")
            and (auto_uia_repair_click_suggested_steps[0].get("command") == "uia_selector_repair_find")
            and (auto_uia_repair_click_suggested_steps[0].get("args") or {}).get("suggestion") == "$steps.uia_click_selector_repair_probe.result.original_result.failure_summary.selector_suggestions.0"
            and (auto_uia_repair_click_suggested_steps[1].get("command") == "uia_action")
            and (auto_uia_repair_click_suggested_steps[1].get("args") or {}).get("action") == "Invoke"
            and (auto_uia_repair_text_suggested_steps[1].get("command") == "uia_set_value")
            and (auto_uia_repair_text_suggested_steps[1].get("args") or {}).get("value") == "query"
            and (auto_uia_repair_select_suggested_steps[1].get("command") == "uia_action")
            and (auto_uia_repair_select_suggested_steps[1].get("args") or {}).get("action") == "Select"
            and (auto_uia_repair_cell_probe.get("command") == "uia_find")
            and (auto_uia_repair_cell_probe.get("optional") is True)
            and (auto_uia_repair_cell_probe.get("args") or {}).get("pattern") == "GridItem"
            and (auto_uia_repair_cell_probe.get("args") or {}).get("automation_id") == "resultsGrid"
            and (auto_uia_repair_cell_try.get("command") == "batch_try")
            and (auto_uia_repair_cell_direct_steps[0].get("command") == "uia_cell_selector_repair_find")
            and ((auto_uia_repair_cell_direct_steps[0].get("args") or {}).get("original") or {}).get("row_text") == "Beta"
            and ((auto_uia_repair_cell_direct_steps[0].get("args") or {}).get("original") or {}).get("column_name") == "State"
            and (auto_uia_repair_cell_direct_steps[1].get("command") == "uia_set_value")
            and (auto_uia_repair_cell_direct_steps[1].get("args") or {}).get("value") == "Done"
            and (auto_uia_repair_cell_suggested_steps[0].get("command") == "uia_cell_selector_repair_find")
            and (auto_uia_repair_cell_suggested_steps[0].get("args") or {}).get("suggestion") == "$steps.uia_cell_selector_repair_probe.result.original_result.failure_summary.selector_suggestions.0"
            and (auto_uia_repair_cell_suggested_steps[1].get("command") == "uia_set_value")
            and (auto_uia_repair_cell_get_direct_steps[1].get("command") == "uia_element")
            and (auto_smart_wait_repair_click.get("args") or {}).get("repair") is True
            and (auto_smart_wait_repair_click.get("args") or {}).get("repair_timeout") == 0.0
            and auto_smart_wait_repair_click_plan_summary.get("has_smart_wait_repair") is True
            and auto_smart_wait_repair_click_plan_summary.get("has_selector_repair") is True
            and auto_smart_wait_repair_click_plan_summary.get("has_uia_selector_repair") is True
            and (auto_smart_wait_repair_uia_alias.get("args") or {}).get("repair") is True
            and (auto_smart_wait_repair_uia_alias.get("args") or {}).get("repair_timeout") == 0.0
            and auto_smart_wait_repair_uia_alias_plan_summary.get("has_smart_wait_repair") is True
            and auto_smart_wait_repair_uia_alias_plan_summary.get("has_uia_selector_repair") is True
            and (auto_smart_wait_repair_cell.get("args") or {}).get("repair") is True
            and (auto_smart_wait_repair_cell.get("args") or {}).get("repair_timeout") == 0.0
            and auto_smart_wait_repair_cell_plan_summary.get("has_smart_wait_repair") is True
            and auto_smart_wait_repair_cell_plan_summary.get("has_selector_repair") is True
            and auto_smart_wait_repair_cell_plan_summary.get("has_uia_selector_repair") is True
            and auto_smart_wait_repair_no_timeout.get("command") == "smart_wait_click"
            and (auto_smart_wait_repair_no_timeout.get("args") or {}).get("repair") is True
            and (auto_smart_wait_repair_no_timeout.get("args") or {}).get("repair_timeout") == 0.0
            and "timeout" not in (auto_smart_wait_repair_no_timeout.get("args") or {})
            and auto_smart_wait_repair_no_timeout_plan_summary.get("has_smart_wait_repair") is True
            and auto_smart_wait_repair_text_no_timeout.get("command") == "smart_wait_text"
            and (auto_smart_wait_repair_text_no_timeout.get("args") or {}).get("repair") is True
            and (auto_smart_wait_repair_text_no_timeout.get("args") or {}).get("repair_timeout") == 0.0
            and "timeout" not in (auto_smart_wait_repair_text_no_timeout.get("args") or {})
            and auto_smart_wait_repair_text_no_timeout_plan_summary.get("has_smart_wait_repair") is True
            and auto_smart_wait_repair_select_no_timeout.get("command") == "smart_wait_select"
            and (auto_smart_wait_repair_select_no_timeout.get("args") or {}).get("repair") is True
            and (auto_smart_wait_repair_select_no_timeout.get("args") or {}).get("repair_timeout") == 0.0
            and "timeout" not in (auto_smart_wait_repair_select_no_timeout.get("args") or {})
            and auto_smart_wait_repair_select_no_timeout_plan_summary.get("has_smart_wait_repair") is True
            and auto_smart_wait_repair_cell_no_timeout.get("command") == "smart_wait_cell"
            and (auto_smart_wait_repair_cell_no_timeout.get("args") or {}).get("repair") is True
            and (auto_smart_wait_repair_cell_no_timeout.get("args") or {}).get("repair_timeout") == 0.0
            and "timeout" not in (auto_smart_wait_repair_cell_no_timeout.get("args") or {})
            and auto_smart_wait_repair_cell_no_timeout_plan_summary.get("has_smart_wait_repair") is True
            and auto_smart_wait_repair_timeout_only.get("command") == "smart_wait_click"
            and (auto_smart_wait_repair_timeout_only.get("args") or {}).get("repair") is True
            and (auto_smart_wait_repair_timeout_only.get("args") or {}).get("repair_timeout") == 0.0
            and "timeout" not in (auto_smart_wait_repair_timeout_only.get("args") or {})
            and auto_smart_wait_repair_timeout_only_plan_summary.get("has_smart_wait_repair") is True
            and auto_smart_wait_repair_timeout_only_disabled == {}
            and auto_smart_wait_repair_timeout_only_disabled_plan_summary.get("has_smart_wait_repair") is not True
            and not any("selector_repair" in str(branch_id or "") for branch_id in auto_selector_repair_disabled_ids)
            and "uia_click_selector_repair" not in auto_uia_repair_disabled_ids
            and "uia_cell_selector_repair" not in auto_uia_repair_cell_disabled_ids
            and "win32_click_selector_repair" in auto_uia_repair_disabled_ids
            and {"win32_click_selector_repair", "win32_text_selector_repair", "win32_select_selector_repair"}.issubset(
                set(auto_selector_repair_click_ids + auto_selector_repair_text_ids + auto_selector_repair_select_ids)
            )
            and "win32_cell_selector_repair" in auto_native_repair_cell_ids
            and len(auto_native_repair_click_steps) == 4
            and (auto_native_repair_click_steps[0].get("command") == "win32_control_find")
            and (auto_native_repair_click_steps[0].get("optional") is True)
            and (auto_native_repair_click_steps[1].get("args") or {}).get("hwnd") == "$steps.win32_click_selector_repair_probe.result.matches.0.hwnd"
            and ((auto_native_repair_click_steps[1].get("when") or {}).get("path") == "$steps.win32_click_selector_repair_probe.result.matches.0.hwnd")
            and (auto_native_repair_click_steps[2].get("command") == "win32_selector_repair_find")
            and (auto_native_repair_click_steps[2].get("args") or {}).get("suggestion") == "$steps.win32_click_selector_repair_probe.result.original_result.failure_summary.selector_suggestions.0"
            and (auto_native_repair_click_steps[2].get("args") or {}).get("original", {}).get("automation_id") == "okButton"
            and (auto_native_repair_click_steps[3].get("args") or {}).get("hwnd") == "$steps.win32_click_selector_repair_suggested_find.result.matches.0.hwnd"
            and (auto_native_repair_text_steps[3].get("command") == "win32_set_text")
            and (auto_native_repair_text_steps[3].get("args") or {}).get("text") == "query"
            and (auto_native_repair_select_steps[3].get("command") == "win32_control_action")
            and (auto_native_repair_select_steps[3].get("args") or {}).get("text") == "Normal"
            and (auto_native_repair_cell_steps[3].get("command") == "win32_control_action")
            and (auto_native_repair_cell_steps[3].get("args") or {}).get("value") == 3
            and "win32_click_selector_repair" not in auto_native_repair_disabled_ids
            and auto_visual_row_click.get("command") == "visual_row_scroll_click"
            and (auto_visual_row_click.get("args") or {}).get("row") == 16
            and (auto_visual_row_click.get("args") or {}).get("click_x") == 320
            and (auto_visual_row_click.get("args") or {}).get("clicks") == 2
            and (auto_visual_row_click.get("args") or {}).get("max_scrolls") == 9
            and (auto_visual_row_click.get("args") or {}).get("capture_mode") == "visible"
            and auto_ocr_scroll_click.get("command") == "ocr_scroll_click"
            and (auto_ocr_scroll_click.get("args") or {}).get("text") == "Hidden Item"
            and (auto_ocr_scroll_click.get("args") or {}).get("max_scrolls") == 6
            and (auto_ocr_scroll_click.get("args") or {}).get("scroll_amount") == 4
            and (auto_ocr_scroll_click.get("args") or {}).get("scroll_x") == 300
            and (auto_ocr_scroll_click.get("args") or {}).get("scroll_y") == 500
            and (auto_ocr_scroll_click.get("args") or {}).get("capture_mode") == "visible"
            and auto_image_scroll_click.get("command") == "image_scroll_click"
            and (auto_image_scroll_click.get("args") or {}).get("template_path") == "hidden-icon.png"
            and (auto_image_scroll_click.get("args") or {}).get("confidence") == 0.9
            and (auto_image_scroll_click.get("args") or {}).get("max_scrolls") == 5
            and (auto_image_scroll_click.get("args") or {}).get("scroll_amount") == 3
            and (auto_image_scroll_click.get("args") or {}).get("scroll_x") == 280
            and (auto_image_scroll_click.get("args") or {}).get("scroll_y") == 520
            and (auto_image_scroll_click.get("args") or {}).get("capture_mode") == "visible"
            and (auto_visual_row_select.get("args") or {}).get("row") == 7
            and (auto_visual_row_select.get("args") or {}).get("clicks") == 1
            and {"image_select", "image_scroll_select", "ocr_select", "ocr_scroll_select"}.issubset(set(auto_visual_select_ids))
            and auto_visual_select_image.get("command") == "image_click"
            and (auto_visual_select_image.get("args") or {}).get("template_path") == "option-icon.png"
            and (auto_visual_select_image.get("args") or {}).get("confidence") == 0.91
            and (auto_visual_select_image.get("args") or {}).get("capture_mode") == "visible"
            and auto_visual_select_image_scroll.get("command") == "image_scroll_click"
            and (auto_visual_select_image_scroll.get("args") or {}).get("template_path") == "option-icon.png"
            and (auto_visual_select_image_scroll.get("args") or {}).get("max_scrolls") == 6
            and (auto_visual_select_image_scroll.get("args") or {}).get("scroll_amount") == 4
            and (auto_visual_select_image_scroll.get("args") or {}).get("scroll_x") == 300
            and (auto_visual_select_image_scroll.get("args") or {}).get("scroll_y") == 500
            and (auto_visual_select_image_scroll.get("args") or {}).get("capture_mode") == "visible"
            and auto_visual_select_ocr.get("command") == "ocr_click"
            and (auto_visual_select_ocr.get("args") or {}).get("text") == "Hidden Option"
            and (auto_visual_select_ocr.get("args") or {}).get("capture_mode") == "visible"
            and auto_visual_select_ocr_scroll.get("command") == "ocr_scroll_click"
            and (auto_visual_select_ocr_scroll.get("args") or {}).get("text") == "Hidden Option"
            and (auto_visual_select_ocr_scroll.get("args") or {}).get("max_scrolls") == 6
            and (auto_visual_select_ocr_scroll.get("args") or {}).get("scroll_amount") == 4
            and (auto_visual_select_ocr_scroll.get("args") or {}).get("scroll_x") == 300
            and (auto_visual_select_ocr_scroll.get("args") or {}).get("scroll_y") == 500
            and (auto_visual_select_ocr_scroll.get("args") or {}).get("capture_mode") == "visible"
            and {"image_text_input", "image_scroll_text_input", "ocr_text_input", "ocr_scroll_text_input"}.issubset(set(auto_visual_text_ids))
            and auto_visual_text_image_focus.get("command") == "image_click"
            and (auto_visual_text_image_focus.get("args") or {}).get("template_path") == "search-box.png"
            and (auto_visual_text_image_focus.get("args") or {}).get("confidence") == 0.92
            and (auto_visual_text_image_focus.get("args") or {}).get("capture_mode") == "visible"
            and auto_visual_text_image_input.get("command") == "focused_input"
            and (auto_visual_text_image_input.get("args") or {}).get("text") == "typed value"
            and (auto_visual_text_image_input.get("args") or {}).get("timeout") == 0.7
            and (auto_visual_text_image_input.get("args") or {}).get("timeout_ms") == 333
            and (auto_visual_text_image_input.get("args") or {}).get("verify") == "false"
            and auto_visual_text_image_scroll_focus.get("command") == "image_scroll_click"
            and (auto_visual_text_image_scroll_focus.get("args") or {}).get("max_scrolls") == 4
            and (auto_visual_text_image_scroll_focus.get("args") or {}).get("scroll_amount") == 2
            and (auto_visual_text_image_scroll_focus.get("args") or {}).get("scroll_x") == 260
            and (auto_visual_text_image_scroll_focus.get("args") or {}).get("scroll_y") == 480
            and (auto_visual_text_image_scroll_focus.get("args") or {}).get("capture_mode") == "visible"
            and auto_visual_text_ocr_focus.get("command") == "ocr_click"
            and (auto_visual_text_ocr_focus.get("args") or {}).get("text") == "Search here"
            and (auto_visual_text_ocr_focus.get("args") or {}).get("capture_mode") == "visible"
            and auto_visual_text_ocr_input.get("command") == "focused_input"
            and (auto_visual_text_ocr_input.get("args") or {}).get("text") == "typed value"
            and auto_visual_text_ocr_scroll_focus.get("command") == "ocr_scroll_click"
            and (auto_visual_text_ocr_scroll_focus.get("args") or {}).get("text") == "Search here"
            and (auto_visual_text_ocr_scroll_focus.get("args") or {}).get("max_scrolls") == 4
            and (auto_visual_text_ocr_scroll_focus.get("args") or {}).get("scroll_amount") == 2
            and (auto_visual_text_ocr_scroll_focus.get("args") or {}).get("scroll_x") == 260
            and (auto_visual_text_ocr_scroll_focus.get("args") or {}).get("scroll_y") == 480
            and (auto_visual_text_ocr_scroll_focus.get("args") or {}).get("capture_mode") == "visible"
            and auto_visual_text_desktop_ocr_focus.get("command") == "desktop_ocr_click"
            and (auto_visual_text_desktop_ocr_focus.get("args") or {}).get("text") == "Global Search"
            and auto_visual_text_desktop_ocr_input.get("command") == "type_foreground"
            and (auto_visual_text_desktop_ocr_input.get("args") or {}).get("text") == "global query"
            and auto_pre_visual_click_stable.get("command") == "visual_stable_wait"
            and (auto_pre_visual_click_stable.get("args") or {}).get("hwnd") == 1
            and (auto_pre_visual_click_stable.get("args") or {}).get("timeout") == 0.4
            and (auto_pre_visual_click_stable.get("args") or {}).get("interval") == 0.08
            and (auto_pre_visual_click_stable.get("args") or {}).get("stable_ticks") == 3
            and (auto_pre_visual_click_stable.get("args") or {}).get("region") == "1,2,300,220"
            and (auto_pre_visual_click_stable.get("args") or {}).get("comparison_max_width") == 80
            and (auto_pre_visual_click_stable.get("args") or {}).get("capture_mode") == "visible"
            and auto_pre_visual_click_action.get("command") == "image_click"
            and (auto_pre_visual_click_action.get("args") or {}).get("template_path") == "ok.png"
            and auto_pre_visual_dialog_stable.get("command") == "desktop_visual_stable_wait"
            and "hwnd" not in (auto_pre_visual_dialog_stable.get("args") or {})
            and (auto_pre_visual_dialog_stable.get("args") or {}).get("timeout") == 0.35
            and auto_pre_visual_dialog_action.get("command") == "desktop_ocr_click"
            and (auto_pre_visual_dialog_action.get("args") or {}).get("text") == "OK"
            and auto_pre_uia_click_stable.get("command") == "uia_stable_wait"
            and (auto_pre_uia_click_stable.get("args") or {}).get("hwnd") == 1
            and (auto_pre_uia_click_stable.get("args") or {}).get("timeout") == 0.45
            and (auto_pre_uia_click_stable.get("args") or {}).get("interval") == 0.07
            and (auto_pre_uia_click_stable.get("args") or {}).get("stable_ticks") == 3
            and (auto_pre_uia_click_stable.get("args") or {}).get("max_depth") == 6
            and (auto_pre_uia_click_stable.get("args") or {}).get("max_elements") == 120
            and (auto_pre_uia_click_stable.get("args") or {}).get("view") == "content"
            and (auto_pre_uia_click_stable.get("args") or {}).get("include_values") is True
            and (auto_pre_uia_click_stable.get("args") or {}).get("rect_bucket") == 4
            and auto_pre_uia_click_action.get("command") == "smart_wait_click"
            and (auto_pre_uia_click_action.get("args") or {}).get("name") == "Save"
            and auto_pre_uia_dialog_stable.get("command") == "desktop_uia_stable_wait"
            and "hwnd" not in (auto_pre_uia_dialog_stable.get("args") or {})
            and (auto_pre_uia_dialog_stable.get("args") or {}).get("timeout") == 0.5
            and auto_pre_uia_dialog_wait.get("command") == "desktop_wait"
            and auto_post_click_commands[:7] == ["smart_click", "batch_sleep", "visual_stable_wait", "uia_stable_wait", "uia_wait", "image_wait", "ocr_wait"]
            and auto_post_click_commands[-1] == "observe"
            and (auto_post_click_stable.get("args") or {}).get("hwnd") == 1
            and (auto_post_click_stable.get("args") or {}).get("stable_ticks") == 3
            and (auto_post_click_stable.get("args") or {}).get("comparison_max_width") == 96
            and (auto_post_click_stable.get("args") or {}).get("difference_threshold") == 0.002
            and (auto_post_click_stable.get("args") or {}).get("pixel_threshold") == 7
            and (auto_post_click_stable.get("args") or {}).get("region") == "10,20,300,220"
            and (auto_post_click_uia_stable.get("args") or {}).get("hwnd") == 1
            and (auto_post_click_uia_stable.get("args") or {}).get("stable_ticks") == 2
            and (auto_post_click_uia_stable.get("args") or {}).get("max_depth") == 6
            and (auto_post_click_uia_stable.get("args") or {}).get("max_elements") == 160
            and (auto_post_click_uia_stable.get("args") or {}).get("view") == "content"
            and (auto_post_click_uia_stable.get("args") or {}).get("include_values") is True
            and (auto_post_click_uia_stable.get("args") or {}).get("rect_bucket") == 5
            and (auto_post_click_uia_stable.get("args") or {}).get("timeout") == 0.4
            and (auto_post_click_steps[4].get("args") or {}).get("hwnd") == 1
            and (auto_post_click_steps[4].get("args") or {}).get("name") == "Pause"
            and (auto_post_click_steps[4].get("args") or {}).get("control_type") == "button"
            and (auto_post_click_steps[4].get("args") or {}).get("timeout") == 0.4
            and (auto_post_click_steps[5].get("args") or {}).get("template_path") == "playing.png"
            and (auto_post_click_steps[5].get("args") or {}).get("capture_mode") == "visible"
            and (auto_post_click_steps[6].get("args") or {}).get("text") == "Playing"
            and (auto_post_click_steps[7].get("args") or {}).get("hwnd") == 1
            and auto_post_click_plan_summary.get("has_post_verification") is True
            and auto_post_absent_commands == ["smart_click", "batch_repeat", "batch_repeat", "batch_repeat"]
            and auto_post_absent_selector_loop.get("max_iterations") == 4
            and auto_post_absent_selector_probe.get("command") == "uia_find"
            and (auto_post_absent_selector_probe.get("args") or {}).get("hwnd") == 1
            and (auto_post_absent_selector_probe.get("args") or {}).get("name") == "Loading"
            and (auto_post_absent_selector_probe.get("args") or {}).get("control_type") == "text"
            and auto_post_absent_image_probe.get("command") == "locate_image"
            and (auto_post_absent_image_probe.get("args") or {}).get("template_path") == "spinner.png"
            and (auto_post_absent_image_probe.get("args") or {}).get("capture_mode") == "visible"
            and auto_post_absent_text_probe.get("command") == "ocr_find"
            and (auto_post_absent_text_probe.get("args") or {}).get("text") == "Loading"
            and auto_post_absent_plan_summary.get("has_post_verification") is True
            and auto_post_absent_plan_summary.get("has_negative_post_verification") is True
            and auto_post_pixel_commands == ["smart_click", "pixel_wait", "pixel_wait"]
            and (auto_post_pixel_positive.get("args") or {}).get("hwnd") == 1
            and (auto_post_pixel_positive.get("args") or {}).get("x") == 12
            and (auto_post_pixel_positive.get("args") or {}).get("y") == 34
            and (auto_post_pixel_positive.get("args") or {}).get("color") == "#00aa55"
            and (auto_post_pixel_positive.get("args") or {}).get("tolerance") == 6
            and (auto_post_pixel_positive.get("args") or {}).get("capture_mode") == "visible"
            and (auto_post_pixel_negative.get("args") or {}).get("mode") == "not_equals"
            and (auto_post_pixel_negative.get("args") or {}).get("color") == "#777777"
            and auto_post_pixel_plan_summary.get("has_post_verification") is True
            and auto_post_pixel_plan_summary.get("has_negative_post_verification") is True
            and auto_desktop_post_commands == ["desktop_ocr_click", "desktop_ocr_wait", "desktop_accessibility"]
            and (auto_desktop_post_steps[1].get("args") or {}).get("text") == "Done"
            and auto_desktop_post_steps[2].get("expect", {}).get("path") == "$result.desktop"
            and auto_desktop_absent_commands == ["desktop_ocr_click", "batch_repeat", "batch_repeat"]
            and auto_desktop_absent_selector_probe.get("command") == "desktop_find"
            and (auto_desktop_absent_selector_probe.get("args") or {}).get("name") == "Progress"
            and auto_desktop_absent_text_probe.get("command") == "desktop_ocr_find"
            and (auto_desktop_absent_text_probe.get("args") or {}).get("text") == "Working"
            and auto_desktop_pixel_commands == ["desktop_ocr_click", "desktop_visual_stable_wait", "desktop_uia_stable_wait", "desktop_pixel_wait"]
            and (auto_desktop_pixel_stable.get("args") or {}).get("stable_ticks") == 2
            and (auto_desktop_pixel_uia_stable.get("args") or {}).get("max_depth") == 3
            and (auto_desktop_pixel_uia_stable.get("args") or {}).get("view") == "control"
            and (auto_desktop_pixel_steps[3].get("args") or {}).get("x") == 20
            and (auto_desktop_pixel_steps[3].get("args") or {}).get("color") == "#00aa55"
            and (auto_visual_row_cell.get("args") or {}).get("row") == 3
            and not any("visual_row" in str(branch_id or "") for branch_id in auto_visual_row_disabled_ids)
            and visual_row_path_item.get("path") == "/visual_row_scroll_click"
            and _batch_command_from_path("/visual-row-scroll-click") == "visual_row_scroll_click"
            and auto_dialog_command.get("command") == "dialog_command_action"
            and auto_dialog_command.get("args", {}).get("hwnd") == 1
            and auto_dialog_command.get("args", {}).get("dialog_title") == "Confirm"
            and auto_dialog_command.get("args", {}).get("name") == "OK"
            and auto_dialog_command.get("args", {}).get("timeout") == 0.1
            and auto_dialog_native.get("command") == "dialog_button_action"
            and auto_dialog_native.get("args", {}).get("hwnd") == 1
            and auto_dialog_native.get("args", {}).get("dialog_title") == "Confirm"
            and auto_dialog_native.get("args", {}).get("name") == "OK"
            and auto_dialog_native.get("args", {}).get("automation_id") == "okButton"
            and auto_dialog_native.get("args", {}).get("control_type") == "button"
            and auto_dialog_native.get("args", {}).get("prefer_command") is False
            and auto_dialog_native.get("args", {}).get("timeout") == 0.1
            and auto_dialog_smart.get("command") == "smart_dialog_action"
            and auto_dialog_smart.get("args", {}).get("action_kind") == "click"
            and auto_dialog_smart.get("args", {}).get("dialog_title") == "Confirm"
            and auto_dialog_smart.get("args", {}).get("automation_id") == "okButton"
            and auto_dialog_smart.get("args", {}).get("action_timeout") == 0.1
            and auto_dialog_repair_smart.get("command") == "smart_dialog_action"
            and auto_dialog_repair_smart.get("args", {}).get("action_kind") == "select"
            and auto_dialog_repair_smart.get("args", {}).get("repair") is True
            and auto_dialog_repair_smart.get("args", {}).get("repair_timeout") == 0.0
            and auto_dialog_repair_smart.get("args", {}).get("stable_ticks") == 3
            and auto_dialog_repair_plan_summary.get("has_dialog_action_repair") is True
            and auto_dialog_repair_plan_summary.get("has_dialog_stable_wait") is True
            and auto_dialog_repair_plan_summary.get("has_selector_repair") is True
            and auto_dialog_repair_plan_summary.get("has_uia_selector_repair") is True
            and (auto_dialog_repair_plan_preview.get("options") or {}).get("repair") is True
            and (auto_dialog_repair_plan_preview.get("options") or {}).get("repair_timeout") == 0.0
            and (auto_dialog_repair_plan_preview.get("options") or {}).get("stable_ticks") == 3
            and auto_dialog_stable_alias_smart.get("command") == "smart_dialog_action"
            and (auto_dialog_stable_alias_smart.get("args") or {}).get("stable_ticks") == 4
            and (auto_dialog_uia_repair_alias_smart.get("args") or {}).get("repair") is True
            and (auto_dialog_uia_repair_alias_smart.get("args") or {}).get("repair_timeout") == 0.0
            and auto_dialog_uia_repair_alias_plan_summary.get("has_dialog_action_repair") is True
            and auto_dialog_uia_repair_alias_plan_summary.get("has_uia_selector_repair") is True
            and (auto_dialog_repair_timeout_only_smart.get("args") or {}).get("repair") is True
            and (auto_dialog_repair_timeout_only_smart.get("args") or {}).get("repair_timeout") == 0.0
            and auto_dialog_repair_timeout_only_plan_summary.get("has_dialog_action_repair") is True
            and auto_dialog_repair_timeout_only_plan_summary.get("has_uia_selector_repair") is True
            and (auto_dialog_repair_timeout_only_disabled_smart.get("args") or {}).get("repair") is False
            and (auto_dialog_repair_timeout_only_disabled_smart.get("args") or {}).get("repair_timeout") == 0.0
            and auto_dialog_repair_timeout_only_disabled_plan_summary.get("has_dialog_action_repair") is not True
            and (auto_dialog_desktop.get("steps") or [{}])[0].get("command") == "desktop_wait"
            and ((auto_dialog_desktop.get("steps") or [{}])[0].get("expect") or {}).get("path") == "$result.match.index"
            and (auto_dialog_desktop_repair_steps[0] if auto_dialog_desktop_repair_steps else {}).get("command") == "desktop_find"
            and (auto_dialog_desktop_repair_steps[0] if auto_dialog_desktop_repair_steps else {}).get("optional") is True
            and auto_dialog_desktop_repair_try.get("command") == "batch_try"
            and (auto_dialog_desktop_repair_suggested_steps[0] if auto_dialog_desktop_repair_suggested_steps else {}).get("command") == "uia_selector_repair_find"
            and ((auto_dialog_desktop_repair_suggested_steps[0] if auto_dialog_desktop_repair_suggested_steps else {}).get("args") or {}).get("hwnd") == _DESKTOP_UIA_KEY
            and ((auto_dialog_desktop_repair_suggested_steps[0] if auto_dialog_desktop_repair_suggested_steps else {}).get("args") or {}).get("suggestion") == "$steps.desktop_dialog_uia_selector_repair_probe.result.original_result.failure_summary.selector_suggestions.0"
            and (auto_dialog_desktop_repair_suggested_steps[1] if len(auto_dialog_desktop_repair_suggested_steps) > 1 else {}).get("command") == "desktop_action"
            and (auto_dialog_ocr.get("args") or {}).get("text") == "OK"
            and (auto_dialog_image.get("args") or {}).get("template_path") == "ok.png"
            and (auto_dialog_coordinate.get("args") or {}).get("x") == 10
            and (auto_window_smart.get("args") or {}).get("title") == "Demo App"
            and (auto_window_smart.get("args") or {}).get("process") == "demo.exe"
            and (auto_window_smart.get("args") or {}).get("app") == "demo.exe"
            and "window_focus" not in [step.get("id") for step in auto_window_wait_steps]
            and "window_boundary" not in [step.get("id") for step in auto_window_wait_steps]
            and "window_observe" in [step.get("id") for step in auto_window_wait_steps]
            and (auto_window_wait_steps[-1] or {}).get("id") == "window_ready"
            and (auto_window_launch_steps[-1] or {}).get("id") == "launch_ready"
            and (auto_window_helper_smart.get("args") or {}).get("boundary") is True
            and auto_window_helper_wait_boundary.get("command") == "control_boundary"
            and (auto_window_helper_wait_boundary.get("args") or {}).get("hwnd") == "$steps.window_wait.result.value.hwnd"
            and (auto_window_helper_wait_boundary.get("extract") or {}).get("needs_elevation") == "$result.needs_elevation"
            and auto_window_helper_wait_helper.get("command") == "helper_status"
            and (auto_window_helper_wait_helper.get("args") or {}).get("start") == "$steps.window_boundary.result.value.needs_elevation"
            and (auto_window_helper_wait_helper.get("when") or {}).get("equals") is True
            and auto_window_helper_launch_boundary.get("command") == "control_boundary"
            and (auto_window_helper_launch_boundary.get("args") or {}).get("hwnd") == "$steps.window_launch.result.value.hwnd"
            and (auto_window_helper_launch_boundary.get("extract") or {}).get("needs_elevation") == "$result.needs_elevation"
            and auto_window_helper_launch_helper.get("command") == "helper_status"
            and (auto_window_helper_launch_helper.get("args") or {}).get("start") == "$steps.launch_boundary.result.value.needs_elevation"
            and (auto_window_helper_launch_helper.get("when") or {}).get("path") == "$steps.launch_boundary.result.value.needs_elevation"
            and (auto_window_helper_launch_helper.get("when") or {}).get("equals") is True
            and (auto_window_action_auto_steps[0] or {}).get("id") == "auto_window_target"
            and (auto_window_action_auto_steps[0] or {}).get("command") == "auto_window"
            and (auto_window_action_auto_steps[0].get("args") or {}).get("title") == "Demo App"
            and (auto_window_action_auto_steps[0].get("args") or {}).get("app") == "demo.exe"
            and "name" not in (auto_window_action_auto_steps[0].get("args") or {})
            and auto_window_action_preflight_plan_summary.get("has_boundary_preflight") is True
            and auto_window_action_preflight_plan_summary.get("has_conditional_helper") is True
            and auto_window_action_preflight_boundary.get("command") == "control_boundary"
            and (auto_window_action_preflight_boundary.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_preflight_boundary.get("extract") or {}).get("uipi_risk") == "$result.uipi_risk"
            and auto_window_action_preflight_helper.get("command") == "helper_status"
            and (auto_window_action_preflight_helper.get("args") or {}).get("elevated") == "$steps.auto_window_pre_boundary.result.value.needs_elevation"
            and (auto_window_action_preflight_helper.get("args") or {}).get("start") == "$steps.auto_window_pre_boundary.result.value.needs_elevation"
            and (auto_window_action_preflight_helper.get("when") or {}).get("path") == "$steps.auto_window_pre_boundary.result.value.needs_elevation"
            and (auto_window_action_preflight_helper.get("when") or {}).get("equals") is True
            and manual_plan_summary.get("has_smart_wait_repair") is True
            and manual_plan_summary.get("has_dialog_action_repair") is True
            and manual_plan_summary.get("has_native_wait_repair") is True
            and manual_plan_summary.get("has_selector_repair") is True
            and manual_plan_summary.get("has_uia_selector_repair") is True
            and (manual_plan_preview.get("options") or {}).get("repair_timeout") == 0.0
            and (manual_plan_preview.get("options") or {}).get("allow_suggestion_index") == "true"
            and manual_plan_summary_disabled.get("has_smart_wait_repair") is not True
            and manual_plan_summary_disabled.get("has_dialog_action_repair") is not True
            and manual_plan_summary_disabled.get("has_native_wait_repair") is not True
            and auto_window_action_preflight_action.get("command") == "batch_try"
            and auto_window_action_action_try.get("command") == "batch_try"
            and (auto_window_action_smart.get("steps") or [{}])[0].get("args", {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_smart.get("steps") or [{}])[0].get("args", {}).get("name") == "Play"
            and (auto_window_action_smart.get("steps") or [{}])[0].get("args", {}).get("timeout") == 0.2
            and (auto_window_action_image.get("steps") or [{}])[0].get("args", {}).get("template_path") == "play.png"
            and (auto_window_action_coordinate.get("steps") or [{}])[0].get("args", {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_wait.get("steps") or [{}])[-1].get("id") == "window_action_ready"
            and (auto_window_action_launch.get("steps") or [{}])[-1].get("id") == "window_action_ready"
            and (auto_window_action_text_smart.get("steps") or [{}])[0].get("args", {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_text_smart.get("steps") or [{}])[0].get("args", {}).get("text") == "query"
            and auto_window_action_repair_no_timeout_try.get("command") == "batch_try"
            and (auto_window_action_repair_no_timeout_smart.get("steps") or [{}])[0].get("command") == "smart_wait_click"
            and (auto_window_action_repair_no_timeout_smart.get("steps") or [{}])[0].get("args", {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_repair_no_timeout_smart.get("steps") or [{}])[0].get("args", {}).get("repair") is True
            and (auto_window_action_repair_no_timeout_smart.get("steps") or [{}])[0].get("args", {}).get("repair_timeout") == 0.0
            and "timeout" not in ((auto_window_action_repair_no_timeout_smart.get("steps") or [{}])[0].get("args", {}) or {})
            and auto_window_action_repair_no_timeout_plan_summary.get("has_smart_wait_repair") is True
            and auto_window_action_repair_no_timeout_plan_summary.get("has_selector_repair") is True
            and auto_window_action_repair_no_timeout_plan_summary.get("has_uia_selector_repair") is True
            and auto_window_action_key_try.get("command") == "batch_try"
            and auto_window_action_key_input.get("command") == "key"
            and (auto_window_action_key_input.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_key_input.get("args") or {}).get("keys") == "ctrl+s"
            and auto_window_action_key_post.get("command") == "uia_wait"
            and (auto_window_action_key_post.get("args") or {}).get("name") == "Saved"
            and (auto_window_action_key_post.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and auto_window_action_menu_action.get("command") == "menu_action"
            and (auto_window_action_menu_action.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_menu_action.get("args") or {}).get("path") == ["File", "Save"]
            and auto_window_action_file_dialog_action.get("command") == "file_dialog_action"
            and (auto_window_action_file_dialog_action.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_file_dialog_action.get("args") or {}).get("action") == "confirm"
            and (auto_window_action_file_dialog_action.get("args") or {}).get("path") == "C:\\Temp\\demo.txt"
            and (auto_window_action_file_dialog_action.get("args") or {}).get("verify_close") is True
            and "focus" in auto_window_action_recover_policy
            and "blocked_or_elevation" in auto_window_action_recover_policy
            and "clipboard_restore" in auto_window_action_recover_policy
            and auto_window_action_recover_selector_stable.get("command") == "uia_stable_wait"
            and auto_window_action_recover_selector_stable.get("optional") is True
            and (auto_window_action_recover_selector_stable.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_recover_selector_stable.get("args") or {}).get("timeout") == 0.2
            and (auto_window_action_recover_selector_stable.get("expect") or {}).get("path") == "$result.stable"
            and auto_window_action_recover_visual_stable.get("command") == "visual_stable_wait"
            and auto_window_action_recover_visual_stable.get("optional") is True
            and (auto_window_action_recover_visual_stable.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_recover_visual_stable.get("args") or {}).get("timeout") == 0.2
            and auto_window_action_recover_timeout_uia.get("command") == "uia_stable_wait"
            and auto_window_action_recover_timeout_visual.get("command") == "visual_stable_wait"
            and auto_window_action_recover_plan_summary.get("has_recovery") is True
            and "clipboard_restore" in auto_window_action_text_recover_policy
            and auto_window_action_text_recover_plan_summary.get("has_recovery") is True
            and auto_window_action_text_recover_clipboard_focus.get("command") == "focus_hwnd"
            and (auto_window_action_text_recover_clipboard_focus.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and auto_window_action_text_recover_clipboard_input.get("command") == "focused_input"
            and (auto_window_action_text_recover_clipboard_input.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_action_text_recover_clipboard_input.get("args") or {}).get("text") == "query"
            and (auto_window_action_text_recover_clipboard_input.get("args") or {}).get("timeout") == 0.2
            and (auto_window_action_text_recover_clipboard_input.get("expect") or {}).get("path") == "$result.ok"
            and auto_window_sequence_preflight_plan_summary.get("has_boundary_preflight") is True
            and auto_window_sequence_preflight_plan_summary.get("has_conditional_helper") is True
            and auto_window_sequence_preflight_boundary.get("command") == "control_boundary"
            and (auto_window_sequence_preflight_boundary.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_preflight_boundary.get("extract") or {}).get("can_send_input_likely") == "$result.can_send_input_likely"
            and auto_window_sequence_preflight_helper.get("command") == "helper_status"
            and (auto_window_sequence_preflight_helper.get("args") or {}).get("start") == "$steps.auto_window_pre_boundary.result.value.needs_elevation"
            and (auto_window_sequence_preflight_helper.get("when") or {}).get("equals") is True
            and auto_window_sequence_preflight_play.get("command") == "batch_try"
            and (auto_window_sequence_steps[0] or {}).get("id") == "auto_window_target"
            and auto_window_sequence_focus1.get("command") == "focus_hwnd"
            and (auto_window_sequence_focus1.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_search_branch.get("steps") or [{}])[0].get("args", {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_search_branch.get("steps") or [{}])[0].get("args", {}).get("text") == "query"
            and auto_window_sequence_delay1.get("command") == "batch_sleep"
            and (auto_window_sequence_delay1.get("args") or {}).get("delay") == 0.05
            and auto_window_sequence_focus2.get("command") == "focus_hwnd"
            and (auto_window_sequence_play_branch.get("steps") or [{}])[0].get("args", {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_play_branch.get("steps") or [{}])[0].get("args", {}).get("name") == "Play"
            and auto_window_sequence_delay2.get("command") == "batch_sleep"
            and (auto_window_sequence_delay2.get("args") or {}).get("delay") == 0.05
            and auto_window_sequence_key.get("command") == "key"
            and (auto_window_sequence_key.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_key.get("args") or {}).get("keys") == "ctrl+s"
            and (auto_window_sequence_repair_play_branch.get("steps") or [{}])[0].get("args", {}).get("repair") is True
            and (auto_window_sequence_repair_play_branch.get("steps") or [{}])[0].get("args", {}).get("repair_timeout") == 0.0
            and auto_window_sequence_repair_plan_summary.get("has_smart_wait_repair") is True
            and auto_window_sequence_repair_plan_summary.get("has_selector_repair") is True
            and auto_window_sequence_repair_plan_summary.get("has_uia_selector_repair") is True
            and auto_window_sequence_auto_kind_shortcut.get("command") == "batch_try"
            and auto_window_sequence_auto_kind_wheel.get("command") == "batch_try"
            and auto_window_sequence_auto_kind_drag.get("command") == "batch_try"
            and auto_window_sequence_auto_kind_shortcut_action.get("command") == "key"
            and (auto_window_sequence_auto_kind_shortcut_action.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_auto_kind_shortcut_action.get("args") or {}).get("keys") == "ctrl+f"
            and auto_window_sequence_auto_kind_wheel_action.get("command") == "scroll"
            and (auto_window_sequence_auto_kind_wheel_action.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_auto_kind_wheel_action.get("args") or {}).get("dy") == -2
            and auto_window_sequence_auto_kind_drag_action.get("command") == "drag"
            and (auto_window_sequence_auto_kind_drag_action.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_auto_kind_drag_action.get("args") or {}).get("start_x") == 1
            and (auto_window_sequence_auto_kind_drag_action.get("args") or {}).get("end_y") == 40
            and auto_window_sequence_auto_kind_menu.get("command") == "batch_try"
            and auto_window_sequence_auto_kind_menu_branch.get("id") == "step4_menu_action"
            and auto_window_sequence_auto_kind_menu_action.get("command") == "menu_action"
            and (auto_window_sequence_auto_kind_menu_action.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_auto_kind_menu_action.get("args") or {}).get("path") == ["File", "Open"]
            and auto_window_sequence_auto_kind_file_dialog.get("command") == "batch_try"
            and auto_window_sequence_auto_kind_file_dialog_branch.get("id") == "step5_file_dialog_action"
            and auto_window_sequence_auto_kind_file_dialog_action.get("command") == "file_dialog_action"
            and (auto_window_sequence_auto_kind_file_dialog_action.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_auto_kind_file_dialog_action.get("args") or {}).get("path") == "C:\\Temp\\open.txt"
            and (auto_window_sequence_auto_kind_file_dialog_action.get("args") or {}).get("verify_close") is True
            and bool(auto_window_sequence_autorecover_search.get("recover_on_failure"))
            and bool(auto_window_sequence_autorecover_play.get("recover_on_failure"))
            and auto_window_sequence_autorecover_plan_summary.get("has_recovery") is True
            and (auto_window_sequence_wait.get("steps") or [{}])[-1].get("id") == "window_sequence_ready"
            and (auto_window_sequence_launch.get("steps") or [{}])[-1].get("id") == "window_sequence_ready"
            and auto_window_sequence_recovery_play.get("command") == "batch_try"
            and (auto_window_sequence_recovery_primary.get("steps") or [{}])[0].get("id") == "play_attempt"
            and auto_window_sequence_recovery_focus.get("command") == "focus_hwnd"
            and (auto_window_sequence_recovery_focus.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and auto_window_sequence_recovery_dialog.get("command") == "batch_try"
            and auto_window_sequence_recovery_delay.get("command") == "batch_sleep"
            and (auto_window_sequence_recovery_delay.get("args") or {}).get("delay") == 0.03
            and auto_window_sequence_recovery_retry.get("id") == "play_retry"
            and (auto_window_sequence_recovery_retry_branch.get("steps") or [{}])[0].get("args", {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and (auto_window_sequence_recovery_steps[-1] or {}).get("id") == "window_sequence_ready"
            and auto_window_sequence_recovery_plan_summary.get("branch_count") == 4
            and auto_window_sequence_recovery_plan_summary.get("has_recovery") is True
            and auto_window_sequence_recovery_plan_summary.get("has_retry") is True
            and auto_window_sequence_recovery_plan_summary.get("has_focus_repair") is True
            and auto_window_sequence_recovery_plan_summary.get("has_visual_fallback") is True
            and auto_window_sequence_recovery_plan_summary.get("has_input_fallback") is True
            and "semantic" in (auto_window_sequence_recovery_plan_summary.get("layers") or [])
            and "visual" in (auto_window_sequence_recovery_plan_summary.get("layers") or [])
            and "input" in (auto_window_sequence_recovery_plan_summary.get("layers") or [])
            and auto_window_sequence_recovery_plan_auto.get("nested_branch_count", 0) >= 2
            and "play" in (auto_window_sequence_recovery_plan_auto.get("step_ids") or [])
            and "ocr_wait" in auto_window_sequence_post_play_commands
            and (auto_window_sequence_post_play_branch.get("steps") or [{}])[-1].get("args", {}).get("text") == "Playing"
            and auto_window_sequence_post_key.get("command") == "batch_try"
            and auto_window_sequence_post_key_commands == ["key", "uia_wait", "batch_repeat"]
            and (auto_window_sequence_post_key_branch.get("steps") or [{}, {}])[1].get("args", {}).get("name") == "Saved"
            and (auto_window_sequence_post_key_branch.get("steps") or [{}, {}])[1].get("args", {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and auto_window_sequence_post_key_absent_probe.get("command") == "ocr_find"
            and (auto_window_sequence_post_key_absent_probe.get("args") or {}).get("text") == "Saving"
            and (auto_window_sequence_post_key_absent_probe.get("args") or {}).get("hwnd") == "$steps.auto_window_target.result.value.hwnd"
            and auto_window_sequence_post_plan_summary.get("has_post_verification") is True
            and auto_window_sequence_post_plan_summary.get("has_negative_post_verification") is True
        )
        repeat_batch = execute_batch([
            {
                "id": "scroll_until_visible",
                "command": "batch_repeat",
                "max_iterations": 5,
                "steps": [
                    {"id": "probe", "command": "batch_value", "args": {"value": {"seen": True}}},
                ],
                "until": {"path": "$result.iteration", "equals": 3},
                "expect": [
                    {"path": "$result.iterations", "equals": 3},
                    {"path": "$result.result.value.seen", "equals": True},
                ],
            },
        ], stop_on_error=True)
        repeat_step_refs_batch = execute_batch([
            {
                "id": "repeat_until_step_ref",
                "command": "batch_repeat",
                "max_iterations": 4,
                "steps": [
                    {
                        "id": "check",
                        "command": "batch_value",
                        "args": {
                            "value": {
                                "ready": "$steps.check.result.value.next_ready",
                                "next_ready": True,
                            },
                        },
                    },
                ],
                "until": [
                    {"path": "$result.steps.check.result.value.ready", "equals": True},
                    {"path": "$result.last_result.value.ready", "equals": True},
                ],
                "expect": [
                    {"path": "$result.iterations", "equals": 2},
                    {"path": "$result.history[1].last_result.value.ready", "equals": True},
                ],
            },
            {
                "id": "copy_loop_named_step",
                "command": "batch_value",
                "args": {"value": "$steps.repeat_until_step_ref.result.history[1].steps.check.result.value.ready"},
                "expect": {"path": "$result.value", "equals": True},
            },
        ], stop_on_error=True)
        timeout_budget_batch = execute_batch([
            {"id": "too_late", "command": "batch_value", "args": {"value": "should-not-run"}},
        ], timeout_budget=0, trace=True)
        step_timeout_batch = execute_batch([
            {
                "id": "retry_budget",
                "command": "unknown_batch_retry_budget",
                "args": {},
                "retries": 2,
                "retry_delay": 0.05,
                "timeout_budget": 0.001,
            },
        ], trace=True)
        cleanup_batch = execute_batch([
            {
                "id": "fragile",
                "command": "unknown_batch_cleanup_probe",
                "args": {},
                "on_failure": [
                    {"id": "rescue", "command": "batch_value", "args": {"value": "rescued"}},
                ],
                "finally": [
                    {"id": "release", "command": "batch_value", "args": {"value": "released"}},
                ],
            },
        ], stop_on_error=True, trace=True)
        batch_cleanup = execute_batch(
            [
                {"id": "bad", "command": "unknown_batch_top_cleanup", "args": {}},
            ],
            stop_on_error=True,
            on_failure=[{"id": "top_rescue", "command": "batch_value", "args": {"value": "top-rescued"}}],
            finally_steps=[{"id": "top_finally", "command": "batch_value", "args": {"value": "top-released"}}],
            trace=True,
        )
        recovery_batch = execute_batch([
            {
                "id": "recoverable",
                "command": "unknown_batch_recovery_probe",
                "args": {},
                "recover_on_failure": {
                    "configuration": [
                        {"id": "repair_config", "command": "batch_value", "args": {"value": "config-repaired"}},
                    ],
                    "default": [
                        {"id": "repair_default", "command": "batch_value", "args": {"value": "default-repaired"}},
                    ],
                },
            },
        ], trace=True)
        repair_plan_batch = execute_batch([
            {
                "id": "repair_plan",
                "command": "batch_repair_plan",
                "args": {
                    "diagnostic_summary": {
                        "next_repair_candidates": [
                            *(native_repair_reports_diag.get("next_repair_candidates") or []),
                            *(native_wait_reports_diag.get("next_repair_candidates") or []),
                            *(uia_find_reports_diag.get("next_repair_candidates") or []),
                            *(window_find_reports_diag.get("next_repair_candidates") or []),
                        ]
                    },
                    "limit": 6,
                },
                "expect": [
                    {"path": "$result.ready", "equals": True},
                    {"path": "$result.ready_steps", "min_len": 4},
                    {"path": "$result.batch.commands", "min_len": 1},
                ],
            },
        ], stop_on_error=True)
        repair_plan_value = (repair_plan_batch.get("results") or [{}])[0].get("result", {})
        repair_plan_context_batch = execute_batch([
            {
                "id": "repair_plan_context",
                "command": "repair-plan",
                "args": {
                    "diagnostic_summary": {
                        "next_repair_candidates": [
                            {
                                "kind": "uia_selector_repair",
                                "command": "uia_selector_repair_find",
                                "source": "contract_probe",
                                "suggestion": {"automation_id": "searchBox", "control_type": "edit", "name": "Search"},
                            }
                        ]
                    },
                    "hwnd": 97531,
                },
            },
        ], stop_on_error=True)
        repair_plan_context_value = (repair_plan_context_batch.get("results") or [{}])[0].get("result", {})
        repair_plan_step_ref_batch = execute_batch([
            {
                "id": "repair_plan_step_ref",
                "path": "/batch-repair-plan",
                "data": {
                    "diagnostic_summary": {
                        "next_repair_steps": [
                            {
                                "id": "old_context_repair",
                                "command": "uia_selector_repair_find",
                                "args": {
                                    "hwnd": "$steps.failed_probe.result.hwnd",
                                    "suggestion": {"automation_id": "applyButton"},
                                },
                                "ready": True,
                            }
                        ]
                    },
                    "allow_step_refs": False,
                },
            },
        ], stop_on_error=True)
        repair_plan_step_ref_value = (repair_plan_step_ref_batch.get("results") or [{}])[0].get("result", {})
        auto_repair_probe_step = {
            "id": "diagnostic_repair_probe",
            "command": "batch_value",
            "args": {"value": {"repair_probe": "ran"}},
            "ready": True,
        }
        auto_repair_probe_failure = {
            "diagnostic_summary": {
                "next_repair_steps": [auto_repair_probe_step],
            }
        }
        auto_repair_disabled_batch = execute_batch([
            {
                "id": "failed_with_repair_probe",
                "command": "batch_value",
                "args": {"value": auto_repair_probe_failure},
                "expect": {"path": "$result.value.ok", "equals": True},
            },
        ], stop_on_error=True, trace=True)
        auto_repair_enabled_batch = execute_batch([
            {
                "id": "failed_with_repair_probe",
                "command": "batch_value",
                "args": {"value": auto_repair_probe_failure},
                "expect": {"path": "$result.value.ok", "equals": True},
            },
        ], stop_on_error=True, trace=True, auto_repair_diagnostics=True, repair_limit=2)
        auto_repair_result = auto_repair_enabled_batch.get("diagnostic_repair", {})
        rebinding_probe_failure = {
            "diagnostic_summary": {
                "next_repair_steps": [
                    {
                        "id": "repair_rebind_bundle",
                        "command": "batch_rebinding_probe",
                        "args": {"kind": "bundle"},
                        "ready": True,
                    },
                ],
            }
        }
        auto_repair_rebinding_batch = execute_batch([
            {
                "id": "failed_with_rebinding_probe",
                "command": "batch_value",
                "args": {"value": rebinding_probe_failure},
                "expect": {"path": "$result.value.ok", "equals": True},
            },
        ], stop_on_error=True, trace=True, auto_repair_diagnostics=True, repair_limit=4)
        auto_repair_rebindings = (auto_repair_rebinding_batch.get("diagnostic_repair") or {}).get("rebindings") or []
        globals()["_BATCH_RETRY_PROBE_STATE"] = {}
        auto_repair_retry_batch = execute_batch([
            {
                "id": "repair_then_retry",
                "command": "batch_retry_probe",
                "args": {
                    "key": "auto_repair_retry",
                    "pass_after": 2,
                    "diagnostic_summary": {
                        "next_repair_steps": [
                            {
                                "id": "retry_repair_probe",
                                "command": "batch_value",
                                "args": {"value": {"repair_probe": "retry-ran"}},
                                "ready": True,
                            }
                        ]
                    },
                },
            },
        ], stop_on_error=True, trace=True, diagnostic_repair_retry=True, diagnostic_repair_retry_limit=1)
        auto_repair_retry = (auto_repair_retry_batch.get("diagnostic_repair") or {}).get("retry", {})
        rebind_retry_probe_failure = {
            "diagnostic_summary": {
                "next_repair_steps": [
                    {
                        "id": "repair_rebind_retry_bundle",
                        "command": "batch_rebinding_probe",
                        "args": {"kind": "bundle"},
                        "ready": True,
                    },
                ],
            }
        }
        auto_repair_rebind_retry_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry",
                "command": "batch_rebind_target_probe",
                "args": {
                    "kind": "uia",
                    "hwnd": 1,
                    "index": 1,
                    "view": "control",
                    **rebind_retry_probe_failure,
                },
            },
        ], stop_on_error=True, trace=True, diagnostic_repair_rebind_retry=True, diagnostic_repair_rebind_retry_limit=1, repair_limit=4)
        auto_repair_rebind_retry = (auto_repair_rebind_retry_batch.get("diagnostic_repair") or {}).get("rebind_retry", {})
        auto_repair_rebind_retry_item = (auto_repair_rebind_retry.get("results") or [{}])[0]
        auto_repair_rebind_retry_args = ((auto_repair_rebind_retry_item.get("result") or {}).get("args") or {})
        auto_repair_rebind_retry_auto_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry_auto",
                "command": "batch_auto",
                "args": {
                    "kind": "click",
                    "hwnd": 1,
                    "index": 1,
                    "view": "control",
                    "layers": "semantic",
                    **rebind_retry_probe_failure,
                },
                "branches": [
                    {
                        "id": "auto_rebind_probe_branch",
                        "command": "batch_rebind_target_probe",
                        "args": {
                            "kind": "uia",
                            "hwnd": 1,
                            "index": 1,
                            "view": "control",
                        },
                    },
                ],
            },
        ], stop_on_error=True, trace=True, diagnostic_repair_rebind_retry=True, diagnostic_repair_rebind_retry_limit=1, repair_limit=4)
        auto_repair_rebind_retry_auto = (auto_repair_rebind_retry_auto_batch.get("diagnostic_repair") or {}).get("rebind_retry", {})
        auto_repair_rebind_retry_auto_item = (auto_repair_rebind_retry_auto.get("results") or [{}])[0]
        auto_repair_rebind_retry_auto_branch_result = (((auto_repair_rebind_retry_auto_item.get("result") or {}).get("candidates") or [{}])[0].get("results") or [{}])[0]
        auto_repair_rebind_retry_auto_args = ((auto_repair_rebind_retry_auto_branch_result.get("result") or {}).get("args") or {})
        auto_repair_rebind_retry_nested_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry_nested",
                "command": "batch_try",
                "args": {
                    **rebind_retry_probe_failure,
                },
                "branches": [
                    {
                        "id": "nested_rebind_probe_branch",
                        "steps": [
                            {
                                "id": "nested_rebind_probe",
                                "command": "batch_rebind_target_probe",
                                "args": {
                                    "kind": "uia",
                                    "hwnd": 1,
                                    "index": 1,
                                    "view": "control",
                                },
                            },
                        ],
                    },
                ],
            },
        ], stop_on_error=True, trace=True, diagnostic_repair_rebind_retry=True, diagnostic_repair_rebind_retry_limit=1, repair_limit=4)
        auto_repair_rebind_retry_nested = (auto_repair_rebind_retry_nested_batch.get("diagnostic_repair") or {}).get("rebind_retry", {})
        auto_repair_rebind_retry_nested_item = (auto_repair_rebind_retry_nested.get("results") or [{}])[0]
        auto_repair_rebind_retry_nested_branch_result = (((auto_repair_rebind_retry_nested_item.get("result") or {}).get("candidates") or [{}])[0].get("results") or [{}])[0]
        auto_repair_rebind_retry_nested_args = ((auto_repair_rebind_retry_nested_branch_result.get("result") or {}).get("args") or {})
        auto_repair_rebind_retry_skip_batch = execute_batch([
            {
                "id": "repair_rebind_retry_skip",
                "command": "batch_retry_probe",
                "args": {
                    "key": "auto_repair_rebind_retry_skip",
                    "reset": True,
                    "pass_after": 99,
                    **rebind_retry_probe_failure,
                },
            },
        ], stop_on_error=True, trace=True, diagnostic_repair_rebind_retry=True, diagnostic_repair_rebind_retry_limit=1, repair_limit=4)
        auto_repair_rebind_retry_skip = (auto_repair_rebind_retry_skip_batch.get("diagnostic_repair") or {}).get("rebind_retry", {})
        auto_repair_rebind_retry_skip_item = (auto_repair_rebind_retry_skip.get("results") or [{}])[0]
        auto_repair_rebind_retry_autorecover_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry_autorecover_window",
                "command": "batch_auto",
                "args": {
                    "kind": "window_action",
                    "action-kind": "click",
                    "hwnd": 1,
                    "index": 1,
                    "view": "control",
                    "auto-recover": "true",
                    "layers": "semantic",
                    **rebind_retry_probe_failure,
                },
                "branches": [
                    {
                        "id": "autorecover_window_rebind_probe_branch",
                        "command": "batch_rebind_target_probe",
                        "args": {
                            "kind": "uia",
                            "hwnd": 1,
                            "index": 1,
                            "view": "control",
                        },
                    },
                ],
            },
        ], stop_on_error=True, trace=True, repair_limit=4)
        auto_repair_rebind_retry_autorecover = (auto_repair_rebind_retry_autorecover_batch.get("diagnostic_repair") or {}).get("rebind_retry", {})
        auto_repair_rebind_retry_autorecover_item = (auto_repair_rebind_retry_autorecover.get("results") or [{}])[0]
        auto_repair_rebind_retry_autorecover_branch_result = (((auto_repair_rebind_retry_autorecover_item.get("result") or {}).get("candidates") or [{}])[0].get("results") or [{}])[0]
        auto_repair_rebind_retry_autorecover_args = ((auto_repair_rebind_retry_autorecover_branch_result.get("result") or {}).get("args") or {})
        auto_repair_rebind_retry_autorecover_nested_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry_autorecover_nested_try",
                "command": "batch_try",
                "args": {
                    **rebind_retry_probe_failure,
                },
                "branches": [
                    {
                        "id": "autorecover_nested_try_branch",
                        "steps": [
                            {
                                "id": "autorecover_nested_auto",
                                "command": "batch_auto",
                                "args": {
                                    "kind": "window_action",
                                    "action-kind": "click",
                                    "hwnd": 1,
                                    "index": 1,
                                    "view": "control",
                                    "auto-recover": "true",
                                    "layers": "semantic",
                                },
                                "branches": [
                                    {
                                        "id": "autorecover_nested_rebind_probe_branch",
                                        "command": "batch_rebind_target_probe",
                                        "args": {
                                            "kind": "uia",
                                            "hwnd": 1,
                                            "index": 1,
                                            "view": "control",
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ], stop_on_error=True, trace=True, repair_limit=4)
        auto_repair_rebind_retry_autorecover_nested = (auto_repair_rebind_retry_autorecover_nested_batch.get("diagnostic_repair") or {}).get("rebind_retry", {})
        auto_repair_rebind_retry_autorecover_nested_item = (auto_repair_rebind_retry_autorecover_nested.get("results") or [{}])[0]
        auto_repair_rebind_retry_autorecover_nested_branch_result = (((((auto_repair_rebind_retry_autorecover_nested_item.get("result") or {}).get("candidates") or [{}])[0].get("results") or [{}])[0].get("result") or {}).get("candidates") or [{}])[0].get("results", [{}])[0]
        auto_repair_rebind_retry_autorecover_nested_args = ((auto_repair_rebind_retry_autorecover_nested_branch_result.get("result") or {}).get("args") or {})
        auto_repair_rebind_retry_autorecover_alternatives_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry_autorecover_alternatives",
                "command": "batch_try",
                "args": {
                    **rebind_retry_probe_failure,
                },
                "alternatives": [
                    {
                        "id": "autorecover_alternatives_branch",
                        "steps": [
                            {
                                "id": "autorecover_alternatives_auto",
                                "command": "batch_auto",
                                "args": {
                                    "kind": "window_action",
                                    "action-kind": "click",
                                    "hwnd": 1,
                                    "index": 1,
                                    "view": "control",
                                    "auto-recover": "true",
                                    "layers": "semantic",
                                },
                                "branches": [
                                    {
                                        "id": "autorecover_alternatives_rebind_probe_branch",
                                        "command": "batch_rebind_target_probe",
                                        "args": {
                                            "kind": "uia",
                                            "hwnd": 1,
                                            "index": 1,
                                            "view": "control",
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ], stop_on_error=True, trace=True, repair_limit=4)
        auto_repair_rebind_retry_autorecover_alternatives = (auto_repair_rebind_retry_autorecover_alternatives_batch.get("diagnostic_repair") or {}).get("rebind_retry", {})
        auto_repair_rebind_retry_autorecover_alternatives_item = (auto_repair_rebind_retry_autorecover_alternatives.get("results") or [{}])[0]
        auto_repair_rebind_retry_autorecover_alternatives_branch_result = (((((auto_repair_rebind_retry_autorecover_alternatives_item.get("result") or {}).get("candidates") or [{}])[0].get("results") or [{}])[0].get("result") or {}).get("candidates") or [{}])[0].get("results", [{}])[0]
        auto_repair_rebind_retry_autorecover_alternatives_args = ((auto_repair_rebind_retry_autorecover_alternatives_branch_result.get("result") or {}).get("args") or {})
        auto_repair_rebind_retry_autorecover_alias_commands = [
            {
                "id": "repair_then_rebind_retry_autorecover_workflow_alias",
                "command": "batch_try",
                "branches": [
                    {
                        "id": "autorecover_workflow_alias_branch",
                        "steps": [
                            {
                                "id": "autorecover_workflow_alias_sequence",
                                "command": "batch_auto",
                                "args": {
                                    "kind": "window_sequence",
                                    "hwnd": 1,
                                    "layers": "semantic",
                                    "workflow": [
                                        {
                                            "id": "autorecover_workflow_alias_auto",
                                            "command": "batch_auto",
                                            "args": {
                                                "kind": "window_action",
                                                "action-kind": "click",
                                                "hwnd": 1,
                                                "index": 1,
                                                "view": "control",
                                                "auto-recover": "true",
                                                "layers": "semantic",
                                            },
                                            "branches": [
                                                {
                                                    "id": "autorecover_workflow_alias_rebind_probe_branch",
                                                    "command": "batch_rebind_target_probe",
                                                    "args": {
                                                        "kind": "uia",
                                                        "hwnd": 1,
                                                        "index": 1,
                                                        "view": "control",
                                                    },
                                                },
                                            ],
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            },
        ]
        auto_repair_rebind_retry_autorecover_alias_detected = _batch_auto_recover_rebind_retry_requested(auto_repair_rebind_retry_autorecover_alias_commands)
        auto_repair_rebind_retry_autorecover_alias_patch = _batch_rebinding_retry_item(
            auto_repair_rebind_retry_autorecover_alias_commands[0],
            {"kind": "uia_element", "hwnd": 24681, "index": 7, "view": "raw"},
        ) or {}
        auto_repair_rebind_retry_autorecover_alias_paths = auto_repair_rebind_retry_autorecover_alias_patch.get("patched_paths") or []
        auto_repair_rebind_retry_autorecover_recovery_commands = [
            {
                "id": "repair_then_rebind_retry_autorecover_recovery_map",
                "command": "batch_try",
                "branches": [
                    {
                        "id": "autorecover_recovery_map_branch",
                        "steps": [
                            {
                                "id": "autorecover_recovery_map_holder",
                                "command": "batch_value",
                                "args": {"value": {"ok": False}},
                                "recover_on_failure": {
                                    "retry_original": False,
                                    "selector": [
                                        {
                                            "id": "autorecover_recovery_map_auto",
                                            "command": "batch_auto",
                                            "args": {
                                                "kind": "window_action",
                                                "action-kind": "click",
                                                "hwnd": 1,
                                                "index": 1,
                                                "view": "control",
                                                "auto-recover": "true",
                                                "layers": "semantic",
                                            },
                                            "branches": [
                                                {
                                                    "id": "autorecover_recovery_map_rebind_probe_branch",
                                                    "command": "batch_rebind_target_probe",
                                                    "args": {
                                                        "kind": "uia",
                                                        "hwnd": 1,
                                                        "index": 1,
                                                        "view": "control",
                                                    },
                                                },
                                            ],
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                ],
            },
        ]
        auto_repair_rebind_retry_autorecover_recovery_detected = _batch_auto_recover_rebind_retry_requested(auto_repair_rebind_retry_autorecover_recovery_commands)
        auto_repair_rebind_retry_autorecover_recovery_patch = _batch_rebinding_retry_item(
            auto_repair_rebind_retry_autorecover_recovery_commands[0],
            {"kind": "uia_element", "hwnd": 24681, "index": 7, "view": "raw"},
        ) or {}
        auto_repair_rebind_retry_autorecover_recovery_paths = auto_repair_rebind_retry_autorecover_recovery_patch.get("patched_paths") or []
        auto_repair_rebind_retry_post_patch = _batch_rebinding_retry_item(
            {
                "id": "repair_then_rebind_retry_post_steps",
                "command": "batch_auto",
                "args": {
                    "kind": "window_action",
                    "action-kind": "click",
                    "hwnd": 1,
                    "index": 1,
                    "view": "control",
                    "auto-recover": "true",
                    "layers": "semantic",
                    "post_steps": [
                        {
                            "id": "post_rebind_probe",
                            "command": "batch_rebind_target_probe",
                            "args": {
                                "kind": "uia",
                                "hwnd": 1,
                                "index": 1,
                                "view": "control",
                            },
                        },
                    ],
                },
            },
            {"kind": "uia_element", "hwnd": 24681, "index": 7, "view": "raw"},
        ) or {}
        auto_repair_rebind_retry_post_paths = auto_repair_rebind_retry_post_patch.get("patched_paths") or []
        auto_repair_rebind_retry_autorecover_item_disabled_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry_autorecover_item_disabled",
                "command": "batch_auto",
                "diagnostic_repair_rebind_retry": False,
                "args": {
                    "kind": "window_action",
                    "action-kind": "click",
                    "hwnd": 1,
                    "index": 1,
                    "view": "control",
                    "auto-recover": "true",
                    "layers": "semantic",
                    **rebind_retry_probe_failure,
                },
                "branches": [
                    {
                        "id": "autorecover_item_disabled_rebind_probe_branch",
                        "command": "batch_rebind_target_probe",
                        "args": {
                            "kind": "uia",
                            "hwnd": 1,
                            "index": 1,
                            "view": "control",
                        },
                    },
                ],
            },
        ], stop_on_error=True, trace=True, repair_limit=4)
        auto_repair_rebind_retry_autorecover_args_disabled_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry_autorecover_args_disabled",
                "command": "batch_auto",
                "args": {
                    "kind": "window_action",
                    "action-kind": "click",
                    "hwnd": 1,
                    "index": 1,
                    "view": "control",
                    "auto-recover": "true",
                    "diagnostic_repair_rebind_retry": False,
                    "layers": "semantic",
                    **rebind_retry_probe_failure,
                },
                "branches": [
                    {
                        "id": "autorecover_args_disabled_rebind_probe_branch",
                        "command": "batch_rebind_target_probe",
                        "args": {
                            "kind": "uia",
                            "hwnd": 1,
                            "index": 1,
                            "view": "control",
                        },
                    },
                ],
            },
        ], stop_on_error=True, trace=True, repair_limit=4)
        auto_repair_rebind_retry_option_disabled_options = _batch_execute_options({
            "diagnostic-repair-rebind-retry": "false",
        })
        auto_repair_rebind_retry_autorecover_option_disabled_batch = execute_batch([
            {
                "id": "repair_then_rebind_retry_autorecover_option_disabled",
                "command": "batch_auto",
                "args": {
                    "kind": "window_action",
                    "action-kind": "click",
                    "hwnd": 1,
                    "index": 1,
                    "view": "control",
                    "auto-recover": "true",
                    "layers": "semantic",
                    **rebind_retry_probe_failure,
                },
                "branches": [
                    {
                        "id": "autorecover_option_disabled_rebind_probe_branch",
                        "command": "batch_rebind_target_probe",
                        "args": {
                            "kind": "uia",
                            "hwnd": 1,
                            "index": 1,
                            "view": "control",
                        },
                    },
                ],
            },
        ], stop_on_error=True, trace=True, repair_limit=4, **auto_repair_rebind_retry_option_disabled_options)
        helper_smart_commands = [
            {"command": "smart_click", "args": {"hwnd": 1, "name": "OK"}},
            {"command": "smart_wait_click", "args": {"hwnd": 1, "name": "OK", "timeout": 0.1}},
            {"command": "smart_text", "args": {"hwnd": 1, "name": "Search", "text": "query"}},
            {"command": "smart_wait_text", "args": {"hwnd": 1, "name": "Search", "text": "query", "timeout": 0.1}},
        ]
        helper_smart_paths = [
            {"path": "/smart_click", "data": {"hwnd": 1, "name": "OK"}},
            {"path": "/smart_wait_click", "data": {"hwnd": 1, "name": "OK", "timeout": 0.1}},
            {"path": "/smart_text", "data": {"hwnd": 1, "name": "Search", "text": "query"}},
            {"path": "/smart_wait_text", "data": {"hwnd": 1, "name": "Search", "text": "query", "timeout": 0.1}},
        ]
        helper_repair_commands = [
            {"command": "uia_selector_repair_find", "args": {"hwnd": 1, "suggestion": {"name": "OK"}}},
            {"command": "uia_cell_selector_repair_find", "args": {"hwnd": 1, "suggestion": {"pattern": "GridItem"}, "row": 0, "column": 1}},
            {"command": "win32_selector_repair_find", "args": {"hwnd": 1, "suggestion": {"automation_id": "101"}}},
        ]
        helper_repair_paths = [
            {"path": "/uia_selector_repair_find", "data": {"hwnd": 1, "suggestion": {"name": "OK"}}},
            {"path": "/uia_cell_selector_repair_find", "data": {"hwnd": 1, "suggestion": {"pattern": "GridItem"}, "row": 0, "column": 1}},
            {"path": "/win32_selector_repair_find", "data": {"hwnd": 1, "suggestion": {"automation_id": "101"}}},
        ]
        helper_alias_commands = [
            {"command": "smart-click", "args": {"hwnd": 1, "name": "OK"}},
            {"command": "smart-wait-click", "args": {"hwnd": 1, "name": "OK", "timeout": 0.1}},
            {"command": "smart_text_input", "args": {"hwnd": 1, "name": "Search", "text": "query"}},
            {"command": "smart-wait-text-input", "args": {"hwnd": 1, "name": "Search", "text": "query", "timeout": 0.1}},
            {"command": "smart-control-action", "args": {"hwnd": 1, "name": "OK"}},
            {"command": "smart-wait-control-action", "args": {"hwnd": 1, "name": "OK", "timeout": 0.1}},
            {"command": "smart-select-item", "args": {"hwnd": 1, "item": "Choice"}},
            {"command": "smart-wait-select-item", "args": {"hwnd": 1, "item": "Choice", "timeout": 0.1}},
            {"command": "smart-grid-cell", "args": {"hwnd": 1, "row": 0, "column": 1}},
            {"command": "smart-wait-listview-cell", "args": {"hwnd": 1, "row": 0, "column": 1, "timeout": 0.1}},
            {"command": "type-text", "args": {"text": "hello"}},
            {"command": "press-key", "args": {"key": "enter"}},
            {"command": "uia-repair-find", "args": {"hwnd": 1, "suggestion": {"name": "OK"}}},
            {"command": "uia-cell-repair-find", "args": {"hwnd": 1, "suggestion": {"pattern": "GridItem"}, "row": 0, "column": 1}},
            {"command": "native-repair-find", "args": {"hwnd": 1, "suggestion": {"automation_id": "101"}}},
        ]
        helper_alias_paths = [
            {"path": "/smart-click", "data": {"hwnd": 1, "name": "OK"}},
            {"path": "smart-wait-click", "data": {"hwnd": 1, "name": "OK", "timeout": 0.1}},
            {"path": "/smart-text", "data": {"hwnd": 1, "name": "Search", "text": "query"}},
            {"path": "smart-wait-text", "data": {"hwnd": 1, "name": "Search", "text": "query", "timeout": 0.1}},
            {"path": "/smart-text-input", "data": {"hwnd": 1, "name": "Search", "text": "query"}},
            {"path": "smart-wait-text-input", "data": {"hwnd": 1, "name": "Search", "text": "query", "timeout": 0.1}},
            {"path": "/smart-control-action", "data": {"hwnd": 1, "name": "OK"}},
            {"path": "smart-wait-control-action", "data": {"hwnd": 1, "name": "OK", "timeout": 0.1}},
            {"path": "/smart-select-item", "data": {"hwnd": 1, "item": "Choice"}},
            {"path": "smart-wait-select-item", "data": {"hwnd": 1, "item": "Choice", "timeout": 0.1}},
            {"path": "/smart-grid-cell", "data": {"hwnd": 1, "row": 0, "column": 1}},
            {"path": "smart-wait-listview-cell", "data": {"hwnd": 1, "row": 0, "column": 1, "timeout": 0.1}},
            {"path": "/type-text", "data": {"text": "hello"}},
            {"path": "press-key", "data": {"key": "enter"}},
            {"path": "/uia-repair-find", "data": {"hwnd": 1, "suggestion": {"name": "OK"}}},
            {"path": "uia-cell-repair-find", "data": {"hwnd": 1, "suggestion": {"pattern": "GridItem"}, "row": 0, "column": 1}},
            {"path": "win32-selector-repair-find", "data": {"hwnd": 1, "suggestion": {"automation_id": "101"}}},
        ]
        helper_alias_normalized = [_batch_item_for_helper(item) for item in helper_alias_commands + helper_alias_paths]
        helper_smart_round_trips = {
            command: _BATCH_PATH_TO_COMMAND.get(_BATCH_COMMAND_TO_PATH.get(command)) == command
            for command in ("smart_click", "smart_wait_click", "smart_text", "smart_wait_text", "uia_selector_repair_find", "uia_cell_selector_repair_find", "win32_selector_repair_find")
        }
        helper_recovery_routing_ok = bool(not _can_helper_handle_batch([
            {"command": "smart_click", "args": {"hwnd": 1, "name": "OK", "recover_on_failure": {"default": []}}},
        ]))
        helper_smart_routing_ok = bool(
            _can_helper_handle_batch(helper_smart_commands)
            and _can_helper_handle_batch(helper_smart_paths)
            and _can_helper_handle_batch(helper_repair_commands)
            and _can_helper_handle_batch(helper_repair_paths)
            and _can_helper_handle_batch(helper_alias_commands)
            and _can_helper_handle_batch(helper_alias_paths)
            and _batch_contains_uia(helper_smart_commands)
            and _batch_contains_uia(helper_smart_paths)
            and _batch_contains_uia(helper_repair_commands)
            and _batch_contains_uia(helper_repair_paths)
            and _batch_contains_uia(helper_alias_commands)
            and _batch_contains_uia(helper_alias_paths)
            and all(helper_smart_round_trips.values())
            and [item.get("command") for item in helper_alias_normalized[:15]] == [
                "smart_click",
                "smart_wait_click",
                "smart_text",
                "smart_wait_text",
                "smart_click",
                "smart_wait_click",
                "smart_select",
                "smart_wait_select",
                "smart_cell",
                "smart_wait_cell",
                "type",
                "key",
                "uia_selector_repair_find",
                "uia_cell_selector_repair_find",
                "win32_selector_repair_find",
            ]
            and [item.get("path") for item in helper_alias_normalized[15:]] == [
                "/smart_click",
                "/smart_wait_click",
                "/smart_text",
                "/smart_wait_text",
                "/smart_text",
                "/smart_wait_text",
                "/smart_click",
                "/smart_wait_click",
                "/smart_select",
                "/smart_wait_select",
                "/smart_cell",
                "/smart_wait_cell",
                "/type_text",
                "/press_key",
                "/uia_selector_repair_find",
                "/uia_cell_selector_repair_find",
                "/win32_selector_repair_find",
            ]
        )
        helper_timeout_contract: Dict[str, Any] = {"ok": False}
        helper_timeout_contract_ok = False
        try:
            helper_spec = importlib.util.spec_from_file_location("_desktop_control_helper_probe", _helper_path())
            helper_module = importlib.util.module_from_spec(helper_spec) if helper_spec and helper_spec.loader else None
            if helper_module is None or helper_spec is None or helper_spec.loader is None:
                raise RuntimeError("helper module could not be loaded")
            helper_spec.loader.exec_module(helper_module)
            smart_timeout_default = helper_module._smart_repair_worker_timeout({"hwnd": 1})
            smart_timeout_repair_budget = helper_module._smart_repair_worker_timeout({"hwnd": 1, "repair_timeout": 2.5})
            smart_timeout_repair_flag = helper_module._smart_repair_worker_timeout({"hwnd": 1, "repair": True})
            smart_timeout_override = helper_module._smart_repair_worker_timeout({"hwnd": 1, "repair_timeout": 2.5, "uia_timeout": 3.25})
            wait_timeout_default = helper_module._wait_repair_worker_timeout({"hwnd": 1, "timeout": 2.0}, 2.0)
            wait_timeout_repair_budget = helper_module._wait_repair_worker_timeout({"hwnd": 1, "timeout": 2.0, "repair_timeout": 2.5}, 2.0)
            wait_timeout_repair_flag = helper_module._wait_repair_worker_timeout({"hwnd": 1, "timeout": 2.0, "repair": True}, 2.0)
            wait_timeout_override = helper_module._wait_repair_worker_timeout({"hwnd": 1, "timeout": 2.0, "repair_timeout": 2.5, "uia_timeout": 3.25}, 2.0)
            helper_post_default = _smart_action_helper_timeout({"hwnd": 1})
            helper_post_repair_budget = _smart_action_helper_timeout({"hwnd": 1, "repair_timeout": 2.5})
            helper_post_repair_flag = _smart_action_helper_timeout({"hwnd": 1, "repair": True})
            helper_post_direct_budget = _smart_action_helper_timeout({"hwnd": 1, "timeout": 1.5, "repair_timeout": 2.5}, timeout=1.5)
            helper_post_prebudgeted = _smart_action_helper_timeout({"hwnd": 1, "timeout": 2.0, "repair_timeout": 1.25}, timeout=3.25)
            helper_timeout_contract_ok = bool(
                smart_timeout_default == 5.0
                and smart_timeout_repair_budget == 7.5
                and smart_timeout_repair_flag == 6.0
                and smart_timeout_override == 3.25
                and wait_timeout_default == 4.0
                and wait_timeout_repair_budget == 5.5
                and wait_timeout_repair_flag == 4.0
                and wait_timeout_override == 3.25
                and helper_post_default == 4.0
                and helper_post_repair_budget == 7.5
                and helper_post_repair_flag == 6.0
                and helper_post_direct_budget == 5.0
                and helper_post_prebudgeted == 4.25
            )
            helper_timeout_contract = {
                "default": smart_timeout_default,
                "repair_timeout": smart_timeout_repair_budget,
                "repair_flag": smart_timeout_repair_flag,
                "override": smart_timeout_override,
                "wait_default": wait_timeout_default,
                "wait_repair_timeout": wait_timeout_repair_budget,
                "wait_repair_flag": wait_timeout_repair_flag,
                "wait_override": wait_timeout_override,
                "post_default": helper_post_default,
                "post_repair_timeout": helper_post_repair_budget,
                "post_repair_flag": helper_post_repair_flag,
                "post_direct_timeout_repair": helper_post_direct_budget,
                "post_prebudgeted_wait_repair": helper_post_prebudgeted,
                "ok": helper_timeout_contract_ok,
            }
        except Exception as e:
            helper_timeout_contract = {"ok": False, "error": str(e)}
        cli_repair_calls: Dict[str, Dict[str, Any]] = {}
        real_argv = list(sys.argv)
        real_ensure_helper = globals().get("_ensure_helper")
        real_cli_smart_click = globals().get("smart_click")
        real_cli_smart_wait_click = globals().get("smart_wait_click")
        real_cli_smart_text_input = globals().get("smart_text_input")
        real_cli_smart_wait_text_input = globals().get("smart_wait_text_input")
        real_cli_smart_select = globals().get("smart_select")
        real_cli_smart_cell = globals().get("smart_cell")
        try:
            class _CliProbeStdout(io.StringIO):
                def reconfigure(self, **kwargs: Any) -> None:
                    return None

            def fake_cli_ensure_helper() -> None:
                return None

            def fake_cli_smart_click(hwnd: Optional[int], **kwargs: Any) -> Dict[str, Any]:
                cli_repair_calls["smart_click"] = {"hwnd": hwnd, **kwargs}
                return {"ok": True, "cli_probe": "smart_click"}

            def fake_cli_smart_wait_click(hwnd: Optional[int], **kwargs: Any) -> Dict[str, Any]:
                cli_repair_calls["smart_wait_click"] = {"hwnd": hwnd, **kwargs}
                return {"ok": True, "cli_probe": "smart_wait_click"}

            def fake_cli_smart_text_input(hwnd: Optional[int], text: str, **kwargs: Any) -> Dict[str, Any]:
                cli_repair_calls["smart_text"] = {"hwnd": hwnd, "text": text, **kwargs}
                return {"ok": True, "cli_probe": "smart_text"}

            def fake_cli_smart_wait_text_input(hwnd: Optional[int], text: str, **kwargs: Any) -> Dict[str, Any]:
                cli_repair_calls["smart_wait_text"] = {"hwnd": hwnd, "text": text, **kwargs}
                return {"ok": True, "cli_probe": "smart_wait_text"}

            def fake_cli_smart_select(hwnd: Optional[int], **kwargs: Any) -> Dict[str, Any]:
                cli_repair_calls["smart_select"] = {"hwnd": hwnd, **kwargs}
                return {"ok": True, "cli_probe": "smart_select"}

            def fake_cli_smart_cell(hwnd: Optional[int], **kwargs: Any) -> Dict[str, Any]:
                cli_repair_calls["smart_cell"] = {"hwnd": hwnd, **kwargs}
                return {"ok": True, "cli_probe": "smart_cell"}

            globals()["_ensure_helper"] = fake_cli_ensure_helper
            globals()["smart_click"] = fake_cli_smart_click
            globals()["smart_wait_click"] = fake_cli_smart_wait_click
            globals()["smart_text_input"] = fake_cli_smart_text_input
            globals()["smart_wait_text_input"] = fake_cli_smart_wait_text_input
            globals()["smart_select"] = fake_cli_smart_select
            globals()["smart_cell"] = fake_cli_smart_cell
            for argv in (
                [
                    "tools.py",
                    "smart-click",
                    "1",
                    "--name",
                    "OK",
                    "--repair-timeout",
                    "0.1",
                ],
                [
                    "tools.py",
                    "smart-wait-click",
                    "1",
                    "--name",
                    "OK",
                    "--repair-timeout",
                    "0",
                    "--no-repair",
                ],
                [
                    "tools.py",
                    "smart-wait-text",
                    "1",
                    "query",
                    "--name",
                    "Search",
                    "--repair",
                    "--repair-timeout",
                    "0.25",
                ],
                [
                    "tools.py",
                    "smart-text",
                    "1",
                    "query",
                    "--name",
                    "Search",
                    "--selector-repair-timeout",
                    "0.2",
                ],
                [
                    "tools.py",
                    "smart-select",
                    "1",
                    "Choice",
                    "--repair",
                    "--repair-timeout",
                    "0.3",
                ],
                [
                    "tools.py",
                    "smart-cell",
                    "1",
                    "--row",
                    "2",
                    "--column",
                    "1",
                    "--repair-timeout",
                    "0.4",
                ],
            ):
                sys.argv = argv
                with contextlib.redirect_stdout(_CliProbeStdout()):
                    main()
        finally:
            sys.argv = real_argv
            if real_ensure_helper is not None:
                globals()["_ensure_helper"] = real_ensure_helper
            if real_cli_smart_click is not None:
                globals()["smart_click"] = real_cli_smart_click
            if real_cli_smart_wait_click is not None:
                globals()["smart_wait_click"] = real_cli_smart_wait_click
            if real_cli_smart_text_input is not None:
                globals()["smart_text_input"] = real_cli_smart_text_input
            if real_cli_smart_wait_text_input is not None:
                globals()["smart_wait_text_input"] = real_cli_smart_wait_text_input
            if real_cli_smart_select is not None:
                globals()["smart_select"] = real_cli_smart_select
            if real_cli_smart_cell is not None:
                globals()["smart_cell"] = real_cli_smart_cell
        cli_repair_contract_ok = bool(
            (cli_repair_calls.get("smart_click") or {}).get("repair_timeout") == 0.1
            and (cli_repair_calls.get("smart_wait_click") or {}).get("repair") is False
            and (cli_repair_calls.get("smart_wait_click") or {}).get("repair_timeout") == 0.0
            and (cli_repair_calls.get("smart_text") or {}).get("repair_timeout") == 0.2
            and (cli_repair_calls.get("smart_wait_text") or {}).get("repair") is True
            and (cli_repair_calls.get("smart_wait_text") or {}).get("repair_timeout") == 0.25
            and (cli_repair_calls.get("smart_select") or {}).get("repair") is True
            and (cli_repair_calls.get("smart_select") or {}).get("repair_timeout") == 0.3
            and (cli_repair_calls.get("smart_cell") or {}).get("repair_timeout") == 0.4
        )
        relocated_click_payload = {
            "ok": True,
            "message": "Clicked element [5] at screen(10,20)",
            "hwnd": 1357,
            "index": 5,
            "relocated": True,
            "relocation": {
                "from_index": 5,
                "to_index": 9,
                "score": 590,
                "reasons": ["automation_id", "parent_automation_id"],
            },
        }
        relocated_click_result = _uia_click_message_result(json.dumps(relocated_click_payload, ensure_ascii=False), hwnd=1357, index=5)
        plain_click_result = _uia_click_message_result("Clicked element [2] at screen(10,20)", hwnd=1357, index=2)
        error_click_result = _uia_click_message_result("Error: Element index 2 not found", hwnd=1357, index=2)
        batch_click_relocation: Dict[str, Any] = {}
        batch_uia_click_relocation: Dict[str, Any] = {}
        batch_desktop_click_relocation: Dict[str, Any] = {}
        real_click_index = globals().get("click_index")
        try:
            def fake_relocated_click_index(
                hwnd: int,
                index: int,
                button: str = "left",
                clicks: int = 1,
                max_depth: Optional[int] = None,
                max_elements: Optional[int] = None,
                view: Optional[str] = None,
            ) -> str:
                payload = dict(relocated_click_payload)
                payload["hwnd"] = int(hwnd)
                payload["index"] = int(index)
                payload["button"] = button
                payload["clicks"] = int(clicks)
                return json.dumps(payload, ensure_ascii=False)

            globals()["click_index"] = fake_relocated_click_index
            batch_click_relocation = _batch_execute_local("click_index", {"hwnd": 1357, "index": 5})
            batch_uia_click_relocation = _batch_execute_local("uia_click_index", {"hwnd": 1357, "index": 5})
            batch_desktop_click_relocation = _batch_execute_local("desktop_click_index", {"index": 5})
        finally:
            if real_click_index is not None:
                globals()["click_index"] = real_click_index
        uia_click_message_contract_ok = bool(
            relocated_click_result.get("relocated") is True
            and relocated_click_result.get("relocation", {}).get("to_index") == 9
            and plain_click_result.get("ok") is True
            and plain_click_result.get("message", "").startswith("Clicked element")
            and error_click_result.get("ok") is False
            and error_click_result.get("error") == "Element index 2 not found"
            and batch_click_relocation.get("relocated") is True
            and batch_click_relocation.get("relocation", {}).get("to_index") == 9
            and batch_uia_click_relocation.get("relocated") is True
            and batch_uia_click_relocation.get("relocation", {}).get("to_index") == 9
            and batch_desktop_click_relocation.get("relocated") is True
            and batch_desktop_click_relocation.get("relocation", {}).get("to_index") == 9
            and batch_desktop_click_relocation.get("hwnd") == _DESKTOP_UIA_KEY
        )
        mouse_context_result: Dict[str, Any] = {}
        mouse_context_batch: Dict[str, Any] = {}
        real_mouse_position = globals().get("mouse_position")
        real_window_from_point = globals().get("window_from_point")
        real_element_from_point = globals().get("element_from_point")
        real_msaa_from_point = globals().get("msaa_from_point")
        try:
            globals()["mouse_position"] = lambda: {"x": 12, "y": 34}
            globals()["window_from_point"] = lambda x=None, y=None, **kwargs: {
                "ok": True,
                "screen": {"x": int(x or 0), "y": int(y or 0)},
                "window": {"hwnd": 111, "title": "Root"},
                "child": {"hwnd": 222, "class_name": "Edit"},
                "root": {"hwnd": 333},
                "root_owner": {"hwnd": 444},
            }
            globals()["element_from_point"] = lambda x=None, y=None, **kwargs: {
                "element": {"name": "Search", "control_type": "edit"},
                "screen": {"x": int(x or 0), "y": int(y or 0)},
            }
            globals()["msaa_from_point"] = lambda x=None, y=None, **kwargs: {
                "msaa": {"name": "Search", "role_text": "text"},
                "screen": {"x": int(x or 0), "y": int(y or 0)},
            }
            mouse_context_result = mouse_context()
            mouse_context_batch = _batch_execute_local("cursor_context", {"include-msaa": "false"})
        finally:
            if real_mouse_position is not None:
                globals()["mouse_position"] = real_mouse_position
            if real_window_from_point is not None:
                globals()["window_from_point"] = real_window_from_point
            if real_element_from_point is not None:
                globals()["element_from_point"] = real_element_from_point
            if real_msaa_from_point is not None:
                globals()["msaa_from_point"] = real_msaa_from_point
        mouse_context_contract_ok = bool(
            mouse_context_result.get("ok") is True
            and mouse_context_result.get("source") == "cursor"
            and (mouse_context_result.get("screen") or {}).get("x") == 12
            and (mouse_context_result.get("targets") or {}).get("child") == 222
            and ((mouse_context_result.get("uia") or {}).get("element") or {}).get("name") == "Search"
            and ((mouse_context_result.get("msaa") or {}).get("msaa") or {}).get("role_text") == "text"
            and mouse_context_batch.get("ok") is True
            and "msaa" not in mouse_context_batch
            and (mouse_context_batch.get("targets") or {}).get("root_owner") == 444
        )

        report["steps"]["normalize"] = {
            "success_string": success_string,
            "error_string": error_string,
            "warning_string": warning_string,
            "helper_clipboard_warning": helper_clipboard_warning,
            "warning_failure": warning_failure,
            "helper_warning_failure": helper_warning_failure,
            "value_result": value_result,
            "empty_result": empty_result,
            "normalized_item": normalized_item,
        }
        report["steps"]["summary"] = summary
        report["steps"]["local_all"] = local_all
        report["steps"]["local_stop_on_error"] = local_stop
        report["steps"]["malformed_all"] = malformed_all
        report["steps"]["malformed_stop_on_error"] = malformed_stop
        report["steps"]["retry_fail"] = retry_fail
        report["steps"]["ref_batch"] = ref_batch
        report["steps"]["arg_alias_batch"] = arg_alias_batch
        report["steps"]["sleep_batch"] = sleep_batch
        report["steps"]["batch_alias_contracts"] = batch_alias_contracts
        report["steps"]["expect_pass"] = expect_pass
        report["steps"]["expect_fail"] = expect_fail
        report["steps"]["expect_retry_fail"] = expect_retry_fail
        report["steps"]["expect_refs"] = expect_refs
        report["steps"]["expect_ops"] = expect_ops
        report["steps"]["expect_ops_fail"] = expect_ops_fail
        report["steps"]["extract_batch"] = extract_batch
        report["steps"]["extract_fail"] = extract_fail
        report["steps"]["conditional_batch"] = conditional_batch
        report["steps"]["named_ref_batch"] = named_ref_batch
        report["steps"]["optional_batch"] = optional_batch
        report["steps"]["try_batch"] = try_batch
        report["steps"]["try_fail_batch"] = try_fail_batch
        report["steps"]["try_relocation_batch"] = try_relocation_batch
        report["steps"]["native_repair_diagnostic_summary"] = {
            "branch": native_repair_branch_diag,
            "reports": native_repair_reports_diag,
        }
        report["steps"]["native_wait_diagnostic_summary"] = {
            "branch": native_wait_branch_diag,
            "reports": native_wait_reports_diag,
        }
        report["steps"]["window_find_diagnostic_summary"] = {
            "failure_summary": window_find_failure_summary,
            "branch": window_find_branch_diag,
            "reports": window_find_reports_diag,
        }
        report["steps"]["auto_explicit"] = auto_explicit
        report["steps"]["auto_relocation_batch"] = auto_relocation_batch
        report["steps"]["auto_path_explicit"] = auto_path_explicit
        report["steps"]["auto_generation"] = {
            "click": auto_click_branch_ids,
            "text": auto_text_branch_ids,
            "select": auto_select_branch_ids,
            "select_check": {
                "smart": auto_select_check_smart,
                "native": auto_select_check_native,
                "conservative": auto_select_check_conservative_ids,
                "allow_unverified": auto_select_check_unverified_ids,
                "allow_unverified_with_row": auto_select_check_unverified_row_ids,
                "verified": auto_select_check_verified_branches,
                "state_verified": auto_select_check_state_verified_branches,
                "present_repair": auto_select_present_repair_wait,
                "present_repair_plan_summary": auto_select_present_repair_plan_summary,
                "present_native_repair": auto_select_present_native_repair_wait,
                "present_native_repair_plan_summary": auto_select_present_native_repair_plan_summary,
                "present_native_repair_disabled": auto_select_present_native_repair_disabled_wait,
                "present_native_repair_disabled_plan_summary": auto_select_present_native_repair_disabled_plan_summary,
            },
            "cell": auto_cell_branch_ids,
            "key": auto_key_branch_ids,
            "key_branch": auto_key_branch,
            "hover": {
                "branches": auto_hover_branch_ids,
                "uia": auto_hover,
                "coordinate": auto_hover_coord,
                "desktop_coordinate": auto_desktop_hover,
            },
            "scroll": auto_scroll_branch_ids,
            "scroll_wheel": auto_scroll_wheel,
            "scroll_keyboard": auto_scroll_keyboard,
            "desktop_scroll": auto_desktop_scroll,
            "desktop_scroll_with_keyboard": auto_desktop_scroll_with_keyboard,
            "drag": auto_drag,
            "menu": auto_menu_branch_ids,
            "menu_action": auto_menu,
            "menu_system": auto_menu_system,
            "file_dialog": auto_file_dialog_branch_ids,
            "file_dialog_action": auto_file_dialog,
            "file_dialog_info": auto_file_dialog_info,
            "selector_repair_click": auto_selector_repair_click_ids,
            "selector_repair_text": auto_selector_repair_text_ids,
            "selector_repair_select": auto_selector_repair_select_ids,
            "selector_repair_cell": auto_uia_repair_cell_ids,
            "uia_repair_click": auto_uia_repair_click,
            "uia_repair_text": auto_uia_repair_text,
            "uia_repair_select": auto_uia_repair_select,
            "uia_repair_cell": auto_uia_repair_cell,
            "native_repair_click": auto_native_repair_click,
            "native_repair_text": auto_native_repair_text,
            "native_repair_select": auto_native_repair_select,
            "native_repair_cell": auto_native_repair_cell,
            "native_repair_disabled": auto_native_repair_disabled_ids,
            "uia_repair_disabled": auto_uia_repair_disabled_ids,
            "uia_repair_cell_disabled": auto_uia_repair_cell_disabled_ids,
            "selector_repair_plan": auto_selector_repair_plan_summary,
            "cell_selector_repair_plan": auto_cell_selector_repair_plan_summary,
            "smart_wait_repair": {
                "click": auto_smart_wait_repair_click,
                "click_plan_summary": auto_smart_wait_repair_click_plan_summary,
                "uia_alias": auto_smart_wait_repair_uia_alias,
                "uia_alias_plan_summary": auto_smart_wait_repair_uia_alias_plan_summary,
                "cell": auto_smart_wait_repair_cell,
                "cell_plan_summary": auto_smart_wait_repair_cell_plan_summary,
                "click_no_timeout": auto_smart_wait_repair_no_timeout,
                "click_no_timeout_plan_summary": auto_smart_wait_repair_no_timeout_plan_summary,
                "text_no_timeout": auto_smart_wait_repair_text_no_timeout,
                "text_no_timeout_plan_summary": auto_smart_wait_repair_text_no_timeout_plan_summary,
                "select_no_timeout": auto_smart_wait_repair_select_no_timeout,
                "select_no_timeout_plan_summary": auto_smart_wait_repair_select_no_timeout_plan_summary,
                "cell_no_timeout": auto_smart_wait_repair_cell_no_timeout,
                "cell_no_timeout_plan_summary": auto_smart_wait_repair_cell_no_timeout_plan_summary,
                "timeout_only": auto_smart_wait_repair_timeout_only,
                "timeout_only_plan_summary": auto_smart_wait_repair_timeout_only_plan_summary,
                "timeout_only_disabled": auto_smart_wait_repair_timeout_only_disabled,
                "timeout_only_disabled_plan_summary": auto_smart_wait_repair_timeout_only_disabled_plan_summary,
            },
            "visual_row_click": auto_visual_row_click,
            "ocr_scroll_click": auto_ocr_scroll_click,
            "image_scroll_click": auto_image_scroll_click,
            "visual_row_select": auto_visual_row_select,
            "visual_select": auto_visual_select_ids,
            "visual_select_image": auto_visual_select_image,
            "visual_select_image_scroll": auto_visual_select_image_scroll,
            "visual_select_ocr": auto_visual_select_ocr,
            "visual_select_ocr_scroll": auto_visual_select_ocr_scroll,
            "visual_text": auto_visual_text_ids,
            "visual_text_image": auto_visual_text_image,
            "visual_text_image_scroll": auto_visual_text_image_scroll,
            "visual_text_ocr": auto_visual_text_ocr,
            "visual_text_ocr_scroll": auto_visual_text_ocr_scroll,
            "visual_text_desktop_ocr": auto_visual_text_desktop_ocr,
            "pre_visual_click": auto_pre_visual_click_image,
            "pre_visual_dialog": auto_pre_visual_dialog_ocr,
            "pre_uia_click": auto_pre_uia_click_smart,
            "pre_uia_dialog": auto_pre_uia_dialog_uia,
            "post_click": auto_post_click_smart,
            "post_click_plan_summary": auto_post_click_plan_summary,
            "post_absent": auto_post_absent_smart,
            "post_absent_plan_summary": auto_post_absent_plan_summary,
            "post_pixel": auto_post_pixel_smart,
            "post_pixel_plan_summary": auto_post_pixel_plan_summary,
            "desktop_post": auto_desktop_post_ocr,
            "desktop_absent_post": auto_desktop_absent_ocr,
            "desktop_pixel_post": auto_desktop_pixel_ocr,
            "visual_row_cell": auto_visual_row_cell,
            "visual_row_disabled": auto_visual_row_disabled_ids,
            "visual_row_path": visual_row_path_item,
            "dialog": auto_dialog_branch_ids,
            "dialog_command": auto_dialog_command,
            "dialog_native": auto_dialog_native,
            "dialog_smart": auto_dialog_smart,
            "dialog_repair_smart": auto_dialog_repair_smart,
            "dialog_repair_plan_summary": auto_dialog_repair_plan_summary,
            "dialog_stable_alias_smart": auto_dialog_stable_alias_smart,
            "dialog_uia_repair_alias_smart": auto_dialog_uia_repair_alias_smart,
            "dialog_uia_repair_alias_plan_summary": auto_dialog_uia_repair_alias_plan_summary,
            "dialog_repair_timeout_only": auto_dialog_repair_timeout_only_smart,
            "dialog_repair_timeout_only_plan_summary": auto_dialog_repair_timeout_only_plan_summary,
            "dialog_repair_timeout_only_disabled": auto_dialog_repair_timeout_only_disabled_smart,
            "dialog_repair_timeout_only_disabled_plan_summary": auto_dialog_repair_timeout_only_disabled_plan_summary,
            "window": auto_window_branch_ids,
            "window_helper": {
                "auto": auto_window_helper_smart,
                "wait_boundary": auto_window_helper_wait_boundary,
                "wait_helper": auto_window_helper_wait_helper,
                "launch_boundary": auto_window_helper_launch_boundary,
                "launch_helper": auto_window_helper_launch_helper,
            },
            "window_plan_summary": auto_window_plan_summary,
            "window_action": auto_window_action_branch_ids,
            "window_action_plan_summary": auto_window_action_plan_summary,
            "window_action_preflight": auto_window_action_preflight_auto,
            "window_action_preflight_plan_summary": auto_window_action_preflight_plan_summary,
            "manual_plan_summary": manual_plan_summary,
            "manual_plan_summary_disabled": manual_plan_summary_disabled,
            "window_action_auto": auto_window_action_auto,
            "window_action_text": auto_window_action_text_auto,
            "window_action_key": auto_window_action_key_auto,
            "window_action_menu": auto_window_action_menu_auto,
            "window_action_file_dialog": auto_window_action_file_dialog_auto,
            "window_action_repair_no_timeout": auto_window_action_repair_no_timeout_auto,
            "window_action_repair_no_timeout_plan_summary": auto_window_action_repair_no_timeout_plan_summary,
            "window_action_auto_recover": auto_window_action_recover_auto,
            "window_action_auto_recover_plan_summary": auto_window_action_recover_plan_summary,
            "window_action_text_auto_recover": auto_window_action_text_recover_auto,
            "window_action_text_auto_recover_plan_summary": auto_window_action_text_recover_plan_summary,
            "window_sequence": auto_window_sequence_branch_ids,
            "window_sequence_plan_summary": auto_window_sequence_plan_summary,
            "window_sequence_preflight": auto_window_sequence_preflight_auto,
            "window_sequence_preflight_plan_summary": auto_window_sequence_preflight_plan_summary,
            "window_sequence_auto": auto_window_sequence_auto,
            "window_sequence_repair": auto_window_sequence_repair_auto,
            "window_sequence_repair_plan_summary": auto_window_sequence_repair_plan_summary,
            "window_sequence_auto_kind": auto_window_sequence_auto_kind,
            "window_sequence_auto_kind_menu": auto_window_sequence_auto_kind_menu,
            "window_sequence_auto_kind_file_dialog": auto_window_sequence_auto_kind_file_dialog,
            "window_sequence_auto_recover": auto_window_sequence_autorecover_auto,
            "window_sequence_auto_recover_plan_summary": auto_window_sequence_autorecover_plan_summary,
            "window_sequence_recovery": auto_window_sequence_recovery_auto,
            "window_sequence_recovery_plan_summary": auto_window_sequence_recovery_plan_summary,
            "window_sequence_post": auto_window_sequence_post_auto,
            "window_sequence_post_plan_summary": auto_window_sequence_post_plan_summary,
            "layered": auto_layered_branch_ids,
            "ok": auto_generation_ok,
        }
        report["steps"]["auto_dialog_explicit"] = auto_dialog_explicit
        report["steps"]["auto_window_plan"] = auto_window_plan
        report["steps"]["auto_window_action_plan"] = auto_window_action_plan
        report["steps"]["auto_window_action_preflight_plan"] = auto_window_action_preflight_plan
        report["steps"]["risky_plan_summary"] = risky_plan_summary
        report["steps"]["auto_window_sequence_plan"] = auto_window_sequence_plan
        report["steps"]["bracket_ref_batch"] = bracket_ref_batch
        report["steps"]["repeat_batch"] = repeat_batch
        report["steps"]["repeat_step_refs_batch"] = repeat_step_refs_batch
        report["steps"]["timeout_budget_batch"] = timeout_budget_batch
        report["steps"]["step_timeout_batch"] = step_timeout_batch
        report["steps"]["safety_gate"] = {
            "blocked": safety_gate_blocked,
            "nested_blocked": safety_gate_nested_blocked,
            "confirmed": safety_gate_confirmed,
        }
        report["steps"]["cleanup_batch"] = cleanup_batch
        report["steps"]["batch_cleanup"] = batch_cleanup
        report["steps"]["recovery_batch"] = recovery_batch
        report["steps"]["clipboard_recovery_batch"] = clipboard_recovery_batch
        report["steps"]["repair_plan_batch"] = {
            "plan": repair_plan_batch,
            "context": repair_plan_context_batch,
            "step_ref": repair_plan_step_ref_batch,
        }
        report["steps"]["auto_repair_diagnostics"] = {
            "disabled": auto_repair_disabled_batch,
            "enabled": auto_repair_enabled_batch,
            "rebindings": auto_repair_rebinding_batch,
            "retry": auto_repair_retry_batch,
            "rebind_retry": auto_repair_rebind_retry_batch,
            "rebind_retry_auto": auto_repair_rebind_retry_auto_batch,
            "rebind_retry_nested": auto_repair_rebind_retry_nested_batch,
            "rebind_retry_skip": auto_repair_rebind_retry_skip_batch,
            "rebind_retry_autorecover": auto_repair_rebind_retry_autorecover_batch,
            "rebind_retry_autorecover_nested": auto_repair_rebind_retry_autorecover_nested_batch,
            "rebind_retry_autorecover_alternatives": auto_repair_rebind_retry_autorecover_alternatives_batch,
            "rebind_retry_autorecover_alias": {
                "detected": auto_repair_rebind_retry_autorecover_alias_detected,
                "patch_count": auto_repair_rebind_retry_autorecover_alias_patch.get("patch_count"),
                "patched_paths": auto_repair_rebind_retry_autorecover_alias_paths,
                "patched_args_preview": auto_repair_rebind_retry_autorecover_alias_patch.get("patched_args_preview"),
            },
            "rebind_retry_autorecover_recovery_map": {
                "detected": auto_repair_rebind_retry_autorecover_recovery_detected,
                "patch_count": auto_repair_rebind_retry_autorecover_recovery_patch.get("patch_count"),
                "patched_paths": auto_repair_rebind_retry_autorecover_recovery_paths,
                "patched_args_preview": auto_repair_rebind_retry_autorecover_recovery_patch.get("patched_args_preview"),
            },
            "rebind_retry_post_steps": {
                "patch_count": auto_repair_rebind_retry_post_patch.get("patch_count"),
                "patched_paths": auto_repair_rebind_retry_post_paths,
                "patched_args_preview": auto_repair_rebind_retry_post_patch.get("patched_args_preview"),
            },
            "rebind_retry_autorecover_item_disabled": auto_repair_rebind_retry_autorecover_item_disabled_batch,
            "rebind_retry_autorecover_args_disabled": auto_repair_rebind_retry_autorecover_args_disabled_batch,
            "rebind_retry_autorecover_option_disabled": auto_repair_rebind_retry_autorecover_option_disabled_batch,
        }
        report["steps"]["helper_smart_routing"] = {
            "canonical_commands": [item.get("command") for item in helper_smart_commands],
            "canonical_paths": [item.get("path") for item in helper_smart_paths],
            "alias_normalized": helper_alias_normalized,
            "round_trips": helper_smart_round_trips,
            "recovery_local_only": helper_recovery_routing_ok,
            "worker_timeout_contract": helper_timeout_contract,
            "ok": helper_smart_routing_ok,
        }
        report["steps"]["cli_repair_contract"] = {
            "calls": cli_repair_calls,
            "ok": cli_repair_contract_ok,
        }
        report["steps"]["uia_click_message_result"] = {
            "relocated": relocated_click_result,
            "plain": plain_click_result,
            "error": error_click_result,
            "batch_click": batch_click_relocation,
            "batch_uia_click": batch_uia_click_relocation,
            "batch_desktop_click": batch_desktop_click_relocation,
            "ok": uia_click_message_contract_ok,
        }
        report["steps"]["mouse_context"] = {
            "result": mouse_context_result,
            "batch": mouse_context_batch,
            "ok": mouse_context_contract_ok,
        }
        report["ok"] = bool(
            success_string.get("ok") is True
            and success_string.get("message") == "Pressed: enter"
            and error_string.get("ok") is False
            and error_string.get("error") == "bad key"
            and warning_string.get("ok") is False
            and warning_string.get("clipboard_restore_ok") is False
            and (warning_failure or {}).get("failure_category") == "clipboard_restore"
            and helper_clipboard_warning.get("ok") is True
            and (helper_warning_failure or {}).get("failure_category") == "clipboard_restore"
            and value_result.get("ok") is True
            and value_result.get("value") == ["probe"]
            and empty_result.get("ok") is False
            and normalized_item.get("index") == 7
            and normalized_item.get("result", {}).get("ok") is True
            and summary.get("ok") is False
            and summary.get("failed_count") == 3
            and "clipboard_restore" in (summary.get("failure_categories") or [])
            and summary.get("diagnostic_summary", {}).get("clipboard_restore")
            and local_all.get("ok") is False
            and local_all.get("failed_count") == 2
            and local_all.get("count") == 2
            and isinstance(local_all.get("elapsed_ms"), (int, float))
            and all(isinstance((item.get("result") if isinstance(item, dict) else None), dict) for item in local_all.get("results", []))
            and all(isinstance((item.get("elapsed_ms") if isinstance(item, dict) else None), (int, float)) for item in local_all.get("results", []))
            and local_stop.get("ok") is False
            and local_stop.get("failed_count") == 1
            and local_stop.get("count") == 1
            and local_stop.get("total_count") == 2
            and local_stop.get("stopped_on_error") is True
            and isinstance((local_stop.get("failures") or [{}])[0].get("elapsed_ms"), (int, float))
            and malformed_all.get("ok") is False
            and malformed_all.get("failed_count") == 3
            and malformed_all.get("count") == 3
            and isinstance(malformed_all.get("elapsed_ms"), (int, float))
            and (malformed_all.get("failures") or [{}])[0].get("error") == "invalid_batch_item"
            and (malformed_all.get("failures") or [{}, {}])[1].get("error") == "invalid_batch_args"
            and (malformed_all.get("failures") or [{}, {}, {}])[2].get("error") == "invalid_batch_args"
            and malformed_stop.get("ok") is False
            and malformed_stop.get("failed_count") == 1
            and malformed_stop.get("count") == 1
            and malformed_stop.get("total_count") == 2
            and malformed_stop.get("stopped_on_error") is True
            and retry_fail.get("ok") is False
            and retry_fail.get("failed_count") == 1
            and (retry_fail.get("results") or [{}])[0].get("attempts") == 3
            and (retry_fail.get("results") or [{}])[0].get("retries") == 2
            and (retry_fail.get("failures") or [{}])[0].get("attempts") == 3
            and (retry_fail.get("failures") or [{}])[0].get("retries") == 2
            and ref_batch.get("ok") is True
            and ref_batch.get("count") == 2
            and (ref_batch.get("results") or [{}, {}])[1].get("result", {}).get("value", {}).get("copied_hwnd") == 12345
            and (ref_batch.get("results") or [{}, {}])[1].get("result", {}).get("value", {}).get("nested") == [7]
            and arg_alias_batch.get("ok") is True
            and [
                item.get("result", {}).get("value")
                for item in (arg_alias_batch.get("results") or [])
            ] == ["command-data", "path-args", "path-data"]
            and sleep_batch.get("ok") is True
            and [item.get("result", {}).get("slept") for item in (sleep_batch.get("results") or [])] == [0.0, 0.0]
            and all(item.get("ok") is True for item in batch_alias_contracts)
            and expect_pass.get("ok") is True
            and (expect_pass.get("results") or [{}])[0].get("result", {}).get("expectation", {}).get("ok") is True
            and len((expect_pass.get("results") or [{}])[0].get("result", {}).get("expectation", {}).get("checks") or []) == 4
            and expect_fail.get("ok") is False
            and expect_fail.get("failed_count") == 1
            and (expect_fail.get("results") or [{}])[0].get("result", {}).get("error") == "batch_expectation_failed"
            and (expect_fail.get("failures") or [{}])[0].get("expectation", {}).get("ok") is False
            and expect_retry_fail.get("ok") is False
            and (expect_retry_fail.get("results") or [{}])[0].get("attempts") == 3
            and (expect_retry_fail.get("failures") or [{}])[0].get("error") == "batch_expectation_failed"
            and expect_refs.get("ok") is True
            and expect_refs.get("count") == 2
            and (expect_refs.get("results") or [{}, {}])[1].get("result", {}).get("expectation", {}).get("ok") is True
            and expect_ops.get("ok") is True
            and len((expect_ops.get("results") or [{}])[0].get("result", {}).get("expectation", {}).get("checks") or []) == 9
            and expect_ops_fail.get("ok") is False
            and (expect_ops_fail.get("results") or [{}])[0].get("result", {}).get("error") == "batch_expectation_failed"
            and (expect_ops_fail.get("failures") or [{}])[0].get("expectation", {}).get("ok") is False
            and extract_batch.get("ok") is True
            and (extract_batch.get("results") or [{}])[0].get("result", {}).get("extracted") is True
            and (extract_batch.get("results") or [{}])[0].get("result", {}).get("value", {}).get("first") == "Save"
            and (extract_batch.get("results") or [{}, {}])[1].get("result", {}).get("value") == "Save"
            and extract_fail.get("ok") is False
            and (extract_fail.get("results") or [{}])[0].get("result", {}).get("error") == "batch_extract_failed"
            and (extract_fail.get("failures") or [{}])[0].get("extract", {}).get("error") == "extract_path_missing"
            and conditional_batch.get("ok") is True
            and conditional_batch.get("count") == 4
            and (conditional_batch.get("results") or [{}, {}])[1].get("result", {}).get("skipped") is True
            and (conditional_batch.get("results") or [{}, {}])[1].get("result", {}).get("skip_reason") == "when_false"
            and (conditional_batch.get("results") or [{}, {}, {}])[2].get("result", {}).get("skipped") is True
            and (conditional_batch.get("results") or [{}, {}, {}])[2].get("result", {}).get("skip_reason") == "unless_true"
            and (conditional_batch.get("results") or [{}, {}, {}, {}])[3].get("result", {}).get("value") == "continued"
            and (conditional_batch.get("results") or [{}, {}, {}, {}])[3].get("result", {}).get("expectation", {}).get("ok") is True
            and named_ref_batch.get("ok") is True
            and named_ref_batch.get("count") == 4
            and (named_ref_batch.get("results") or [{}])[0].get("id") == "launch_info"
            and (named_ref_batch.get("results") or [{}, {}])[1].get("id") == "copied"
            and (named_ref_batch.get("results") or [{}, {}])[1].get("result", {}).get("value") == 2468
            and (named_ref_batch.get("results") or [{}, {}, {}])[2].get("id") == "conditional"
            and (named_ref_batch.get("results") or [{}, {}, {}])[2].get("result", {}).get("value", {}).get("legacy_hwnd") == 2468
            and (named_ref_batch.get("results") or [{}, {}, {}, {}])[3].get("id") == "final"
            and (named_ref_batch.get("results") or [{}, {}, {}, {}])[3].get("result", {}).get("value") == "ready"
            and bracket_ref_batch.get("ok") is True
            and (bracket_ref_batch.get("results") or [{}])[0].get("result", {}).get("value", {}).get("hwnd") == 1357
            and (bracket_ref_batch.get("results") or [{}])[0].get("result", {}).get("value", {}).get("state") == "ready"
            and (bracket_ref_batch.get("results") or [{}, {}])[1].get("result", {}).get("value", {}).get("hwnd") == 1357
            and (bracket_ref_batch.get("results") or [{}, {}])[1].get("result", {}).get("expectation", {}).get("ok") is True
            and optional_batch.get("ok") is True
            and optional_batch.get("failed_count") == 0
            and optional_batch.get("count") == 2
            and (optional_batch.get("results") or [{}])[0].get("allow_failure") is True
            and (optional_batch.get("results") or [{}])[0].get("attempts") == 2
            and (optional_batch.get("results") or [{}])[0].get("result", {}).get("tolerated_failure") is True
            and (optional_batch.get("results") or [{}])[0].get("result", {}).get("failure", {}).get("error")
            and (optional_batch.get("results") or [{}, {}])[1].get("result", {}).get("value") == "fallback-used"
            and try_batch.get("ok") is True
            and try_batch.get("count") == 2
            and (try_batch.get("results") or [{}, {}])[1].get("result", {}).get("selected") == 1
            and (try_batch.get("results") or [{}, {}])[1].get("result", {}).get("selected_id") == "win32"
            and len((try_batch.get("results") or [{}, {}])[1].get("result", {}).get("candidates") or []) == 2
            and ((try_batch.get("results") or [{}, {}])[1].get("result", {}).get("candidates") or [{}])[0].get("ok") is False
            and ((try_batch.get("results") or [{}, {}])[1].get("result", {}).get("candidates") or [{}, {}])[1].get("selected") is True
            and (try_batch.get("results") or [{}, {}])[1].get("result", {}).get("result", {}).get("value", {}).get("layer") == "win32"
            and try_fail_batch.get("ok") is False
            and (try_fail_batch.get("results") or [{}])[0].get("result", {}).get("failure_summary", {}).get("failed_branch_count") == 2
            and "semantic_provider" in ((try_fail_batch.get("results") or [{}])[0].get("result", {}).get("failure_summary", {}).get("failure_categories") or [])
            and "visual" in ((try_fail_batch.get("results") or [{}])[0].get("result", {}).get("failure_summary", {}).get("failure_categories") or [])
            and try_relocation_batch.get("ok") is True
            and try_relocation_batch.get("diagnostic_summary", {}).get("relocated") is True
            and try_relocation_batch.get("diagnostic_summary", {}).get("uia_relocation_count") == 1
            and try_relocation_batch.get("diagnostic_summary", {}).get("last_uia_relocation", {}).get("to_index") == 9
            and (try_relocation_batch.get("results") or [{}])[0].get("result", {}).get("diagnostic_summary", {}).get("relocated") is True
            and (try_relocation_batch.get("results") or [{}])[0].get("result", {}).get("diagnostic_summary", {}).get("uia_relocation_count") == 1
            and (try_relocation_batch.get("results") or [{}])[0].get("result", {}).get("diagnostic_summary", {}).get("selected", {}).get("last_uia_relocation", {}).get("to_index") == 9
            and (try_relocation_batch.get("results") or [{}])[0].get("result", {}).get("result", {}).get("value", {}).get("relocation", {}).get("to_index") == 9
            and native_repair_branch_diag.get("native_selector_repair_available") is True
            and (native_repair_branch_diag.get("native_selector_suggestions") or [{}])[0].get("automation_id") == "101"
            and (native_repair_branch_diag.get("next_repair_candidates") or [{}])[0].get("kind") == "native_selector_repair"
            and (native_repair_branch_diag.get("next_repair_candidates") or [{}])[0].get("command") == "win32_selector_repair_find"
            and (native_repair_branch_diag.get("next_repair_steps") or [{}])[0].get("command") == "win32_selector_repair_find"
            and (native_repair_branch_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("hwnd") == 24682
            and (native_repair_branch_diag.get("next_repair_steps") or [{}])[0].get("ready") is True
            and (native_repair_branch_diag.get("native_control_find") or [{}, {}])[0].get("selector_repair_available") is True
            and (native_repair_branch_diag.get("native_control_find") or [{}, {}])[1].get("matched_count") == 1
            and native_repair_reports_diag.get("native_selector_repair_available") is True
            and (native_repair_reports_diag.get("native_selector_suggestions") or [{}])[0].get("class_name") == "Edit"
            and (native_repair_reports_diag.get("next_repair_candidates") or [{}])[0].get("suggestion", {}).get("name") == "Search"
            and (native_repair_reports_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("suggestion", {}).get("automation_id") == "101"
            and (native_repair_reports_diag.get("selected") or {}).get("native_selector_repair_available") is True
            and (native_wait_branch_diag.get("native_control_wait") or [{}])[0].get("state") == "present"
            and (native_wait_branch_diag.get("native_control_wait") or [{}])[0].get("item_count") == 2
            and ((native_wait_branch_diag.get("native_control_wait") or [{}])[0].get("item_preview") or [{}])[0].get("text") == "Alpha"
            and ((native_wait_branch_diag.get("native_control_wait") or [{}])[0].get("repair_suggestions") or [{}])[0].get("match") == "contains"
            and (native_wait_branch_diag.get("next_repair_candidates") or [{}])[0].get("kind") == "native_wait_repair"
            and (native_wait_branch_diag.get("next_repair_candidates") or [{}])[0].get("repair_suggestion", {}).get("match") == "contains"
            and (native_wait_branch_diag.get("next_repair_steps") or [{}])[0].get("command") == "win32_control_wait"
            and (native_wait_branch_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("match") == "contains"
            and (native_wait_branch_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("text") == "Delta"
            and bool(native_wait_branch_diag.get("recommendations"))
            and (native_wait_reports_diag.get("native_control_wait") or [{}])[0].get("target_text") == "Delta"
            and ((native_wait_reports_diag.get("selected") or {}).get("native_control_wait") or [{}])[0].get("kind") == "listbox"
            and (native_wait_reports_diag.get("next_repair_candidates") or [{}])[0].get("command") == "win32_control_wait"
            and (native_wait_reports_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("hwnd") == 24683
            and uia_find_branch_diag.get("uia_selector_repair_available") is True
            and (uia_find_branch_diag.get("uia_selector_suggestions") or [{}])[0].get("automation_id") == "saveButton"
            and (uia_find_branch_diag.get("next_repair_candidates") or [{}])[0].get("command") == "uia_selector_repair_find"
            and (uia_find_branch_diag.get("next_repair_steps") or [{}])[0].get("command") == "uia_selector_repair_find"
            and (uia_find_branch_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("hwnd") == 24681
            and (uia_find_branch_diag.get("uia_find") or [{}])[0].get("near_matches")
            and (uia_find_branch_diag.get("uia_find") or [{}])[0].get("miss_counts", {}).get("name") == 3
            and (uia_find_branch_diag.get("uia_find") or [{}, {}])[1].get("matched_count") == 1
            and uia_find_reports_diag.get("uia_selector_repair_available") is True
            and (uia_find_reports_diag.get("uia_selector_suggestions") or [{}])[0].get("pattern") == "Invoke"
            and (uia_find_reports_diag.get("next_repair_candidates") or [{}])[0].get("suggestion", {}).get("pattern") == "Invoke"
            and (uia_find_reports_diag.get("next_repair_steps") or [{}])[0].get("ready") is True
            and (uia_find_reports_diag.get("selected") or {}).get("uia_selector_repair_available") is True
            and bool(window_find_failure_summary.get("miss_counts", {}).get("title"))
            and (window_find_failure_summary.get("selector_suggestions") or [{}])[0].get("process") == "demo-player.exe"
            and window_find_branch_diag.get("window_selector_repair_available") is True
            and (window_find_branch_diag.get("next_repair_candidates") or [{}])[0].get("command") == "window_selector_repair_find"
            and (window_find_branch_diag.get("next_repair_steps") or [{}])[0].get("command") == "window_selector_repair_find"
            and (window_find_branch_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("probe_original") is False
            and (window_find_branch_diag.get("window_find") or [{}])[0].get("near_windows")
            and window_find_reports_diag.get("window_selector_repair_available") is True
            and (window_find_reports_diag.get("window_selector_suggestions") or [{}])[0].get("hwnd") == 7001
            and (window_find_reports_diag.get("next_repair_candidates") or [{}])[0].get("suggestion", {}).get("process") == "demo-player.exe"
            and (window_find_reports_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("suggestion", {}).get("hwnd") == 7001
            and auto_explicit.get("ok") is True
            and (auto_explicit.get("results") or [{}])[0].get("result", {}).get("selected_id") == "win32"
            and (auto_explicit.get("results") or [{}])[0].get("result", {}).get("kind") == "click"
            and (auto_explicit.get("results") or [{}])[0].get("result", {}).get("branch_count") == 3
            and len((auto_explicit.get("results") or [{}])[0].get("result", {}).get("branches") or []) == 3
            and any(item.get("event") == "auto_start" for item in auto_explicit.get("trace") or [])
            and any(item.get("event") == "auto_end" for item in auto_explicit.get("trace") or [])
            and auto_relocation_batch.get("ok") is True
            and auto_relocation_batch.get("diagnostic_summary", {}).get("relocated") is True
            and auto_relocation_batch.get("diagnostic_summary", {}).get("uia_relocation_count") == 1
            and auto_relocation_batch.get("diagnostic_summary", {}).get("last_uia_relocation", {}).get("to_index") == 9
            and (auto_relocation_batch.get("results") or [{}])[0].get("result", {}).get("diagnostic_summary", {}).get("selected", {}).get("last_uia_relocation", {}).get("to_index") == 9
            and ((auto_relocation_batch.get("results") or [{}])[0].get("result", {}).get("branches") or [{}])[0].get("relocated") is True
            and ((auto_relocation_batch.get("results") or [{}])[0].get("result", {}).get("branches") or [{}])[0].get("uia_relocation_count") == 1
            and auto_path_explicit.get("ok") is True
            and (auto_path_explicit.get("results") or [{}])[0].get("command") == "batch_auto"
            and (auto_path_explicit.get("results") or [{}])[0].get("path") == "/batch_auto"
            and (auto_path_explicit.get("results") or [{}])[0].get("result", {}).get("selected_id") == "input"
            and auto_dialog_explicit.get("ok") is True
            and (auto_dialog_explicit.get("results") or [{}])[0].get("result", {}).get("selected_id") == "desktop_ocr"
            and (auto_dialog_explicit.get("results") or [{}])[0].get("result", {}).get("kind") == "dialog"
            and any(item.get("event") == "auto_start" for item in auto_dialog_explicit.get("trace") or [])
            and auto_window_plan.get("ok") is True
            and (auto_window_plan.get("results") or [{}])[0].get("result", {}).get("planned") is True
            and (auto_window_plan.get("results") or [{}])[0].get("result", {}).get("kind") == "window"
            and (auto_window_plan.get("results") or [{}])[0].get("result", {}).get("branch_count") == 4
            and auto_selector_repair_plan.get("ok") is True
            and auto_selector_repair_plan_summary.get("has_selector_repair") is True
            and auto_selector_repair_plan_summary.get("has_native_selector_repair") is True
            and auto_cell_selector_repair_plan.get("ok") is True
            and auto_cell_selector_repair_plan_summary.get("has_selector_repair") is True
            and auto_cell_selector_repair_plan_summary.get("has_uia_selector_repair") is True
            and "requires_launch" in (auto_window_plan_summary.get("risk_flags") or [])
            and "uses_coordinate_fallback" in (risky_plan_summary.get("risk_flags") or [])
            and "lacks_stable_selector" in (risky_plan_summary.get("risk_flags") or [])
            and "contains_sensitive_or_destructive_action" in (risky_plan_summary.get("risk_flags") or [])
            and auto_generation_ok
            and repeat_batch.get("ok") is True
            and repeat_batch.get("count") == 1
            and (repeat_batch.get("results") or [{}])[0].get("result", {}).get("iterations") == 3
            and len((repeat_batch.get("results") or [{}])[0].get("result", {}).get("history") or []) == 3
            and (repeat_batch.get("results") or [{}])[0].get("result", {}).get("result", {}).get("value", {}).get("seen") is True
            and (repeat_batch.get("results") or [{}])[0].get("result", {}).get("expectation", {}).get("ok") is True
            and repeat_step_refs_batch.get("ok") is True
            and repeat_step_refs_batch.get("count") == 2
            and ((repeat_step_refs_batch.get("results") or [{}])[0].get("result") or {}).get("iterations") == 2
            and (((repeat_step_refs_batch.get("results") or [{}])[0].get("result") or {}).get("history") or [{}, {}])[1].get("last_result", {}).get("value", {}).get("ready") is True
            and (((((repeat_step_refs_batch.get("results") or [{}])[0].get("result") or {}).get("history") or [{}, {}])[1].get("until") or {}).get("ok") is True)
            and ((repeat_step_refs_batch.get("results") or [{}, {}])[1].get("result") or {}).get("value") is True
            and ((repeat_step_refs_batch.get("results") or [{}, {}])[1].get("result") or {}).get("expectation", {}).get("ok") is True
            and timeout_budget_batch.get("ok") is False
            and timeout_budget_batch.get("timeout_budget_exceeded") is True
            and (timeout_budget_batch.get("results") or [{}])[0].get("result", {}).get("error") == "batch_timeout"
            and any(item.get("event") == "batch_start" for item in timeout_budget_batch.get("trace") or [])
            and step_timeout_batch.get("ok") is False
            and (step_timeout_batch.get("results") or [{}])[0].get("result", {}).get("error") == "batch_timeout"
            and (step_timeout_batch.get("results") or [{}])[0].get("attempts") == 1
            and safety_gate_blocked.get("ok") is False
            and safety_gate_blocked.get("error") == "confirmation_required"
            and safety_gate_blocked.get("failure_category") == "safety"
            and safety_gate_blocked.get("executed") is False
            and safety_gate_blocked.get("confirmations")
            and safety_gate_nested_blocked.get("error") == "confirmation_required"
            and safety_gate_nested_blocked.get("confirmations")
            and safety_gate_confirmed.get("ok") is True
            and safety_gate_confirmed.get("safety", {}).get("confirmed") is True
            and cleanup_batch.get("ok") is False
            and (cleanup_batch.get("results") or [{}])[0].get("on_failure", {}).get("ok") is True
            and ((cleanup_batch.get("results") or [{}])[0].get("on_failure", {}).get("results") or [{}])[0].get("result", {}).get("value") == "rescued"
            and (cleanup_batch.get("results") or [{}])[0].get("finally", {}).get("ok") is True
            and ((cleanup_batch.get("results") or [{}])[0].get("finally", {}).get("results") or [{}])[0].get("result", {}).get("value") == "released"
            and any(item.get("event") == "followup_start" for item in cleanup_batch.get("trace") or [])
            and batch_cleanup.get("ok") is False
            and batch_cleanup.get("on_failure", {}).get("ok") is True
            and (batch_cleanup.get("on_failure", {}).get("results") or [{}])[0].get("result", {}).get("value") == "top-rescued"
            and batch_cleanup.get("finally", {}).get("ok") is True
            and (batch_cleanup.get("finally", {}).get("results") or [{}])[0].get("result", {}).get("value") == "top-released"
            and any(item.get("event") == "batch_end" for item in batch_cleanup.get("trace") or [])
            and recovery_batch.get("ok") is False
            and (recovery_batch.get("results") or [{}])[0].get("attempts") == 2
            and (recovery_batch.get("results") or [{}])[0].get("recovery", {}).get("ok") is True
            and (((recovery_batch.get("results") or [{}])[0].get("recovery", {}).get("results") or [{}])[0].get("result", {}).get("value") == "config-repaired")
            and any(item.get("event") == "step_recovery_retry" for item in recovery_batch.get("trace") or [])
            and clipboard_recovery_batch.get("ok") is False
            and (clipboard_recovery_batch.get("failures") or [{}])[0].get("failure_category") == "clipboard_restore"
            and (clipboard_recovery_batch.get("results") or [{}])[0].get("recovery", {}).get("ok") is True
            and (((clipboard_recovery_batch.get("results") or [{}])[0].get("recovery", {}).get("results") or [{}])[0].get("id") == "fallback_text_input")
            and (((clipboard_recovery_batch.get("results") or [{}])[0].get("recovery", {}).get("results") or [{}])[0].get("result", {}).get("value") == "retried-with-focused-input")
            and "clipboard_restore" in (clipboard_recovery_batch.get("failure_categories") or [])
            and clipboard_recovery_batch.get("diagnostic_summary", {}).get("clipboard_restore")
            and repair_plan_batch.get("ok") is True
            and repair_plan_value.get("ready_count") >= 4
            and {step.get("command") for step in (repair_plan_value.get("ready_steps") or [])} >= {"win32_selector_repair_find", "win32_control_wait", "uia_selector_repair_find", "window_selector_repair_find"}
            and (repair_plan_value.get("try_step") or {}).get("command") == "batch_try"
            and (repair_plan_value.get("batch") or {}).get("commands")
            and repair_plan_context_batch.get("ok") is True
            and (repair_plan_context_value.get("ready_steps") or [{}])[0].get("args", {}).get("hwnd") == 97531
            and (repair_plan_context_value.get("ready_steps") or [{}])[0].get("portable_ready") is True
            and repair_plan_step_ref_batch.get("ok") is True
            and (repair_plan_step_ref_value.get("ready") is False)
            and (repair_plan_step_ref_value.get("pending_steps") or [{}])[0].get("uses_step_refs") is True
            and "original_batch_context" in ((repair_plan_step_ref_value.get("pending_steps") or [{}])[0].get("requires") or [])
            and not _can_helper_handle_batch([{"command": "batch_repair_plan", "args": {"diagnostic_summary": {}}}])
            and auto_repair_disabled_batch.get("ok") is False
            and "diagnostic_repair" not in auto_repair_disabled_batch
            and auto_repair_enabled_batch.get("ok") is False
            and auto_repair_result.get("enabled") is True
            and auto_repair_result.get("executed") is True
            and auto_repair_result.get("ok") is True
            and (auto_repair_result.get("plan") or {}).get("ready_count") == 1
            and (((auto_repair_result.get("result") or {}).get("results") or [{}])[0].get("id") == "diagnostic_repair_probe")
            and ((((auto_repair_result.get("result") or {}).get("results") or [{}])[0].get("result") or {}).get("value") or {}).get("repair_probe") == "ran"
            and any(item.get("event") == "diagnostic_repair_start" for item in auto_repair_enabled_batch.get("trace") or [])
            and auto_repair_rebinding_batch.get("ok") is False
            and ((auto_repair_rebinding_batch.get("diagnostic_repair") or {}).get("ok") is True)
            and ((auto_repair_rebinding_batch.get("diagnostic_repair") or {}).get("rebinding_count") == 4)
            and {item.get("kind") for item in auto_repair_rebindings} >= {"uia_element", "native_control", "window", "native_wait"}
            and next((item for item in auto_repair_rebindings if item.get("kind") == "uia_element"), {}).get("index") == 7
            and next((item for item in auto_repair_rebindings if item.get("kind") == "uia_element"), {}).get("view") == "raw"
            and next((item for item in auto_repair_rebindings if item.get("kind") == "native_control"), {}).get("child_hwnd") == 5432
            and next((item for item in auto_repair_rebindings if item.get("kind") == "window"), {}).get("target_hwnd") == 7001
            and next((item for item in auto_repair_rebindings if item.get("kind") == "native_wait"), {}).get("text") == "Delta"
            and auto_repair_retry_batch.get("ok") is False
            and ((auto_repair_retry_batch.get("diagnostic_repair") or {}).get("ok") is True)
            and auto_repair_retry.get("enabled") is True
            and auto_repair_retry.get("executed") is True
            and auto_repair_retry.get("ok") is True
            and (auto_repair_retry.get("summary") or {}).get("failed_count") == 0
            and ((auto_repair_retry.get("results") or [{}])[0].get("id") == "repair_then_retry")
            and ((auto_repair_retry.get("results") or [{}])[0].get("result") or {}).get("count") == 2
            and any(item.get("event") == "diagnostic_repair_retry_start" for item in auto_repair_retry_batch.get("trace") or [])
            and auto_repair_rebind_retry_batch.get("ok") is False
            and ((auto_repair_rebind_retry_batch.get("diagnostic_repair") or {}).get("ok") is True)
            and ((auto_repair_rebind_retry_batch.get("diagnostic_repair") or {}).get("rebinding_count") == 4)
            and auto_repair_rebind_retry.get("enabled") is True
            and auto_repair_rebind_retry.get("executed") is True
            and auto_repair_rebind_retry.get("ok") is True
            and (auto_repair_rebind_retry.get("summary") or {}).get("failed_count") == 0
            and auto_repair_rebind_retry.get("patched_count") == 1
            and auto_repair_rebind_retry.get("skipped_count") == 0
            and auto_repair_rebind_retry.get("patch_count") == 1
            and "$" in (auto_repair_rebind_retry.get("patched_paths") or [])
            and auto_repair_rebind_retry_item.get("id") == "repair_then_rebind_retry"
            and (auto_repair_rebind_retry_item.get("result") or {}).get("rebound") is True
            and auto_repair_rebind_retry_args.get("hwnd") == 24681
            and auto_repair_rebind_retry_args.get("index") == 7
            and auto_repair_rebind_retry_args.get("view") == "raw"
            and ((auto_repair_rebind_retry_item.get("rebinding_patches") or [{}])[0].get("args_preview") or {}).get("hwnd") == 24681
            and any(item.get("event") == "diagnostic_repair_rebind_retry_start" for item in auto_repair_rebind_retry_batch.get("trace") or [])
            and auto_repair_rebind_retry_auto_batch.get("ok") is False
            and auto_repair_rebind_retry_auto.get("enabled") is True
            and auto_repair_rebind_retry_auto.get("executed") is True
            and auto_repair_rebind_retry_auto.get("ok") is True
            and (auto_repair_rebind_retry_auto.get("summary") or {}).get("failed_count") == 0
            and auto_repair_rebind_retry_auto.get("patched_count") == 1
            and auto_repair_rebind_retry_auto.get("patch_count") >= 2
            and "$" in (auto_repair_rebind_retry_auto.get("patched_paths") or [])
            and "$.branches[0]" in (auto_repair_rebind_retry_auto.get("patched_paths") or [])
            and (auto_repair_rebind_retry_auto_branch_result.get("result") or {}).get("rebound") is True
            and auto_repair_rebind_retry_auto_args.get("hwnd") == 24681
            and auto_repair_rebind_retry_auto_args.get("index") == 7
            and auto_repair_rebind_retry_auto_args.get("view") == "raw"
            and auto_repair_rebind_retry_nested_batch.get("ok") is False
            and auto_repair_rebind_retry_nested.get("enabled") is True
            and auto_repair_rebind_retry_nested.get("executed") is True
            and auto_repair_rebind_retry_nested.get("ok") is True
            and (auto_repair_rebind_retry_nested.get("summary") or {}).get("failed_count") == 0
            and auto_repair_rebind_retry_nested.get("patched_count") == 1
            and auto_repair_rebind_retry_nested.get("patch_count") == 1
            and "$.branches[0].steps[0]" in (auto_repair_rebind_retry_nested.get("patched_paths") or [])
            and (auto_repair_rebind_retry_nested_branch_result.get("result") or {}).get("rebound") is True
            and auto_repair_rebind_retry_nested_args.get("hwnd") == 24681
            and auto_repair_rebind_retry_nested_args.get("index") == 7
            and auto_repair_rebind_retry_nested_args.get("view") == "raw"
            and auto_repair_rebind_retry_skip_batch.get("ok") is False
            and auto_repair_rebind_retry_skip.get("enabled") is True
            and auto_repair_rebind_retry_skip.get("executed") is False
            and auto_repair_rebind_retry_skip.get("ok") is False
            and auto_repair_rebind_retry_skip.get("patched_count") == 0
            and auto_repair_rebind_retry_skip.get("skipped_count") == 1
            and auto_repair_rebind_retry_skip.get("patch_count") == 0
            and auto_repair_rebind_retry_skip.get("reason") == "no_retry_steps_patched"
            and (auto_repair_rebind_retry_skip_item.get("result") or {}).get("skipped") is True
            and (auto_repair_rebind_retry_skip_item.get("result") or {}).get("reason") == "no_matching_rebinding"
            and auto_repair_rebind_retry_autorecover_batch.get("ok") is False
            and ((auto_repair_rebind_retry_autorecover_batch.get("diagnostic_repair") or {}).get("auto_recover_rebind_retry") is True)
            and auto_repair_rebind_retry_autorecover.get("enabled") is True
            and auto_repair_rebind_retry_autorecover.get("executed") is True
            and auto_repair_rebind_retry_autorecover.get("ok") is True
            and auto_repair_rebind_retry_autorecover.get("patched_count") == 1
            and auto_repair_rebind_retry_autorecover.get("patch_count") >= 2
            and "$" in (auto_repair_rebind_retry_autorecover.get("patched_paths") or [])
            and "$.branches[0]" in (auto_repair_rebind_retry_autorecover.get("patched_paths") or [])
            and (auto_repair_rebind_retry_autorecover_branch_result.get("result") or {}).get("rebound") is True
            and auto_repair_rebind_retry_autorecover_args.get("hwnd") == 24681
            and auto_repair_rebind_retry_autorecover_args.get("index") == 7
            and auto_repair_rebind_retry_autorecover_args.get("view") == "raw"
            and any(item.get("event") == "auto_recover_rebind_retry_enabled" for item in auto_repair_rebind_retry_autorecover_batch.get("trace") or [])
            and auto_repair_rebind_retry_autorecover_nested_batch.get("ok") is False
            and ((auto_repair_rebind_retry_autorecover_nested_batch.get("diagnostic_repair") or {}).get("auto_recover_rebind_retry") is True)
            and auto_repair_rebind_retry_autorecover_nested.get("enabled") is True
            and auto_repair_rebind_retry_autorecover_nested.get("executed") is True
            and auto_repair_rebind_retry_autorecover_nested.get("ok") is True
            and auto_repair_rebind_retry_autorecover_nested.get("patched_count") == 1
            and auto_repair_rebind_retry_autorecover_nested.get("patch_count") >= 2
            and "$.branches[0].steps[0]" in (auto_repair_rebind_retry_autorecover_nested.get("patched_paths") or [])
            and "$.branches[0].steps[0].branches[0]" in (auto_repair_rebind_retry_autorecover_nested.get("patched_paths") or [])
            and (auto_repair_rebind_retry_autorecover_nested_branch_result.get("result") or {}).get("rebound") is True
            and auto_repair_rebind_retry_autorecover_nested_args.get("hwnd") == 24681
            and auto_repair_rebind_retry_autorecover_nested_args.get("index") == 7
            and auto_repair_rebind_retry_autorecover_nested_args.get("view") == "raw"
            and any(item.get("event") == "auto_recover_rebind_retry_enabled" for item in auto_repair_rebind_retry_autorecover_nested_batch.get("trace") or [])
            and auto_repair_rebind_retry_autorecover_alternatives_batch.get("ok") is False
            and ((auto_repair_rebind_retry_autorecover_alternatives_batch.get("diagnostic_repair") or {}).get("auto_recover_rebind_retry") is True)
            and auto_repair_rebind_retry_autorecover_alternatives.get("enabled") is True
            and auto_repair_rebind_retry_autorecover_alternatives.get("executed") is True
            and auto_repair_rebind_retry_autorecover_alternatives.get("ok") is True
            and auto_repair_rebind_retry_autorecover_alternatives.get("patched_count") == 1
            and auto_repair_rebind_retry_autorecover_alternatives.get("patch_count") >= 2
            and "$.alternatives[0].steps[0]" in (auto_repair_rebind_retry_autorecover_alternatives.get("patched_paths") or [])
            and "$.alternatives[0].steps[0].branches[0]" in (auto_repair_rebind_retry_autorecover_alternatives.get("patched_paths") or [])
            and (auto_repair_rebind_retry_autorecover_alternatives_branch_result.get("result") or {}).get("rebound") is True
            and auto_repair_rebind_retry_autorecover_alternatives_args.get("hwnd") == 24681
            and auto_repair_rebind_retry_autorecover_alternatives_args.get("index") == 7
            and auto_repair_rebind_retry_autorecover_alternatives_args.get("view") == "raw"
            and any(item.get("event") == "auto_recover_rebind_retry_enabled" for item in auto_repair_rebind_retry_autorecover_alternatives_batch.get("trace") or [])
            and auto_repair_rebind_retry_autorecover_alias_detected is True
            and auto_repair_rebind_retry_autorecover_alias_patch.get("patch_count", 0) >= 3
            and "$.branches[0].steps[0].args.workflow[0]" in auto_repair_rebind_retry_autorecover_alias_paths
            and "$.branches[0].steps[0].args.workflow[0].branches[0]" in auto_repair_rebind_retry_autorecover_alias_paths
            and any((preview or {}).get("hwnd") == 24681 for preview in (auto_repair_rebind_retry_autorecover_alias_patch.get("patched_args_preview") or []))
            and auto_repair_rebind_retry_autorecover_recovery_detected is True
            and auto_repair_rebind_retry_autorecover_recovery_patch.get("patch_count", 0) >= 2
            and "$.branches[0].steps[0].recover_on_failure.selector[0]" in auto_repair_rebind_retry_autorecover_recovery_paths
            and "$.branches[0].steps[0].recover_on_failure.selector[0].branches[0]" in auto_repair_rebind_retry_autorecover_recovery_paths
            and auto_repair_rebind_retry_post_patch.get("patch_count", 0) >= 2
            and "$.args.post_steps[0]" in auto_repair_rebind_retry_post_paths
            and auto_repair_rebind_retry_autorecover_item_disabled_batch.get("ok") is False
            and "diagnostic_repair" not in auto_repair_rebind_retry_autorecover_item_disabled_batch
            and not any(item.get("event") == "auto_recover_rebind_retry_enabled" for item in auto_repair_rebind_retry_autorecover_item_disabled_batch.get("trace") or [])
            and auto_repair_rebind_retry_autorecover_args_disabled_batch.get("ok") is False
            and "diagnostic_repair" not in auto_repair_rebind_retry_autorecover_args_disabled_batch
            and not any(item.get("event") == "auto_recover_rebind_retry_enabled" for item in auto_repair_rebind_retry_autorecover_args_disabled_batch.get("trace") or [])
            and auto_repair_rebind_retry_option_disabled_options.get("diagnostic_repair_rebind_retry") is False
            and auto_repair_rebind_retry_option_disabled_options.get("diagnostic_repair_rebind_retry_explicit") is True
            and auto_repair_rebind_retry_autorecover_option_disabled_batch.get("ok") is False
            and "diagnostic_repair" not in auto_repair_rebind_retry_autorecover_option_disabled_batch
            and not any(item.get("event") == "auto_recover_rebind_retry_enabled" for item in auto_repair_rebind_retry_autorecover_option_disabled_batch.get("trace") or [])
            and helper_recovery_routing_ok
            and helper_smart_routing_ok
            and helper_timeout_contract_ok
            and cli_repair_contract_ok
            and uia_click_message_contract_ok
            and mouse_context_contract_ok
        )
        if not report["ok"]:
            report["error"] = "Batch contract probe did not verify normalization, stop-on-error, retry, optional failures, numeric/named references, args/data aliases, expanded expectations, extraction, conditional steps, batch_try fallback, batch_auto fallback/window generation, native present/absent post verification, native wait diagnostic aggregation, repair planning/rebinding/rebind retry, batch_repeat loops, timeout budgets, cleanup hooks, trace events, and helper smart-command routing"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report


def selftest_selector(timeout: float = 1.0) -> Dict[str, Any]:
    """Exercise selector normalization/ranking without desktop I/O."""
    report: Dict[str, Any] = {"app": "selector_contract_probe", "timeout": timeout, "steps": {}}
    try:
        uia_elements: List[Dict[str, Any]] = [
            {
                "index": 0,
                "name": "Save as copy",
                "automation_id": "cmdSaveAs",
                "control_type": "button",
                "control_type_id": 50000,
                "class_name": "Button",
                "enabled": True,
                "visible": True,
                "rect": {"left": 10, "top": 10, "right": 110, "bottom": 40, "width": 100, "height": 30},
                "patterns": ["Invoke"],
            },
            {
                "index": 1,
                "name": "Quick Save Backup",
                "automation_id": "cmdQuickBackup",
                "control_type": "button",
                "control_type_id": 50000,
                "class_name": "Button",
                "enabled": True,
                "visible": True,
                "rect": {"left": 10, "top": 50, "right": 150, "bottom": 80, "width": 140, "height": 30},
                "patterns": ["Invoke"],
            },
            {
                "index": 2,
                "name": "Ｓａｖｅ",
                "automation_id": "cmdSave",
                "control_type": "button",
                "control_type_id": 50000,
                "class_name": "Button",
                "enabled": True,
                "visible": True,
                "rect": {"left": 10, "top": 90, "right": 90, "bottom": 120, "width": 80, "height": 30},
                "patterns": ["Invoke"],
            },
        ]
        uia_pool = _filter_elements(
            uia_elements,
            name="Save",
            pattern="Invoke",
            visible_only=True,
            match="contains",
            limit=1,
            collect_all=True,
        )
        uia_ranked = _rank_uia_matches(
            uia_pool,
            name="Save",
            pattern="Invoke",
            visible_only=True,
            match="contains",
            limit=1,
        )
        exact_late_ok = bool(uia_ranked and uia_ranked[0].get("index") == 2)
        report["steps"]["uia_exact_late"] = {
            "pool_count": len(uia_pool),
            "top_index": uia_ranked[0].get("index") if uia_ranked else None,
            "top_reasons": uia_ranked[0].get("selector_reasons") if uia_ranked else [],
            "ok": exact_late_ok,
        }

        compact_elements = [
            {
                "index": 10,
                "name": "Ｓａｖｅ　 File",
                "control_type": "button",
                "control_type_id": 50000,
                "class_name": "Button",
                "enabled": True,
                "visible": True,
                "rect": {"left": 20, "top": 20, "right": 120, "bottom": 50, "width": 100, "height": 30},
                "patterns": ["Invoke"],
            }
        ]
        compact_pool = _filter_elements(
            compact_elements,
            name="SaveFile",
            pattern="Invoke",
            visible_only=True,
            match="contains",
            limit=1,
            collect_all=True,
        )
        compact_ranked = _rank_uia_matches(
            compact_pool,
            name="SaveFile",
            pattern="Invoke",
            visible_only=True,
            match="contains",
            limit=1,
        )
        compact_ok = bool(compact_ranked and compact_ranked[0].get("index") == 10)
        report["steps"]["uia_compact_width"] = {
            "pool_count": len(compact_pool),
            "top_index": compact_ranked[0].get("index") if compact_ranked else None,
            "top_reasons": compact_ranked[0].get("selector_reasons") if compact_ranked else [],
            "ok": compact_ok,
        }

        operable_ranked = _rank_uia_matches(
            [
                {
                    "index": 20,
                    "name": "Open",
                    "control_type": "button",
                    "control_type_id": 50000,
                    "class_name": "Button",
                    "enabled": False,
                    "visible": False,
                    "rect": {"left": 1, "top": 1, "right": 80, "bottom": 24, "width": 79, "height": 23},
                    "patterns": ["Invoke"],
                },
                {
                    "index": 21,
                    "name": "Open",
                    "control_type": "button",
                    "control_type_id": 50000,
                    "class_name": "Button",
                    "enabled": True,
                    "visible": True,
                    "rect": {"left": 1, "top": 30, "right": 80, "bottom": 54, "width": 79, "height": 24},
                    "patterns": ["Invoke"],
                },
            ],
            name="Open",
            pattern="Invoke",
            visible_only=False,
            match="exact",
            limit=2,
        )
        operable_ok = bool(operable_ranked and operable_ranked[0].get("index") == 21)
        report["steps"]["uia_operable_priority"] = {
            "top_index": operable_ranked[0].get("index") if operable_ranked else None,
            "scores": [item.get("selector_score") for item in operable_ranked],
            "ok": operable_ok,
        }

        exact_pool = _filter_elements(
            uia_elements,
            name="Save",
            pattern="Invoke",
            visible_only=True,
            match="exact",
            limit=10,
            collect_all=True,
        )
        exact_ok = [item.get("index") for item in exact_pool] == [2]
        report["steps"]["uia_exact_filter"] = {
            "indexes": [item.get("index") for item in exact_pool],
            "ok": exact_ok,
        }

        native_ranked = _rank_native_candidates(
            [
                {
                    "ordinal": 0,
                    "hwnd": 101,
                    "kind": "listbox",
                    "class_name": "ListBox",
                    "title": "Save location choices",
                    "control_id": 1001,
                    "rect": {"left": 0, "top": 0, "right": 150, "bottom": 90, "width": 150, "height": 90},
                    "window": {"visible": True, "enabled": True, "title": "Save location choices"},
                    "control": {"kind": "listbox", "items": [{"text": "Save copy"}]},
                },
                {
                    "ordinal": 1,
                    "hwnd": 102,
                    "kind": "listbox",
                    "class_name": "ListBox",
                    "title": "",
                    "control_id": 1002,
                    "rect": {"left": 0, "top": 100, "right": 150, "bottom": 190, "width": 150, "height": 90},
                    "window": {"visible": True, "enabled": True, "title": ""},
                    "control": {"kind": "listbox", "items": [{"text": "Ｓａｖｅ"}]},
                },
            ],
            name="Save",
            control_type="listbox",
            match="contains",
        )
        native_ok = bool(native_ranked and native_ranked[0].get("hwnd") == 102)
        report["steps"]["native_item_priority"] = {
            "top_hwnd": native_ranked[0].get("hwnd") if native_ranked else None,
            "top_reasons": native_ranked[0].get("selector_reasons") if native_ranked else [],
            "ok": native_ok,
        }

        near_matches = _uia_near_matches(
            uia_elements,
            name="Svae",
            control_type="button",
            pattern="Invoke",
            visible_only=True,
            match="exact",
            limit=3,
        )
        near_ok = bool(near_matches and near_matches[0].get("index") in (0, 2) and near_matches[0].get("selector_score") is not None)
        report["steps"]["uia_near_matches"] = {
            "count": len(near_matches),
            "top_index": near_matches[0].get("index") if near_matches else None,
            "top_reasons": near_matches[0].get("selector_reasons") if near_matches else [],
            "ok": near_ok,
        }
        uia_failure_summary = _uia_find_failure_summary(
            uia_elements,
            near_matches,
            name="Svae",
            control_type="button",
            pattern="Invoke",
            visible_only=True,
            match="exact",
            scanned=len(uia_elements),
            view="raw",
        )
        first_uia_suggestion = (uia_failure_summary.get("selector_suggestions") or [{}])[0]
        uia_failure_summary_ok = bool(
            uia_failure_summary.get("miss_counts", {}).get("name")
            and uia_failure_summary.get("observed_control_types")
            and uia_failure_summary.get("observed_classes")
            and first_uia_suggestion.get("index") is not None
            and (first_uia_suggestion.get("name") or first_uia_suggestion.get("automation_id"))
            and first_uia_suggestion.get("control_type")
            and first_uia_suggestion.get("pattern")
        )
        report["steps"]["uia_find_failure_summary"] = {
            "miss_counts": uia_failure_summary.get("miss_counts"),
            "observed_control_types": uia_failure_summary.get("observed_control_types"),
            "suggestion": first_uia_suggestion,
            "ok": uia_failure_summary_ok,
        }

        real_find_elements = globals().get("find_elements")
        uia_repair_find_calls: List[Dict[str, Any]] = []

        def fake_repair_find(
            hwnd: int,
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
            max_depth: int = 10,
            max_elements: int = 500,
            view: str = "raw",
        ) -> Dict[str, Any]:
            uia_repair_find_calls.append({
                "hwnd": hwnd,
                "name": name,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "pattern": pattern,
                "match": match,
                "limit": limit,
                "max_depth": max_depth,
                "max_elements": max_elements,
                "view": view,
            })
            return {
                "ok": True,
                "hwnd": hwnd,
                "view": view,
                "count": 1,
                "matches": [{"index": 31, "name": name, "control_type": control_type, "patterns": [pattern]}],
            }

        try:
            globals()["find_elements"] = fake_repair_find
            uia_repair_find = uia_selector_repair_find(
                2468,
                {
                    "index": 31,
                    "name": "Save",
                    "control_type": "button",
                    "class_name": "Button",
                    "pattern": "Invoke",
                    "match": "exact",
                },
                original={
                    "name": "Svae",
                    "automation_id": "staleId",
                    "view": "control",
                    "max_depth": 4,
                    "max_elements": 40,
                    "visible_only": True,
                },
                allow_suggestion_index=False,
            )
        finally:
            if real_find_elements is not None:
                globals()["find_elements"] = real_find_elements
        uia_repair_find_ok = bool(
            uia_repair_find.get("ok")
            and (uia_repair_find.get("matches") or [{}])[0].get("index") == 31
            and uia_repair_find_calls
            and uia_repair_find_calls[0].get("automation_id") is None
            and uia_repair_find_calls[0].get("name") == "Save"
            and uia_repair_find_calls[0].get("control_type") == "button"
            and uia_repair_find_calls[0].get("pattern") == "Invoke"
            and uia_repair_find_calls[0].get("view") == "control"
            and uia_repair_find_calls[0].get("max_depth") == 4
        )
        report["steps"]["uia_selector_repair_find"] = {
            "calls": uia_repair_find_calls,
            "result": uia_repair_find,
            "ok": uia_repair_find_ok,
        }

        real_find_elements = globals().get("find_elements")
        real_wait_boundary = globals().get("_elevated_helper_required_result")
        real_wait_prepare_helper = globals().get("_prepare_helper_for_uia")
        uia_wait_repair_calls: List[Dict[str, Any]] = []

        def fake_wait_repair_find(
            hwnd: int,
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
            max_depth: int = 10,
            max_elements: int = 500,
            view: str = "raw",
        ) -> Dict[str, Any]:
            uia_wait_repair_calls.append({
                "hwnd": hwnd,
                "name": name,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "pattern": pattern,
                "match": match,
                "limit": limit,
                "max_depth": max_depth,
                "max_elements": max_elements,
                "view": view,
            })
            if name == "Save" and control_type == "button" and pattern == "Invoke":
                return {
                    "ok": True,
                    "hwnd": hwnd,
                    "view": view,
                    "scanned": 5,
                    "count": 1,
                    "matches": [{"index": 31, "name": name, "control_type": control_type, "patterns": [pattern]}],
                }
            return {
                "ok": False,
                "hwnd": hwnd,
                "view": view,
                "scanned": 5,
                "count": 0,
                "matches": [],
                "near_matches": [{"index": 31, "name": "Save", "control_type": "button", "patterns": ["Invoke"]}],
                "failure_summary": {
                    "selector_suggestions": [
                        {
                            "index": 31,
                            "name": "Save",
                            "control_type": "button",
                            "class_name": "Button",
                            "pattern": "Invoke",
                            "match": "exact",
                        }
                    ],
                    "miss_counts": {"name": 1},
                },
            }

        try:
            globals()["find_elements"] = fake_wait_repair_find
            globals()["_elevated_helper_required_result"] = lambda *_args, **_kwargs: None
            globals()["_prepare_helper_for_uia"] = lambda _hwnd: (False, False)
            uia_wait_strict = wait_for_element(
                2468,
                {
                    "name": "Svae",
                    "control_type": "button",
                    "pattern": "Invoke",
                    "match": "exact",
                    "max_depth": 4,
                    "max_elements": 40,
                    "view": "control",
                },
                timeout=0.0,
                interval=0.01,
                repair=False,
            )
            uia_wait_repair = wait_for_element(
                2468,
                {
                    "name": "Svae",
                    "control_type": "button",
                    "pattern": "Invoke",
                    "match": "exact",
                    "max_depth": 4,
                    "max_elements": 40,
                    "view": "control",
                },
                timeout=0.0,
                interval=0.01,
                repair=True,
                repair_timeout=0.0,
            )
            uia_wait_timeout_only_alias = wait_for_element(
                2468,
                {
                    "name": "Svae",
                    "control_type": "button",
                    "pattern": "Invoke",
                    "match": "exact",
                    "max_depth": 4,
                    "max_elements": 40,
                    "view": "control",
                    "repair-timeout": 0.0,
                    "allow-suggestion-index": "true",
                },
                timeout=0.0,
                interval=0.01,
            )
            uia_wait_timeout_only_disabled = wait_for_element(
                2468,
                {
                    "name": "Svae",
                    "control_type": "button",
                    "pattern": "Invoke",
                    "match": "exact",
                    "max_depth": 4,
                    "max_elements": 40,
                    "view": "control",
                    "repair": "false",
                    "repair-timeout": 0.0,
                },
                timeout=0.0,
                interval=0.01,
            )
        finally:
            if real_find_elements is not None:
                globals()["find_elements"] = real_find_elements
            if real_wait_boundary is not None:
                globals()["_elevated_helper_required_result"] = real_wait_boundary
            if real_wait_prepare_helper is not None:
                globals()["_prepare_helper_for_uia"] = real_wait_prepare_helper
        uia_wait_repair_suggestion_call = next(
            (
                call
                for call in reversed(uia_wait_repair_calls)
                if call.get("name") == "Save"
                and call.get("control_type") == "button"
                and call.get("pattern") == "Invoke"
            ),
            {},
        )
        uia_wait_repair_ok = bool(
            uia_wait_strict.get("ok") is False
            and uia_wait_strict.get("matched") is False
            and (uia_wait_strict.get("failure_summary") or {}).get("selector_suggestions")
            and uia_wait_repair.get("ok") is True
            and uia_wait_repair.get("matched") is True
            and uia_wait_repair.get("repaired") is True
            and uia_wait_repair.get("uia_selector_repair") is True
            and (uia_wait_repair.get("match") or {}).get("index") == 31
            and len(uia_wait_repair_calls) >= 3
            and uia_wait_repair_suggestion_call.get("name") == "Save"
            and uia_wait_repair_suggestion_call.get("control_type") == "button"
            and uia_wait_repair_suggestion_call.get("pattern") == "Invoke"
            and uia_wait_repair_suggestion_call.get("view") == "control"
            and uia_wait_repair_suggestion_call.get("max_depth") == 4
            and uia_wait_timeout_only_alias.get("repaired") is True
            and uia_wait_timeout_only_alias.get("uia_selector_repair") is True
            and (uia_wait_timeout_only_alias.get("match") or {}).get("index") == 31
            and uia_wait_timeout_only_disabled.get("ok") is False
            and uia_wait_timeout_only_disabled.get("matched") is False
            and not uia_wait_timeout_only_disabled.get("repaired")
        )
        report["steps"]["uia_wait_repair"] = {
            "calls": uia_wait_repair_calls,
            "strict": uia_wait_strict,
            "repair": uia_wait_repair,
            "timeout_only_alias": uia_wait_timeout_only_alias,
            "timeout_only_disabled": uia_wait_timeout_only_disabled,
            "ok": uia_wait_repair_ok,
        }

        real_find_elements = globals().get("find_elements")
        uia_cell_repair_find_calls: List[Dict[str, Any]] = []

        def fake_cell_repair_find(
            hwnd: int,
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
            max_depth: int = 10,
            max_elements: int = 500,
            view: str = "raw",
        ) -> Dict[str, Any]:
            uia_cell_repair_find_calls.append({
                "hwnd": hwnd,
                "name": name,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "value": value,
                "pattern": pattern,
                "match": match,
                "limit": limit,
                "max_depth": max_depth,
                "max_elements": max_elements,
                "view": view,
            })
            if pattern == "GridItem":
                return {
                    "ok": True,
                    "hwnd": hwnd,
                    "view": view,
                    "count": 2,
                    "matches": [
                        {
                            "index": 70,
                            "name": "Beta",
                            "value": "Wrong",
                            "grid_item": {"row": 2, "column": 1},
                            "table_item": {"column_headers": [{"name": "State"}]},
                        },
                        {
                            "index": 79,
                            "name": "Beta",
                            "value": "Done",
                            "grid_item": {"row": 2, "column": 3},
                            "table_item": {"column_headers": [{"name": "State"}]},
                        },
                    ],
                }
            return {"ok": False, "hwnd": hwnd, "view": view, "count": 0, "matches": []}

        try:
            globals()["find_elements"] = fake_cell_repair_find
            uia_cell_repair_find = uia_cell_selector_repair_find(
                2468,
                {
                    "index": 79,
                    "automation_id": "staleCell",
                    "control_type": "data item",
                    "class_name": "DataGridCell",
                    "pattern": "GridItem",
                    "match": "contains",
                },
                original={
                    "row": 2,
                    "column": 3,
                    "row_text": "Beta",
                    "column_name": "State",
                    "view": "control",
                    "max_depth": 4,
                    "max_elements": 40,
                    "visible_only": True,
                },
            )
            uia_cell_repair_missing = uia_cell_selector_repair_find(
                2468,
                {"pattern": "GridItem"},
                original={"row": 2},
            )
            uia_cell_repair_bad_index = uia_cell_selector_repair_find(
                2468,
                {"pattern": "GridItem"},
                original={"row": "two", "column": 3},
            )
        finally:
            if real_find_elements is not None:
                globals()["find_elements"] = real_find_elements
        uia_cell_repair_find_ok = bool(
            uia_cell_repair_find.get("ok")
            and uia_cell_repair_find.get("cell_selector_repair") is True
            and (uia_cell_repair_find.get("matches") or [{}])[0].get("index") == 79
            and len(uia_cell_repair_find.get("matches") or []) == 1
            and uia_cell_repair_find_calls
            and uia_cell_repair_find_calls[0].get("automation_id") == "staleCell"
            and uia_cell_repair_find_calls[0].get("pattern") == "GridItem"
            and uia_cell_repair_find_calls[0].get("view") == "control"
            and uia_cell_repair_find_calls[0].get("max_depth") == 4
            and (uia_cell_repair_find.get("cell") or {}).get("row") == 2
            and (uia_cell_repair_find.get("cell") or {}).get("column") == 3
            and uia_cell_repair_missing.get("ok") is False
            and "requires row/row_text" in str(uia_cell_repair_missing.get("error") or "")
            and uia_cell_repair_bad_index.get("ok") is False
            and "must be integers" in str(uia_cell_repair_bad_index.get("error") or "")
        )
        report["steps"]["uia_cell_selector_repair_find"] = {
            "calls": uia_cell_repair_find_calls,
            "result": uia_cell_repair_find,
            "missing": uia_cell_repair_missing,
            "bad_index": uia_cell_repair_bad_index,
            "ok": uia_cell_repair_find_ok,
        }

        real_win32_control_find = globals().get("win32_control_find")
        real_helper_no_reenter = os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER")
        native_repair_find_calls: List[Dict[str, Any]] = []

        def fake_native_repair_find(
            hwnd: int,
            name: Optional[str] = None,
            automation_id: Optional[Any] = None,
            control_type: Optional[str] = None,
            class_name: Optional[str] = None,
            text: Optional[str] = None,
            value: Optional[str] = None,
            state: Optional[Any] = None,
            expected: Any = None,
            match: str = "contains",
            include_invisible: bool = False,
            include_self: bool = True,
            limit: int = 20,
            min_score: Optional[int] = None,
            timeout_ms: int = 250,
            max_items: int = 200,
            max_children: int = 1000,
            diagnostic: bool = False,
        ) -> Dict[str, Any]:
            native_repair_find_calls.append({
                "hwnd": hwnd,
                "name": name,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "value": value,
                "state": state,
                "expected": expected,
                "match": match,
                "include_invisible": include_invisible,
                "include_self": include_self,
                "limit": limit,
                "min_score": min_score,
                "timeout_ms": timeout_ms,
                "max_items": max_items,
                "max_children": max_children,
                "diagnostic": diagnostic,
            })
            if automation_id == "101" and control_type == "edit" and class_name == "Edit" and name == "File name":
                return {
                    "ok": True,
                    "hwnd": hwnd,
                    "count": 1,
                    "matches": [{"hwnd": 9090, "automation_id": automation_id, "class_name": class_name, "name": name}],
                }
            return {"ok": False, "hwnd": hwnd, "count": 0, "matches": [], "failure_summary": {"selector_suggestions": []}}

        try:
            os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = "1"
            globals()["win32_control_find"] = fake_native_repair_find
            native_repair_find = win32_selector_repair_find(
                2468,
                {
                    "automation_id": "101",
                    "control_type": "edit",
                    "class_name": "Edit",
                    "name": "File name",
                    "match": "exact",
                },
                original={
                    "automation_id": "staleNativeId",
                    "name": "Filename",
                    "include_invisible": True,
                    "include_self": False,
                    "timeout_ms": 333,
                    "max_items": 44,
                    "max_children": 55,
                    "diagnostic": True,
                },
            )
            native_repair_missing = win32_selector_repair_find(2468, {}, original={})
        finally:
            if real_helper_no_reenter is None:
                os.environ.pop("WIN_AUTOMATION_HELPER_NO_REENTER", None)
            else:
                os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = real_helper_no_reenter
            if real_win32_control_find is not None:
                globals()["win32_control_find"] = real_win32_control_find
        native_repair_find_ok = bool(
            native_repair_find.get("ok")
            and native_repair_find.get("native_selector_repair") is True
            and (native_repair_find.get("matches") or [{}])[0].get("hwnd") == 9090
            and native_repair_find_calls
            and native_repair_find_calls[0].get("automation_id") == "101"
            and native_repair_find_calls[0].get("name") == "File name"
            and native_repair_find_calls[0].get("control_type") == "edit"
            and native_repair_find_calls[0].get("class_name") == "Edit"
            and native_repair_find_calls[0].get("include_invisible") is True
            and native_repair_find_calls[0].get("include_self") is False
            and native_repair_find_calls[0].get("timeout_ms") == 333
            and native_repair_missing.get("ok") is False
            and "suggestion required" in str(native_repair_missing.get("error") or "")
        )
        report["steps"]["win32_selector_repair_find"] = {
            "calls": native_repair_find_calls,
            "result": native_repair_find,
            "missing": native_repair_missing,
            "ok": native_repair_find_ok,
        }

        real_wait_find_direct = globals().get("_win32_control_find_direct")
        real_wait_find_helper_route = globals().get("_helper_route_for_hwnd")
        native_wait_find_repair_calls: List[Dict[str, Any]] = []

        def fake_wait_find_direct(
            hwnd: int,
            name: Optional[str] = None,
            automation_id: Optional[Any] = None,
            control_type: Optional[str] = None,
            class_name: Optional[str] = None,
            text: Optional[str] = None,
            value: Optional[str] = None,
            state: Optional[Any] = None,
            expected: Any = None,
            match: str = "contains",
            include_invisible: bool = False,
            include_self: bool = True,
            limit: int = 20,
            min_score: Optional[int] = None,
            timeout_ms: int = 250,
            max_items: int = 200,
            max_children: int = 1000,
            diagnostic: bool = False,
        ) -> Dict[str, Any]:
            native_wait_find_repair_calls.append({
                "hwnd": hwnd,
                "name": name,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "match": match,
                "include_invisible": include_invisible,
                "include_self": include_self,
                "limit": limit,
                "timeout_ms": timeout_ms,
                "max_items": max_items,
                "max_children": max_children,
                "diagnostic": diagnostic,
            })
            if automation_id == "101" and control_type == "edit" and class_name == "Edit" and name == "File name":
                return {
                    "ok": True,
                    "hwnd": hwnd,
                    "count": 1,
                    "matches": [{"hwnd": 9090, "automation_id": automation_id, "class_name": class_name, "name": name}],
                }
            return {
                "ok": False,
                "hwnd": hwnd,
                "count": 0,
                "matches": [],
                "scanned": 3,
                "failure_summary": {
                    "selector_suggestions": [
                        {
                            "automation_id": "101",
                            "control_type": "edit",
                            "class_name": "Edit",
                            "name": "File name",
                            "match": "exact",
                        }
                    ],
                    "miss_counts": {"name": 1},
                },
            }

        try:
            globals()["_win32_control_find_direct"] = fake_wait_find_direct
            globals()["_helper_route_for_hwnd"] = lambda _hwnd, _path: (False, False, None)
            native_wait_find_strict = win32_control_wait_find(
                2468,
                name="Filename",
                control_type="edit",
                match="exact",
                include_invisible=True,
                include_self=False,
                timeout=0.0,
                interval=0.01,
                timeout_ms=333,
                max_items=44,
                max_children=55,
                diagnostic=True,
                repair=False,
            )
            native_wait_find_repair = win32_control_wait_find(
                2468,
                name="Filename",
                control_type="edit",
                match="exact",
                include_invisible=True,
                include_self=False,
                timeout=0.0,
                interval=0.01,
                timeout_ms=333,
                max_items=44,
                max_children=55,
                diagnostic=True,
                repair=True,
                repair_timeout=0.0,
            )
        finally:
            if real_wait_find_direct is not None:
                globals()["_win32_control_find_direct"] = real_wait_find_direct
            if real_wait_find_helper_route is not None:
                globals()["_helper_route_for_hwnd"] = real_wait_find_helper_route
        native_wait_find_repair_ok = bool(
            native_wait_find_strict.get("ok") is False
            and native_wait_find_strict.get("matched") is False
            and (native_wait_find_strict.get("failure_summary") or {}).get("selector_suggestions")
            and native_wait_find_repair.get("ok") is True
            and native_wait_find_repair.get("matched") is True
            and native_wait_find_repair.get("repaired") is True
            and native_wait_find_repair.get("native_selector_repair") is True
            and (native_wait_find_repair.get("repair") or {}).get("selector", {}).get("automation_id") == "101"
            and (native_wait_find_repair.get("matches") or [{}])[0].get("hwnd") == 9090
            and len(native_wait_find_repair_calls) >= 3
            and native_wait_find_repair_calls[-1].get("name") == "File name"
            and native_wait_find_repair_calls[-1].get("automation_id") == "101"
            and native_wait_find_repair_calls[-1].get("include_invisible") is True
            and native_wait_find_repair_calls[-1].get("include_self") is False
            and native_wait_find_repair_calls[-1].get("timeout_ms") == 333
        )
        report["steps"]["win32_wait_find_repair"] = {
            "calls": native_wait_find_repair_calls,
            "strict": native_wait_find_strict,
            "repair": native_wait_find_repair,
            "ok": native_wait_find_repair_ok,
        }

        real_wait_stable_window = globals().get("_wait_stable_window")
        window_repair_calls: List[Dict[str, Any]] = []
        repaired_window = {
            "hwnd": 7001,
            "title": "Demo Player",
            "pid": 8100,
            "process_name": "demo-player.exe",
            "process_path": "C:\\Apps\\Demo\\demo-player.exe",
            "visible": True,
            "rect": {"left": 10, "top": 20, "right": 810, "bottom": 620, "width": 800, "height": 600},
        }

        def fake_wait_stable_window(
            hwnd: Optional[int] = None,
            title: Optional[str] = None,
            process: Optional[str] = None,
            pid: Optional[int] = None,
            timeout: float = 2.0,
            interval: float = 0.1,
            match: str = "contains",
            stable_ticks: int = 2,
        ) -> Dict[str, Any]:
            window_repair_calls.append({
                "hwnd": hwnd,
                "title": title,
                "process": process,
                "pid": pid,
                "timeout": timeout,
                "interval": interval,
                "match": match,
                "stable_ticks": stable_ticks,
            })
            if int(hwnd or 0) == 7001 and title == "Demo Player" and process == "demo-player.exe" and pid == 8100 and match == "exact":
                return {"ok": True, "attempts": 2, "stable_ticks": stable_ticks, "window": repaired_window}
            return {
                "ok": False,
                "error": "timeout",
                "attempts": 1,
                "near_windows": [_compact_window_candidate(repaired_window, title=title, process=process, pid=pid, preferred_hwnd=hwnd, match=match, stable_count=1)],
                "failure_summary": {
                    "selector_suggestions": [
                        {
                            "hwnd": 7001,
                            "title": "Demo Player",
                            "process": "demo-player.exe",
                            "pid": 8100,
                            "match": "exact",
                        }
                    ],
                    "miss_counts": {"title": 1},
                },
            }

        try:
            globals()["_wait_stable_window"] = fake_wait_stable_window
            window_repair_find = window_selector_repair_find(
                original={
                    "title": "Demo App",
                    "process": "demo.exe",
                    "timeout": 0.2,
                    "interval": 0.01,
                    "stable_ticks": 3,
                },
            )
            window_repair_hwnd_only = window_selector_repair_find(
                suggestion={"hwnd": 7001},
                original={},
                probe_original=False,
            )
        finally:
            if real_wait_stable_window is not None:
                globals()["_wait_stable_window"] = real_wait_stable_window
        window_repair_find_ok = bool(
            window_repair_find.get("ok")
            and window_repair_find.get("window_selector_repair") is True
            and window_repair_find.get("source") == "suggestion"
            and window_repair_find.get("hwnd") == 7001
            and len(window_repair_calls) >= 2
            and window_repair_calls[0].get("title") == "Demo App"
            and window_repair_calls[0].get("process") == "demo.exe"
            and window_repair_calls[0].get("stable_ticks") == 3
            and window_repair_calls[1].get("hwnd") == 7001
            and window_repair_calls[1].get("title") == "Demo Player"
            and window_repair_calls[1].get("process") == "demo-player.exe"
            and window_repair_calls[1].get("pid") == 8100
            and window_repair_calls[1].get("match") == "exact"
            and window_repair_hwnd_only.get("ok") is False
            and window_repair_hwnd_only.get("error") == "window_selector_suggestion_only_has_hwnd"
        )
        report["steps"]["window_selector_repair_find"] = {
            "calls": window_repair_calls,
            "result": window_repair_find,
            "hwnd_only": window_repair_hwnd_only,
            "ok": window_repair_find_ok,
        }

        smart_find_attempts: List[Dict[str, Any]] = []
        smart_find_calls: List[Dict[str, Any]] = []

        def fake_find(query: Dict[str, Any]) -> Dict[str, Any]:
            smart_find_calls.append({"view": query.get("view"), "pattern": query.get("pattern")})
            if query.get("view") == "control":
                return {
                    "view": "control",
                    "scanned": 7,
                    "count": 1,
                    "matches": [{"index": 42, "name": "Control Only", "patterns": ["Invoke"]}],
                }
            return {
                "view": query.get("view"),
                "scanned": 3,
                "count": 0,
                "matches": [],
                "near_matches": [{"index": 7, "name": "Almost Control", "selector_score": 41, "selector_reasons": ["name_similarity"]}],
            }

        smart_find = _uia_smart_find(
            fake_find,
            smart_find_attempts,
            patterns=["Invoke"],
            payload={"name": "Control Only", "limit": 1},
            diagnostic=False,
        )
        smart_find_ok = bool(
            smart_find.get("view") == "control"
            and (smart_find.get("selected") or {}).get("index") == 42
            and [call.get("view") for call in smart_find_calls] == ["raw", "control"]
            and (smart_find.get("selected") or {}).get("uia_view") == "control"
        )
        report["steps"]["uia_smart_view_fallback"] = {
            "calls": smart_find_calls,
            "selected_view": smart_find.get("view"),
            "selected_index": (smart_find.get("selected") or {}).get("index"),
            "attempt_methods": [item.get("method") for item in smart_find_attempts],
            "ok": smart_find_ok,
        }

        smart_click_legacy_attempts: List[Dict[str, Any]] = []
        smart_click_legacy_calls: List[Dict[str, Any]] = []

        def fake_smart_click_legacy_find(query: Dict[str, Any]) -> Dict[str, Any]:
            smart_click_legacy_calls.append({"view": query.get("view"), "pattern": query.get("pattern")})
            if query.get("pattern") == "LegacyIAccessible" and query.get("view") == "control":
                return {
                    "view": "control",
                    "scanned": 5,
                    "count": 1,
                    "matches": [{"index": 66, "name": "Legacy Button", "patterns": ["LegacyIAccessible"]}],
                }
            return {"view": query.get("view"), "scanned": 2, "count": 0, "matches": []}

        smart_click_legacy_lookup = _uia_smart_find(
            fake_smart_click_legacy_find,
            smart_click_legacy_attempts,
            patterns=_smart_click_uia_patterns("invoke"),
            payload={"name": "Legacy Button", "limit": 1, "enabled_only": True, "visible_only": True},
            diagnostic=False,
        )
        smart_click_legacy_action = _smart_click_uia_action("invoke", smart_click_legacy_lookup.get("selected") or {})
        smart_click_legacy_ok = bool(
            smart_click_legacy_lookup.get("view") == "control"
            and (smart_click_legacy_lookup.get("selected") or {}).get("index") == 66
            and smart_click_legacy_action == "legacy-default"
            and [item.get("method") for item in smart_click_legacy_attempts][-2:] == [
                "uia.find.raw.LegacyIAccessible",
                "uia.find.control.LegacyIAccessible",
            ]
        )
        report["steps"]["uia_smart_click_legacy_fallback"] = {
            "calls": smart_click_legacy_calls,
            "selected_view": smart_click_legacy_lookup.get("view"),
            "selected_index": (smart_click_legacy_lookup.get("selected") or {}).get("index"),
            "action": smart_click_legacy_action,
            "attempt_methods": [item.get("method") for item in smart_click_legacy_attempts],
            "ok": smart_click_legacy_ok,
        }

        action_chain_default = _smart_click_uia_action_chain("invoke", {"patterns": ["Invoke", "LegacyIAccessible", "SelectionItem"]})
        action_chain_select = _smart_click_uia_action_chain("select", {"patterns": ["Invoke", "LegacyIAccessible", "SelectionItem"]})
        action_chain_check = _smart_click_uia_action_chain("check", {"patterns": ["Toggle", "Invoke", "LegacyIAccessible"]})
        native_action_listbox_invoke = _smart_click_native_action("invoke", {"kind": "listbox"})
        native_action_listview_invoke = _smart_click_native_action("invoke", {"kind": "listview"})
        native_action_tree_default = _smart_click_native_action("default", {"kind": "treeview"})
        native_action_listbox_select = _smart_click_native_action("select", {"kind": "listbox"})
        native_action_tab_invoke = _smart_click_native_action("invoke", {"kind": "tab"})
        native_action_list_check = _smart_click_native_action("check", {"kind": "listview"})
        native_action_tree_uncheck = _smart_click_native_action("uncheck", {"kind": "treeview"})
        native_action_tree_toggle = _smart_click_native_action("toggle", {"kind": "treeview"})
        prepare_chain_virtualized = _smart_uia_prepare_action_chain({"patterns": ["VirtualizedItem", "ScrollItem", "Invoke"]})
        prepare_chain_scroll_only = _smart_uia_prepare_action_chain({"patterns": ["ScrollItem", "SelectionItem"]})
        prepare_chain_plain = _smart_uia_prepare_action_chain({"patterns": ["Invoke"]})
        prepare_calls: List[Dict[str, Any]] = []

        def fake_prepare_action(target: int, index: int, action: str, **kwargs: Any) -> Dict[str, Any]:
            prepare_calls.append({"target": target, "index": index, "action": action, "view": kwargs.get("view")})
            refreshed = {
                "index": index,
                "name": "Prepared",
                "patterns": ["Invoke", "ScrollItem"],
                "rect": {"left": 1, "top": 2, "right": 21, "bottom": 22, "width": 20, "height": 20},
            }
            return {"ok": True, "action": action, "element": refreshed}

        real_perform_action = globals().get("perform_action")
        try:
            globals()["perform_action"] = fake_prepare_action
            prepare_attempts: List[Dict[str, Any]] = []
            prepared_element = _smart_uia_prepare_element(
                4321,
                88,
                {"index": 88, "name": "Before", "patterns": ["VirtualizedItem", "ScrollItem"]},
                "control",
                prepare_attempts,
                max_depth=9,
                max_elements=99,
                diagnostic=False,
            )
        finally:
            globals()["perform_action"] = real_perform_action
        prepare_helper_ok = bool(
            [item.get("action") for item in prepare_calls] == ["realize", "scrollitem"]
            and [item.get("method") for item in prepare_attempts] == ["uia.action.control.realize", "uia.action.control.scrollitem"]
            and prepared_element.get("name") == "Prepared"
            and prepared_element.get("uia_view") == "control"
        )
        smart_click_chain_ok = bool(
            action_chain_default == ["invoke", "legacy-default", "select"]
            and action_chain_select == ["select", "legacy-select", "invoke"]
            and action_chain_check == ["check"]
            and native_action_listbox_invoke == "activate"
            and native_action_listview_invoke == "activate"
            and native_action_tree_default == "activate"
            and native_action_listbox_select == "select"
            and native_action_tab_invoke == "select"
            and native_action_list_check == "check"
            and native_action_tree_uncheck == "uncheck"
            and native_action_tree_toggle == "toggle"
            and prepare_chain_virtualized == ["realize", "scrollitem"]
            and prepare_chain_scroll_only == ["scrollitem"]
            and prepare_chain_plain == []
            and prepare_helper_ok
        )
        report["steps"]["uia_smart_click_action_chain"] = {
            "invoke_chain": action_chain_default,
            "select_chain": action_chain_select,
            "check_chain": action_chain_check,
            "native_actions": {
                "invoke_listbox": native_action_listbox_invoke,
                "invoke_listview": native_action_listview_invoke,
                "default_treeview": native_action_tree_default,
                "select_listbox": native_action_listbox_select,
                "invoke_tab": native_action_tab_invoke,
                "check_listview": native_action_list_check,
                "uncheck_treeview": native_action_tree_uncheck,
                "toggle_treeview": native_action_tree_toggle,
            },
            "prepare_virtualized_chain": prepare_chain_virtualized,
            "prepare_scroll_chain": prepare_chain_scroll_only,
            "prepare_plain_chain": prepare_chain_plain,
            "prepare_calls": prepare_calls,
            "prepared_name": prepared_element.get("name"),
            "ok": smart_click_chain_ok,
        }

        smart_cell_calls: List[Dict[str, Any]] = []

        def fake_cell_find(query: Dict[str, Any]) -> Dict[str, Any]:
            smart_cell_calls.append({"view": query.get("view"), "pattern": query.get("pattern")})
            if query.get("view") == "raw":
                return {
                    "view": "raw",
                    "scanned": 4,
                    "count": 1,
                    "matches": [{"index": 50, "name": "Other", "grid_item": {"row": 0, "column": 1}}],
                }
            if query.get("view") == "content":
                return {
                    "view": "content",
                    "scanned": 5,
                    "count": 1,
                    "matches": [{
                        "index": 77,
                        "name": "Beta",
                        "value": "Done",
                        "grid_item": {"row": 2, "column": 1},
                        "table_item": {"column_headers": [{"name": "State"}]},
                    }],
                }
            return {"view": query.get("view"), "scanned": 2, "count": 0, "matches": []}

        smart_cell_match, smart_cell_view, smart_cell_attempts = _smart_cell_uia_match_from_find(
            fake_cell_find,
            row=2,
            column=1,
            row_text="Beta",
            column_name="State",
            match="exact",
        )
        smart_cell_ok = bool(
            smart_cell_view == "content"
            and (smart_cell_match or {}).get("index") == 77
            and (smart_cell_match or {}).get("uia_view") == "content"
            and [call.get("view") for call in smart_cell_calls[:3]] == ["raw", "control", "content"]
        )
        report["steps"]["uia_smart_cell_view_fallback"] = {
            "calls": smart_cell_calls,
            "selected_view": smart_cell_view,
            "selected_index": (smart_cell_match or {}).get("index"),
            "attempt_methods": [item.get("method") for item in smart_cell_attempts],
            "ok": smart_cell_ok,
        }

        virtualized_attempts: List[Dict[str, Any]] = []
        virtualized_find_calls: List[Dict[str, Any]] = []
        virtualized_item_calls: List[Dict[str, Any]] = []

        def fake_virtualized_find(query: Dict[str, Any]) -> Dict[str, Any]:
            virtualized_find_calls.append({"view": query.get("view"), "pattern": query.get("pattern")})
            if query.get("pattern") == "ItemContainer" and query.get("view") == "control":
                return {
                    "view": "control",
                    "scanned": 4,
                    "count": 1,
                    "matches": [{"index": 12, "name": "Virtual List", "patterns": ["ItemContainer"]}],
                }
            return {"view": query.get("view"), "scanned": 2, "count": 0, "matches": []}

        def fake_item_find(container_index: int, property_name: str, property_value: Any, limit_value: int, view_name: str) -> Dict[str, Any]:
            virtualized_item_calls.append({
                "container_index": container_index,
                "property": property_name,
                "value": property_value,
                "limit": limit_value,
                "view": view_name,
            })
            if container_index == 12 and property_name == "name" and property_value == "Hidden Song":
                return {
                    "ok": True,
                    "count": 1,
                    "matches": [{"index": 91, "name": "Hidden Song", "patterns": ["VirtualizedItem", "SelectionItem"]}],
                }
            return {"ok": False, "count": 0, "matches": []}

        virtualized_lookup = _smart_select_virtualized_find(
            fake_virtualized_find,
            fake_item_find,
            virtualized_attempts,
            item_text="Hidden Song",
            automation_id=None,
            control_type=None,
            class_name=None,
            match="exact",
            requested_index=None,
            diagnostic=False,
        )
        virtualized_ok = bool(
            (virtualized_lookup.get("selected") or {}).get("index") == 91
            and virtualized_lookup.get("view") == "control"
            and (virtualized_lookup.get("selected") or {}).get("container_index") == 12
            and (virtualized_lookup.get("selected") or {}).get("uia_view") == "control"
            and any(call.get("property") == "name" for call in virtualized_item_calls)
        )
        report["steps"]["uia_item_container_virtualized_select"] = {
            "find_calls": virtualized_find_calls,
            "item_calls": virtualized_item_calls,
            "selected_view": virtualized_lookup.get("view"),
            "selected_index": (virtualized_lookup.get("selected") or {}).get("index"),
            "attempt_methods": [item.get("method") for item in virtualized_attempts],
            "ok": virtualized_ok,
        }

        smart_cell_virtualized_attempts: List[Dict[str, Any]] = []
        smart_cell_virtualized_find_calls: List[Dict[str, Any]] = []
        smart_cell_virtualized_item_calls: List[Dict[str, Any]] = []

        def fake_cell_virtualized_find(query: Dict[str, Any]) -> Dict[str, Any]:
            smart_cell_virtualized_find_calls.append({"view": query.get("view"), "pattern": query.get("pattern")})
            if query.get("pattern") == "ItemContainer" and query.get("view") == "content":
                return {
                    "view": "content",
                    "scanned": 6,
                    "count": 1,
                    "matches": [{"index": 33, "name": "Virtual Grid", "patterns": ["ItemContainer"]}],
                }
            return {"view": query.get("view"), "scanned": 2, "count": 0, "matches": []}

        def fake_cell_virtualized_item_find(container_index: int, property_name: str, property_value: Any, limit_value: int, view_name: str) -> Dict[str, Any]:
            smart_cell_virtualized_item_calls.append({
                "container_index": container_index,
                "property": property_name,
                "value": property_value,
                "limit": limit_value,
                "view": view_name,
            })
            if container_index == 33 and property_name == "name" and property_value == "Order 42":
                return {
                    "ok": True,
                    "count": 1,
                    "matches": [{
                        "index": 205,
                        "name": "Order 42",
                        "value": "Ready",
                        "patterns": ["VirtualizedItem", "GridItem", "SelectionItem", "Value"],
                        "grid_item": {"row": 42, "column": 3},
                        "table_item": {"column_headers": [{"name": "Status"}]},
                    }],
                }
            return {"ok": False, "count": 0, "matches": []}

        smart_cell_virtualized_lookup = _smart_cell_virtualized_find(
            fake_cell_virtualized_find,
            fake_cell_virtualized_item_find,
            smart_cell_virtualized_attempts,
            row=None,
            column=3,
            row_text="Order 42",
            column_name="Status",
            automation_id=None,
            match="exact",
            diagnostic=False,
        )
        smart_cell_virtualized_ok = bool(
            smart_cell_virtualized_lookup.get("view") == "content"
            and (smart_cell_virtualized_lookup.get("selected") or {}).get("index") == 205
            and (smart_cell_virtualized_lookup.get("selected") or {}).get("item_container_cell_match") is True
            and (smart_cell_virtualized_lookup.get("selected") or {}).get("uia_view") == "content"
            and any(call.get("property") == "name" for call in smart_cell_virtualized_item_calls)
            and [item.get("method") for item in smart_cell_virtualized_attempts][-1] == "uia.item_container.content.cell.name"
        )
        report["steps"]["uia_item_container_virtualized_cell"] = {
            "find_calls": smart_cell_virtualized_find_calls,
            "item_calls": smart_cell_virtualized_item_calls,
            "selected_view": smart_cell_virtualized_lookup.get("view"),
            "selected_index": (smart_cell_virtualized_lookup.get("selected") or {}).get("index"),
            "attempt_methods": [item.get("method") for item in smart_cell_virtualized_attempts],
            "ok": smart_cell_virtualized_ok,
        }

        smart_cell_virtualized_row_attempts: List[Dict[str, Any]] = []
        smart_cell_virtualized_row_item_calls: List[Dict[str, Any]] = []

        def fake_cell_virtualized_row_item_find(container_index: int, property_name: str, property_value: Any, limit_value: int, view_name: str) -> Dict[str, Any]:
            smart_cell_virtualized_row_item_calls.append({
                "container_index": container_index,
                "property": property_name,
                "value": property_value,
                "limit": limit_value,
                "view": view_name,
            })
            if container_index == 33 and property_name == "name" and property_value == "Order 42":
                return {
                    "ok": True,
                    "count": 1,
                    "matches": [{
                        "index": 230,
                        "name": "Order 42",
                        "patterns": ["VirtualizedItem", "SelectionItem"],
                        "children": [
                            {
                                "index": 231,
                                "name": "Order 42",
                                "value": "Order 42",
                                "patterns": ["GridItem"],
                                "grid_item": {"row": 42, "column": 0},
                                "table_item": {"column_headers": [{"name": "Order"}]},
                            },
                            {
                                "index": 232,
                                "name": "Ready",
                                "value": "Ready",
                                "patterns": ["GridItem", "SelectionItem", "Value"],
                                "grid_item": {"row": 42, "column": 3},
                                "table_item": {"column_headers": [{"name": "Status"}]},
                            },
                        ],
                    }],
                }
            return {"ok": False, "count": 0, "matches": []}

        smart_cell_virtualized_row_lookup = _smart_cell_virtualized_find(
            fake_cell_virtualized_find,
            fake_cell_virtualized_row_item_find,
            smart_cell_virtualized_row_attempts,
            row=None,
            column=3,
            row_text="Order 42",
            column_name="Status",
            automation_id=None,
            match="exact",
            diagnostic=False,
        )
        smart_cell_virtualized_row_ok = bool(
            smart_cell_virtualized_row_lookup.get("view") == "content"
            and (smart_cell_virtualized_row_lookup.get("selected") or {}).get("index") == 232
            and (smart_cell_virtualized_row_lookup.get("selected") or {}).get("item_container_row_child_match") is True
            and (smart_cell_virtualized_row_lookup.get("selected") or {}).get("item_container_row_index") == 230
            and any(item.get("method") == "uia.item_container.content.cell.row_children" and (item.get("result") or {}).get("ok") for item in smart_cell_virtualized_row_attempts)
        )
        report["steps"]["uia_item_container_virtualized_row_cell"] = {
            "item_calls": smart_cell_virtualized_row_item_calls,
            "selected_view": smart_cell_virtualized_row_lookup.get("view"),
            "selected_index": (smart_cell_virtualized_row_lookup.get("selected") or {}).get("index"),
            "attempt_methods": [item.get("method") for item in smart_cell_virtualized_row_attempts],
            "ok": smart_cell_virtualized_row_ok,
        }

        legacy_select_attempts: List[Dict[str, Any]] = []
        legacy_select_calls: List[Dict[str, Any]] = []

        def fake_legacy_select_find(query: Dict[str, Any]) -> Dict[str, Any]:
            legacy_select_calls.append({"view": query.get("view"), "pattern": query.get("pattern")})
            if query.get("pattern") == "LegacyIAccessible" and query.get("view") == "control":
                return {
                    "view": "control",
                    "scanned": 5,
                    "count": 1,
                    "matches": [{"index": 144, "name": "Legacy Row", "patterns": ["LegacyIAccessible"]}],
                }
            return {"view": query.get("view"), "scanned": 2, "count": 0, "matches": []}

        legacy_select_lookup = _uia_smart_find(
            fake_legacy_select_find,
            legacy_select_attempts,
            patterns=["SelectionItem"],
            payload={"name": "Legacy Row", "match": "exact", "limit": 1},
            diagnostic=False,
        )
        if not legacy_select_lookup.get("selected"):
            legacy_select_lookup = _uia_smart_find(
                fake_legacy_select_find,
                legacy_select_attempts,
                patterns=["LegacyIAccessible"],
                payload={"name": "Legacy Row", "match": "exact", "limit": 1},
                requested_index=None,
                diagnostic=False,
                method_prefix="uia.find.legacy_select",
            )
        legacy_select_flags_ok = (
            _smart_select_legacy_flags("select") == MSAA_SELECT_TAKESELECTION
            and _smart_select_legacy_flags("add") == MSAA_SELECT_ADDSELECTION
            and _smart_select_legacy_flags("remove") == MSAA_SELECT_REMOVESELECTION
        )
        smart_select_chain_select = _smart_select_uia_action_chain("select", {"patterns": ["SelectionItem", "LegacyIAccessible"]})
        smart_select_chain_add = _smart_select_uia_action_chain("add", {"patterns": ["SelectionItem", "LegacyIAccessible"]})
        smart_select_chain_remove = _smart_select_uia_action_chain("remove", {"patterns": ["SelectionItem", "LegacyIAccessible"]})
        smart_select_chain_legacy_only = _smart_select_uia_action_chain("select", {"patterns": ["LegacyIAccessible"]})
        smart_select_chain_check = _smart_select_uia_action_chain("check", {"patterns": ["Toggle", "SelectionItem", "LegacyIAccessible"]})
        smart_select_chain_uncheck = _smart_select_uia_action_chain("uncheck", {"patterns": ["Toggle", "SelectionItem"]})
        smart_select_chain_toggle = _smart_select_uia_action_chain("toggle", {"patterns": ["Toggle", "LegacyIAccessible"]})
        smart_select_chain_check_legacy_only = _smart_select_uia_action_chain("check", {"patterns": ["LegacyIAccessible"]})
        smart_select_patterns_select = _smart_select_uia_patterns("select")
        smart_select_patterns_check = _smart_select_uia_patterns("check")
        smart_select_legacy_patterns_select = _smart_select_legacy_patterns("select")
        smart_select_legacy_patterns_check = _smart_select_legacy_patterns("check")
        smart_select_native_check = _smart_select_native_action("check", {"kind": "listview"})
        smart_select_native_uncheck = _smart_select_native_action("uncheck", {"kind": "treeview"})
        smart_select_native_toggle = _smart_select_native_action("toggle", {"kind": "treeview"})
        smart_select_native_remove = _smart_select_native_action("remove", {"kind": "listbox"})
        smart_select_checked_check = _smart_select_native_checked_arg("check", "check")
        smart_select_checked_uncheck = _smart_select_native_checked_arg("uncheck", "uncheck")
        smart_select_checked_toggle = _smart_select_native_checked_arg("toggle", "toggle")
        smart_text_chain_value_legacy = _smart_text_uia_action_chain({"patterns": ["Value", "LegacyIAccessible"]})
        smart_text_chain_value_only = _smart_text_uia_action_chain({"patterns": ["Value"]})
        smart_text_chain_legacy_only = _smart_text_uia_action_chain({"patterns": ["LegacyIAccessible"]})
        smart_select_chain_ok = bool(
            smart_select_chain_select == ["select", "legacy-select"]
            and smart_select_chain_add == ["add-to-selection", "select", "legacy-select"]
            and smart_select_chain_remove == ["remove-from-selection", "legacy-select"]
            and smart_select_chain_legacy_only == ["legacy-select"]
            and smart_select_chain_check == ["check"]
            and smart_select_chain_uncheck == ["uncheck"]
            and smart_select_chain_toggle == ["toggle"]
            and smart_select_chain_check_legacy_only == []
            and smart_select_patterns_select == ["SelectionItem"]
            and smart_select_patterns_check == ["Toggle"]
            and smart_select_legacy_patterns_select == ["LegacyIAccessible"]
            and smart_select_legacy_patterns_check == []
            and smart_select_native_check == "check"
            and smart_select_native_uncheck == "uncheck"
            and smart_select_native_toggle == "toggle"
            and smart_select_native_remove == "multi_select"
            and smart_select_checked_check is True
            and smart_select_checked_uncheck is False
            and smart_select_checked_toggle is None
            and smart_text_chain_value_legacy == ["set-value", "legacy-set-value"]
            and smart_text_chain_value_only == ["set-value"]
            and smart_text_chain_legacy_only == ["legacy-set-value"]
        )
        legacy_select_ok = bool(
            legacy_select_lookup.get("view") == "control"
            and (legacy_select_lookup.get("selected") or {}).get("index") == 144
            and (legacy_select_lookup.get("selected") or {}).get("uia_view") == "control"
            and [item.get("method") for item in legacy_select_attempts][-2:] == [
                "uia.find.legacy_select.raw.LegacyIAccessible",
                "uia.find.legacy_select.control.LegacyIAccessible",
            ]
            and legacy_select_flags_ok
        )
        report["steps"]["uia_smart_select_legacy_fallback"] = {
            "calls": legacy_select_calls,
            "selected_view": legacy_select_lookup.get("view"),
            "selected_index": (legacy_select_lookup.get("selected") or {}).get("index"),
            "flags": {
                "select": _smart_select_legacy_flags("select"),
                "add": _smart_select_legacy_flags("add"),
                "remove": _smart_select_legacy_flags("remove"),
            },
            "attempt_methods": [item.get("method") for item in legacy_select_attempts],
            "ok": legacy_select_ok,
        }
        report["steps"]["uia_smart_select_action_chain"] = {
            "select_chain": smart_select_chain_select,
            "add_chain": smart_select_chain_add,
            "remove_chain": smart_select_chain_remove,
            "legacy_only_chain": smart_select_chain_legacy_only,
            "check_chain": smart_select_chain_check,
            "uncheck_chain": smart_select_chain_uncheck,
            "toggle_chain": smart_select_chain_toggle,
            "check_legacy_only_chain": smart_select_chain_check_legacy_only,
            "patterns_select": smart_select_patterns_select,
            "patterns_check": smart_select_patterns_check,
            "legacy_patterns_select": smart_select_legacy_patterns_select,
            "legacy_patterns_check": smart_select_legacy_patterns_check,
            "native_actions": {
                "check_listview": smart_select_native_check,
                "uncheck_treeview": smart_select_native_uncheck,
                "toggle_treeview": smart_select_native_toggle,
                "remove_listbox": smart_select_native_remove,
            },
            "native_checked": {
                "check": smart_select_checked_check,
                "uncheck": smart_select_checked_uncheck,
                "toggle": smart_select_checked_toggle,
            },
            "text_value_legacy_chain": smart_text_chain_value_legacy,
            "text_value_only_chain": smart_text_chain_value_only,
            "text_legacy_only_chain": smart_text_chain_legacy_only,
            "ok": smart_select_chain_ok,
        }

        smart_text_attempts: List[Dict[str, Any]] = []
        smart_text_calls: List[Dict[str, Any]] = []

        def fake_smart_text_find(query: Dict[str, Any]) -> Dict[str, Any]:
            smart_text_calls.append({"view": query.get("view"), "pattern": query.get("pattern")})
            if query.get("pattern") == "LegacyIAccessible" and query.get("view") == "content":
                return {
                    "view": "content",
                    "scanned": 6,
                    "count": 1,
                    "matches": [{"index": 123, "name": "Legacy Input", "patterns": ["LegacyIAccessible"]}],
                }
            return {"view": query.get("view"), "scanned": 2, "count": 0, "matches": []}

        smart_text_lookup = _smart_text_uia_find(
            fake_smart_text_find,
            smart_text_attempts,
            name="Legacy Input",
            automation_id=None,
            control_type=None,
            class_name=None,
            match="exact",
            requested_index=None,
            diagnostic=False,
        )
        smart_text_methods = [item.get("method") for item in smart_text_attempts]
        smart_text_legacy_ok = bool(
            smart_text_lookup.get("strategy") == "legacy"
            and smart_text_lookup.get("view") == "content"
            and (smart_text_lookup.get("selected") or {}).get("index") == 123
            and (smart_text_lookup.get("selected") or {}).get("uia_view") == "content"
            and smart_text_methods[:3] == [
                "uia.find.value.raw.Value",
                "uia.find.value.control.Value",
                "uia.find.value.content.Value",
            ]
            and smart_text_methods[-1] == "uia.find.legacy.content.LegacyIAccessible"
        )
        report["steps"]["uia_smart_text_legacy_fallback"] = {
            "calls": smart_text_calls,
            "selected_view": smart_text_lookup.get("view"),
            "selected_index": (smart_text_lookup.get("selected") or {}).get("index"),
            "strategy": smart_text_lookup.get("strategy"),
            "attempt_methods": smart_text_methods,
            "ok": smart_text_legacy_ok,
        }

        smart_text_broad_attempts: List[Dict[str, Any]] = []
        smart_text_broad_calls: List[Dict[str, Any]] = []

        def fake_smart_text_broad_find(query: Dict[str, Any]) -> Dict[str, Any]:
            smart_text_broad_calls.append({"view": query.get("view"), "pattern": query.get("pattern"), "control_type": query.get("control_type")})
            if query.get("pattern") == "Value" and query.get("control_type") is None and query.get("view") == "control":
                return {
                    "view": "control",
                    "scanned": 8,
                    "count": 1,
                    "matches": [{"index": 188, "name": "Search Box", "control_type": "custom", "patterns": ["Value"]}],
                }
            return {"view": query.get("view"), "scanned": 3, "count": 0, "matches": []}

        smart_text_broad_lookup = _smart_text_uia_find(
            fake_smart_text_broad_find,
            smart_text_broad_attempts,
            name="Search Box",
            automation_id=None,
            control_type=None,
            class_name=None,
            match="exact",
            requested_index=None,
            diagnostic=False,
        )
        smart_text_broad_methods = [item.get("method") for item in smart_text_broad_attempts]
        smart_text_broad_ok = bool(
            smart_text_broad_lookup.get("strategy") == "value"
            and smart_text_broad_lookup.get("broad_value_match") is True
            and smart_text_broad_lookup.get("view") == "control"
            and (smart_text_broad_lookup.get("selected") or {}).get("index") == 188
            and smart_text_broad_methods[:3] == [
                "uia.find.value.raw.Value",
                "uia.find.value.control.Value",
                "uia.find.value.content.Value",
            ]
            and smart_text_broad_methods[-2:] == [
                "uia.find.value_any.raw.Value",
                "uia.find.value_any.control.Value",
            ]
        )
        report["steps"]["uia_smart_text_broad_value_fallback"] = {
            "calls": smart_text_broad_calls,
            "selected_view": smart_text_broad_lookup.get("view"),
            "selected_index": (smart_text_broad_lookup.get("selected") or {}).get("index"),
            "strategy": smart_text_broad_lookup.get("strategy"),
            "broad_value_match": smart_text_broad_lookup.get("broad_value_match"),
            "attempt_methods": smart_text_broad_methods,
            "ok": smart_text_broad_ok,
        }

        smart_text_typed_attempts: List[Dict[str, Any]] = []
        smart_text_typed_calls: List[Dict[str, Any]] = []

        def fake_smart_text_typed_find(query: Dict[str, Any]) -> Dict[str, Any]:
            smart_text_typed_calls.append({
                "view": query.get("view"),
                "pattern": query.get("pattern"),
                "control_type": query.get("control_type"),
                "class_name": query.get("class_name"),
            })
            if query.get("pattern") == "Value" and query.get("control_type") == "custom" and query.get("class_name") == "SearchBox" and query.get("view") == "raw":
                return {
                    "view": "raw",
                    "scanned": 4,
                    "count": 1,
                    "matches": [{"index": 222, "name": "Custom Search", "control_type": "custom", "class_name": "SearchBox", "patterns": ["Value"]}],
                }
            return {"view": query.get("view"), "scanned": 2, "count": 0, "matches": []}

        smart_text_typed_lookup = _smart_text_uia_find(
            fake_smart_text_typed_find,
            smart_text_typed_attempts,
            name="Custom Search",
            automation_id=None,
            control_type="custom",
            class_name="SearchBox",
            match="exact",
            requested_index=None,
            diagnostic=False,
        )
        smart_text_typed_methods = [item.get("method") for item in smart_text_typed_attempts]
        smart_text_typed_ok = bool(
            smart_text_typed_lookup.get("strategy") == "value"
            and smart_text_typed_lookup.get("broad_value_match") is not True
            and (smart_text_typed_lookup.get("selected") or {}).get("index") == 222
            and smart_text_typed_methods == ["uia.find.value.raw.Value"]
            and smart_text_typed_calls[0].get("control_type") == "custom"
            and smart_text_typed_calls[0].get("class_name") == "SearchBox"
        )
        report["steps"]["uia_smart_text_typed_selector"] = {
            "calls": smart_text_typed_calls,
            "selected_index": (smart_text_typed_lookup.get("selected") or {}).get("index"),
            "attempt_methods": smart_text_typed_methods,
            "ok": smart_text_typed_ok,
        }

        failure_summary = _compact_attempt_failure_summary([
            {"method": "uia.action.control.realize", "result": {"ok": False, "error": "not virtualized"}},
            {"method": "uia.action.control.invoke", "result": {"ok": False, "error": "invoke failed"}},
            {"method": "win32.control_action.press", "result": {"ok": False, "error": "send timeout"}},
            {"method": "focused_input.fallback", "result": {"ok": False, "error": "focus denied"}},
        ])
        failure_summary_ok = bool(
            failure_summary.get("attempt_count") == 4
            and failure_summary.get("uia_prepare_failed_count") == 1
            and failure_summary.get("last_uia_error") == "invoke failed"
            and failure_summary.get("last_win32_error") == "send timeout"
            and failure_summary.get("last_focus_error") == "focus denied"
            and failure_summary.get("failed_methods") == [
                "uia.action.control.realize",
                "uia.action.control.invoke",
                "win32.control_action.press",
                "focused_input.fallback",
            ]
        )
        report["steps"]["smart_action_failure_summary"] = {
            "summary": failure_summary,
            "ok": failure_summary_ok,
        }

        smart_uia_find_failure = {
            "view": "raw",
            "count": 0,
            "scanned": 9,
            "failure_summary": {
                "miss_counts": {"name": 3, "pattern": 1},
                "observed_control_types": [{"value": "button", "count": 4}],
                "observed_classes": [{"value": "Button", "count": 2}],
                "selector_suggestions": [
                    {
                        "index": 4,
                        "name": "Save",
                        "automation_id": "saveButton",
                        "control_type": "button",
                        "class_name": "Button",
                        "pattern": "Invoke",
                        "match": "exact",
                    }
                ],
                "recommendations": ["Requested UIA text did not match; use selector_suggestions."],
            },
        }
        smart_uia_selector_attempts = [
            {"method": "uia.find.raw.Invoke", "result": smart_uia_find_failure},
            {"method": "win32.find_click_child", "count": 0, "candidates": []},
        ]
        smart_uia_selector_failure_summary = _compact_attempt_failure_summary(smart_uia_selector_attempts)
        smart_uia_selector_poll_summary = _smart_click_poll_summary({
            "ok": False,
            "error": "No semantic UIA or native Win32 click path succeeded",
            "attempts": smart_uia_selector_attempts,
        })
        smart_uia_selector_branch_diag = _batch_branch_diagnostic_summary({
            "results": [
                {
                    "id": "smart_click_probe",
                    "command": "smart_click",
                    "result": {
                        "ok": False,
                        "error": "No semantic UIA or native Win32 click path succeeded",
                        "failure_summary": smart_uia_selector_failure_summary,
                    },
                }
            ]
        })
        smart_uia_selector_failure_summary_ok = bool(
            smart_uia_selector_failure_summary.get("last_failure_category") == "selector"
            and smart_uia_selector_failure_summary.get("uia_selector_repair_available") is True
            and smart_uia_selector_failure_summary.get("miss_counts", {}).get("name") == 3
            and (smart_uia_selector_failure_summary.get("selector_suggestions") or [{}])[0].get("automation_id") == "saveButton"
            and (smart_uia_selector_failure_summary.get("next_repair_candidates") or [{}])[0].get("command") == "uia_selector_repair_find"
            and (smart_uia_selector_failure_summary.get("next_repair_candidates") or [{}])[0].get("suggestion", {}).get("automation_id") == "saveButton"
            and (smart_uia_selector_failure_summary.get("next_repair_steps") or [{}])[0].get("command") == "uia_selector_repair_find"
            and (smart_uia_selector_failure_summary.get("next_repair_steps") or [{}])[0].get("ready") is False
            and "hwnd" in ((smart_uia_selector_failure_summary.get("next_repair_steps") or [{}])[0].get("requires") or [])
            and smart_uia_selector_branch_diag.get("uia_selector_repair_available") is True
            and (smart_uia_selector_branch_diag.get("uia_selector_suggestions") or [{}])[0].get("name") == "Save"
            and (smart_uia_selector_branch_diag.get("next_repair_candidates") or [{}])[0].get("kind") == "uia_selector_repair"
            and (smart_uia_selector_branch_diag.get("next_repair_steps") or [{}])[0].get("args", {}).get("suggestion", {}).get("name") == "Save"
            and not smart_uia_selector_branch_diag.get("native_selector_repair_available")
            and smart_uia_selector_poll_summary.get("uia_selector_repair_available") is True
            and (smart_uia_selector_poll_summary.get("uia_selector_suggestions") or [{}])[0].get("automation_id") == "saveButton"
            and (smart_uia_selector_poll_summary.get("next_repair_candidates") or [{}])[0].get("source") == "smart_poll.failure_summary"
            and (smart_uia_selector_poll_summary.get("next_repair_steps") or [{}])[0].get("command") == "uia_selector_repair_find"
            and (smart_uia_selector_poll_summary.get("failure_summary") or {}).get("last_failure_category") == "selector"
        )
        report["steps"]["smart_uia_selector_failure_summary"] = {
            "summary": smart_uia_selector_failure_summary,
            "poll": smart_uia_selector_poll_summary,
            "branch_diagnostic": smart_uia_selector_branch_diag,
            "ok": smart_uia_selector_failure_summary_ok,
        }

        real_smart_click = globals().get("smart_click")
        smart_wait_repair_click_calls: List[Dict[str, Any]] = []

        def fake_smart_wait_repair_click(
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
        ) -> Dict[str, Any]:
            smart_wait_repair_click_calls.append({
                "hwnd": hwnd,
                "name": name,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "index": index,
                "match": match,
                "action": action,
            })
            if automation_id == "saveButton" and name == "Save" and control_type == "button" and index is None:
                return {"ok": True, "hwnd": hwnd, "method": "uia.action.control.invoke", "target": {"index": 4, "name": name}}
            return {"ok": False, "hwnd": hwnd, "error": "still_missing", "attempts": []}

        try:
            globals()["smart_click"] = fake_smart_wait_repair_click
            smart_wait_click_repair = _smart_wait_click_maybe_repair(
                {
                    "ok": False,
                    "hwnd": 2468,
                    "error": "smart_wait_click_timeout",
                    "wait_attempts": 1,
                    "failure_summary": smart_uia_selector_failure_summary,
                },
                2468,
                name="Svae",
                control_type="button",
                match="exact",
                action="invoke",
                timeout=0.0,
                interval=0.01,
                repair=True,
                repair_timeout=0.0,
            )
        finally:
            if real_smart_click is not None:
                globals()["smart_click"] = real_smart_click
        smart_wait_click_repair_ok = bool(
            smart_wait_click_repair.get("ok")
            and smart_wait_click_repair.get("smart_wait_repair") is True
            and smart_wait_click_repair.get("uia_selector_repair") is True
            and smart_wait_repair_click_calls
            and smart_wait_repair_click_calls[-1].get("automation_id") == "saveButton"
            and smart_wait_repair_click_calls[-1].get("name") == "Save"
            and smart_wait_repair_click_calls[-1].get("index") is None
            and (smart_wait_click_repair.get("suggestion") or {}).get("automation_id") == "saveButton"
        )
        report["steps"]["smart_wait_click_selector_repair"] = {
            "calls": smart_wait_repair_click_calls,
            "result": smart_wait_click_repair,
            "ok": smart_wait_click_repair_ok,
        }

        real_smart_text_input = globals().get("smart_text_input")
        smart_wait_repair_text_calls: List[Dict[str, Any]] = []

        def fake_smart_wait_repair_text(
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
        ) -> Dict[str, Any]:
            smart_wait_repair_text_calls.append({
                "hwnd": hwnd,
                "text": text,
                "name": name,
                "automation_id": automation_id,
                "control_type": control_type,
                "class_name": class_name,
                "index": index,
                "match": match,
                "mode": mode,
            })
            if automation_id == "saveButton" and name == "Save" and index is None:
                return {"ok": True, "hwnd": hwnd, "method": "uia.set_value.control", "text_length": len(text)}
            return {"ok": False, "hwnd": hwnd, "error": "still_missing", "attempts": []}

        try:
            globals()["smart_text_input"] = fake_smart_wait_repair_text
            smart_wait_text_repair = _smart_wait_text_maybe_repair(
                {
                    "ok": False,
                    "hwnd": 2468,
                    "error": "smart_wait_text_input_timeout",
                    "wait_attempts": 1,
                    "failure_summary": smart_uia_selector_failure_summary,
                },
                2468,
                "patched",
                name="Svae",
                control_type="edit",
                match="exact",
                timeout=0.0,
                interval=0.01,
                repair=True,
                repair_timeout=0.0,
            )
        finally:
            if real_smart_text_input is not None:
                globals()["smart_text_input"] = real_smart_text_input
        smart_wait_text_repair_ok = bool(
            smart_wait_text_repair.get("ok")
            and smart_wait_text_repair.get("smart_wait_repair") is True
            and smart_wait_text_repair.get("uia_selector_repair") is True
            and smart_wait_repair_text_calls
            and smart_wait_repair_text_calls[-1].get("automation_id") == "saveButton"
            and smart_wait_repair_text_calls[-1].get("name") == "Save"
            and smart_wait_repair_text_calls[-1].get("index") is None
            and smart_wait_repair_text_calls[-1].get("text") == "patched"
        )
        report["steps"]["smart_wait_text_selector_repair"] = {
            "calls": smart_wait_repair_text_calls,
            "result": smart_wait_text_repair,
            "ok": smart_wait_text_repair_ok,
        }

        summary_relocation = {
            "from_index": 5,
            "to_index": 9,
            "score": 590,
            "reasons": ["automation_id", "parent_automation_id"],
        }
        relocated_action_result = {
            "ok": True,
            "action": "invoke",
            "relocated": True,
            "relocation": summary_relocation,
            "element": {"index": 9, "relocation": summary_relocation},
        }
        compact_relocated_action = _compact_uia_action_result({
            "ok": True,
            "action": "invoke",
            "element": {"index": 9, "relocation": summary_relocation},
        })
        relocation_failure_summary = _compact_attempt_failure_summary([
            {"method": "uia.action.control.invoke", "result": relocated_action_result},
        ])
        relocated_poll_summary = _smart_click_poll_summary({
            "ok": True,
            "method": "uia.action.control.invoke",
            "relocated": True,
            "relocation": summary_relocation,
            "attempts": [{"method": "uia.action.control.invoke", "result": relocated_action_result}],
        })
        relocated_cell_summary = _smart_cell_poll_summary({
            "ok": True,
            "method": "uia.action.control.select",
            "row": 2,
            "column": 3,
            "relocated": True,
            "relocation": summary_relocation,
            "attempts": [{"method": "uia.action.control.select", "result": relocated_action_result}],
        })
        relocated_text_summary = _smart_text_input_poll_summary({
            "ok": True,
            "method": "uia.set_value.control",
            "text_length": 6,
            "attempts": [{"method": "uia.set_value.control", "result": relocated_action_result}],
        })
        smart_action_relocation_summary_ok = bool(
            compact_relocated_action.get("relocated") is True
            and compact_relocated_action.get("relocation", {}).get("to_index") == 9
            and relocation_failure_summary.get("uia_relocation_count") == 1
            and relocation_failure_summary.get("last_uia_relocation", {}).get("to_index") == 9
            and relocated_poll_summary.get("relocated") is True
            and relocated_poll_summary.get("relocation", {}).get("to_index") == 9
            and relocated_poll_summary.get("uia_relocation_count") == 1
            and relocated_cell_summary.get("row") == 2
            and relocated_cell_summary.get("relocation", {}).get("to_index") == 9
            and relocated_text_summary.get("text_length") == 6
            and relocated_text_summary.get("last_uia_relocation", {}).get("to_index") == 9
        )
        report["steps"]["smart_action_relocation_summary"] = {
            "compact_action": compact_relocated_action,
            "failure_summary": relocation_failure_summary,
            "poll": relocated_poll_summary,
            "cell": relocated_cell_summary,
            "text": relocated_text_summary,
            "ok": smart_action_relocation_summary_ok,
        }

        smart_helper_transaction_calls: List[Dict[str, Any]] = []
        real_smart_action_helper_post = globals().get("_smart_action_helper_post")
        real_user32_is_window = getattr(user32, "IsWindow")
        try:
            def fake_smart_transaction_post(
                hwnd: int,
                path: str,
                payload: Dict[str, Any],
                *,
                timeout: Optional[float] = None,
            ) -> Optional[Dict[str, Any]]:
                smart_helper_transaction_calls.append({
                    "hwnd": int(hwnd),
                    "path": path,
                    "payload": dict(payload),
                    "timeout": timeout,
                })
                return {
                    "ok": True,
                    "hwnd": int(hwnd),
                    "method": f"helper{path}",
                    "path": path,
                    "smart_action_worker": True,
                }

            globals()["_smart_action_helper_post"] = fake_smart_transaction_post
            user32.IsWindow = lambda _hwnd: True
            helper_click_result = smart_click(
                24680,
                name="OK",
                action="invoke",
                button="right",
                clicks=2,
                allow_coordinate_fallback=True,
                diagnostic=True,
            )
            helper_wait_click_result = smart_wait_click(
                24680,
                name="OK",
                action="invoke",
                timeout=2.5,
                interval=0.2,
                allow_coordinate_fallback=True,
                skip_uia=True,
            )
            helper_text_result = smart_text_input(
                24680,
                "query",
                name="Search",
                mode="append",
                timeout=1.2,
                verify=False,
                allow_focus_fallback=True,
            )
            helper_wait_text_result = smart_wait_text_input(
                24680,
                "query",
                name="Search",
                timeout=3.0,
                interval=0.3,
                input_timeout=1.4,
                verify=False,
                allow_focus_fallback=True,
                skip_uia=True,
            )
        finally:
            globals()["_smart_action_helper_post"] = real_smart_action_helper_post
            user32.IsWindow = real_user32_is_window
        smart_helper_transaction_ok = bool(
            [call.get("path") for call in smart_helper_transaction_calls] == [
                "/smart_click",
                "/smart_wait_click",
                "/smart_text",
                "/smart_wait_text",
            ]
            and all(result.get("smart_action_worker") for result in (
                helper_click_result,
                helper_wait_click_result,
                helper_text_result,
                helper_wait_text_result,
            ))
            and smart_helper_transaction_calls[0].get("payload", {}).get("button") == "right"
            and smart_helper_transaction_calls[0].get("payload", {}).get("clicks") == 2
            and smart_helper_transaction_calls[1].get("timeout") == 2.5
            and smart_helper_transaction_calls[1].get("payload", {}).get("skip_uia") is True
            and smart_helper_transaction_calls[2].get("timeout") == 1.2
            and smart_helper_transaction_calls[2].get("payload", {}).get("mode") == "append"
            and smart_helper_transaction_calls[2].get("payload", {}).get("verify") is False
            and smart_helper_transaction_calls[3].get("timeout") == 3.0
            and smart_helper_transaction_calls[3].get("payload", {}).get("input_timeout") == 1.4
            and smart_helper_transaction_calls[3].get("payload", {}).get("skip_uia") is True
        )
        report["steps"]["smart_helper_transaction_routing"] = {
            "calls": smart_helper_transaction_calls,
            "results": {
                "click": helper_click_result,
                "wait_click": helper_wait_click_result,
                "text": helper_text_result,
                "wait_text": helper_wait_text_result,
            },
            "ok": smart_helper_transaction_ok,
        }

        dialog_helper_transaction_calls: List[Dict[str, Any]] = []
        dialog_helper_local_calls: List[Dict[str, Any]] = []
        real_control_boundary_dialog_helper = globals().get("control_boundary")
        real_helper_current_dialog_helper = globals().get("_helper_current")
        real_ensure_helper_dialog_helper = globals().get("_ensure_helper")
        real_helper_post_dialog_helper = globals().get("_helper_post")
        real_wait_or_use_related_dialog_helper = globals().get("_wait_or_use_related_dialog")
        real_activate_window_dialog_helper = globals().get("activate_window")
        real_command_dialog_helper = globals().get("_command_dialog")
        real_win32_click_candidates_dialog_helper = globals().get("_win32_click_candidates")
        real_win32_click_dialog_helper = globals().get("win32_click")
        try:
            def fake_dialog_helper_control_boundary(hwnd: Optional[int] = None) -> Dict[str, Any]:
                return {
                    "ok": True,
                    "hwnd": int(hwnd or 0),
                    "current_integrity": "medium",
                    "target_integrity": "medium",
                    "uipi_risk": False,
                    "needs_elevation": False,
                    "can_send_input_likely": True,
                    "win32_messages_likely": True,
                    "uia_access_likely": True,
                }

            def fake_dialog_helper_post(path: str, data: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
                dialog_helper_transaction_calls.append({
                    "path": path,
                    "data": dict(data),
                    **kwargs,
                })
                return {
                    "ok": True,
                    "hwnd": int(data.get("hwnd") or 0),
                    "method": f"helper{path}",
                }

            def fake_dialog_helper_wait(
                hwnd: Optional[int],
                **_kwargs: Any,
            ) -> Dict[str, Any]:
                dialog_hwnd = int(hwnd or 24680)
                dialog = {
                    "hwnd": dialog_hwnd,
                    "class_name": "#32770",
                    "title": "Confirm",
                    "visible": True,
                    "root_hwnd": dialog_hwnd,
                }
                return {
                    "ok": True,
                    "hwnd": dialog_hwnd,
                    "dialog_hwnd": dialog_hwnd,
                    "dialog": dialog,
                    "target": dialog,
                    "waited": 0.0,
                    "wait_attempts": 0,
                    "stable_ticks": 1,
                    "direct": True,
                    "candidates": [dialog],
                    "wait_polls": [],
                }

            globals()["control_boundary"] = fake_dialog_helper_control_boundary
            globals()["_helper_current"] = lambda *, elevated=False: False if elevated else True
            globals()["_ensure_helper"] = lambda: dialog_helper_transaction_calls.append({"path": "ensure", "data": {}})
            globals()["_helper_post"] = fake_dialog_helper_post
            globals()["_wait_or_use_related_dialog"] = fake_dialog_helper_wait
            globals()["activate_window"] = lambda hwnd: dialog_helper_local_calls.append({"kind": "activate", "hwnd": hwnd}) or True
            globals()["_command_dialog"] = lambda hwnd, command_id, **kwargs: dialog_helper_local_calls.append({"kind": "command", "hwnd": hwnd, "command_id": command_id, **kwargs}) or {"ok": True}
            globals()["_win32_click_candidates"] = lambda *args, **kwargs: dialog_helper_local_calls.append({"kind": "find_button", "args": args, "kwargs": kwargs}) or []
            globals()["win32_click"] = lambda hwnd, **kwargs: dialog_helper_local_calls.append({"kind": "win32_click", "hwnd": hwnd, **kwargs}) or {"ok": True}

            dialog_helper_command_result = dialog_command_action(
                24680,
                action="yes",
                timeout=0.0,
                activate=True,
                verify_close=True,
            )
            dialog_helper_button_result = dialog_button_action(
                24680,
                name="OK",
                action="ok",
                timeout=0.0,
                activate=True,
                verify_close=True,
                prefer_command=False,
            )
        finally:
            if real_control_boundary_dialog_helper is not None:
                globals()["control_boundary"] = real_control_boundary_dialog_helper
            if real_helper_current_dialog_helper is not None:
                globals()["_helper_current"] = real_helper_current_dialog_helper
            if real_ensure_helper_dialog_helper is not None:
                globals()["_ensure_helper"] = real_ensure_helper_dialog_helper
            if real_helper_post_dialog_helper is not None:
                globals()["_helper_post"] = real_helper_post_dialog_helper
            if real_wait_or_use_related_dialog_helper is not None:
                globals()["_wait_or_use_related_dialog"] = real_wait_or_use_related_dialog_helper
            if real_activate_window_dialog_helper is not None:
                globals()["activate_window"] = real_activate_window_dialog_helper
            if real_command_dialog_helper is not None:
                globals()["_command_dialog"] = real_command_dialog_helper
            if real_win32_click_candidates_dialog_helper is not None:
                globals()["_win32_click_candidates"] = real_win32_click_candidates_dialog_helper
            if real_win32_click_dialog_helper is not None:
                globals()["win32_click"] = real_win32_click_dialog_helper
        dialog_helper_transaction_ok = bool(
            [call.get("path") for call in dialog_helper_transaction_calls] == [
                "ensure",
                "/dialog_command_action",
                "ensure",
                "/dialog_button_action",
            ]
            and dialog_helper_transaction_calls[1].get("data", {}).get("action") == "yes"
            and dialog_helper_transaction_calls[1].get("data", {}).get("command_id") == IDYES
            and dialog_helper_transaction_calls[1].get("data", {}).get("activate") is True
            and dialog_helper_transaction_calls[1].get("data", {}).get("verify_close") is True
            and dialog_helper_transaction_calls[3].get("data", {}).get("name") == "OK"
            and dialog_helper_transaction_calls[3].get("data", {}).get("prefer_command") is False
            and dialog_helper_transaction_calls[3].get("data", {}).get("activate") is True
            and dialog_helper_transaction_calls[3].get("data", {}).get("verify_close") is True
            and isinstance(dialog_helper_command_result, dict)
            and dialog_helper_command_result.get("helper") is True
            and dialog_helper_command_result.get("helper_elevated") is False
            and isinstance(dialog_helper_button_result, dict)
            and dialog_helper_button_result.get("helper") is True
            and dialog_helper_button_result.get("helper_elevated") is False
            and dialog_helper_local_calls == []
        )
        report["steps"]["dialog_helper_transaction_routing"] = {
            "calls": dialog_helper_transaction_calls,
            "local_calls": dialog_helper_local_calls,
            "results": {
                "command": dialog_helper_command_result,
                "button": dialog_helper_button_result,
            },
            "ok": dialog_helper_transaction_ok,
        }

        elevation_calls: List[Dict[str, Any]] = []
        elevation_mouse_calls: List[Dict[str, Any]] = []
        elevation_native_results: Dict[str, Any] = {}
        real_control_boundary = globals().get("control_boundary")
        real_helper_current = globals().get("_helper_current")
        real_ensure_helper = globals().get("_ensure_helper")
        real_helper_post = globals().get("_helper_post")
        real_desktop_point_to_screen = globals().get("_desktop_point_to_screen")
        real_hwnd_from_screen_point = globals().get("_hwnd_from_screen_point")
        real_mouse_click_screen = globals().get("_mouse_click_screen")
        real_set_cursor_pos_checked = globals().get("_set_cursor_pos_checked")
        real_send_mouse_input = globals().get("_send_mouse_input")
        real_force_foreground_window = globals().get("_force_foreground_window")
        real_win32_window_info = globals().get("_win32_window_info")
        real_find_file_dialog = globals().get("_find_file_dialog")
        real_wait_related_dialog = globals().get("wait_related_dialog")
        real_wait_or_use_related_dialog = globals().get("_wait_or_use_related_dialog")
        try:
            def fake_control_boundary(hwnd: Optional[int] = None) -> Dict[str, Any]:
                return {
                    "ok": True,
                    "hwnd": int(hwnd or 0),
                    "current_integrity": "medium",
                    "target_integrity": "high",
                    "uipi_risk": True,
                    "needs_elevation": True,
                    "can_send_input_likely": False,
                    "win32_messages_likely": False,
                    "uia_access_likely": False,
                    "reasons": ["target integrity is higher than current process"],
                }

            def fake_helper_current(*, elevated: bool = False) -> bool:
                return False if elevated else True

            def fake_helper_post(path: str, data: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
                elevation_calls.append({"kind": "post", "path": path, "data": dict(data), **kwargs})
                return {"ok": True}

            def fake_win32_window_info(hwnd: int, **_kwargs: Any) -> Dict[str, Any]:
                return {
                    "hwnd": int(hwnd),
                    "class_name": "Button",
                    "title": "Elevated Button",
                    "visible": True,
                    "enabled": True,
                    "root_hwnd": int(hwnd),
                }

            def fake_find_file_dialog(hwnd: Optional[int] = None, timeout: float = 0.0, match: str = "contains") -> Dict[str, Any]:
                return {
                    "ok": True,
                    "attempts": 1,
                    "window": {
                        "hwnd": int(hwnd or 24680),
                        "class_name": "#32770",
                        "title": "Open",
                        "visible": True,
                        "root_hwnd": int(hwnd or 24680),
                    },
                    "candidates": [],
                }

            def fake_wait_or_use_related_dialog(
                hwnd: Optional[int],
                **_kwargs: Any,
            ) -> Dict[str, Any]:
                dialog_hwnd = int(hwnd or 24680)
                dialog = {
                    "hwnd": dialog_hwnd,
                    "class_name": "#32770",
                    "title": "Confirm",
                    "visible": True,
                    "root_hwnd": dialog_hwnd,
                }
                return {
                    "ok": True,
                    "hwnd": dialog_hwnd,
                    "dialog_hwnd": dialog_hwnd,
                    "dialog": dialog,
                    "target": dialog,
                    "waited": 0.0,
                    "wait_attempts": 0,
                    "stable_ticks": 1,
                    "direct": True,
                    "candidates": [dialog],
                    "wait_polls": [],
                }

            globals()["control_boundary"] = fake_control_boundary
            globals()["_helper_current"] = fake_helper_current
            globals()["_ensure_helper"] = lambda: elevation_calls.append({"kind": "ensure"})
            globals()["_helper_post"] = fake_helper_post
            globals()["_desktop_point_to_screen"] = lambda x, y, screenshot_id=None: (int(x) + 100, int(y) + 200, "fake desktop point")
            globals()["_hwnd_from_screen_point"] = lambda _x, _y: 24680
            globals()["_mouse_click_screen"] = lambda *args, **kwargs: elevation_mouse_calls.append({"kind": "click", "args": args, "kwargs": kwargs})
            globals()["_set_cursor_pos_checked"] = lambda *args, **kwargs: elevation_mouse_calls.append({"kind": "move", "args": args, "kwargs": kwargs})
            globals()["_send_mouse_input"] = lambda *args, **kwargs: elevation_mouse_calls.append({"kind": "input", "args": args, "kwargs": kwargs})
            globals()["_force_foreground_window"] = lambda *args, **kwargs: elevation_mouse_calls.append({"kind": "foreground", "args": args, "kwargs": kwargs}) or {"ok": True}
            globals()["_win32_window_info"] = fake_win32_window_info
            globals()["_find_file_dialog"] = fake_find_file_dialog
            globals()["wait_related_dialog"] = fake_wait_or_use_related_dialog
            globals()["_wait_or_use_related_dialog"] = fake_wait_or_use_related_dialog

            route_ready, route_elevated, route_result = _helper_route_for_hwnd(24680, "/type_text")
            cli_click_result = click(24680, 10, 20)
            cli_type_result = type_text(24680, "abc")
            cli_desktop_click_result = desktop_click(10, 20)
            cli_activate_result = activate_window(24680)
            cli_uia_find_result = find_elements(24680, name="OK", limit=1)
            cli_smart_result = _smart_action_helper_post(24680, "/smart_click", {"name": "OK"})
            cli_batch_result = execute_batch([
                {"command": "type", "args": {"hwnd": 24680, "text": "abc"}},
            ])
            elevation_native_results = {
                "child_windows": child_windows(24680),
                "window_from_point": window_from_point(x=10, y=20),
                "msaa_window": msaa_window(24680),
                "msaa_from_point": msaa_from_point(x=10, y=20),
                "msaa_action": msaa_action(24680, action="default"),
                "menu_tree": menu_tree(24680),
                "menu_action": menu_action(24680, command_id=100),
                "win32_text": win32_text(24680),
                "win32_set_text": win32_set_text(24680, "value"),
                "win32_click": win32_click(24680),
                "file_dialog_info": file_dialog_info(hwnd=24680, timeout=0.0),
                "file_dialog_action": file_dialog_action("cancel", hwnd=24680, timeout=0.0),
                "win32_control_find": win32_control_find(24680, name="OK"),
                "win32_selector_repair_find": win32_selector_repair_find(24680, {"automation_id": "101"}),
                "win32_control_wait_find": win32_control_wait_find(24680, name="OK", timeout=0.0),
                "win32_control_info": win32_control_info(24680),
                "win32_control_action": win32_control_action(24680, "click"),
                "win32_control_wait": win32_control_wait(24680, state="checked", expected=True, timeout=0.0),
                "dialog_command_action": dialog_command_action(24680, action="ok", timeout=0.0, activate=True),
                "dialog_button_action": dialog_button_action(24680, action="ok", timeout=0.0, activate=True),
                "smart_dialog_action": smart_dialog_action(24680, action_kind="click", name="OK", timeout=0.0, activate=True),
            }
        finally:
            if real_control_boundary is not None:
                globals()["control_boundary"] = real_control_boundary
            if real_helper_current is not None:
                globals()["_helper_current"] = real_helper_current
            if real_ensure_helper is not None:
                globals()["_ensure_helper"] = real_ensure_helper
            if real_helper_post is not None:
                globals()["_helper_post"] = real_helper_post
            if real_desktop_point_to_screen is not None:
                globals()["_desktop_point_to_screen"] = real_desktop_point_to_screen
            if real_hwnd_from_screen_point is not None:
                globals()["_hwnd_from_screen_point"] = real_hwnd_from_screen_point
            if real_mouse_click_screen is not None:
                globals()["_mouse_click_screen"] = real_mouse_click_screen
            if real_set_cursor_pos_checked is not None:
                globals()["_set_cursor_pos_checked"] = real_set_cursor_pos_checked
            if real_send_mouse_input is not None:
                globals()["_send_mouse_input"] = real_send_mouse_input
            if real_force_foreground_window is not None:
                globals()["_force_foreground_window"] = real_force_foreground_window
            if real_win32_window_info is not None:
                globals()["_win32_window_info"] = real_win32_window_info
            if real_find_file_dialog is not None:
                globals()["_find_file_dialog"] = real_find_file_dialog
            if real_wait_related_dialog is not None:
                globals()["wait_related_dialog"] = real_wait_related_dialog
            if real_wait_or_use_related_dialog is not None:
                globals()["_wait_or_use_related_dialog"] = real_wait_or_use_related_dialog
        elevation_boundary_routing_ok = bool(
            elevation_calls == []
            and elevation_mouse_calls == []
            and route_ready is False
            and route_elevated is False
            and isinstance(route_result, dict)
            and route_result.get("error") == "elevated_helper_required"
            and str(cli_click_result).startswith("Error: elevated_helper_required")
            and str(cli_type_result).startswith("Error: elevated_helper_required")
            and str(cli_desktop_click_result).startswith("Error: elevated_helper_required")
            and cli_activate_result is False
            and isinstance(cli_uia_find_result, dict)
            and cli_uia_find_result.get("error") == "elevated_helper_required"
            and isinstance(cli_smart_result, dict)
            and cli_smart_result.get("error") == "elevated_helper_required"
            and cli_smart_result.get("smart_action_worker") is True
            and isinstance(cli_batch_result, dict)
            and cli_batch_result.get("error") == "elevated_helper_required"
            and cli_batch_result.get("command_count") == 1
            and all(
                isinstance(result, dict)
                and result.get("error") == "elevated_helper_required"
                and result.get("failure_category") == "blocked_or_elevation"
                for result in elevation_native_results.values()
            )
        )
        report["steps"]["elevation_boundary_routing"] = {
            "route_result": route_result,
            "click": cli_click_result,
            "type": cli_type_result,
            "desktop_click": cli_desktop_click_result,
            "activate": cli_activate_result,
            "uia_find": cli_uia_find_result,
            "smart": cli_smart_result,
            "batch": cli_batch_result,
            "native_results": elevation_native_results,
            "helper_calls": elevation_calls,
            "mouse_calls": elevation_mouse_calls,
            "ok": elevation_boundary_routing_ok,
        }

        win32_button_action_calls: List[Dict[str, Any]] = []
        real_button_helper_route = globals().get("_helper_route_for_hwnd")
        real_button_control_info = globals().get("win32_control_info")
        real_button_send_message = globals().get("_send_message_timeout")
        try:
            def fake_button_helper_route(_hwnd: Optional[int], _path: str = "") -> Tuple[bool, bool, Optional[Dict[str, Any]]]:
                return False, False, None

            def fake_button_control_info(hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> Dict[str, Any]:
                return {
                    "hwnd": int(hwnd),
                    "kind": "button",
                    "window": {
                        "hwnd": int(hwnd),
                        "class_name": "Button",
                        "title": "Run",
                        "parent_hwnd": 13579,
                        "control_id": 246,
                    },
                    "check_state": BST_UNCHECKED,
                    "checked": False,
                    "max_items": max_items,
                    "timeout_ms": timeout_ms,
                }

            def fake_button_send_message(
                hwnd: int,
                msg: int,
                wparam: int = 0,
                lparam: int = 0,
                timeout_ms: int = 500,
            ) -> Tuple[bool, int]:
                win32_button_action_calls.append({
                    "hwnd": int(hwnd),
                    "msg": int(msg),
                    "wparam": int(wparam),
                    "lparam": int(lparam),
                    "timeout_ms": int(timeout_ms),
                })
                return True, 0

            globals()["_helper_route_for_hwnd"] = fake_button_helper_route
            globals()["win32_control_info"] = fake_button_control_info
            globals()["_send_message_timeout"] = fake_button_send_message
            win32_button_press_result = win32_control_action(24680, "press", timeout_ms=321)
            win32_button_default_result = win32_control_action(24680, "default", timeout_ms=322)
        finally:
            globals()["_helper_route_for_hwnd"] = real_button_helper_route
            globals()["win32_control_info"] = real_button_control_info
            globals()["_send_message_timeout"] = real_button_send_message
        win32_button_action_ok = bool(
            win32_button_press_result.get("ok")
            and win32_button_default_result.get("ok")
            and win32_button_press_result.get("method") == "SendMessageTimeoutW"
            and win32_button_default_result.get("method") == "SendMessageTimeoutW"
            and [call.get("msg") for call in win32_button_action_calls] == [BM_CLICK, BM_CLICK]
            and [call.get("timeout_ms") for call in win32_button_action_calls] == [321, 322]
        )
        report["steps"]["win32_button_click_action"] = {
            "calls": win32_button_action_calls,
            "results": {
                "press": win32_button_press_result,
                "default": win32_button_default_result,
            },
            "ok": win32_button_action_ok,
        }

        toolbar_send_calls: List[Dict[str, Any]] = []
        toolbar_click_calls: List[Dict[str, Any]] = []
        toolbar_notify_calls: List[Dict[str, Any]] = []
        real_toolbar_send_message = globals().get("_send_message_timeout")
        real_toolbar_client_click = globals().get("_send_client_click_sequence")
        real_toolbar_notify_parent = globals().get("_win32_notify_parent")
        try:
            toolbar_click_results = [
                {"ok": True, "method": "fake_client_click"},
                {"ok": False, "error": "client click unavailable"},
            ]

            def fake_toolbar_send_message(
                hwnd: int,
                msg: int,
                wparam: int = 0,
                lparam: int = 0,
                timeout_ms: int = 500,
            ) -> Tuple[bool, int]:
                toolbar_send_calls.append({
                    "hwnd": int(hwnd),
                    "msg": int(msg),
                    "wparam": int(wparam),
                    "lparam": int(lparam),
                    "timeout_ms": int(timeout_ms),
                })
                return True, 1

            def fake_toolbar_client_click(
                hwnd: int,
                x: int,
                y: int,
                clicks: int = 2,
                timeout_ms: int = 500,
            ) -> Dict[str, Any]:
                toolbar_click_calls.append({
                    "hwnd": int(hwnd),
                    "x": int(x),
                    "y": int(y),
                    "clicks": int(clicks),
                    "timeout_ms": int(timeout_ms),
                })
                return toolbar_click_results.pop(0) if toolbar_click_results else {"ok": False, "error": "unexpected click"}

            def fake_toolbar_notify_parent(info: Dict[str, Any], notification: int) -> bool:
                toolbar_notify_calls.append({
                    "hwnd": int(info.get("hwnd") or 0),
                    "parent_hwnd": int(info.get("parent_hwnd") or 0),
                    "control_id": int(info.get("control_id") or 0),
                    "notification": int(notification),
                })
                return True

            globals()["_send_message_timeout"] = fake_toolbar_send_message
            globals()["_send_client_click_sequence"] = fake_toolbar_client_click
            globals()["_win32_notify_parent"] = fake_toolbar_notify_parent
            toolbar_info = {"hwnd": 24690, "parent_hwnd": 13579, "control_id": 9000}
            toolbar_rect = {"left": 10, "top": 20, "right": 50, "bottom": 60}
            toolbar_client_click_result = _toolbar_button_action(
                24690,
                2,
                901,
                toolbar_info,
                rect=toolbar_rect,
                timeout_ms=321,
            )
            toolbar_notify_fallback_result = _toolbar_button_action(
                24690,
                3,
                902,
                toolbar_info,
                rect=toolbar_rect,
                timeout_ms=322,
            )
            toolbar_check_result = _toolbar_button_action(
                24690,
                4,
                903,
                toolbar_info,
                check_target=True,
                rect=toolbar_rect,
                timeout_ms=323,
            )
        finally:
            globals()["_send_message_timeout"] = real_toolbar_send_message
            globals()["_send_client_click_sequence"] = real_toolbar_client_click
            globals()["_win32_notify_parent"] = real_toolbar_notify_parent
        toolbar_press_calls = [call for call in toolbar_send_calls if call.get("msg") == TB_PRESSBUTTON]
        toolbar_check_calls = [call for call in toolbar_send_calls if call.get("msg") == TB_CHECKBUTTON]
        toolbar_button_action_ok = bool(
            toolbar_client_click_result.get("ok")
            and toolbar_client_click_result.get("notified_parent") is False
            and toolbar_client_click_result.get("notify_fallback") is None
            and (toolbar_client_click_result.get("click") or {}).get("ok") is True
            and toolbar_notify_fallback_result.get("ok")
            and toolbar_notify_fallback_result.get("notified_parent") is True
            and toolbar_notify_fallback_result.get("notify_fallback") == "client_click_unavailable"
            and (toolbar_notify_fallback_result.get("click") or {}).get("ok") is False
            and toolbar_check_result.get("ok")
            and toolbar_check_result.get("notified_parent") is True
            and [call.get("wparam") for call in toolbar_press_calls] == [901, 901, 902, 902]
            and [call.get("lparam") for call in toolbar_press_calls] == [1, 0, 1, 0]
            and [call.get("timeout_ms") for call in toolbar_press_calls] == [321, 321, 322, 322]
            and [call.get("wparam") for call in toolbar_check_calls] == [903]
            and [call.get("lparam") for call in toolbar_check_calls] == [1]
            and [call.get("control_id") for call in toolbar_notify_calls] == [902, 903]
            and [call.get("clicks") for call in toolbar_click_calls] == [1, 1]
        )
        report["steps"]["toolbar_button_action_contract"] = {
            "send_calls": toolbar_send_calls,
            "click_calls": toolbar_click_calls,
            "notify_calls": toolbar_notify_calls,
            "results": {
                "client_click": toolbar_client_click_result,
                "notify_fallback": toolbar_notify_fallback_result,
                "check": toolbar_check_result,
            },
            "ok": toolbar_button_action_ok,
        }

        real_wait_control_info = globals().get("win32_control_info")
        try:
            def fake_wait_control_info(hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> Dict[str, Any]:
                return {
                    "hwnd": int(hwnd),
                    "kind": "edit",
                    "window": {
                        "hwnd": int(hwnd),
                        "class_name": "Edit",
                        "title": "Alpha Beta Gamma",
                        "parent_hwnd": 13579,
                        "control_id": 248,
                    },
                    "text": {"ok": True, "text": "Alpha Beta Gamma", "length": 16},
                    "selection": {"start": 6, "end": 10},
                    "selected_text": "Beta",
                    "max_items": max_items,
                    "timeout_ms": timeout_ms,
                }

            globals()["win32_control_info"] = fake_wait_control_info
            selection_aliases = {
                "selection text": _normalize_win32_wait_state("selection text"),
                "caret-position": _normalize_win32_wait_state("caret-position"),
                "selection-len": _normalize_win32_wait_state("selection-len"),
            }
            selected_text_wait = _win32_control_wait_once(24682, state="selection text", expected="Beta", match="exact")
            selected_text_contains_wait = _win32_control_wait_once(24682, state="selected-text", expected="et", match="contains")
            selection_start_wait = _win32_control_wait_once(24682, state="selection-start", expected="6")
            selection_end_wait = _win32_control_wait_once(24682, state="caret", expected=10)
            selection_length_wait = _win32_control_wait_once(24682, state="selection-length", expected=4)
        finally:
            globals()["win32_control_info"] = real_wait_control_info
        win32_wait_selection_state_ok = bool(
            selection_aliases == {
                "selection text": "selected_text",
                "caret-position": "selection_end",
                "selection-len": "selection_length",
            }
            and selected_text_wait.get("ok")
            and selected_text_wait.get("actual") == "Beta"
            and selected_text_contains_wait.get("ok")
            and selection_start_wait.get("ok")
            and selection_start_wait.get("actual") == 6
            and selection_end_wait.get("ok")
            and selection_end_wait.get("actual") == 10
            and selection_length_wait.get("ok")
            and selection_length_wait.get("actual") == 4
        )
        report["steps"]["win32_wait_selection_state_contract"] = {
            "aliases": selection_aliases,
            "results": {
                "selected_text": selected_text_wait,
                "selected_text_contains": selected_text_contains_wait,
                "selection_start": selection_start_wait,
                "selection_end": selection_end_wait,
                "selection_length": selection_length_wait,
            },
            "ok": win32_wait_selection_state_ok,
        }

        real_presence_control_info = globals().get("win32_control_info")
        real_presence_helper_route = globals().get("_helper_route_for_hwnd")
        try:
            def fake_presence_control_info(hwnd: int, timeout_ms: int = 500, max_items: int = 200) -> Dict[str, Any]:
                if int(hwnd) == 24684:
                    return {
                        "hwnd": int(hwnd),
                        "kind": "button",
                        "window": {
                            "hwnd": int(hwnd),
                            "class_name": "Button",
                            "title": "Run",
                            "parent_hwnd": 13579,
                            "control_id": 249,
                        },
                        "text": {"ok": True, "text": "Run", "length": 3},
                        "max_items": max_items,
                        "timeout_ms": timeout_ms,
                    }
                if int(hwnd) == 24685:
                    return {
                        "hwnd": int(hwnd),
                        "kind": "listbox",
                        "window": {
                            "hwnd": int(hwnd),
                            "class_name": "ListBox",
                            "title": "",
                            "parent_hwnd": 13579,
                            "control_id": 251,
                        },
                        "count": 2,
                        "selected_index": -1,
                        "items": [
                            {"index": 0, "text": "Alpha", "selected": False},
                            {"index": 1, "text": "Beta Extended", "selected": False},
                        ],
                        "max_items": max_items,
                        "timeout_ms": timeout_ms,
                    }
                return {
                    "hwnd": int(hwnd),
                    "kind": "listbox",
                    "window": {
                        "hwnd": int(hwnd),
                        "class_name": "ListBox",
                        "title": "",
                        "parent_hwnd": 13579,
                        "control_id": 250,
                    },
                    "count": 2,
                    "selected_index": -1,
                    "items": [
                        {"index": 0, "text": "Alpha", "selected": False},
                        {"index": 1, "text": "Beta", "selected": False},
                    ],
                    "max_items": max_items,
                    "timeout_ms": timeout_ms,
                }

            globals()["win32_control_info"] = fake_presence_control_info
            globals()["_helper_route_for_hwnd"] = lambda _hwnd, _path: (False, False, None)
            presence_aliases = {
                "exists": _normalize_win32_wait_state("exists"),
                "item-missing": _normalize_win32_wait_state("item-missing"),
            }
            present_beta = _win32_control_wait_once(24683, state="exists", text="Beta", match="exact")
            present_missing_false = _win32_control_wait_once(24683, state="present", expected=False, text="Delta", match="exact")
            absent_delta = _win32_control_wait_once(24683, state="gone", text="Delta", match="exact")
            absent_beta_false = _win32_control_wait_once(24683, state="absent", expected=False, text="Beta", match="exact")
            present_index = _win32_control_wait_once(24683, state="present", index=1)
            absent_index = _win32_control_wait_once(24683, state="absent", index=5)
            present_button_text = _win32_control_wait_once(24684, state="present", text="Run", match="exact")
            missing_present_summary = _win32_control_wait_failure_summary(
                _win32_control_wait_once(24683, state="present", text="Delta", match="exact"),
                state="present",
                text="Delta",
                match="exact",
            )
            direct_repair_strict = win32_control_wait(
                24685,
                state="present",
                expected=True,
                text="Beta",
                match="exact",
                timeout=0.0,
                interval=0.01,
                repair=False,
            )
            direct_repair_result = win32_control_wait(
                24685,
                state="present",
                expected=True,
                text="Beta",
                match="exact",
                timeout=0.0,
                interval=0.01,
                repair=True,
                repair_timeout=0.0,
            )
        finally:
            globals()["win32_control_info"] = real_presence_control_info
            globals()["_helper_route_for_hwnd"] = real_presence_helper_route
        win32_wait_presence_state_ok = bool(
            presence_aliases == {"exists": "present", "item-missing": "absent"}
            and present_beta.get("ok")
            and present_beta.get("actual") is True
            and present_beta.get("present") is True
            and (present_beta.get("target") or {}).get("index") == 1
            and present_missing_false.get("ok")
            and present_missing_false.get("actual") is False
            and present_missing_false.get("present") is False
            and absent_delta.get("ok")
            and absent_delta.get("actual") is True
            and absent_delta.get("present") is False
            and absent_beta_false.get("ok")
            and absent_beta_false.get("actual") is False
            and absent_beta_false.get("present") is True
            and present_index.get("ok")
            and (present_index.get("target") or {}).get("text") == "Beta"
            and absent_index.get("ok")
            and absent_index.get("present") is False
            and present_button_text.get("ok")
            and present_button_text.get("present") is True
            and missing_present_summary.get("item_count") == 2
            and ((missing_present_summary.get("item_preview") or [{}])[0]).get("text") == "Alpha"
            and bool(missing_present_summary.get("recommendations"))
        )
        win32_wait_repair_ok = bool(
            direct_repair_strict.get("ok") is False
            and direct_repair_strict.get("matched") is False
            and ((direct_repair_strict.get("failure_summary") or {}).get("repair_suggestions") or [{}])[0].get("match") == "contains"
            and direct_repair_result.get("ok") is True
            and direct_repair_result.get("matched") is True
            and direct_repair_result.get("repaired") is True
            and (direct_repair_result.get("repair") or {}).get("match") == "contains"
            and (direct_repair_result.get("target") or {}).get("text") == "Beta Extended"
        )
        report["steps"]["win32_wait_presence_state_contract"] = {
            "aliases": presence_aliases,
            "missing_present_summary": missing_present_summary,
            "results": {
                "present_beta": present_beta,
                "present_missing_false": present_missing_false,
                "absent_delta": absent_delta,
                "absent_beta_false": absent_beta_false,
                "present_index": present_index,
                "absent_index": absent_index,
                "present_button_text": present_button_text,
            },
            "ok": win32_wait_presence_state_ok,
        }
        report["steps"]["win32_wait_repair_contract"] = {
            "strict": direct_repair_strict,
            "repaired": direct_repair_result,
            "ok": win32_wait_repair_ok,
        }

        ad_hoc_hwnd = 987654
        ad_hoc_index = 55
        ad_hoc_elem = object()
        _uia_element_cache[ad_hoc_hwnd] = {ad_hoc_index: ad_hoc_elem}
        _uia_ad_hoc_element_indices[ad_hoc_hwnd] = {ad_hoc_index}
        ad_hoc_info_calls: List[Dict[str, Any]] = []
        real_element_info = globals().get("_element_info")
        real_last_uia_scan_options = globals().get("_last_uia_scan_options")
        try:
            def fake_ad_hoc_element_info(elem: Any, index: Optional[int] = None, depth: Optional[int] = None) -> Dict[str, Any]:
                ad_hoc_info_calls.append({"same": elem is ad_hoc_elem, "index": index, "depth": depth})
                return {"index": index, "name": "AdHoc Virtual Item", "ad_hoc": elem is ad_hoc_elem}

            def fake_last_uia_scan_options(_hwnd: int) -> Dict[str, Any]:
                raise AssertionError("ad-hoc UIA element should not trigger tree rescan")

            globals()["_element_info"] = fake_ad_hoc_element_info
            globals()["_last_uia_scan_options"] = fake_last_uia_scan_options
            resolved_elem, resolved_info = _uia_element_by_index(ad_hoc_hwnd, ad_hoc_index)
        finally:
            globals()["_element_info"] = real_element_info
            globals()["_last_uia_scan_options"] = real_last_uia_scan_options
            _uia_element_cache.pop(ad_hoc_hwnd, None)
            _uia_ad_hoc_element_indices.pop(ad_hoc_hwnd, None)
        ad_hoc_cache_ok = bool(
            resolved_elem is ad_hoc_elem
            and resolved_info.get("ad_hoc") is True
            and ad_hoc_info_calls == [{"same": True, "index": ad_hoc_index, "depth": None}]
        )
        report["steps"]["uia_ad_hoc_element_cache"] = {
            "resolved_index": resolved_info.get("index"),
            "calls": ad_hoc_info_calls,
            "ok": ad_hoc_cache_ok,
        }

        relocation_hwnd = 987656
        relocation_old_index = 5
        relocation_new_index = 9
        relocation_old_info = {
            "index": relocation_old_index,
            "depth": 3,
            "name": "Save",
            "automation_id": "cmdSave",
            "control_type": "button",
            "control_type_id": 50000,
            "class_name": "Button",
            "framework_id": "Win32",
            "native_window_handle": 1200,
            "enabled": True,
            "visible": True,
            "keyboard_focusable": True,
            "rect": {
                "left": 20,
                "top": 40,
                "right": 120,
                "bottom": 70,
                "width": 100,
                "height": 30,
                "center_x": 70,
                "center_y": 55,
            },
            "patterns": ["Invoke", "LegacyIAccessible"],
        }
        relocation_wrong_info = dict(
            relocation_old_info,
            index=relocation_old_index,
            name="Cancel",
            automation_id="cmdCancel",
            native_window_handle=0,
            rect={
                "left": 300,
                "top": 400,
                "right": 420,
                "bottom": 430,
                "width": 120,
                "height": 30,
                "center_x": 360,
                "center_y": 415,
            },
        )
        relocation_new_info = dict(
            relocation_old_info,
            index=relocation_new_index,
            rect={
                "left": 22,
                "top": 42,
                "right": 122,
                "bottom": 72,
                "width": 100,
                "height": 30,
                "center_x": 72,
                "center_y": 57,
            },
        )
        stable_parent = {
            "name": "Document Commands",
            "automation_id": "paneDocumentCommands",
            "control_type": "toolbar",
            "control_type_id": 50021,
            "class_name": "ToolbarWindow32",
        }
        other_parent = {
            "name": "Dialog Footer",
            "automation_id": "paneDialogFooter",
            "control_type": "pane",
            "control_type_id": 50033,
            "class_name": "FooterPane",
        }
        relocation_old_info = _decorate_uia_structure_info(relocation_old_info, stable_parent, [stable_parent], 2)
        relocation_new_info = _decorate_uia_structure_info(relocation_new_info, stable_parent, [stable_parent], 3)
        relocation_old_signature = _uia_index_signature(relocation_old_info)
        relocation_same_ok = _uia_index_same_identity(relocation_old_signature, _uia_index_signature(relocation_new_info))
        relocation_mismatch_ok = not _uia_index_same_identity(relocation_old_signature, _uia_index_signature(relocation_wrong_info))
        weak_parent_old_info = _decorate_uia_structure_info(
            dict(relocation_old_info, automation_id="", native_window_handle=0),
            stable_parent,
            [stable_parent],
            2,
        )
        weak_parent_wrong_info = _decorate_uia_structure_info(
            dict(relocation_new_info, index=relocation_new_index + 1, automation_id="", native_window_handle=0),
            other_parent,
            [other_parent],
            0,
        )
        relocation_parent_mismatch_ok = not _uia_index_same_identity(_uia_index_signature(weak_parent_old_info), _uia_index_signature(weak_parent_wrong_info))
        relocation_target_elem = object()
        relocation_wrong_elem = object()
        relocation_info_calls: List[Dict[str, Any]] = []
        real_element_info = globals().get("_element_info")
        try:
            def fake_relocation_element_info(elem: Any, index: Optional[int] = None, depth: Optional[int] = None) -> Dict[str, Any]:
                relocation_info_calls.append({"target": elem is relocation_target_elem, "index": index, "depth": depth})
                base = dict(relocation_new_info if elem is relocation_target_elem else relocation_wrong_info)
                base["index"] = index
                base["depth"] = depth
                return base

            globals()["_element_info"] = fake_relocation_element_info
            relocation_cache = {
                relocation_old_index: relocation_wrong_elem,
                relocation_new_index: relocation_target_elem,
            }
            relocation_signatures = {
                relocation_old_index: _uia_index_signature(relocation_wrong_info),
                relocation_new_index: _uia_index_signature(relocation_new_info),
            }
            relocation_structure_score = _uia_index_signature_score(relocation_old_signature, relocation_signatures[relocation_new_index])
            _uia_element_cache[relocation_hwnd] = dict(relocation_cache)
            _uia_element_signatures[relocation_hwnd] = {relocation_old_index: relocation_old_signature}
            relocated_elem, relocated_info, relocation_diag = _uia_relocate_index_from_signatures(
                relocation_hwnd,
                relocation_old_index,
                relocation_old_signature,
                relocation_cache,
                relocation_signatures,
            )
        finally:
            globals()["_element_info"] = real_element_info
            _uia_element_cache.pop(relocation_hwnd, None)
            _uia_element_signatures.pop(relocation_hwnd, None)
        relocation_ok = bool(
            relocation_same_ok
            and relocation_mismatch_ok
            and relocation_parent_mismatch_ok
            and relocated_elem is relocation_target_elem
            and relocated_info
            and relocated_info.get("relocated_from_index") == relocation_old_index
            and (relocation_diag or {}).get("from_index") == relocation_old_index
            and (relocation_diag or {}).get("to_index") == relocation_new_index
            and int((relocation_diag or {}).get("score") or 0) >= 150
            and "parent_automation_id" in ((relocation_structure_score or {}).get("reasons") or [])
            and "sibling_ordinal_near" in ((relocation_structure_score or {}).get("reasons") or [])
            and relocation_info_calls == [{"target": True, "index": relocation_new_index, "depth": 3}]
        )
        report["steps"]["uia_index_relocation"] = {
            "same_identity": relocation_same_ok,
            "mismatch_rejected": relocation_mismatch_ok,
            "parent_mismatch_rejected": relocation_parent_mismatch_ok,
            "relocated_to": (relocation_diag or {}).get("to_index"),
            "score": (relocation_diag or {}).get("score"),
            "reasons": (relocation_diag or {}).get("reasons"),
            "info_calls": relocation_info_calls,
            "ok": relocation_ok,
        }

        action_name_normalization_ok = bool(
            _normalize_uia_action_name("ItemFind") == "item_find"
            and _normalize_uia_action_name("SpreadsheetGetItem") == "spreadsheet_get_item"
            and _normalize_uia_action_name("SetScrollPercent") == "set_scroll_percent"
            and _normalize_uia_action_name("TextScrollIntoView") == "text_scroll_into_view"
            and _normalize_uia_action_name("legacy-default") == "legacy_default"
            and _normalize_uia_action_name("click") == "invoke"
            and _normalize_uia_action_name("press") == "invoke"
            and _normalize_uia_action_name("default") == "invoke"
            and _normalize_uia_action_name("set-text") == "set_value"
            and _normalize_uia_action_name("input-text") == "set_value"
            and _normalize_uia_action_name("clear-text") == "set_value"
        )
        report["steps"]["uia_action_name_normalization"] = {
            "samples": {
                "ItemFind": _normalize_uia_action_name("ItemFind"),
                "SpreadsheetGetItem": _normalize_uia_action_name("SpreadsheetGetItem"),
                "SetScrollPercent": _normalize_uia_action_name("SetScrollPercent"),
                "TextScrollIntoView": _normalize_uia_action_name("TextScrollIntoView"),
                "legacy-default": _normalize_uia_action_name("legacy-default"),
                "click": _normalize_uia_action_name("click"),
                "press": _normalize_uia_action_name("press"),
                "default": _normalize_uia_action_name("default"),
                "set-text": _normalize_uia_action_name("set-text"),
                "input-text": _normalize_uia_action_name("input-text"),
                "clear-text": _normalize_uia_action_name("clear-text"),
            },
            "ok": action_name_normalization_ok,
        }

        action_argument_cases = {
            "SetScrollPercent": (["-1", "75"], (None, -1.0, 75.0)),
            "TextScrollIntoView": (["needle"], ("needle", None, None)),
            "SetText": (["hello"], ("hello", None, None)),
            "input-text": ([""], ("", None, None)),
            "clear-text": ([], ("", None, None)),
            "TextSelectRange": (["2", "5"], (2.0, None, 5.0)),
            "ItemFind": (["name", "Virtual Row", "2"], ("name", "Virtual Row", 2.0)),
            "SpreadsheetGetItem": (["A1"], ("A1", None, None)),
            "CustomNavigate": (["next"], ("next", None, None)),
            "SetCurrentView": (["50009"], (50009.0, None, None)),
            "LegacySetValue": (["hello"], ("hello", None, None)),
            "legacy-set-value": ([""], ("", None, None)),
            "ZoomByUnit": (["small_increment"], ("small_increment", None, None)),
            "Move": (["10", "20"], (10.0, 20.0, None)),
            "Resize": (["320", "200"], (320.0, 200.0, None)),
        }
        action_argument_results: Dict[str, Any] = {}
        for case_name, (case_args, expected) in action_argument_cases.items():
            parsed = _parse_uia_action_arguments(case_name, case_args)
            action_argument_results[case_name] = {
                "args": case_args,
                "parsed": parsed,
                "expected": expected,
                "ok": parsed == expected,
            }
        action_argument_parsing_ok = all(item["ok"] for item in action_argument_results.values())
        report["steps"]["uia_action_argument_parsing"] = {
            "cases": action_argument_results,
            "ok": action_argument_parsing_ok,
        }

        win32_action_name_samples = {
            "ClearText": _normalize_win32_control_action_name("ClearText"),
            "set-value": _normalize_win32_control_action_name("set-value"),
            "replace text": _normalize_win32_control_action_name("replace text"),
            "select-all": _normalize_win32_control_action_name("select-all"),
            "delete-selection": _normalize_win32_control_action_name("delete-selection"),
            "input-text": _normalize_win32_control_action_name("input-text"),
            "appendText": _normalize_win32_control_action_name("appendText"),
        }
        win32_action_name_normalization_ok = bool(
            win32_action_name_samples == {
                "ClearText": "clear",
                "set-value": "set_value",
                "replace text": "replace_all",
                "select-all": "select_all",
                "delete-selection": "delete_selection",
                "input-text": "input_text",
                "appendText": "append_text",
            }
        )
        report["steps"]["win32_action_name_normalization"] = {
            "samples": win32_action_name_samples,
            "ok": win32_action_name_normalization_ok,
        }

        enum_alias_results = {
            "scroll_small_increment": _parse_uia_scroll_amount("small-increment") == UIA_SCROLL_AMOUNT_VALUES["small_increment"],
            "scroll_no_amount": _parse_uia_scroll_amount("no-amount") == UIA_SCROLL_NO_AMOUNT,
            "zoom_small_increment": _parse_uia_zoom_unit("small-increment") == UIA_ZOOM_UNIT_VALUES["small_increment"],
            "zoom_no_amount": _parse_uia_zoom_unit("no-amount") == UIA_ZOOM_UNIT_VALUES["no_amount"],
            "sync_key_down": _parse_uia_sync_input_type("key-down") == UIA_SYNC_INPUT_TYPE_VALUES["key_down"],
            "sync_left_mouse_down": _parse_uia_sync_input_type("left-mouse-down") == UIA_SYNC_INPUT_TYPE_VALUES["left_mouse_down"],
            "navigate_next_sibling": _parse_uia_navigation_direction("next-sibling") == UIA_NAVIGATION_DIRECTION_VALUES["next_sibling"],
            "navigate_first_child": _parse_uia_navigation_direction("first-child") == UIA_NAVIGATION_DIRECTION_VALUES["first_child"],
        }
        enum_alias_parsing_ok = all(enum_alias_results.values())
        report["steps"]["uia_enum_alias_parsing"] = {
            "cases": enum_alias_results,
            "ok": enum_alias_parsing_ok,
        }

        provider_action_hwnd = 987655
        provider_container = object()
        provider_item = object()
        provider_sheet = object()
        provider_cell = object()
        provider_nav = object()
        provider_target = object()
        provider_info_calls: List[Dict[str, Any]] = []
        provider_registered_indexes: List[int] = []
        provider_ad_hoc_snapshot: set[int] = set()
        real_prepare_helper_for_uia = globals().get("_prepare_helper_for_uia")
        real_uia_element_by_index = globals().get("_uia_element_by_index")
        real_get_typed_pattern = globals().get("_get_typed_pattern")
        real_element_info = globals().get("_element_info")
        try:
            class FakeItemContainerPattern:
                def FindItemByProperty(self, _start_after: Any, _property_id: int, _property_value: Any) -> Any:
                    return provider_item

            class FakeSpreadsheetPattern:
                def GetItemByName(self, _name: str) -> Any:
                    return provider_cell

            class FakeCustomNavigationPattern:
                def Navigate(self, _direction: int) -> Any:
                    return provider_target

            def fake_provider_prepare(_hwnd: int) -> Tuple[bool, bool]:
                return False, False

            def fake_provider_element_by_index(
                _hwnd: int,
                idx: int,
                max_depth: Optional[int] = None,
                max_elements: Optional[int] = None,
                view: Optional[str] = None,
            ) -> Tuple[Any, Dict[str, Any]] | Tuple[None, None]:
                if idx == 1:
                    return provider_container, {"index": 1, "patterns": ["ItemContainer"]}
                if idx == 2:
                    return provider_sheet, {"index": 2, "patterns": ["Spreadsheet"]}
                if idx == 3:
                    return provider_nav, {"index": 3, "patterns": ["CustomNavigation"]}
                return None, None

            def fake_provider_get_typed_pattern(elem: Any, pattern_name: str) -> Any:
                if elem is provider_container and pattern_name == "ItemContainer":
                    return FakeItemContainerPattern()
                if elem is provider_sheet and pattern_name == "Spreadsheet":
                    return FakeSpreadsheetPattern()
                if elem is provider_nav and pattern_name == "CustomNavigation":
                    return FakeCustomNavigationPattern()
                return None

            def fake_provider_element_info(elem: Any, index: Optional[int] = None, depth: Optional[int] = None) -> Dict[str, Any]:
                registered = elem in (provider_item, provider_cell, provider_target)
                provider_info_calls.append({
                    "item": elem is provider_item,
                    "cell": elem is provider_cell,
                    "target": elem is provider_target,
                    "index": index,
                    "depth": depth,
                    "registered": registered,
                })
                return {"index": index, "registered": registered}

            globals()["_prepare_helper_for_uia"] = fake_provider_prepare
            globals()["_uia_element_by_index"] = fake_provider_element_by_index
            globals()["_get_typed_pattern"] = fake_provider_get_typed_pattern
            globals()["_element_info"] = fake_provider_element_info
            _uia_element_cache[provider_action_hwnd] = {1: provider_container, 2: provider_sheet, 3: provider_nav}
            _uia_ad_hoc_element_indices[provider_action_hwnd] = set()
            item_find_result = perform_action(provider_action_hwnd, 1, "ItemFind", value="name", horizontal="Virtual Row", vertical=1)
            sheet_result = perform_action(provider_action_hwnd, 2, "SpreadsheetGetItem", value="A1")
            nav_result = perform_action(provider_action_hwnd, 3, "CustomNavigate", value="next")
            provider_registered_indexes = [
                idx
                for idx in (
                    (item_find_result.get("matches") or [{}])[0].get("index"),
                    (sheet_result.get("item") or {}).get("index"),
                    (nav_result.get("target") or {}).get("index"),
                )
                if idx is not None
            ]
            provider_ad_hoc_snapshot = set(_uia_ad_hoc_element_indices.get(provider_action_hwnd, set()))
        finally:
            globals()["_prepare_helper_for_uia"] = real_prepare_helper_for_uia
            globals()["_uia_element_by_index"] = real_uia_element_by_index
            globals()["_get_typed_pattern"] = real_get_typed_pattern
            globals()["_element_info"] = real_element_info
            _uia_element_cache.pop(provider_action_hwnd, None)
            _uia_ad_hoc_element_indices.pop(provider_action_hwnd, None)
        provider_action_registration_ok = bool(
            item_find_result.get("ok")
            and sheet_result.get("ok")
            and nav_result.get("ok")
            and len(provider_registered_indexes) == 3
            and len(set(provider_registered_indexes)) == 3
            and all(index in provider_ad_hoc_snapshot for index in provider_registered_indexes)
            and [call.get("registered") for call in provider_info_calls] == [True, True, True]
        )
        report["steps"]["uia_provider_action_registration"] = {
            "registered_indexes": provider_registered_indexes,
            "info_calls": provider_info_calls,
            "results": {
                "item_find": item_find_result,
                "spreadsheet_get_item": sheet_result,
                "custom_navigate": nav_result,
            },
            "ok": provider_action_registration_ok,
        }

        report["ok"] = bool(exact_late_ok and compact_ok and operable_ok and exact_ok and native_ok and near_ok and uia_failure_summary_ok and uia_repair_find_ok and uia_cell_repair_find_ok and native_repair_find_ok and native_wait_find_repair_ok and window_repair_find_ok and smart_find_ok and smart_click_legacy_ok and smart_click_chain_ok and smart_cell_ok and virtualized_ok and smart_cell_virtualized_ok and smart_cell_virtualized_row_ok and legacy_select_ok and smart_select_chain_ok and smart_text_legacy_ok and smart_text_broad_ok and smart_text_typed_ok and failure_summary_ok and smart_uia_selector_failure_summary_ok and smart_action_relocation_summary_ok and smart_helper_transaction_ok and dialog_helper_transaction_ok and win32_button_action_ok and toolbar_button_action_ok and win32_wait_selection_state_ok and win32_wait_presence_state_ok and win32_wait_repair_ok and elevation_boundary_routing_ok and ad_hoc_cache_ok and relocation_ok and action_name_normalization_ok and action_argument_parsing_ok and enum_alias_parsing_ok and provider_action_registration_ok)
        if not report["ok"]:
            report["error"] = "Selector contract probe did not verify normalized matching, exact ranking, operable priority, native item ranking, near-match diagnostics, UIA find failure summaries/repair find/cell repair find, native selector repair find, native wait-find repair, smart UIA view fallback, smart-click LegacyIAccessible fallback/action chain, smart cell view fallback, ItemContainer virtualized selection/cell fallback, smart-select LegacyIAccessible fallback/action chain, smart-text typed/broad ValuePattern fallback, smart-text LegacyIAccessible fallback, smart action failure/selector-repair/relocation summaries, smart helper/dialog transaction routing, Win32 Button BM_CLICK action routing, ToolbarWindow32 press/check notification routing, Win32 text selection wait states, Win32 present/absent wait states, Win32 wait repair, ad-hoc UIA element cache reuse, stale UIA index relocation, UIA action name normalization, UIA action argument parsing, UIA enum alias parsing, and provider-returned action element registration"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report


def selftest_server_contracts(timeout: float = 10.0) -> Dict[str, Any]:
    """Run no-desktop MCP server contracts from the CLI selftest entry."""
    script = (
        "import asyncio, json, server\n"
        "async def main():\n"
        "    raw = await server.selftest_server_contracts()\n"
        "    print(raw)\n"
        "asyncio.run(main())\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(float(timeout), 1.0),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "app": "server_contract_probe",
            "error": "server contract selftest timed out",
            "timeout": timeout,
        }
    except Exception as e:
        return {"ok": False, "app": "server_contract_probe", "error": str(e)}
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {
            "ok": False,
            "app": "server_contract_probe",
            "returncode": proc.returncode,
            "stdout": _shorten(stdout, 2000),
            "stderr": _shorten(stderr, 2000),
        }
    try:
        parsed = json.loads(stdout)
    except Exception as e:
        return {
            "ok": False,
            "app": "server_contract_probe",
            "error": f"invalid server contract JSON: {e}",
            "stdout": _shorten(stdout, 2000),
            "stderr": _shorten(stderr, 2000) if stderr else "",
        }
    if stderr:
        parsed.setdefault("stderr", _shorten(stderr, 2000))
    return parsed


def selftest_clipboard(timeout: float = 1.0) -> Dict[str, Any]:
    """Exercise clipboard snapshot/restore helpers without touching the real clipboard."""
    report: Dict[str, Any] = {"app": "clipboard_contract_probe", "timeout": timeout, "steps": {}}

    class FakeClipboard:
        def __init__(self) -> None:
            self.formats: Dict[int, bytes] = {}
            self._next_handle = 1000
            self._buffers: Dict[int, Any] = {}
            self._sizes: Dict[int, int] = {}
            self.deleted_objects: List[int] = []
            self.deleted_metafiles: List[int] = []
            self.open_count = 0
            self.empty_count = 0
            self.fail_enum_after_previous: Optional[int] = None
            self.fail_empty = False

        def _new_handle(self, data: bytes) -> int:
            handle = self._next_handle
            self._next_handle += 1
            size = max(len(data), 1)
            buf = ctypes.create_string_buffer(size)
            if data:
                ctypes.memmove(ctypes.addressof(buf), data, len(data))
            self._buffers[handle] = buf
            self._sizes[handle] = size
            return handle

        def OpenClipboard(self, _hwnd: int) -> bool:
            self.open_count += 1
            return True

        def CloseClipboard(self) -> bool:
            return True

        def EmptyClipboard(self) -> bool:
            self.empty_count += 1
            if self.fail_empty:
                return False
            self.formats.clear()
            return True

        def EnumClipboardFormats(self, previous: int) -> int:
            if self.fail_enum_after_previous is not None and int(previous) == int(self.fail_enum_after_previous):
                raise RuntimeError("forced EnumClipboardFormats failure")
            keys = sorted(self.formats)
            if not keys:
                return 0
            if not previous:
                return keys[0]
            try:
                index = keys.index(int(previous)) + 1
            except ValueError:
                return 0
            return keys[index] if index < len(keys) else 0

        def GetClipboardData(self, fmt: int) -> int:
            data = self.formats.get(int(fmt))
            if data is None:
                return 0
            return self._new_handle(data)

        def SetClipboardData(self, fmt: int, handle: int) -> int:
            handle = int(handle)
            buf = self._buffers.get(handle)
            if buf is None:
                return 0
            self.formats[int(fmt)] = ctypes.string_at(ctypes.addressof(buf), self._sizes[handle])
            return handle

        def GlobalAlloc(self, _flags: int, size: int) -> int:
            return self._new_handle(b"\x00" * max(int(size), 1))

        def GlobalLock(self, handle: int) -> int:
            buf = self._buffers.get(int(handle))
            return ctypes.addressof(buf) if buf is not None else 0

        def GlobalUnlock(self, _handle: int) -> bool:
            return True

        def GlobalSize(self, handle: int) -> int:
            return int(self._sizes.get(int(handle), 0))

        def GlobalFree(self, handle: int) -> int:
            handle = int(handle)
            self._buffers.pop(handle, None)
            self._sizes.pop(handle, None)
            return 0

        def CopyImage(self, handle: int, _image_type: int, _cx: int, _cy: int, _flags: int) -> int:
            handle = int(handle)
            buf = self._buffers.get(handle)
            if buf is None:
                return 0
            return self._new_handle(ctypes.string_at(ctypes.addressof(buf), self._sizes[handle]))

        def CopyEnhMetaFileW(self, handle: int, _filename: Optional[str]) -> int:
            handle = int(handle)
            buf = self._buffers.get(handle)
            if buf is None:
                return 0
            return self._new_handle(ctypes.string_at(ctypes.addressof(buf), self._sizes[handle]))

        def DeleteObject(self, handle: int) -> bool:
            self.deleted_objects.append(int(handle))
            self.GlobalFree(handle)
            return True

        def DeleteEnhMetaFile(self, handle: int) -> bool:
            self.deleted_metafiles.append(int(handle))
            self.GlobalFree(handle)
            return True

    fake = FakeClipboard()
    originals = {
        "OpenClipboard": user32.OpenClipboard,
        "CloseClipboard": user32.CloseClipboard,
        "EmptyClipboard": user32.EmptyClipboard,
        "EnumClipboardFormats": user32.EnumClipboardFormats,
        "GetClipboardData": user32.GetClipboardData,
        "SetClipboardData": user32.SetClipboardData,
        "CopyImage": user32.CopyImage,
        "GlobalAlloc": kernel32.GlobalAlloc,
        "GlobalLock": kernel32.GlobalLock,
        "GlobalUnlock": kernel32.GlobalUnlock,
        "GlobalSize": kernel32.GlobalSize,
        "GlobalFree": kernel32.GlobalFree,
        "CopyEnhMetaFileW": gdi32.CopyEnhMetaFileW,
        "DeleteObject": gdi32.DeleteObject,
        "DeleteEnhMetaFile": gdi32.DeleteEnhMetaFile,
    }
    try:
        user32.OpenClipboard = fake.OpenClipboard
        user32.CloseClipboard = fake.CloseClipboard
        user32.EmptyClipboard = fake.EmptyClipboard
        user32.EnumClipboardFormats = fake.EnumClipboardFormats
        user32.GetClipboardData = fake.GetClipboardData
        user32.SetClipboardData = fake.SetClipboardData
        user32.CopyImage = fake.CopyImage
        kernel32.GlobalAlloc = fake.GlobalAlloc
        kernel32.GlobalLock = fake.GlobalLock
        kernel32.GlobalUnlock = fake.GlobalUnlock
        kernel32.GlobalSize = fake.GlobalSize
        kernel32.GlobalFree = fake.GlobalFree
        gdi32.CopyEnhMetaFileW = fake.CopyEnhMetaFileW
        gdi32.DeleteObject = fake.DeleteObject
        gdi32.DeleteEnhMetaFile = fake.DeleteEnhMetaFile

        original = {
            CF_UNICODETEXT: "hello".encode("utf-16-le") + b"\x00\x00",
            CF_BITMAP: b"bitmap-handle-data",
            CF_DIB: b"DIBDATA",
            CF_ENHMETAFILE: b"emf-handle-data",
            49161: b"Version:0.9\r\nStartHTML:00000097\r\n",
        }
        fake.formats = dict(original)
        snapshot = _clipboard_snapshot()
        _set_clipboard_text("typed")
        typed_text = fake.formats.get(CF_UNICODETEXT, b"").decode("utf-16-le", errors="ignore").rstrip("\x00")
        restore = _clipboard_restore_snapshot(snapshot)
        roundtrip_ok = bool(
            snapshot.get("ok")
            and len(snapshot.get("formats") or []) == len(original)
            and typed_text == "typed"
            and restore.get("ok")
            and fake.formats == original
        )
        report["steps"]["multi_format_roundtrip"] = {
            "snapshot_formats": [
                {"format": item.get("format"), "storage": item.get("storage")} for item in snapshot.get("formats") or []
            ],
            "typed_text": typed_text,
            "restore": restore,
            "ok": roundtrip_ok,
        }

        fake.formats = {}
        empty_snapshot = _clipboard_snapshot()
        _set_clipboard_text("typed")
        empty_restore = _clipboard_restore_snapshot(empty_snapshot)
        empty_ok = bool(empty_snapshot.get("ok") and empty_snapshot.get("empty") and empty_restore.get("ok") and fake.formats == {})
        report["steps"]["empty_clipboard_restored_empty"] = {
            "snapshot": {k: v for k, v in empty_snapshot.items() if k != "formats"},
            "restore": empty_restore,
            "ok": empty_ok,
        }

        fake.formats = {
            CF_UNICODETEXT: "text".encode("utf-16-le") + b"\x00\x00",
            CF_METAFILEPICT: b"old-metafile-handle-data",
            CF_PALETTE: b"palette-handle-data",
        }
        skip_snapshot = _clipboard_snapshot()
        skipped_formats = [item.get("format") for item in skip_snapshot.get("skipped_formats") or []]
        skip_ok = bool(
            skip_snapshot.get("ok")
            and CF_METAFILEPICT in skipped_formats
            and CF_PALETTE in skipped_formats
            and CF_METAFILEPICT not in [item.get("format") for item in skip_snapshot.get("formats") or []]
            and CF_PALETTE not in [item.get("format") for item in skip_snapshot.get("formats") or []]
        )
        report["steps"]["unsupported_handle_formats_skipped"] = {
            "formats": [item.get("format") for item in skip_snapshot.get("formats") or []],
            "skipped_formats": skip_snapshot.get("skipped_formats"),
            "ok": skip_ok,
        }

        fake.formats = {
            CF_BITMAP: b"bitmap-to-cleanup",
            CF_UNICODETEXT: "text".encode("utf-16-le") + b"\x00\x00",
        }
        fake.fail_enum_after_previous = CF_BITMAP
        deleted_before = len(fake.deleted_objects)
        failing_snapshot = _clipboard_snapshot()
        fake.fail_enum_after_previous = None
        snapshot_cleanup_ok = bool(
            failing_snapshot.get("ok") is False
            and "forced EnumClipboardFormats failure" in str(failing_snapshot.get("error") or "")
            and len(fake.deleted_objects) > deleted_before
            and any(item.get("format") == CF_BITMAP for item in failing_snapshot.get("disposed_handles") or [])
        )
        report["steps"]["partial_snapshot_handle_cleanup"] = {
            "snapshot": {
                "ok": failing_snapshot.get("ok"),
                "error": failing_snapshot.get("error"),
                "disposed_handles": failing_snapshot.get("disposed_handles"),
            },
            "deleted_objects": fake.deleted_objects[deleted_before:],
            "ok": snapshot_cleanup_ok,
        }

        restore_snapshot = {
            "ok": True,
            "formats": [
                {"format": CF_BITMAP, "storage": "handle", "handle_kind": "bitmap", "handle": fake._new_handle(b"restore-bitmap")},
                {"format": CF_ENHMETAFILE, "storage": "handle", "handle_kind": "enhmetafile", "handle": fake._new_handle(b"restore-emf")},
            ],
            "skipped_formats": [],
        }
        deleted_objects_before = len(fake.deleted_objects)
        deleted_metafiles_before = len(fake.deleted_metafiles)
        fake.fail_empty = True
        restore_failure = _clipboard_restore_snapshot(restore_snapshot)
        fake.fail_empty = False
        restore_cleanup_ok = bool(
            restore_failure.get("ok") is False
            and restore_failure.get("error") == "EmptyClipboard failed"
            and len(fake.deleted_objects) > deleted_objects_before
            and len(fake.deleted_metafiles) > deleted_metafiles_before
            and len(restore_failure.get("disposed_handles") or []) == 2
        )
        report["steps"]["restore_failure_handle_cleanup"] = {
            "restore": restore_failure,
            "deleted_objects": fake.deleted_objects[deleted_objects_before:],
            "deleted_metafiles": fake.deleted_metafiles[deleted_metafiles_before:],
            "ok": restore_cleanup_ok,
        }

        input_release = _selftest_input_sequence_release_contract()
        report["steps"]["input_sequence_release_on_failure"] = input_release
        type_restore_warning = _selftest_type_text_restore_warning_contract()
        report["steps"]["type_text_restore_warning"] = type_restore_warning

        report["ok"] = bool(
            roundtrip_ok
            and empty_ok
            and skip_ok
            and snapshot_cleanup_ok
            and restore_cleanup_ok
            and input_release.get("ok")
            and type_restore_warning.get("ok")
        )
        if not report["ok"]:
            report["error"] = "Clipboard contract probe did not verify multi-format restore, empty clipboard restore, handle-format skip behavior, copied-handle cleanup paths, modifier release on failed input sequences, and type_text restore-warning reporting"
        return report
    except Exception as e:
        report["ok"] = False
        report["error"] = str(e)
        return report
    finally:
        user32.OpenClipboard = originals["OpenClipboard"]
        user32.CloseClipboard = originals["CloseClipboard"]
        user32.EmptyClipboard = originals["EmptyClipboard"]
        user32.EnumClipboardFormats = originals["EnumClipboardFormats"]
        user32.GetClipboardData = originals["GetClipboardData"]
        user32.SetClipboardData = originals["SetClipboardData"]
        user32.CopyImage = originals["CopyImage"]
        kernel32.GlobalAlloc = originals["GlobalAlloc"]
        kernel32.GlobalLock = originals["GlobalLock"]
        kernel32.GlobalUnlock = originals["GlobalUnlock"]
        kernel32.GlobalSize = originals["GlobalSize"]
        kernel32.GlobalFree = originals["GlobalFree"]
        gdi32.CopyEnhMetaFileW = originals["CopyEnhMetaFileW"]
        gdi32.DeleteObject = originals["DeleteObject"]
        gdi32.DeleteEnhMetaFile = originals["DeleteEnhMetaFile"]


def _selftest_input_sequence_release_contract() -> Dict[str, Any]:
    real_send_key_down = globals().get("_send_key_down")
    real_send_key_up = globals().get("_send_key_up")
    events: List[Dict[str, Any]] = []
    ctrl_sc = _keysym_to_scancode("ctrl")
    v_sc = _keysym_to_scancode("v")

    def fake_down(scancode: int) -> None:
        events.append({"action": "down", "scancode": scancode})
        if scancode == v_sc:
            raise RuntimeError("forced key down failure")

    def fake_up(scancode: int) -> None:
        events.append({"action": "up", "scancode": scancode})

    try:
        globals()["_send_key_down"] = fake_down
        globals()["_send_key_up"] = fake_up
        error_text = ""
        try:
            _press_scancode_sequence([ctrl_sc, v_sc])
        except Exception as e:
            error_text = str(e)
        ok = bool(
            "forced key down failure" in error_text
            and events == [
                {"action": "down", "scancode": ctrl_sc},
                {"action": "down", "scancode": v_sc},
                {"action": "up", "scancode": ctrl_sc},
            ]
        )
        return {"ok": ok, "events": events, "error": error_text}
    except Exception as e:
        return {"ok": False, "error": str(e), "events": events}
    finally:
        globals()["_send_key_down"] = real_send_key_down
        globals()["_send_key_up"] = real_send_key_up


def _selftest_type_text_restore_warning_contract() -> Dict[str, Any]:
    real_resolve_target = globals().get("_resolve_target")
    real_prepare_helper = globals().get("_prepare_helper_for_hwnd")
    real_helper_post = globals().get("_helper_post")
    real_activate_window = globals().get("activate_window")
    real_clipboard_snapshot = globals().get("_clipboard_snapshot")
    real_set_clipboard_text = globals().get("_set_clipboard_text")
    real_send_ctrl_v = globals().get("_send_ctrl_v")
    real_restore_snapshot = globals().get("_clipboard_restore_snapshot")
    calls: List[Dict[str, Any]] = []
    try:
        globals()["_resolve_target"] = lambda hwnd=None: int(hwnd or 1234)
        globals()["_prepare_helper_for_hwnd"] = lambda hwnd: (True, False)

        def fake_helper_post(path: str, payload: Dict[str, Any], elevated: bool = False, **kwargs: Any) -> Dict[str, Any]:
            calls.append({"path": path, "payload": payload, "elevated": elevated})
            return {
                "ok": True,
                "clipboard_restore_ok": False,
                "clipboard_saved_formats": 3,
                "clipboard_restored_formats": 2,
                "clipboard_restore_error": "restore failed",
            }

        globals()["_helper_post"] = fake_helper_post
        helper_warning = type_text(1234, "abc")
        helper_ok = bool(
            helper_warning.startswith("Warning: pasted 3 characters")
            and "restore failed" in helper_warning
            and calls
            and calls[0].get("path") == "/type_text"
        )

        globals()["_prepare_helper_for_hwnd"] = lambda hwnd: (False, False)
        globals()["activate_window"] = lambda hwnd: calls.append({"activate": hwnd})
        globals()["_clipboard_snapshot"] = lambda: {"ok": True, "formats": [], "skipped_formats": [], "empty": True}
        globals()["_set_clipboard_text"] = lambda text: calls.append({"set_clipboard_text": text})
        globals()["_send_ctrl_v"] = lambda: calls.append({"send_ctrl_v": True})
        globals()["_clipboard_restore_snapshot"] = lambda snapshot: {
            "ok": False,
            "restored_formats": 0,
            "error": "open_clipboard_failed",
        }
        fallback_warning = type_text(1234, "xyz")
        fallback_ok = bool(
            fallback_warning.startswith("Warning: pasted 3 characters")
            and "open_clipboard_failed" in fallback_warning
            and any(item.get("send_ctrl_v") for item in calls)
        )
        globals()["_send_ctrl_v"] = lambda: (_ for _ in ()).throw(RuntimeError("send failed"))
        fallback_error = type_text(1234, "err")
        fallback_error_ok = bool(
            fallback_error.startswith("Error: send failed; clipboard restore may be incomplete")
            and "open_clipboard_failed" in fallback_error
        )
        globals()["_send_ctrl_v"] = lambda: (_ for _ in ()).throw(RuntimeError("foreground send failed"))
        foreground_error = type_text_foreground("fg")
        foreground_error_ok = bool(
            foreground_error.startswith("Error: foreground send failed; clipboard restore may be incomplete")
            and "open_clipboard_failed" in foreground_error
        )
        return {
            "ok": helper_ok and fallback_ok and fallback_error_ok and foreground_error_ok,
            "helper_warning": helper_warning,
            "fallback_warning": fallback_warning,
            "fallback_error": fallback_error,
            "foreground_error": foreground_error,
            "calls": calls,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "calls": calls}
    finally:
        globals()["_resolve_target"] = real_resolve_target
        globals()["_prepare_helper_for_hwnd"] = real_prepare_helper
        globals()["_helper_post"] = real_helper_post
        globals()["activate_window"] = real_activate_window
        globals()["_clipboard_snapshot"] = real_clipboard_snapshot
        globals()["_set_clipboard_text"] = real_set_clipboard_text
        globals()["_send_ctrl_v"] = real_send_ctrl_v
        globals()["_clipboard_restore_snapshot"] = real_restore_snapshot


def selftest(target: str = "notepad", timeout: float = 15.0) -> Dict[str, Any]:
    """Run real-app regression tests."""
    target = target.lower()
    if target in ("batch", "batch_contract", "batch-contract"):
        result = {"batch": selftest_batch(timeout=min(timeout, 1.0))}
        result["ok"] = bool(result["batch"].get("ok"))
        return result
    if target in ("selector", "selectors", "selector_ranking", "selector-ranking"):
        result = {"selector": selftest_selector(timeout=min(timeout, 1.0))}
        result["ok"] = bool(result["selector"].get("ok"))
        return result
    if target in ("server_contracts", "server-contracts", "server_contract", "server-contract", "mcp_contracts", "mcp-contracts"):
        result = {"server_contracts": selftest_server_contracts(timeout=max(min(timeout, 45.0), 30.0))}
        result["ok"] = bool(result["server_contracts"].get("ok"))
        return result
    if target in ("clipboard", "clip", "clipboard_contract", "clipboard-contract"):
        result = {"clipboard": selftest_clipboard(timeout=min(timeout, 1.0))}
        result["ok"] = bool(result["clipboard"].get("ok"))
        return result
    if target == "notepad":
        result = {"notepad": selftest_notepad(timeout=timeout)}
        result["ok"] = bool(result["notepad"].get("ok"))
        return result
    if target == "win32":
        result = {"win32": selftest_win32(timeout=timeout)}
        result["ok"] = bool(result["win32"].get("ok"))
        return result
    if target == "msaa":
        result = {"msaa": selftest_msaa(timeout=timeout)}
        result["ok"] = bool(result["msaa"].get("ok"))
        return result
    if target == "menu":
        result = {"menu": selftest_menu(timeout=timeout)}
        result["ok"] = bool(result["menu"].get("ok"))
        return result
    if target == "controls":
        result = {"controls": selftest_controls(timeout=timeout)}
        result["ok"] = bool(result["controls"].get("ok"))
        return result
    if target in ("common", "common_controls"):
        result = {"common_controls": selftest_common_controls(timeout=timeout)}
        result["ok"] = bool(result["common_controls"].get("ok"))
        return result
    if target in ("header", "headers", "header_controls"):
        result = {"header_controls": selftest_header_controls(timeout=timeout)}
        result["ok"] = bool(result["header_controls"].get("ok"))
        return result
    if target in ("bars", "tab_toolbar"):
        result = {"bars": selftest_bars(timeout=timeout)}
        result["ok"] = bool(result["bars"].get("ok"))
        return result
    if target in ("numeric", "numeric_controls", "status_trackbar"):
        result = {"numeric_controls": selftest_numeric_controls(timeout=timeout)}
        result["ok"] = bool(result["numeric_controls"].get("ok"))
        return result
    if target in ("date_ip", "datetime", "date"):
        result = {"date_ip_controls": selftest_date_ip_controls(timeout=timeout)}
        result["ok"] = bool(result["date_ip_controls"].get("ok"))
        return result
    if target in ("richedit", "rich_edit", "text_controls"):
        result = {"richedit_controls": selftest_richedit_controls(timeout=timeout)}
        result["ok"] = bool(result["richedit_controls"].get("ok"))
        return result
    if target in ("light", "light_controls", "static_hotkey_link"):
        result = {"light_controls": selftest_light_controls(timeout=timeout)}
        result["ok"] = bool(result["light_controls"].get("ok"))
        return result
    if target in ("uia", "uia_patterns", "uia_range_scroll"):
        result = {"uia_patterns": selftest_uia_patterns(timeout=timeout)}
        result["ok"] = bool(result["uia_patterns"].get("ok"))
        return result
    if target in ("text", "text_pattern", "uia_text"):
        result = {"text_pattern": selftest_text_pattern(timeout=timeout)}
        result["ok"] = bool(result["text_pattern"].get("ok"))
        return result
    if target in ("winevent", "win_event", "events"):
        result = {"winevent": selftest_winevent(timeout=timeout)}
        result["ok"] = bool(result["winevent"].get("ok"))
        return result
    if target in ("view", "uia_view", "uia_views", "view_modes"):
        result = {"uia_view_modes": selftest_uia_view_modes(timeout=timeout)}
        result["ok"] = bool(result["uia_view_modes"].get("ok"))
        return result
    if target in ("window", "windows", "window_action", "window_actions", "window_management"):
        result = {"window_actions": selftest_window_management(timeout=timeout)}
        result["ok"] = bool(result["window_actions"].get("ok"))
        return result
    if target in ("focus", "focus_hwnd", "foreground_focus", "input_focus"):
        result = {"focus_hwnd": selftest_focus_hwnd(timeout=timeout)}
        result["ok"] = bool(result["focus_hwnd"].get("ok"))
        return result
    if target in ("focused_input", "focused-input", "focus_input", "input"):
        result = {"focused_input": selftest_focused_input(timeout=timeout)}
        result["ok"] = bool(result["focused_input"].get("ok"))
        return result
    if target in ("file_dialog", "file-dialog", "dialog", "open_save_dialog"):
        result = {"file_dialog": selftest_file_dialog(timeout=timeout)}
        result["ok"] = bool(result["file_dialog"].get("ok"))
        return result
    if target in ("ocr", "windows_ocr", "vision_ocr"):
        result = {"ocr": selftest_ocr(timeout=timeout)}
        result["ok"] = bool(result["ocr"].get("ok"))
        return result
    if target in ("image", "image_match", "vision_image", "template"):
        result = {"image_match": selftest_image_match(timeout=timeout)}
        result["ok"] = bool(result["image_match"].get("ok"))
        return result
    if target == "all":
        result = {
            "batch": selftest_batch(timeout=min(timeout, 1.0)),
            "selector": selftest_selector(timeout=min(timeout, 1.0)),
            "server_contracts": selftest_server_contracts(timeout=max(min(timeout, 20.0), 5.0)),
            "clipboard": selftest_clipboard(timeout=min(timeout, 1.0)),
            "notepad": selftest_notepad(timeout=timeout),
            "uia_patterns": selftest_uia_patterns(timeout=timeout),
            "text_pattern": selftest_text_pattern(timeout=timeout),
            "winevent": selftest_winevent(timeout=timeout),
            "uia_view_modes": selftest_uia_view_modes(timeout=timeout),
            "window_actions": selftest_window_management(timeout=timeout),
            "focus_hwnd": selftest_focus_hwnd(timeout=timeout),
            "focused_input": selftest_focused_input(timeout=timeout),
            "ocr": selftest_ocr(timeout=timeout),
            "image_match": selftest_image_match(timeout=timeout),
            "win32": selftest_win32(timeout=timeout),
            "msaa": selftest_msaa(timeout=timeout),
            "menu": selftest_menu(timeout=timeout),
            "controls": selftest_controls(timeout=timeout),
            "common_controls": selftest_common_controls(timeout=timeout),
            "header_controls": selftest_header_controls(timeout=timeout),
            "bars": selftest_bars(timeout=timeout),
            "numeric_controls": selftest_numeric_controls(timeout=timeout),
            "date_ip_controls": selftest_date_ip_controls(timeout=timeout),
            "richedit_controls": selftest_richedit_controls(timeout=timeout),
            "light_controls": selftest_light_controls(timeout=timeout),
        }
        result["ok"] = bool(
            result["batch"].get("ok")
            and result["selector"].get("ok")
            and result["server_contracts"].get("ok")
            and result["clipboard"].get("ok")
            and result["notepad"].get("ok")
            and result["uia_patterns"].get("ok")
            and result["text_pattern"].get("ok")
            and result["winevent"].get("ok")
            and result["uia_view_modes"].get("ok")
            and result["window_actions"].get("ok")
            and result["focus_hwnd"].get("ok")
            and result["focused_input"].get("ok")
            and result["ocr"].get("ok")
            and result["image_match"].get("ok")
            and result["win32"].get("ok")
            and result["msaa"].get("ok")
            and result["menu"].get("ok")
            and result["controls"].get("ok")
            and result["common_controls"].get("ok")
            and result["header_controls"].get("ok")
            and result["bars"].get("ok")
            and result["numeric_controls"].get("ok")
            and result["date_ip_controls"].get("ok")
            and result["richedit_controls"].get("ok")
            and result["light_controls"].get("ok")
        )
        return result


run_selftest = selftest