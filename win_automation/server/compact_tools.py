"""
Compact Profile definitions and tool implementations for win-automation-mcp.
Exposes 9 composite high-intent tools with under 35,000 serialized characters schema size:
1. observe_window
2. act
3. type_input
4. key_press
5. wait_state
6. execute_batch
7. check_safety
8. launch_app
9. doctor
"""

from __future__ import annotations

import os
import sys
import json
import time
import subprocess
from typing import Any, Dict, List, Optional, Union

from win_automation.safety.gate import check_safety as _check_safety_func
from win_automation.state.persistence import load_state, save_state, resolve_target_hwnd
from win_automation.diagnostics.doctor import doctor as _doctor_func
from win_automation.batch.engine import execute_batch as _execute_batch_func
from win_automation.input.smart_input import (
    smart_click,
    smart_text_input,
    smart_select,
    smart_cell,
)
from win_automation.input.keyboard import press_key as _press_key_func
from win_automation.input.mouse import (
    click as _mouse_click,
    scroll as _mouse_scroll,
    drag as _mouse_drag,
)
from win_automation.vision.capture import observe_window as _observe_window_func
from win_automation.uia import find_elements as _uia_find

COMPACT_TOOLS = [
    "observe_window",
    "act",
    "type_input",
    "key_press",
    "wait_state",
    "execute_batch",
    "check_safety",
    "launch_app",
    "doctor",
]

COMPACT_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "observe_window": {
        "name": "observe_window",
        "description": "Capture multimodal window state: visual screenshot, UI element tree, and in-memory OCR bounding boxes.",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "Target window handle (0 for active/foreground window)"},
                "include_screenshot": {"type": "boolean", "default": True, "description": "Include base64 PNG screenshot"},
                "include_tree": {"type": "boolean", "default": True, "description": "Include UIA control hierarchy tree"},
                "include_ocr": {"type": "boolean", "default": False, "description": "Include in-memory Windows Media OCR word rects"},
                "max_width": {"type": "integer", "default": 1280, "description": "Max width for screenshot downscaling"},
            },
            "required": [],
        },
    },
    "act": {
        "name": "act",
        "description": "Unified interaction tool replacing 10 low-level mouse/keyboard tools with intent-driven actions.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["click", "double_click", "right_click", "hover", "context_menu", "select", "toggle", "scroll", "drag", "invoke"],
                    "description": "Interaction intent",
                },
                "hwnd": {"type": "integer", "description": "Target window handle"},
                "element_id": {"type": "string", "description": "UIA AutomationId, Name, or control identifier"},
                "text": {"type": "string", "description": "OCR text match target"},
                "x": {"type": "integer", "description": "Window-relative X coordinate"},
                "y": {"type": "integer", "description": "Window-relative Y coordinate"},
                "scroll_amount": {"type": "integer", "description": "Scroll wheel delta"},
                "drag_to_x": {"type": "integer", "description": "Target X for drag action"},
                "drag_to_y": {"type": "integer", "description": "Target Y for drag action"},
            },
            "required": ["action"],
        },
    },
    "type_input": {
        "name": "type_input",
        "description": "Smart text entry with 3-tier fallback ladder (ValuePattern -> WM_SETTEXT -> SendInput) and clipboard auto-switch.",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "Target window handle"},
                "element_id": {"type": "string", "description": "Target UI element identifier"},
                "text": {"type": "string", "description": "Text content to enter"},
                "mode": {"type": "string", "enum": ["auto", "direct", "type", "paste"], "default": "auto"},
                "clear_first": {"type": "boolean", "default": False},
                "press_enter": {"type": "boolean", "default": False},
            },
            "required": ["text"],
        },
    },
    "key_press": {
        "name": "key_press",
        "description": "Send keyboard shortcuts, functional keys, and key combinations safely.",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {"type": "string", "description": "Key combinations, e.g., 'ctrl+s', 'alt+f4', 'enter'"},
                "hwnd": {"type": "integer", "description": "Target window handle"},
            },
            "required": ["keys"],
        },
    },
    "wait_state": {
        "name": "wait_state",
        "description": "Smart synchronization waiting for UI state conditions rather than fixed sleep durations.",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "Window handle to observe"},
                "condition": {
                    "type": "string",
                    "enum": ["window_exists", "window_gone", "element_visible", "text_visible", "visual_stable"],
                    "description": "Condition to wait for",
                },
                "target": {"type": "string", "description": "Element ID, title substring, or OCR text"},
                "timeout_ms": {"type": "integer", "default": 5000, "description": "Max timeout in milliseconds"},
                "poll_interval_ms": {"type": "integer", "default": 200, "description": "Polling interval"},
            },
            "required": ["condition"],
        },
    },
    "execute_batch": {
        "name": "execute_batch",
        "description": "Atomic multi-step action execution within a single tool call with safety gating verification.",
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Ordered list of tool action dicts to execute sequentially",
                },
                "stop_on_failure": {"type": "boolean", "default": True},
            },
            "required": ["steps"],
        },
    },
    "check_safety": {
        "name": "check_safety",
        "description": "Safety gate classifier validating commands against dangerous patterns (Chinese and English).",
        "parameters": {
            "type": "object",
            "properties": {
                "action_description": {"type": "string", "description": "Command or operation description to evaluate"},
            },
            "required": ["action_description"],
        },
    },
    "launch_app": {
        "name": "launch_app",
        "description": "Launch desktop application or document with DPI awareness and initial state readiness tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "path_or_name": {"type": "string", "description": "Application executable path or standard alias (e.g. 'notepad')"},
                "args": {"type": "array", "items": {"type": "string"}, "default": []},
                "working_dir": {"type": "string", "description": "Working directory for spawned process"},
            },
            "required": ["path_or_name"],
        },
    },
    "doctor": {
        "name": "doctor",
        "description": "Self-diagnostics and capability inspector (display count, DPI scale, DXCam, Windows Media OCR).",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "Optional window handle to probe"},
                "detailed": {"type": "boolean", "default": False, "description": "Include extended selftest checks"},
            },
            "required": [],
        },
    },

}


