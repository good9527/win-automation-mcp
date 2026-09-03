"""
Resident helper background daemon client and process supervisor.
Manages HTTP communication with helper instances on port 18765 and elevated 18766.
"""

from __future__ import annotations

import os
import sys
import time
import json
import socket
import logging
import hashlib
import tempfile
import subprocess
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

from win_automation.core.types import HelperError
from win_automation.core.win32_structures import kernel32, user32, PROCESS_QUERY_LIMITED_INFORMATION
from win_automation.helper.security import generate_session_token, verify_request

# ---------------------------------------------------------------------------
HELPER_URL = "http://127.0.0.1:18765"
ELEVATED_HELPER_URL = "http://127.0.0.1:18766"
_helper_process = None
_elevated_helper_process = None
HELPER_PORT = 18765
ELEVATED_HELPER_PORT = 18766
_session_token: Optional[str] = None
_DESKTOP_UIA_KEY = 0


def _control_boundary_safe(hwnd: int) -> Dict[str, Any]:
    try:
        from win_automation.win32.window import control_boundary
        return control_boundary(hwnd)
    except Exception:
        return {}


def get_session_token() -> str:
    """Get active session token, generating one if not already created."""
    global _session_token
    env_token = os.environ.get("WIN_AUTOMATION_HELPER_TOKEN")
    if env_token:
        _session_token = env_token
        return env_token
    if _session_token is None:
        _session_token = generate_session_token()
        os.environ["WIN_AUTOMATION_HELPER_TOKEN"] = _session_token
    return _session_token


def set_session_token(token: str) -> None:
    """Set active session token."""
    global _session_token
    _session_token = token
    os.environ["WIN_AUTOMATION_HELPER_TOKEN"] = token


def _helper_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "helper.py"))


def _tools_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tools.py"))


def _file_sha256(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _expected_helper_signature() -> Dict[str, str]:
    helper_path = _helper_path()
    tools_path = _tools_path()
    return {
        "helper_path": os.path.abspath(helper_path),
        "helper_sha256": _file_sha256(helper_path),
        "tools_path": os.path.abspath(tools_path),
        "tools_sha256": _file_sha256(tools_path),
    }


def _helper_url(elevated: bool = False) -> str:
    return ELEVATED_HELPER_URL if elevated else HELPER_URL


def _helper_port(elevated: bool = False) -> int:
    return ELEVATED_HELPER_PORT if elevated else HELPER_PORT


def _helper_port_pids(elevated: bool = False) -> List[int]:
    """Find PIDs listening on the helper TCP port."""
    try:
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    pids: List[int] = []
    needle = f":{_helper_port(elevated)}"
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[-2].upper() != "LISTENING":
            continue
        local = parts[1]
        if not local.endswith(needle):
            continue
        try:
            pid = int(parts[-1])
        except Exception:
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


def _process_command_line(pid: int) -> str:
    """Read a process command line for targeted helper shutdown verification."""
    if sys.platform != "win32":
        return ""
    query = f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}').CommandLine"
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", query],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _is_helper_process(pid: int) -> bool:
    cmdline = _process_command_line(pid)
    if not cmdline:
        return False
    helper_path = os.path.abspath(_helper_path()).lower()
    normalized = cmdline.replace("/", "\\").replace('"', "").lower()
    return helper_path in normalized or (
        "helper.py" in normalized
        and os.path.dirname(helper_path) in normalized
        and ("python" in normalized or "py.exe" in normalized)
    )


def _force_stop_stale_helper(elevated: bool = False) -> Dict[str, Any]:
    """Force-stop only verified helper.py processes that still own the helper port."""
    stopped: List[int] = []
    skipped: List[Dict[str, Any]] = []
    for pid in _helper_port_pids(elevated=elevated):
        if not _is_helper_process(pid):
            skipped.append({"pid": pid, "reason": "port owner is not verified helper.py"})
            continue
        try:
            proc = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if proc.returncode == 0:
                stopped.append(pid)
            else:
                skipped.append({"pid": pid, "reason": (proc.stderr or proc.stdout or "").strip()})
        except Exception as e:
            skipped.append({"pid": pid, "reason": str(e)})
    return {"ok": bool(stopped), "stopped_pids": stopped, "skipped": skipped}


