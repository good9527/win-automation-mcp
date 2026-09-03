"""
Expert Profile tool registration for win-automation-mcp.
Preserves all 111 granular tools for backward compatibility with legacy workflows.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import win_automation
from win_automation.core.win32_structures import *
from win_automation.core.types import Point, Rect, WinAutomationError
from win_automation.win32 import *
from win_automation.uia import *
from win_automation.msaa.accessible import *
from win_automation.input import *
from win_automation.vision import *
from win_automation.ocr import *
from win_automation.safety import check_safety
from win_automation.state.persistence import load_state, save_state, get_state_value, set_state_value, set_target_hwnd, resolve_target_hwnd
from win_automation.diagnostics import doctor, selftest
from win_automation.batch import execute_batch
from win_automation.helper.client import ensure_helper, helper_status


def register_expert_tools(app: Any) -> None:
    """Register all 111 granular tools on FastMCP server."""
    if app is None:
        return

    @app.tool(name="list_apps", description="List running applications with their visible windows.")
    def tool_list_apps() -> Any:
        """List running applications with their visible windows."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "list_apps", None)
            if func is not None and callable(func):
                res = func()
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function list_apps not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "list_apps"}

    @app.tool(name="list_windows", description="List all open visible windows.")
    def tool_list_windows() -> Any:
        """List all open visible windows."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "list_windows", None)
            if func is not None and callable(func):
                res = func()
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function list_windows not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "list_windows"}

    @app.tool(name="execute_batch", description="Execute mixed automation commands in one MCP call using the same batch engine as the CLI.")
    def tool_execute_batch(commands: Any, stop_on_error: bool = False, confirmed: bool = False, timeout: float = 60.0, timeout_budget: Optional[float] = None, trace: bool = False, on_failure: Any = None, finally_steps: Any = None, auto_repair_diagnostics: bool = False, repair_context: Any = None, repair_limit: Optional[int] = None, diagnostic_repair_retry: bool = False, diagnostic_repair_retry_limit: Optional[int] = None, diagnostic_repair_rebind_retry: bool = False, diagnostic_repair_rebind_retry_limit: Optional[int] = None) -> Any:
        """Execute mixed automation commands in one MCP call using the same batch engine as the CLI."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "execute_batch", None)
            if func is not None and callable(func):
                res = func(commands=commands, stop_on_error=stop_on_error, confirmed=confirmed, timeout=timeout, timeout_budget=timeout_budget, trace=trace, on_failure=on_failure, finally_steps=finally_steps, auto_repair_diagnostics=auto_repair_diagnostics, repair_context=repair_context, repair_limit=repair_limit, diagnostic_repair_retry=diagnostic_repair_retry, diagnostic_repair_retry_limit=diagnostic_repair_retry_limit, diagnostic_repair_rebind_retry=diagnostic_repair_rebind_retry, diagnostic_repair_rebind_retry_limit=diagnostic_repair_rebind_retry_limit)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function execute_batch not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "execute_batch"}

    @app.tool(name="selftest_batch", description="Run the no-desktop batch contract selftest through the MCP batch backend.")
    def tool_selftest_batch(timeout: float = 5.0) -> Any:
        """Run the no-desktop batch contract selftest through the MCP batch backend."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "selftest_batch", None)
            if func is not None and callable(func):
                res = func(timeout=timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function selftest_batch not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "selftest_batch"}

    @app.tool(name="selftest_server_contracts", description="Run no-desktop MCP server contract tests for internal UIA index lifecycle behavior.")
    def tool_selftest_server_contracts() -> Any:
        """Run no-desktop MCP server contract tests for internal UIA index lifecycle behavior."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "selftest_server_contracts", None)
            if func is not None and callable(func):
                res = func()
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function selftest_server_contracts not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "selftest_server_contracts"}

    @app.tool(name="get_window", description="Get information about a specific window by HWND.")
    def tool_get_window(hwnd: Optional[int] = None) -> Any:
        """Get information about a specific window by HWND."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "get_window", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function get_window not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "get_window"}

    @app.tool(name="foreground_window", description="Return the current foreground window metadata.")
    def tool_foreground_window() -> Any:
        """Return the current foreground window metadata."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "foreground_window", None)
            if func is not None and callable(func):
                res = func()
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function foreground_window not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "foreground_window"}

    @app.tool(name="control_boundary", description="Diagnose integrity, UIPI, UIAccess, elevation, and desktop boundaries for a target HWND.")
    def tool_control_boundary(hwnd: Optional[int] = None) -> Any:
        """Diagnose integrity, UIPI, UIAccess, elevation, and desktop boundaries for a target HWND."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "control_boundary", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function control_boundary not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "control_boundary"}

    @app.tool(name="helper_status", description="Inspect or start the resident input/screenshot helper used by MCP tools.")
    def tool_helper_status(restart: bool = False, elevated: bool = False, start: bool = False) -> Any:
        """Inspect or start the resident input/screenshot helper used by MCP tools."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "helper_status", None)
            if func is not None and callable(func):
                res = func(restart=restart, elevated=elevated, start=start)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function helper_status not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "helper_status"}

    @app.tool(name="gui_thread_info", description="Inspect the active/focus/capture/menu/move-size/caret HWNDs for a GUI thread.")
    def tool_gui_thread_info(hwnd: Optional[int] = None, thread_id: Optional[int] = None) -> Any:
        """Inspect the active/focus/capture/menu/move-size/caret HWNDs for a GUI thread."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "gui_thread_info", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, thread_id=thread_id)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function gui_thread_info not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "gui_thread_info"}

    @app.tool(name="related_windows", description="Return windows related by PID, owner, or root owner for dialog/popup tracking.")
    def tool_related_windows(hwnd: Optional[int] = None, include_invisible: bool = False) -> Any:
        """Return windows related by PID, owner, or root owner for dialog/popup tracking."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "related_windows", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, include_invisible=include_invisible)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function related_windows not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "related_windows"}

    @app.tool(name="wait_window", description="Wait for a visible top-level window matching title and/or process name/path.")
    def tool_wait_window(hwnd: Optional[int] = None, title: Optional[str] = None, process: Optional[str] = None, pid: Optional[int] = None, timeout: float = 10.0, interval: float = 0.25, match: str = 'contains', stable_ticks: int = 2) -> Any:
        """Wait for a visible top-level window matching title and/or process name/path."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "wait_window", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, title=title, process=process, pid=pid, timeout=timeout, interval=interval, match=match, stable_ticks=stable_ticks)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function wait_window not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "wait_window"}

    @app.tool(name="window_selector_repair_find", description="Repair a failed wait_window selector using failure_summary.selector_suggestions[0].")
    def tool_window_selector_repair_find(suggestion: Optional[dict[str, Any]] = None, original: Optional[dict[str, Any]] = None, timeout: Optional[float] = None, interval: Optional[float] = None, match: Optional[str] = None, stable_ticks: Optional[int] = None, allow_suggestion_hwnd: bool = False, probe_original: bool = True) -> Any:
        """Repair a failed wait_window selector using failure_summary.selector_suggestions[0]."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "window_selector_repair_find", None)
            if func is not None and callable(func):
                res = func(suggestion=suggestion, original=original, timeout=timeout, interval=interval, match=match, stable_ticks=stable_ticks, allow_suggestion_hwnd=allow_suggestion_hwnd, probe_original=probe_original)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function window_selector_repair_find not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "window_selector_repair_find"}

    @app.tool(name="wait_event", description="Wait for native WinEvent notifications such as foreground, dialog/menu, show/hide, focus, selection, name, value, or location changes.")
    def tool_wait_event(event: Optional[str] = None, hwnd: Optional[int] = None, pid: Optional[int] = None, title: Optional[str] = None, class_name: Optional[str] = None, timeout: float = 5.0, limit: int = 1, match: str = 'contains', include_children: bool = True, skip_own_process: bool = True) -> Any:
        """Wait for native WinEvent notifications such as foreground, dialog/menu, show/hide, focus, selection, name, value, or location changes."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "wait_event", None)
            if func is not None and callable(func):
                res = func(event=event, hwnd=hwnd, pid=pid, title=title, class_name=class_name, timeout=timeout, limit=limit, match=match, include_children=include_children, skip_own_process=skip_own_process)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function wait_event not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "wait_event"}

    @app.tool(name="screen_info", description="Return virtual desktop and primary screen metrics.")
    def tool_screen_info() -> Any:
        """Return virtual desktop and primary screen metrics."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "screen_info", None)
            if func is not None and callable(func):
                res = func()
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function screen_info not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "screen_info"}

    @app.tool(name="mouse_position", description="Return current cursor position in screen coordinates.")
    def tool_mouse_position() -> Any:
        """Return current cursor position in screen coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "mouse_position", None)
            if func is not None and callable(func):
                res = func()
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function mouse_position not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "mouse_position"}

    @app.tool(name="mouse_context", description="Inspect HWND/UIA/MSAA context under the cursor or a screen/window screenshot point without clicking.")
    def tool_mouse_context(x: Optional[int] = None, y: Optional[int] = None, hwnd: Optional[int] = None, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None, include_text: bool = False, include_uia: bool = True, include_msaa: bool = True) -> Any:
        """Inspect HWND/UIA/MSAA context under the cursor or a screen/window screenshot point without clicking."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "mouse_context", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, hwnd=hwnd, screenshot_width=screenshot_width, screenshot_height=screenshot_height, include_text=include_text, include_uia=include_uia, include_msaa=include_msaa)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function mouse_context not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "mouse_context"}

    @app.tool(name="desktop_screenshot", description="Capture the full virtual desktop for taskbar, Start menu, tray flyouts, overlays, and UI without a stable HWND.")
    def tool_desktop_screenshot(max_screenshot_width: int = 1600, output_path: Optional[str] = None) -> Any:
        """Capture the full virtual desktop for taskbar, Start menu, tray flyouts, overlays, and UI without a stable HWND."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_screenshot", None)
            if func is not None and callable(func):
                res = func(max_screenshot_width=max_screenshot_width, output_path=output_path)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_screenshot not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_screenshot"}

    @app.tool(name="desktop_point", description="Map a full-desktop screenshot point to physical virtual-screen coordinates.")
    def tool_desktop_point(x: int, y: int, screenshot_id: Optional[int] = None) -> Any:
        """Map a full-desktop screenshot point to physical virtual-screen coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_point", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, screenshot_id=screenshot_id)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_point not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_point"}

    @app.tool(name="desktop_pixel", description="Read one RGB pixel from a full-desktop screenshot.")
    def tool_desktop_pixel(x: int, y: int, screenshot_id: Optional[int] = None) -> Any:
        """Read one RGB pixel from a full-desktop screenshot."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_pixel", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, screenshot_id=screenshot_id)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_pixel not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_pixel"}

    @app.tool(name="desktop_pixel_wait", description="Poll fresh full-desktop screenshots until a pixel matches or stops matching a color.")
    def tool_desktop_pixel_wait(x: int, y: int, color: str, tolerance: float = 0.0, timeout: float = 10.0, interval: float = 0.25, mode: str = 'equals', max_screenshot_width: int = 1600) -> Any:
        """Poll fresh full-desktop screenshots until a pixel matches or stops matching a color."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_pixel_wait", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, color=color, tolerance=tolerance, timeout=timeout, interval=interval, mode=mode, max_screenshot_width=max_screenshot_width)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_pixel_wait not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_pixel_wait"}

    @app.tool(name="desktop_visual_stable_wait", description="Poll fresh full-desktop screenshots until consecutive frames stop changing.")
    def tool_desktop_visual_stable_wait(timeout: float = 5.0, interval: float = 0.25, stable_ticks: int = 2, difference_threshold: float = 0.003, pixel_threshold: float = 8.0, region: Optional[str] = None, max_screenshot_width: int = 1600, comparison_max_width: int = 320) -> Any:
        """Poll fresh full-desktop screenshots until consecutive frames stop changing."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_visual_stable_wait", None)
            if func is not None and callable(func):
                res = func(timeout=timeout, interval=interval, stable_ticks=stable_ticks, difference_threshold=difference_threshold, pixel_threshold=pixel_threshold, region=region, max_screenshot_width=max_screenshot_width, comparison_max_width=comparison_max_width)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_visual_stable_wait not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_visual_stable_wait"}

    @app.tool(name="desktop_uia_stable_wait", description="Poll desktop-root UIA snapshots until the structure signature stops changing.")
    def tool_desktop_uia_stable_wait(timeout: float = 5.0, interval: float = 0.25, stable_ticks: int = 2, max_depth: int = 4, max_elements: int = 500, view: str = 'control', include_values: bool = False, rect_bucket: int = 2) -> Any:
        """Poll desktop-root UIA snapshots until the structure signature stops changing."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_uia_stable_wait", None)
            if func is not None and callable(func):
                res = func(timeout=timeout, interval=interval, stable_ticks=stable_ticks, max_depth=max_depth, max_elements=max_elements, view=view, include_values=include_values, rect_bucket=rect_bucket)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_uia_stable_wait not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_uia_stable_wait"}

    @app.tool(name="desktop_click", description="Click a full-desktop screenshot point, mapped through the virtual desktop bounds.")
    def tool_desktop_click(x: int, y: int, button: str = 'left', clicks: int = 1, screenshot_id: Optional[int] = None) -> Any:
        """Click a full-desktop screenshot point, mapped through the virtual desktop bounds."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_click", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, button=button, clicks=clicks, screenshot_id=screenshot_id)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_click not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_click"}

    @app.tool(name="desktop_move", description="Move the cursor to a full-desktop screenshot point without clicking.")
    def tool_desktop_move(x: int, y: int, screenshot_id: Optional[int] = None, settle: float = 0.05) -> Any:
        """Move the cursor to a full-desktop screenshot point without clicking."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_move", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, screenshot_id=screenshot_id, settle=settle)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_move not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_move"}

    @app.tool(name="desktop_hover", description="Alias for desktop_move; useful for revealing desktop-level hover UI without clicking.")
    def tool_desktop_hover(x: int, y: int, screenshot_id: Optional[int] = None, settle: float = 0.05) -> Any:
        """Alias for desktop_move; useful for revealing desktop-level hover UI without clicking."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_hover", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, screenshot_id=screenshot_id, settle=settle)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_hover not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_hover"}

    @app.tool(name="desktop_scroll", description="Scroll at a full-desktop screenshot point, mapped through the virtual desktop bounds.")
    def tool_desktop_scroll(x: int, y: int, scroll_y: int, screenshot_id: Optional[int] = None) -> Any:
        """Scroll at a full-desktop screenshot point, mapped through the virtual desktop bounds."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_scroll", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, scroll_y=scroll_y, screenshot_id=screenshot_id)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_scroll not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_scroll"}

    @app.tool(name="desktop_drag", description="Drag between two full-desktop screenshot points, mapped through the virtual desktop bounds.")
    def tool_desktop_drag(start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5, screenshot_id: Optional[int] = None) -> Any:
        """Drag between two full-desktop screenshot points, mapped through the virtual desktop bounds."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_drag", None)
            if func is not None and callable(func):
                res = func(start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y, duration=duration, screenshot_id=screenshot_id)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_drag not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_drag"}

    @app.tool(name="desktop_locate_image", description="Locate a template image inside a full virtual desktop screenshot.")
    def tool_desktop_locate_image(template_path: str, confidence: float = 0.85, max_screenshot_width: int = 1600, screenshot_id: Optional[int] = None, region: Optional[str] = None, scale_min: float = 1.0, scale_max: float = 1.0, scale_step: float = 0.0) -> Any:
        """Locate a template image inside a full virtual desktop screenshot."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_locate_image", None)
            if func is not None and callable(func):
                res = func(template_path=template_path, confidence=confidence, max_screenshot_width=max_screenshot_width, screenshot_id=screenshot_id, region=region, scale_min=scale_min, scale_max=scale_max, scale_step=scale_step)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_locate_image not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_locate_image"}

    @app.tool(name="desktop_wait_image", description="Poll full-desktop screenshots until a template image appears.")
    def tool_desktop_wait_image(template_path: str, confidence: float = 0.85, max_screenshot_width: int = 1600, timeout: float = 10.0, interval: float = 0.5, region: Optional[str] = None, scale_min: float = 1.0, scale_max: float = 1.0, scale_step: float = 0.0) -> Any:
        """Poll full-desktop screenshots until a template image appears."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_wait_image", None)
            if func is not None and callable(func):
                res = func(template_path=template_path, confidence=confidence, max_screenshot_width=max_screenshot_width, timeout=timeout, interval=interval, region=region, scale_min=scale_min, scale_max=scale_max, scale_step=scale_step)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_wait_image not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_wait_image"}

    @app.tool(name="desktop_click_image", description="Click the center of a template image match on the full virtual desktop.")
    def tool_desktop_click_image(template_path: str, confidence: float = 0.85, max_screenshot_width: int = 1600, screenshot_id: Optional[int] = None, button: str = 'left', clicks: int = 1, timeout: float = 0.0, interval: float = 0.5, region: Optional[str] = None, scale_min: float = 1.0, scale_max: float = 1.0, scale_step: float = 0.0) -> Any:
        """Click the center of a template image match on the full virtual desktop."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_click_image", None)
            if func is not None and callable(func):
                res = func(template_path=template_path, confidence=confidence, max_screenshot_width=max_screenshot_width, screenshot_id=screenshot_id, button=button, clicks=clicks, timeout=timeout, interval=interval, region=region, scale_min=scale_min, scale_max=scale_max, scale_step=scale_step)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_click_image not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_click_image"}

    @app.tool(name="child_windows", description="Enumerate native Win32 child HWNDs for legacy controls and dialogs.")
    def tool_child_windows(hwnd: Optional[int] = None, include_invisible: bool = False, include_text: bool = False, max_count: int = 500) -> Any:
        """Enumerate native Win32 child HWNDs for legacy controls and dialogs."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "child_windows", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, include_invisible=include_invisible, include_text=include_text, max_count=max_count)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function child_windows not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "child_windows"}

    @app.tool(name="window_from_point", description="Return the top-level and child HWND under a screen or window screenshot point.")
    def tool_window_from_point(x: Optional[int] = None, y: Optional[int] = None, hwnd: Optional[int] = None, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None, include_text: bool = False) -> Any:
        """Return the top-level and child HWND under a screen or window screenshot point."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "window_from_point", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, hwnd=hwnd, screenshot_width=screenshot_width, screenshot_height=screenshot_height, include_text=include_text)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function window_from_point not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "window_from_point"}

    @app.tool(name="element_from_point", description="Return UI Automation metadata for the element under a screen or window screenshot point.")
    def tool_element_from_point(x: Optional[int] = None, y: Optional[int] = None, hwnd: Optional[int] = None, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> Any:
        """Return UI Automation metadata for the element under a screen or window screenshot point."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "element_from_point", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, hwnd=hwnd, screenshot_width=screenshot_width, screenshot_height=screenshot_height)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function element_from_point not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "element_from_point"}

    @app.tool(name="msaa_window", description="Inspect the MSAA/IAccessible client object for a window.")
    def tool_msaa_window(hwnd: Optional[int] = None, max_children: int = 80) -> Any:
        """Inspect the MSAA/IAccessible client object for a window."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "msaa_window", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, max_children=max_children)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function msaa_window not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "msaa_window"}

    @app.tool(name="msaa_from_point", description="Return MSAA/IAccessible metadata under a screen or window screenshot point.")
    def tool_msaa_from_point(x: Optional[int] = None, y: Optional[int] = None, hwnd: Optional[int] = None, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> Any:
        """Return MSAA/IAccessible metadata under a screen or window screenshot point."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "msaa_from_point", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, hwnd=hwnd, screenshot_width=screenshot_width, screenshot_height=screenshot_height)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function msaa_from_point not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "msaa_from_point"}

    @app.tool(name="msaa_action", description="Run an MSAA default/focus/select/set_value action on a window or child path.")
    def tool_msaa_action(hwnd: Optional[int] = None, action: str = 'default', path: Optional[list[int]] = None, child_id: int = MSAA_SELF, value: Optional[str] = None) -> Any:
        """Run an MSAA default/focus/select/set_value action on a window or child path."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "msaa_action", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, action=action, path=path, child_id=child_id, value=value)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function msaa_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "msaa_action"}

    @app.tool(name="menu_tree", description="Inspect the classic Win32 HMENU tree for menu bars and system menus.")
    def tool_menu_tree(hwnd: Optional[int] = None, include_system: bool = False, max_depth: int = 5, max_items: int = 300) -> Any:
        """Inspect the classic Win32 HMENU tree for menu bars and system menus."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "menu_tree", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, include_system=include_system, max_depth=max_depth, max_items=max_items)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function menu_tree not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "menu_tree"}

    @app.tool(name="menu_action", description="Invoke a classic Win32 menu item by path or command id using WM_COMMAND.")
    def tool_menu_action(hwnd: Optional[int] = None, path: Any = None, command_id: Optional[int] = None, include_system: bool = False, async_post: bool = False, timeout_ms: int = 500) -> Any:
        """Invoke a classic Win32 menu item by path or command id using WM_COMMAND."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "menu_action", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, path=path, command_id=command_id, include_system=include_system, async_post=async_post, timeout_ms=timeout_ms)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function menu_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "menu_action"}

    @app.tool(name="win32_text", description="Read text from a native HWND with WM_GETTEXT.")
    def tool_win32_text(hwnd: int, timeout_ms: int = 250) -> Any:
        """Read text from a native HWND with WM_GETTEXT."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_text", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, timeout_ms=timeout_ms)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_text not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_text"}

    @app.tool(name="win32_set_text", description="Set text on a native HWND with WM_SETTEXT.")
    def tool_win32_set_text(hwnd: int, text: str, timeout_ms: int = 500) -> Any:
        """Set text on a native HWND with WM_SETTEXT."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_set_text", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, text=text, timeout_ms=timeout_ms)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_set_text not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_set_text"}

    @app.tool(name="win32_click", description="Click a native button-like HWND using BM_CLICK without relying on coordinates.")
    def tool_win32_click(hwnd: int, timeout_ms: int = 500) -> Any:
        """Click a native button-like HWND using BM_CLICK without relying on coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_click", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, timeout_ms=timeout_ms)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_click not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_click"}

    @app.tool(name="file_dialog_info", description="Inspect the foreground or supplied Windows Open/Save file dialog and locate filename/confirm/cancel controls.")
    def tool_file_dialog_info(hwnd: Optional[int] = None, timeout: float = 0.0, timeout_ms: int = 300, include_children: bool = False) -> Any:
        """Inspect the foreground or supplied Windows Open/Save file dialog and locate filename/confirm/cancel controls."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "file_dialog_info", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, timeout=timeout, timeout_ms=timeout_ms, include_children=include_children)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function file_dialog_info not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "file_dialog_info"}

    @app.tool(name="file_dialog_action", description="Set filename, confirm/open/save/select, or cancel a standard Windows file dialog without coordinate clicking.")
    def tool_file_dialog_action(action: str, hwnd: Optional[int] = None, path: Optional[str] = None, timeout: float = 5.0, timeout_ms: int = 500, verify_close: bool = False) -> Any:
        """Set filename, confirm/open/save/select, or cancel a standard Windows file dialog without coordinate clicking."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "file_dialog_action", None)
            if func is not None and callable(func):
                res = func(action=action, hwnd=hwnd, path=path, timeout=timeout, timeout_ms=timeout_ms, verify_close=verify_close)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function file_dialog_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "file_dialog_action"}

    @app.tool(name="win32_control_find", description="Find native Win32 child controls by text, class, kind, control id, and current state.")
    def tool_win32_control_find(hwnd: int, name: Optional[str] = None, automation_id: Optional[Any] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, text: Optional[str] = None, value: Optional[str] = None, state: Optional[str] = None, expected: Optional[Any] = None, match: str = 'contains', include_invisible: bool = False, include_self: bool = True, limit: int = 20, min_score: Optional[int] = None, timeout_ms: int = 250, max_items: int = 200, max_children: int = 1000, diagnostic: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Find native Win32 child controls by text, class, kind, control id, and current state."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_control_find", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, text=text, value=value, state=state, expected=expected, match=match, include_invisible=include_invisible, include_self=include_self, limit=limit, min_score=min_score, timeout_ms=timeout_ms, max_items=max_items, max_children=max_children, diagnostic=diagnostic, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_control_find not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_control_find"}

    @app.tool(name="win32_selector_repair_find", description="Retry a failed native Win32 control selector using a cleaned selector_suggestions entry.")
    def tool_win32_selector_repair_find(hwnd: int, suggestion: Optional[dict[str, Any]] = None, original: Optional[dict[str, Any]] = None, limit: int = 1, include_invisible: Optional[bool] = None, include_self: Optional[bool] = None, min_score: Optional[int] = None, timeout_ms: Optional[int] = None, max_items: Optional[int] = None, max_children: Optional[int] = None, diagnostic: Optional[bool] = None, allow_suggestion_hwnd: bool = False) -> Any:
        """Retry a failed native Win32 control selector using a cleaned selector_suggestions entry."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_selector_repair_find", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, suggestion=suggestion, original=original, limit=limit, include_invisible=include_invisible, include_self=include_self, min_score=min_score, timeout_ms=timeout_ms, max_items=max_items, max_children=max_children, diagnostic=diagnostic, allow_suggestion_hwnd=allow_suggestion_hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_selector_repair_find not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_selector_repair_find"}

    @app.tool(name="win32_control_wait_find", description="Poll until native Win32 controls matching the selector appear.")
    def tool_win32_control_wait_find(hwnd: int, name: Optional[str] = None, automation_id: Optional[Any] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, text: Optional[str] = None, value: Optional[str] = None, state: Optional[str] = None, expected: Optional[Any] = None, match: str = 'contains', include_invisible: bool = False, include_self: bool = True, limit: int = 20, min_score: Optional[int] = None, timeout: float = 3.0, interval: float = 0.1, timeout_ms: int = 250, max_items: int = 200, max_children: int = 1000, diagnostic: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Poll until native Win32 controls matching the selector appear."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_control_wait_find", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, text=text, value=value, state=state, expected=expected, match=match, include_invisible=include_invisible, include_self=include_self, limit=limit, min_score=min_score, timeout=timeout, interval=interval, timeout_ms=timeout_ms, max_items=max_items, max_children=max_children, diagnostic=diagnostic, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_control_wait_find not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_control_wait_find"}

    @app.tool(name="win32_control_info", description="Inspect common native ComboBox/ComboBoxEx/ListBox/Button state without coordinates.")
    def tool_win32_control_info(hwnd: int, timeout_ms: int = 250, max_items: int = 200) -> Any:
        """Inspect common native ComboBox/ComboBoxEx/ListBox/Button state without coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_control_info", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, timeout_ms=timeout_ms, max_items=max_items)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_control_info not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_control_info"}

    @app.tool(name="win32_control_action", description="Select/check/edit common native ComboBox/ComboBoxEx/ListBox/Button controls without coordinates.")
    def tool_win32_control_action(hwnd: int, action: str, index: Optional[int] = None, text: Optional[str] = None, value: Optional[int] = None, checked: Optional[bool] = None, match: str = 'contains', timeout_ms: int = 500) -> Any:
        """Select/check/edit common native ComboBox/ComboBoxEx/ListBox/Button controls without coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_control_action", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, action=action, index=index, text=text, value=value, checked=checked, match=match, timeout_ms=timeout_ms)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_control_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_control_action"}

    @app.tool(name="win32_control_wait", description="Wait until a native Win32 control/item state matches, optionally retrying exact text waits with conservative diagnostic repair.")
    def tool_win32_control_wait(hwnd: int, state: Optional[str] = None, expected: Optional[Any] = None, index: Optional[int] = None, text: Optional[str] = None, match: str = 'contains', timeout: float = 3.0, interval: float = 0.1, timeout_ms: int = 250, max_items: int = 200, diagnostic: bool = False, repair: Optional[bool] = None, repair_match: Optional[str] = None, repair_timeout: Optional[float] = None) -> Any:
        """Wait until a native Win32 control/item state matches, optionally retrying exact text waits with conservative diagnostic repair."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "win32_control_wait", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, state=state, expected=expected, index=index, text=text, match=match, timeout=timeout, interval=interval, timeout_ms=timeout_ms, max_items=max_items, diagnostic=diagnostic, repair=repair, repair_match=repair_match, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function win32_control_wait not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "win32_control_wait"}

    @app.tool(name="doctor", description="Run a lightweight self-check across window, screenshot, UIA, vision, and input layers.")
    def tool_doctor(hwnd: Optional[int] = None) -> Any:
        """Run a lightweight self-check across window, screenshot, UIA, vision, and input layers."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "doctor", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function doctor not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "doctor"}

    @app.tool(name="launch_app", description="Launch an application by name or path.")
    def tool_launch_app(path_or_name: str, timeout: float = 10.0) -> Any:
        """Launch an application by name or path."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "launch_app", None)
            if func is not None and callable(func):
                res = func(path_or_name=path_or_name, timeout=timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function launch_app not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "launch_app"}

    @app.tool(name="get_window_state", description="Capture the current state of a window.")
    def tool_get_window_state(hwnd: Optional[int] = None, include_screenshot: bool = True, include_accessibility: bool = False, max_screenshot_width: int = 1280, accessibility_view: str = 'raw', capture_mode: str = 'auto') -> Any:
        """Capture the current state of a window."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "get_window_state", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, include_screenshot=include_screenshot, include_accessibility=include_accessibility, max_screenshot_width=max_screenshot_width, accessibility_view=accessibility_view, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function get_window_state not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "get_window_state"}

    @app.tool(name="observe_window", description="Capture a unified point-in-time window observation: metadata, screenshot, UIA summary, and optional OCR fallback.")
    def tool_observe_window(hwnd: Optional[int] = None, include_screenshot: bool = True, include_accessibility: bool = True, include_ocr: bool = False, ocr_on_accessibility_error: bool = True, ocr_engine: str = 'auto', ocr_lang: str = 'eng+chi_sim', max_screenshot_width: int = 1280, max_depth: int = 10, max_elements: int = 500, view: str = 'raw', capture_mode: str = 'auto') -> Any:
        """Capture a unified point-in-time window observation: metadata, screenshot, UIA summary, and optional OCR fallback."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "observe_window", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, include_screenshot=include_screenshot, include_accessibility=include_accessibility, include_ocr=include_ocr, ocr_on_accessibility_error=ocr_on_accessibility_error, ocr_engine=ocr_engine, ocr_lang=ocr_lang, max_screenshot_width=max_screenshot_width, max_depth=max_depth, max_elements=max_elements, view=view, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function observe_window not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "observe_window"}

    @app.tool(name="pixel", description="Read one RGB pixel from a fresh window screenshot at screenshot coordinates.")
    def tool_pixel(hwnd: Optional[int] = None, x: int = 0, y: int = 0, max_screenshot_width: int = 1280, capture_mode: str = 'auto') -> Any:
        """Read one RGB pixel from a fresh window screenshot at screenshot coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "pixel", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, x=x, y=y, max_screenshot_width=max_screenshot_width, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function pixel not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "pixel"}

    @app.tool(name="pixel_wait", description="Poll fresh window screenshots until a pixel matches or stops matching a color.")
    def tool_pixel_wait(hwnd: Optional[int] = None, x: int = 0, y: int = 0, color: str = '', tolerance: float = 0.0, timeout: float = 10.0, interval: float = 0.25, mode: str = 'equals', max_screenshot_width: int = 1280, capture_mode: str = 'auto') -> Any:
        """Poll fresh window screenshots until a pixel matches or stops matching a color."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "pixel_wait", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, x=x, y=y, color=color, tolerance=tolerance, timeout=timeout, interval=interval, mode=mode, max_screenshot_width=max_screenshot_width, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function pixel_wait not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "pixel_wait"}

    @app.tool(name="visual_stable_wait", description="Poll fresh window screenshots until consecutive frames stop changing.")
    def tool_visual_stable_wait(hwnd: Optional[int] = None, timeout: float = 5.0, interval: float = 0.25, stable_ticks: int = 2, difference_threshold: float = 0.003, pixel_threshold: float = 8.0, region: Optional[str] = None, max_screenshot_width: int = 1280, comparison_max_width: int = 320, capture_mode: str = 'auto') -> Any:
        """Poll fresh window screenshots until consecutive frames stop changing."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "visual_stable_wait", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, timeout=timeout, interval=interval, stable_ticks=stable_ticks, difference_threshold=difference_threshold, pixel_threshold=pixel_threshold, region=region, max_screenshot_width=max_screenshot_width, comparison_max_width=comparison_max_width, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function visual_stable_wait not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "visual_stable_wait"}

    @app.tool(name="uia_stable_wait", description="Poll target-window UIA snapshots until the structure signature stops changing.")
    def tool_uia_stable_wait(hwnd: Optional[int] = None, timeout: float = 5.0, interval: float = 0.25, stable_ticks: int = 2, max_depth: int = 10, max_elements: int = 500, view: str = 'control', include_values: bool = False, rect_bucket: int = 2) -> Any:
        """Poll target-window UIA snapshots until the structure signature stops changing."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "uia_stable_wait", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, timeout=timeout, interval=interval, stable_ticks=stable_ticks, max_depth=max_depth, max_elements=max_elements, view=view, include_values=include_values, rect_bucket=rect_bucket)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function uia_stable_wait not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "uia_stable_wait"}

    @app.tool(name="locate_image", description="Locate a template image inside the target window screenshot using OpenCV.")
    def tool_locate_image(template_path: str, hwnd: Optional[int] = None, confidence: float = 0.85, max_screenshot_width: int = 1280, region: Optional[str] = None, scale_min: float = 1.0, scale_max: float = 1.0, scale_step: float = 0.0, capture_mode: str = 'auto') -> Any:
        """Locate a template image inside the target window screenshot using OpenCV."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "locate_image", None)
            if func is not None and callable(func):
                res = func(template_path=template_path, hwnd=hwnd, confidence=confidence, max_screenshot_width=max_screenshot_width, region=region, scale_min=scale_min, scale_max=scale_max, scale_step=scale_step, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function locate_image not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "locate_image"}

    @app.tool(name="wait_image", description="Poll screenshots until a template image appears, returning click-ready coordinates.")
    def tool_wait_image(template_path: str, hwnd: Optional[int] = None, confidence: float = 0.85, max_screenshot_width: int = 1280, timeout: float = 10.0, interval: float = 0.5, region: Optional[str] = None, scale_min: float = 1.0, scale_max: float = 1.0, scale_step: float = 0.0, capture_mode: str = 'auto') -> Any:
        """Poll screenshots until a template image appears, returning click-ready coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "wait_image", None)
            if func is not None and callable(func):
                res = func(template_path=template_path, hwnd=hwnd, confidence=confidence, max_screenshot_width=max_screenshot_width, timeout=timeout, interval=interval, region=region, scale_min=scale_min, scale_max=scale_max, scale_step=scale_step, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function wait_image not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "wait_image"}

    @app.tool(name="click_image", description="Click the center of a template image match, optionally waiting for it first.")
    def tool_click_image(template_path: str, hwnd: Optional[int] = None, confidence: float = 0.85, max_screenshot_width: int = 1280, button: str = 'left', clicks: int = 1, timeout: float = 0.0, interval: float = 0.5, region: Optional[str] = None, scale_min: float = 1.0, scale_max: float = 1.0, scale_step: float = 0.0, capture_mode: str = 'auto') -> Any:
        """Click the center of a template image match, optionally waiting for it first."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "click_image", None)
            if func is not None and callable(func):
                res = func(template_path=template_path, hwnd=hwnd, confidence=confidence, max_screenshot_width=max_screenshot_width, button=button, clicks=clicks, timeout=timeout, interval=interval, region=region, scale_min=scale_min, scale_max=scale_max, scale_step=scale_step, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function click_image not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "click_image"}

    @app.tool(name="visual_row", description="Locate a visible numbered list/table row from OCR row-number anchors.")
    def tool_visual_row(row: int, hwnd: Optional[int] = None, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', row_region: Optional[str] = None, min_row: int = 1, max_row: int = 999, capture_mode: str = 'auto') -> Any:
        """Locate a visible numbered list/table row from OCR row-number anchors."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "visual_row", None)
            if func is not None and callable(func):
                res = func(row=row, hwnd=hwnd, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, row_region=row_region, min_row=min_row, max_row=max_row, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function visual_row not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "visual_row"}

    @app.tool(name="visual_row_click", description="Click a visible numbered list/table row from OCR row-number anchors.")
    def tool_visual_row_click(row: int, hwnd: Optional[int] = None, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', row_region: Optional[str] = None, click_x: Optional[int] = None, x_offset: int = 120, button: str = 'left', clicks: int = 2, min_row: int = 1, max_row: int = 999, capture_mode: str = 'auto') -> Any:
        """Click a visible numbered list/table row from OCR row-number anchors."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "visual_row_click", None)
            if func is not None and callable(func):
                res = func(row=row, hwnd=hwnd, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, row_region=row_region, click_x=click_x, x_offset=x_offset, button=button, clicks=clicks, min_row=min_row, max_row=max_row, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function visual_row_click not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "visual_row_click"}

    @app.tool(name="visual_row_scroll", description="Scroll a visible numbered list/table until row N can be located.")
    def tool_visual_row_scroll(row: int, hwnd: Optional[int] = None, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', row_region: Optional[str] = None, min_row: int = 1, max_row: int = 999, max_scrolls: int = 8, scroll_amount: int = 5, scroll_x: Optional[int] = None, scroll_y: Optional[int] = None, pause: float = 0.35, capture_mode: str = 'auto') -> Any:
        """Scroll a visible numbered list/table until row N can be located."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "visual_row_scroll", None)
            if func is not None and callable(func):
                res = func(row=row, hwnd=hwnd, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, row_region=row_region, min_row=min_row, max_row=max_row, max_scrolls=max_scrolls, scroll_amount=scroll_amount, scroll_x=scroll_x, scroll_y=scroll_y, pause=pause, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function visual_row_scroll not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "visual_row_scroll"}

    @app.tool(name="visual_row_scroll_click", description="Scroll to and click a numbered list/table row.")
    def tool_visual_row_scroll_click(row: int, hwnd: Optional[int] = None, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', row_region: Optional[str] = None, click_x: Optional[int] = None, x_offset: int = 120, button: str = 'left', clicks: int = 2, min_row: int = 1, max_row: int = 999, max_scrolls: int = 8, scroll_amount: int = 5, scroll_x: Optional[int] = None, scroll_y: Optional[int] = None, pause: float = 0.35, capture_mode: str = 'auto') -> Any:
        """Scroll to and click a numbered list/table row."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "visual_row_scroll_click", None)
            if func is not None and callable(func):
                res = func(row=row, hwnd=hwnd, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, row_region=row_region, click_x=click_x, x_offset=x_offset, button=button, clicks=clicks, min_row=min_row, max_row=max_row, max_scrolls=max_scrolls, scroll_amount=scroll_amount, scroll_x=scroll_x, scroll_y=scroll_y, pause=pause, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function visual_row_scroll_click not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "visual_row_scroll_click"}

    @app.tool(name="ocr", description="Run OCR on the target window screenshot with Tesseract or Windows built-in OCR.")
    def tool_ocr(hwnd: Optional[int] = None, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', capture_mode: str = 'auto') -> Any:
        """Run OCR on the target window screenshot with Tesseract or Windows built-in OCR."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "ocr", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function ocr not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "ocr"}

    @app.tool(name="desktop_ocr", description="Run OCR on a full virtual desktop screenshot.")
    def tool_desktop_ocr(lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, screenshot_id: Optional[int] = None, engine: str = 'auto') -> Any:
        """Run OCR on a full virtual desktop screenshot."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_ocr", None)
            if func is not None and callable(func):
                res = func(lang=lang, max_screenshot_width=max_screenshot_width, screenshot_id=screenshot_id, engine=engine)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_ocr not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_ocr"}

    @app.tool(name="desktop_find_text_ocr", description="Find OCR-visible text in a full virtual desktop screenshot and return click-ready coordinates.")
    def tool_desktop_find_text_ocr(text: str, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, screenshot_id: Optional[int] = None, engine: str = 'auto', match: str = 'contains', limit: int = 10, region: Optional[str] = None, max_words: Optional[int] = None) -> Any:
        """Find OCR-visible text in a full virtual desktop screenshot and return click-ready coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_find_text_ocr", None)
            if func is not None and callable(func):
                res = func(text=text, lang=lang, max_screenshot_width=max_screenshot_width, screenshot_id=screenshot_id, engine=engine, match=match, limit=limit, region=region, max_words=max_words)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_find_text_ocr not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_find_text_ocr"}

    @app.tool(name="find_text_ocr", description="Find visible text in a window screenshot through OCR and return click-ready coordinates.")
    def tool_find_text_ocr(text: str, hwnd: Optional[int] = None, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', match: str = 'contains', limit: int = 10, region: Optional[str] = None, max_words: Optional[int] = None, capture_mode: str = 'auto') -> Any:
        """Find visible text in a window screenshot through OCR and return click-ready coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "find_text_ocr", None)
            if func is not None and callable(func):
                res = func(text=text, hwnd=hwnd, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, match=match, limit=limit, region=region, max_words=max_words, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function find_text_ocr not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "find_text_ocr"}

    @app.tool(name="wait_text_ocr", description="Poll screenshots with OCR until visible text appears, then return click-ready coordinates.")
    def tool_wait_text_ocr(text: str, hwnd: Optional[int] = None, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', match: str = 'contains', timeout: float = 10.0, interval: float = 0.5, limit: int = 10, region: Optional[str] = None, max_words: Optional[int] = None, capture_mode: str = 'auto') -> Any:
        """Poll screenshots with OCR until visible text appears, then return click-ready coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "wait_text_ocr", None)
            if func is not None and callable(func):
                res = func(text=text, hwnd=hwnd, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, match=match, timeout=timeout, interval=interval, limit=limit, region=region, max_words=max_words, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function wait_text_ocr not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "wait_text_ocr"}

    @app.tool(name="desktop_wait_text_ocr", description="Poll full-desktop screenshots with OCR until visible text appears.")
    def tool_desktop_wait_text_ocr(text: str, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', match: str = 'contains', timeout: float = 10.0, interval: float = 0.5, limit: int = 10, region: Optional[str] = None, max_words: Optional[int] = None) -> Any:
        """Poll full-desktop screenshots with OCR until visible text appears."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_wait_text_ocr", None)
            if func is not None and callable(func):
                res = func(text=text, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, match=match, timeout=timeout, interval=interval, limit=limit, region=region, max_words=max_words)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_wait_text_ocr not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_wait_text_ocr"}

    @app.tool(name="click_text_ocr", description="Click the center of visible OCR text in custom-rendered or weak-accessibility apps.")
    def tool_click_text_ocr(text: str, hwnd: Optional[int] = None, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, engine: str = 'auto', match: str = 'contains', index: int = 0, button: str = 'left', clicks: int = 1, region: Optional[str] = None, max_words: Optional[int] = None, timeout: float = 0.0, interval: float = 0.5, capture_mode: str = 'auto') -> Any:
        """Click the center of visible OCR text in custom-rendered or weak-accessibility apps."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "click_text_ocr", None)
            if func is not None and callable(func):
                res = func(text=text, hwnd=hwnd, lang=lang, max_screenshot_width=max_screenshot_width, engine=engine, match=match, index=index, button=button, clicks=clicks, region=region, max_words=max_words, timeout=timeout, interval=interval, capture_mode=capture_mode)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function click_text_ocr not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "click_text_ocr"}

    @app.tool(name="desktop_click_text_ocr", description="Click the center of OCR-visible text in a full virtual desktop screenshot.")
    def tool_desktop_click_text_ocr(text: str, lang: str = 'eng+chi_sim', max_screenshot_width: int = 1600, screenshot_id: Optional[int] = None, engine: str = 'auto', match: str = 'contains', index: int = 0, button: str = 'left', clicks: int = 1, region: Optional[str] = None, max_words: Optional[int] = None, timeout: float = 0.0, interval: float = 0.5) -> Any:
        """Click the center of OCR-visible text in a full virtual desktop screenshot."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_click_text_ocr", None)
            if func is not None and callable(func):
                res = func(text=text, lang=lang, max_screenshot_width=max_screenshot_width, screenshot_id=screenshot_id, engine=engine, match=match, index=index, button=button, clicks=clicks, region=region, max_words=max_words, timeout=timeout, interval=interval)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_click_text_ocr not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_click_text_ocr"}

    @app.tool(name="find_elements", description="Find UI Automation elements by stable selectors and refresh element indexes.")
    def tool_find_elements(hwnd: Optional[int] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, value: Optional[str] = None, pattern: Optional[str] = None, enabled_only: bool = False, visible_only: bool = True, match: str = 'contains', limit: int = 25, max_depth: int = 10, max_elements: int = 500, view: str = 'raw') -> Any:
        """Find UI Automation elements by stable selectors and refresh element indexes."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "find_elements", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, value=value, pattern=pattern, enabled_only=enabled_only, visible_only=visible_only, match=match, limit=limit, max_depth=max_depth, max_elements=max_elements, view=view)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function find_elements not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "find_elements"}

    @app.tool(name="uia_selector_repair_find", description="Retry a failed UIA selector using a cleaned failure_summary.selector_suggestions entry.")
    def tool_uia_selector_repair_find(hwnd: Optional[int] = None, suggestion: Optional[dict[str, Any]] = None, original: Optional[dict[str, Any]] = None, limit: int = 1, max_depth: Optional[int] = None, max_elements: Optional[int] = None, view: Optional[str] = None, allow_suggestion_index: bool = False) -> Any:
        """Retry a failed UIA selector using a cleaned failure_summary.selector_suggestions entry."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "uia_selector_repair_find", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, suggestion=suggestion, original=original, limit=limit, max_depth=max_depth, max_elements=max_elements, view=view, allow_suggestion_index=allow_suggestion_index)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function uia_selector_repair_find not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "uia_selector_repair_find"}

    @app.tool(name="uia_cell_selector_repair_find", description="Repair a UIA grid/table/list cell selector and prove row/column metadata before acting.")
    def tool_uia_cell_selector_repair_find(hwnd: Optional[int] = None, suggestion: Optional[dict[str, Any]] = None, original: Optional[dict[str, Any]] = None, row: Optional[int] = None, column: Optional[int] = None, row_text: Optional[str] = None, column_name: Optional[str] = None, limit: int = 1, max_depth: Optional[int] = None, max_elements: Optional[int] = None, view: Optional[str] = None) -> Any:
        """Repair a UIA grid/table/list cell selector and prove row/column metadata before acting."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "uia_cell_selector_repair_find", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, suggestion=suggestion, original=original, row=row, column=column, row_text=row_text, column_name=column_name, limit=limit, max_depth=max_depth, max_elements=max_elements, view=view)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function uia_cell_selector_repair_find not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "uia_cell_selector_repair_find"}

    @app.tool(name="wait_for_element", description="Poll UI Automation until an element matching the selector appears.")
    def tool_wait_for_element(hwnd: Optional[int] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, value: Optional[str] = None, pattern: Optional[str] = None, enabled_only: bool = False, visible_only: bool = True, match: str = 'contains', timeout: float = 10.0, interval: float = 0.5, max_depth: int = 10, max_elements: int = 500, view: str = 'raw', repair: Optional[bool] = None, repair_timeout: Optional[float] = None, allow_suggestion_index: bool = False) -> Any:
        """Poll UI Automation until an element matching the selector appears."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "wait_for_element", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, value=value, pattern=pattern, enabled_only=enabled_only, visible_only=visible_only, match=match, timeout=timeout, interval=interval, max_depth=max_depth, max_elements=max_elements, view=view, repair=repair, repair_timeout=repair_timeout, allow_suggestion_index=allow_suggestion_index)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function wait_for_element not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "wait_for_element"}

    @app.tool(name="desktop_accessibility", description="Build a UI Automation tree rooted at the Windows desktop root for taskbar, Start, menus, overlays, and cross-window UI.")
    def tool_desktop_accessibility(max_depth: int = 4, max_elements: int = 500, view: str = 'control') -> Any:
        """Build a UI Automation tree rooted at the Windows desktop root for taskbar, Start, menus, overlays, and cross-window UI."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_accessibility", None)
            if func is not None and callable(func):
                res = func(max_depth=max_depth, max_elements=max_elements, view=view)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_accessibility not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_accessibility"}

    @app.tool(name="desktop_find_elements", description="Find UI Automation elements from the Windows desktop root without choosing an app HWND first.")
    def tool_desktop_find_elements(name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, value: Optional[str] = None, pattern: Optional[str] = None, enabled_only: bool = False, visible_only: bool = True, match: str = 'contains', limit: int = 25, max_depth: int = 4, max_elements: int = 500, view: str = 'control') -> Any:
        """Find UI Automation elements from the Windows desktop root without choosing an app HWND first."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_find_elements", None)
            if func is not None and callable(func):
                res = func(name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, value=value, pattern=pattern, enabled_only=enabled_only, visible_only=visible_only, match=match, limit=limit, max_depth=max_depth, max_elements=max_elements, view=view)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_find_elements not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_find_elements"}

    @app.tool(name="desktop_wait_for_element", description="Poll desktop-root UIA until an element matching the selector appears.")
    def tool_desktop_wait_for_element(name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, value: Optional[str] = None, pattern: Optional[str] = None, enabled_only: bool = False, visible_only: bool = True, match: str = 'contains', timeout: float = 10.0, interval: float = 0.5, max_depth: int = 4, max_elements: int = 500, view: str = 'control', repair: Optional[bool] = None, repair_timeout: Optional[float] = None, allow_suggestion_index: bool = False) -> Any:
        """Poll desktop-root UIA until an element matching the selector appears."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_wait_for_element", None)
            if func is not None and callable(func):
                res = func(name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, value=value, pattern=pattern, enabled_only=enabled_only, visible_only=visible_only, match=match, timeout=timeout, interval=interval, max_depth=max_depth, max_elements=max_elements, view=view, repair=repair, repair_timeout=repair_timeout, allow_suggestion_index=allow_suggestion_index)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_wait_for_element not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_wait_for_element"}

    @app.tool(name="desktop_get_element", description="Return metadata for an indexed desktop-root UIA element from the latest desktop scan.")
    def tool_desktop_get_element(index: int) -> Any:
        """Return metadata for an indexed desktop-root UIA element from the latest desktop scan."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_get_element", None)
            if func is not None and callable(func):
                res = func(index=index)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_get_element not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_get_element"}

    @app.tool(name="desktop_focus_element", description="Move keyboard focus to an indexed desktop-root UIA element.")
    def tool_desktop_focus_element(index: int) -> Any:
        """Move keyboard focus to an indexed desktop-root UIA element."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_focus_element", None)
            if func is not None and callable(func):
                res = func(index=index)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_focus_element not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_focus_element"}

    @app.tool(name="desktop_click_element", description="Click the center of an indexed desktop-root UIA element.")
    def tool_desktop_click_element(index: int, button: str = 'left', clicks: int = 1) -> Any:
        """Click the center of an indexed desktop-root UIA element."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_click_element", None)
            if func is not None and callable(func):
                res = func(index=index, button=button, clicks=clicks)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_click_element not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_click_element"}

    @app.tool(name="desktop_action", description="Run a common UIA pattern action on an indexed desktop-root element.")
    def tool_desktop_action(index: int, action: str, value: Optional[str] = None, horizontal: Optional[str] = None, vertical: Optional[str] = None) -> Any:
        """Run a common UIA pattern action on an indexed desktop-root element."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "desktop_action", None)
            if func is not None and callable(func):
                res = func(index=index, action=action, value=value, horizontal=horizontal, vertical=vertical)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function desktop_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "desktop_action"}

    @app.tool(name="get_element", description="Return metadata for an indexed UI Automation element from the latest accessibility scan.")
    def tool_get_element(index: int, hwnd: Optional[int] = None) -> Any:
        """Return metadata for an indexed UI Automation element from the latest accessibility scan."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "get_element", None)
            if func is not None and callable(func):
                res = func(index=index, hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function get_element not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "get_element"}

    @app.tool(name="find_item_in_container", description="Find child items through UIA ItemContainer.FindItemByProperty and register returned indexes.")
    def tool_find_item_in_container(index: int, property_name: str = 'name', property_value: str = '', hwnd: Optional[int] = None, limit: int = 1, include_children: bool = False, max_children: int = 64) -> Any:
        """Find child items through UIA ItemContainer.FindItemByProperty and register returned indexes."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "find_item_in_container", None)
            if func is not None and callable(func):
                res = func(index=index, property_name=property_name, property_value=property_value, hwnd=hwnd, limit=limit, include_children=include_children, max_children=max_children)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function find_item_in_container not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "find_item_in_container"}

    @app.tool(name="focus_element", description="Move keyboard focus to an indexed UI Automation element.")
    def tool_focus_element(index: int, hwnd: Optional[int] = None) -> Any:
        """Move keyboard focus to an indexed UI Automation element."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "focus_element", None)
            if func is not None and callable(func):
                res = func(index=index, hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function focus_element not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "focus_element"}

    @app.tool(name="click", description="Click in a window at coordinates or on an element by index.")
    def tool_click(hwnd: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None, index: Optional[int] = None, button: str = 'left', clicks: int = 1, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> Any:
        """Click in a window at coordinates or on an element by index."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "click", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, x=x, y=y, index=index, button=button, clicks=clicks, screenshot_width=screenshot_width, screenshot_height=screenshot_height)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function click not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "click"}

    @app.tool(name="type_text", description="Type text into a window.")
    def tool_type_text(text: str, hwnd: Optional[int] = None) -> Any:
        """Type text into a window."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "type_text", None)
            if func is not None and callable(func):
                res = func(text=text, hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function type_text not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "type_text"}

    @app.tool(name="press_key", description="Press a key or keyboard shortcut.")
    def tool_press_key(keys: str, hwnd: Optional[int] = None) -> Any:
        """Press a key or keyboard shortcut."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "press_key", None)
            if func is not None and callable(func):
                res = func(keys=keys, hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function press_key not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "press_key"}

    @app.tool(name="scroll", description="Scroll in a window at the specified coordinates.")
    def tool_scroll(x: int, y: int, scroll_y: int, hwnd: Optional[int] = None, scroll_x: int = 0, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> Any:
        """Scroll in a window at the specified coordinates."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "scroll", None)
            if func is not None and callable(func):
                res = func(x=x, y=y, scroll_y=scroll_y, hwnd=hwnd, scroll_x=scroll_x, screenshot_width=screenshot_width, screenshot_height=screenshot_height)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function scroll not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "scroll"}

    @app.tool(name="drag", description="Drag from one position to another in a window.")
    def tool_drag(start_x: int, start_y: int, end_x: int, end_y: int, hwnd: Optional[int] = None, duration: float = 0.5, button: str = 'left', screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None) -> Any:
        """Drag from one position to another in a window."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "drag", None)
            if func is not None and callable(func):
                res = func(start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y, hwnd=hwnd, duration=duration, button=button, screenshot_width=screenshot_width, screenshot_height=screenshot_height)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function drag not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "drag"}

    @app.tool(name="set_value", description="Set the value of an editable element by index.")
    def tool_set_value(index: int, value: str, hwnd: Optional[int] = None) -> Any:
        """Set the value of an editable element by index."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "set_value", None)
            if func is not None and callable(func):
                res = func(index=index, value=value, hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function set_value not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "set_value"}

    @app.tool(name="perform_secondary_action", description="Perform a secondary action on an element by index.")
    def tool_perform_secondary_action(index: int, action: str, hwnd: Optional[int] = None, value: Optional[float] = None, horizontal: Optional[str] = None, vertical: Optional[str] = None, text: Optional[str] = None) -> Any:
        """Perform a secondary action on an element by index."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "perform_secondary_action", None)
            if func is not None and callable(func):
                res = func(index=index, action=action, hwnd=hwnd, value=value, horizontal=horizontal, vertical=vertical, text=text)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function perform_secondary_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "perform_secondary_action"}

    @app.tool(name="activate_window", description="Bring a window to the foreground.")
    def tool_activate_window(hwnd: Optional[int] = None) -> Any:
        """Bring a window to the foreground."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "activate_window", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function activate_window not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "activate_window"}

    @app.tool(name="focus_hwnd", description="Force foreground/active/focus for a top-level HWND or child control HWND.")
    def tool_focus_hwnd(hwnd: Optional[int] = None, timeout: float = 1.0, restore: bool = True) -> Any:
        """Force foreground/active/focus for a top-level HWND or child control HWND."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "focus_hwnd", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, timeout=timeout, restore=restore)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function focus_hwnd not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "focus_hwnd"}

    @app.tool(name="focused_input", description="Input text into the true focused native HWND for a window.")
    def tool_focused_input(text: str, hwnd: Optional[int] = None, mode: str = 'auto', timeout: float = 1.0, restore: bool = True, timeout_ms: int = 500, verify: bool = True, diagnostic: bool = False) -> Any:
        """Input text into the true focused native HWND for a window."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "focused_input", None)
            if func is not None and callable(func):
                res = func(text=text, hwnd=hwnd, mode=mode, timeout=timeout, restore=restore, timeout_ms=timeout_ms, verify=verify, diagnostic=diagnostic)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function focused_input not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "focused_input"}

    @app.tool(name="smart_text_input", description="Set text by trying UIA ValuePattern, native Win32 text children, then optional focused-input fallback.")
    def tool_smart_text_input(text: str, hwnd: Optional[int] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, index: Optional[int] = None, match: str = 'contains', mode: str = 'set-text', timeout: float = 1.0, timeout_ms: int = 500, verify: bool = True, diagnostic: bool = False, allow_focus_fallback: bool = False, skip_uia: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Set text by trying UIA ValuePattern, native Win32 text children, then optional focused-input fallback."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_text_input", None)
            if func is not None and callable(func):
                res = func(text=text, hwnd=hwnd, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, index=index, match=match, mode=mode, timeout=timeout, timeout_ms=timeout_ms, verify=verify, diagnostic=diagnostic, allow_focus_fallback=allow_focus_fallback, skip_uia=skip_uia, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_text_input not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_text_input"}

    @app.tool(name="smart_wait_text_input", description="Wait for a matching text input and set text through the smart-text action chain.")
    def tool_smart_wait_text_input(text: str, hwnd: Optional[int] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, index: Optional[int] = None, match: str = 'contains', mode: str = 'set-text', timeout: float = 10.0, interval: float = 0.25, input_timeout: float = 1.0, timeout_ms: int = 500, verify: bool = True, diagnostic: bool = False, allow_focus_fallback: bool = False, skip_uia: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Wait for a matching text input and set text through the smart-text action chain."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_wait_text_input", None)
            if func is not None and callable(func):
                res = func(text=text, hwnd=hwnd, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, index=index, match=match, mode=mode, timeout=timeout, interval=interval, input_timeout=input_timeout, timeout_ms=timeout_ms, verify=verify, diagnostic=diagnostic, allow_focus_fallback=allow_focus_fallback, skip_uia=skip_uia, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_wait_text_input not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_wait_text_input"}

    @app.tool(name="smart_click", description="Trigger a control by stable selectors using UIA actions, native Win32 actions, then optional coordinate fallback.")
    def tool_smart_click(hwnd: Optional[int] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, index: Optional[int] = None, match: str = 'contains', action: str = 'invoke', button: str = 'left', clicks: int = 1, timeout_ms: int = 500, diagnostic: bool = False, allow_coordinate_fallback: bool = False, skip_uia: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Trigger a control by stable selectors using UIA actions, native Win32 actions, then optional coordinate fallback."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_click", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, index=index, match=match, action=action, button=button, clicks=clicks, timeout_ms=timeout_ms, diagnostic=diagnostic, allow_coordinate_fallback=allow_coordinate_fallback, skip_uia=skip_uia, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_click not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_click"}

    @app.tool(name="smart_wait_click", description="Wait for a control and trigger it by stable selectors using the smart-click action chain.")
    def tool_smart_wait_click(hwnd: Optional[int] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, index: Optional[int] = None, match: str = 'contains', action: str = 'invoke', timeout: float = 10.0, interval: float = 0.25, button: str = 'left', clicks: int = 1, timeout_ms: int = 500, diagnostic: bool = False, allow_coordinate_fallback: bool = False, skip_uia: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Wait for a control and trigger it by stable selectors using the smart-click action chain."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_wait_click", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, index=index, match=match, action=action, timeout=timeout, interval=interval, button=button, clicks=clicks, timeout_ms=timeout_ms, diagnostic=diagnostic, allow_coordinate_fallback=allow_coordinate_fallback, skip_uia=skip_uia, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_wait_click not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_wait_click"}

    @app.tool(name="smart_select", description="Select or checkbox-toggle a list/combo/tree/tab/toolbar item by stable selectors.")
    def tool_smart_select(hwnd: Optional[int] = None, item: Optional[str] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, index: Optional[int] = None, match: str = 'contains', mode: str = 'select', timeout_ms: int = 500, diagnostic: bool = False, skip_uia: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Select or checkbox-toggle a list/combo/tree/tab/toolbar item by stable selectors."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_select", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, item=item, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, index=index, match=match, mode=mode, timeout_ms=timeout_ms, diagnostic=diagnostic, skip_uia=skip_uia, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_select not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_select"}

    @app.tool(name="smart_wait_select", description="Wait for a selectable/checkable item and run the smart-select action chain.")
    def tool_smart_wait_select(hwnd: Optional[int] = None, item: Optional[str] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, index: Optional[int] = None, match: str = 'contains', mode: str = 'select', timeout: float = 10.0, interval: float = 0.25, timeout_ms: int = 500, diagnostic: bool = False, skip_uia: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Wait for a selectable/checkable item and run the smart-select action chain."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_wait_select", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, item=item, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, index=index, match=match, mode=mode, timeout=timeout, interval=interval, timeout_ms=timeout_ms, diagnostic=diagnostic, skip_uia=skip_uia, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_wait_select not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_wait_select"}

    @app.tool(name="smart_cell", description="Read, select, or set a table/ListView/grid cell by row/column selectors.")
    def tool_smart_cell(hwnd: Optional[int] = None, row: Optional[int] = None, column: Optional[int] = None, row_text: Optional[str] = None, column_name: Optional[str] = None, text: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, match: str = 'contains', action: str = 'get', timeout_ms: int = 500, diagnostic: bool = False, skip_uia: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Read, select, or set a table/ListView/grid cell by row/column selectors."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_cell", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, row=row, column=column, row_text=row_text, column_name=column_name, text=text, automation_id=automation_id, control_type=control_type, class_name=class_name, match=match, action=action, timeout_ms=timeout_ms, diagnostic=diagnostic, skip_uia=skip_uia, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_cell not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_cell"}

    @app.tool(name="smart_wait_cell", description="Wait for a table/ListView/grid cell and read, select, or set it.")
    def tool_smart_wait_cell(hwnd: Optional[int] = None, row: Optional[int] = None, column: Optional[int] = None, row_text: Optional[str] = None, column_name: Optional[str] = None, text: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, match: str = 'contains', action: str = 'get', timeout: float = 10.0, interval: float = 0.25, timeout_ms: int = 500, diagnostic: bool = False, skip_uia: bool = False, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Wait for a table/ListView/grid cell and read, select, or set it."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_wait_cell", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, row=row, column=column, row_text=row_text, column_name=column_name, text=text, automation_id=automation_id, control_type=control_type, class_name=class_name, match=match, action=action, timeout=timeout, interval=interval, timeout_ms=timeout_ms, diagnostic=diagnostic, skip_uia=skip_uia, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_wait_cell not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_wait_cell"}

    @app.tool(name="dialog_command_action", description="Wait for a related standard dialog and send a WM_COMMAND button id such as OK, Cancel, Yes, or No.")
    def tool_dialog_command_action(hwnd: Optional[int] = None, action: Optional[str] = None, command_id: Optional[Any] = None, name: Optional[str] = None, dialog_title: Optional[str] = None, dialog_class_name: Optional[str] = None, dialog_process: Optional[str] = None, match: str = 'contains', timeout: float = 10.0, interval: float = 0.25, timeout_ms: int = 500, include_invisible: bool = False, activate: bool = True, verify_close: bool = False, diagnostic: bool = False) -> Any:
        """Wait for a related standard dialog and send a WM_COMMAND button id such as OK, Cancel, Yes, or No."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "dialog_command_action", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, action=action, command_id=command_id, name=name, dialog_title=dialog_title, dialog_class_name=dialog_class_name, dialog_process=dialog_process, match=match, timeout=timeout, interval=interval, timeout_ms=timeout_ms, include_invisible=include_invisible, activate=activate, verify_close=verify_close, diagnostic=diagnostic)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function dialog_command_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "dialog_command_action"}

    @app.tool(name="dialog_button_action", description="Wait for a related dialog and trigger a native Win32 button by WM_COMMAND or BM_CLICK.")
    def tool_dialog_button_action(hwnd: Optional[int] = None, name: Optional[str] = None, action: Optional[str] = None, command_id: Optional[Any] = None, dialog_title: Optional[str] = None, dialog_class_name: Optional[str] = None, dialog_process: Optional[str] = None, automation_id: Optional[str] = None, class_name: Optional[str] = None, control_type: Optional[str] = None, index: Optional[int] = None, match: str = 'contains', timeout: float = 10.0, interval: float = 0.25, timeout_ms: int = 500, include_invisible: bool = False, activate: bool = True, verify_close: bool = False, prefer_command: bool = True, diagnostic: bool = False) -> Any:
        """Wait for a related dialog and trigger a native Win32 button by WM_COMMAND or BM_CLICK."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "dialog_button_action", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, name=name, action=action, command_id=command_id, dialog_title=dialog_title, dialog_class_name=dialog_class_name, dialog_process=dialog_process, automation_id=automation_id, class_name=class_name, control_type=control_type, index=index, match=match, timeout=timeout, interval=interval, timeout_ms=timeout_ms, include_invisible=include_invisible, activate=activate, verify_close=verify_close, prefer_command=prefer_command, diagnostic=diagnostic)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function dialog_button_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "dialog_button_action"}

    @app.tool(name="smart_dialog_action", description="Wait for a related popup/dialog and run a smart click/text/select/cell action inside it.")
    def tool_smart_dialog_action(hwnd: Optional[int] = None, action_kind: str = 'click', dialog_title: Optional[str] = None, dialog_class_name: Optional[str] = None, dialog_process: Optional[str] = None, name: Optional[str] = None, automation_id: Optional[str] = None, control_type: Optional[str] = None, class_name: Optional[str] = None, index: Optional[int] = None, match: str = 'contains', text: Optional[str] = None, item: Optional[str] = None, row: Optional[int] = None, column: Optional[int] = None, row_text: Optional[str] = None, column_name: Optional[str] = None, control_action: str = 'invoke', cell_action: str = 'get', mode: str = 'set-text', timeout: float = 10.0, action_timeout: float = 5.0, interval: float = 0.25, input_timeout: float = 1.0, timeout_ms: int = 500, verify: bool = True, diagnostic: bool = False, allow_focus_fallback: bool = False, allow_coordinate_fallback: bool = False, skip_uia: bool = False, include_invisible: bool = False, stable_ticks: int = 2, activate: bool = True, button: str = 'left', clicks: int = 1, repair: Optional[bool] = None, repair_timeout: Optional[float] = None) -> Any:
        """Wait for a related popup/dialog and run a smart click/text/select/cell action inside it."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "smart_dialog_action", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, action_kind=action_kind, dialog_title=dialog_title, dialog_class_name=dialog_class_name, dialog_process=dialog_process, name=name, automation_id=automation_id, control_type=control_type, class_name=class_name, index=index, match=match, text=text, item=item, row=row, column=column, row_text=row_text, column_name=column_name, control_action=control_action, cell_action=cell_action, mode=mode, timeout=timeout, action_timeout=action_timeout, interval=interval, input_timeout=input_timeout, timeout_ms=timeout_ms, verify=verify, diagnostic=diagnostic, allow_focus_fallback=allow_focus_fallback, allow_coordinate_fallback=allow_coordinate_fallback, skip_uia=skip_uia, include_invisible=include_invisible, stable_ticks=stable_ticks, activate=activate, button=button, clicks=clicks, repair=repair, repair_timeout=repair_timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function smart_dialog_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "smart_dialog_action"}

    @app.tool(name="window_action", description="Move, resize, change Z-order/topmost state, inspect placement, minimize/maximize/restore/show, or request-close a native HWND.")
    def tool_window_action(action: str, hwnd: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None, width: Optional[int] = None, height: Optional[int] = None, timeout: float = 1.5) -> Any:
        """Move, resize, change Z-order/topmost state, inspect placement, minimize/maximize/restore/show, or request-close a native HWND."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "window_action", None)
            if func is not None and callable(func):
                res = func(action=action, hwnd=hwnd, x=x, y=y, width=width, height=height, timeout=timeout)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function window_action not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "window_action"}

    @app.tool(name="check_safety", description="Check if an action requires user confirmation before proceeding.")
    def tool_check_safety(action: str) -> Any:
        """Check if an action requires user confirmation before proceeding."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "check_safety", None)
            if func is not None and callable(func):
                res = func(action=action)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function check_safety not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "check_safety"}

    @app.tool(name="hover", description="Move the mouse cursor over a window coordinate or an accessibility element without clicking.")
    def tool_hover(hwnd: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None, index: Optional[int] = None, screenshot_width: Optional[int] = None, screenshot_height: Optional[int] = None, settle: float = 0.05) -> Any:
        """Move the mouse cursor over a window coordinate or an accessibility element without clicking."""
        try:
            import tools as _tools_entry
            func = getattr(_tools_entry, "hover", None)
            if func is not None and callable(func):
                res = func(hwnd=hwnd, x=x, y=y, index=index, screenshot_width=screenshot_width, screenshot_height=screenshot_height, settle=settle)
                if isinstance(res, (dict, list, str, int, float, bool)) or res is None:
                    return res
                return str(res)
            return {"ok": False, "error": "Function hover not found"}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "tool": "hover"}

