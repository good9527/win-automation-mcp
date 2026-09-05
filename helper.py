"""
Windows Automation Helper Server
Runs as a persistent background process in the desktop session.
Accepts HTTP commands from tools.py and executes them via SendInput.

Usage: python helper.py [--port 18765]
"""

import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import sys
import subprocess
import time
import io
import base64
import threading
import atexit
import re
import importlib.util
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from win_automation.helper.security import generate_session_token, verify_request

EXPECTED_TOKEN: str = os.environ.get("WIN_AUTOMATION_HELPER_TOKEN", "")

HELPER_STARTED_AT = time.time()
_TOOLS_MODULE = None
UIA_WORKER_DEFAULT_TIMEOUT = 4.0
_BATCH_COMMAND_TO_PATH = {
    "activate": "/activate",
    "move": "/move",
    "click": "/click",
    "type": "/type_text",
    "key": "/press_key",
    "scroll": "/scroll",
    "drag": "/drag",
    "win32_text": "/win32_text",
    "win32_set_text": "/win32_set_text",
    "win32_click": "/win32_click",
    "win32_control_find": "/win32_control_find",
    "win32_selector_repair_find": "/win32_selector_repair_find",
    "win32_control_wait_find": "/win32_control_wait_find",
    "win32_control_info": "/win32_control_info",
    "win32_control_action": "/win32_control_action",
    "win32_control_wait": "/win32_control_wait",
    "menu_tree": "/menu_tree",
    "menu_action": "/menu_action",
    "dialog_command_action": "/dialog_command_action",
    "dialog_button_action": "/dialog_button_action",
    "file_dialog_info": "/file_dialog_info",
    "file_dialog_action": "/file_dialog_action",
    "msaa_window": "/msaa_window",
    "msaa_from_point": "/msaa_from_point",
    "msaa_action": "/msaa_action",
    "child_windows": "/child_windows",
    "window_from_point": "/window_from_point",
    "uia_accessibility": "/uia_accessibility",
    "uia_find": "/uia_find",
    "uia_wait": "/uia_wait",
    "uia_element": "/uia_element",
    "uia_focus": "/uia_focus",
    "uia_click_index": "/uia_click_index",
    "uia_set_value": "/uia_set_value",
    "uia_action": "/uia_action",
    "uia_item_container_find": "/uia_item_container_find",
    "uia_selector_repair_find": "/uia_selector_repair_find",
    "uia_cell_selector_repair_find": "/uia_cell_selector_repair_find",
    "smart_click": "/smart_click",
    "smart_wait_click": "/smart_wait_click",
    "smart_text": "/smart_text",
    "smart_wait_text": "/smart_wait_text",
    "smart_select": "/smart_select",
    "smart_wait_select": "/smart_wait_select",
    "smart_cell": "/smart_cell",
    "smart_wait_cell": "/smart_wait_cell",
    "clipboard": "/clipboard",
    "set_clipboard": "/set_clipboard",
}
_BATCH_COMMAND_ALIASES = {
    "activate_window": "activate",
    "move_mouse": "move",
    "mouse_move": "move",
    "hover": "move",
    "mouse_hover": "move",
    "type_text": "type",
    "press_key": "key",
    "win32_find_control": "win32_control_find",
    "find_win32_control": "win32_control_find",
    "native_control_find": "win32_control_find",
    "find_native_control": "win32_control_find",
    "win32_repair_find": "win32_selector_repair_find",
    "win32_selector_repair": "win32_selector_repair_find",
    "native_repair_find": "win32_selector_repair_find",
    "native_selector_repair_find": "win32_selector_repair_find",
    "native_selector_repair": "win32_selector_repair_find",
    "win32_wait_find": "win32_control_wait_find",
    "win32_wait_control_find": "win32_control_wait_find",
    "wait_win32_control_find": "win32_control_wait_find",
    "wait_native_control_find": "win32_control_wait_find",
    "native_control_wait_find": "win32_control_wait_find",
    "win32_wait_control": "win32_control_wait",
    "win32_wait_state": "win32_control_wait",
    "win32_control_state_wait": "win32_control_wait",
    "wait_win32_control": "win32_control_wait",
    "wait_native_control": "win32_control_wait",
    "native_control_wait": "win32_control_wait",
    "find": "uia_find",
    "find_elements": "uia_find",
    "wait": "uia_wait",
    "wait_for_element": "uia_wait",
    "get_element": "uia_element",
    "element": "uia_element",
    "focus": "uia_focus",
    "focus_element": "uia_focus",
    "click_index": "uia_click_index",
    "click_element": "uia_click_index",
    "set_value": "uia_set_value",
    "set_element_value": "uia_set_value",
    "action": "uia_action",
    "perform_secondary_action": "uia_action",
    "secondary_action": "uia_action",
    "item_container_find": "uia_item_container_find",
    "find_item_in_container": "uia_item_container_find",
    "uia_repair_find": "uia_selector_repair_find",
    "uia_cell_repair_find": "uia_cell_selector_repair_find",
    "smart_text_input": "smart_text",
    "smart_wait_text_input": "smart_wait_text",
    "smart_control_action": "smart_click",
    "smart_wait_control_action": "smart_wait_click",
    "smart_select_item": "smart_select",
    "smart_wait_select_item": "smart_wait_select",
    "smart_grid_cell": "smart_cell",
    "smart_listview_cell": "smart_cell",
    "smart_wait_grid_cell": "smart_wait_cell",
    "smart_wait_listview_cell": "smart_wait_cell",
    "dialog_command": "dialog_command_action",
    "native_dialog_command": "dialog_command_action",
    "messagebox_command": "dialog_command_action",
    "message_box_command": "dialog_command_action",
    "dialog_button": "dialog_button_action",
    "native_dialog_button": "dialog_button_action",
    "messagebox_button": "dialog_button_action",
    "message_box_button": "dialog_button_action",
}


def _normalize_batch_command_name(command_name):
    text = str(command_name or "").strip()
    if not text:
        return ""
    underscore = text.replace("-", "_")
    if underscore in _BATCH_COMMAND_TO_PATH:
        return underscore
    return _BATCH_COMMAND_ALIASES.get(underscore, text)


def _normalize_batch_path(path):
    text = str(path or "").strip()
    if not text:
        return ""
    known_paths = set(_BATCH_COMMAND_TO_PATH.values())
    if text in known_paths:
        return text
    path_name = text.lstrip("/").replace("-", "_")
    command_name = _normalize_batch_command_name(path_name)
    if command_name in _BATCH_COMMAND_TO_PATH:
        return _BATCH_COMMAND_TO_PATH[command_name]
    candidate = "/" + path_name
    return candidate if candidate in known_paths else text