def _ensure_helper():
    """Auto-start the helper server, restarting stale resident copies after code changes."""
    global _helper_process
    if _helper_current():
        return
    if _helper_available():
        _helper_shutdown(wait=True)
        if _helper_current():
            return
        if _helper_available():
            _force_stop_stale_helper()
            if _helper_current():
                return
            if _helper_available():
                return
    # Start helper in background with security session token
    token = get_session_token()
    helper_path = _helper_path()
    _helper_process = subprocess.Popen(
        [sys.executable, helper_path, "--port", str(HELPER_PORT), "--token", token],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for it to be ready
    for _ in range(20):
        time.sleep(0.2)
        if _helper_current():
            return
    # If still not ready, fall back to direct SendInput


def _helper_health(elevated: bool = False) -> Dict[str, Any]:
    """Return helper health metadata, including source hash when supported."""
    try:
        req = urllib.request.Request(
            f"{_helper_url(elevated)}/health",
            headers={"X-Helper-Token": get_session_token()},
        )
        resp = urllib.request.urlopen(req, timeout=1)
        if resp.status != 200:
            return {"ok": False, "status": resp.status}
        data = json.loads(resp.read().decode("utf-8"))
        data["ok"] = True
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _helper_available(elevated: bool = False) -> bool:
    """Check if the helper server is running."""
    return bool(_helper_health(elevated=elevated).get("ok"))


def _helper_current(elevated: bool = False) -> bool:
    """Return True when a running helper matches the current helper.py source."""
    health = _helper_health(elevated=elevated)
    if not health.get("ok"):
        return False
    expected = _expected_helper_signature()
    running_hash = str(health.get("helper_sha256") or "")
    running_tools_hash = str(health.get("tools_sha256") or "")
    if not running_hash or not running_tools_hash:
        return False
    if running_hash != expected.get("helper_sha256"):
        return False
    if running_tools_hash != expected.get("tools_sha256"):
        return False
    if elevated:
        token = health.get("token") or {}
        return bool(token.get("elevated") or _integrity_rank(str(token.get("integrity_level") or "unknown")) >= _integrity_rank("high"))
    return True


def _prepare_helper() -> bool:
    """Ensure the helper is running current code before sending input requests."""
    _ensure_helper()
    return _helper_current()


def start_elevated_helper(timeout: float = 20.0) -> Dict[str, Any]:
    """Start the helper on the elevated port using UAC runas and wait for health."""
    global _elevated_helper_process
    before = _helper_health(elevated=True)
    if _helper_current(elevated=True):
        return {"ok": True, "already_running": True, "health": before}
    if before.get("ok"):
        _helper_shutdown(wait=True, elevated=True)
        if _helper_available(elevated=True):
            _force_stop_stale_helper(elevated=True)
    token = get_session_token()
    helper_path = _helper_path()
    params = f'"{helper_path}" --port {ELEVATED_HELPER_PORT} --token {token}'
    try:
        result = int(shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            params,
            os.path.dirname(helper_path),
            SW_SHOWNORMAL,
        ))
    except Exception as e:
        return {"ok": False, "error": str(e), "method": "ShellExecuteW runas"}
    launched = result > 32
    deadline = time.time() + max(float(timeout), 0.0)
    health: Dict[str, Any] = {}
    while time.time() < deadline:
        time.sleep(0.25)
        health = _helper_health(elevated=True)
        if _helper_current(elevated=True):
            return {
                "ok": True,
                "launched": launched,
                "shell_execute_result": result,
                "health": health,
                "port_pids": _helper_port_pids(elevated=True),
            }
    return {
        "ok": False,
        "launched": launched,
        "shell_execute_result": result,
        "error": "elevated helper did not become ready before timeout; UAC may have been cancelled",
        "health": health,
    }


def _target_needs_elevated_helper(hwnd: Optional[int]) -> bool:
    if not hwnd:
        return False
    boundary = _control_boundary_safe(int(hwnd))
    return bool(boundary.get("uipi_risk") or boundary.get("needs_elevation"))


def _select_helper_for_hwnd(hwnd: Optional[int]) -> bool:
    """Return True when the elevated helper should be used for this target."""
    if not _target_needs_elevated_helper(hwnd):
        return False
    return _helper_current(elevated=True)


