"""
Centralized Dynamic Symbol Resolver for Backward Compatibility.
Supports PEP 562 module __getattr__ and __dir__ in root server.py and tools.py.
"""
from __future__ import annotations

import importlib
from typing import Any, Dict, List, Optional

# Static Fast-Lookup Tables for frequently accessed root symbols
_SERVER_FAST_MAP: Dict[str, str] = {
    "_enum_windows": "win_automation.win32.window:enum_windows",
    "enum_windows": "win_automation.win32.window:enum_windows",
    "_get_window": "win_automation.win32.window:get_window_info",
    "get_window": "win_automation.win32.window:get_window_info",
    "_foreground_window": "win_automation.win32.window:foreground_window",
    "foreground_window": "win_automation.win32.window:foreground_window",
    "_capture_window_screenshot": "win_automation.vision.capture:capture_window_screenshot",
    "capture_window_screenshot": "win_automation.vision.capture:capture_window_screenshot",
    "_capture_desktop_screenshot": "win_automation.vision.capture:capture_desktop_screenshot",
    "capture_desktop_screenshot": "win_automation.vision.capture:capture_desktop_screenshot",
    "_build_accessibility_tree": "win_automation.uia.tree:build_accessibility_tree",
    "build_accessibility_tree": "win_automation.uia.tree:build_accessibility_tree",
    "_check_safety": "win_automation.safety.gate:check_safety",
    "check_safety": "win_automation.safety.gate:check_safety",
    "_load_state": "win_automation.state.persistence:load_state",
    "_save_state": "win_automation.state.persistence:save_state",
    "load_state": "win_automation.state.persistence:load_state",
    "save_state": "win_automation.state.persistence:save_state",
    "STATE_FILE": "win_automation.state.persistence:STATE_FILE",
    "DEFAULT_STATE_FILE": "win_automation.state.persistence:DEFAULT_STATE_FILE",
    "HELPER_URL": "win_automation.helper.client:HELPER_URL",
    "ELEVATED_HELPER_URL": "win_automation.helper.client:ELEVATED_HELPER_URL",
    "execute_batch": "win_automation.batch.engine:execute_batch",
    "execute_batch_file": "win_automation.batch.engine:execute_batch_file",
}

_TOOLS_FAST_MAP: Dict[str, str] = {
    **_SERVER_FAST_MAP,
    # 19 Expert Profile Remediated Mappings
    "list_windows": "win_automation.win32.window:enum_windows",
    "screen_info": "win_automation.core.dpi:screen_info",
    "desktop_wait_image": "win_automation.vision.match:desktop_wait_image",
    "desktop_click_image": "win_automation.vision.match:desktop_click_image",
    "element_from_point": "win_automation.uia.engine:element_from_point",
    "get_window_state": "win_automation.vision.capture:get_window_state",
    "wait_image": "win_automation.vision.match:wait_image",
    "click_image": "win_automation.vision.match:click_image",
    "desktop_find_text_ocr": "win_automation.ocr.finder:desktop_find_text_ocr",
    "find_text_ocr": "win_automation.ocr.finder:find_text_ocr",
    "wait_text_ocr": "win_automation.ocr.finder:wait_text_ocr",
    "desktop_wait_text_ocr": "win_automation.ocr.finder:desktop_wait_text_ocr",
    "click_text_ocr": "win_automation.ocr.finder:click_text_ocr",
    "desktop_click_text_ocr": "win_automation.ocr.finder:desktop_click_text_ocr",
    "desktop_get_element": "win_automation.uia.tree:desktop_get_element",
    "desktop_click_element": "win_automation.uia.patterns:desktop_click_element",
    "desktop_action": "win_automation.uia.patterns:desktop_action",
    "find_item_in_container": "win_automation.uia.patterns:find_item_in_container",
    "perform_secondary_action": "win_automation.uia.patterns:perform_secondary_action",
    "item_container_find": "win_automation.uia.patterns:item_container_find",

    "selftest_selector": "win_automation.diagnostics.selftest:selftest_selector",
    "selftest_batch": "win_automation.diagnostics.selftest:selftest_batch",
    "selftest_server_contracts": "win_automation.diagnostics.selftest:selftest_server_contracts",
    "selftest_clipboard": "win_automation.diagnostics.selftest:selftest_clipboard",
    "selftest_notepad": "win_automation.diagnostics.selftest:selftest_notepad",
    "selftest_ocr": "win_automation.diagnostics.selftest:selftest_ocr",
    "selftest_win32": "win_automation.diagnostics.selftest:selftest_win32",
    "selftest_uia_patterns": "win_automation.diagnostics.selftest:selftest_uia_patterns",
    "selftest": "win_automation.diagnostics.selftest:selftest",
    "doctor": "win_automation.diagnostics.doctor:doctor",
    "run_doctor": "win_automation.diagnostics.doctor:run_doctor",
    "control_boundary": "win_automation.win32.window:control_boundary",
    "gui_thread_info": "win_automation.win32.window:gui_thread_info",
    "smart_text_input": "win_automation.input.smart_input:smart_text_input",
    "smart_click": "win_automation.input.smart_input:smart_click",
    "smart_select": "win_automation.input.smart_input:smart_select",
    "smart_cell": "win_automation.input.smart_input:smart_cell",
    "smart_dialog_action": "win_automation.input.smart_input:smart_dialog_action",
    "type_text": "win_automation.input.keyboard:type_text",
    "press_key": "win_automation.input.keyboard:press_key",
    "click": "win_automation.input.mouse:click",
    "move_mouse": "win_automation.input.mouse:move_mouse",
    "scroll": "win_automation.input.mouse:scroll",
    "drag": "win_automation.input.mouse:drag",
    "observe": "win_automation.vision.capture:observe_window",
    "screenshot": "win_automation.vision.capture:capture_window_screenshot",
    "desktop_screenshot": "win_automation.vision.capture:capture_desktop_screenshot",
    "ocr": "win_automation.ocr.finder:run_ocr",
    "desktop_ocr": "win_automation.ocr.finder:run_desktop_ocr",
}