def _file_sha256(path: str) -> str:
    """Hash a source file so tools.py can detect stale resident helpers."""
    try:
        with open(os.path.abspath(path), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


def _helper_source_hash() -> str:
    return _file_sha256(__file__)


def _tools_source_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools.py")


def _tools_source_hash() -> str:
    return _file_sha256(_tools_source_path())


HELPER_SOURCE_HASH = _helper_source_hash()
TOOLS_SOURCE_PATH = os.path.abspath(_tools_source_path())
TOOLS_SOURCE_HASH = _tools_source_hash()


def _load_tools_module():
    global _TOOLS_MODULE
    if _TOOLS_MODULE is not None:
        return _TOOLS_MODULE
    tools_path = TOOLS_SOURCE_PATH
    previous = os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER")
    os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = "1"
    try:
        spec = importlib.util.spec_from_file_location("_win_automation_tools_for_helper", tools_path)
        if not spec or not spec.loader:
            raise RuntimeError(f"Cannot load tools.py from {tools_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TOOLS_MODULE = module
        return module
    finally:
        if previous is None:
            os.environ.pop("WIN_AUTOMATION_HELPER_NO_REENTER", None)
        else:
            os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = previous


def _call_tools_no_reenter(func, *args, **kwargs):
    previous = os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER")
    os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = "1"
    try:
        return func(*args, **kwargs)
    finally:
        if previous is None:
            os.environ.pop("WIN_AUTOMATION_HELPER_NO_REENTER", None)
        else:
            os.environ["WIN_AUTOMATION_HELPER_NO_REENTER"] = previous


def _coerce_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on", "enable", "enabled"):
        return True
    if text in ("0", "false", "no", "n", "off", "disable", "disabled", "none", "null"):
        return False
    return bool(default)


def _dict_get_any(data, *keys, default=None):
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def _repair_timeout_value(value, default: float = 0.0) -> float:
    try:
        return max(float(value), 0.0)
    except Exception:
        return float(default)


def _repair_worker_budget(data: dict, default_repair_budget: float = 1.0) -> float:
    raw_repair_timeout = _dict_get_any(
        data,
        "repair_timeout",
        "repair-timeout",
        "selector_repair_timeout",
        "selector-repair-timeout",
    )
    raw_repair = _dict_get_any(data, "repair", "selector_repair", "selector-repair")
    repair_requested = _coerce_bool(raw_repair, False) if raw_repair is not None else raw_repair_timeout is not None
    if not repair_requested:
        return 0.0
    if raw_repair_timeout is not None:
        return _repair_timeout_value(raw_repair_timeout, 0.0)
    return _repair_timeout_value(default_repair_budget, 0.0)


def _repair_worker_timeout(data: dict, base_timeout: float = UIA_WORKER_DEFAULT_TIMEOUT, default_repair_budget: float = 1.0) -> float:
    try:
        base_value = float(base_timeout)
    except Exception:
        base_value = UIA_WORKER_DEFAULT_TIMEOUT
    repair_budget = _repair_worker_budget(data, default_repair_budget=default_repair_budget)
    return float(data.get("uia_timeout", max(base_value + repair_budget + 1.0, UIA_WORKER_DEFAULT_TIMEOUT)) or UIA_WORKER_DEFAULT_TIMEOUT)


def _smart_repair_worker_timeout(data: dict, base_timeout: float = UIA_WORKER_DEFAULT_TIMEOUT) -> float:
    return _repair_worker_timeout(data, base_timeout=base_timeout, default_repair_budget=1.0)


def _wait_repair_worker_timeout(data: dict, timeout_value: float) -> float:
    timeout_value = _repair_timeout_value(timeout_value, 0.0)
    return _repair_worker_timeout(
        data,
        base_timeout=timeout_value,
        default_repair_budget=min(timeout_value, 1.0),
    )


def _batch_normalize_result(result):
    if isinstance(result, dict):
        return result
    if result is None:
        return {"ok": False, "error": "empty_result", "result_type": "NoneType"}
    if isinstance(result, str):
        text = result.strip()
        if text.lower().startswith("error"):
            error = text.split(":", 1)[1].strip() if ":" in text else text
            return {"ok": False, "error": error or "error", "message": result}
        if text.lower().startswith("warning") and "clipboard restore may be incomplete" in text.lower():
            error = text.split(":", 1)[1].strip() if ":" in text else text
            return {
                "ok": False,
                "error": error or "clipboard_restore_incomplete",
                "message": result,
                "warning": True,
                "clipboard_restore_ok": False,
            }
        return {"ok": True, "message": result}
    return {"ok": True, "value": result, "result_type": type(result).__name__}


def _batch_normalize_item(item, fallback_index):
    normalized = dict(item) if isinstance(item, dict) else {"result": item}
    normalized.setdefault("index", fallback_index)
    normalized["result"] = _batch_normalize_result(normalized.get("result"))
    return {k: v for k, v in normalized.items() if v is not None}


def _batch_invalid_item(index, item):
    return _batch_normalize_item(
        {
            "index": index,
            "command": None,
            "path": None,
            "result": {
                "ok": False,
                "error": "invalid_batch_item",
                "message": "batch item must be a JSON object",
                "item_type": type(item).__name__,
            },
        },
        index,
    )


def _batch_item_args(item, use_data=False):
    if use_data:
        key = "data" if "data" in item else "args"
    else:
        key = "args" if "args" in item else "data"
    args = item.get(key, {})
    if args is None:
        return {}
    if isinstance(args, dict):
        return args
    return {"__batch_arg_error__": f"{key} must be a JSON object", "__batch_arg_type__": type(args).__name__}


def _batch_arg_error(args):
    if "__batch_arg_error__" not in args:
        return None
    return {
        "ok": False,
        "error": "invalid_batch_args",
        "message": str(args.get("__batch_arg_error__") or "args must be a JSON object"),
        "args_type": args.get("__batch_arg_type__"),
    }


def _batch_step_id(item):
    for key in ("id", "as", "name", "label"):
        value = item.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _batch_find_result_by_id(results, step_id):
    for item in reversed(results):
        if isinstance(item, dict) and str(item.get("id", "")) == step_id:
            return True, item
    return False, None


def _batch_context_value(path, results):
    if path == "$steps":
        return True, results
    if not isinstance(path, str) or not path.startswith("$steps."):
        return False, None
    current = results
    parts = path[len("$steps."):].split(".")
    if parts and parts[0] != "":
        try:
            current = current[int(parts[0])]
            parts = parts[1:]
        except Exception:
            found, current = _batch_find_result_by_id(results, parts[0])
            if not found:
                return False, None
            parts = parts[1:]
    for part in parts:
        if part == "":
            return False, None
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except Exception:
                return False, None
        elif isinstance(current, dict):
            if part not in current:
                return False, None
            current = current.get(part)
        else:
            return False, None
    return True, current


def _batch_resolve_refs(value, results):
    if isinstance(value, str):
        found, resolved = _batch_context_value(value, results)
        return resolved if found else value
    if isinstance(value, list):
        return [_batch_resolve_refs(item, results) for item in value]
    if isinstance(value, dict):
        return {key: _batch_resolve_refs(item, results) for key, item in value.items()}
    return value


def _batch_traverse_value(current, path):
    for part in str(path or "").split("."):
        if part == "":
            return False, None
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except Exception:
                return False, None
        elif isinstance(current, dict):
            if part not in current:
                return False, None
            current = current.get(part)
        else:
            return False, None
    return True, current


def _batch_expect_path_value(path, result, results):
    if not isinstance(path, str):
        return True, path
    if path == "$result":
        return True, result
    if path.startswith("$result."):
        return _batch_traverse_value(result, path[len("$result."):])
    if path == "$steps" or path.startswith("$steps."):
        return _batch_context_value(path, results)
    return _batch_traverse_value(result, path)


def _batch_resolve_expect_value(value, result, results):
    if isinstance(value, str) and (value == "$result" or value.startswith("$result.") or value == "$steps" or value.startswith("$steps.")):
        found, resolved = _batch_expect_path_value(value, result, results)
        return resolved if found else value
    if isinstance(value, list):
        return [_batch_resolve_expect_value(item, result, results) for item in value]
    if isinstance(value, dict):
        return {key: _batch_resolve_expect_value(item, result, results) for key, item in value.items()}
    return value


def _batch_diag_value(value):
    if isinstance(value, str):
        if len(value) > 500:
            return {"type": "str", "length": len(value), "prefix": value[:500]}
        return value
    if isinstance(value, list):
        if len(value) > 20:
            return {"type": "list", "length": len(value), "sample": [_batch_diag_value(item) for item in value[:5]]}
        return [_batch_diag_value(item) for item in value]
    if isinstance(value, dict):
        keys = list(value.keys())
        if len(keys) > 20:
            return {"type": "dict", "keys": keys[:20], "omitted_keys": len(keys) - 20}
        return {key: _batch_diag_value(item) for key, item in value.items()}
    return value


def _batch_expect_contains(actual, expected):
    try:
        if isinstance(actual, str):
            return str(expected) in actual
        if isinstance(actual, dict):
            return expected in actual or expected in actual.values()
        return expected in actual
    except Exception:
        return False


def _batch_expect_len(value):
    try:
        return len(value)
    except Exception:
        return None


def _batch_expect_number(value):
    return float(value)


def _batch_expect_contains_all(actual, expected):
    values = expected if isinstance(expected, list) else [expected]
    return all(_batch_expect_contains(actual, item) for item in values)


def _batch_expect_contains_any(actual, expected):
    values = expected if isinstance(expected, list) else [expected]
    return any(_batch_expect_contains(actual, item) for item in values)


def _batch_expect_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _batch_expectation_spec(item):
    for key in ("expect", "expects", "assert", "assertion"):
        if key in item:
            return item.get(key)
    return None


def _batch_evaluate_expectation(expectation, result, results):
    if not isinstance(expectation, dict):
        return [{
            "ok": False,
            "error": "invalid_expectation",
            "message": "expectation must be a JSON object",
            "expectation_type": type(expectation).__name__,
        }]

    path = expectation.get("path", "$result")
    found, actual = _batch_expect_path_value(path, result, results)
    operator_keys = [
        key for key in (
            "exists", "equals", "eq", "not_equals", "not-equals", "ne",
            "contains", "not_contains", "not-contains", "contains_any", "contains-any",
            "contains_all", "contains-all", "starts_with", "starts-with", "ends_with",
            "ends-with", "min_len", "min-len", "max_len", "max-len", "len_equals",
            "len-equals", "empty", "not_empty", "not-empty", "gt", "greater_than",
            "greater-than", "gte", "greater_equal", "greater-equal", "min", "lt",
            "less_than", "less-than", "lte", "less_equal", "less-equal", "max",
            "truthy", "regex", "type",
        )
        if key in expectation
    ]
    if not operator_keys:
        operator_keys = ["exists"]
        expectation = {**expectation, "exists": True}

    checks = []
    for operator in operator_keys:
        raw_expected = expectation.get(operator)
        expected = _batch_resolve_expect_value(raw_expected, result, results)
        passed = False
        error = None
        actual_len = None

        try:
            if operator == "exists":
                expected_bool = bool(expected)
                passed = (found and actual is not None) if expected_bool else (not found or actual is None)
            elif not found:
                error = "missing_path"
            elif operator in ("equals", "eq"):
                passed = actual == expected
            elif operator in ("not_equals", "not-equals", "ne"):
                passed = actual != expected
            elif operator == "contains":
                passed = _batch_expect_contains(actual, expected)
            elif operator in ("not_contains", "not-contains"):
                passed = not _batch_expect_contains(actual, expected)
            elif operator in ("contains_any", "contains-any"):
                passed = _batch_expect_contains_any(actual, expected)
            elif operator in ("contains_all", "contains-all"):
                passed = _batch_expect_contains_all(actual, expected)
            elif operator in ("starts_with", "starts-with"):
                passed = str(actual).startswith(str(expected))
            elif operator in ("ends_with", "ends-with"):
                passed = str(actual).endswith(str(expected))
            elif operator in ("min_len", "min-len"):
                actual_len = _batch_expect_len(actual)
                passed = actual_len is not None and actual_len >= int(expected)
            elif operator in ("max_len", "max-len"):
                actual_len = _batch_expect_len(actual)
                passed = actual_len is not None and actual_len <= int(expected)
            elif operator in ("len_equals", "len-equals"):
                actual_len = _batch_expect_len(actual)
                passed = actual_len is not None and actual_len == int(expected)
            elif operator == "empty":
                actual_len = _batch_expect_len(actual)
                passed = (actual_len == 0) is bool(expected)
            elif operator in ("not_empty", "not-empty"):
                actual_len = _batch_expect_len(actual)
                passed = (actual_len is not None and actual_len > 0) is bool(expected)
            elif operator in ("gt", "greater_than", "greater-than"):
                passed = _batch_expect_number(actual) > _batch_expect_number(expected)
            elif operator in ("gte", "greater_equal", "greater-equal", "min"):
                passed = _batch_expect_number(actual) >= _batch_expect_number(expected)
            elif operator in ("lt", "less_than", "less-than"):
                passed = _batch_expect_number(actual) < _batch_expect_number(expected)
            elif operator in ("lte", "less_equal", "less-equal", "max"):
                passed = _batch_expect_number(actual) <= _batch_expect_number(expected)
            elif operator == "truthy":
                passed = bool(actual) is bool(expected)
            elif operator == "regex":
                passed = re.search(str(expected), str(actual)) is not None
            elif operator == "type":
                expected_types = expected if isinstance(expected, list) else [expected]
                passed = _batch_expect_type(actual) in {str(item).lower() for item in expected_types}
            else:
                error = "unknown_expectation_operator"
        except Exception as e:
            error = f"invalid_expectation: {e}"

        check = {
            "ok": bool(passed),
            "path": path,
            "operator": operator,
            "expected": _batch_diag_value(expected),
            "actual": _batch_diag_value(actual) if found else None,
            "found": bool(found),
        }
        if actual_len is not None:
            check["actual_len"] = actual_len
        if error:
            check["error"] = error
        elif not passed:
            check["error"] = "expectation_failed"
        checks.append({k: v for k, v in check.items() if v is not None})
    return checks


def _batch_evaluate_expectations(expectation, result, results):
    expectations = expectation if isinstance(expectation, list) else [expectation]
    checks = []
    for item in expectations:
        checks.extend(_batch_evaluate_expectation(item, result, results))
    return {"ok": all(check.get("ok") is True for check in checks), "checks": checks}


def _batch_apply_expectation(result, expectation, results):
    if expectation is None or _batch_result_failure(result):
        return result
    evaluated = _batch_evaluate_expectations(expectation, result, results)
    checked = dict(result)
    checked["expectation"] = evaluated
    if not evaluated.get("ok"):
        checked["ok"] = False
        checked["error"] = "batch_expectation_failed"
    return checked


def _batch_extract_spec(item):
    for key in ("extract", "select", "pick"):
        if key in item:
            return item.get(key)
    return None


def _batch_extract_value(spec, result, results):
    if isinstance(spec, str):
        found, value = _batch_expect_path_value(spec, result, results)
        if not found:
            return False, None, {"error": "extract_path_missing", "path": spec}
        return True, value, None
    if isinstance(spec, list):
        extracted = []
        for path in spec:
            ok, value, error = _batch_extract_value(path, result, results)
            if not ok:
                return False, None, error
            extracted.append(value)
        return True, extracted, None
    if isinstance(spec, dict):
        extracted = {}
        for key, path in spec.items():
            ok, value, error = _batch_extract_value(path, result, results)
            if not ok:
                detail = error or {"error": "extract_failed"}
                return False, None, {"field": key, **detail}
            extracted[str(key)] = value
        return True, extracted, None
    return False, None, {"error": "invalid_extract", "extract_type": type(spec).__name__}


def _batch_apply_extract(result, extract, results):
    if extract is None or _batch_result_failure(result):
        return result
    ok, value, error = _batch_extract_value(extract, result, results)
    if not ok:
        return {"ok": False, "error": "batch_extract_failed", "extract": error}
    extracted = dict(result)
    extracted["extracted"] = True
    extracted["extract"] = extract
    extracted["original_result"] = result
    extracted["value"] = value
    return extracted


def _batch_condition_spec(item):
    when = item.get("when", item.get("if"))
    unless = item.get("unless", item.get("if_not", item.get("if-not")))
    return when, unless


def _batch_evaluate_condition(condition, results):
    if condition is None:
        return {"ok": True, "checks": []}
    return _batch_evaluate_expectations(condition, {"ok": True}, results)


def _batch_skip_decision(item, results):
    when, unless = _batch_condition_spec(item)
    diagnostics = {}
    if when is not None:
        diagnostics["when"] = _batch_evaluate_condition(when, results)
        if not diagnostics["when"].get("ok"):
            return {"skip_reason": "when_false", "condition": diagnostics}
    if unless is not None:
        diagnostics["unless"] = _batch_evaluate_condition(unless, results)
        if diagnostics["unless"].get("ok"):
            return {"skip_reason": "unless_true", "condition": diagnostics}
    return None


def _batch_retry_options(item):
    retry_count = item.get("retries", item.get("retry_count", item.get("retry-count", 0)))
    retry_delay = item.get("retry_delay", item.get("retry-delay", item.get("interval", 0.0)))
    try:
        retry_count_int = max(int(retry_count or 0), 0)
    except Exception:
        retry_count_int = 0
    try:
        retry_delay_float = max(float(retry_delay or 0.0), 0.0)
    except Exception:
        retry_delay_float = 0.0
    return retry_count_int, retry_delay_float


def _batch_allows_failure(item):
    for key in ("optional", "allow_failure", "allow-failure", "continue_on_error", "continue-on-error", "soft_fail", "soft-fail"):
        if key in item:
            return bool(item.get(key))
    return False


def _batch_clipboard_restore_payload(result):
    if isinstance(result, dict) and result.get("clipboard_restore_ok") is False:
        return result
    if isinstance(result, dict) and isinstance(result.get("value"), dict) and result["value"].get("clipboard_restore_ok") is False:
        return result["value"]
    return None


def _batch_result_failure(result):
    if not isinstance(result, dict):
        result = _batch_normalize_result(result)
    clipboard_payload = _batch_clipboard_restore_payload(result)
    if clipboard_payload is not None:
        error = (
            clipboard_payload.get("clipboard_restore_error")
            or clipboard_payload.get("clipboard_restore_failures")
            or clipboard_payload.get("clipboard_restore_skipped_formats")
            or clipboard_payload.get("error")
            or clipboard_payload.get("message")
            or "clipboard_restore_incomplete"
        )
        return {"error": str(error), "failure_category": "clipboard_restore"}
    if "error" in result:
        return {"error": str(result.get("error") or "error")}
    if result.get("ok") is False:
        return {"error": str(result.get("message") or result.get("reason") or "ok_false")}
    return None


def _batch_summary(results, total_count=None, stopped_on_error=False):
    failures = []
    elapsed_values = []
    for index, item in enumerate(results):
        if isinstance(item, dict) and item.get("elapsed_ms") is not None:
            try:
                elapsed_values.append(float(item.get("elapsed_ms") or 0.0))
            except Exception:
                pass
        result = item.get("result") if isinstance(item, dict) else item
        failure = _batch_result_failure(result)
        if failure:
            entry = {
                "index": int(item.get("index", index)) if isinstance(item, dict) else index,
                "path": item.get("path") if isinstance(item, dict) else None,
                "command": item.get("command") if isinstance(item, dict) else None,
                "id": item.get("id") if isinstance(item, dict) else None,
                "attempts": item.get("attempts") if isinstance(item, dict) else None,
                "retries": item.get("retries") if isinstance(item, dict) else None,
                "elapsed_ms": item.get("elapsed_ms") if isinstance(item, dict) else None,
                "expectation": result.get("expectation") if isinstance(result, dict) else None,
                "extract": result.get("extract") if isinstance(result, dict) else None,
                **failure,
            }
            failures.append({k: v for k, v in entry.items() if v is not None})
    return {
        "ok": not failures and len(results) == int(total_count if total_count is not None else len(results)),
        "count": len(results),
        "total_count": int(total_count if total_count is not None else len(results)),
        "failed_count": len(failures),
        "failures": failures,
        "stopped_on_error": bool(stopped_on_error),
        "elapsed_ms": round(sum(elapsed_values), 3) if elapsed_values else 0.0,
    }


def _call_tools_worker(command: str, data: dict, timeout: float | None = None) -> dict:
    """Run potentially blocking tools.py work in a child process that can be killed."""
    worker_timeout = UIA_WORKER_DEFAULT_TIMEOUT if timeout is None else max(float(timeout), 0.1)
    tools_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools.py")
    env = os.environ.copy()
    env["WIN_AUTOMATION_HELPER_NO_REENTER"] = "1"
    env.setdefault("PYTHONUTF8", "1")
    payload = {"command": command, "data": data}
    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--worker-uia"],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=worker_timeout,
            env=env,
            cwd=os.path.dirname(tools_path),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "uia_worker_timeout",
            "timeout": worker_timeout,
            "command": command,
            "worker_killed": True,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "command": command}
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": "uia_worker_failed",
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "").strip()[-1000:],
            "stdout": (proc.stdout or "").strip()[-1000:],
            "command": command,
        }
    output = (proc.stdout or "").strip()
    if not output:
        return {"ok": False, "error": "uia_worker_empty_response", "command": command}
    try:
        return json.loads(output)
    except Exception as e:
        return {
            "ok": False,
            "error": f"uia_worker_invalid_json: {e}",
            "stdout": output[-1000:],
            "command": command,
        }


# Auto-cleanup temporary screenshot file on daemon termination
def _cleanup():
    try:
        import tempfile
        output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
        path = os.path.join(output_dir, "screenshot.png")
        if os.path.exists(path):
            os.remove(path)
        # Clean desktop one if it exists
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop", "win-automation-mcp")
        desktop_path = os.path.join(desktop_dir, "screenshot.png")
        if os.path.exists(desktop_path):
            os.remove(desktop_path)
    except Exception:
        pass

atexit.register(_cleanup)

# ---------------------------------------------------------------------------
# DPI awareness
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Windows API constants
# ---------------------------------------------------------------------------
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001
ASFW_ANY = 0xFFFFFFFF
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
SW_RESTORE = 9
VK_MENU = 0x12
GA_ROOT = 2
GA_ROOTOWNER = 3
GW_OWNER = 4
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
SMTO_ABORTIFHUNG = 0x0002
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
CWP_SKIPINVISIBLE = 0x0001
CWP_SKIPDISABLED = 0x0002
CWP_SKIPTRANSPARENT = 0x0004
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION_CLASS = 20
TOKEN_INTEGRITY_LEVEL_CLASS = 25
TOKEN_UIACCESS_CLASS = 26
SECURITY_MANDATORY_UNTRUSTED_RID = 0x00000000
SECURITY_MANDATORY_LOW_RID = 0x00001000
SECURITY_MANDATORY_MEDIUM_RID = 0x00002000
SECURITY_MANDATORY_MEDIUM_PLUS_RID = 0x00002100
SECURITY_MANDATORY_HIGH_RID = 0x00003000
SECURITY_MANDATORY_SYSTEM_RID = 0x00004000
SECURITY_MANDATORY_PROTECTED_PROCESS_RID = 0x00005000
MAX_PATH = 265
CF_UNICODETEXT = 13
CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_DIB = 8
CF_PALETTE = 9
CF_ENHMETAFILE = 14
CF_HDROP = 15
CF_LOCALE = 16
CF_DIBV5 = 17
IMAGE_BITMAP = 0
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
LR_CREATEDIBSECTION = 0x00002000
CLIPBOARD_RETRY_TIMEOUT = 1.5
CLIPBOARD_RETRY_INTERVAL = 0.03
CLIPBOARD_HANDLE_FORMATS = {CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE}
CLIPBOARD_DUPLICABLE_HANDLE_FORMATS = {CF_BITMAP, CF_ENHMETAFILE}

# ---------------------------------------------------------------------------
# Windows API handles
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
advapi32 = ctypes.windll.advapi32
shell32 = ctypes.windll.shell32

# ---------------------------------------------------------------------------
# Structs
# ---------------------------------------------------------------------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_ulong)]

class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]

# ---------------------------------------------------------------------------
# API prototypes
# ---------------------------------------------------------------------------
user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint
kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = ctypes.c_ulong
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = ctypes.c_bool
user32.GetCursorPos.argtypes = [ctypes.POINTER(ctypes.wintypes.POINT)]
user32.GetCursorPos.restype = ctypes.c_bool
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_bool
try:
    user32.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
    user32.AllowSetForegroundWindow.restype = ctypes.c_bool
except Exception:
    pass
try:
    user32.SwitchToThisWindow.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    user32.SwitchToThisWindow.restype = None
except Exception:
    pass