def _hwnd_belongs_to_current_process(hwnd: Optional[int]) -> bool:
    if not hwnd:
        return False
    try:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(int(hwnd)), ctypes.byref(pid))
        return bool(int(pid.value or 0) == int(kernel32.GetCurrentProcessId()))
    except Exception:
        return False


def _prepare_helper_for_hwnd(hwnd: Optional[int]) -> Tuple[bool, bool]:
    """Return (available, elevated) for the best helper available for a target."""
    if os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER") == "1":
        return False, False
    if _hwnd_belongs_to_current_process(hwnd):
        return False, False
    use_elevated = _select_helper_for_hwnd(hwnd)
    if use_elevated:
        return True, True
    _ensure_helper()
    return _helper_current(), False


def _hwnd_from_screen_point(x: int, y: int) -> int:
    try:
        point = ctypes.wintypes.POINT(int(x), int(y))
        direct = int(user32.WindowFromPoint(point) or 0)
        if not direct:
            return 0
        return int(user32.GetAncestor(direct, GA_ROOT) or direct or 0)
    except Exception:
        return 0


def _prepare_helper_for_screen_point(x: int, y: int) -> Tuple[bool, bool, int]:
    hwnd = _hwnd_from_screen_point(x, y)
    helper_ready, helper_elevated = _prepare_helper_for_hwnd(hwnd or None)
    return helper_ready, helper_elevated, hwnd


def _prepare_helper_for_uia(hwnd: Optional[int]) -> Tuple[bool, bool]:
    """Return helper routing for UIA work without deadlocking same-process probes."""
    if os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER") == "1":
        return False, False
    try:
        hwnd_int = int(hwnd or 0)
    except Exception:
        hwnd_int = 0
    if hwnd_int == _DESKTOP_UIA_KEY:
        _ensure_helper()
        return _helper_current(), False
    if hwnd_int:
        try:
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd_int), ctypes.byref(pid))
            if int(pid.value or 0) == int(kernel32.GetCurrentProcessId()):
                return False, False
        except Exception:
            pass
    return _prepare_helper_for_hwnd(hwnd_int or None)


def _elevated_helper_required_result(hwnd: Optional[int], path: str = "") -> Optional[Dict[str, Any]]:
    if not hwnd or int(hwnd or 0) == _DESKTOP_UIA_KEY:
        return None
    boundary = _control_boundary_safe(int(hwnd))
    if not bool(boundary.get("uipi_risk") or boundary.get("needs_elevation")):
        return None
    if _helper_current(elevated=True):
        return None
    compact_boundary = {
        key: boundary.get(key)
        for key in (
            "ok",
            "hwnd",
            "current_integrity",
            "target_integrity",
            "uipi_risk",
            "needs_elevation",
            "secure_desktop_risk",
            "can_send_input_likely",
            "win32_messages_likely",
            "uia_access_likely",
            "reasons",
        )
        if boundary.get(key) not in (None, "", [], {})
    }
    return {
        "ok": False,
        "error": "elevated_helper_required",
        "message": "Target is across a Windows integrity/UIPI boundary; start the elevated helper before helper-backed UIA/input actions.",
        "hwnd": int(hwnd),
        "path": path or None,
        "helper": True,
        "helper_elevated": False,
        "elevated_helper_available": False,
        "failure_category": "blocked_or_elevation",
        "boundary": compact_boundary,
        "recommendations": [
            "Run control-boundary for the target HWND, then helper-status --elevated --start only when needs_elevation/uipi_risk is reported.",
            "For generated app_action/window_sequence plans, enable pre-boundary/pre-helper or auto-recover so elevation recovery can run before retry.",
        ],
    }


def _elevated_helper_required_message(result: Dict[str, Any]) -> str:
    hwnd = result.get("hwnd")
    path = result.get("path") or "helper action"
    return (
        f"Error: elevated_helper_required: {path} for HWND {hwnd} crosses a Windows integrity/UIPI elevation boundary; "
        "run control-boundary first, then helper-status --elevated --start only when needs_elevation/uipi_risk is reported"
    )


def _helper_route_for_hwnd(hwnd: Optional[int], path: str = "") -> Tuple[bool, bool, Optional[Dict[str, Any]]]:
    boundary_result = _elevated_helper_required_result(hwnd, path)
    if boundary_result is not None:
        return False, False, boundary_result
    helper_ready, helper_elevated = _prepare_helper_for_hwnd(hwnd)
    return helper_ready, helper_elevated, None


