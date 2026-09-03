"""
Command-line argument and flag parsing utilities.
"""

from __future__ import annotations

import sys
import json
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.utils import parse_rgb_color
from win_automation.uia.engine import _normalize_uia_action_name, _is_uia_clear_value_action, _DESKTOP_UIA_KEY
from win_automation.uia.cache import _parse_uia_scan_args
from win_automation.uia.patterns import _parse_selector_args

__all__ = [
    "_parse_uia_action_arguments",
    "_parse_image_match_args",
    "_parse_pixel_wait_args",
    "_parse_visual_stable_wait_args",
    "_parse_uia_stable_wait_args",
    "_smart_cli_finalize_repair_options",
    "_parse_smart_click_cli_args",
    "_parse_smart_select_cli_args",
    "_parse_smart_cell_cli_args",
    "_parse_smart_text_cli_args",
    "_parse_smart_dialog_cli_args",
    "_parse_dialog_button_cli_args",
    "_parse_win32_control_find_cli_args",
    "_parse_uia_scan_args",
    "_parse_selector_args",
    "_DESKTOP_UIA_KEY",
    "_normalize_uia_action_name",
    "_is_uia_clear_value_action",
]

def _parse_uia_action_arguments(action_name: str, action_args: List[str]) -> Tuple[Any, Any, Any]:
    """Map CLI positional action arguments to perform_action value/horizontal/vertical."""
    action_lower = _normalize_uia_action_name(action_name)
    value = None
    horizontal = None
    vertical = None
    if action_lower in ("set_value", "setvalue", "value") and len(action_args) > 0:
        value = action_args[0]
    elif action_lower in ("set_value", "setvalue", "value") and _is_uia_clear_value_action(action_name):
        value = ""
    elif action_lower in ("set_range", "setrange", "range", "rangevalue", "set_range_value") and len(action_args) > 0:
        value = float(action_args[0])
    elif action_lower == "scroll":
        horizontal = action_args[0] if len(action_args) > 0 else None
        vertical = action_args[1] if len(action_args) > 1 else None
    elif action_lower in ("set_scroll_percent", "setscrollpercent", "scroll_percent"):
        horizontal = float(action_args[0]) if len(action_args) > 0 else None
        vertical = float(action_args[1]) if len(action_args) > 1 else None
    elif action_lower in ("text_find", "find_text", "textfind", "text_select", "select_text", "textselect", "text_scroll_into_view", "scroll_text_into_view", "text_scroll"):
        value = action_args[0] if len(action_args) > 0 else None
    elif action_lower in ("text_select_range", "select_text_range"):
        value = float(action_args[0]) if len(action_args) > 0 else 0
        vertical = float(action_args[1]) if len(action_args) > 1 else value
    elif action_lower in ("set_current_view", "set_view", "view"):
        value = float(action_args[0]) if len(action_args) > 0 else None
    elif action_lower in ("item_find", "find_item", "find_item_by_property", "itemcontainer_find"):
        value = action_args[0] if len(action_args) > 0 else None
        horizontal = action_args[1] if len(action_args) > 1 else None
        vertical = float(action_args[2]) if len(action_args) > 2 else None
    elif action_lower in ("spreadsheet_get_item", "spreadsheet_get_item_by_name", "get_cell", "cell", "custom_navigate", "navigate", "sync_start", "synchronized_input_start", "start_listening"):
        value = action_args[0] if len(action_args) > 0 else None
    elif action_lower in ("legacy_set_value", "legacy_setvalue", "set_legacy_value", "set_dock_position", "dock", "set_dock", "zoom_by_unit", "zoombyunit", "zoom_unit"):
        value = action_args[0] if len(action_args) > 0 else None
    elif action_lower in ("legacy_select", "legacy_take_selection", "rotate", "zoom"):
        value = float(action_args[0]) if len(action_args) > 0 else None
    elif action_lower in ("move", "resize"):
        value = float(action_args[0]) if len(action_args) > 0 else None
        horizontal = float(action_args[1]) if len(action_args) > 1 else None
    return value, horizontal, vertical