user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
user32.BringWindowToTop.restype = ctypes.c_bool
user32.SetActiveWindow.argtypes = [ctypes.c_void_p]
user32.SetActiveWindow.restype = ctypes.c_void_p
user32.SetFocus.argtypes = [ctypes.c_void_p]
user32.SetFocus.restype = ctypes.c_void_p
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetParent.argtypes = [ctypes.c_void_p]
user32.GetParent.restype = ctypes.c_void_p
user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetWindow.restype = ctypes.c_void_p
user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
user32.AttachThreadInput.restype = ctypes.c_bool
user32.IsWindow.argtypes = [ctypes.c_void_p]
user32.IsWindow.restype = ctypes.c_bool
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetDlgCtrlID.argtypes = [ctypes.c_void_p]
user32.GetDlgCtrlID.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.c_bool
user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetClientRect.restype = ctypes.c_bool
user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.POINT)]
user32.ClientToScreen.restype = ctypes.c_bool
user32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.POINT)]
user32.ScreenToClient.restype = ctypes.c_bool
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool
user32.EnumChildWindows.argtypes = [ctypes.c_void_p, ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), ctypes.c_void_p]
user32.EnumChildWindows.restype = ctypes.c_bool
user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.ChildWindowFromPointEx.argtypes = [ctypes.c_void_p, ctypes.wintypes.POINT, ctypes.c_uint]
user32.ChildWindowFromPointEx.restype = ctypes.c_void_p
user32.RealChildWindowFromPoint.argtypes = [ctypes.c_void_p, ctypes.wintypes.POINT]
user32.RealChildWindowFromPoint.restype = ctypes.c_void_p
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.IsWindowEnabled.argtypes = [ctypes.c_void_p]
user32.IsWindowEnabled.restype = ctypes.c_bool
user32.IsIconic.argtypes = [ctypes.c_void_p]
user32.IsIconic.restype = ctypes.c_bool
user32.IsZoomed.argtypes = [ctypes.c_void_p]
user32.IsZoomed.restype = ctypes.c_bool
user32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
user32.SendMessageTimeoutW.restype = ctypes.c_void_p
user32.OpenClipboard.argtypes = [ctypes.c_void_p]
user32.OpenClipboard.restype = ctypes.c_bool
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.c_bool
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.c_bool
user32.EnumClipboardFormats.argtypes = [ctypes.c_uint]
user32.EnumClipboardFormats.restype = ctypes.c_uint
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.CopyImage.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.CopyImage.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = ctypes.c_void_p
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = ctypes.c_ulong
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_bool
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype = ctypes.c_void_p
user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
user32.PrintWindow.restype = ctypes.c_bool
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.restype = ctypes.c_uint
advapi32.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
advapi32.OpenProcessToken.restype = ctypes.c_bool
advapi32.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
advapi32.GetTokenInformation.restype = ctypes.c_bool
advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
advapi32.GetSidSubAuthority.restype = ctypes.POINTER(ctypes.c_ulong)
shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = ctypes.c_bool

# DWM Frame Bounds API
try:
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
except Exception:
    pass
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = ctypes.c_bool
gdi32.CopyEnhMetaFileW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
gdi32.CopyEnhMetaFileW.restype = ctypes.c_void_p
gdi32.DeleteEnhMetaFile.argtypes = [ctypes.c_void_p]
gdi32.DeleteEnhMetaFile.restype = ctypes.c_bool
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = ctypes.c_bool
gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
gdi32.GetDIBits.restype = ctypes.c_int


# ---------------------------------------------------------------------------
# Key map: keysym -> Windows scancode
# ---------------------------------------------------------------------------
_KEYMAP = {
    "escape": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "minus": 0x0C, "equal": 0x0D, "backspace": 0x0E, "tab": 0x0F,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14,
    "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "bracketleft": 0x1A, "bracketright": 0x1B, "Return": 0x1C,
    "control_l": 0x1D, "Control_L": 0x1D, "Control_R": 0xE01D,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21,
    "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    "semicolon": 0x27, "apostrophe": 0x28, "grave": 0x29,
    "shift_l": 0x2A, "backslash": 0x2B,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
    "n": 0x31, "m": 0x32, "comma": 0x33, "period": 0x34, "slash": 0x35,
    "shift_r": 0x36, "Shift_R": 0x36, "KP_Multiply": 0x37,
    "Alt_L": 0x38, "Alt_R": 0xE038, "space": 0x39,
    "Caps_Lock": 0x3A,
    "F1": 0x3B, "F2": 0x3C, "F3": 0x3D, "F4": 0x3E,
    "F5": 0x3F, "F6": 0x40, "F7": 0x41, "F8": 0x42,
    "F9": 0x43, "F10": 0x44,
    "Num_Lock": 0x45, "Scroll_Lock": 0x46,
    "KP_7": 0x47, "KP_8": 0x48, "KP_9": 0x49, "KP_Subtract": 0x4A,
    "KP_4": 0x4B, "KP_5": 0x4C, "KP_6": 0x4D, "KP_Add": 0x4E,
    "KP_1": 0x4F, "KP_2": 0x50, "KP_3": 0x51, "KP_0": 0x52,
    "KP_Decimal": 0x53, "KP_Separator": 0x53, "KP_Divide": 0xE035,
    "KP_Enter": 0xE01C,
    "F11": 0x57, "F12": 0x58,
    "F13": 0x64, "F14": 0x65, "F15": 0x66, "F16": 0x67,
    "F17": 0x68, "F18": 0x69, "F19": 0x6A, "F20": 0x6B,
    "F21": 0x6C, "F22": 0x6D, "F23": 0x6E, "F24": 0x76,
    "Home": 0xE047, "Up": 0xE048, "Page_Up": 0xE049,
    "Left": 0xE04B, "Right": 0xE04D,
    "End": 0xE04F, "Down": 0xE050, "Page_Down": 0xE051,
    "Insert": 0xE052, "Delete": 0xE053,
    "Win_L": 0xE05B, "Win_R": 0xE05C, "Menu": 0xE05D,
    "PrintScreen": 0xE037, "Pause": 0xE11D45,
}

# Aliases
_KEYMAP["ctrl"] = _KEYMAP["control_l"]
_KEYMAP["shift"] = _KEYMAP["shift_l"]
_KEYMAP["Shift_L"] = _KEYMAP["shift_l"]
_KEY_ALIASES = {
    "control": "control_l",
    "ctl": "control_l",
    "lctrl": "control_l",
    "leftctrl": "control_l",
    "leftcontrol": "control_l",
    "rctrl": "Control_R",
    "rightctrl": "Control_R",
    "rightcontrol": "Control_R",
    "alt": "Alt_L",
    "option": "Alt_L",
    "lalt": "Alt_L",
    "leftalt": "Alt_L",
    "ralt": "Alt_R",
    "rightalt": "Alt_R",
    "win": "Win_L",
    "windows": "Win_L",
    "lwin": "Win_L",
    "leftwin": "Win_L",
    "rwin": "Win_R",
    "rightwin": "Win_R",
    "cmd": "Win_L",
    "command": "Win_L",
    "super": "Win_L",
    "meta": "Win_L",
    "enter": "Return",
    "return": "Return",
    "kpenter": "KP_Enter",
    "kp-enter": "KP_Enter",
    "numenter": "KP_Enter",
    "num-enter": "KP_Enter",
    "esc": "escape",
    "escape": "escape",
    "backspace": "backspace",
    "bksp": "backspace",
    "del": "Delete",
    "delete": "Delete",
    "ins": "Insert",
    "insert": "Insert",
    "pgup": "Page_Up",
    "pageup": "Page_Up",
    "page-up": "Page_Up",
    "page_up": "Page_Up",
    "pgdn": "Page_Down",
    "pagedown": "Page_Down",
    "page-down": "Page_Down",
    "page_down": "Page_Down",
    "up": "Up",
    "arrowup": "Up",
    "arrow-up": "Up",
    "arrow_up": "Up",
    "down": "Down",
    "arrowdown": "Down",
    "arrow-down": "Down",
    "arrow_down": "Down",
    "left": "Left",
    "arrowleft": "Left",
    "arrow-left": "Left",
    "arrow_left": "Left",
    "right": "Right",
    "arrowright": "Right",
    "arrow-right": "Right",
    "arrow_right": "Right",
    "home": "Home",
    "end": "End",
    "spacebar": "space",
    "space": "space",
    "capslock": "Caps_Lock",
    "caps-lock": "Caps_Lock",
    "numlock": "Num_Lock",
    "num-lock": "Num_Lock",
    "scrolllock": "Scroll_Lock",
    "scroll-lock": "Scroll_Lock",
    "printscreen": "PrintScreen",
    "print-screen": "PrintScreen",
    "prtsc": "PrintScreen",
    "prt-scr": "PrintScreen",
    "sysrq": "PrintScreen",
    "sys-req": "PrintScreen",
    "pause": "Pause",
    "break": "Pause",
    "pausebreak": "Pause",
    "pause-break": "Pause",
    "apps": "Menu",
    "contextmenu": "Menu",
    "context-menu": "Menu",
    "num0": "KP_0",
    "num1": "KP_1",
    "num2": "KP_2",
    "num3": "KP_3",
    "num4": "KP_4",
    "num5": "KP_5",
    "num6": "KP_6",
    "num7": "KP_7",
    "num8": "KP_8",
    "num9": "KP_9",
    "numpad0": "KP_0",
    "numpad1": "KP_1",
    "numpad2": "KP_2",
    "numpad3": "KP_3",
    "numpad4": "KP_4",
    "numpad5": "KP_5",
    "numpad6": "KP_6",
    "numpad7": "KP_7",
    "numpad8": "KP_8",
    "numpad9": "KP_9",
    "kpmultiply": "KP_Multiply",
    "kp-multiply": "KP_Multiply",
    "nummultiply": "KP_Multiply",
    "num-multiply": "KP_Multiply",
    "multiply": "KP_Multiply",
    "kpadd": "KP_Add",
    "kp-add": "KP_Add",
    "numadd": "KP_Add",
    "num-add": "KP_Add",
    "add": "KP_Add",
    "kpsubtract": "KP_Subtract",
    "kp-subtract": "KP_Subtract",
    "numsubtract": "KP_Subtract",
    "num-subtract": "KP_Subtract",
    "subtract": "KP_Subtract",
    "kpdecimal": "KP_Decimal",
    "kp-decimal": "KP_Decimal",
    "numdecimal": "KP_Decimal",
    "num-decimal": "KP_Decimal",
    "decimal": "KP_Decimal",
    "kpseparator": "KP_Separator",
    "kp-separator": "KP_Separator",
    "numseparator": "KP_Separator",
    "num-separator": "KP_Separator",
    "separator": "KP_Separator",
    "kpdivide": "KP_Divide",
    "kp-divide": "KP_Divide",
    "numdivide": "KP_Divide",
    "num-divide": "KP_Divide",
    "divide": "KP_Divide",
    "-": "minus",
    "=": "equal",
    ",": "comma",
    ".": "period",
    "[": "bracketleft",
    "]": "bracketright",
    "\\": "backslash",
    ";": "semicolon",
    "'": "apostrophe",
    "`": "grave",
    "/": "slash",
}
KEYMAP = _KEYMAP


def _normalize_key_name(key: str) -> str:
    raw = str(key or "").strip()
    if raw in KEYMAP:
        return raw
    compact = raw.lower().replace("_", "").replace(" ", "")
    hyphenated = raw.lower().replace("_", "-").replace(" ", "-")
    if compact in _KEY_ALIASES:
        return _KEY_ALIASES[compact]
    if hyphenated in _KEY_ALIASES:
        return _KEY_ALIASES[hyphenated]
    if len(raw) == 1 and raw.isalpha():
        return raw.lower()
    if len(raw) > 1 and raw[0].lower() == "f" and raw[1:].isdigit():
        return raw.upper()
    if len(raw) > 2 and raw[:2].lower() == "kp" and raw[2:].isdigit():
        return f"KP_{raw[2:]}"
    return raw


def _split_key_sequence(keys: str) -> list[str]:
    raw = str(keys or "").strip()
    if not raw:
        return []

    chunks = re.split(r"[+,]", raw) if re.search(r"[+,]", raw) else [raw]
    parts: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        normalized = _normalize_key_name(chunk)
        if normalized != chunk or normalized in KEYMAP:
            parts.append(chunk)
        else:
            parts.extend(part for part in re.split(r"\s+", chunk) if part)
    return parts


_MOUSE_BUTTON_ALIASES = {
    "primary": "left",
    "secondary": "right",
    "context": "right",
    "middlebutton": "middle",
    "wheel": "middle",
    "wheelbutton": "middle",
    "center": "middle",
}


def _normalize_mouse_button(button: str = "left") -> str:
    normalized = str(button or "left").strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    normalized = _MOUSE_BUTTON_ALIASES.get(normalized, normalized)
    if normalized not in {"left", "right", "middle"}:
        raise ValueError(f"Unsupported mouse button '{button}'. Use left, right, or middle.")
    return normalized


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------
def _send_input_checked(inp: INPUT, label: str) -> None:
    sent = int(user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp)))
    if sent != 1:
        err = int(kernel32.GetLastError())
        raise RuntimeError(f"SendInput failed for {label}: sent={sent}, last_error={err}")


def _send_key(scancode: int, up: bool = False) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = 0
    inp.union.ki.wScan = scancode & 0xFF
    inp.union.ki.dwFlags = KEYEVENTF_SCANCODE
    if scancode & 0xE000:
        inp.union.ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
    if up:
        inp.union.ki.dwFlags |= KEYEVENTF_KEYUP
    direction = "up" if up else "down"
    _send_input_checked(inp, f"key {direction} scancode=0x{scancode:X}")


def _send_char(ch: str) -> None:
    for code in ch:
        cp = ord(code)
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = 0
        inp.union.ki.wScan = cp
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE
        _send_input_checked(inp, f"unicode down U+{cp:04X}")
        time.sleep(0.01)
        inp.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        _send_input_checked(inp, f"unicode up U+{cp:04X}")
        time.sleep(0.01)


def _press_scancode_sequence(scancodes: list[int], delay: float = 0.02) -> None:
    pressed: list[int] = []
    original_error: BaseException | None = None
    try:
        for sc in scancodes:
            _send_key(sc)
            pressed.append(sc)
            time.sleep(delay)
    except BaseException as e:
        original_error = e
    finally:
        release_errors: list[str] = []
        for sc in reversed(pressed):
            try:
                _send_key(sc, up=True)
                time.sleep(delay)
            except BaseException as e:
                release_errors.append(str(e))
        if original_error is not None:
            if release_errors:
                raise RuntimeError(f"{original_error}; release_errors={release_errors}") from original_error
            raise original_error
        if release_errors:
            raise RuntimeError(f"SendInput release failed: {release_errors}")


def _set_cursor_pos_checked(x: int, y: int) -> None:
    if not user32.SetCursorPos(int(x), int(y)):
        err = int(kernel32.GetLastError())
        raise RuntimeError(f"SetCursorPos failed at ({int(x)}, {int(y)}): last_error={err}")


def _send_mouse_input(flags: int, data: int = 0, label: str = "mouse") -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = 0
    inp.union.mi.dy = 0
    inp.union.mi.mouseData = int(data)
    inp.union.mi.dwFlags = int(flags)
    inp.union.mi.time = 0
    inp.union.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    _send_input_checked(inp, label)


def _mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    button = _normalize_mouse_button(button)
    _set_cursor_pos_checked(x, y)
    time.sleep(0.05)

    down_map = {
        "left": MOUSEEVENTF_LEFTDOWN,
        "right": MOUSEEVENTF_RIGHTDOWN,
        "middle": MOUSEEVENTF_MIDDLEDOWN,
    }
    up_map = {
        "left": MOUSEEVENTF_LEFTUP,
        "right": MOUSEEVENTF_RIGHTUP,
        "middle": MOUSEEVENTF_MIDDLEUP,
    }

    for _ in range(clicks):
        _send_mouse_input(down_map[button], label=f"mouse {button} down")
        time.sleep(0.02)
        _send_mouse_input(up_map[button], label=f"mouse {button} up")
        time.sleep(0.05)


def _mouse_scroll(x: int, y: int, delta: int) -> None:
    _set_cursor_pos_checked(x, y)
    time.sleep(0.05)
    _send_mouse_input(MOUSEEVENTF_WHEEL, int(delta), label=f"mouse wheel delta={int(delta)}")


def _mouse_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.5,
    button: str = "left",
) -> None:
    button = _normalize_mouse_button(button)
    down_map = {
        "left": MOUSEEVENTF_LEFTDOWN,
        "right": MOUSEEVENTF_RIGHTDOWN,
        "middle": MOUSEEVENTF_MIDDLEDOWN,
    }
    up_map = {
        "left": MOUSEEVENTF_LEFTUP,
        "right": MOUSEEVENTF_RIGHTUP,
        "middle": MOUSEEVENTF_MIDDLEUP,
    }
    _set_cursor_pos_checked(int(start_x), int(start_y))
    time.sleep(0.05)
    pressed = False
    try:
        _send_mouse_input(down_map[button], label=f"mouse drag {button} down")
        pressed = True
        time.sleep(0.05)
        steps = max(int(float(duration) / 0.02), 1)
        sleep_time = max(float(duration), 0.0) / steps if steps else 0.0
        for i in range(1, steps + 1):
            t = i / steps
            x = int(start_x + (end_x - start_x) * t)
            y = int(start_y + (end_y - start_y) * t)
            _set_cursor_pos_checked(x, y)
            if sleep_time:
                time.sleep(sleep_time)
    finally:
        if pressed:
            _send_mouse_input(up_map[button], label=f"mouse drag {button} up")
    time.sleep(0.02)