def _helper_route_for_screen_point(x: int, y: int, path: str = "") -> Tuple[bool, bool, int, Optional[Dict[str, Any]]]:
    hwnd = _hwnd_from_screen_point(x, y)
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd or None, path)
    return helper_ready, helper_elevated, hwnd, boundary_result


def _is_terminal_uia_helper_error(result: Dict[str, Any]) -> bool:
    error = str(result.get("error") or "")
    return error in {
        "uia_worker_timeout",
        "uia_worker_failed",
        "uia_worker_empty_response",
    } or error.startswith("uia_worker_invalid_json")


def _append_unique_compact_dict(target: List[Dict[str, Any]], value: Any, keys: Tuple[str, ...], limit: int = 8) -> None:
    if not isinstance(value, dict) or len(target) >= limit:
        return
    compact = {
        key: value.get(key)
        for key in keys
        if value.get(key) not in (None, "", [], {})
    }
    if compact and compact not in target:
        target.append(compact)


def _merge_named_counts(target: Dict[str, int], values: Any) -> None:
    if isinstance(values, dict):
        for key, count in values.items():
            if key in (None, ""):
                continue
            try:
                target[str(key)] = target.get(str(key), 0) + int(count or 0)
            except Exception:
                target[str(key)] = target.get(str(key), 0) + 1
        return
    if not isinstance(values, list):
        return
    for item in values:
        if not isinstance(item, dict):
            continue
        key = item.get("value")
        if key in (None, ""):
            continue
        try:
            target[str(key)] = target.get(str(key), 0) + int(item.get("count") or 0)
        except Exception:
            target[str(key)] = target.get(str(key), 0) + 1


def _top_named_counts(values: Dict[str, int], limit: int = 8) -> List[Dict[str, Any]]:
    ranked = sorted((values or {}).items(), key=lambda item: (-item[1], item[0]))
    return [{"value": key, "count": count} for key, count in ranked[:limit]]


