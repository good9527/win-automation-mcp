"""
CLI command execution router and help system.
Supports 100% of all 111 command branches and 242 aliases.
"""

from __future__ import annotations

import os
import sys
import time
import json
import base64
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.win32_structures import *
from win_automation.core.types import *
from win_automation.core.utils import parse_rgb_color, rgb_distance, is_valid_hwnd
from win_automation.core.dpi import screen_info
from win_automation.win32 import *
from win_automation.uia import *
from win_automation.input import *
from win_automation.vision import *
from win_automation.ocr import *
from win_automation.safety import check_safety
from win_automation.state import *
from win_automation.diagnostics import doctor, selftest
from win_automation.batch import execute_batch, execute_batch_file
from win_automation.helper.client import (
    _helper_route_for_hwnd,
    _helper_post,
    _helper_get,
    _helper_available,
    _helper_current,
    _helper_health,
    _helper_shutdown,
    _elevated_helper_required_result,
    _prepare_helper_for_uia,
    ensure_helper,
    helper_status,
)
from win_automation.cli.parsers import *

# CLI command aliases
observe = observe_window
desktop_ocr = run_desktop_ocr

def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)

def _get_screenshot_size(screenshot_id: Optional[int] = None) -> Dict[str, int]:
    meta = load_screenshot_meta(screenshot_id)
    if meta and "width" in meta and "height" in meta:
        return {"width": meta["width"], "height": meta["height"]}
    return {"width": 1280, "height": 834}