def _parse_image_match_args(args: List[str], default_confidence: float = 0.85) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "confidence": default_confidence,
        "max_width": 1280,
        "screenshot_id": None,
        "region": None,
        "scale_min": 1.0,
        "scale_max": 1.0,
        "scale_step": 0.0,
        "timeout": 0.0,
        "interval": 0.5,
        "button": "left",
        "clicks": 1,
        "capture_mode": "auto",
    }
    remaining = list(args)
    if remaining and not remaining[0].startswith("--"):
        options["confidence"] = float(remaining[0])
        remaining = remaining[1:]
    if remaining and not remaining[0].startswith("--"):
        options["screenshot_id"] = int(remaining[0])
        remaining = remaining[1:]
    i = 0
    while i < len(remaining):
        arg = remaining[i]
        if arg == "--confidence" and i + 1 < len(remaining):
            options["confidence"] = float(remaining[i + 1])
            i += 2
        elif arg == "--max-width" and i + 1 < len(remaining):
            options["max_width"] = int(remaining[i + 1])
            i += 2
        elif arg == "--screenshot-id" and i + 1 < len(remaining):
            options["screenshot_id"] = int(remaining[i + 1])
            i += 2
        elif arg == "--region" and i + 1 < len(remaining):
            options["region"] = remaining[i + 1]
            i += 2
        elif arg == "--scale" and i + 1 < len(remaining):
            scale = float(remaining[i + 1])
            options["scale_min"] = scale
            options["scale_max"] = scale
            options["scale_step"] = 0.0
            i += 2
        elif arg == "--scale-min" and i + 1 < len(remaining):
            options["scale_min"] = float(remaining[i + 1])
            i += 2
        elif arg == "--scale-max" and i + 1 < len(remaining):
            options["scale_max"] = float(remaining[i + 1])
            i += 2
        elif arg == "--scale-step" and i + 1 < len(remaining):
            options["scale_step"] = float(remaining[i + 1])
            i += 2
        elif arg == "--timeout" and i + 1 < len(remaining):
            options["timeout"] = float(remaining[i + 1])
            i += 2
        elif arg == "--interval" and i + 1 < len(remaining):
            options["interval"] = float(remaining[i + 1])
            i += 2
        elif arg == "--button" and i + 1 < len(remaining):
            options["button"] = remaining[i + 1]
            i += 2
        elif arg == "--clicks" and i + 1 < len(remaining):
            options["clicks"] = int(remaining[i + 1])
            i += 2
        elif arg in ("--capture-mode", "--capture") and i + 1 < len(remaining):
            options["capture_mode"] = remaining[i + 1]
            i += 2
        else:
            i += 1
    return options