def get_compact_tool_schemas() -> Dict[str, Dict[str, Any]]:
    """Return a dictionary of the 9 compact tool schemas."""
    return dict(COMPACT_TOOL_SCHEMAS)


def calculate_serialized_schema_size(schemas: Dict[str, Dict[str, Any]]) -> int:
    """Calculate minified JSON serialized character length of tool schemas."""
    return len(json.dumps(schemas, separators=(",", ":")))


def compact_observe_window(
    hwnd: int = 0,
    include_screenshot: bool = True,
    include_tree: bool = True,
    include_ocr: bool = False,
    max_width: int = 1280,
) -> Dict[str, Any]:
    """Capture multimodal window state."""
    target_hwnd = resolve_target_hwnd(hwnd if hwnd != 0 else None) or hwnd
    return _observe_window_func(
        hwnd=target_hwnd,
        include_screenshot=include_screenshot,
        include_tree=include_tree,
        include_ocr=include_ocr,
        max_width=max_width,
    )


def compact_act(
    action: str,
    hwnd: Optional[int] = None,
    element_id: Optional[str] = None,
    text: Optional[str] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    scroll_amount: Optional[int] = None,
    drag_to_x: Optional[int] = None,
    drag_to_y: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Unified interaction router cascading through UIA -> Win32 -> OCR -> Coordinate fallback.
    Supports click, double_click, right_click, scroll, and drag.
    """
    act_norm = str(action or "click").strip().lower()
    target_hwnd = resolve_target_hwnd(hwnd)

    if act_norm in ("click", "invoke", "toggle", "select", "double_click", "right_click", "context_menu"):
        button = "right" if act_norm in ("right_click", "context_menu") else "left"
        clicks = 2 if act_norm == "double_click" else 1
        target_name = element_id or text

        # 1. Try UIA & Win32 native actions via smart_click if semantic selector is provided
        if target_name:
            try:
                res = smart_click(
                    hwnd=target_hwnd or 0,
                    name=target_name,
                    button=button,
                    clicks=clicks,
                )
                if res and res.get("ok"):
                    return res
            except Exception:
                pass

            # 2. Try OCR fallback if text is provided
            if text:
                try:
                    from win_automation.ocr.finder import ocr_click
                    ocr_res = ocr_click(hwnd=target_hwnd or 0, text=text, button=button)
                    if ocr_res and ocr_res.get("ok"):
                        if clicks == 2:
                            # Double click the recognized coordinate
                            matched_rect = ocr_res.get("rect") or {}
                            cx = matched_rect.get("center_x") or (matched_rect.get("left", 0) + matched_rect.get("width", 0) // 2)
                            cy = matched_rect.get("center_y") or (matched_rect.get("top", 0) + matched_rect.get("height", 0) // 2)
                            return _mouse_click(int(cx), int(cy), hwnd=target_hwnd, button=button, clicks=2)
                        return ocr_res
                except Exception:
                    pass

        # 3. Try coordinate fallback if coordinates provided
        if x is not None and y is not None:
            return _mouse_click(int(x), int(y), hwnd=target_hwnd, button=button, clicks=clicks)

        if target_name:
            return {
                "ok": False,
                "error": f"Target '{target_name}' not found via UIA, Win32, or OCR",
                "action": action,
            }

        return {
            "ok": False,
            "error": f"act '{action}' requires element_id, text, or coordinates (x, y)",
            "action": action,
        }

    elif act_norm == "scroll":
        delta = int(scroll_amount if scroll_amount is not None else 3)
        return _mouse_scroll(int(x or 0), int(y or 0), delta, hwnd=target_hwnd)

    elif act_norm == "drag":
        if x is not None and y is not None and drag_to_x is not None and drag_to_y is not None:
            return _mouse_drag(int(x), int(y), int(drag_to_x), int(drag_to_y), hwnd=target_hwnd)
        return {"ok": False, "error": "drag requires x, y, drag_to_x, drag_to_y"}

    return {"ok": False, "error": f"Unsupported act action '{action}'"}


def compact_type_input(
    text: str,
    hwnd: Optional[int] = None,
    element_id: Optional[str] = None,
    mode: str = "auto",
    clear_first: bool = False,
    press_enter: bool = False,
) -> Dict[str, Any]:
    """Smart text input with 3-tier fallback."""
    target_hwnd = resolve_target_hwnd(hwnd)
    return smart_text_input(
        hwnd=target_hwnd or 0,
        text=text,
        name=element_id,
        mode=mode,
        clear_first=clear_first,
        press_enter=press_enter,
    )


def compact_key_press(keys: str, hwnd: Optional[int] = None) -> Dict[str, Any]:
    """Send key combination or shortcut."""
    target_hwnd = resolve_target_hwnd(hwnd)
    return _press_key_func(keys, hwnd=target_hwnd)


def compact_wait_state(
    condition: str,
    hwnd: Optional[int] = None,
    target: Optional[str] = None,
    timeout_ms: int = 5000,
    poll_interval_ms: int = 200,
) -> Dict[str, Any]:
    """Wait for state condition."""
    target_hwnd = resolve_target_hwnd(hwnd)
    deadline = time.time() + (timeout_ms / 1000.0)
    interval = max(poll_interval_ms / 1000.0, 0.05)

    while time.time() < deadline:
        if condition == "window_exists":
            from win_automation.win32.window import find_window
            found = find_window(title_substring=target or "")
            if found.get("hwnd"):
                return {"ok": True, "condition": condition, "matched": True, "window": found}
        elif condition == "window_gone":
            from win_automation.win32.window import find_window
            found = find_window(title_substring=target or "")
            if not found.get("hwnd"):
                return {"ok": True, "condition": condition, "matched": True}
        time.sleep(interval)

    return {"ok": False, "condition": condition, "timeout": True, "message": f"Timeout waiting for {condition}"}


def compact_execute_batch(steps: List[Dict[str, Any]], stop_on_failure: bool = True) -> Dict[str, Any]:
    """Execute batch of commands sequentially."""
    return _execute_batch_func(steps, stop_on_error=stop_on_failure)


def compact_check_safety(action_description: str) -> Dict[str, Any]:
    """Bilingual safety gate verification."""
    return _check_safety_func(action_description)


def compact_launch_app(
    path_or_name: str,
    args: Optional[List[str]] = None,
    working_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Launch application or document."""
    try:
        cmd = [path_or_name] + (args or [])
        proc = subprocess.Popen(
            cmd,
            cwd=working_dir,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        return {"ok": True, "pid": proc.pid, "path": path_or_name}
    except Exception as e:
        return {"ok": False, "error": str(e), "path": path_or_name}


def compact_doctor(hwnd: Optional[int] = None, detailed: bool = False) -> Dict[str, Any]:
    """Environment and diagnostics self-check."""
    return _doctor_func(hwnd=hwnd, detailed=detailed)



def register_compact_tools(app: Any) -> None:
    """Register the 9 high-intent compact tools with FastMCP."""
    if app is None:
        return

    @app.tool(name="observe_window", description=COMPACT_TOOL_SCHEMAS["observe_window"]["description"])
    def observe_window(
        hwnd: int = 0,
        include_screenshot: bool = True,
        include_tree: bool = True,
        include_ocr: bool = False,
        max_width: int = 1280,
    ) -> str:
        res = compact_observe_window(hwnd, include_screenshot, include_tree, include_ocr, max_width)
        return json.dumps(res, ensure_ascii=False)

    @app.tool(name="act", description=COMPACT_TOOL_SCHEMAS["act"]["description"])
    def act(
        action: str,
        hwnd: Optional[int] = None,
        element_id: Optional[str] = None,
        text: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        scroll_amount: Optional[int] = None,
        drag_to_x: Optional[int] = None,
        drag_to_y: Optional[int] = None,
    ) -> str:
        res = compact_act(action, hwnd, element_id, text, x, y, scroll_amount, drag_to_x, drag_to_y)
        return json.dumps(res, ensure_ascii=False)

    @app.tool(name="type_input", description=COMPACT_TOOL_SCHEMAS["type_input"]["description"])
    def type_input(
        text: str,
        hwnd: Optional[int] = None,
        element_id: Optional[str] = None,
        mode: str = "auto",
        clear_first: bool = False,
        press_enter: bool = False,
    ) -> str:
        res = compact_type_input(text, hwnd, element_id, mode, clear_first, press_enter)
        return json.dumps(res, ensure_ascii=False)

    @app.tool(name="key_press", description=COMPACT_TOOL_SCHEMAS["key_press"]["description"])
    def key_press(keys: str, hwnd: Optional[int] = None) -> str:
        res = compact_key_press(keys, hwnd)
        return json.dumps(res, ensure_ascii=False)

    @app.tool(name="wait_state", description=COMPACT_TOOL_SCHEMAS["wait_state"]["description"])
    def wait_state(
        condition: str,
        hwnd: Optional[int] = None,
        target: Optional[str] = None,
        timeout_ms: int = 5000,
        poll_interval_ms: int = 200,
    ) -> str:
        res = compact_wait_state(condition, hwnd, target, timeout_ms, poll_interval_ms)
        return json.dumps(res, ensure_ascii=False)

    @app.tool(name="execute_batch", description=COMPACT_TOOL_SCHEMAS["execute_batch"]["description"])
    def execute_batch(steps: List[Dict[str, Any]], stop_on_failure: bool = True) -> str:
        res = compact_execute_batch(steps, stop_on_failure)
        return json.dumps(res, ensure_ascii=False)

    @app.tool(name="check_safety", description=COMPACT_TOOL_SCHEMAS["check_safety"]["description"])
    def check_safety(action_description: str) -> str:
        res = compact_check_safety(action_description)
        return json.dumps(res, ensure_ascii=False)

    @app.tool(name="launch_app", description=COMPACT_TOOL_SCHEMAS["launch_app"]["description"])
    def launch_app(
        path_or_name: str,
        args: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
    ) -> str:
        res = compact_launch_app(path_or_name, args, working_dir)
        return json.dumps(res, ensure_ascii=False)

    @app.tool(name="doctor", description=COMPACT_TOOL_SCHEMAS["doctor"]["description"])
    def doctor(hwnd: Optional[int] = None, detailed: bool = False) -> str:
        res = compact_doctor(hwnd=hwnd, detailed=detailed)
        return json.dumps(res, ensure_ascii=False)