def _allow_set_foreground_window() -> dict:
    fn = getattr(user32, "AllowSetForegroundWindow", None)
    if not fn:
        return {"available": False, "ok": False}
    try:
        return {"available": True, "ok": bool(fn(ctypes.c_ulong(ASFW_ANY)))}
    except Exception as e:
        return {"available": True, "ok": False, "error": str(e)}


def _alt_foreground_pulse() -> dict:
    """Send a bare Alt press/release; Windows treats this as user input for foreground repair."""
    try:
        down = INPUT()
        down.type = INPUT_KEYBOARD
        down.union.ki.wVk = VK_MENU
        down.union.ki.wScan = 0
        down.union.ki.dwFlags = 0
        down.union.ki.time = 0
        down.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        up = INPUT()
        up.type = INPUT_KEYBOARD
        up.union.ki.wVk = VK_MENU
        up.union.ki.wScan = 0
        up.union.ki.dwFlags = KEYEVENTF_KEYUP
        up.union.ki.time = 0
        up.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        _send_input_checked(down, "foreground alt down")
        time.sleep(0.02)
        _send_input_checked(up, "foreground alt up")
        time.sleep(0.02)
        return {"ok": True, "sent_down": 1, "sent_up": 1}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _switch_to_this_window(hwnd: int) -> dict:
    fn = getattr(user32, "SwitchToThisWindow", None)
    if not fn:
        return {"available": False, "ok": False}
    try:
        fn(ctypes.c_void_p(hwnd), True)
        return {"available": True, "ok": True}
    except Exception as e:
        return {"available": True, "ok": False, "error": str(e)}


def _activate_window(hwnd: int) -> dict:
    hwnd = int(hwnd or 0)
    if not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window {hwnd} no longer exists", "hwnd": hwnd}
    root = int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
    fg_before = int(user32.GetForegroundWindow() or 0)
    fg_tid = int(user32.GetWindowThreadProcessId(fg_before, None)) if fg_before else 0
    root_tid = int(user32.GetWindowThreadProcessId(root, None))
    target_tid = int(user32.GetWindowThreadProcessId(hwnd, None))
    my_tid = int(kernel32.GetCurrentThreadId())
    attached = []
    attempts = []

    def foreground_is_root() -> bool:
        return int(user32.GetForegroundWindow() or 0) == root

    def attach(thread_id: int, attach_flag: bool) -> bool:
        if thread_id <= 0 or thread_id == my_tid:
            return True
        ok = bool(user32.AttachThreadInput(my_tid, thread_id, attach_flag))
        attached.append({"thread_id": int(thread_id), "attach": bool(attach_flag), "ok": ok})
        return ok

    def attempt(name: str, action) -> bool:
        step = {"name": name}
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

    unique_threads = []
    for tid in (fg_tid, root_tid, target_tid):
        if tid > 0 and tid != my_tid and tid not in unique_threads:
            unique_threads.append(tid)

    try:
        for tid in unique_threads:
            attach(tid, True)
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
        user32.SetActiveWindow(root)
        user32.SetFocus(hwnd)
        deadline = time.time() + 0.5
        while not foreground_is_root() and time.time() < deadline:
            time.sleep(0.01)
    except Exception as e:
        attempts.append({"name": "activate_exception", "error": str(e)})
    finally:
        for tid in reversed(unique_threads):
            attach(tid, False)

    fg_after = int(user32.GetForegroundWindow() or 0)
    return {
        "ok": bool(fg_after == root),
        "hwnd": hwnd,
        "root_hwnd": root,
        "foreground_before": fg_before,
        "foreground_after": fg_after,
        "current_thread_id": my_tid,
        "foreground_thread_id": fg_tid,
        "root_thread_id": root_tid,
        "target_thread_id": target_tid,
        "attached_threads": attached,
        "attempts": attempts,
    }


def _send_message_timeout(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0, timeout_ms: int = 500) -> tuple[bool, int]:
    result = ctypes.c_void_p()
    ok = bool(user32.SendMessageTimeoutW(
        ctypes.c_void_p(int(hwnd)),
        ctypes.c_uint(int(msg)),
        ctypes.c_void_p(int(wparam)),
        ctypes.c_void_p(int(lparam)),
        SMTO_ABORTIFHUNG,
        ctypes.c_uint(max(int(timeout_ms), 1)),
        ctypes.byref(result),
    ))
    return ok, int(result.value or 0)


def _win32_text(hwnd: int, timeout_ms: int = 500, max_chars: int = 8192) -> dict:
    hwnd = int(hwnd or 0)
    if not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window/control {hwnd} not found", "hwnd": hwnd}
    ok, length = _send_message_timeout(hwnd, WM_GETTEXTLENGTH, timeout_ms=timeout_ms)
    if not ok:
        return {"ok": False, "error": "WM_GETTEXTLENGTH timed out or failed", "hwnd": hwnd, "text": ""}
    length = min(max(int(length), 0), max(int(max_chars), 0))
    buf = ctypes.create_unicode_buffer(length + 1)
    ok, copied = _send_message_timeout(hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buf), timeout_ms=timeout_ms)
    if not ok:
        return {"ok": False, "error": "WM_GETTEXT timed out or failed", "hwnd": hwnd, "text": ""}
    return {"ok": True, "hwnd": hwnd, "text": buf.value, "length": int(copied)}


def _win32_set_text(hwnd: int, text: str, timeout_ms: int = 500) -> dict:
    hwnd = int(hwnd or 0)
    if not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window/control {hwnd} not found", "hwnd": hwnd}
    buf = ctypes.create_unicode_buffer(str(text))
    ok, result = _send_message_timeout(hwnd, WM_SETTEXT, 0, ctypes.addressof(buf), timeout_ms=timeout_ms)
    after = _win32_text(hwnd, timeout_ms=timeout_ms)
    return {"ok": bool(ok and result), "hwnd": hwnd, "result": int(result), "text": after}


def _win32_click(hwnd: int, timeout_ms: int = 500) -> dict:
    hwnd = int(hwnd or 0)
    if not user32.IsWindow(hwnd):
        return {"ok": False, "error": f"Window/control {hwnd} not found", "hwnd": hwnd}
    root = int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
    if root:
        _activate_window(root)
        time.sleep(0.05)
    ok, result = _send_message_timeout(hwnd, BM_CLICK, 0, 0, timeout_ms=timeout_ms)
    if not ok:
        post_ok = bool(user32.PostMessageW(hwnd, BM_CLICK, 0, 0))
        return {"ok": post_ok, "hwnd": hwnd, "method": "PostMessageW"}
    return {"ok": True, "hwnd": hwnd, "method": "SendMessageTimeoutW", "result": int(result)}


def _open_clipboard_retry(timeout: float = CLIPBOARD_RETRY_TIMEOUT, interval: float = CLIPBOARD_RETRY_INTERVAL) -> bool:
    deadline = time.time() + max(float(timeout), 0.0)
    while True:
        if user32.OpenClipboard(0):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(max(float(interval), 0.005))


def _clipboard_set_memory_format(fmt: int, data: bytes) -> None:
    size = max(len(data), 1)
    h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
    if not h_mem:
        raise RuntimeError("GlobalAlloc failed")
    set_ok = False
    try:
        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            raise RuntimeError("GlobalLock failed")
        try:
            if data:
                ctypes.memmove(p_mem, data, len(data))
        finally:
            kernel32.GlobalUnlock(h_mem)
        if not user32.SetClipboardData(int(fmt), h_mem):
            raise RuntimeError("SetClipboardData failed")
        set_ok = True
    finally:
        if not set_ok:
            try:
                kernel32.GlobalFree(h_mem)
            except Exception:
                pass


def _clipboard_dispose_handle_format(fmt: int, handle: int) -> None:
    if not handle:
        return
    try:
        if int(fmt) == CF_BITMAP:
            gdi32.DeleteObject(handle)
        elif int(fmt) == CF_ENHMETAFILE:
            gdi32.DeleteEnhMetaFile(handle)
    except Exception:
        pass


def _clipboard_dispose_snapshot_handles(snapshot: dict | None, exclude_indexes: set[int] | None = None) -> list:
    disposed = []
    if not isinstance(snapshot, dict):
        return disposed
    excluded = exclude_indexes or set()
    for index, item in enumerate(snapshot.get("formats") or []):
        if index in excluded or not isinstance(item, dict) or item.get("storage") != "handle":
            continue
        fmt = int(item.get("format") or 0)
        handle = int(item.get("handle") or 0)
        if not fmt or not handle:
            continue
        _clipboard_dispose_handle_format(fmt, handle)
        disposed.append({"index": index, "format": fmt, "handle_kind": item.get("handle_kind")})
        item["handle"] = 0
        item["disposed"] = True
    return disposed


def _clipboard_copy_handle_format(fmt: int) -> tuple[dict | None, str | None]:
    fmt = int(fmt)
    h_data = user32.GetClipboardData(fmt)
    if not h_data:
        return None, "no_handle"
    if fmt == CF_BITMAP:
        h_copy = user32.CopyImage(h_data, IMAGE_BITMAP, 0, 0, LR_CREATEDIBSECTION)
        if not h_copy:
            h_copy = user32.CopyImage(h_data, IMAGE_BITMAP, 0, 0, 0)
        if not h_copy:
            return None, "copy_image_failed"
        return {"format": fmt, "storage": "handle", "handle_kind": "bitmap", "handle": int(h_copy)}, None
    if fmt == CF_ENHMETAFILE:
        h_copy = gdi32.CopyEnhMetaFileW(h_data, None)
        if not h_copy:
            return None, "copy_enhmetafile_failed"
        return {"format": fmt, "storage": "handle", "handle_kind": "enhmetafile", "handle": int(h_copy)}, None
    return None, "unsupported_handle_format"


def _clipboard_set_handle_format(fmt: int, handle: int) -> None:
    fmt = int(fmt)
    handle = int(handle or 0)
    if not handle:
        raise RuntimeError("missing clipboard handle")
    set_ok = False
    try:
        if not user32.SetClipboardData(fmt, handle):
            raise RuntimeError("SetClipboardData failed")
        set_ok = True
    finally:
        if not set_ok:
            _clipboard_dispose_handle_format(fmt, handle)


def _clipboard_read_memory_format(fmt: int) -> tuple[bytes | None, str | None]:
    if int(fmt) in CLIPBOARD_HANDLE_FORMATS:
        return None, "unsupported_handle_format"
    h_data = user32.GetClipboardData(int(fmt))
    if not h_data:
        return None, "no_handle"
    size = int(kernel32.GlobalSize(h_data) or 0)
    if size <= 0:
        return None, "not_global_memory"
    p_data = kernel32.GlobalLock(h_data)
    if not p_data:
        return None, "lock_failed"
    try:
        return ctypes.string_at(p_data, size), None
    finally:
        kernel32.GlobalUnlock(h_data)


def _clipboard_snapshot() -> dict:
    """Snapshot memory-backed clipboard formats so paste fallback can restore them."""
    snapshot = {"ok": False, "formats": [], "skipped_formats": []}
    if not _open_clipboard_retry():
        snapshot["error"] = "open_clipboard_failed"
        return snapshot
    try:
        snapshot["ok"] = True
        seen = set()
        fmt = 0
        while True:
            fmt = int(user32.EnumClipboardFormats(fmt) or 0)
            if not fmt or fmt in seen:
                break
            seen.add(fmt)
            if fmt in CLIPBOARD_DUPLICABLE_HANDLE_FORMATS:
                handle_item, error = _clipboard_copy_handle_format(fmt)
                if handle_item is None:
                    snapshot["skipped_formats"].append({"format": fmt, "reason": error or "unavailable"})
                    continue
                snapshot["formats"].append(handle_item)
                continue
            data, error = _clipboard_read_memory_format(fmt)
            if data is None:
                snapshot["skipped_formats"].append({"format": fmt, "reason": error or "unavailable"})
                continue
            snapshot["formats"].append({"format": fmt, "storage": "memory", "data": data, "size": len(data)})
        snapshot["format_count"] = len(snapshot["formats"])
        snapshot["skipped_count"] = len(snapshot["skipped_formats"])
        snapshot["empty"] = not bool(snapshot["formats"]) and not bool(snapshot["skipped_formats"])
        return snapshot
    except Exception as e:
        disposed = _clipboard_dispose_snapshot_handles(snapshot)
        snapshot["ok"] = False
        snapshot["error"] = str(e)
        if disposed:
            snapshot["disposed_handles"] = disposed
        return snapshot
    finally:
        user32.CloseClipboard()


def _clipboard_restore_snapshot(snapshot: dict | None) -> dict:
    if not isinstance(snapshot, dict) or not snapshot.get("ok"):
        return {"ok": False, "restored": False, "error": "no_valid_clipboard_snapshot"}
    if not _open_clipboard_retry():
        disposed = _clipboard_dispose_snapshot_handles(snapshot)
        result = {"ok": False, "restored": False, "error": "open_clipboard_failed"}
        if disposed:
            result["disposed_handles"] = disposed
        return result
    restored = 0
    failures = []
    transferred_handle_indexes = set()
    try:
        if not user32.EmptyClipboard():
            raise RuntimeError("EmptyClipboard failed")
        for index, item in enumerate(snapshot.get("formats") or []):
            try:
                if item.get("storage") == "handle":
                    _clipboard_set_handle_format(int(item.get("format")), int(item.get("handle") or 0))
                    transferred_handle_indexes.add(index)
                else:
                    _clipboard_set_memory_format(int(item.get("format")), bytes(item.get("data") or b""))
                restored += 1
            except Exception as e:
                failures.append({"format": item.get("format"), "error": str(e)})
        skipped = list(snapshot.get("skipped_formats") or [])
        return {
            "ok": not failures and not skipped,
            "restored": True,
            "restored_formats": restored,
            "format_count": len(snapshot.get("formats") or []),
            "skipped_formats": skipped,
            "failures": failures,
        }
    except Exception as e:
        disposed = _clipboard_dispose_snapshot_handles(snapshot, exclude_indexes=transferred_handle_indexes)
        result = {"ok": False, "restored": False, "error": str(e), "restored_formats": restored, "failures": failures}
        if disposed:
            result["disposed_handles"] = disposed
        return result
    finally:
        user32.CloseClipboard()


def _clipboard_save() -> bytes | None:
    """Save current clipboard text. Returns bytes or None."""
    try:
        if not _open_clipboard_retry():
            return None
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            user32.CloseClipboard()
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            user32.CloseClipboard()
            return None
        # Read as null-terminated wide string for legacy clipboard get/save commands.
        text = ctypes.c_wchar_p(p).value or ""
        kernel32.GlobalUnlock(h)
        user32.CloseClipboard()
        return text.encode("utf-16-le")
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass
        return None


def _clipboard_restore(data: bytes | None) -> None:
    """Restore clipboard from saved bytes."""
    if data is None:
        return
    try:
        if not _open_clipboard_retry():
            return
        user32.EmptyClipboard()
        text_bytes = data + b"\x00\x00"
        _clipboard_set_memory_format(CF_UNICODETEXT, text_bytes)
        user32.CloseClipboard()
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# DPI & process helpers
# ---------------------------------------------------------------------------
def _get_dpi_scale(hwnd: int) -> float:
    """Return DPI scale factor relative to 96 DPI (1.0 = no scaling)."""
    try:
        dpi = user32.GetDpiForWindow(hwnd)
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _get_window_rect(hwnd: int) -> ctypes.wintypes.RECT:
    """Get the visible window rect, excluding invisible shadow borders using DWM API."""
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
            return rect
    except Exception:
        pass
    
    # Fallback to standard GetWindowRect
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def _get_process_path(pid: int) -> str:
    """Return full image path for a process, or empty string on failure."""
    try:
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        pbuf = ctypes.create_unicode_buffer(MAX_PATH)
        size = ctypes.c_ulong(MAX_PATH)
        if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
            path = pbuf.value
            kernel32.CloseHandle(h)
            return path
        kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def _rect_dict(rect: ctypes.wintypes.RECT) -> dict:
    left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    width = right - left
    height = bottom - top
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": width,
        "height": height,
        "center_x": left + width // 2,
        "center_y": top + height // 2,
    }


def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    try:
        user32.GetClassNameW(ctypes.c_void_p(int(hwnd)), buf, 256)
    except Exception:
        return ""
    return buf.value