def _parse_pixel_wait_args(args: List[str]) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "timeout": 10.0,
        "interval": 0.25,
        "tolerance": 0.0,
        "mode": "equals",
        "capture_mode": "auto",
        "max_width": 1600,
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif arg in ("--tolerance", "--tol") and i + 1 < len(args):
            options["tolerance"] = float(args[i + 1])
            i += 2
        elif arg == "--mode" and i + 1 < len(args):
            options["mode"] = args[i + 1]
            i += 2
        elif arg in ("--not", "--different", "--not-equals"):
            options["mode"] = "not_equals"
            i += 1
        elif arg in ("--capture-mode", "--capture") and i + 1 < len(args):
            options["capture_mode"] = args[i + 1]
            i += 2
        elif arg == "--max-width" and i + 1 < len(args):
            options["max_width"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    return options


def _parse_visual_stable_wait_args(args: List[str]) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "timeout": 5.0,
        "interval": 0.25,
        "stable_ticks": 2,
        "difference_threshold": 0.003,
        "pixel_threshold": 8.0,
        "region": None,
        "max_width": 1280,
        "comparison_max_width": 320,
        "capture_mode": "auto",
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif arg in ("--stable-ticks", "--ticks") and i + 1 < len(args):
            options["stable_ticks"] = int(args[i + 1])
            i += 2
        elif arg in ("--difference-threshold", "--diff-threshold") and i + 1 < len(args):
            options["difference_threshold"] = float(args[i + 1])
            i += 2
        elif arg == "--pixel-threshold" and i + 1 < len(args):
            options["pixel_threshold"] = float(args[i + 1])
            i += 2
        elif arg == "--region" and i + 1 < len(args):
            options["region"] = args[i + 1]
            i += 2
        elif arg == "--max-width" and i + 1 < len(args):
            options["max_width"] = int(args[i + 1])
            i += 2
        elif arg in ("--comparison-max-width", "--stable-max-width") and i + 1 < len(args):
            options["comparison_max_width"] = int(args[i + 1])
            i += 2
        elif arg in ("--capture-mode", "--capture") and i + 1 < len(args):
            options["capture_mode"] = args[i + 1]
            i += 2
        else:
            i += 1
    return options


def _parse_uia_stable_wait_args(args: List[str]) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "timeout": 5.0,
        "interval": 0.25,
        "stable_ticks": 2,
        "max_depth": 10,
        "max_elements": 500,
        "view": "control",
        "include_values": False,
        "rect_bucket": 2,
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif arg in ("--stable-ticks", "--ticks") and i + 1 < len(args):
            options["stable_ticks"] = int(args[i + 1])
            i += 2
        elif arg in ("--max-depth", "--depth") and i + 1 < len(args):
            options["max_depth"] = int(args[i + 1])
            i += 2
        elif arg in ("--max-elements", "--elements") and i + 1 < len(args):
            options["max_elements"] = int(args[i + 1])
            i += 2
        elif arg == "--view" and i + 1 < len(args):
            options["view"] = args[i + 1]
            i += 2
        elif arg in ("--include-values", "--values"):
            options["include_values"] = True
            i += 1
        elif arg in ("--rect-bucket", "--bucket") and i + 1 < len(args):
            options["rect_bucket"] = int(args[i + 1])
            i += 2
        else:
            i += 1
    return options


def _smart_cli_finalize_repair_options(options: Dict[str, Any]) -> Dict[str, Any]:
    if options.get("repair") is None and options.get("repair_timeout") is not None:
        options["repair"] = True
    return options


def _parse_smart_click_cli_args(raw_args: List[str], wait_defaults: bool = False) -> Dict[str, Any]:
    args = list(raw_args)
    options: Dict[str, Any] = {
        "hwnd": None,
        "name": None,
        "automation_id": None,
        "control_type": None,
        "class_name": None,
        "index": None,
        "match": "contains",
        "action": "invoke",
        "button": "left",
        "clicks": 1,
        "timeout_ms": 500,
        "diagnostic": False,
        "allow_coordinate_fallback": False,
        "skip_uia": False,
        "repair": None,
        "repair_timeout": None,
    }
    if wait_defaults:
        options.update({"timeout": 10.0, "interval": 0.25})
    if args and not args[0].startswith("--"):
        try:
            options["hwnd"] = int(args[0], 0)
            args = args[1:]
        except ValueError:
            options["name"] = args[0]
            args = args[1:]
    i = 0
    while i < len(args):
        if args[i] == "--hwnd" and i + 1 < len(args):
            options["hwnd"] = int(args[i + 1], 0)
            i += 2
        elif args[i] == "--name" and i + 1 < len(args):
            options["name"] = args[i + 1]
            i += 2
        elif args[i] in ("--automation-id", "--automation_id") and i + 1 < len(args):
            options["automation_id"] = args[i + 1]
            i += 2
        elif args[i] in ("--type", "--control-type", "--control_type") and i + 1 < len(args):
            options["control_type"] = args[i + 1]
            i += 2
        elif args[i] in ("--class", "--class-name", "--class_name") and i + 1 < len(args):
            options["class_name"] = args[i + 1]
            i += 2
        elif args[i] == "--index" and i + 1 < len(args):
            options["index"] = int(args[i + 1])
            i += 2
        elif args[i] == "--match" and i + 1 < len(args):
            options["match"] = args[i + 1]
            i += 2
        elif args[i] == "--action" and i + 1 < len(args):
            options["action"] = args[i + 1]
            i += 2
        elif args[i] == "--button" and i + 1 < len(args):
            options["button"] = args[i + 1]
            i += 2
        elif args[i] == "--clicks" and i + 1 < len(args):
            options["clicks"] = int(args[i + 1])
            i += 2
        elif args[i] == "--timeout-ms" and i + 1 < len(args):
            options["timeout_ms"] = int(args[i + 1])
            i += 2
        elif wait_defaults and args[i] == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif wait_defaults and args[i] == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif args[i] in ("--diagnostic", "--verbose"):
            options["diagnostic"] = True
            i += 1
        elif args[i] == "--allow-coordinate-fallback":
            options["allow_coordinate_fallback"] = True
            i += 1
        elif args[i] in ("--skip-uia", "--no-uia"):
            options["skip_uia"] = True
            i += 1
        elif args[i] in ("--repair", "--selector-repair", "--selector_repair"):
            options["repair"] = True
            i += 1
        elif args[i] in ("--no-repair", "--no-selector-repair"):
            options["repair"] = False
            i += 1
        elif args[i] in ("--repair-timeout", "--repair_timeout", "--selector-repair-timeout", "--selector_repair_timeout") and i + 1 < len(args):
            options["repair_timeout"] = float(args[i + 1])
            i += 2
        elif options.get("name") is None:
            options["name"] = args[i]
            i += 1
        else:
            i += 1
    return _smart_cli_finalize_repair_options(options)


def _parse_smart_select_cli_args(raw_args: List[str], wait_defaults: bool = False) -> Dict[str, Any]:
    args = list(raw_args)
    options: Dict[str, Any] = {
        "hwnd": None,
        "item": None,
        "name": None,
        "automation_id": None,
        "control_type": None,
        "class_name": None,
        "index": None,
        "match": "contains",
        "mode": "select",
        "timeout_ms": 500,
        "diagnostic": False,
        "skip_uia": False,
        "repair": None,
        "repair_timeout": None,
    }
    if wait_defaults:
        options.update({"timeout": 10.0, "interval": 0.25})
    if args and not args[0].startswith("--"):
        try:
            options["hwnd"] = int(args[0], 0)
            args = args[1:]
            if args and not args[0].startswith("--"):
                options["item"] = args[0]
                args = args[1:]
        except ValueError:
            options["item"] = args[0]
            args = args[1:]
    i = 0
    while i < len(args):
        if args[i] == "--hwnd" and i + 1 < len(args):
            options["hwnd"] = int(args[i + 1], 0)
            i += 2
        elif args[i] in ("--item", "--text", "--value") and i + 1 < len(args):
            options["item"] = args[i + 1]
            i += 2
        elif args[i] == "--name" and i + 1 < len(args):
            options["name"] = args[i + 1]
            i += 2
        elif args[i] in ("--automation-id", "--automation_id") and i + 1 < len(args):
            options["automation_id"] = args[i + 1]
            i += 2
        elif args[i] in ("--type", "--control-type", "--control_type") and i + 1 < len(args):
            options["control_type"] = args[i + 1]
            i += 2
        elif args[i] in ("--class", "--class-name", "--class_name") and i + 1 < len(args):
            options["class_name"] = args[i + 1]
            i += 2
        elif args[i] == "--index" and i + 1 < len(args):
            options["index"] = int(args[i + 1])
            i += 2
        elif args[i] == "--match" and i + 1 < len(args):
            options["match"] = args[i + 1]
            i += 2
        elif args[i] == "--mode" and i + 1 < len(args):
            options["mode"] = args[i + 1]
            i += 2
        elif args[i] == "--timeout-ms" and i + 1 < len(args):
            options["timeout_ms"] = int(args[i + 1])
            i += 2
        elif wait_defaults and args[i] == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif wait_defaults and args[i] == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif args[i] in ("--diagnostic", "--verbose"):
            options["diagnostic"] = True
            i += 1
        elif args[i] in ("--skip-uia", "--no-uia"):
            options["skip_uia"] = True
            i += 1
        elif args[i] in ("--repair", "--selector-repair", "--selector_repair"):
            options["repair"] = True
            i += 1
        elif args[i] in ("--no-repair", "--no-selector-repair"):
            options["repair"] = False
            i += 1
        elif args[i] in ("--repair-timeout", "--repair_timeout", "--selector-repair-timeout", "--selector_repair_timeout") and i + 1 < len(args):
            options["repair_timeout"] = float(args[i + 1])
            i += 2
        elif options.get("item") is None:
            options["item"] = args[i]
            i += 1
        else:
            i += 1
    return _smart_cli_finalize_repair_options(options)


def _parse_smart_cell_cli_args(raw_args: List[str]) -> Dict[str, Any]:
    args = list(raw_args)
    options: Dict[str, Any] = {
        "hwnd": None,
        "row": None,
        "column": None,
        "row_text": None,
        "column_name": None,
        "text": None,
        "automation_id": None,
        "control_type": None,
        "class_name": None,
        "match": "contains",
        "action": "get",
        "timeout": 10.0,
        "interval": 0.25,
        "timeout_ms": 500,
        "diagnostic": False,
        "skip_uia": False,
        "repair": None,
        "repair_timeout": None,
    }
    if args and not args[0].startswith("--"):
        try:
            options["hwnd"] = int(args[0], 0)
            args = args[1:]
        except ValueError:
            pass
    i = 0
    while i < len(args):
        if args[i] == "--hwnd" and i + 1 < len(args):
            options["hwnd"] = int(args[i + 1], 0)
            i += 2
        elif args[i] == "--row" and i + 1 < len(args):
            options["row"] = int(args[i + 1])
            i += 2
        elif args[i] in ("--column", "--col") and i + 1 < len(args):
            options["column"] = int(args[i + 1])
            i += 2
        elif args[i] in ("--row-text", "--row_text", "--name") and i + 1 < len(args):
            options["row_text"] = args[i + 1]
            i += 2
        elif args[i] in ("--column-name", "--column_name", "--header") and i + 1 < len(args):
            options["column_name"] = args[i + 1]
            i += 2
        elif args[i] in ("--text", "--value") and i + 1 < len(args):
            options["text"] = args[i + 1]
            i += 2
        elif args[i] in ("--automation-id", "--automation_id") and i + 1 < len(args):
            options["automation_id"] = args[i + 1]
            i += 2
        elif args[i] in ("--type", "--control-type", "--control_type") and i + 1 < len(args):
            options["control_type"] = args[i + 1]
            i += 2
        elif args[i] in ("--class", "--class-name", "--class_name") and i + 1 < len(args):
            options["class_name"] = args[i + 1]
            i += 2
        elif args[i] == "--match" and i + 1 < len(args):
            options["match"] = args[i + 1]
            i += 2
        elif args[i] == "--action" and i + 1 < len(args):
            options["action"] = args[i + 1]
            i += 2
        elif args[i] == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif args[i] == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif args[i] == "--timeout-ms" and i + 1 < len(args):
            options["timeout_ms"] = int(args[i + 1])
            i += 2
        elif args[i] in ("--diagnostic", "--verbose"):
            options["diagnostic"] = True
            i += 1
        elif args[i] in ("--skip-uia", "--no-uia"):
            options["skip_uia"] = True
            i += 1
        elif args[i] in ("--repair", "--selector-repair", "--selector_repair"):
            options["repair"] = True
            i += 1
        elif args[i] in ("--no-repair", "--no-selector-repair"):
            options["repair"] = False
            i += 1
        elif args[i] in ("--repair-timeout", "--repair_timeout", "--selector-repair-timeout", "--selector_repair_timeout") and i + 1 < len(args):
            options["repair_timeout"] = float(args[i + 1])
            i += 2
        else:
            i += 1
    return _smart_cli_finalize_repair_options(options)


def _parse_smart_text_cli_args(raw_args: List[str], wait_defaults: bool = False) -> Dict[str, Any]:
    args = list(raw_args)
    options: Dict[str, Any] = {
        "hwnd": None,
        "text": None,
        "name": None,
        "automation_id": None,
        "control_type": None,
        "class_name": None,
        "index": None,
        "match": "contains",
        "mode": "set-text",
        "timeout": 10.0 if wait_defaults else 1.0,
        "interval": 0.25,
        "input_timeout": 1.0,
        "timeout_ms": 500,
        "verify": True,
        "diagnostic": False,
        "allow_focus_fallback": False,
        "skip_uia": False,
        "repair": None,
        "repair_timeout": None,
    }
    if args and not args[0].startswith("--"):
        try:
            candidate = int(args[0], 0)
            if len(args) >= 2:
                options["hwnd"] = candidate
                options["text"] = args[1]
                args = args[2:]
            else:
                args = args[1:]
        except ValueError:
            options["text"] = args[0]
            args = args[1:]
    i = 0
    while i < len(args):
        if args[i] == "--hwnd" and i + 1 < len(args):
            options["hwnd"] = int(args[i + 1], 0)
            i += 2
        elif args[i] == "--text" and i + 1 < len(args):
            options["text"] = args[i + 1]
            i += 2
        elif args[i] == "--name" and i + 1 < len(args):
            options["name"] = args[i + 1]
            i += 2
        elif args[i] in ("--automation-id", "--automation_id") and i + 1 < len(args):
            options["automation_id"] = args[i + 1]
            i += 2
        elif args[i] in ("--type", "--control-type", "--control_type") and i + 1 < len(args):
            options["control_type"] = args[i + 1]
            i += 2
        elif args[i] in ("--class", "--class-name", "--class_name") and i + 1 < len(args):
            options["class_name"] = args[i + 1]
            i += 2
        elif args[i] == "--index" and i + 1 < len(args):
            options["index"] = int(args[i + 1])
            i += 2
        elif args[i] == "--match" and i + 1 < len(args):
            options["match"] = args[i + 1]
            i += 2
        elif args[i] == "--mode" and i + 1 < len(args):
            options["mode"] = args[i + 1]
            i += 2
        elif args[i] == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif wait_defaults and args[i] == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif args[i] in ("--input-timeout", "--input_timeout") and i + 1 < len(args):
            options["input_timeout"] = float(args[i + 1])
            i += 2
        elif args[i] == "--timeout-ms" and i + 1 < len(args):
            options["timeout_ms"] = int(args[i + 1])
            i += 2
        elif args[i] == "--no-verify":
            options["verify"] = False
            i += 1
        elif args[i] in ("--diagnostic", "--verbose"):
            options["diagnostic"] = True
            i += 1
        elif args[i] in ("--allow-focus-fallback", "--allow_focus_fallback"):
            options["allow_focus_fallback"] = True
            i += 1
        elif args[i] in ("--skip-uia", "--no-uia"):
            options["skip_uia"] = True
            i += 1
        elif args[i] in ("--repair", "--selector-repair", "--selector_repair"):
            options["repair"] = True
            i += 1
        elif args[i] in ("--no-repair", "--no-selector-repair"):
            options["repair"] = False
            i += 1
        elif args[i] in ("--repair-timeout", "--repair_timeout", "--selector-repair-timeout", "--selector_repair_timeout") and i + 1 < len(args):
            options["repair_timeout"] = float(args[i + 1])
            i += 2
        elif options.get("text") is None:
            options["text"] = args[i]
            i += 1
        else:
            i += 1
    return _smart_cli_finalize_repair_options(options)


def _parse_smart_dialog_cli_args(raw_args: List[str]) -> Dict[str, Any]:
    args = list(raw_args)
    options: Dict[str, Any] = {
        "hwnd": None,
        "action_kind": "click",
        "dialog_title": None,
        "dialog_class_name": None,
        "dialog_process": None,
        "name": None,
        "automation_id": None,
        "control_type": None,
        "class_name": None,
        "index": None,
        "match": "contains",
        "text": None,
        "item": None,
        "row": None,
        "column": None,
        "row_text": None,
        "column_name": None,
        "control_action": "invoke",
        "cell_action": "get",
        "mode": "set-text",
        "timeout": 10.0,
        "action_timeout": 5.0,
        "interval": 0.25,
        "input_timeout": 1.0,
        "timeout_ms": 500,
        "verify": True,
        "diagnostic": False,
        "allow_focus_fallback": False,
        "allow_coordinate_fallback": False,
        "skip_uia": False,
        "include_invisible": False,
        "stable_ticks": 2,
        "activate": True,
        "button": "left",
        "clicks": 1,
        "repair": None,
        "repair_timeout": None,
    }
    if args and not args[0].startswith("--"):
        try:
            options["hwnd"] = int(args[0], 0)
            args = args[1:]
        except ValueError:
            options["action_kind"] = args[0]
            args = args[1:]
    if args and not args[0].startswith("--"):
        options["action_kind"] = args[0]
        args = args[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--hwnd" and i + 1 < len(args):
            options["hwnd"] = int(args[i + 1], 0)
            i += 2
        elif arg in ("--kind", "--action-kind", "--action_kind", "--dialog-action", "--dialog_action") and i + 1 < len(args):
            options["action_kind"] = args[i + 1]
            i += 2
        elif arg in ("--dialog-title", "--dialog_title", "--title") and i + 1 < len(args):
            options["dialog_title"] = args[i + 1]
            i += 2
        elif arg in ("--dialog-class", "--dialog-class-name", "--dialog_class", "--dialog_class_name") and i + 1 < len(args):
            options["dialog_class_name"] = args[i + 1]
            i += 2
        elif arg in ("--dialog-process", "--dialog_process", "--process") and i + 1 < len(args):
            options["dialog_process"] = args[i + 1]
            i += 2
        elif arg == "--name" and i + 1 < len(args):
            options["name"] = args[i + 1]
            i += 2
        elif arg in ("--automation-id", "--automation_id") and i + 1 < len(args):
            options["automation_id"] = args[i + 1]
            i += 2
        elif arg in ("--type", "--control-type", "--control_type") and i + 1 < len(args):
            options["control_type"] = args[i + 1]
            i += 2
        elif arg in ("--class", "--class-name", "--class_name") and i + 1 < len(args):
            options["class_name"] = args[i + 1]
            i += 2
        elif arg == "--index" and i + 1 < len(args):
            options["index"] = int(args[i + 1])
            i += 2
        elif arg == "--match" and i + 1 < len(args):
            options["match"] = args[i + 1]
            i += 2
        elif arg == "--exact":
            options["match"] = "exact"
            i += 1
        elif arg == "--regex":
            options["match"] = "regex"
            i += 1
        elif arg in ("--text", "--value") and i + 1 < len(args):
            options["text"] = args[i + 1]
            i += 2
        elif arg == "--item" and i + 1 < len(args):
            options["item"] = args[i + 1]
            i += 2
        elif arg == "--row" and i + 1 < len(args):
            options["row"] = int(args[i + 1])
            i += 2
        elif arg in ("--column", "--col") and i + 1 < len(args):
            options["column"] = int(args[i + 1])
            i += 2
        elif arg in ("--row-text", "--row_text") and i + 1 < len(args):
            options["row_text"] = args[i + 1]
            i += 2
        elif arg in ("--column-name", "--column_name", "--header") and i + 1 < len(args):
            options["column_name"] = args[i + 1]
            i += 2
        elif arg in ("--control-action", "--control_action", "--click-action", "--click_action", "--action") and i + 1 < len(args):
            options["control_action"] = args[i + 1]
            i += 2
        elif arg in ("--cell-action", "--cell_action") and i + 1 < len(args):
            options["cell_action"] = args[i + 1]
            i += 2
        elif arg == "--mode" and i + 1 < len(args):
            options["mode"] = args[i + 1]
            i += 2
        elif arg == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif arg in ("--action-timeout", "--action_timeout") and i + 1 < len(args):
            options["action_timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif arg in ("--input-timeout", "--input_timeout") and i + 1 < len(args):
            options["input_timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--timeout-ms" and i + 1 < len(args):
            options["timeout_ms"] = int(args[i + 1])
            i += 2
        elif arg == "--button" and i + 1 < len(args):
            options["button"] = args[i + 1]
            i += 2
        elif arg == "--clicks" and i + 1 < len(args):
            options["clicks"] = int(args[i + 1])
            i += 2
        elif arg in ("--diagnostic", "--verbose"):
            options["diagnostic"] = True
            i += 1
        elif arg == "--allow-focus-fallback":
            options["allow_focus_fallback"] = True
            i += 1
        elif arg == "--allow-coordinate-fallback":
            options["allow_coordinate_fallback"] = True
            i += 1
        elif arg in ("--skip-uia", "--no-uia"):
            options["skip_uia"] = True
            i += 1
        elif arg in ("--repair", "--selector-repair", "--selector_repair", "--action-repair", "--action_repair"):
            options["repair"] = True
            i += 1
        elif arg in ("--no-repair", "--no-selector-repair", "--no-action-repair"):
            options["repair"] = False
            i += 1
        elif arg in ("--repair-timeout", "--repair_timeout", "--selector-repair-timeout", "--selector_repair_timeout", "--action-repair-timeout", "--action_repair_timeout") and i + 1 < len(args):
            options["repair_timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--include-invisible":
            options["include_invisible"] = True
            i += 1
        elif arg in ("--stable-ticks", "--stable_ticks", "--dialog-stable-ticks", "--dialog_stable_ticks") and i + 1 < len(args):
            options["stable_ticks"] = int(args[i + 1])
            i += 2
        elif arg == "--no-activate":
            options["activate"] = False
            i += 1
        elif arg == "--no-verify":
            options["verify"] = False
            i += 1
        elif options.get("text") is None and str(options.get("action_kind") or "").lower().replace("-", "_") in ("text", "input", "set_text"):
            options["text"] = arg
            i += 1
        elif options.get("name") is None:
            options["name"] = arg
            i += 1
        else:
            i += 1
    return _smart_cli_finalize_repair_options(options)


def _parse_dialog_button_cli_args(raw_args: List[str]) -> Dict[str, Any]:
    args = list(raw_args)
    options: Dict[str, Any] = {
        "hwnd": None,
        "name": None,
        "dialog_title": None,
        "dialog_class_name": None,
        "dialog_process": None,
        "automation_id": None,
        "class_name": None,
        "control_type": "button",
        "index": None,
        "match": "contains",
        "timeout": 10.0,
        "interval": 0.25,
        "timeout_ms": 500,
        "include_invisible": False,
        "activate": True,
        "action": None,
        "command_id": None,
        "verify_close": False,
        "prefer_command": True,
        "diagnostic": False,
    }
    if args and not args[0].startswith("--"):
        try:
            options["hwnd"] = int(args[0], 0)
            args = args[1:]
        except ValueError:
            options["name"] = args[0]
            args = args[1:]
    if args and not args[0].startswith("--") and options.get("name") is None:
        options["name"] = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--hwnd" and i + 1 < len(args):
            options["hwnd"] = int(args[i + 1], 0)
            i += 2
        elif arg in ("--name", "--text", "--value") and i + 1 < len(args):
            options["name"] = args[i + 1]
            i += 2
        elif arg in ("--action", "--command") and i + 1 < len(args):
            options["action"] = args[i + 1]
            i += 2
        elif arg in ("--command-id", "--command_id", "--id") and i + 1 < len(args):
            options["command_id"] = int(args[i + 1], 0)
            i += 2
        elif arg in ("--dialog-title", "--dialog_title", "--title") and i + 1 < len(args):
            options["dialog_title"] = args[i + 1]
            i += 2
        elif arg in ("--dialog-class", "--dialog-class-name", "--dialog_class", "--dialog_class_name") and i + 1 < len(args):
            options["dialog_class_name"] = args[i + 1]
            i += 2
        elif arg in ("--dialog-process", "--dialog_process", "--process") and i + 1 < len(args):
            options["dialog_process"] = args[i + 1]
            i += 2
        elif arg in ("--automation-id", "--automation_id") and i + 1 < len(args):
            options["automation_id"] = args[i + 1]
            i += 2
        elif arg in ("--type", "--control-type", "--control_type") and i + 1 < len(args):
            options["control_type"] = args[i + 1]
            i += 2
        elif arg in ("--class", "--class-name", "--class_name") and i + 1 < len(args):
            options["class_name"] = args[i + 1]
            i += 2
        elif arg == "--index" and i + 1 < len(args):
            options["index"] = int(args[i + 1])
            i += 2
        elif arg == "--match" and i + 1 < len(args):
            options["match"] = args[i + 1]
            i += 2
        elif arg == "--exact":
            options["match"] = "exact"
            i += 1
        elif arg == "--regex":
            options["match"] = "regex"
            i += 1
        elif arg == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif arg == "--timeout-ms" and i + 1 < len(args):
            options["timeout_ms"] = int(args[i + 1])
            i += 2
        elif arg in ("--include-invisible", "--include_invisible"):
            options["include_invisible"] = True
            i += 1
        elif arg == "--no-activate":
            options["activate"] = False
            i += 1
        elif arg in ("--verify-close", "--verify_close"):
            options["verify_close"] = True
            i += 1
        elif arg in ("--no-command", "--no-prefer-command", "--no_command", "--no_prefer_command"):
            options["prefer_command"] = False
            i += 1
        elif arg in ("--diagnostic", "--verbose"):
            options["diagnostic"] = True
            i += 1
        elif options.get("name") is None:
            options["name"] = arg
            i += 1
        else:
            i += 1
    return options


def _parse_win32_control_find_cli_args(raw_args: List[str]) -> Dict[str, Any]:
    args = list(raw_args)
    options: Dict[str, Any] = {
        "hwnd": None,
        "name": None,
        "automation_id": None,
        "control_type": None,
        "class_name": None,
        "text": None,
        "value": None,
        "state": None,
        "expected": None,
        "match": "contains",
        "include_invisible": False,
        "include_self": True,
        "limit": 20,
        "min_score": None,
        "timeout": 3.0,
        "interval": 0.1,
        "timeout_ms": 250,
        "max_items": 200,
        "max_children": 1000,
        "diagnostic": False,
        "repair": None,
        "repair_timeout": None,
    }
    if args and not args[0].startswith("--"):
        options["hwnd"] = int(args[0], 0)
        args = args[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--hwnd" and i + 1 < len(args):
            options["hwnd"] = int(args[i + 1], 0)
            i += 2
        elif arg in ("--name", "--title") and i + 1 < len(args):
            options["name"] = args[i + 1]
            i += 2
        elif arg in ("--automation-id", "--automation_id", "--id", "--control-id", "--control_id") and i + 1 < len(args):
            options["automation_id"] = args[i + 1]
            i += 2
        elif arg in ("--type", "--control-type", "--control_type", "--kind") and i + 1 < len(args):
            options["control_type"] = args[i + 1]
            i += 2
        elif arg in ("--class", "--class-name", "--class_name") and i + 1 < len(args):
            options["class_name"] = args[i + 1]
            i += 2
        elif arg in ("--text", "--item") and i + 1 < len(args):
            options["text"] = args[i + 1]
            i += 2
        elif arg == "--value" and i + 1 < len(args):
            options["value"] = args[i + 1]
            i += 2
        elif arg == "--state" and i + 1 < len(args):
            options["state"] = args[i + 1]
            i += 2
        elif arg in ("--expected", "--checked") and i + 1 < len(args):
            options["expected"] = args[i + 1]
            i += 2
        elif arg == "--match" and i + 1 < len(args):
            options["match"] = args[i + 1]
            i += 2
        elif arg == "--limit" and i + 1 < len(args):
            options["limit"] = int(args[i + 1])
            i += 2
        elif arg == "--min-score" and i + 1 < len(args):
            options["min_score"] = int(args[i + 1])
            i += 2
        elif arg == "--timeout" and i + 1 < len(args):
            options["timeout"] = float(args[i + 1])
            i += 2
        elif arg == "--interval" and i + 1 < len(args):
            options["interval"] = float(args[i + 1])
            i += 2
        elif arg == "--timeout-ms" and i + 1 < len(args):
            options["timeout_ms"] = int(args[i + 1])
            i += 2
        elif arg == "--max-items" and i + 1 < len(args):
            options["max_items"] = int(args[i + 1])
            i += 2
        elif arg == "--max-children" and i + 1 < len(args):
            options["max_children"] = int(args[i + 1])
            i += 2
        elif arg in ("--include-invisible", "--include_invisible"):
            options["include_invisible"] = True
            i += 1
        elif arg in ("--no-self", "--no_self"):
            options["include_self"] = False
            i += 1
        elif arg == "--exact":
            options["match"] = "exact"
            i += 1
        elif arg == "--regex":
            options["match"] = "regex"
            i += 1
        elif arg in ("--diagnostic", "--verbose"):
            options["diagnostic"] = True
            i += 1
        elif arg == "--repair":
            options["repair"] = True
            i += 1
        elif arg == "--no-repair":
            options["repair"] = False
            i += 1
        elif arg == "--repair-timeout" and i + 1 < len(args):
            options["repair_timeout"] = float(args[i + 1])
            i += 2
        elif options.get("name") is None:
            options["name"] = arg
            i += 1
        else:
            i += 1
    if options["hwnd"] is None:
        print("Error: hwnd required")
        sys.exit(1)
    return options