def _load_screenshot_meta(screenshot_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    return load_screenshot_meta(screenshot_id)

# CLI entry point (items 9, 10, 16 — get_window cmd, JSON, error msgs)
# ---------------------------------------------------------------------------

def main() -> None:
    # Fix encoding for Windows console
    if sys.platform == "win32":
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        if hasattr(sys.stderr, "reconfigure"):
            try:
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


    # Auto-start helper server for input commands (click/type/key/scroll/drag)
    input_commands = {"click", "type", "key", "scroll", "drag", "activate", "win32-control-find", "win32_control_find", "win32-find-control", "win32_find_control", "native-control-find", "native_control_find", "win32-control-wait-find", "win32_control_wait_find", "win32-wait-control-find", "win32_wait_control_find", "native-control-wait-find", "native_control_wait_find", "smart-text", "smart_text", "smart-text-input", "smart_text_input", "smart-wait-text", "smart_wait_text", "smart-wait-text-input", "smart_wait_text_input", "smart-click", "smart_click", "smart-control-action", "smart_control_action", "smart-wait-click", "smart_wait_click", "smart-wait-control-action", "smart_wait_control_action", "smart-select", "smart_select", "smart-select-item", "smart_select_item", "smart-wait-select", "smart_wait_select", "smart-wait-select-item", "smart_wait_select_item", "smart-cell", "smart_cell", "smart-grid-cell", "smart_grid_cell", "smart-listview-cell", "smart_listview_cell", "smart-wait-cell", "smart_wait_cell", "smart-wait-grid-cell", "smart_wait_grid_cell", "smart-wait-listview-cell", "smart_wait_listview_cell", "smart-dialog", "smart_dialog", "smart-dialog-action", "smart_dialog_action", "smart-wait-dialog-action", "smart_wait_dialog_action", "dialog-command", "dialog_command", "dialog-command-action", "dialog_command_action", "native-dialog-command", "native_dialog_command", "messagebox-command", "messagebox_command", "message-box-command", "message_box_command", "dialog-button", "dialog_button", "dialog-button-action", "dialog_button_action", "native-dialog-button", "native_dialog_button", "messagebox-button", "messagebox_button", "message-box-button", "message_box_button", "visual-row-click", "visual_row_click", "visual-row-scroll-click", "visual_row_scroll_click", "visual-row-wait-click", "visual_row_wait_click"}
    if len(sys.argv) > 1 and sys.argv[1] in input_commands:
        ensure_helper()

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Usage: python tools.py <command> [args...]")
        print()
        print("Commands:")
        print("  list_windows                                List all visible windows")
        print("  list_apps                                   List apps grouped by process")
        print("  launch <app-or-path> [timeout]              Launch an app and set new window as target")
        print("  get_window <hwnd>                           Get/validate a window handle (rehydrate)")
        print("  foreground                                  Get current foreground window")
        print("  control-boundary [hwnd]                     Diagnose integrity/UIPI/UIAccess/desktop control boundaries")
        print("  helper-status [--restart] [--elevated --start] Inspect/reload normal or elevated helper")
        print("  gui-thread-info [hwnd]                      Inspect active/focus/capture/menu/caret HWNDs for a GUI thread")
        print("  focus-hwnd <hwnd>                           Force foreground/active/focus for a top-level or child HWND")
        print("  focused-input [hwnd] <text>                 Input text into the true focused HWND; supports --mode")
        print("  smart-text [hwnd] <text>                    Set text via UIA, Win32 child controls, then focused-input fallback")
        print("  smart-wait-text [hwnd] <text>               Poll smart-text until a matching input appears and accepts text")
        print("  smart-click [hwnd] [--name TEXT]            Trigger controls via UIA actions, Win32 native actions, optional coordinate fallback")
        print("  smart-wait-click [hwnd] [--name TEXT]       Poll smart-click until the control appears and action succeeds")
        print("  smart-select [hwnd] <item>                  Select list/combo/tree/tab/toolbar items via UIA or Win32 actions")
        print("  smart-wait-select [hwnd] <item>             Poll smart-select until the item appears and selection succeeds")
        print("  smart-cell [hwnd] --row N --column N        Read/select/set table or ListView cells via UIA or Win32 actions")
        print("  smart-wait-cell [hwnd] --row N --column N   Poll smart-cell until the cell appears and action succeeds")
        print("  smart-dialog [hwnd] <click|text|select|cell> Wait related popup/dialog, then run a smart action inside it")
        print("  dialog-command [hwnd] <ok|cancel|yes|no>    Wait related standard dialog and send WM_COMMAND")
        print("  dialog-button [hwnd] [--name TEXT]          Wait related dialog and trigger native button via WM_COMMAND/BM_CLICK")
        print("  related-windows <hwnd>                      List same-process/owned/root-owner windows")
        print("  wait-window [--title TEXT] [--process NAME] Wait for a visible top-level window")
        print("  window-selector-repair-find [--suggestion JSON] [--original JSON] Repair a stale wait-window selector")
        print("  window-action <hwnd> <action> [--x N --y N --width N --height N] Move/resize/z-order/placement/minimize/maximize/restore/close HWND")
        print("  wait-event [event] [--hwnd H] [--pid P]     Wait for WinEvent focus/show/dialog/menu/value changes")
        print("  screen                                      Get virtual desktop and monitor metrics")
        print("  mouse                                       Get current cursor position")
        print("  mouse-context [x y] [hwnd] [sid]            Inspect HWND/UIA/MSAA context under cursor or point")
        print("  child-windows <hwnd> [--include-text]       Enumerate native Win32 child controls")
        print("  window-from-point <x> <y> [hwnd] [sid]      Find HWND under screen or screenshot point")
        print("  element-from-point <x> <y> [hwnd] [sid]     Find UIA element under screen or screenshot point")
        print("  msaa-window <hwnd> [max_children]           Inspect MSAA/IAccessible client object")
        print("  msaa-from-point <x> <y> [hwnd] [sid]        Find MSAA object under screen or screenshot point")
        print("  msaa-action <hwnd> <action> [path_json]     Run MSAA default/focus/select/set_value")
        print("  menu-tree <hwnd> [--system]                 Inspect classic Win32 HMENU menu commands")
        print("  menu-action <hwnd> <path_json|id>           Invoke HMENU item via WM_COMMAND")
        print("  win32-text <hwnd>                           Read native control text with WM_GETTEXT")
        print("  win32-set-text <hwnd> <text>                Set native control text with WM_SETTEXT")
        print("  win32-click <hwnd>                          Invoke native button/control with BM_CLICK")
        print("  file-dialog info [hwnd]                     Inspect foreground/supplied Open/Save dialog controls")
        print("  file-dialog <set|open|save|cancel> [path]   Set filename, confirm, or cancel a file dialog")
        print("  win32-control-find <hwnd> [selector flags]  Find native Win32 child controls by text/class/kind/state")
        print("  win32-control-wait-find <hwnd> [flags]      Wait native selector; add --repair to retry selector_suggestions")
        print("  win32-control-wait <hwnd> [state] [expected] Wait native state/presence; add --repair for exact-text relaxed retry")
        print("  win32-control-info <hwnd>                   Inspect native Combo/ComboEx/List/Button/Static/Link/HotKey/ListView/Tree/RichEdit state")
        print("  win32-control-action <hwnd> <action> [...]  Select/check/expand/edit native common and lightweight controls")
        print("  doctor [hwnd]                               Run self-check across core control layers")
        print("  selftest [batch|selector|server-contracts|clipboard|notepad|uia|text|winevent|view|window|focus|focused_input|file_dialog|ocr|image|win32|msaa|menu|controls|common|header|bars|numeric|date_ip|richedit|light|all] [timeout] Run regression tests")
        print("  observe [hwnd] [--no-a11y] [--ocr] [--no-ocr-on-a11y-error] [--view raw|control|content] Capture window info, screenshot, and UIA/OCR summary")
        print("  screenshot <hwnd> [output.jpg]              Capture window screenshot (returns JSON with id)")
        print("      Window capture supports --capture-mode auto|visible|window|printwindow|bitblt")
        print("  screenshot_b64 <hwnd>                       Capture screenshot as base64 PNG")
        print("  pixel <hwnd> <x> <y> [screenshot_id]        Read RGB pixel from screenshot coordinates")
        print("  pixel-wait <hwnd> <x> <y> <#rrggbb>         Wait until a window pixel matches or differs from a color")
        print("  visual-stable-wait <hwnd>                   Wait until a window screenshot stops changing")
        print("  uia-stable-wait <hwnd>                      Wait until a window UIA tree signature stops changing")
        print("  desktop-screenshot [output.jpg] [max_width] Capture full virtual desktop screenshot")
        print("  desktop-pixel <x> <y> [screenshot_id]       Read RGB pixel from a desktop screenshot")
        print("  desktop-pixel-wait <x> <y> <#rrggbb>        Wait until a desktop pixel matches or differs from a color")
        print("  desktop-visual-stable-wait                  Wait until the full desktop screenshot stops changing")
        print("  desktop-uia-stable-wait                     Wait until the desktop-root UIA tree signature stops changing")
        print("  desktop-point <x> <y> [screenshot_id]       Map desktop screenshot point to screen coordinates")
        print("  desktop-click <x> <y> [button] [clicks] [sid] Click absolute desktop/screenshot point")
        print("  desktop-scroll <x> <y> <dy> [sid]           Scroll at absolute desktop/screenshot point")
        print("  desktop-drag <x1> <y1> <x2> <y2> [sid]      Drag across desktop/screenshot points")
        print("  desktop-locate-image <template> [confidence] Locate template in full desktop screenshot")
        print("  desktop-image-wait <template> [confidence]  Wait until template appears on full desktop")
        print("  desktop-image-click <template> [confidence] Click desktop template match center")
        print("  locate-image <hwnd> <template> [confidence] Locate template image in window screenshot")
        print("  image-wait <hwnd> <template> [confidence]   Wait until template image appears")
        print("  image-click <hwnd> <template> [confidence]  Click the center of a template image match")
        print("  desktop-ocr [lang] [--engine auto|windows]  Run OCR on full desktop screenshot")
        print("  desktop-ocr-find <text> [lang]              Find OCR text on full desktop")
        print("  desktop-ocr-wait <text> [lang]              Wait until desktop OCR text appears")
        print("  desktop-ocr-click <text> [lang]             Click desktop OCR text match center")
        print("  ocr <hwnd> [lang] [--engine auto|windows]   Run OCR on a window screenshot")
        print("  ocr-find <hwnd> <text> [lang]               Find OCR text and return click-ready coordinates")
        print("  ocr-wait <hwnd> <text> [lang]               Wait until OCR-visible text appears")
        print("  ocr-click <hwnd> <text> [lang]              Click the center of OCR-matched text")
        print("  visual-row <hwnd> --row N                   Locate a visible numbered list row from OCR row anchors")
        print("  visual-row-click <hwnd> --row N             Click a visible numbered list row from OCR row anchors")
        print("  visual-row-scroll <hwnd> --row N            Scroll a numbered list/table until row N is visible")
        print("  visual-row-scroll-click <hwnd> --row N      Scroll to and click row N in a numbered list/table")
        print("  accessibility <hwnd> [--view raw|control|content] Get accessibility tree + focused element")
        print("  find <hwnd> [--name TEXT] [--type TYPE] [--automation-id ID] [--pattern PATTERN] [--view raw|control|content]")
        print("  item-container-find <hwnd> <index> <property> <value> [limit] [--view raw|control|content] [--include-children --max-children N] Find items through UIA ItemContainer")
        print("  wait <hwnd> [selector flags] [--timeout SEC] [--repair] Wait until a UIA element appears")
        print("  element <hwnd> <index> [--view raw|control|content] Get metadata for one UIA element index")
        print("  focus <hwnd> <index> [--view raw|control|content] Set keyboard focus to a UIA element")
        print("  click-index <hwnd> <index> [button] [clicks] [--view raw|control|content] Click a UIA element center")
        print("  set-value <hwnd> <index> <text> [--view raw|control|content] Set UIA ValuePattern text")
        print("  action <hwnd> <index> <Invoke|Toggle|Expand|Collapse|Select|AddToSelection|RemoveFromSelection|ScrollItem|SetRange|Scroll|SetScrollPercent|TextFind|TextSelect|TextScrollIntoView|TextSelectRange|SetCurrentView|Realize|ItemFind|SpreadsheetGetItem|CustomNavigate|SyncStart|SyncCancel> [value|horizontal] [vertical] [--view raw|control|content]")
        print("  desktop-accessibility [--view raw|control|content] Get UIA tree rooted at the Windows desktop")
        print("  desktop-find [selector flags] [--view raw|control|content] Find UIA elements from desktop root")
        print("  desktop-wait [selector flags] [--timeout SEC] [--repair] Wait for desktop-root UIA element")
        print("  desktop-element <index> [--view raw|control|content] Get desktop-root UIA element metadata")
        print("  desktop-focus <index> [--view raw|control|content] Set focus to desktop-root UIA element")
        print("  desktop-click-index <index> [button] [clicks] [--view raw|control|content] Click desktop-root UIA element center")
        print("  desktop-action <index> <Invoke|Toggle|Expand|Collapse|Select|ScrollItem|...> [args] Run UIA action on desktop-root element")
        print("  click <hwnd> <x> <y> [button] [clicks] [screenshot_id] Click at coordinates (clicks=2 for double-click)")
        print("  type <hwnd> <text>                          Type/paste text via clipboard")
        print("  key <hwnd> <keys>                           Press key combo (e.g. ctrl+a)")
        print("  scroll <hwnd> <x> <y> <dy> [screenshot_id] Scroll at coordinates")
        print("  drag <hwnd> <x1> <y1> <x2> <y2> [screenshot_id] Drag between coordinates")
        print("  activate <hwnd>                             Bring window to foreground")
        print("  batch '<json_commands>' [--confirmed]      Execute multiple commands; confirm sensitive actions explicitly")
        print("  batch_repair_plan via batch                 Convert diagnostic next_repair_* data into executable batch snippets")
        print("  batch-file <commands.json>                  Execute batch commands from a JSON file")
        print("  state get [key]                             Get state (all or specific key)")
        print("  state set <key> <value>                     Set a state key/value pair")
        print("  state target <hwnd>                         Set current target window")
        print("  confirm <action>                            Check if action needs user confirmation")
        print()
        print("Note: click/type/key/scroll auto-use 'target' from state if no hwnd given.")
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    cmd = sys.argv[1]

    # ------------------------------------------------------------------
    if cmd == "list_windows":
        windows = enum_windows()
        for w in windows:
            print(json.dumps(w, ensure_ascii=False))

    # ------------------------------------------------------------------
    elif cmd == "get_window":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        print(get_window(hwnd))

    # ------------------------------------------------------------------
    elif cmd == "foreground":
        print(json.dumps(foreground_window(), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("control-boundary", "control_boundary", "boundary", "integrity"):
        hwnd = None
        if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
            hwnd = int(sys.argv[2], 0)
        print(json.dumps(control_boundary(hwnd), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("helper-status", "helper_status"):
        args = sys.argv[2:]
        restart = "--restart" in args
        elevated = "--elevated" in args or "--admin" in args
        start = "--start" in args
        print(json.dumps(helper_status(restart=restart, elevated=elevated, start=start), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("gui-thread-info", "gui_thread_info", "gui"):
        hwnd = None
        thread_id = None
        args = sys.argv[2:]
        if args and not args[0].startswith("--"):
            hwnd = int(args[0], 0)
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--hwnd" and i + 1 < len(args):
                hwnd = int(args[i + 1], 0)
                i += 2
            elif args[i] in ("--thread", "--thread-id") and i + 1 < len(args):
                thread_id = int(args[i + 1], 0)
                i += 2
            else:
                i += 1
        print(json.dumps(gui_thread_info(hwnd=hwnd, thread_id=thread_id), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("focus-hwnd", "focus_hwnd", "hwnd-focus", "set-focus-hwnd"):
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2], 0)
        timeout = 1.0
        restore = True
        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--no-restore":
                restore = False
                i += 1
            else:
                i += 1
        print(json.dumps(focus_hwnd(hwnd, timeout=timeout, restore=restore), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("focused-input", "focused_input", "focus-input", "focus_input"):
        args = sys.argv[2:]
        hwnd = None
        text = None
        mode = "auto"
        timeout = 1.0
        timeout_ms = 500
        restore = True
        verify = True
        diagnostic = False
        allow_focus_fallback = False
        if args and not args[0].startswith("--"):
            try:
                candidate = int(args[0], 0)
                if len(args) >= 2:
                    hwnd = candidate
                    text = args[1]
                    args = args[2:]
            except ValueError:
                text = args[0]
                args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--hwnd" and i + 1 < len(args):
                hwnd = int(args[i + 1], 0)
                i += 2
            elif args[i] == "--text" and i + 1 < len(args):
                text = args[i + 1]
                i += 2
            elif args[i] == "--mode" and i + 1 < len(args):
                mode = args[i + 1]
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--timeout-ms" and i + 1 < len(args):
                timeout_ms = int(args[i + 1])
                i += 2
            elif args[i] == "--no-restore":
                restore = False
                i += 1
            elif args[i] == "--no-verify":
                verify = False
                i += 1
            elif args[i] in ("--diagnostic", "--verbose"):
                diagnostic = True
                i += 1
            elif args[i] == "--allow-focus-fallback":
                allow_focus_fallback = True
                i += 1
            elif text is None:
                text = args[i]
                i += 1
            else:
                i += 1
        if text is None:
            print("Error: text required")
            sys.exit(1)
        print(json.dumps(focused_input(hwnd, text, mode=mode, timeout=timeout, restore=restore, timeout_ms=timeout_ms, verify=verify, diagnostic=diagnostic, allow_focus_fallback=allow_focus_fallback), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("smart-text", "smart_text", "smart-text-input", "smart_text_input"):
        options = _parse_smart_text_cli_args(sys.argv[2:])
        if options["text"] is None:
            print("Error: text required")
            sys.exit(1)
        print(json.dumps(
            smart_text_input(
                options["hwnd"],
                options["text"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                index=options["index"],
                match=options["match"],
                mode=options["mode"],
                timeout=options["timeout"],
                timeout_ms=options["timeout_ms"],
                verify=options["verify"],
                diagnostic=options["diagnostic"],
                allow_focus_fallback=options["allow_focus_fallback"],
                skip_uia=options["skip_uia"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("smart-wait-text", "smart_wait_text", "smart-wait-text-input", "smart_wait_text_input"):
        options = _parse_smart_text_cli_args(sys.argv[2:], wait_defaults=True)
        if options["text"] is None:
            print("Error: text required")
            sys.exit(1)
        print(json.dumps(
            smart_wait_text_input(
                options["hwnd"],
                options["text"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                index=options["index"],
                match=options["match"],
                mode=options["mode"],
                timeout=options["timeout"],
                interval=options["interval"],
                input_timeout=options["input_timeout"],
                timeout_ms=options["timeout_ms"],
                verify=options["verify"],
                diagnostic=options["diagnostic"],
                allow_focus_fallback=options["allow_focus_fallback"],
                skip_uia=options["skip_uia"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("smart-click", "smart_click", "smart-control-action", "smart_control_action"):
        options = _parse_smart_click_cli_args(sys.argv[2:])
        print(json.dumps(
            smart_click(
                options["hwnd"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                index=options["index"],
                match=options["match"],
                action=options["action"],
                button=options["button"],
                clicks=options["clicks"],
                timeout_ms=options["timeout_ms"],
                diagnostic=options["diagnostic"],
                allow_coordinate_fallback=options["allow_coordinate_fallback"],
                skip_uia=options["skip_uia"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("smart-wait-click", "smart_wait_click", "smart-wait-control-action", "smart_wait_control_action"):
        options = _parse_smart_click_cli_args(sys.argv[2:], wait_defaults=True)
        print(json.dumps(
            smart_wait_click(
                options["hwnd"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                index=options["index"],
                match=options["match"],
                action=options["action"],
                timeout=options["timeout"],
                interval=options["interval"],
                button=options["button"],
                clicks=options["clicks"],
                timeout_ms=options["timeout_ms"],
                diagnostic=options["diagnostic"],
                allow_coordinate_fallback=options["allow_coordinate_fallback"],
                skip_uia=options["skip_uia"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("smart-select", "smart_select", "smart-select-item", "smart_select_item"):
        options = _parse_smart_select_cli_args(sys.argv[2:])
        print(json.dumps(
            smart_select(
                options["hwnd"],
                item=options["item"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                index=options["index"],
                match=options["match"],
                mode=options["mode"],
                timeout_ms=options["timeout_ms"],
                diagnostic=options["diagnostic"],
                skip_uia=options["skip_uia"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("smart-wait-select", "smart_wait_select", "smart-wait-select-item", "smart_wait_select_item"):
        options = _parse_smart_select_cli_args(sys.argv[2:], wait_defaults=True)
        print(json.dumps(
            smart_wait_select(
                options["hwnd"],
                item=options["item"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                index=options["index"],
                match=options["match"],
                mode=options["mode"],
                timeout=options["timeout"],
                interval=options["interval"],
                timeout_ms=options["timeout_ms"],
                diagnostic=options["diagnostic"],
                skip_uia=options["skip_uia"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("smart-cell", "smart_cell", "smart-grid-cell", "smart_grid_cell", "smart-listview-cell", "smart_listview_cell"):
        options = _parse_smart_cell_cli_args(sys.argv[2:])
        print(json.dumps(
            smart_cell(
                options["hwnd"],
                row=options["row"],
                column=options["column"],
                row_text=options["row_text"],
                column_name=options["column_name"],
                text=options["text"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                match=options["match"],
                action=options["action"],
                timeout_ms=options["timeout_ms"],
                diagnostic=options["diagnostic"],
                skip_uia=options["skip_uia"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("smart-wait-cell", "smart_wait_cell", "smart-wait-grid-cell", "smart_wait_grid_cell", "smart-wait-listview-cell", "smart_wait_listview_cell"):
        options = _parse_smart_cell_cli_args(sys.argv[2:])
        print(json.dumps(
            smart_wait_cell(
                options["hwnd"],
                row=options["row"],
                column=options["column"],
                row_text=options["row_text"],
                column_name=options["column_name"],
                text=options["text"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                match=options["match"],
                action=options["action"],
                timeout=options["timeout"],
                interval=options["interval"],
                timeout_ms=options["timeout_ms"],
                diagnostic=options["diagnostic"],
                skip_uia=options["skip_uia"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("smart-dialog", "smart_dialog", "smart-dialog-action", "smart_dialog_action", "smart-wait-dialog-action", "smart_wait_dialog_action"):
        options = _parse_smart_dialog_cli_args(sys.argv[2:])
        print(json.dumps(
            smart_dialog_action(
                options["hwnd"],
                action_kind=options["action_kind"],
                dialog_title=options["dialog_title"],
                dialog_class_name=options["dialog_class_name"],
                dialog_process=options["dialog_process"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                index=options["index"],
                match=options["match"],
                text=options["text"],
                item=options["item"],
                row=options["row"],
                column=options["column"],
                row_text=options["row_text"],
                column_name=options["column_name"],
                control_action=options["control_action"],
                cell_action=options["cell_action"],
                mode=options["mode"],
                timeout=options["timeout"],
                action_timeout=options["action_timeout"],
                interval=options["interval"],
                input_timeout=options["input_timeout"],
                timeout_ms=options["timeout_ms"],
                verify=options["verify"],
                diagnostic=options["diagnostic"],
                allow_focus_fallback=options["allow_focus_fallback"],
                allow_coordinate_fallback=options["allow_coordinate_fallback"],
                skip_uia=options["skip_uia"],
                include_invisible=options["include_invisible"],
                stable_ticks=options["stable_ticks"],
                activate=options["activate"],
                button=options["button"],
                clicks=options["clicks"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("dialog-command", "dialog_command", "dialog-command-action", "dialog_command_action", "native-dialog-command", "native_dialog_command", "messagebox-command", "messagebox_command", "message-box-command", "message_box_command"):
        options = _parse_dialog_button_cli_args(sys.argv[2:])
        print(json.dumps(
            dialog_command_action(
                options["hwnd"],
                action=options["action"] or options["name"],
                command_id=options["command_id"],
                name=options["name"],
                dialog_title=options["dialog_title"],
                dialog_class_name=options["dialog_class_name"],
                dialog_process=options["dialog_process"],
                match=options["match"],
                timeout=options["timeout"],
                interval=options["interval"],
                timeout_ms=options["timeout_ms"],
                include_invisible=options["include_invisible"],
                activate=options["activate"],
                verify_close=options["verify_close"],
                diagnostic=options["diagnostic"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("dialog-button", "dialog_button", "dialog-button-action", "dialog_button_action", "native-dialog-button", "native_dialog_button", "messagebox-button", "messagebox_button", "message-box-button", "message_box_button"):
        options = _parse_dialog_button_cli_args(sys.argv[2:])
        print(json.dumps(
            dialog_button_action(
                options["hwnd"],
                name=options["name"],
                action=options["action"],
                command_id=options["command_id"],
                dialog_title=options["dialog_title"],
                dialog_class_name=options["dialog_class_name"],
                dialog_process=options["dialog_process"],
                automation_id=options["automation_id"],
                class_name=options["class_name"],
                control_type=options["control_type"],
                index=options["index"],
                match=options["match"],
                timeout=options["timeout"],
                interval=options["interval"],
                timeout_ms=options["timeout_ms"],
                include_invisible=options["include_invisible"],
                activate=options["activate"],
                verify_close=options["verify_close"],
                prefer_command=options["prefer_command"],
                diagnostic=options["diagnostic"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "related-windows":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        include_invisible = "--include-invisible" in sys.argv[3:]
        print(json.dumps(related_windows(int(sys.argv[2]), include_invisible=include_invisible), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "wait-window":
        title = None
        process = None
        timeout = 10.0
        interval = 0.25
        match = "contains"
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--title" and i + 1 < len(args):
                title = args[i + 1]
                i += 2
            elif args[i] == "--process" and i + 1 < len(args):
                process = args[i + 1]
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--interval" and i + 1 < len(args):
                interval = float(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            else:
                i += 1
        print(json.dumps(wait_window(title=title, process=process, timeout=timeout, interval=interval, match=match), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("window-selector-repair-find", "window_selector_repair_find", "window-repair-find", "window_repair_find", "window-rebind", "window_rebind"):
        suggestion: Dict[str, Any] = {}
        original: Dict[str, Any] = {}
        timeout: Optional[float] = None
        interval: Optional[float] = None
        match: Optional[str] = None
        stable_ticks: Optional[int] = None
        allow_suggestion_hwnd = False
        probe_original = True
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--suggestion" and i + 1 < len(args):
                suggestion = json.loads(args[i + 1])
                i += 2
            elif args[i] == "--original" and i + 1 < len(args):
                original = json.loads(args[i + 1])
                i += 2
            elif args[i] == "--hwnd" and i + 1 < len(args):
                original["hwnd"] = int(args[i + 1], 0)
                i += 2
            elif args[i] == "--title" and i + 1 < len(args):
                original["title"] = args[i + 1]
                i += 2
            elif args[i] == "--process" and i + 1 < len(args):
                original["process"] = args[i + 1]
                i += 2
            elif args[i] == "--pid" and i + 1 < len(args):
                original["pid"] = int(args[i + 1], 0)
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                original["timeout"] = timeout
                i += 2
            elif args[i] == "--interval" and i + 1 < len(args):
                interval = float(args[i + 1])
                original["interval"] = interval
                i += 2
            elif args[i] in ("--stable-ticks", "--stable_ticks") and i + 1 < len(args):
                stable_ticks = int(args[i + 1])
                original["stable_ticks"] = stable_ticks
                i += 2
            elif args[i] == "--match" and i + 1 < len(args):
                match = args[i + 1]
                original["match"] = match
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                original["match"] = match
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                original["match"] = match
                i += 1
            elif args[i] == "--allow-suggestion-hwnd":
                allow_suggestion_hwnd = True
                i += 1
            elif args[i] == "--no-probe-original":
                probe_original = False
                i += 1
            else:
                i += 1
        print(json.dumps(
            window_selector_repair_find(
                suggestion=suggestion,
                original=original,
                timeout=timeout,
                interval=interval,
                match=match,
                stable_ticks=stable_ticks,
                allow_suggestion_hwnd=allow_suggestion_hwnd,
                probe_original=probe_original,
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("window-action", "window_action", "window"):
        if len(sys.argv) < 4:
            print("Error: hwnd and action required")
            sys.exit(1)
        hwnd = int(sys.argv[2], 0)
        action = sys.argv[3]
        x = None
        y = None
        width = None
        height = None
        timeout = 1.5
        args = sys.argv[4:]
        i = 0
        if action.lower().replace("-", "_") in ("move", "resize", "set_rect", "set_position", "position"):
            positional: List[int] = []
            while i < len(args) and not args[i].startswith("--") and len(positional) < 4:
                positional.append(int(args[i], 0))
                i += 1
            if len(positional) >= 2:
                x, y = positional[0], positional[1]
            if len(positional) >= 4:
                width, height = positional[2], positional[3]
        while i < len(args):
            if args[i] == "--x" and i + 1 < len(args):
                x = int(args[i + 1], 0)
                i += 2
            elif args[i] == "--y" and i + 1 < len(args):
                y = int(args[i + 1], 0)
                i += 2
            elif args[i] in ("--width", "--w") and i + 1 < len(args):
                width = int(args[i + 1], 0)
                i += 2
            elif args[i] in ("--height", "--h") and i + 1 < len(args):
                height = int(args[i + 1], 0)
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            else:
                i += 1
        print(json.dumps(window_action(hwnd, action, x=x, y=y, width=width, height=height, timeout=timeout), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "wait-event":
        event = None
        hwnd = None
        pid = None
        title = None
        class_name = None
        timeout = 5.0
        limit = 1
        match = "contains"
        include_children = True
        skip_own_process = True
        args = sys.argv[2:]
        if args and not args[0].startswith("--"):
            event = args[0]
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--hwnd" and i + 1 < len(args):
                hwnd = int(args[i + 1], 0)
                i += 2
            elif args[i] == "--pid" and i + 1 < len(args):
                pid = int(args[i + 1], 0)
                i += 2
            elif args[i] == "--title" and i + 1 < len(args):
                title = args[i + 1]
                i += 2
            elif args[i] in ("--class", "--class-name") and i + 1 < len(args):
                class_name = args[i + 1]
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            elif args[i] == "--top-level-only":
                include_children = False
                i += 1
            elif args[i] == "--include-own-process":
                skip_own_process = False
                i += 1
            else:
                i += 1
        print(json.dumps(wait_event(event=event, hwnd=hwnd, pid=pid, title=title, class_name=class_name, timeout=timeout, limit=limit, match=match, include_children=include_children, skip_own_process=skip_own_process), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "screen":
        print(json.dumps(screen_info(), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "mouse":
        print(json.dumps(mouse_position(), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("mouse-context", "mouse_context", "cursor-context", "cursor_context", "point-context", "point_context"):
        args = sys.argv[2:]
        positional = [arg for arg in args if not arg.startswith("--")]
        x = int(positional[0]) if len(positional) >= 2 else None
        y = int(positional[1]) if len(positional) >= 2 else None
        hwnd = int(positional[2]) if len(positional) >= 3 else None
        screenshot_id = int(positional[3]) if len(positional) >= 4 else None
        print(json.dumps(mouse_context(
            x,
            y,
            hwnd=hwnd,
            screenshot_id=screenshot_id,
            include_text="--include-text" in args,
            include_uia="--no-uia" not in args,
            include_msaa="--no-msaa" not in args,
        ), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "child-windows":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        include_invisible = "--include-invisible" in sys.argv[3:]
        include_text = "--include-text" in sys.argv[3:]
        max_count = 500
        args = sys.argv[3:]
        for i, arg in enumerate(args):
            if arg == "--max-count" and i + 1 < len(args):
                max_count = int(args[i + 1])
        print(json.dumps(child_windows(hwnd, include_invisible=include_invisible, include_text=include_text, max_count=max_count), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "window-from-point":
        if len(sys.argv) < 4:
            print("Error: x and y required")
            sys.exit(1)
        x, y = int(sys.argv[2]), int(sys.argv[3])
        hwnd = int(sys.argv[4]) if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else None
        screenshot_id = int(sys.argv[5]) if len(sys.argv) > 5 and not sys.argv[5].startswith("--") else None
        include_text = "--include-text" in sys.argv[4:]
        print(json.dumps(window_from_point(x, y, hwnd=hwnd, screenshot_id=screenshot_id, include_text=include_text), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "element-from-point":
        if len(sys.argv) < 4:
            print("Error: x and y required")
            sys.exit(1)
        x, y = int(sys.argv[2]), int(sys.argv[3])
        hwnd = int(sys.argv[4]) if len(sys.argv) > 4 else None
        screenshot_id = int(sys.argv[5]) if len(sys.argv) > 5 else None
        print(json.dumps(element_from_point(x, y, hwnd=hwnd, screenshot_id=screenshot_id), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "msaa-window":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        max_children = int(sys.argv[3]) if len(sys.argv) > 3 else 80
        print(json.dumps(msaa_window(hwnd, max_children=max_children), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "msaa-from-point":
        if len(sys.argv) < 4:
            print("Error: x and y required")
            sys.exit(1)
        x, y = int(sys.argv[2]), int(sys.argv[3])
        hwnd = int(sys.argv[4]) if len(sys.argv) > 4 else None
        screenshot_id = int(sys.argv[5]) if len(sys.argv) > 5 else None
        print(json.dumps(msaa_from_point(x, y, hwnd=hwnd, screenshot_id=screenshot_id), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "msaa-action":
        if len(sys.argv) < 4:
            print("Error: hwnd and action required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        action = sys.argv[3]
        path = json.loads(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else []
        value = sys.argv[5] if len(sys.argv) > 5 else None
        print(json.dumps(msaa_action(hwnd, path=path, action=action, value=value), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "menu-tree":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        args = sys.argv[3:]
        include_system = "--system" in args or "--include-system" in args
        max_depth = 5
        max_items = 300
        for i, arg in enumerate(args):
            if arg == "--max-depth" and i + 1 < len(args):
                max_depth = int(args[i + 1])
            elif arg == "--max-items" and i + 1 < len(args):
                max_items = int(args[i + 1])
        print(json.dumps(menu_tree(hwnd, include_system=include_system, max_depth=max_depth, max_items=max_items), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "menu-action":
        if len(sys.argv) < 4:
            print("Error: hwnd and path_json or command_id required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        target = sys.argv[3]
        args = sys.argv[4:]
        include_system = "--system" in args or "--include-system" in args
        async_post = "--post" in args or "--async" in args
        timeout_ms = 500
        for i, arg in enumerate(args):
            if arg == "--timeout-ms" and i + 1 < len(args):
                timeout_ms = int(args[i + 1])
        command_id = None
        path: Any = target
        try:
            command_id = int(target, 0)
            path = None
        except ValueError:
            try:
                parsed = json.loads(target)
                path = parsed if isinstance(parsed, list) else target
            except json.JSONDecodeError:
                path = target
        print(json.dumps(menu_action(hwnd, path=path, command_id=command_id, include_system=include_system, async_post=async_post, timeout_ms=timeout_ms), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "win32-text":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        print(json.dumps(win32_text(int(sys.argv[2])), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "win32-set-text":
        if len(sys.argv) < 4:
            print("Error: hwnd and text required")
            sys.exit(1)
        print(json.dumps(win32_set_text(int(sys.argv[2]), sys.argv[3]), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "win32-click":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        print(json.dumps(win32_click(int(sys.argv[2])), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("win32-control-find", "win32_control_find", "win32-find-control", "win32_find_control", "native-control-find", "native_control_find"):
        options = _parse_win32_control_find_cli_args(sys.argv[2:])
        print(json.dumps(
            win32_control_find(
                options["hwnd"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                text=options["text"],
                value=options["value"],
                state=options["state"],
                expected=options["expected"],
                match=options["match"],
                include_invisible=options["include_invisible"],
                include_self=options["include_self"],
                limit=options["limit"],
                min_score=options["min_score"],
                timeout_ms=options["timeout_ms"],
                max_items=options["max_items"],
                max_children=options["max_children"],
                diagnostic=options["diagnostic"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("win32-control-wait-find", "win32_control_wait_find", "win32-wait-control-find", "win32_wait_control_find", "native-control-wait-find", "native_control_wait_find"):
        options = _parse_win32_control_find_cli_args(sys.argv[2:])
        print(json.dumps(
            win32_control_wait_find(
                options["hwnd"],
                name=options["name"],
                automation_id=options["automation_id"],
                control_type=options["control_type"],
                class_name=options["class_name"],
                text=options["text"],
                value=options["value"],
                state=options["state"],
                expected=options["expected"],
                match=options["match"],
                include_invisible=options["include_invisible"],
                include_self=options["include_self"],
                limit=options["limit"],
                min_score=options["min_score"],
                timeout=options["timeout"],
                interval=options["interval"],
                timeout_ms=options["timeout_ms"],
                max_items=options["max_items"],
                max_children=options["max_children"],
                diagnostic=options["diagnostic"],
                repair=options["repair"],
                repair_timeout=options["repair_timeout"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("file-dialog", "file_dialog", "file-dialog-info", "file_dialog_info", "file-dialog-action", "file_dialog_action"):
        subcmd = "info"
        args = sys.argv[2:]
        if cmd in ("file-dialog-info", "file_dialog_info"):
            subcmd = "info"
        elif cmd in ("file-dialog-action", "file_dialog_action"):
            subcmd = args[0] if args else "info"
            args = args[1:] if args else []
        elif args and not args[0].startswith("--"):
            subcmd = args[0]
            args = args[1:]

        hwnd = None
        path = None
        timeout = 5.0
        timeout_ms = 500
        include_children = False
        verify_close = False
        i = 0
        if args and not args[0].startswith("--"):
            if subcmd in ("info", "cancel", "confirm") and args[0].isdigit():
                hwnd = int(args[0])
            else:
                path = args[0]
            i = 1
        while i < len(args):
            if args[i] == "--hwnd" and i + 1 < len(args):
                hwnd = int(args[i + 1])
                i += 2
            elif args[i] in ("--path", "--file", "--filename") and i + 1 < len(args):
                path = args[i + 1]
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--timeout-ms" and i + 1 < len(args):
                timeout_ms = int(args[i + 1])
                i += 2
            elif args[i] == "--include-children":
                include_children = True
                i += 1
            elif args[i] == "--verify-close":
                verify_close = True
                i += 1
            else:
                i += 1
        if subcmd == "info":
            print(json.dumps(file_dialog_info(hwnd=hwnd, timeout=timeout, timeout_ms=timeout_ms, include_children=include_children), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(file_dialog_action(subcmd, hwnd=hwnd, path=path, timeout=timeout, timeout_ms=timeout_ms, verify_close=verify_close), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "win32-control-info":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        max_items = int(sys.argv[3]) if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else 200
        print(json.dumps(win32_control_info(hwnd, max_items=max_items), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "win32-control-action":
        if len(sys.argv) < 4:
            print("Error: hwnd and action required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        action_name = sys.argv[3]
        args = sys.argv[4:]
        index = None
        text = None
        value = None
        checked = None
        match = "contains"
        i = 0
        if args and not args[0].startswith("--"):
            try:
                index = int(args[0])
            except ValueError:
                text = args[0]
            i = 1
        while i < len(args):
            if args[i] == "--index" and i + 1 < len(args):
                index = int(args[i + 1])
                i += 2
            elif args[i] == "--text" and i + 1 < len(args):
                text = args[i + 1]
                i += 2
            elif args[i] == "--value" and i + 1 < len(args):
                value = int(args[i + 1])
                i += 2
            elif args[i] == "--checked" and i + 1 < len(args):
                checked = args[i + 1].lower() in ("1", "true", "yes", "on", "checked")
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            else:
                i += 1
        print(json.dumps(win32_control_action(hwnd, action_name, index=index, text=text, value=value, checked=checked, match=match), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("win32-control-wait", "win32_control_wait", "win32-wait-control", "win32_wait_control"):
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2], 0)
        args = sys.argv[3:]
        state = None
        expected = None
        index = None
        text = None
        match = "contains"
        timeout = 3.0
        interval = 0.1
        timeout_ms = 250
        max_items = 200
        diagnostic = False
        repair = None
        repair_match = None
        repair_timeout = None
        i = 0
        if i < len(args) and not args[i].startswith("--"):
            state = args[i]
            i += 1
        if i < len(args) and not args[i].startswith("--"):
            expected = args[i]
            i += 1
        while i < len(args):
            if args[i] == "--state" and i + 1 < len(args):
                state = args[i + 1]
                i += 2
            elif args[i] in ("--expected", "--value") and i + 1 < len(args):
                expected = args[i + 1]
                i += 2
            elif args[i] == "--index" and i + 1 < len(args):
                index = int(args[i + 1])
                i += 2
            elif args[i] in ("--text", "--item", "--name") and i + 1 < len(args):
                text = args[i + 1]
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--interval" and i + 1 < len(args):
                interval = float(args[i + 1])
                i += 2
            elif args[i] == "--timeout-ms" and i + 1 < len(args):
                timeout_ms = int(args[i + 1])
                i += 2
            elif args[i] == "--max-items" and i + 1 < len(args):
                max_items = int(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            elif args[i] == "--diagnostic":
                diagnostic = True
                i += 1
            elif args[i] == "--repair":
                repair = True
                i += 1
            elif args[i] == "--no-repair":
                repair = False
                i += 1
            elif args[i] == "--repair-match" and i + 1 < len(args):
                repair_match = args[i + 1]
                i += 2
            elif args[i] == "--repair-timeout" and i + 1 < len(args):
                repair_timeout = float(args[i + 1])
                i += 2
            else:
                i += 1
        print(json.dumps(
            win32_control_wait(
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
                repair=repair,
                repair_match=repair_match,
                repair_timeout=repair_timeout,
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "doctor":
        hwnd = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(json.dumps(doctor(hwnd), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "selftest":
        target = sys.argv[2] if len(sys.argv) > 2 else "notepad"
        timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
        print(json.dumps(selftest.selftest(target, timeout=timeout), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "launch":
        if len(sys.argv) < 3:
            print("Error: app name or path required")
            sys.exit(1)
        timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
        result = launch_app(sys.argv[2], timeout=timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "observe":
        hwnd = None
        args = sys.argv[2:]
        if args and not args[0].startswith("--"):
            hwnd = int(args[0])
            args = args[1:]
        include_screenshot = "--no-screenshot" not in args
        include_accessibility = "--no-a11y" not in args
        include_ocr = "--ocr" in args
        ocr_on_accessibility_error = "--no-ocr-on-a11y-error" not in args
        max_width = 1280
        max_elements = 500
        max_depth = 10
        view = "raw"
        ocr_engine = "auto"
        ocr_lang = "eng+chi_sim"
        output = None
        capture_mode = "auto"
        i = 0
        while i < len(args):
            if args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--max-depth" and i + 1 < len(args):
                max_depth = int(args[i + 1])
                i += 2
            elif args[i] == "--max-elements" and i + 1 < len(args):
                max_elements = int(args[i + 1])
                i += 2
            elif args[i] == "--view" and i + 1 < len(args):
                view = _normalize_uia_view(args[i + 1])
                i += 2
            elif args[i] == "--ocr-engine" and i + 1 < len(args):
                ocr_engine = _normalize_ocr_engine(args[i + 1])
                i += 2
            elif args[i] == "--ocr-lang" and i + 1 < len(args):
                ocr_lang = args[i + 1]
                i += 2
            elif args[i] == "--output" and i + 1 < len(args):
                output = args[i + 1]
                i += 2
            elif args[i] in ("--capture-mode", "--capture") and i + 1 < len(args):
                capture_mode = args[i + 1]
                i += 2
            else:
                i += 1
        result = observe(
            hwnd,
            include_screenshot=include_screenshot,
            include_accessibility=include_accessibility,
            include_ocr=include_ocr,
            ocr_on_accessibility_error=ocr_on_accessibility_error,
            ocr_engine=ocr_engine,
            ocr_lang=ocr_lang,
            max_width=max_width,
            max_depth=max_depth,
            max_elements=max_elements,
            view=view,
            output=output,
            capture_mode=capture_mode,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "screenshot":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        args = sys.argv[3:]
        output = (
            args[0]
            if args and not args[0].startswith("--")
            else os.path.join(os.path.dirname(__file__), "screenshot.jpg")
        )
        if args and not args[0].startswith("--"):
            args = args[1:]
        max_width = 1280
        capture_mode = "auto"
        i = 0
        while i < len(args):
            if args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] in ("--capture-mode", "--capture") and i + 1 < len(args):
                capture_mode = args[i + 1]
                i += 2
            else:
                i += 1
        result = screenshot(hwnd, output, max_width=max_width, capture_mode=capture_mode)
        print(json.dumps(result, ensure_ascii=False))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-screenshot", "desktop_screenshot"):
        output = os.path.join(os.path.dirname(__file__), "desktop.jpg")
        max_width = 1600
        args = sys.argv[2:]
        if args and not args[0].startswith("--"):
            output = args[0]
            args = args[1:]
        if args and not args[0].startswith("--"):
            max_width = int(args[0])
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            else:
                i += 1
        output_path = output or os.path.join(tempfile.gettempdir(), f"desktop-{int(time.time()*1000)}.jpg")
        result = desktop_screenshot(output_path, max_width=max_width)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "accessibility":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        args = sys.argv[3:]
        max_depth = 10
        max_elements = 500
        view = "raw"
        i = 0
        while i < len(args):
            if args[i] == "--max-depth" and i + 1 < len(args):
                max_depth = int(args[i + 1])
                i += 2
            elif args[i] == "--max-elements" and i + 1 < len(args):
                max_elements = int(args[i + 1])
                i += 2
            elif args[i] == "--view" and i + 1 < len(args):
                view = _normalize_uia_view(args[i + 1])
                i += 2
            else:
                i += 1
        result = build_accessibility_tree(hwnd, max_depth=max_depth, max_elements=max_elements, view=view)
        print(json.dumps(result, ensure_ascii=False))

    # ------------------------------------------------------------------
    elif cmd == "pixel":
        if len(sys.argv) < 5:
            print("Error: hwnd, x, y required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x = int(sys.argv[3])
        y = int(sys.argv[4])
        screenshot_id = int(sys.argv[5]) if len(sys.argv) > 5 else None
        print(json.dumps(pixel(hwnd, x, y, screenshot_id), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("pixel-wait", "pixel_wait", "wait-pixel", "wait_pixel"):
        if len(sys.argv) < 6:
            print("Error: hwnd, x, y, color required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x = int(sys.argv[3])
        y = int(sys.argv[4])
        color = sys.argv[5]
        options = _parse_pixel_wait_args(sys.argv[6:])
        print(json.dumps(pixel_wait(
            hwnd,
            x,
            y,
            color,
            tolerance=options["tolerance"],
            timeout=options["timeout"],
            interval=options["interval"],
            mode=options["mode"],
            capture_mode=options["capture_mode"],
        ), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("visual-stable-wait", "visual_stable_wait", "wait-visual-stable", "wait_visual_stable", "visual-wait-stable", "visual_wait_stable"):
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        options = _parse_visual_stable_wait_args(sys.argv[3:])
        print(json.dumps(visual_stable_wait(
            hwnd,
            timeout=options["timeout"],
            interval=options["interval"],
            stable_ticks=options["stable_ticks"],
            difference_threshold=options["difference_threshold"],
            pixel_threshold=options["pixel_threshold"],
            region=options["region"],
            max_width=options["max_width"],
            comparison_max_width=options["comparison_max_width"],
            capture_mode=options["capture_mode"],
        ), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("uia-stable-wait", "uia_stable_wait", "wait-uia-stable", "wait_uia_stable", "uia-wait-stable", "uia_wait_stable"):
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        options = _parse_uia_stable_wait_args(sys.argv[3:])
        print(json.dumps(uia_stable_wait(
            hwnd,
            timeout=options["timeout"],
            interval=options["interval"],
            stable_ticks=options["stable_ticks"],
            max_depth=options["max_depth"],
            max_elements=options["max_elements"],
            view=options["view"],
            include_values=options["include_values"],
            rect_bucket=options["rect_bucket"],
        ), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-pixel", "desktop_pixel"):
        if len(sys.argv) < 4:
            print("Error: x and y required")
            sys.exit(1)
        x = int(sys.argv[2])
        y = int(sys.argv[3])
        screenshot_id = int(sys.argv[4]) if len(sys.argv) > 4 else None
        print(json.dumps(desktop_pixel(x, y, screenshot_id), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-pixel-wait", "desktop_pixel_wait", "desktop-wait-pixel", "desktop_wait_pixel", "wait-desktop-pixel", "wait_desktop_pixel"):
        if len(sys.argv) < 5:
            print("Error: x, y, color required")
            sys.exit(1)
        x = int(sys.argv[2])
        y = int(sys.argv[3])
        color = sys.argv[4]
        options = _parse_pixel_wait_args(sys.argv[5:])
        print(json.dumps(desktop_pixel_wait(
            x,
            y,
            color,
            tolerance=options["tolerance"],
            timeout=options["timeout"],
            interval=options["interval"],
            mode=options["mode"],
            max_width=options["max_width"],
        ), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-visual-stable-wait", "desktop_visual_stable_wait", "desktop-wait-visual-stable", "desktop_wait_visual_stable", "wait-desktop-visual-stable", "wait_desktop_visual_stable"):
        options = _parse_visual_stable_wait_args(sys.argv[2:])
        print(json.dumps(desktop_visual_stable_wait(
            timeout=options["timeout"],
            interval=options["interval"],
            stable_ticks=options["stable_ticks"],
            difference_threshold=options["difference_threshold"],
            pixel_threshold=options["pixel_threshold"],
            region=options["region"],
            max_width=options["max_width"],
            comparison_max_width=options["comparison_max_width"],
        ), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-uia-stable-wait", "desktop_uia_stable_wait", "desktop-wait-uia-stable", "desktop_wait_uia_stable", "wait-desktop-uia-stable", "wait_desktop_uia_stable"):
        options = _parse_uia_stable_wait_args(sys.argv[2:])
        if "--max-depth" not in sys.argv[2:] and "--depth" not in sys.argv[2:]:
            options["max_depth"] = 4
        print(json.dumps(desktop_uia_stable_wait(
            timeout=options["timeout"],
            interval=options["interval"],
            stable_ticks=options["stable_ticks"],
            max_depth=options["max_depth"],
            max_elements=options["max_elements"],
            view=options["view"],
            include_values=options["include_values"],
            rect_bucket=options["rect_bucket"],
        ), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-point", "desktop_point"):
        if len(sys.argv) < 4:
            print("Error: x and y required")
            sys.exit(1)
        x = int(sys.argv[2])
        y = int(sys.argv[3])
        screenshot_id = int(sys.argv[4]) if len(sys.argv) > 4 else None
        print(json.dumps(desktop_point(x, y, screenshot_id), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-locate-image", "desktop_locate_image"):
        if len(sys.argv) < 3:
            print("Error: template image path required")
            sys.exit(1)
        template = sys.argv[2]
        options = _parse_image_match_args(sys.argv[3:])
        result = desktop_locate_image(
            template,
            confidence=options["confidence"],
            max_width=options.get("max_width", 1600),
            screenshot_id=options["screenshot_id"],
            region=options["region"],
            scale_min=options["scale_min"],
            scale_max=options["scale_max"],
            scale_step=options["scale_step"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-image-wait", "desktop_image_wait", "desktop-wait-image", "desktop_wait_image"):
        if len(sys.argv) < 3:
            print("Error: template image path required")
            sys.exit(1)
        template = sys.argv[2]
        options = _parse_image_match_args(sys.argv[3:])
        if not options.get("timeout"):
            options["timeout"] = 10.0
        result = desktop_image_wait(
            template,
            confidence=options["confidence"],
            max_width=options.get("max_width", 1600),
            timeout=options["timeout"],
            interval=options["interval"],
            region=options["region"],
            scale_min=options["scale_min"],
            scale_max=options["scale_max"],
            scale_step=options["scale_step"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-image-click", "desktop_image_click", "desktop-click-image", "desktop_click_image"):
        if len(sys.argv) < 3:
            print("Error: template image path required")
            sys.exit(1)
        template = sys.argv[2]
        options = _parse_image_match_args(sys.argv[3:])
        result = desktop_image_click(
            template,
            confidence=options["confidence"],
            max_width=options.get("max_width", 1600),
            screenshot_id=options["screenshot_id"],
            button=options["button"],
            clicks=options["clicks"],
            timeout=options["timeout"],
            interval=options["interval"],
            region=options["region"],
            scale_min=options["scale_min"],
            scale_max=options["scale_max"],
            scale_step=options["scale_step"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "locate-image":
        if len(sys.argv) < 4:
            print("Error: hwnd and template image path required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        template = sys.argv[3]
        options = _parse_image_match_args(sys.argv[4:])
        result = locate_image(
            hwnd,
            template,
            confidence=options["confidence"],
            max_width=options["max_width"],
            screenshot_id=options["screenshot_id"],
            region=options["region"],
            scale_min=options["scale_min"],
            scale_max=options["scale_max"],
            scale_step=options["scale_step"],
            capture_mode=options["capture_mode"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("image-wait", "image_wait", "wait-image", "wait_image"):
        if len(sys.argv) < 4:
            print("Error: hwnd and template image path required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        template = sys.argv[3]
        options = _parse_image_match_args(sys.argv[4:])
        if not options.get("timeout"):
            options["timeout"] = 10.0
        result = image_wait(
            hwnd,
            template,
            confidence=options["confidence"],
            max_width=options["max_width"],
            timeout=options["timeout"],
            interval=options["interval"],
            region=options["region"],
            scale_min=options["scale_min"],
            scale_max=options["scale_max"],
            scale_step=options["scale_step"],
            capture_mode=options["capture_mode"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("image-click", "image_click", "click-image", "click_image"):
        if len(sys.argv) < 4:
            print("Error: hwnd and template image path required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        template = sys.argv[3]
        options = _parse_image_match_args(sys.argv[4:])
        result = image_click(
            hwnd,
            template,
            confidence=options["confidence"],
            max_width=options["max_width"],
            screenshot_id=options["screenshot_id"],
            button=options["button"],
            clicks=options["clicks"],
            timeout=options["timeout"],
            interval=options["interval"],
            region=options["region"],
            scale_min=options["scale_min"],
            scale_max=options["scale_max"],
            scale_step=options["scale_step"],
            capture_mode=options["capture_mode"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "ocr":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        args = sys.argv[3:]
        lang = "eng+chi_sim"
        engine = "auto"
        max_width = 1600
        screenshot_id = None
        capture_mode = "auto"
        if args and not args[0].startswith("--"):
            lang = args[0]
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = _normalize_ocr_engine(args[i + 1])
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--screenshot-id" and i + 1 < len(args):
                screenshot_id = int(args[i + 1])
                i += 2
            elif args[i] in ("--capture-mode", "--capture") and i + 1 < len(args):
                capture_mode = args[i + 1]
                i += 2
            else:
                i += 1
        print(json.dumps(ocr(hwnd, lang=lang, max_width=max_width, screenshot_id=screenshot_id, engine=engine, capture_mode=capture_mode), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-ocr", "desktop_ocr"):
        lang = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "eng+chi_sim"
        args = sys.argv[3:] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else sys.argv[2:]
        engine = "auto"
        max_width = 1600
        screenshot_id = None
        i = 0
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = args[i + 1]
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--screenshot-id" and i + 1 < len(args):
                screenshot_id = int(args[i + 1])
                i += 2
            else:
                i += 1
        print(json.dumps(desktop_ocr(lang=lang, max_width=max_width, screenshot_id=screenshot_id, engine=engine), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-ocr-find", "desktop_ocr_find"):
        if len(sys.argv) < 3:
            print("Error: text required")
            sys.exit(1)
        text = sys.argv[2]
        lang = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "eng+chi_sim"
        args = sys.argv[4:] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else sys.argv[3:]
        engine = "auto"
        match = "contains"
        region = None
        max_width = 1600
        screenshot_id = None
        limit = 10
        max_words = None
        i = 0
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = args[i + 1]
                i += 2
            elif args[i] == "--match" and i + 1 < len(args):
                match = args[i + 1]
                i += 2
            elif args[i] == "--region" and i + 1 < len(args):
                region = args[i + 1]
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--screenshot-id" and i + 1 < len(args):
                screenshot_id = int(args[i + 1])
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            elif args[i] == "--max-words" and i + 1 < len(args):
                max_words = int(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            else:
                i += 1
        print(json.dumps(desktop_ocr_find(text, lang=lang, max_width=max_width, screenshot_id=screenshot_id, engine=engine, match=match, limit=limit, region=region, max_words=max_words), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-ocr-wait", "desktop_ocr_wait", "desktop-wait-ocr", "desktop_wait_ocr"):
        if len(sys.argv) < 3:
            print("Error: text required")
            sys.exit(1)
        text = sys.argv[2]
        lang = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "eng+chi_sim"
        args = sys.argv[4:] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else sys.argv[3:]
        engine = "auto"
        match = "contains"
        region = None
        max_width = 1600
        timeout = 10.0
        interval = 0.5
        limit = 10
        max_words = None
        i = 0
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = args[i + 1]
                i += 2
            elif args[i] == "--match" and i + 1 < len(args):
                match = args[i + 1]
                i += 2
            elif args[i] == "--region" and i + 1 < len(args):
                region = args[i + 1]
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--interval" and i + 1 < len(args):
                interval = float(args[i + 1])
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            elif args[i] == "--max-words" and i + 1 < len(args):
                max_words = int(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            else:
                i += 1
        print(json.dumps(desktop_ocr_wait(text, lang=lang, max_width=max_width, engine=engine, match=match, timeout=timeout, interval=interval, limit=limit, region=region, max_words=max_words), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-ocr-click", "desktop_ocr_click"):
        if len(sys.argv) < 3:
            print("Error: text required")
            sys.exit(1)
        text = sys.argv[2]
        lang = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "eng+chi_sim"
        args = sys.argv[4:] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else sys.argv[3:]
        engine = "auto"
        match = "contains"
        region = None
        max_width = 1600
        screenshot_id = None
        index = 0
        button = "left"
        clicks = 1
        timeout = 0.0
        interval = 0.5
        max_words = None
        i = 0
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = args[i + 1]
                i += 2
            elif args[i] == "--match" and i + 1 < len(args):
                match = args[i + 1]
                i += 2
            elif args[i] == "--region" and i + 1 < len(args):
                region = args[i + 1]
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--screenshot-id" and i + 1 < len(args):
                screenshot_id = int(args[i + 1])
                i += 2
            elif args[i] == "--index" and i + 1 < len(args):
                index = int(args[i + 1])
                i += 2
            elif args[i] == "--button" and i + 1 < len(args):
                button = args[i + 1]
                i += 2
            elif args[i] == "--clicks" and i + 1 < len(args):
                clicks = int(args[i + 1])
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--interval" and i + 1 < len(args):
                interval = float(args[i + 1])
                i += 2
            elif args[i] == "--max-words" and i + 1 < len(args):
                max_words = int(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            else:
                i += 1
        print(json.dumps(desktop_ocr_click(text, lang=lang, max_width=max_width, screenshot_id=screenshot_id, engine=engine, match=match, index=index, button=button, clicks=clicks, region=region, max_words=max_words, timeout=timeout, interval=interval), ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("ocr-find", "ocr_find"):
        if len(sys.argv) < 4:
            print("Error: hwnd and text required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        text = sys.argv[3]
        args = sys.argv[4:]
        lang = "eng+chi_sim"
        engine = "auto"
        max_width = 1600
        screenshot_id = None
        match = "contains"
        limit = 10
        region = None
        max_words = None
        capture_mode = "auto"
        if args and not args[0].startswith("--"):
            lang = args[0]
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = _normalize_ocr_engine(args[i + 1])
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--screenshot-id" and i + 1 < len(args):
                screenshot_id = int(args[i + 1])
                i += 2
            elif args[i] == "--match" and i + 1 < len(args):
                match = _normalize_ocr_match_mode(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            elif args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            elif args[i] == "--region" and i + 1 < len(args):
                region = args[i + 1]
                i += 2
            elif args[i] == "--max-words" and i + 1 < len(args):
                max_words = int(args[i + 1])
                i += 2
            elif args[i] in ("--capture-mode", "--capture") and i + 1 < len(args):
                capture_mode = args[i + 1]
                i += 2
            else:
                i += 1
        print(json.dumps(
            ocr_find(
                hwnd,
                text,
                lang=lang,
                max_width=max_width,
                screenshot_id=screenshot_id,
                engine=engine,
                match=match,
                limit=limit,
                region=region,
                max_words=max_words,
                capture_mode=capture_mode,
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("ocr-click", "ocr_click"):
        if len(sys.argv) < 4:
            print("Error: hwnd and text required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        text = sys.argv[3]
        args = sys.argv[4:]
        lang = "eng+chi_sim"
        engine = "auto"
        max_width = 1600
        screenshot_id = None
        match = "contains"
        index = 0
        button = "left"
        clicks = 1
        region = None
        max_words = None
        capture_mode = "auto"
        timeout = 0.0
        interval = 0.5
        if args and not args[0].startswith("--"):
            lang = args[0]
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = _normalize_ocr_engine(args[i + 1])
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--screenshot-id" and i + 1 < len(args):
                screenshot_id = int(args[i + 1])
                i += 2
            elif args[i] == "--match" and i + 1 < len(args):
                match = _normalize_ocr_match_mode(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            elif args[i] == "--index" and i + 1 < len(args):
                index = int(args[i + 1])
                i += 2
            elif args[i] == "--button" and i + 1 < len(args):
                button = args[i + 1]
                i += 2
            elif args[i] == "--clicks" and i + 1 < len(args):
                clicks = int(args[i + 1])
                i += 2
            elif args[i] == "--region" and i + 1 < len(args):
                region = args[i + 1]
                i += 2
            elif args[i] == "--max-words" and i + 1 < len(args):
                max_words = int(args[i + 1])
                i += 2
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--interval" and i + 1 < len(args):
                interval = float(args[i + 1])
                i += 2
            elif args[i] in ("--capture-mode", "--capture") and i + 1 < len(args):
                capture_mode = args[i + 1]
                i += 2
            else:
                i += 1
        print(json.dumps(
            ocr_click(
                hwnd,
                text,
                lang=lang,
                max_width=max_width,
                screenshot_id=screenshot_id,
                engine=engine,
                match=match,
                index=index,
                button=button,
                clicks=clicks,
                region=region,
                max_words=max_words,
                timeout=timeout,
                interval=interval,
                capture_mode=capture_mode,
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in (
        "visual-row",
        "visual_row",
        "visual-row-find",
        "visual_row_find",
        "visual-row-click",
        "visual_row_click",
        "visual-row-scroll",
        "visual_row_scroll",
        "visual-row-wait",
        "visual_row_wait",
        "visual-row-scroll-click",
        "visual_row_scroll_click",
        "visual-row-wait-click",
        "visual_row_wait_click",
    ):
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        args = sys.argv[3:]
        row = None
        lang = "eng+chi_sim"
        engine = "auto"
        max_width = 1600
        screenshot_id = None
        row_region = None
        click_x = None
        x_offset = 120
        button = "left"
        clicks = 2 if cmd in ("visual-row-click", "visual_row_click", "visual-row-scroll-click", "visual_row_scroll_click", "visual-row-wait-click", "visual_row_wait_click") else 1
        min_row = 1
        max_row = 999
        max_scrolls = 8
        scroll_amount = 5
        scroll_x = None
        scroll_y = None
        pause = 0.35
        capture_mode = "auto"
        i = 0
        while i < len(args):
            if args[i] in ("--row", "-r") and i + 1 < len(args):
                row = int(args[i + 1])
                i += 2
            elif args[i] == "--engine" and i + 1 < len(args):
                engine = _normalize_ocr_engine(args[i + 1])
                i += 2
            elif args[i] == "--lang" and i + 1 < len(args):
                lang = args[i + 1]
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--screenshot-id" and i + 1 < len(args):
                screenshot_id = int(args[i + 1])
                i += 2
            elif args[i] in ("--row-region", "--region") and i + 1 < len(args):
                row_region = args[i + 1]
                i += 2
            elif args[i] == "--click-x" and i + 1 < len(args):
                click_x = int(args[i + 1])
                i += 2
            elif args[i] == "--x-offset" and i + 1 < len(args):
                x_offset = int(args[i + 1])
                i += 2
            elif args[i] == "--button" and i + 1 < len(args):
                button = args[i + 1]
                i += 2
            elif args[i] == "--clicks" and i + 1 < len(args):
                clicks = int(args[i + 1])
                i += 2
            elif args[i] == "--min-row" and i + 1 < len(args):
                min_row = int(args[i + 1])
                i += 2
            elif args[i] == "--max-row" and i + 1 < len(args):
                max_row = int(args[i + 1])
                i += 2
            elif args[i] == "--max-scrolls" and i + 1 < len(args):
                max_scrolls = int(args[i + 1])
                i += 2
            elif args[i] == "--scroll-amount" and i + 1 < len(args):
                scroll_amount = int(args[i + 1])
                i += 2
            elif args[i] == "--scroll-x" and i + 1 < len(args):
                scroll_x = int(args[i + 1])
                i += 2
            elif args[i] == "--scroll-y" and i + 1 < len(args):
                scroll_y = int(args[i + 1])
                i += 2
            elif args[i] == "--pause" and i + 1 < len(args):
                pause = float(args[i + 1])
                i += 2
            elif args[i] in ("--capture-mode", "--capture") and i + 1 < len(args):
                capture_mode = args[i + 1]
                i += 2
            elif row is None and not args[i].startswith("--"):
                row = int(args[i])
                i += 1
            else:
                i += 1
        if row is None:
            print("Error: --row N required")
            sys.exit(1)
        if cmd in ("visual-row-scroll-click", "visual_row_scroll_click", "visual-row-wait-click", "visual_row_wait_click"):
            result = visual_row_scroll_click(
                hwnd,
                row,
                lang=lang,
                max_width=max_width,
                engine=engine,
                row_region=row_region,
                click_x=click_x,
                x_offset=x_offset,
                button=button,
                clicks=clicks,
                min_row=min_row,
                max_row=max_row,
                max_scrolls=max_scrolls,
                scroll_amount=scroll_amount,
                scroll_x=scroll_x,
                scroll_y=scroll_y,
                pause=pause,
                capture_mode=capture_mode,
            )
        elif cmd in ("visual-row-scroll", "visual_row_scroll", "visual-row-wait", "visual_row_wait"):
            result = visual_row_scroll(
                hwnd,
                row,
                lang=lang,
                max_width=max_width,
                engine=engine,
                row_region=row_region,
                min_row=min_row,
                max_row=max_row,
                max_scrolls=max_scrolls,
                scroll_amount=scroll_amount,
                scroll_x=scroll_x,
                scroll_y=scroll_y,
                pause=pause,
                capture_mode=capture_mode,
            )
        elif cmd in ("visual-row-click", "visual_row_click"):
            result = visual_row_click(
                hwnd,
                row,
                lang=lang,
                max_width=max_width,
                screenshot_id=screenshot_id,
                engine=engine,
                row_region=row_region,
                click_x=click_x,
                x_offset=x_offset,
                button=button,
                clicks=clicks,
                min_row=min_row,
                max_row=max_row,
                capture_mode=capture_mode,
            )
        else:
            result = visual_row(
                hwnd,
                row,
                lang=lang,
                max_width=max_width,
                screenshot_id=screenshot_id,
                engine=engine,
                row_region=row_region,
                min_row=min_row,
                max_row=max_row,
                capture_mode=capture_mode,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("ocr-wait", "ocr_wait", "wait-ocr", "wait_ocr"):
        if len(sys.argv) < 4:
            print("Error: hwnd and text required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        text = sys.argv[3]
        args = sys.argv[4:]
        lang = "eng+chi_sim"
        engine = "auto"
        max_width = 1600
        match = "contains"
        timeout = 10.0
        interval = 0.5
        limit = 10
        region = None
        max_words = None
        capture_mode = "auto"
        if args and not args[0].startswith("--"):
            lang = args[0]
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--engine" and i + 1 < len(args):
                engine = _normalize_ocr_engine(args[i + 1])
                i += 2
            elif args[i] == "--max-width" and i + 1 < len(args):
                max_width = int(args[i + 1])
                i += 2
            elif args[i] == "--match" and i + 1 < len(args):
                match = _normalize_ocr_match_mode(args[i + 1])
                i += 2
            elif args[i] == "--exact":
                match = "exact"
                i += 1
            elif args[i] == "--regex":
                match = "regex"
                i += 1
            elif args[i] == "--timeout" and i + 1 < len(args):
                timeout = float(args[i + 1])
                i += 2
            elif args[i] == "--interval" and i + 1 < len(args):
                interval = float(args[i + 1])
                i += 2
            elif args[i] == "--limit" and i + 1 < len(args):
                limit = int(args[i + 1])
                i += 2
            elif args[i] == "--region" and i + 1 < len(args):
                region = args[i + 1]
                i += 2
            elif args[i] == "--max-words" and i + 1 < len(args):
                max_words = int(args[i + 1])
                i += 2
            elif args[i] in ("--capture-mode", "--capture") and i + 1 < len(args):
                capture_mode = args[i + 1]
                i += 2
            else:
                i += 1
        print(json.dumps(
            ocr_wait(
                hwnd,
                text,
                lang=lang,
                max_width=max_width,
                engine=engine,
                match=match,
                timeout=timeout,
                interval=interval,
                limit=limit,
                region=region,
                max_words=max_words,
                capture_mode=capture_mode,
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "find":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        try:
            selector, _ = _parse_selector_args(sys.argv[3:])
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        result = find_elements(hwnd, **selector)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-accessibility", "desktop_accessibility", "desktop-uia", "desktop_uia"):
        scan_options, _ = _parse_uia_scan_args(sys.argv[2:], _DESKTOP_UIA_KEY)
        if "--view" not in sys.argv[2:]:
            scan_options["view"] = "control"
        if "--max-depth" not in sys.argv[2:]:
            scan_options["max_depth"] = 4
        result = desktop_accessibility(
            max_depth=scan_options["max_depth"],
            max_elements=scan_options["max_elements"],
            hydrate=True,
            view=scan_options["view"],
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-find", "desktop_find", "desktop-find-elements", "desktop_find_elements"):
        try:
            selector, _ = _parse_selector_args(sys.argv[2:])
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        selector.setdefault("max_depth", 4)
        selector.setdefault("max_elements", 500)
        if "view" not in selector or selector.get("view") == "raw":
            selector["view"] = "control"
        result = desktop_find_elements(**selector)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-wait", "desktop_wait", "desktop-wait-element", "desktop_wait_element"):
        try:
            selector, options = _parse_selector_args(sys.argv[2:])
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        selector.setdefault("max_depth", 4)
        selector.setdefault("max_elements", 500)
        if "view" not in selector or selector.get("view") == "raw":
            selector["view"] = "control"
        result = desktop_wait_for_element(
            selector,
            timeout=options.get("timeout", 10.0),
            interval=options.get("interval", 0.5),
            repair=options.get("repair"),
            repair_timeout=options.get("repair_timeout"),
            allow_suggestion_index=options.get("allow_suggestion_index", False),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-element", "desktop_element"):
        if len(sys.argv) < 3:
            print("Error: index required")
            sys.exit(1)
        index = int(sys.argv[2])
        scan_options, _ = _parse_uia_scan_args(sys.argv[3:], _DESKTOP_UIA_KEY)
        print(json.dumps(
            desktop_element(
                index,
                max_depth=scan_options["max_depth"],
                max_elements=scan_options["max_elements"],
                view=scan_options["view"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-focus", "desktop_focus"):
        if len(sys.argv) < 3:
            print("Error: index required")
            sys.exit(1)
        index = int(sys.argv[2])
        scan_options, _ = _parse_uia_scan_args(sys.argv[3:], _DESKTOP_UIA_KEY)
        print(json.dumps(
            desktop_focus_element(
                index,
                max_depth=scan_options["max_depth"],
                max_elements=scan_options["max_elements"],
                view=scan_options["view"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-click-index", "desktop_click_index"):
        if len(sys.argv) < 3:
            print("Error: index required")
            sys.exit(1)
        index = int(sys.argv[2])
        scan_options, args = _parse_uia_scan_args(sys.argv[3:], _DESKTOP_UIA_KEY)
        button = "left"
        clicks = 1
        i = 0
        if args and not args[0].startswith("--"):
            button = args[0]
            i = 1
        if i < len(args) and not args[i].startswith("--"):
            clicks = int(args[i])
        print(desktop_click_index(
            index,
            button=button,
            clicks=clicks,
            max_depth=scan_options["max_depth"],
            max_elements=scan_options["max_elements"],
            view=scan_options["view"],
        ))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-action", "desktop_action"):
        if len(sys.argv) < 4:
            print("Error: index and action required")
            sys.exit(1)
        index = int(sys.argv[2])
        action_name = sys.argv[3]
        scan_options, action_args = _parse_uia_scan_args(sys.argv[4:], _DESKTOP_UIA_KEY)
        value, horizontal, vertical = _parse_uia_action_arguments(action_name, action_args)
        print(json.dumps(
            desktop_perform_action(
                index,
                action_name,
                value=value,
                horizontal=horizontal,
                vertical=vertical,
                max_depth=scan_options["max_depth"],
                max_elements=scan_options["max_elements"],
                view=scan_options["view"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "item-container-find":
        if len(sys.argv) < 6:
            print("Error: hwnd, index, property, and value required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        index = int(sys.argv[3])
        property_name = sys.argv[4]
        property_value = sys.argv[5]
        scan_options, remaining = _parse_uia_scan_args(sys.argv[6:], hwnd)
        limit = 1
        include_children = False
        max_children = 64
        i = 0
        while i < len(remaining):
            arg = remaining[i]
            if arg == "--include-children":
                include_children = True
            elif arg == "--max-children" and i + 1 < len(remaining):
                max_children = int(remaining[i + 1])
                i += 1
            elif not str(arg).startswith("--"):
                limit = int(arg)
            i += 1
        print(json.dumps(
            item_container_find(
                hwnd,
                index,
                property_name,
                property_value,
                limit=limit,
                max_depth=scan_options["max_depth"],
                max_elements=scan_options["max_elements"],
                view=scan_options["view"],
                include_children=include_children,
                max_children=max_children,
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "wait":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        try:
            selector, options = _parse_selector_args(sys.argv[3:])
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        timeout = options.get("timeout", 10.0)
        interval = options.get("interval", 0.5)
        result = wait_for_element(
            hwnd,
            selector,
            timeout=timeout,
            interval=interval,
            repair=options.get("repair"),
            repair_timeout=options.get("repair_timeout"),
            allow_suggestion_index=options.get("allow_suggestion_index", False),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "element":
        if len(sys.argv) < 4:
            print("Error: hwnd and index required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        index = int(sys.argv[3])
        scan_options, _ = _parse_uia_scan_args(sys.argv[4:], hwnd)
        _, info = _uia_element_by_index(
            hwnd,
            index,
            max_depth=scan_options["max_depth"],
            max_elements=scan_options["max_elements"],
            view=scan_options["view"],
        )
        print(json.dumps(info or {"error": f"Element index {index} not found"}, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "focus":
        if len(sys.argv) < 4:
            print("Error: hwnd and index required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        index = int(sys.argv[3])
        scan_options, _ = _parse_uia_scan_args(sys.argv[4:], hwnd)
        print(json.dumps(
            focus_element(
                hwnd,
                index,
                max_depth=scan_options["max_depth"],
                max_elements=scan_options["max_elements"],
                view=scan_options["view"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "click-index":
        if len(sys.argv) < 4:
            print("Error: hwnd and index required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        index = int(sys.argv[3])
        scan_options, args = _parse_uia_scan_args(sys.argv[4:], hwnd)
        button = "left"
        clicks = 1
        i = 0
        if args and not args[0].startswith("--"):
            button = args[0]
            i = 1
        if i < len(args) and not args[i].startswith("--"):
            clicks = int(args[i])
            i += 1
        print(click_index(
            hwnd,
            index,
            button,
            clicks,
            max_depth=scan_options["max_depth"],
            max_elements=scan_options["max_elements"],
            view=scan_options["view"],
        ))

    # ------------------------------------------------------------------
    elif cmd == "set-value":
        if len(sys.argv) < 5:
            print("Error: hwnd, index, and text required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        index = int(sys.argv[3])
        value = sys.argv[4]
        scan_options, _ = _parse_uia_scan_args(sys.argv[5:], hwnd)
        print(json.dumps(
            set_value(
                hwnd,
                index,
                value,
                max_depth=scan_options["max_depth"],
                max_elements=scan_options["max_elements"],
                view=scan_options["view"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "action":
        if len(sys.argv) < 5:
            print("Error: hwnd, index, and action required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        index = int(sys.argv[3])
        action_name = sys.argv[4]
        scan_options, action_args = _parse_uia_scan_args(sys.argv[5:], hwnd)
        value, horizontal, vertical = _parse_uia_action_arguments(action_name, action_args)
        print(json.dumps(
            perform_action(
                hwnd,
                index,
                action_name,
                value=value,
                horizontal=horizontal,
                vertical=vertical,
                max_depth=scan_options["max_depth"],
                max_elements=scan_options["max_elements"],
                view=scan_options["view"],
            ),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "click":
        if len(sys.argv) < 5:
            print("Error: hwnd, x, y required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x, y = int(sys.argv[3]), int(sys.argv[4])
        button = sys.argv[5] if len(sys.argv) > 5 else "left"
        clicks = int(sys.argv[6]) if len(sys.argv) > 6 else 1
        screenshot_id = int(sys.argv[7]) if len(sys.argv) > 7 else None
        print(click(hwnd, x, y, button, clicks, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd in ("move", "hover"):
        if len(sys.argv) < 5:
            print("Error: hwnd, x, y required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x, y = int(sys.argv[3]), int(sys.argv[4])
        screenshot_id = int(sys.argv[5]) if len(sys.argv) > 5 else None
        print(move_mouse(hwnd, x, y, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-click", "desktop_click"):
        if len(sys.argv) < 4:
            print("Error: x, y required")
            sys.exit(1)
        x, y = int(sys.argv[2]), int(sys.argv[3])
        button = sys.argv[4] if len(sys.argv) > 4 else "left"
        clicks = int(sys.argv[5]) if len(sys.argv) > 5 else 1
        screenshot_id = int(sys.argv[6]) if len(sys.argv) > 6 else None
        print(desktop_click(x, y, button, clicks, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-move", "desktop_move", "desktop-hover", "desktop_hover"):
        if len(sys.argv) < 4:
            print("Error: x, y required")
            sys.exit(1)
        x, y = int(sys.argv[2]), int(sys.argv[3])
        screenshot_id = int(sys.argv[4]) if len(sys.argv) > 4 else None
        print(desktop_move(x, y, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd == "type":
        if len(sys.argv) < 4:
            print("Error: hwnd and text required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        text = sys.argv[3]
        print(type_text(hwnd, text))

    # ------------------------------------------------------------------
    elif cmd == "key":
        if len(sys.argv) < 4:
            print("Error: hwnd and keys required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        keys = sys.argv[3]
        print(press_key(hwnd, keys))

    # ------------------------------------------------------------------
    elif cmd == "scroll":
        if len(sys.argv) < 6:
            print("Error: hwnd, x, y, dy required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x, y, dy = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
        screenshot_id = int(sys.argv[6]) if len(sys.argv) > 6 else None
        print(scroll(hwnd, x, y, dy, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-scroll", "desktop_scroll"):
        if len(sys.argv) < 5:
            print("Error: x, y, dy required")
            sys.exit(1)
        x, y, dy = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
        screenshot_id = int(sys.argv[5]) if len(sys.argv) > 5 else None
        print(desktop_scroll(x, y, dy, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd == "drag":
        if len(sys.argv) < 7:
            print("Error: hwnd, x1, y1, x2, y2 required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        x1, y1 = int(sys.argv[3]), int(sys.argv[4])
        x2, y2 = int(sys.argv[5]), int(sys.argv[6])
        screenshot_id = int(sys.argv[7]) if len(sys.argv) > 7 else None
        print(drag(hwnd, x1, y1, x2, y2, 0.5, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd in ("desktop-drag", "desktop_drag"):
        if len(sys.argv) < 6:
            print("Error: x1, y1, x2, y2 required")
            sys.exit(1)
        x1, y1 = int(sys.argv[2]), int(sys.argv[3])
        x2, y2 = int(sys.argv[4]), int(sys.argv[5])
        screenshot_id = int(sys.argv[6]) if len(sys.argv) > 6 else None
        print(desktop_drag(x1, y1, x2, y2, 0.5, screenshot_id))

    # ------------------------------------------------------------------
    elif cmd == "activate":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        boundary_result = _elevated_helper_required_result(hwnd, "/activate")
        if boundary_result is not None:
            print(json.dumps(boundary_result, ensure_ascii=False))
            sys.exit(0)
        if activate_window(hwnd):
            print(f"Activated window {hwnd}")
        else:
            print(f"Failed to activate window {hwnd}")

    # ------------------------------------------------------------------
    elif cmd == "list_apps":
        result = list_apps()
        if isinstance(result, dict) and "error" in result:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    elif cmd == "screenshot_b64":
        if len(sys.argv) < 3:
            print("Error: hwnd required")
            sys.exit(1)
        hwnd = int(sys.argv[2])
        args = sys.argv[3:]
        max_w = 1280
        capture_mode = "auto"
        if args and not args[0].startswith("--"):
            max_w = int(args[0])
            args = args[1:]
        i = 0
        while i < len(args):
            if args[i] == "--max-width" and i + 1 < len(args):
                max_w = int(args[i + 1])
                i += 2
            elif args[i] in ("--capture-mode", "--capture") and i + 1 < len(args):
                capture_mode = args[i + 1]
                i += 2
            else:
                i += 1
        helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/screenshot_b64")
        if helper_ready and str(capture_mode or "auto").strip().lower().replace("-", "_") == "auto":
            result = _helper_get(f"/screenshot_b64?hwnd={hwnd}&max_width={max_w}", elevated=helper_elevated)
        else:
            # Fallback: capture locally and convert
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            result = screenshot(hwnd, tmp_path, max_w, capture_mode=capture_mode)
            if "error" not in result:
                with open(tmp_path, "rb") as f:
                    png_data = f.read()
                import base64 as _b64
                result = {
                    "text": "Captured window screenshot.",
                    "base64": _b64.b64encode(png_data).decode("ascii"),
                    "width": result["width"],
                    "height": result["height"],
                    "dpi_scale": result.get("dpi_scale", 1.0),
                    "capture_mode": result.get("capture_mode"),
                    "capture_method": result.get("capture_method"),
                }
                os.unlink(tmp_path)
        print(json.dumps(result, ensure_ascii=False))

    # ------------------------------------------------------------------
    elif cmd == "state":
        if len(sys.argv) < 3:
            print("Error: state subcommand required (get/set/target)")
            sys.exit(1)
        subcmd = sys.argv[2]
        if subcmd == "get":
            key = sys.argv[3] if len(sys.argv) > 3 else None
            result = get_state_value(key)
            print(json.dumps(result, ensure_ascii=False))
        elif subcmd == "set":
            if len(sys.argv) < 5:
                print("Error: state set requires <key> <value>")
                sys.exit(1)
            key = sys.argv[3]
            value = sys.argv[4]
            result = set_state_value(key, value)
            print(json.dumps(result, ensure_ascii=False))
        elif subcmd == "target":
            if len(sys.argv) < 4:
                print("Error: state target requires <hwnd>")
                sys.exit(1)
            target_hwnd = int(sys.argv[3])
            result = set_target_hwnd(target_hwnd)
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Error: Unknown state subcommand '{subcmd}'")
            sys.exit(1)

    # ------------------------------------------------------------------
    elif cmd == "batch":
        if len(sys.argv) < 3:
            print("Error: batch requires JSON command list")
            sys.exit(1)
        stop_on_error = "--stop-on-error" in sys.argv[3:] or "--stop_on_error" in sys.argv[3:]
        confirmed = "--confirmed" in sys.argv[3:]
        trace = "--trace" in sys.argv[3:]
        auto_repair_diagnostics = "--auto-repair-diagnostics" in sys.argv[3:] or "--auto_repair_diagnostics" in sys.argv[3:] or "--diagnostic-repair" in sys.argv[3:]
        diagnostic_repair_retry = "--diagnostic-repair-retry" in sys.argv[3:] or "--diagnostic_repair_retry" in sys.argv[3:] or "--auto-repair-retry" in sys.argv[3:] or "--retry-after-repair" in sys.argv[3:]
        diagnostic_repair_rebind_retry = "--diagnostic-repair-rebind-retry" in sys.argv[3:] or "--diagnostic_repair_rebind_retry" in sys.argv[3:] or "--rebind-retry-after-repair" in sys.argv[3:] or "--repair-rebind-retry" in sys.argv[3:]
        timeout_budget = None
        repair_limit = None
        diagnostic_repair_retry_limit = None
        diagnostic_repair_rebind_retry_limit = None
        repair_context = None
        for flag in ("--timeout-budget", "--timeout_budget"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    timeout_budget = float(sys.argv[flag_index + 1])
        for flag in ("--repair-limit", "--repair_limit", "--diagnostic-repair-limit"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    repair_limit = int(sys.argv[flag_index + 1])
        for flag in ("--diagnostic-repair-retry-limit", "--diagnostic_repair_retry_limit", "--repair-retry-limit"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    diagnostic_repair_retry_limit = int(sys.argv[flag_index + 1])
        for flag in ("--diagnostic-repair-rebind-retry-limit", "--diagnostic_repair_rebind_retry_limit", "--rebind-retry-limit", "--repair-rebind-retry-limit"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    diagnostic_repair_rebind_retry_limit = int(sys.argv[flag_index + 1])
        for flag in ("--repair-context", "--repair_context", "--diagnostic-repair-context"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    try:
                        repair_context = json.loads(sys.argv[flag_index + 1])
                    except json.JSONDecodeError as e:
                        print(f"Error: Invalid repair context JSON: {e}")
                        sys.exit(1)
        try:
            payload = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON: {e}")
            sys.exit(1)
        commands, options, payload_error = _batch_payload_parts(payload)
        if payload_error:
            print(json.dumps(payload_error, ensure_ascii=False, indent=2))
            sys.exit(1)
        options["stop_on_error"] = _batch_stop_on_error_option(options, stop_on_error)
        if confirmed:
            options["confirmed"] = True
        if timeout_budget is not None:
            options["timeout_budget"] = timeout_budget
        if trace:
            options["trace"] = True
        if auto_repair_diagnostics:
            options["auto_repair_diagnostics"] = True
        if diagnostic_repair_retry:
            options["diagnostic_repair_retry"] = True
        if diagnostic_repair_rebind_retry:
            options["diagnostic_repair_rebind_retry"] = True
        if repair_limit is not None:
            options["repair_limit"] = repair_limit
        if diagnostic_repair_retry_limit is not None:
            options["diagnostic_repair_retry_limit"] = diagnostic_repair_retry_limit
        if diagnostic_repair_rebind_retry_limit is not None:
            options["diagnostic_repair_rebind_retry_limit"] = diagnostic_repair_rebind_retry_limit
        if repair_context is not None:
            options["repair_context"] = repair_context
        print(json.dumps(
            execute_batch(commands, stop_on_error=_batch_stop_on_error_option(options), **_batch_execute_options(options)),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "batch-file":
        if len(sys.argv) < 3:
            print("Error: batch-file requires path to JSON file")
            sys.exit(1)
        stop_on_error = "--stop-on-error" in sys.argv[3:] or "--stop_on_error" in sys.argv[3:]
        confirmed = "--confirmed" in sys.argv[3:]
        trace = "--trace" in sys.argv[3:]
        auto_repair_diagnostics = "--auto-repair-diagnostics" in sys.argv[3:] or "--auto_repair_diagnostics" in sys.argv[3:] or "--diagnostic-repair" in sys.argv[3:]
        diagnostic_repair_retry = "--diagnostic-repair-retry" in sys.argv[3:] or "--diagnostic_repair_retry" in sys.argv[3:] or "--auto-repair-retry" in sys.argv[3:] or "--retry-after-repair" in sys.argv[3:]
        diagnostic_repair_rebind_retry = "--diagnostic-repair-rebind-retry" in sys.argv[3:] or "--diagnostic_repair_rebind_retry" in sys.argv[3:] or "--rebind-retry-after-repair" in sys.argv[3:] or "--repair-rebind-retry" in sys.argv[3:]
        timeout_budget = None
        repair_limit = None
        diagnostic_repair_retry_limit = None
        diagnostic_repair_rebind_retry_limit = None
        repair_context = None
        for flag in ("--timeout-budget", "--timeout_budget"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    timeout_budget = float(sys.argv[flag_index + 1])
        for flag in ("--repair-limit", "--repair_limit", "--diagnostic-repair-limit"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    repair_limit = int(sys.argv[flag_index + 1])
        for flag in ("--diagnostic-repair-retry-limit", "--diagnostic_repair_retry_limit", "--repair-retry-limit"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    diagnostic_repair_retry_limit = int(sys.argv[flag_index + 1])
        for flag in ("--diagnostic-repair-rebind-retry-limit", "--diagnostic_repair_rebind_retry_limit", "--rebind-retry-limit", "--repair-rebind-retry-limit"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    diagnostic_repair_rebind_retry_limit = int(sys.argv[flag_index + 1])
        for flag in ("--repair-context", "--repair_context", "--diagnostic-repair-context"):
            if flag in sys.argv[3:]:
                flag_index = sys.argv.index(flag)
                if flag_index + 1 < len(sys.argv):
                    try:
                        repair_context = json.loads(sys.argv[flag_index + 1])
                    except json.JSONDecodeError as e:
                        print(f"Error: Invalid repair context JSON: {e}")
                        sys.exit(1)
        try:
            with open(sys.argv[2], "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"Error: Could not read batch file: {e}")
            sys.exit(1)
        commands, options, payload_error = _batch_payload_parts(payload)
        if payload_error:
            print(json.dumps(payload_error, ensure_ascii=False, indent=2))
            sys.exit(1)
        options["stop_on_error"] = _batch_stop_on_error_option(options, stop_on_error)
        if confirmed:
            options["confirmed"] = True
        if timeout_budget is not None:
            options["timeout_budget"] = timeout_budget
        if trace:
            options["trace"] = True
        if auto_repair_diagnostics:
            options["auto_repair_diagnostics"] = True
        if diagnostic_repair_retry:
            options["diagnostic_repair_retry"] = True
        if diagnostic_repair_rebind_retry:
            options["diagnostic_repair_rebind_retry"] = True
        if repair_limit is not None:
            options["repair_limit"] = repair_limit
        if diagnostic_repair_retry_limit is not None:
            options["diagnostic_repair_retry_limit"] = diagnostic_repair_retry_limit
        if diagnostic_repair_rebind_retry_limit is not None:
            options["diagnostic_repair_rebind_retry_limit"] = diagnostic_repair_rebind_retry_limit
        if repair_context is not None:
            options["repair_context"] = repair_context
        print(json.dumps(
            execute_batch(commands, stop_on_error=_batch_stop_on_error_option(options), **_batch_execute_options(options)),
            ensure_ascii=False,
            indent=2,
        ))

    # ------------------------------------------------------------------
    elif cmd == "confirm":
        if len(sys.argv) < 3:
            print("Error: confirm requires <action>")
            sys.exit(1)
        action = sys.argv[2]
        result = check_safety(action)
        print(json.dumps(result, ensure_ascii=False))

    # ------------------------------------------------------------------
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()