def _get_window_text(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    try:
        user32.GetWindowTextW(ctypes.c_void_p(int(hwnd)), buf, 512)
    except Exception:
        return ""
    return buf.value


def _get_client_rect_info(hwnd: int) -> dict:
    rect = ctypes.wintypes.RECT()
    if not user32.GetClientRect(ctypes.c_void_p(int(hwnd)), ctypes.byref(rect)):
        return {}
    origin = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(ctypes.c_void_p(int(hwnd)), ctypes.byref(origin))
    return {
        "rect": _rect_dict(rect),
        "screen_origin": {"x": int(origin.x), "y": int(origin.y)},
    }


def _window_info(hwnd: int, include_text: bool = False) -> dict | None:
    hwnd = int(hwnd or 0)
    try:
        if not user32.IsWindow(ctypes.c_void_p(hwnd)):
            return None
        pid = ctypes.c_ulong()
        thread_id = int(user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid)) or 0)
        proc_path = _get_process_path(int(pid.value))
        style = int(user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE))
        ex_style = int(user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE))
        parent = int(user32.GetParent(ctypes.c_void_p(hwnd)) or 0)
        owner = int(user32.GetWindow(ctypes.c_void_p(hwnd), GW_OWNER) or 0)
        root = int(user32.GetAncestor(ctypes.c_void_p(hwnd), GA_ROOT) or 0)
        root_owner = int(user32.GetAncestor(ctypes.c_void_p(hwnd), GA_ROOTOWNER) or 0)
        rect = _get_window_rect(hwnd)
        info = {
            "hwnd": hwnd,
            "title": _get_window_text(hwnd),
            "class_name": _get_class_name(hwnd),
            "control_id": int(user32.GetDlgCtrlID(ctypes.c_void_p(hwnd))),
            "pid": int(pid.value),
            "thread_id": thread_id,
            "process_name": os.path.basename(proc_path) if proc_path else "",
            "process_path": proc_path,
            "visible": bool(user32.IsWindowVisible(ctypes.c_void_p(hwnd))),
            "enabled": bool(user32.IsWindowEnabled(ctypes.c_void_p(hwnd))),
            "minimized": bool(user32.IsIconic(ctypes.c_void_p(hwnd))),
            "maximized": bool(user32.IsZoomed(ctypes.c_void_p(hwnd))),
            "topmost": bool(ex_style & WS_EX_TOPMOST),
            "is_child": bool(style & WS_CHILD),
            "parent_hwnd": parent,
            "owner_hwnd": owner,
            "root_hwnd": root,
            "root_owner_hwnd": root_owner,
            "style": style,
            "ex_style": ex_style,
            "rect": _rect_dict(rect),
            "client": _get_client_rect_info(hwnd),
        }
        if include_text:
            info["text"] = _win32_text(hwnd)
        return info
    except Exception:
        return None


def _child_windows(hwnd: int, include_invisible: bool = False, include_text: bool = False, max_count: int = 500) -> dict:
    hwnd = int(hwnd or 0)
    target = _window_info(hwnd, include_text=include_text)
    if not target:
        return {"ok": False, "error": f"Window {hwnd} not found", "hwnd": hwnd}
    children = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(child, _):
        try:
            if len(children) >= int(max_count):
                return False
            info = _window_info(int(child), include_text=include_text)
            if not info:
                return True
            if not include_invisible and not info.get("visible", False):
                return True
            children.append(info)
        except Exception:
            pass
        return True

    user32.EnumChildWindows(ctypes.c_void_p(hwnd), callback, None)
    return {"ok": True, "target": target, "count": len(children), "children": children}


def _window_from_point(x: int, y: int, include_text: bool = False) -> dict:
    screen_x, screen_y = int(x), int(y)
    point = ctypes.wintypes.POINT(screen_x, screen_y)
    direct_hwnd = int(user32.WindowFromPoint(point) or 0)
    root_hwnd = int(user32.GetAncestor(ctypes.c_void_p(direct_hwnd), GA_ROOT) or direct_hwnd or 0) if direct_hwnd else 0
    root_owner_hwnd = int(user32.GetAncestor(ctypes.c_void_p(direct_hwnd), GA_ROOTOWNER) or direct_hwnd or 0) if direct_hwnd else 0
    child_hwnd = 0
    real_child_hwnd = 0
    if root_hwnd:
        client_point = ctypes.wintypes.POINT(screen_x, screen_y)
        user32.ScreenToClient(ctypes.c_void_p(root_hwnd), ctypes.byref(client_point))
        flags = CWP_SKIPINVISIBLE | CWP_SKIPDISABLED | CWP_SKIPTRANSPARENT
        child_hwnd = int(user32.ChildWindowFromPointEx(ctypes.c_void_p(root_hwnd), client_point, flags) or 0)
        real_child_hwnd = int(user32.RealChildWindowFromPoint(ctypes.c_void_p(root_hwnd), client_point) or 0)
    return {
        "ok": True,
        "screen": {"x": screen_x, "y": screen_y},
        "window": _window_info(direct_hwnd, include_text=include_text) if direct_hwnd else None,
        "root": _window_info(root_hwnd, include_text=include_text) if root_hwnd else None,
        "root_owner": _window_info(root_owner_hwnd, include_text=include_text) if root_owner_hwnd else None,
        "child": _window_info(child_hwnd, include_text=include_text) if child_hwnd else None,
        "real_child": _window_info(real_child_hwnd, include_text=include_text) if real_child_hwnd else None,
    }


def _integrity_level_name(rid: int | None) -> str:
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


def _query_token_dword(token: int, info_class: int) -> int | None:
    value = ctypes.c_ulong()
    needed = ctypes.c_ulong()
    ok = advapi32.GetTokenInformation(
        ctypes.c_void_p(token),
        info_class,
        ctypes.byref(value),
        ctypes.sizeof(value),
        ctypes.byref(needed),
    )
    return int(value.value) if ok else None


def _query_token_integrity(token: int) -> dict:
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


def _current_process_token_info() -> dict:
    pid = int(kernel32.GetCurrentProcessId())
    info = {
        "pid": pid,
        "process_path": _get_process_path(pid),
        "token_readable": False,
    }
    token = ctypes.c_void_p()
    process = int(kernel32.GetCurrentProcess() or 0)
    if not advapi32.OpenProcessToken(ctypes.c_void_p(process), TOKEN_QUERY, ctypes.byref(token)):
        return info
    try:
        info["token_readable"] = True
        elevation = _query_token_dword(int(token.value or 0), TOKEN_ELEVATION_CLASS)
        uiaccess = _query_token_dword(int(token.value or 0), TOKEN_UIACCESS_CLASS)
        info["elevated"] = bool(elevation) if elevation is not None else None
        info["uiaccess"] = bool(uiaccess) if uiaccess is not None else None
        try:
            info["is_admin_user"] = bool(shell32.IsUserAnAdmin())
        except Exception:
            info["is_admin_user"] = False
        info.update(_query_token_integrity(int(token.value or 0)))
    finally:
        if token.value:
            kernel32.CloseHandle(token)
    return info


# ---------------------------------------------------------------------------
# Persistent state
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


def _set_clipboard_text(text: str) -> None:
    """Set clipboard text."""
    opened = False
    try:
        if not _open_clipboard_retry():
            raise RuntimeError("Could not open clipboard")
        opened = True
        user32.EmptyClipboard()
        text_bytes = text.encode("utf-16-le") + b"\x00\x00"
        _clipboard_set_memory_format(CF_UNICODETEXT, text_bytes)
    finally:
        if opened:
            try:
                user32.CloseClipboard()
            except Exception:
                pass


def _capture_dxcam_rect(left: int, top: int, right: int, bottom: int):
    """Capture a global desktop rect with dxcam, including multi-monitor windows."""
    from PIL import Image as PILImage

    try:
        import re
        import dxcam
    except Exception:
        return None

    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None

    try:
        output_info = dxcam.output_info()
        pairs = [
            (int(device_idx), int(output_idx))
            for device_idx, output_idx in re.findall(r"Device\[(\d+)\]\s+Output\[(\d+)\]", output_info)
        ]
        if not pairs:
            pairs = [(0, None)]

        canvas = PILImage.new("RGB", (width, height))
        coverage = PILImage.new("L", (width, height), 0)
        captured_any = False

        for device_idx, output_idx in pairs:
            try:
                kwargs = {"device_idx": device_idx, "output_color": "RGB"}
                if output_idx is not None:
                    kwargs["output_idx"] = output_idx
                camera = dxcam.create(**kwargs)
                output = getattr(camera, "_output", None)
                desc = getattr(output, "desc", None)
                coords = getattr(desc, "DesktopCoordinates", None)
                if coords:
                    out_left, out_top = int(coords.left), int(coords.top)
                    out_right, out_bottom = int(coords.right), int(coords.bottom)
                else:
                    out_left, out_top = 0, 0
                    out_right, out_bottom = int(camera.width), int(camera.height)

                overlap_left = max(left, out_left)
                overlap_top = max(top, out_top)
                overlap_right = min(right, out_right)
                overlap_bottom = min(bottom, out_bottom)
                if overlap_right <= overlap_left or overlap_bottom <= overlap_top:
                    continue

                region = (
                    overlap_left - out_left,
                    overlap_top - out_top,
                    overlap_right - out_left,
                    overlap_bottom - out_top,
                )
                try:
                    frame = camera.grab(region=region, new_frame_only=False)
                finally:
                    try:
                        camera.stop()
                    except Exception:
                        pass
                if frame is None:
                    continue

                chunk = PILImage.fromarray(frame).convert("RGB")
                paste_x = overlap_left - left
                paste_y = overlap_top - top
                canvas.paste(chunk, (paste_x, paste_y))
                coverage.paste(255, (paste_x, paste_y, paste_x + chunk.width, paste_y + chunk.height))
                captured_any = True
            except Exception:
                continue

        if captured_any and coverage.getextrema() == (255, 255):
            return canvas
    except Exception:
        return None
    return None