def _compact_attempt_failure_summary(attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(attempts, list):
        attempts = []
    summary: Dict[str, Any] = {
        "attempt_count": len(attempts or []),
        "uia_find_count": 0,
        "uia_action_count": 0,
        "uia_prepare_count": 0,
        "uia_prepare_failed_count": 0,
        "uia_relocation_count": 0,
        "last_uia_relocation": None,
        "win32_action_count": 0,
        "focus_action_count": 0,
        "coordinate_fallback_attempted": False,
        "terminal_uia_error": None,
        "last_uia_error": None,
        "last_win32_error": None,
        "last_focus_error": None,
        "last_error": None,
        "failed_methods": [],
    }
    failed_methods: List[str] = []
    uia_selector_suggestions: List[Dict[str, Any]] = []
    uia_recommendations: List[str] = []
    uia_miss_counts: Dict[str, int] = {}
    uia_observed_control_types: Dict[str, int] = {}
    uia_observed_classes: Dict[str, int] = {}
    for item in attempts or []:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "")
        result = item.get("result")
        if method.startswith("uia.find"):
            summary["uia_find_count"] += 1
        if method.startswith("uia.action") or method.startswith("uia.set_value") or method.startswith("uia.legacy_set_value"):
            summary["uia_action_count"] += 1
        if method.startswith("uia.action") and (method.endswith(".realize") or method.endswith(".scrollitem")):
            summary["uia_prepare_count"] += 1
        if method.startswith("win32."):
            summary["win32_action_count"] += 1
        if method.startswith("focused_input") or "focused_input" in method:
            summary["focus_action_count"] += 1
        if "coordinate_fallback" in method:
            summary["coordinate_fallback_attempted"] = True
        if isinstance(result, dict):
            ok = result.get("ok")
            error = result.get("error")
            relocation = result.get("relocation")
            find_count = result.get("count")
            if method.startswith("uia.find") and error is None:
                try:
                    if int(find_count or 0) <= 0 and method not in failed_methods:
                        failed_methods.append(method)
                except Exception:
                    pass
            if method.startswith("uia.") and (result.get("relocated") is True or isinstance(relocation, dict)):
                summary["uia_relocation_count"] += 1
                if isinstance(relocation, dict):
                    summary["last_uia_relocation"] = dict(relocation)
            if ok is False and method not in failed_methods:
                failed_methods.append(method)
            if method.startswith("uia.action") and (method.endswith(".realize") or method.endswith(".scrollitem")) and ok is False:
                summary["uia_prepare_failed_count"] += 1
            if error:
                error_text = str(error)
                summary["last_error"] = error_text
                if method.startswith("uia."):
                    summary["last_uia_error"] = error_text
                    if _is_terminal_uia_helper_error(result):
                        summary["terminal_uia_error"] = error_text
                elif method.startswith("win32."):
                    summary["last_win32_error"] = error_text
                elif method.startswith("focused_input") or "focused_input" in method:
                    summary["last_focus_error"] = error_text
            nested_failure = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
            if method.startswith("uia.find") and nested_failure:
                _merge_named_counts(uia_miss_counts, nested_failure.get("miss_counts"))
                _merge_named_counts(uia_observed_control_types, nested_failure.get("observed_control_types"))
                _merge_named_counts(uia_observed_classes, nested_failure.get("observed_classes"))
                for suggestion in nested_failure.get("selector_suggestions") or []:
                    _append_unique_compact_dict(
                        uia_selector_suggestions,
                        suggestion,
                        ("index", "automation_id", "control_type", "class_name", "name", "value", "pattern", "match"),
                        limit=8,
                    )
                for recommendation in nested_failure.get("recommendations") or []:
                    if recommendation and recommendation not in uia_recommendations:
                        uia_recommendations.append(str(recommendation))
    summary["failed_methods"] = failed_methods[:8]
    if uia_miss_counts:
        summary["miss_counts"] = dict(sorted(uia_miss_counts.items()))
    if uia_observed_control_types:
        summary["observed_control_types"] = _top_named_counts(uia_observed_control_types)
    if uia_observed_classes:
        summary["observed_classes"] = _top_named_counts(uia_observed_classes)
    if uia_selector_suggestions:
        summary["selector_suggestions"] = uia_selector_suggestions[:5]
        summary["uia_selector_repair_available"] = True
        summary["uia_selector_suggestion_count"] = len(uia_selector_suggestions)
        repair_candidates = [
            {
                "kind": "uia_selector_repair",
                "layer": "semantic",
                "command": "uia_selector_repair_find",
                "source": "smart_action.failure_summary",
                "suggestion": suggestion,
                "reason": "retry UIA lookup with failure_summary.selector_suggestions[0]",
            }
            for suggestion in uia_selector_suggestions[:3]
        ]
        summary["next_repair_candidates"] = repair_candidates
        repair_steps = _batch_repair_candidate_steps(repair_candidates, limit=3)
        if repair_steps:
            summary["next_repair_steps"] = repair_steps
    if summary.get("last_error"):
        category = _batch_failure_category(summary.get("last_error"), command=(failed_methods[-1] if failed_methods else None))
        summary["last_failure_category"] = category
        summary["recommendations"] = _batch_failure_recommendations(category)
    elif uia_selector_suggestions:
        summary["last_failure_category"] = "selector"
        summary["recommendations"] = _batch_failure_recommendations("selector")
    if uia_recommendations:
        merged = list(summary.get("recommendations") or [])
        for recommendation in uia_recommendations:
            if recommendation not in merged:
                merged.append(recommendation)
        summary["recommendations"] = merged
    return summary