# Submodules scanned dynamically on Tier 2 fallback
_FALLBACK_MODULES = [
    "win_automation.core.types",
    "win_automation.core.win32_structures",
    "win_automation.core.dpi",
    "win_automation.core.utils",
    "win_automation.win32.window",
    "win_automation.win32.controls",
    "win_automation.win32.dialog",
    "win_automation.win32.menu",
    "win_automation.win32.find",
    "win_automation.uia.tree",
    "win_automation.uia.engine",
    "win_automation.uia.patterns",
    "win_automation.uia.repair",
    "win_automation.uia.cache",
    "win_automation.msaa.accessible",
    "win_automation.vision.capture",
    "win_automation.vision.pixel",
    "win_automation.vision.stability",
    "win_automation.vision.match",
    "win_automation.vision.visual_row",
    "win_automation.ocr.finder",
    "win_automation.input.keyboard",
    "win_automation.input.mouse",
    "win_automation.input.clipboard",
    "win_automation.input.smart_input",
    "win_automation.safety.gate",
    "win_automation.state.persistence",
    "win_automation.helper.client",
    "win_automation.batch.engine",
    "win_automation.batch.evaluator",
    "win_automation.diagnostics.doctor",
    "win_automation.diagnostics.selftest",
]


def _import_target(spec: str) -> Any:
    mod_name, attr_name = spec.split(":")
    mod = importlib.import_module(mod_name)
    return getattr(mod, attr_name)


def resolve_server_symbol(name: str) -> Any:
    """Resolve attribute for server.py."""
    if name in _SERVER_FAST_MAP:
        return _import_target(_SERVER_FAST_MAP[name])

    alt_name = name[1:] if name.startswith("_") else f"_{name}"
    if alt_name in _SERVER_FAST_MAP:
        return _import_target(_SERVER_FAST_MAP[alt_name])

    for mod_path in _FALLBACK_MODULES:
        try:
            mod = importlib.import_module(mod_path)
            if hasattr(mod, name):
                return getattr(mod, name)
            if hasattr(mod, alt_name):
                return getattr(mod, alt_name)
        except Exception:
            continue
    return None


def resolve_tools_symbol(name: str) -> Any:
    """Resolve attribute for tools.py."""
    if name in _TOOLS_FAST_MAP:
        return _import_target(_TOOLS_FAST_MAP[name])

    alt_name = name[1:] if name.startswith("_") else f"_{name}"
    if alt_name in _TOOLS_FAST_MAP:
        return _import_target(_TOOLS_FAST_MAP[alt_name])

    for mod_path in _FALLBACK_MODULES:
        try:
            mod = importlib.import_module(mod_path)
            if hasattr(mod, name):
                return getattr(mod, name)
            if hasattr(mod, alt_name):
                return getattr(mod, alt_name)
        except Exception:
            continue
    return None


def get_server_all_symbols(existing_keys: List[str]) -> List[str]:
    """Compile list of available attributes for server.py __dir__."""
    return sorted(list(set(existing_keys + list(_SERVER_FAST_MAP.keys()))))


def get_tools_all_symbols(existing_keys: List[str]) -> List[str]:
    """Compile list of available attributes for tools.py __dir__."""
    return sorted(list(set(existing_keys + list(_TOOLS_FAST_MAP.keys()))))