def _capture_screenshot(hwnd: int, max_width: int = 1280) -> dict:
    """Capture window screenshot. Returns dict with path, width, height, dpi_scale."""
    from PIL import Image as PILImage

    # Physical bounds (visible bounds via DWM)
    rect = _get_window_rect(hwnd)
    win_w = rect.right - rect.left
    win_h = rect.bottom - rect.top
    if win_w <= 0 or win_h <= 0:
        return {"error": f"Invalid dimensions: {win_w}x{win_h}"}

    # Logical bounds (DPI virtualized bounds via GetWindowRect)
    logical_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
    log_w = logical_rect.right - logical_rect.left
    log_h = logical_rect.bottom - logical_rect.top

    dpi_scale = _get_dpi_scale(hwnd)
    img = None
    capture_method = "unknown"

    # --- Capture method 1: dxcam (fastest, GPU-accelerated) ---
    img = _capture_dxcam_rect(rect.left, rect.top, rect.right, rect.bottom)
    if img is not None:
        width = win_w
        height = win_h
        capture_method = "dxcam"

    # --- Capture method 2: PrintWindow ---
    if img is None:
        hdc = user32.GetDC(hwnd)
        release_hwnd_dc = True
        hdc_mem = gdi32.CreateCompatibleDC(hdc)
        
        # Use logical size for PrintWindow to prevent black/empty borders
        hbitmap = gdi32.CreateCompatibleBitmap(hdc, log_w, log_h)
        old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)

        captured = user32.PrintWindow(hwnd, hdc_mem, 0x00000002)
        if captured:
            capture_method = "printwindow_full"
        if not captured:
            captured = user32.PrintWindow(hwnd, hdc_mem, 0)
            if captured:
                capture_method = "printwindow"

        if captured:
            # Successfully captured via PrintWindow (logical size)
            width = log_w
            height = log_h
        else:
            # --- Capture method 3: BitBlt from screen DC (physical size) ---
            gdi32.SelectObject(hdc_mem, old_bmp)
            gdi32.DeleteObject(hbitmap)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(hwnd, hdc)
            release_hwnd_dc = False

            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, win_w, win_h)
            old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)
            gdi32.BitBlt(hdc_mem, 0, 0, win_w, win_h,
                         hdc_screen, rect.left, rect.top, 0x00CC0020)
            user32.ReleaseDC(0, hdc_screen)
            width = win_w
            height = win_h
            capture_method = "bitblt"

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)
        gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bmi), 0)

        img = PILImage.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1)

        gdi32.SelectObject(hdc_mem, old_bmp)
        gdi32.DeleteObject(hbitmap)
        gdi32.DeleteDC(hdc_mem)
        if release_hwnd_dc:
            user32.ReleaseDC(hwnd, hdc)

    img = img.convert("RGB")

    if max_width and width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        img = img.resize((max_width, new_height), PILImage.LANCZOS)

    # Save to file in system temp directory to prevent Desktop clutter
    import tempfile
    output_dir = os.path.join(tempfile.gettempdir(), "win-automation-mcp")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "screenshot.png")
    img.save(path, "PNG")

    return {
        "path": path,
        "width": img.width,
        "height": img.height,
        "dpi_scale": dpi_scale,
        "capture_method": capture_method,
        "window_hwnd": hwnd,
    }


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
class HelperHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        ok, status, msg = verify_request(dict(self.headers), EXPECTED_TOKEN)
        if not ok:
            self._send_json({"ok": False, "error": "forbidden", "message": msg}, status=status)
            return

        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/health":
            self._send_json({
                "status": "ok",
                "pid": os.getpid(),
                "started_at": HELPER_STARTED_AT,
                "helper_path": os.path.abspath(__file__),
                "helper_sha256": HELPER_SOURCE_HASH,
                "tools_path": TOOLS_SOURCE_PATH,
                "tools_sha256": TOOLS_SOURCE_HASH,
                "token": _current_process_token_info(),
            })

        elif path == "/list_windows":
            self._handle_list_windows()

        elif path == "/list_apps":
            self._handle_list_apps()

        elif path == "/get_window":
            hwnd = int(params.get("hwnd", [0])[0])
            self._handle_get_window(hwnd)

        elif path == "/screenshot":
            hwnd = int(params.get("hwnd", [0])[0])
            max_w = int(params.get("max_width", [1280])[0])
            self._handle_screenshot(hwnd, max_w)

        elif path == "/screenshot_b64":
            hwnd = int(params.get("hwnd", [0])[0])
            max_w = int(params.get("max_width", [1280])[0])
            self._handle_screenshot_b64(hwnd, max_w)

        elif path == "/get_state":
            self._handle_get_state(params)

        else:
            self._send_json({"error": f"Unknown path: {path}"}, 404)

    def do_POST(self):
        ok, status, msg = verify_request(dict(self.headers), EXPECTED_TOKEN)
        if not ok:
            self._send_json({"ok": False, "error": "forbidden", "message": msg}, status=status)
            return

        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        # Auto-resolve hwnd from state when not provided
        should_resolve_hwnd = (
            path in ("/type_text", "/press_key")
            or (path in ("/move", "/click", "/scroll", "/drag") and not data.get("absolute"))
            or path in ("/smart_click", "/smart_wait_click", "/smart_text", "/smart_wait_text", "/smart_select", "/smart_wait_select", "/smart_cell", "/smart_wait_cell")
        )
        if should_resolve_hwnd:
            if "hwnd" not in data or data["hwnd"] is None:
                target = _load_state().get("target_hwnd")
                if target:
                    data["hwnd"] = target

        if path == "/move":
            self._handle_move(data)
        elif path == "/click":
            self._handle_click(data)
        elif path == "/type_text":
            self._handle_type_text(data)
        elif path == "/press_key":
            self._handle_press_key(data)
        elif path == "/scroll":
            self._handle_scroll(data)
        elif path == "/drag":
            self._handle_drag(data)
        elif path == "/activate":
            self._handle_activate(data)
        elif path == "/win32_text":
            self._handle_win32_text(data)
        elif path == "/win32_set_text":
            self._handle_win32_set_text(data)
        elif path == "/win32_click":
            self._handle_win32_click(data)
        elif path == "/win32_control_find":
            self._handle_win32_control_find(data)
        elif path == "/win32_selector_repair_find":
            self._handle_win32_selector_repair_find(data)
        elif path == "/win32_control_wait_find":
            self._handle_win32_control_wait_find(data)
        elif path == "/win32_control_info":
            self._handle_win32_control_info(data)
        elif path == "/win32_control_action":
            self._handle_win32_control_action(data)
        elif path == "/win32_control_wait":
            self._handle_win32_control_wait(data)
        elif path == "/menu_tree":
            self._handle_menu_tree(data)
        elif path == "/menu_action":
            self._handle_menu_action(data)
        elif path == "/dialog_command_action":
            self._handle_dialog_command_action(data)
        elif path == "/dialog_button_action":
            self._handle_dialog_button_action(data)
        elif path == "/file_dialog_info":
            self._handle_file_dialog_info(data)
        elif path == "/file_dialog_action":
            self._handle_file_dialog_action(data)
        elif path == "/msaa_window":
            self._handle_msaa_window(data)
        elif path == "/msaa_from_point":
            self._handle_msaa_from_point(data)
        elif path == "/msaa_action":
            self._handle_msaa_action(data)
        elif path == "/child_windows":
            self._handle_child_windows(data)
        elif path == "/window_from_point":
            self._handle_window_from_point(data)
        elif path == "/uia_accessibility":
            self._handle_uia_accessibility(data)
        elif path == "/uia_find":
            self._handle_uia_find(data)
        elif path == "/uia_wait":
            self._handle_uia_wait(data)
        elif path == "/uia_element":
            self._handle_uia_element(data)
        elif path == "/uia_focus":
            self._handle_uia_focus(data)
        elif path == "/uia_click_index":
            self._handle_uia_click_index(data)
        elif path == "/uia_set_value":
            self._handle_uia_set_value(data)
        elif path == "/uia_action":
            self._handle_uia_action(data)
        elif path == "/uia_item_container_find":
            self._handle_uia_item_container_find(data)
        elif path == "/uia_selector_repair_find":
            self._handle_uia_selector_repair_find(data)
        elif path == "/uia_cell_selector_repair_find":
            self._handle_uia_cell_selector_repair_find(data)
        elif path == "/smart_click":
            self._handle_smart_click(data)
        elif path == "/smart_wait_click":
            self._handle_smart_wait_click(data)
        elif path == "/smart_text":
            self._handle_smart_text(data)
        elif path == "/smart_wait_text":
            self._handle_smart_wait_text(data)
        elif path == "/smart_select":
            self._handle_smart_select(data)
        elif path == "/smart_wait_select":
            self._handle_smart_wait_select(data)
        elif path == "/smart_cell":
            self._handle_smart_cell(data)
        elif path == "/smart_wait_cell":
            self._handle_smart_wait_cell(data)
        elif path == "/clipboard":
            self._handle_clipboard(data)
        elif path == "/set_clipboard":
            self._handle_set_clipboard(data)
        elif path == "/set_state":
            self._handle_set_state(data)
        elif path == "/batch":
            self._handle_batch(data)
        elif path == "/shutdown":
            self._handle_shutdown()
        else:
            self._send_json({"error": f"Unknown path: {path}"}, 404)

    # ----- Handlers -----

    def _handle_list_windows(self):
        results = []

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
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                proc_name = ""
                proc_path = ""
                try:
                    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
                    if h:
                        pbuf = ctypes.create_unicode_buffer(MAX_PATH)
                        size = ctypes.c_ulong(MAX_PATH)
                        if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                            proc_path = pbuf.value
                            proc_name = os.path.basename(proc_path)
                        kernel32.CloseHandle(h)
                except Exception:
                    pass
                rect = _get_window_rect(hwnd)
                results.append({
                    "hwnd": hwnd, "title": title, "pid": pid.value,
                    "process_name": proc_name,
                    "process_path": proc_path,
                    "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
                })
            except Exception:
                pass
            return True

        user32.EnumWindows(callback, None)
        self._send_json({"windows": results})

    def _handle_get_window(self, hwnd: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        rect = _get_window_rect(hwnd)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_path = _get_process_path(pid.value)
        self._send_json({
            "hwnd": hwnd, "title": buf.value,
            "pid": pid.value,
            "process_name": os.path.basename(proc_path) if proc_path else "",
            "process_path": proc_path,
            "dpi_scale": _get_dpi_scale(hwnd),
            "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
            "width": rect.right - rect.left, "height": rect.bottom - rect.top,
        })

    def _handle_screenshot(self, hwnd: int, max_width: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        result = _capture_screenshot(hwnd, max_width)
        self._send_json(result)

    def _handle_move(self, data: dict):
        hwnd = data.get("hwnd")
        x = data.get("x", 0)
        y = data.get("y", 0)
        settle = float(data.get("settle", data.get("pause", 0.05)) or 0.0)

        if hwnd:
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            ss_w = data.get("screenshot_width")
            ss_h = data.get("screenshot_height")
            if not ss_w:
                ss_w = 1280 if log_w > 1280 else log_w
            if not ss_h:
                ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

            real_x = int(x * log_w / ss_w) + rect.left
            real_y = int(y * log_h / ss_h) + rect.top

            if data.get("activate", True):
                _activate_window(hwnd)
                time.sleep(0.1)
            _set_cursor_pos_checked(real_x, real_y)
            if settle > 0:
                time.sleep(settle)
            self._send_json({"ok": True, "screen_x": real_x, "screen_y": real_y})
        else:
            _set_cursor_pos_checked(int(x), int(y))
            if settle > 0:
                time.sleep(settle)
            self._send_json({"ok": True, "screen_x": int(x), "screen_y": int(y)})

    def _handle_click(self, data: dict):
        hwnd = data.get("hwnd")
        x = data.get("x", 0)
        y = data.get("y", 0)
        button = data.get("button", "left")
        clicks = data.get("clicks", 1)
        try:
            button = _normalize_mouse_button(button)
        except ValueError as e:
            self._send_json({"error": str(e)})
            return

        if hwnd:
            # Get both physical (DWM) and logical (GetWindowRect) bounds
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            # Screenshot is captured at logical size, downscaled to max 1280px
            ss_w = data.get("screenshot_width")
            ss_h = data.get("screenshot_height")
            if not ss_w:
                ss_w = 1280 if log_w > 1280 else log_w
            if not ss_h:
                ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

            # Correct mapping: screenshot -> logical -> physical screen
            # PrintWindow captures at logical size, so ratio uses logical dims
            # Then add DWM offset to get physical screen position
            real_x = int(x * log_w / ss_w) + rect.left
            real_y = int(y * log_h / ss_h) + rect.top

            # Auto-activate
            if data.get("activate", True):
                _activate_window(hwnd)
                time.sleep(0.1)

            # In DPI-aware process, SetCursorPos / SendInput expect physical screen coordinates
            _mouse_click(real_x, real_y, button, clicks)
            self._send_json({"ok": True, "screen_x": real_x, "screen_y": real_y})
        else:
            # Absolute screen coords
            _mouse_click(x, y, button, clicks)
            self._send_json({"ok": True})

    def _handle_type_text(self, data: dict):
        hwnd = data.get("hwnd")
        text = data.get("text", "")

        if not text:
            self._send_json({"error": "No text provided"})
            return

        # Activate window if hwnd provided
        if hwnd and data.get("activate", True):
            _activate_window(hwnd)
            time.sleep(0.1)

        saved = _clipboard_snapshot()
        response = {
            "ok": True,
            "length": len(text),
            "clipboard_saved": bool(saved.get("ok")),
            "clipboard_saved_formats": len(saved.get("formats") or []),
            "clipboard_skipped_formats": len(saved.get("skipped_formats") or []),
            "clipboard_was_empty": bool(saved.get("empty")),
        }
        try:
            _set_clipboard_text(text)
            time.sleep(0.05)

            # Send Ctrl+V through the checked sequence helper so modifiers are
            # released if any SendInput step fails midway.
            _press_scancode_sequence([KEYMAP.get("control_l", 0x1D), KEYMAP.get("v", 0x2F)])
            time.sleep(0.25)
        except Exception as e:
            response = {
                "error": str(e),
                "clipboard_saved": bool(saved.get("ok")),
                "clipboard_saved_formats": len(saved.get("formats") or []),
                "clipboard_skipped_formats": len(saved.get("skipped_formats") or []),
                "clipboard_was_empty": bool(saved.get("empty")),
            }
        finally:
            restore = _clipboard_restore_snapshot(saved)
            response["clipboard_restore_attempted"] = bool(saved.get("ok"))
            response["clipboard_restore_ok"] = bool(restore.get("ok"))
            response["clipboard_restored_formats"] = restore.get("restored_formats", 0)
            if restore.get("skipped_formats"):
                response["clipboard_restore_skipped_formats"] = restore.get("skipped_formats")
            if restore.get("error"):
                response["clipboard_restore_error"] = restore.get("error")
            if restore.get("failures"):
                response["clipboard_restore_failures"] = restore.get("failures")

        self._send_json(response)

    def _handle_press_key(self, data: dict):
        hwnd = data.get("hwnd")
        keys = data.get("keys", "")

        if not keys:
            self._send_json({"error": "No keys provided"})
            return

        # Activate window if hwnd provided
        if hwnd and data.get("activate", True):
            _activate_window(hwnd)
            time.sleep(0.1)

        parts = _split_key_sequence(keys)
        if not parts:
            self._send_json({"error": "No keys provided"})
            return
        scancodes = []
        for part in parts:
            normalized = _normalize_key_name(part)
            sc = KEYMAP.get(normalized)
            if sc is None:
                if len(normalized) == 1:
                    sc = KEYMAP.get(normalized.lower())
                if sc is None:
                    self._send_json({"error": f"Unknown key: {part}"})
                    return
            scancodes.append(sc)

        try:
            _press_scancode_sequence(scancodes)
        except Exception as e:
            self._send_json({"error": str(e), "keys": keys, "release_attempted": True})
            return

        self._send_json({"ok": True, "keys": keys})

    def _handle_scroll(self, data: dict):
        hwnd = data.get("hwnd")
        x = data.get("x", 0)
        y = data.get("y", 0)
        delta = data.get("delta", 120)
        clicks = data.get("clicks", 3)

        if hwnd:
            # Get both physical (DWM) and logical (GetWindowRect) bounds
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            ss_w = data.get("screenshot_width")
            ss_h = data.get("screenshot_height")
            if not ss_w:
                ss_w = 1280 if log_w > 1280 else log_w
            if not ss_h:
                ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

            # Correct mapping: screenshot -> logical -> physical screen
            real_x = int(x * log_w / ss_w) + rect.left
            real_y = int(y * log_h / ss_h) + rect.top

            if data.get("activate", True):
                _activate_window(hwnd)
                time.sleep(0.1)

            # Move cursor first using physical coordinates
            _set_cursor_pos_checked(real_x, real_y)
            time.sleep(0.05)

            for _ in range(abs(clicks)):
                _mouse_scroll(real_x, real_y, delta if clicks > 0 else -delta)
                time.sleep(0.05)

            self._send_json({"ok": True, "screen_x": real_x, "screen_y": real_y})
        else:
            _set_cursor_pos_checked(x, y)
            time.sleep(0.05)
            for _ in range(abs(clicks)):
                _mouse_scroll(x, y, delta if clicks > 0 else -delta)
                time.sleep(0.05)
            self._send_json({"ok": True})

    def _handle_drag(self, data: dict):
        hwnd = data.get("hwnd")
        start_x = int(data.get("start_x", data.get("x1", 0)) or 0)
        start_y = int(data.get("start_y", data.get("y1", 0)) or 0)
        end_x = int(data.get("end_x", data.get("x2", 0)) or 0)
        end_y = int(data.get("end_y", data.get("y2", 0)) or 0)
        duration = float(data.get("duration", 0.5) or 0.0)
        button = data.get("button", "left")
        try:
            button = _normalize_mouse_button(button)
        except ValueError as e:
            self._send_json({"error": str(e)})
            return

        if hwnd:
            rect = _get_window_rect(hwnd)
            logical_rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(logical_rect))
            log_w = logical_rect.right - logical_rect.left
            log_h = logical_rect.bottom - logical_rect.top

            ss_w = data.get("screenshot_width")
            ss_h = data.get("screenshot_height")
            if not ss_w:
                ss_w = 1280 if log_w > 1280 else log_w
            if not ss_h:
                ss_h = int(log_h * 1280 / log_w) if log_w > 1280 else log_h

            screen_start_x = int(start_x * log_w / ss_w) + rect.left
            screen_start_y = int(start_y * log_h / ss_h) + rect.top
            screen_end_x = int(end_x * log_w / ss_w) + rect.left
            screen_end_y = int(end_y * log_h / ss_h) + rect.top

            if data.get("activate", True):
                _activate_window(hwnd)
                time.sleep(0.1)
        else:
            screen_start_x = start_x
            screen_start_y = start_y
            screen_end_x = end_x
            screen_end_y = end_y

        _mouse_drag(screen_start_x, screen_start_y, screen_end_x, screen_end_y, duration=duration, button=button)
        self._send_json({
            "ok": True,
            "screen_start_x": screen_start_x,
            "screen_start_y": screen_start_y,
            "screen_end_x": screen_end_x,
            "screen_end_y": screen_end_y,
            "duration": duration,
            "button": button,
        })

    def _handle_activate(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        activation = _activate_window(hwnd)
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        self._send_json({"ok": bool(activation.get("ok")), "title": buf.value, "activation": activation})

    def _handle_win32_text(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_win32_text(int(hwnd), timeout_ms=int(data.get("timeout_ms", 500) or 500), max_chars=int(data.get("max_chars", 8192) or 8192)))

    def _handle_win32_set_text(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_win32_set_text(int(hwnd), str(data.get("text", "")), timeout_ms=int(data.get("timeout_ms", 500) or 500)))

    def _handle_win32_click(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_win32_click(int(hwnd), timeout_ms=int(data.get("timeout_ms", 500) or 500)))

    def _handle_win32_control_find(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.win32_control_find,
                int(hwnd),
                name=data.get("name"),
                automation_id=data.get("automation_id", data.get("automationId")),
                control_type=data.get("control_type", data.get("type")),
                class_name=data.get("class_name", data.get("class")),
                text=data.get("text"),
                value=data.get("value"),
                state=data.get("state"),
                expected=data.get("expected", data.get("checked")),
                match=str(data.get("match", "contains") or "contains"),
                include_invisible=_coerce_bool(data.get("include_invisible"), False),
                include_self=_coerce_bool(data.get("include_self"), True),
                limit=int(data.get("limit", 20) or 20),
                min_score=data.get("min_score"),
                timeout_ms=int(data.get("timeout_ms", 250) or 250),
                max_items=int(data.get("max_items", 200) or 200),
                max_children=int(data.get("max_children", 1000) or 1000),
                diagnostic=_coerce_bool(data.get("diagnostic"), False),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd)})

    def _handle_win32_selector_repair_find(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.win32_selector_repair_find,
                int(hwnd),
                data.get("suggestion") if isinstance(data.get("suggestion"), dict) else {},
                original=data.get("original") if isinstance(data.get("original"), dict) else {},
                limit=int(data.get("limit", 1) or 1),
                include_invisible=data.get("include_invisible"),
                include_self=data.get("include_self"),
                min_score=data.get("min_score"),
                timeout_ms=data.get("timeout_ms"),
                max_items=data.get("max_items"),
                max_children=data.get("max_children"),
                diagnostic=data.get("diagnostic"),
                allow_suggestion_hwnd=_coerce_bool(data.get("allow_suggestion_hwnd"), False),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd)})

    def _handle_win32_control_wait_find(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.win32_control_wait_find,
                int(hwnd),
                name=data.get("name"),
                automation_id=data.get("automation_id", data.get("automationId")),
                control_type=data.get("control_type", data.get("type")),
                class_name=data.get("class_name", data.get("class")),
                text=data.get("text"),
                value=data.get("value"),
                state=data.get("state"),
                expected=data.get("expected", data.get("checked")),
                match=str(data.get("match", "contains") or "contains"),
                include_invisible=_coerce_bool(data.get("include_invisible"), False),
                include_self=_coerce_bool(data.get("include_self"), True),
                limit=int(data.get("limit", 20) or 20),
                min_score=data.get("min_score"),
                timeout=float(data.get("timeout", 3.0) or 3.0),
                interval=float(data.get("interval", 0.1) or 0.1),
                timeout_ms=int(data.get("timeout_ms", 250) or 250),
                max_items=int(data.get("max_items", 200) or 200),
                max_children=int(data.get("max_children", 1000) or 1000),
                diagnostic=_coerce_bool(data.get("diagnostic"), False),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd)})

    def _handle_win32_control_info(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.win32_control_info,
                int(hwnd),
                timeout_ms=int(data.get("timeout_ms", 250) or 250),
                max_items=int(data.get("max_items", 200) or 200),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd)})

    def _handle_win32_control_action(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.win32_control_action,
                int(hwnd),
                str(data.get("action", "select")),
                index=data.get("index"),
                text=data.get("text"),
                value=data.get("value"),
                checked=data.get("checked"),
                match=str(data.get("match", "contains") or "contains"),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd), "action": data.get("action")})

    def _handle_win32_control_wait(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.win32_control_wait,
                int(hwnd),
                state=data.get("state") or data.get("field"),
                expected=data.get("expected", data.get("value", data.get("checked"))),
                index=data.get("index"),
                text=data.get("text", data.get("item")),
                match=str(data.get("match", "contains") or "contains"),
                timeout=float(data.get("timeout", 3.0) or 3.0),
                interval=float(data.get("interval", 0.1) or 0.1),
                timeout_ms=int(data.get("timeout_ms", 250) or 250),
                max_items=int(data.get("max_items", 200) or 200),
                diagnostic=_coerce_bool(data.get("diagnostic"), False),
                repair=data.get("repair", data.get("native_wait_repair", data.get("native-wait-repair"))),
                repair_match=data.get("repair_match", data.get("repair-match", data.get("native_wait_repair_match", data.get("native-wait-repair-match")))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("native_wait_repair_timeout", data.get("native-wait-repair-timeout")))),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd), "state": data.get("state")})

    def _handle_menu_tree(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.menu_tree,
                int(hwnd),
                include_system=bool(data.get("include_system", False)),
                max_depth=int(data.get("max_depth", 5) or 5),
                max_items=int(data.get("max_items", 300) or 300),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd)})

    def _handle_menu_action(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.menu_action,
                int(hwnd),
                path=data.get("path"),
                command_id=data.get("command_id"),
                include_system=bool(data.get("include_system", False)),
                async_post=bool(data.get("async_post", False)),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd), "path": data.get("path"), "command_id": data.get("command_id")})

    def _handle_dialog_command_action(self, data: dict):
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.dialog_command_action,
                data.get("hwnd"),
                action=data.get("action") or data.get("command") or data.get("dialog_action") or data.get("dialog-action"),
                command_id=data.get("command_id", data.get("command-id", data.get("id"))),
                name=data.get("name") or data.get("text"),
                dialog_title=data.get("dialog_title") or data.get("dialog-title") or data.get("title"),
                dialog_class_name=data.get("dialog_class_name") or data.get("dialog-class-name") or data.get("dialog_class") or data.get("dialog-class"),
                dialog_process=data.get("dialog_process") or data.get("dialog-process") or data.get("process"),
                match=str(data.get("match", "contains") or "contains"),
                timeout=float(data.get("timeout", 10.0) or 10.0),
                interval=float(data.get("interval", 0.25) or 0.25),
                timeout_ms=int(data.get("timeout_ms", data.get("timeout-ms", 500)) or 500),
                include_invisible=_coerce_bool(data.get("include_invisible", data.get("include-invisible")), False),
                activate=_coerce_bool(data.get("activate"), True),
                verify_close=_coerce_bool(data.get("verify_close", data.get("verify-close")), False),
                diagnostic=_coerce_bool(data.get("diagnostic", data.get("verbose")), False),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "action": data.get("action"), "hwnd": data.get("hwnd")})

    def _handle_dialog_button_action(self, data: dict):
        try:
            tools_mod = _load_tools_module()
            raw_index = data.get("index")
            index = int(raw_index) if raw_index is not None else None
            self._send_json(_call_tools_no_reenter(
                tools_mod.dialog_button_action,
                data.get("hwnd"),
                name=data.get("name") or data.get("text"),
                action=data.get("action") or data.get("command") or data.get("dialog_action") or data.get("dialog-action"),
                command_id=data.get("command_id", data.get("command-id", data.get("id"))),
                dialog_title=data.get("dialog_title") or data.get("dialog-title") or data.get("title"),
                dialog_class_name=data.get("dialog_class_name") or data.get("dialog-class-name") or data.get("dialog_class") or data.get("dialog-class"),
                dialog_process=data.get("dialog_process") or data.get("dialog-process") or data.get("process"),
                automation_id=data.get("automation_id") or data.get("automation-id"),
                class_name=data.get("class_name") or data.get("class-name") or data.get("class"),
                control_type=data.get("control_type") or data.get("control-type") or data.get("type"),
                index=index,
                match=str(data.get("match", "contains") or "contains"),
                timeout=float(data.get("timeout", 10.0) or 10.0),
                interval=float(data.get("interval", 0.25) or 0.25),
                timeout_ms=int(data.get("timeout_ms", data.get("timeout-ms", 500)) or 500),
                include_invisible=_coerce_bool(data.get("include_invisible", data.get("include-invisible")), False),
                activate=_coerce_bool(data.get("activate"), True),
                verify_close=_coerce_bool(data.get("verify_close", data.get("verify-close")), False),
                prefer_command=_coerce_bool(data.get("prefer_command", data.get("prefer-command")), True),
                diagnostic=_coerce_bool(data.get("diagnostic", data.get("verbose")), False),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "action": data.get("action"), "hwnd": data.get("hwnd")})

    def _handle_file_dialog_info(self, data: dict):
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.file_dialog_info,
                hwnd=data.get("hwnd"),
                timeout=float(data.get("timeout", 0.0) or 0.0),
                timeout_ms=int(data.get("timeout_ms", 300) or 300),
                include_children=_coerce_bool(data.get("include_children"), False),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": data.get("hwnd")})

    def _handle_file_dialog_action(self, data: dict):
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.file_dialog_action,
                str(data.get("action", "info")),
                hwnd=data.get("hwnd"),
                path=data.get("path") or data.get("file_dialog_path") or data.get("filename") or data.get("file"),
                timeout=float(data.get("timeout", 5.0) or 5.0),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                verify_close=_coerce_bool(data.get("verify_close"), False),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "action": data.get("action"), "hwnd": data.get("hwnd")})

    def _handle_msaa_window(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.msaa_window,
                int(hwnd),
                max_children=int(data.get("max_children", 80) or 80),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd)})

    def _handle_msaa_from_point(self, data: dict):
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            point = ctypes.wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                self._send_json({"error": "GetCursorPos failed"})
                return
            x, y = int(point.x), int(point.y)
        try:
            tools_mod = _load_tools_module()
            self._send_json(_call_tools_no_reenter(
                tools_mod.msaa_from_point,
                int(x),
                int(y),
                hwnd=data.get("hwnd"),
                screenshot_id=data.get("screenshot_id"),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "screen": {"x": int(x), "y": int(y)}})

    def _handle_msaa_action(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        try:
            tools_mod = _load_tools_module()
            child_id = data.get("child_id", 0)
            if child_id is None:
                child_id = 0
            self._send_json(_call_tools_no_reenter(
                tools_mod.msaa_action,
                int(hwnd),
                path=data.get("path") or [],
                child_id=int(child_id),
                action=str(data.get("action", "default") or "default"),
                value=data.get("value"),
            ))
        except Exception as e:
            self._send_json({"ok": False, "error": str(e), "hwnd": int(hwnd), "action": data.get("action")})

    def _handle_child_windows(self, data: dict):
        hwnd = data.get("hwnd")
        if not hwnd:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_child_windows(
            int(hwnd),
            include_invisible=bool(data.get("include_invisible", False)),
            include_text=bool(data.get("include_text", False)),
            max_count=int(data.get("max_count", 500) or 500),
        ))

    def _handle_window_from_point(self, data: dict):
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            point = ctypes.wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                self._send_json({"error": "GetCursorPos failed"})
                return
            x, y = int(point.x), int(point.y)
        self._send_json(_window_from_point(
            int(x),
            int(y),
            include_text=bool(data.get("include_text", False)),
        ))

    def _handle_uia_accessibility(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        payload = dict(data)
        self._send_json(_call_tools_worker("uia_accessibility", payload, timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_find(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_find", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_wait(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        timeout_value = float(data.get("timeout", 10.0) or 10.0)
        worker_timeout = _wait_repair_worker_timeout(data, timeout_value)
        self._send_json(_call_tools_worker("uia_wait", dict(data), timeout=worker_timeout))

    def _handle_uia_element(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_element", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_focus(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_focus", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_click_index(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_click_index", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_set_value(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_set_value", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_action(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_action", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_item_container_find(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_item_container_find", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_selector_repair_find(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_selector_repair_find", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_uia_cell_selector_repair_find(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("uia_cell_selector_repair_find", dict(data), timeout=float(data.get("uia_timeout", UIA_WORKER_DEFAULT_TIMEOUT) or UIA_WORKER_DEFAULT_TIMEOUT)))

    def _handle_smart_click(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("smart_click", dict(data), timeout=_smart_repair_worker_timeout(data)))

    def _handle_smart_wait_click(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        timeout_value = float(data.get("timeout", 10.0) or 10.0)
        timeout = _wait_repair_worker_timeout(data, timeout_value)
        self._send_json(_call_tools_worker("smart_wait_click", dict(data), timeout=timeout))

    def _handle_smart_text(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("smart_text", dict(data), timeout=_smart_repair_worker_timeout(data, base_timeout=float(data.get("timeout", 1.0) or 1.0))))

    def _handle_smart_wait_text(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        timeout_value = float(data.get("timeout", 10.0) or 10.0)
        timeout = _wait_repair_worker_timeout(data, timeout_value)
        self._send_json(_call_tools_worker("smart_wait_text", dict(data), timeout=timeout))

    def _handle_smart_select(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("smart_select", dict(data), timeout=_smart_repair_worker_timeout(data)))

    def _handle_smart_wait_select(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        timeout_value = float(data.get("timeout", 10.0) or 10.0)
        timeout = _wait_repair_worker_timeout(data, timeout_value)
        self._send_json(_call_tools_worker("smart_wait_select", dict(data), timeout=timeout))

    def _handle_smart_cell(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        self._send_json(_call_tools_worker("smart_cell", dict(data), timeout=_smart_repair_worker_timeout(data)))

    def _handle_smart_wait_cell(self, data: dict):
        hwnd = data.get("hwnd")
        if hwnd is None:
            self._send_json({"error": "No hwnd provided"})
            return
        timeout_value = float(data.get("timeout", 10.0) or 10.0)
        timeout = _wait_repair_worker_timeout(data, timeout_value)
        self._send_json(_call_tools_worker("smart_wait_cell", dict(data), timeout=timeout))

    def _handle_clipboard(self, data: dict):
        action = data.get("action", "get")
        if action == "get":
            saved = _clipboard_save()
            if saved:
                try:
                    text = saved.decode("utf-16-le")
                except Exception:
                    text = ""
                self._send_json({"text": text})
            else:
                self._send_json({"text": ""})
        elif action == "save":
            saved = _clipboard_save()
            # Store in a file for later restore
            save_path = os.path.join(os.path.expanduser("~"), ".win-auto-clipboard")
            with open(save_path, "wb") as f:
                f.write(saved if saved else b"")
            self._send_json({"ok": True})
        elif action == "restore":
            save_path = os.path.join(os.path.expanduser("~"), ".win-auto-clipboard")
            if os.path.exists(save_path):
                with open(save_path, "rb") as f:
                    data = f.read()
                _clipboard_restore(data if data else None)
                os.remove(save_path)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "No saved clipboard"})

    def _handle_set_clipboard(self, data: dict):
        text = data.get("text", "")
        try:
            _set_clipboard_text(text)
            self._send_json({"ok": True, "length": len(text)})
        except Exception as e:
            self._send_json({"error": str(e), "length": len(text)})

    def _handle_shutdown(self):
        self._send_json({"ok": True, "pid": os.getpid()})

        def stop_server():
            time.sleep(0.05)
            try:
                self.server.shutdown()
            except Exception:
                pass

        threading.Thread(target=stop_server, daemon=True).start()

    def _handle_list_apps(self):
        windows_by_pid = {}

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
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pid_val = pid.value
                rect = _get_window_rect(hwnd)
                win_info = {
                    "hwnd": hwnd, "title": title, "pid": pid_val,
                    "rect": {"left": rect.left, "top": rect.top,
                             "right": rect.right, "bottom": rect.bottom},
                }
                if pid_val not in windows_by_pid:
                    proc_path = _get_process_path(pid_val)
                    windows_by_pid[pid_val] = {
                        "app_name": os.path.basename(proc_path) if proc_path else "",
                        "app_path": proc_path,
                        "is_running": True,
                        "windows": [],
                    }
                windows_by_pid[pid_val]["windows"].append(win_info)
            except Exception:
                pass
            return True

        user32.EnumWindows(callback, None)
        results = list(windows_by_pid.values())
        self._send_json(results)

    def _handle_screenshot_b64(self, hwnd: int, max_width: int):
        if not user32.IsWindow(hwnd):
            self._send_json({"error": f"Window {hwnd} no longer exists"})
            return
        result = _capture_screenshot(hwnd, max_width)
        if "error" in result:
            self._send_json(result)
            return
        # Read file and convert to base64
        try:
            with open(result["path"], "rb") as f:
                png_data = f.read()
            self._send_json({
                "text": "Captured window screenshot.",
                "base64": base64.b64encode(png_data).decode("ascii"),
                "width": result["width"],
                "height": result["height"],
                "dpi_scale": result.get("dpi_scale", 1.0),
            })
        except Exception as e:
            self._send_json({"error": str(e)})

    def _handle_get_state(self, params: dict):
        state = _load_state()
        key = params.get("key", [None])[0]
        if key:
            if key in state:
                self._send_json({key: state[key]})
            else:
                self._send_json({"error": f"Key '{key}' not found"})
        else:
            self._send_json({"state": state})

    def _handle_set_state(self, data: dict):
        state = _load_state()
        state.update(data)
        _save_state(state)
        self._send_json({"ok": True, "state": state})

    def _handle_batch(self, data: dict):
        commands = data.get("commands", [])
        stop_on_error = bool(data.get("stop_on_error", data.get("stop-on-error", False)))
        results = []
        stopped_on_error = False
        for index, cmd in enumerate(commands):
            step_start = time.perf_counter()
            if not isinstance(cmd, dict):
                item = _batch_invalid_item(index, cmd)
                item["elapsed_ms"] = round((time.perf_counter() - step_start) * 1000.0, 3)
                results.append(item)
                if stop_on_error:
                    stopped_on_error = True
                    break
                continue
            path = _normalize_batch_path(cmd.get("path", ""))
            cmd_data = _batch_item_args(cmd, use_data=True)
            command = _normalize_batch_command_name(cmd.get("command", ""))
            if not path and "command" in cmd:
                cmd_data = _batch_item_args(cmd)
                path = _BATCH_COMMAND_TO_PATH.get(command, command)
            step_id = _batch_step_id(cmd)
            skip = _batch_skip_decision(cmd, results)
            if skip:
                item = {
                    "index": index,
                    "id": step_id,
                    "path": path,
                    "command": command or None,
                    "result": {"ok": True, "skipped": True, **skip},
                    "attempts": 0,
                    "elapsed_ms": round((time.perf_counter() - step_start) * 1000.0, 3),
                }
                results.append(_batch_normalize_item(item, index))
                continue
            if isinstance(cmd_data, dict) and "__batch_arg_error__" not in cmd_data:
                cmd_data = _batch_resolve_refs(cmd_data, results)
            retry_count, retry_delay = _batch_retry_options(cmd)
            expectation = _batch_expectation_spec(cmd)
            extract = _batch_extract_spec(cmd)
            allow_failure = _batch_allows_failure(cmd)
            arg_error = _batch_arg_error(cmd_data)
            attempts = 1
            last_failure = None
            if arg_error:
                result = arg_error
            else:
                result = _batch_normalize_result(self._dispatch_command(path, cmd_data))
                result = _batch_apply_expectation(result, expectation, results)
                result = _batch_apply_extract(result, extract, results)
                last_failure = _batch_result_failure(result)
                while last_failure and attempts <= retry_count:
                    if retry_delay > 0:
                        time.sleep(retry_delay)
                    attempts += 1
                    result = _batch_normalize_result(self._dispatch_command(path, cmd_data))
                    result = _batch_apply_expectation(result, expectation, results)
                    result = _batch_apply_extract(result, extract, results)
                    last_failure = _batch_result_failure(result)
            if allow_failure:
                tolerated_failure = _batch_result_failure(result)
                if tolerated_failure:
                    result = {
                        "ok": True,
                        "tolerated_failure": True,
                        "failure": tolerated_failure,
                        "original_result": result,
                    }
            item = {"index": index, "id": step_id, "path": path, "command": command or None, "result": result, "attempts": attempts}
            if retry_count:
                item["retries"] = retry_count
                item["retry_delay"] = retry_delay
            if allow_failure:
                item["allow_failure"] = True
            item["elapsed_ms"] = round((time.perf_counter() - step_start) * 1000.0, 3)
            results.append(_batch_normalize_item(item, index))
            if stop_on_error and _batch_result_failure(result):
                stopped_on_error = True
                break
        summary = _batch_summary(results, total_count=len(commands), stopped_on_error=stopped_on_error)
        self._send_json({"results": results, **summary})

    def _dispatch_command(self, path: str, data: dict) -> dict:
        """Dispatch a single command for batch processing."""
        dispatch = {
            "/activate": self._handle_activate,
            "/move": self._handle_move,
            "/click": self._handle_click,
            "/type_text": self._handle_type_text,
            "/press_key": self._handle_press_key,
            "/scroll": self._handle_scroll,
            "/drag": self._handle_drag,
            "/win32_text": self._handle_win32_text,
            "/win32_set_text": self._handle_win32_set_text,
            "/win32_click": self._handle_win32_click,
            "/win32_control_find": self._handle_win32_control_find,
            "/win32_selector_repair_find": self._handle_win32_selector_repair_find,
            "/win32_control_wait_find": self._handle_win32_control_wait_find,
            "/win32_control_info": self._handle_win32_control_info,
            "/win32_control_action": self._handle_win32_control_action,
            "/win32_control_wait": self._handle_win32_control_wait,
            "/menu_tree": self._handle_menu_tree,
            "/menu_action": self._handle_menu_action,
            "/dialog_command_action": self._handle_dialog_command_action,
            "/dialog_button_action": self._handle_dialog_button_action,
            "/file_dialog_info": self._handle_file_dialog_info,
            "/file_dialog_action": self._handle_file_dialog_action,
            "/msaa_window": self._handle_msaa_window,
            "/msaa_from_point": self._handle_msaa_from_point,
            "/msaa_action": self._handle_msaa_action,
            "/child_windows": self._handle_child_windows,
            "/window_from_point": self._handle_window_from_point,
            "/uia_accessibility": self._handle_uia_accessibility,
            "/uia_find": self._handle_uia_find,
            "/uia_wait": self._handle_uia_wait,
            "/uia_element": self._handle_uia_element,
            "/uia_focus": self._handle_uia_focus,
            "/uia_click_index": self._handle_uia_click_index,
            "/uia_set_value": self._handle_uia_set_value,
            "/uia_action": self._handle_uia_action,
            "/uia_item_container_find": self._handle_uia_item_container_find,
            "/uia_selector_repair_find": self._handle_uia_selector_repair_find,
            "/uia_cell_selector_repair_find": self._handle_uia_cell_selector_repair_find,
            "/smart_click": self._handle_smart_click,
            "/smart_wait_click": self._handle_smart_wait_click,
            "/smart_text": self._handle_smart_text,
            "/smart_wait_text": self._handle_smart_wait_text,
            "/smart_select": self._handle_smart_select,
            "/smart_wait_select": self._handle_smart_wait_select,
            "/smart_cell": self._handle_smart_cell,
            "/smart_wait_cell": self._handle_smart_wait_cell,
            "/clipboard": self._handle_clipboard,
            "/set_clipboard": self._handle_set_clipboard,
        }
        handler = dispatch.get(path)
        if not handler:
            return {"error": f"Unknown command path: {path}"}

        # Capture response by temporarily overriding _send_json
        captured = {}
        original_send = self._send_json

        def capturing_send(data_arg, status=200):
            captured["response"] = data_arg

        self._send_json = capturing_send
        try:
            handler(data)
        except Exception as e:
            captured["response"] = {"error": str(e)}
        finally:
            self._send_json = original_send

        return captured.get("response", {"error": "No response"})

    def _resolve_hwnd(self, data: dict) -> int | None:
        """Resolve hwnd from data dict, falling back to stored target_hwnd."""
        hwnd = data.get("hwnd")
        if hwnd:
            return hwnd
        return _load_state().get("target_hwnd")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _worker_uia_main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        command = str(payload.get("command") or "")
        data = dict(payload.get("data") or {})
        tools_mod = _load_tools_module()
        hwnd = int(data.get("hwnd"))
        if command == "uia_accessibility":
            result = _call_tools_no_reenter(
                tools_mod.build_accessibility_tree,
                hwnd,
                max_depth=int(data.get("max_depth", 10) or 10),
                max_elements=int(data.get("max_elements", 500) or 500),
                hydrate=bool(data.get("hydrate", True)),
                view=str(data.get("view", "raw") or "raw"),
            )
        elif command == "uia_find":
            result = _call_tools_no_reenter(
                tools_mod.find_elements,
                hwnd,
                name=data.get("name"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                value=data.get("value"),
                pattern=data.get("pattern"),
                enabled_only=bool(data.get("enabled_only", False)),
                visible_only=bool(data.get("visible_only", True)),
                match=str(data.get("match", "contains") or "contains"),
                limit=int(data.get("limit", 25) or 25),
                max_depth=int(data.get("max_depth", 10) or 10),
                max_elements=int(data.get("max_elements", 500) or 500),
                view=str(data.get("view", "raw") or "raw"),
            )
        elif command == "uia_wait":
            selector = dict(data.get("selector") or {})
            for key in ("name", "automation_id", "control_type", "class_name", "value", "pattern", "enabled_only", "visible_only", "match", "max_depth", "max_elements", "view"):
                if key not in selector and key in data:
                    selector[key] = data.get(key)
            result = _call_tools_no_reenter(
                tools_mod.wait_for_element,
                hwnd,
                selector,
                timeout=float(data.get("timeout", 10.0) or 10.0),
                interval=float(data.get("interval", 0.5) or 0.5),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
                allow_suggestion_index=_coerce_bool(_dict_get_any(data, "allow_suggestion_index", "allow-suggestion-index"), False),
            )
        elif command == "uia_element":
            index = int(data.get("index"))
            if hwnd == int(getattr(tools_mod, "_DESKTOP_UIA_KEY", 0)):
                result = _call_tools_no_reenter(
                    tools_mod.desktop_element,
                    index,
                    max_depth=data.get("max_depth"),
                    max_elements=data.get("max_elements"),
                    view=data.get("view"),
                )
            else:
                _, result = _call_tools_no_reenter(
                    tools_mod._uia_element_by_index,
                    hwnd,
                    index,
                    max_depth=data.get("max_depth"),
                    max_elements=data.get("max_elements"),
                    view=data.get("view"),
                )
                if not result:
                    result = {"error": f"Element index {index} not found", "hwnd": hwnd, "index": index}
        elif command == "uia_focus":
            result = _call_tools_no_reenter(
                tools_mod.focus_element,
                hwnd,
                int(data.get("index")),
                max_depth=data.get("max_depth"),
                max_elements=data.get("max_elements"),
                view=data.get("view"),
            )
        elif command == "uia_click_index":
            message = _call_tools_no_reenter(
                tools_mod.click_index,
                hwnd,
                int(data.get("index")),
                button=str(data.get("button", "left") or "left"),
                clicks=int(data.get("clicks", 1) or 1),
                max_depth=data.get("max_depth"),
                max_elements=data.get("max_elements"),
                view=data.get("view"),
            )
            result = None
            if isinstance(message, str):
                try:
                    decoded = json.loads(message)
                    if isinstance(decoded, dict):
                        result = decoded
                except Exception:
                    result = None
            if result is None:
                result = {"ok": not str(message).lower().startswith("error"), "message": message, "hwnd": hwnd, "index": int(data.get("index"))}
        elif command == "uia_set_value":
            result = _call_tools_no_reenter(
                tools_mod.set_value,
                hwnd,
                int(data.get("index")),
                str(data.get("value", "")),
                max_depth=data.get("max_depth"),
                max_elements=data.get("max_elements"),
                view=data.get("view"),
            )
        elif command == "uia_action":
            result = _call_tools_no_reenter(
                tools_mod.perform_action,
                hwnd,
                int(data.get("index")),
                str(data.get("action", "invoke") or "invoke"),
                value=data.get("value"),
                horizontal=data.get("horizontal"),
                vertical=data.get("vertical"),
                max_depth=data.get("max_depth"),
                max_elements=data.get("max_elements"),
                view=data.get("view"),
            )
        elif command == "uia_item_container_find":
            result = _call_tools_no_reenter(
                tools_mod.item_container_find,
                hwnd,
                int(data.get("index")),
                str(data.get("property_name", "name") or "name"),
                data.get("property_value", data.get("value", "")),
                limit=int(data.get("limit", 1) or 1),
                max_depth=data.get("max_depth"),
                max_elements=data.get("max_elements"),
                view=data.get("view"),
                include_children=bool(data.get("include_children", False)),
                max_children=int(data.get("max_children", 64) or 64),
            )
        elif command == "uia_selector_repair_find":
            result = _call_tools_no_reenter(
                tools_mod.uia_selector_repair_find,
                hwnd,
                data.get("suggestion") if isinstance(data.get("suggestion"), dict) else {},
                original=data.get("original") if isinstance(data.get("original"), dict) else {},
                limit=int(data.get("limit", 1) or 1),
                max_depth=data.get("max_depth"),
                max_elements=data.get("max_elements"),
                view=data.get("view"),
                allow_suggestion_index=_coerce_bool(_dict_get_any(data, "allow_suggestion_index", "allow-suggestion-index"), False),
            )
        elif command == "uia_cell_selector_repair_find":
            result = _call_tools_no_reenter(
                tools_mod.uia_cell_selector_repair_find,
                hwnd,
                data.get("suggestion") if isinstance(data.get("suggestion"), dict) else {},
                data.get("original") if isinstance(data.get("original"), dict) else {},
                row=data.get("row"),
                column=data.get("column"),
                row_text=data.get("row_text"),
                column_name=data.get("column_name"),
                limit=int(data.get("limit", 1) or 1),
                max_depth=data.get("max_depth"),
                max_elements=data.get("max_elements"),
                view=data.get("view"),
            )
        elif command == "smart_click":
            result = _call_tools_no_reenter(
                tools_mod.smart_click,
                hwnd,
                name=data.get("name"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                index=data.get("index"),
                match=str(data.get("match", "contains") or "contains"),
                action=str(data.get("action", "invoke") or "invoke"),
                button=str(data.get("button", "left") or "left"),
                clicks=int(data.get("clicks", 1) or 1),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                diagnostic=bool(data.get("diagnostic", False)),
                allow_coordinate_fallback=bool(data.get("allow_coordinate_fallback", False)),
                skip_uia=bool(data.get("skip_uia", False)),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            )
        elif command == "smart_wait_click":
            result = _call_tools_no_reenter(
                tools_mod.smart_wait_click,
                hwnd,
                name=data.get("name"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                index=data.get("index"),
                match=str(data.get("match", "contains") or "contains"),
                action=str(data.get("action", "invoke") or "invoke"),
                timeout=float(data.get("timeout", 10.0) or 10.0),
                interval=float(data.get("interval", 0.25) or 0.25),
                button=str(data.get("button", "left") or "left"),
                clicks=int(data.get("clicks", 1) or 1),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                diagnostic=bool(data.get("diagnostic", False)),
                allow_coordinate_fallback=bool(data.get("allow_coordinate_fallback", False)),
                skip_uia=bool(data.get("skip_uia", False)),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            )
        elif command == "smart_text":
            result = _call_tools_no_reenter(
                tools_mod.smart_text_input,
                hwnd,
                str(data.get("text", "") or ""),
                name=data.get("name"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                index=data.get("index"),
                match=str(data.get("match", "contains") or "contains"),
                mode=str(data.get("mode", "set-text") or "set-text"),
                timeout=float(data.get("timeout", 1.0) or 1.0),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                verify=bool(data.get("verify", True)),
                diagnostic=bool(data.get("diagnostic", False)),
                allow_focus_fallback=bool(data.get("allow_focus_fallback", False)),
                skip_uia=bool(data.get("skip_uia", False)),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            )
        elif command == "smart_wait_text":
            result = _call_tools_no_reenter(
                tools_mod.smart_wait_text_input,
                hwnd,
                str(data.get("text", "") or ""),
                name=data.get("name"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                index=data.get("index"),
                match=str(data.get("match", "contains") or "contains"),
                mode=str(data.get("mode", "set-text") or "set-text"),
                timeout=float(data.get("timeout", 10.0) or 10.0),
                interval=float(data.get("interval", 0.25) or 0.25),
                input_timeout=float(data.get("input_timeout", 1.0) or 1.0),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                verify=bool(data.get("verify", True)),
                diagnostic=bool(data.get("diagnostic", False)),
                allow_focus_fallback=bool(data.get("allow_focus_fallback", False)),
                skip_uia=bool(data.get("skip_uia", False)),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            )
        elif command == "smart_select":
            result = _call_tools_no_reenter(
                tools_mod.smart_select,
                hwnd,
                item=data.get("item"),
                name=data.get("name"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                index=data.get("index"),
                match=str(data.get("match", "contains") or "contains"),
                mode=str(data.get("mode", "select") or "select"),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                diagnostic=bool(data.get("diagnostic", False)),
                skip_uia=bool(data.get("skip_uia", False)),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            )
        elif command == "smart_wait_select":
            result = _call_tools_no_reenter(
                tools_mod.smart_wait_select,
                hwnd,
                item=data.get("item"),
                name=data.get("name"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                index=data.get("index"),
                match=str(data.get("match", "contains") or "contains"),
                mode=str(data.get("mode", "select") or "select"),
                timeout=float(data.get("timeout", 10.0) or 10.0),
                interval=float(data.get("interval", 0.25) or 0.25),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                diagnostic=bool(data.get("diagnostic", False)),
                skip_uia=bool(data.get("skip_uia", False)),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            )
        elif command == "smart_cell":
            result = _call_tools_no_reenter(
                tools_mod.smart_cell,
                hwnd,
                row=data.get("row"),
                column=data.get("column"),
                row_text=data.get("row_text"),
                column_name=data.get("column_name"),
                text=data.get("text"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                match=str(data.get("match", "contains") or "contains"),
                action=str(data.get("action", "get") or "get"),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                diagnostic=bool(data.get("diagnostic", False)),
                skip_uia=bool(data.get("skip_uia", False)),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            )
        elif command == "smart_wait_cell":
            result = _call_tools_no_reenter(
                tools_mod.smart_wait_cell,
                hwnd,
                row=data.get("row"),
                column=data.get("column"),
                row_text=data.get("row_text"),
                column_name=data.get("column_name"),
                text=data.get("text"),
                automation_id=data.get("automation_id"),
                control_type=data.get("control_type"),
                class_name=data.get("class_name"),
                match=str(data.get("match", "contains") or "contains"),
                action=str(data.get("action", "get") or "get"),
                timeout=float(data.get("timeout", 10.0) or 10.0),
                interval=float(data.get("interval", 0.25) or 0.25),
                timeout_ms=int(data.get("timeout_ms", 500) or 500),
                diagnostic=bool(data.get("diagnostic", False)),
                skip_uia=bool(data.get("skip_uia", False)),
                repair=data.get("repair", data.get("selector_repair", data.get("selector-repair"))),
                repair_timeout=data.get("repair_timeout", data.get("repair-timeout", data.get("selector_repair_timeout", data.get("selector-repair-timeout")))),
            )
        else:
            result = {"ok": False, "error": f"Unknown UIA worker command: {command}"}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), flush=True)
        return 1


def main():
    global EXPECTED_TOKEN
    if "--worker-uia" in sys.argv:
        raise SystemExit(_worker_uia_main())

    port = 18765
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    if "--token" in sys.argv:
        idx = sys.argv.index("--token")
        if idx + 1 < len(sys.argv):
            EXPECTED_TOKEN = sys.argv[idx + 1]

    if not EXPECTED_TOKEN:
        EXPECTED_TOKEN = generate_session_token()
        os.environ["WIN_AUTOMATION_HELPER_TOKEN"] = EXPECTED_TOKEN

    token_file = os.path.expanduser("~/.win-auto-helper.token")
    try:
        with open(token_file, "w", encoding="utf-8") as tf:
            tf.write(EXPECTED_TOKEN)
    except Exception:
        pass

    def _cleanup_token():
        try:
            if os.path.exists(token_file):
                with open(token_file, "r", encoding="utf-8") as tf:
                    if tf.read().strip() == EXPECTED_TOKEN:
                        os.remove(token_file)
        except Exception:
            pass
    atexit.register(_cleanup_token)

    server = ThreadingHTTPServer(("127.0.0.1", port), HelperHandler)
    server.daemon_threads = True
    print(f"Helper server running on http://127.0.0.1:{port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