def _batch_failure_category(error: Any, command: Optional[str] = None, result: Optional[Dict[str, Any]] = None) -> str:
    error_text = str(error or "").strip().lower().replace("-", "_")
    command_text = str(command or "").strip().lower().replace("-", "_")
    result = result if isinstance(result, dict) else {}
    failure_summary = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
    summary_category = failure_summary.get("last_failure_category")
    if summary_category:
        return str(summary_category)
    haystack = " ".join(
        str(value or "").strip().lower().replace("-", "_")
        for value in (
            error_text,
            command_text,
            result.get("message"),
            result.get("reason"),
            result.get("method"),
            result.get("last_error"),
            failure_summary.get("last_error"),
        )
    )
    if result.get("clipboard_restore_ok") is False or "clipboard_restore" in haystack or "clipboard restore may be incomplete" in haystack:
        return "clipboard_restore"
    if not haystack:
        return "unknown"
    if "timeout" in haystack or result.get("timeout_budget_exceeded"):
        return "timeout"
    if "uipi" in haystack or "elevat" in haystack or "access_denied" in haystack or "permission" in haystack or "integrity" in haystack:
        return "blocked_or_elevation"
    if "focus" in haystack or "foreground" in haystack or "active" in haystack or "caret" in haystack:
        return "focus"
    if "uia_worker" in haystack or "uia" in haystack or "provider" in haystack or "pattern" in haystack or "automation" in haystack:
        return "semantic_provider"
    if "win32" in haystack or "sendmessage" in haystack or "wm_" in haystack or "hwnd" in haystack:
        return "native_control"
    if "msaa" in haystack or "iaccessible" in haystack or "legacy" in haystack:
        return "msaa"
    if "ocr" in haystack or "image" in haystack or "template" in haystack or "screenshot" in haystack or "visual" in haystack:
        return "visual"
    if "not_found" in haystack or "not found" in haystack or "missing" in haystack or "no_match" in haystack or "match" in haystack:
        return "selector"
    if "coordinate" in haystack or "click" in haystack or "sendinput" in haystack or "keyboard" in haystack or "mouse" in haystack or "input" in haystack:
        return "input"
    if "invalid" in haystack or "required" in haystack or "malformed" in haystack or "unknown" in haystack or "unsupported" in haystack:
        return "configuration"
    if "expectation" in haystack or "assert" in haystack:
        return "expectation"
    return "unknown"


def _batch_failure_recommendations(category: str) -> List[str]:
    recommendations = {
        "clipboard_restore": ["treat paste as incomplete, inspect clipboard_restore diagnostics, and retry with focused_input or semantic/native text input before clipboard paste"],
        "timeout": ["increase timeout_budget or add a wait_event/smart_wait step before the action"],
        "blocked_or_elevation": ["run control_boundary, then start helper_status(elevated=true,start=true) when needs_elevation is reported"],
        "focus": ["insert focus_hwnd before input, or enable sequence-focus/refocus-on-recovery for workflows"],
        "semantic_provider": ["retry with --no-uia/skip_uia or add native, MSAA, visual, and input fallback layers"],
        "native_control": ["fall back to smart UIA, MSAA, or focused_input when Win32 messages are blocked or unsupported"],
        "msaa": ["fall back to UIA/Win32 first, then OCR/image when the MSAA tree is incomplete"],
        "visual": ["refresh screenshot/capture_mode, constrain region, or add a semantic selector before visual fallback"],
        "input": ["prefer semantic/native selectors; use coordinates only with a fresh screenshot_id and verified focus"],
        "selector": ["tighten name/automation_id/control_type/class_name, or observe/find again after the UI changes"],
        "configuration": ["check command aliases, required args, and generated plan_summary before executing"],
        "expectation": ["loosen or correct expect/assert paths, or extract the value before asserting it"],
        "unknown": ["enable trace and keep layered fallbacks so the next failed method is visible"],
    }
    return list(recommendations.get(category, recommendations["unknown"]))


def _batch_clipboard_restore_incomplete(result: Any) -> bool:
    if _batch_clipboard_restore_payload(result):
        return True
    if isinstance(result, dict):
        value = result.get("value")
        if _batch_clipboard_restore_payload(value):
            return True
    text = str(result or "").strip().lower()
    return "clipboard restore may be incomplete" in text or "clipboard_restore_ok=false" in text


def _batch_clipboard_restore_payload(result: Any) -> Optional[Dict[str, Any]]:
    if isinstance(result, dict) and result.get("clipboard_restore_ok") is False:
        return result
    return None


def _batch_clipboard_restore_error_text(result: Any) -> str:
    if isinstance(result, dict):
        payload = _batch_clipboard_restore_payload(result)
        if payload is None and isinstance(result.get("value"), dict):
            payload = _batch_clipboard_restore_payload(result.get("value"))
        if payload is not None and payload is not result:
            return _batch_clipboard_restore_error_text(payload)
        error = (
            result.get("clipboard_restore_error")
            or result.get("clipboard_restore_failures")
            or result.get("clipboard_restore_skipped_formats")
            or result.get("error")
            or result.get("message")
            or "clipboard_restore_incomplete"
        )
        restored = result.get("clipboard_restored_formats", result.get("restored_formats"))
        return f"clipboard_restore_incomplete(restored_formats={restored}, error={error})"
    text = str(result or "").strip()
    if ":" in text and text.lower().startswith(("warning", "error")):
        return text.split(":", 1)[1].strip() or text
    return text or "clipboard_restore_incomplete"


def _batch_failure_details(error: Any, command: Optional[str] = None, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    category = _batch_failure_category(error, command=command, result=result)
    return {
        "failure_category": category,
        "recommendations": _batch_failure_recommendations(category),
    }


def _mark_uia_helper_error(result: Dict[str, Any], helper_elevated: bool) -> Dict[str, Any]:
    result["helper"] = True
    result["helper_elevated"] = bool(helper_elevated)
    return result


def _helper_timeout_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return max(float(value), 0.0)
    except Exception:
        return default


def _helper_truthy(value: Any, default: bool = False) -> bool:
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


def _helper_payload_repair_budget(payload: Dict[str, Any], base_timeout: Optional[float] = None) -> float:
    if not isinstance(payload, dict):
        return 0.0
    raw_repair_timeout = payload.get("repair_timeout", payload.get("repair-timeout", payload.get("selector_repair_timeout", payload.get("selector-repair-timeout"))))
    raw_repair = payload.get("repair", payload.get("selector_repair", payload.get("selector-repair")))
    repair_requested = _helper_truthy(raw_repair, False) if raw_repair is not None else raw_repair_timeout is not None
    if not repair_requested:
        return 0.0
    if raw_repair_timeout is not None:
        return _helper_timeout_float(raw_repair_timeout, 0.0) or 0.0
    if base_timeout is not None:
        return min(max(float(base_timeout), 0.0), 1.0)
    return 1.0


def _uia_helper_timeout(timeout: Optional[float] = None) -> float:
    timeout_value = _helper_timeout_float(timeout, None)
    if timeout_value is not None:
        return max(timeout_value + 1.0, 4.0)
    return 4.0


def _smart_action_helper_timeout(payload: Dict[str, Any], timeout: Optional[float] = None) -> float:
    data = payload if isinstance(payload, dict) else {}
    payload_timeout = _helper_timeout_float(data.get("timeout"), None)
    override_timeout = _helper_timeout_float(timeout, None)
    timeout_candidates = [value for value in (payload_timeout, override_timeout) if value is not None]
    repair_budget = _helper_payload_repair_budget(data, payload_timeout if payload_timeout is not None else override_timeout)
    if not timeout_candidates:
        if repair_budget:
            return max(4.0 + repair_budget + 1.0, 4.0)
        return 4.0
    base_timeout = max(timeout_candidates)
    included_repair = 0.0
    if payload_timeout is not None and override_timeout is not None:
        included_repair = max(override_timeout - payload_timeout, 0.0)
    extra_repair = max(repair_budget - included_repair, 0.0)
    return max(base_timeout + extra_repair + 1.0, 4.0)


def _smart_action_helper_post(
    hwnd: int,
    path: str,
    payload: Dict[str, Any],
    *,
    timeout: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Run a high-level smart action inside the helper worker when available.

    This keeps UIA provider-returned virtualized elements alive between the
    find and action phases, instead of splitting them across worker processes.
    """
    if os.environ.get("WIN_AUTOMATION_HELPER_NO_REENTER") == "1":
        return None
    target_hwnd = hwnd if int(hwnd) != _DESKTOP_UIA_KEY else None
    boundary_result = _elevated_helper_required_result(target_hwnd, path)
    if boundary_result is not None:
        boundary_result["smart_action_worker"] = True
        return boundary_result
    helper_ready, helper_elevated = _prepare_helper_for_hwnd(target_hwnd)
    if not helper_ready:
        return None
    data = dict(payload)
    data["hwnd"] = int(hwnd)
    helper_timeout = _smart_action_helper_timeout(data, timeout=timeout)
    data.setdefault("uia_timeout", helper_timeout)
    result = _helper_post(path, data, elevated=helper_elevated, timeout=helper_timeout + 1.0)
    if "error" not in result:
        result["helper"] = True
        result["helper_elevated"] = bool(helper_elevated)
        result["smart_action_worker"] = True
        return result
    if _is_terminal_uia_helper_error(result):
        marked = _mark_uia_helper_error(result, helper_elevated)
        marked["smart_action_worker"] = True
        return marked
    return None


def _helper_shutdown(wait: bool = True, timeout: float = 2.0, elevated: bool = False) -> Dict[str, Any]:
    """Ask the resident helper to stop so the next input command reloads current code."""
    result = _helper_post("/shutdown", {}, elevated=elevated)
    if wait:
        deadline = time.time() + max(float(timeout), 0.1)
        while time.time() < deadline:
            time.sleep(0.05)
            if not _helper_available(elevated=elevated):
                result["stopped"] = True
                return result
        result["stopped"] = not _helper_available(elevated=elevated)
    return result


def helper_status(restart: bool = False, elevated: bool = False, start: bool = False) -> Dict[str, Any]:
    """Inspect helper lifecycle state; optionally restart it onto current code."""
    before = _helper_health(elevated=elevated)
    expected = _expected_helper_signature()
    result: Dict[str, Any] = {
        "ok": True,
        "elevated_helper": bool(elevated),
        "url": _helper_url(elevated),
        "port": _helper_port(elevated),
        "available": bool(before.get("ok")),
        "current": _helper_current(elevated=elevated),
        "expected": expected,
        "health": before,
    }
    if before.get("ok"):
        result["port_pids"] = _helper_port_pids(elevated=elevated)
    if elevated and start and not restart:
        result["start"] = start_elevated_helper()
        after = _helper_health(elevated=True)
        result.update({
            "available": bool(after.get("ok")),
            "current": _helper_current(elevated=True),
            "after": after,
            "port_pids": _helper_port_pids(elevated=True) if after.get("ok") else [],
        })
    if restart:
        if before.get("ok"):
            shutdown = _helper_shutdown(wait=True, elevated=elevated)
            if _helper_available(elevated=elevated):
                forced = _force_stop_stale_helper(elevated=elevated)
            else:
                forced = {"ok": False, "stopped_pids": [], "skipped": []}
        else:
            shutdown = {"ok": True, "stopped": True, "reason": "helper was not running"}
            forced = {"ok": False, "stopped_pids": [], "skipped": []}
        if elevated:
            start_result = start_elevated_helper()
        else:
            _ensure_helper()
            start_result = {"ok": _helper_current(), "method": "auto-start"}
        after = _helper_health(elevated=elevated)
        result.update({
            "restarted": bool(after.get("ok") and _helper_current(elevated=elevated)),
            "shutdown": shutdown,
            "forced_shutdown": forced,
            "start": start_result,
            "after": after,
            "available": bool(after.get("ok")),
            "current": _helper_current(elevated=elevated),
        })
    return result


def _helper_post(path: str, data: dict, elevated: bool = False, timeout: float = 5.0) -> dict:
    """Send POST request to helper server."""
    try:
        req = urllib.request.Request(
            f"{_helper_url(elevated)}{path}",
            data=json.dumps(data).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Helper-Token": get_session_token(),
            },
        )
        resp = urllib.request.urlopen(req, timeout=max(float(timeout), 0.1))
        decoded = json.loads(resp.read().decode("utf-8"))
        if not isinstance(decoded, dict):
            return {"error": "helper_invalid_response", "response_type": type(decoded).__name__}
        return decoded
    except Exception as e:
        return {"error": str(e)}


def _helper_ok(result: Dict[str, Any]) -> bool:
    return isinstance(result, dict) and result.get("ok") is True


def _helper_get(path: str, elevated: bool = False) -> dict:
    """Send GET request to helper server."""
    try:
        req = urllib.request.Request(
            f"{_helper_url(elevated)}{path}",
            headers={"X-Helper-Token": get_session_token()},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        decoded = json.loads(resp.read().decode("utf-8"))
        if not isinstance(decoded, dict):
            return {"error": "helper_invalid_response", "response_type": type(decoded).__name__}
        return decoded
    except Exception as e:
        return {"error": str(e)}

# ---------------------------------------------------------------------------
# DPI awareness — must be set before any window queries
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor aware v2
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# PIL is required for screenshot bitmap conversion
from PIL import Image as PILImage

# ---------------------------------------------------------------------------


ensure_helper = _ensure_helper
