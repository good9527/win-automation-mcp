"""
Batch execution engine coordinating compound multi-step automation plans with step timeouts and repair.
"""

from __future__ import annotations

import os
import sys
import time
import json
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.win32 import *
from win_automation.uia import *
from win_automation.input import *
from win_automation.vision import *
from win_automation.ocr import *
from win_automation.safety import check_safety
from win_automation.state.persistence import resolve_target_hwnd, load_state, save_state
from win_automation.helper.client import (
    _helper_route_for_hwnd,
    _helper_post,
    _helper_available,
    _helper_current,
    _elevated_helper_required_result,
    _prepare_helper_for_uia,
)
from win_automation.batch.evaluator import *

def execute_batch_file(filepath: str, stop_on_error: bool = True, timeout: float = 30.0, trace: bool = False) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    commands = data if isinstance(data, list) else data.get("commands", [])
    return execute_batch(commands, stop_on_error=stop_on_error, timeout_budget=timeout)

def _batch_safety_findings(commands: Any) -> List[Dict[str, Any]]:
    """Find confirmation-required actions in a batch plan without executing it."""
    findings: List[Dict[str, Any]] = []
    finding_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    visited: set[int] = set()

    def scan(value: Any, source: str, step_id: Optional[str] = None) -> None:
        if value is None or isinstance(value, (dict, list, tuple, set)):
            return
        text = str(value).strip()
        if not text:
            return
        result = check_safety(text)
        if not result.get("needs_confirmation"):
            return
        category = str(result.get("category") or "Safety").strip()
        action = str(result.get("action") or text).strip()
        key = (category.lower(), action.lower().replace(" ", "_").replace("-", "_"))
        finding = finding_by_key.get(key)
        if finding is None:
            finding = {
                "category": category,
                "description": result.get("description"),
                "action": action,
                "source": source,
                "step_ids": [],
            }
            finding_by_key[key] = finding
            findings.append(finding)
        if step_id and step_id not in finding["step_ids"]:
            finding["step_ids"].append(step_id)
        sources = finding.setdefault("sources", [])
        if source not in sources and len(sources) < 8:
            sources.append(source)

    def visit(value: Any, path: str = "$", depth: int = 0) -> None:
        if depth > 16 or len(findings) >= 16:
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]", depth + 1)
            return
        if not isinstance(value, dict):
            return
        identity = id(value)
        if identity in visited:
            return
        visited.add(identity)

        try:
            command_name, command_path, args = _batch_command_parts(value)
        except Exception:
            command_name, command_path, args = "", "", {}
        step_id = _batch_step_id(value)
        for label, item in (
            ("command", command_name),
            ("path", command_path),
            ("id", step_id),
            ("description", value.get("description")),
            ("reason", value.get("reason")),
        ):
            if item is not None:
                scan(item, f"{path}.{label}", step_id)

        for container_label, container in (("item", value), ("args", args)):
            if not isinstance(container, dict):
                continue
            for key in _BATCH_SAFETY_VALUE_KEYS:
                if key in container:
                    scan(container.get(key), f"{path}.{container_label}.{key}", step_id)
            for key in _BATCH_RECURSIVE_PLAN_KEYS + _BATCH_NESTED_STEP_SPEC_KEYS:
                if key in container:
                    visit(container.get(key), f"{path}.{container_label}.{key}", depth + 1)

        for key in _BATCH_RECURSIVE_PLAN_KEYS + _BATCH_NESTED_STEP_SPEC_KEYS:
            if key in value:
                visit(value.get(key), f"{path}.{key}", depth + 1)

    visit(commands)
    for finding in findings:
        if not finding.get("step_ids"):
            finding.pop("step_ids", None)
        if not finding.get("sources"):
            finding.pop("sources", None)
    return findings


def _batch_execute_local(command_name: str, args: dict) -> dict:
    """Execute a single batch command locally."""
    try:
        if command_name in ("batch_value", "batch-value", "batch_probe", "batch-probe"):
            return {"ok": True, "value": args.get("value"), "args": args}
        elif command_name in ("batch_retry_probe", "batch-retry-probe"):
            key = str(args.get("key") or "default")
            store = globals().setdefault("_BATCH_RETRY_PROBE_STATE", {})
            if not isinstance(store, dict):
                store = {}
                globals()["_BATCH_RETRY_PROBE_STATE"] = store
            if _coerce_bool(args.get("reset"), False):
                store[key] = 0
            count = int(store.get(key, 0) or 0) + 1
            store[key] = count
            pass_after = int(args.get("pass_after", args.get("pass-after", 2)) or 2)
            if count >= pass_after:
                return {"ok": True, "key": key, "count": count, "passed_after": pass_after}
            result = {
                "ok": False,
                "error": "retry_probe_not_ready",
                "key": key,
                "count": count,
                "pass_after": pass_after,
            }
            diagnostic = args.get("diagnostic_summary") if isinstance(args.get("diagnostic_summary"), dict) else {}
            if diagnostic:
                result["diagnostic_summary"] = diagnostic
            return result
        elif command_name in ("batch_rebinding_probe", "batch-rebinding-probe"):
            kind = str(args.get("kind") or "uia").strip().lower().replace("-", "_")
            source = str(args.get("source") or "batch_rebinding_probe")
            if kind in ("all", "bundle", "multi"):
                probes = [
                    ("repair_rebind_uia", {"kind": "uia", "hwnd": 24681, "index": 7, "view": "raw"}),
                    ("repair_rebind_native", {"kind": "native", "hwnd": 24682, "child_hwnd": 5432}),
                    ("repair_rebind_window", {"kind": "window", "hwnd": 7001}),
                    ("repair_rebind_native_wait", {"kind": "native_wait", "hwnd": 24683, "text": "Delta"}),
                ]
                return {
                    "ok": True,
                    "source": source,
                    "results": [
                        {
                            "id": probe_id,
                            "command": "batch_rebinding_probe",
                            "result": _batch_execute_local("batch_rebinding_probe", probe_args),
                        }
                        for probe_id, probe_args in probes
                    ],
                }
            if kind in ("window", "window_selector", "window_selector_repair"):
                hwnd = int(args.get("hwnd", args.get("target_hwnd", 7001)) or 7001)
                return {
                    "ok": True,
                    "selector_repair": True,
                    "window_selector_repair": True,
                    "source": source,
                    "hwnd": hwnd,
                    "target_hwnd": hwnd,
                    "window": {
                        "hwnd": hwnd,
                        "title": args.get("title", "Demo Player - Home"),
                        "pid": int(args.get("pid", 8100) or 8100),
                        "process_name": args.get("process", "demo-player.exe"),
                        "visible": True,
                    },
                    "selector": {"title": args.get("title", "Demo Player"), "process": args.get("process", "demo-player.exe"), "match": "contains"},
                    "suggestion": {"hwnd": hwnd, "title": args.get("title", "Demo Player - Home"), "process": args.get("process", "demo-player.exe")},
                }
            if kind in ("native", "win32", "native_selector", "win32_selector"):
                parent_hwnd = int(args.get("hwnd", 24682) or 24682)
                child_hwnd = int(args.get("child_hwnd", args.get("child-hwnd", 5432)) or 5432)
                return {
                    "ok": True,
                    "selector_repair": True,
                    "native_selector_repair": True,
                    "source": source,
                    "hwnd": parent_hwnd,
                    "selector": {"automation_id": "101", "control_type": "edit", "class_name": "Edit", "name": "Search", "match": "contains"},
                    "suggestion": {"hwnd": child_hwnd, "automation_id": "101", "control_type": "edit", "class_name": "Edit", "name": "Search"},
                    "count": 1,
                    "matches": [
                        {
                            "hwnd": child_hwnd,
                            "control_id": 101,
                            "kind": "edit",
                            "class_name": "Edit",
                            "name": "Search",
                            "selector_score": 96,
                        }
                    ],
                }
            if kind in ("native_wait", "win32_wait"):
                hwnd = int(args.get("hwnd", 24683) or 24683)
                return {
                    "ok": True,
                    "matched": True,
                    "repaired": True,
                    "source": source,
                    "hwnd": hwnd,
                    "state": args.get("state", "present"),
                    "expected": args.get("expected", True),
                    "text": args.get("text", "Delta"),
                    "match": args.get("match", "contains"),
                    "repair": {
                        "attempted": True,
                        "ok": True,
                        "original_match": "exact",
                        "match": args.get("match", "contains"),
                    },
                }
            hwnd = int(args.get("hwnd", 24681) or 24681)
            index = int(args.get("index", 7) or 7)
            return {
                "ok": True,
                "selector_repair": True,
                "cell_selector_repair": kind in ("uia_cell", "cell"),
                "source": source,
                "hwnd": hwnd,
                "view": args.get("view", "raw"),
                "selector": {"automation_id": "saveButton", "control_type": "button", "class_name": "Button", "name": "Save", "match": "contains"},
                "suggestion": {"index": index, "automation_id": "saveButton", "control_type": "button", "class_name": "Button", "name": "Save", "pattern": "Invoke"},
                "cell": {"row": 1, "column": 2} if kind in ("uia_cell", "cell") else None,
                "count": 1,
                "matches": [
                    {
                        "index": index,
                        "automation_id": "saveButton",
                        "control_type": "button",
                        "class_name": "Button",
                        "name": "Save",
                        "patterns": ["Invoke"],
                        "selector_score": 100,
                    }
                ],
            }
        elif command_name in ("batch_rebind_target_probe", "batch-rebind-target-probe"):
            kind = str(args.get("kind") or "uia").strip().lower().replace("-", "_")
            ok = False
            expected: Dict[str, Any] = {}
            if kind in ("window", "window_selector", "window_selector_repair"):
                expected = {"hwnd": 7001}
                ok = int(args.get("hwnd") or 0) == 7001
            elif kind in ("native", "win32", "native_selector", "win32_selector"):
                expected = {"hwnd": 5432}
                ok = int(args.get("hwnd") or 0) == 5432
            elif kind in ("native_wait", "win32_wait"):
                expected = {"hwnd": 24683, "state": "present", "text": "Delta", "match": "contains"}
                ok = (
                    int(args.get("hwnd") or 0) == 24683
                    and str(args.get("state") or "present") == "present"
                    and str(args.get("text") or "") == "Delta"
                    and str(args.get("match") or "") == "contains"
                )
            else:
                expected = {"hwnd": 24681, "index": 7, "view": "raw"}
                ok = (
                    int(args.get("hwnd") or 0) == 24681
                    and int(args.get("index") or 0) == 7
                    and str(args.get("view") or "") == "raw"
                )
            if ok:
                return {"ok": True, "kind": kind, "rebound": True, "args": args}
            result = {
                "ok": False,
                "error": "rebind_target_not_ready",
                "kind": kind,
                "expected": expected,
                "actual": {
                    key: args.get(key)
                    for key in ("hwnd", "index", "view", "state", "text", "match")
                    if args.get(key) not in (None, "", [], {})
                },
            }
            diagnostic = args.get("diagnostic_summary") if isinstance(args.get("diagnostic_summary"), dict) else {}
            if diagnostic:
                result["diagnostic_summary"] = diagnostic
            return result
        elif command_name in ("batch_repair_plan", "batch-repair-plan", "repair_plan", "repair-plan", "diagnostic_repair_plan", "diagnostic-repair-plan"):
            return _batch_repair_plan(args)
        elif command_name in ("batch_sleep", "batch-sleep", "sleep", "delay", "wait_delay", "wait-delay"):
            delay = args.get("delay", args.get("seconds", args.get("duration", args.get("timeout", 0.0))))
            try:
                delay_value = max(float(delay or 0.0), 0.0)
            except Exception:
                return {"ok": False, "error": "invalid_delay", "delay": delay}
            time.sleep(delay_value)
            return {"ok": True, "slept": delay_value}
        elif command_name == "activate":
            hwnd = args.get("hwnd")
            if not hwnd:
                return {"error": "hwnd required"}
            return {"ok": activate_window(hwnd)}
        elif command_name == "launch":
            app = args.get("app") or args.get("path") or args.get("path_or_name")
            if not app:
                return {"error": "app/path required"}
            return launch_app(app, timeout=args.get("timeout", 10.0))
        elif command_name == "foreground":
            return foreground_window()
        elif command_name in ("auto_window", "auto-window", "ensure_window", "ensure-window", "window_target", "window-target"):
            return auto_window(
                hwnd=args.get("hwnd"),
                title=args.get("title") or args.get("window_title") or args.get("window-title") or args.get("name"),
                process=args.get("process") or args.get("process_name") or args.get("process-name") or args.get("app_name") or args.get("app-name"),
                app=args.get("app") or args.get("path") or args.get("path_or_name") or args.get("path-or-name") or args.get("launch"),
                path=args.get("path"),
                timeout=args.get("timeout", args.get("wait_timeout", args.get("wait-timeout", 10.0))),
                interval=args.get("interval", 0.25),
                match=args.get("match", "contains"),
                activate=_coerce_bool(args.get("activate"), True),
                restore=_coerce_bool(args.get("restore"), True),
                boundary=_coerce_bool(args.get("boundary", args.get("control_boundary", args.get("control-boundary"))), True),
                helper=_coerce_bool(args.get("helper", args.get("helper_status", args.get("helper-status"))), False),
                observe_window=_coerce_bool(args.get("observe", args.get("observe_window", args.get("observe-window"))), False),
                include_a11y=_coerce_bool(args.get("include_a11y", args.get("include-a11y", args.get("accessibility"))), False),
                ocr=_coerce_bool(args.get("ocr"), False),
            )
        elif command_name in ("window_selector_repair_find", "window-selector-repair-find", "window_repair_find", "window-repair-find", "window_selector_repair", "window-selector-repair", "window_rebind", "window-rebind"):
            original = dict(args.get("original") if isinstance(args.get("original"), dict) else {})
            for key, aliases in {
                "hwnd": ("hwnd", "window_hwnd", "window-hwnd", "target_hwnd", "target-hwnd"),
                "title": ("title", "window_title", "window-title", "name"),
                "process": ("process", "process_name", "process-name", "app_name", "app-name"),
                "pid": ("pid", "process_id", "process-id"),
                "match": ("match",),
                "timeout": ("timeout", "wait_timeout", "wait-timeout"),
                "interval": ("interval",),
                "stable_ticks": ("stable_ticks", "stable-ticks"),
            }.items():
                if original.get(key) not in (None, "", [], {}):
                    continue
                for alias in aliases:
                    if args.get(alias) not in (None, "", [], {}):
                        original[key] = args.get(alias)
                        break
            return window_selector_repair_find(
                suggestion=args.get("suggestion") if isinstance(args.get("suggestion"), dict) else {},
                original=original,
                timeout=args.get("timeout", args.get("wait_timeout", args.get("wait-timeout"))),
                interval=args.get("interval"),
                match=args.get("match"),
                stable_ticks=args.get("stable_ticks", args.get("stable-ticks")),
                allow_suggestion_hwnd=_coerce_bool(args.get("allow_suggestion_hwnd", args.get("allow-suggestion-hwnd")), False),
                probe_original=_coerce_bool(args.get("probe_original", args.get("probe-original")), True),
            )
        elif command_name in ("helper_status", "helper-status"):
            return helper_status(
                restart=_coerce_bool(args.get("restart"), False),
                elevated=_coerce_bool(args.get("elevated"), False),
                start=_coerce_bool(args.get("start"), False),
            )
        elif command_name in ("control_boundary", "control-boundary", "boundary", "integrity"):
            return control_boundary(args.get("hwnd"))
        elif command_name in ("gui_thread_info", "gui-thread-info", "gui"):
            return gui_thread_info(hwnd=args.get("hwnd"), thread_id=args.get("thread_id"))
        elif command_name in ("focus_hwnd", "focus-hwnd", "hwnd_focus", "hwnd-focus", "set_focus_hwnd"):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return focus_hwnd(
                int(hwnd),
                timeout=args.get("timeout", 1.0),
                restore=args.get("restore", True),
            )
        elif command_name in ("focused_input", "focused-input", "focus_input", "focus-input"):
            return focused_input(
                args.get("hwnd"),
                args.get("text", ""),
                mode=args.get("mode", "auto"),
                timeout=args.get("timeout", 1.0),
                restore=args.get("restore", True),
                timeout_ms=args.get("timeout_ms", 500),
                verify=args.get("verify", True),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                allow_focus_fallback=args.get("allow_focus_fallback", args.get("allow-focus-fallback", False)),
            )
        elif command_name in ("smart_text_input", "smart-text-input", "smart_text", "smart-text"):
            return smart_text_input(
                args.get("hwnd"),
                args.get("text", ""),
                name=args.get("name"),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                mode=args.get("mode", "set-text"),
                timeout=args.get("timeout", 1.0),
                timeout_ms=args.get("timeout_ms", 500),
                verify=args.get("verify", True),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                allow_focus_fallback=args.get("allow_focus_fallback", args.get("allow-focus-fallback", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("smart_wait_text_input", "smart-wait-text-input", "smart_wait_text", "smart-wait-text"):
            return smart_wait_text_input(
                args.get("hwnd"),
                args.get("text", ""),
                name=args.get("name"),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                mode=args.get("mode", "set-text"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                input_timeout=args.get("input_timeout", args.get("input-timeout", 1.0)),
                timeout_ms=args.get("timeout_ms", 500),
                verify=args.get("verify", True),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                allow_focus_fallback=args.get("allow_focus_fallback", args.get("allow-focus-fallback", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("smart_click", "smart-click", "smart_control_action", "smart-control-action"):
            return smart_click(
                args.get("hwnd"),
                name=args.get("name"),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                action=args.get("action", "invoke"),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                allow_coordinate_fallback=args.get("allow_coordinate_fallback", args.get("allow-coordinate-fallback", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("smart_wait_click", "smart-wait-click", "smart_wait_control_action", "smart-wait-control-action"):
            return smart_wait_click(
                args.get("hwnd"),
                name=args.get("name"),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                action=args.get("action", "invoke"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                allow_coordinate_fallback=args.get("allow_coordinate_fallback", args.get("allow-coordinate-fallback", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("smart_select", "smart-select", "smart_select_item", "smart-select-item"):
            return smart_select(
                args.get("hwnd"),
                item=args.get("item", args.get("text", args.get("value"))),
                name=args.get("name"),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                mode=args.get("mode", "select"),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("smart_wait_select", "smart-wait-select", "smart_wait_select_item", "smart-wait-select-item"):
            return smart_wait_select(
                args.get("hwnd"),
                item=args.get("item", args.get("text", args.get("value"))),
                name=args.get("name"),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                mode=args.get("mode", "select"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("smart_cell", "smart-cell", "smart_grid_cell", "smart-grid-cell", "smart_listview_cell", "smart-listview-cell"):
            return smart_cell(
                args.get("hwnd"),
                row=args.get("row"),
                column=args.get("column", args.get("col")),
                row_text=args.get("row_text") or args.get("row-text") or args.get("name"),
                column_name=args.get("column_name") or args.get("column-name") or args.get("header"),
                text=args.get("text", args.get("value")),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                match=args.get("match", "contains"),
                action=args.get("action", "get"),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("smart_wait_cell", "smart-wait-cell", "smart_wait_grid_cell", "smart-wait-grid-cell", "smart_wait_listview_cell", "smart-wait-listview-cell"):
            return smart_wait_cell(
                args.get("hwnd"),
                row=args.get("row"),
                column=args.get("column", args.get("col")),
                row_text=args.get("row_text") or args.get("row-text") or args.get("name"),
                column_name=args.get("column_name") or args.get("column-name") or args.get("header"),
                text=args.get("text", args.get("value")),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                match=args.get("match", "contains"),
                action=args.get("action", "get"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("smart_dialog_action", "smart-dialog-action", "smart_dialog", "smart-dialog", "smart_wait_dialog", "smart-wait-dialog", "smart_wait_dialog_action", "smart-wait-dialog-action"):
            return smart_dialog_action(
                args.get("hwnd"),
                action_kind=args.get("action_kind") or args.get("action-kind") or args.get("kind", "click"),
                dialog_title=args.get("dialog_title") or args.get("dialog-title") or args.get("title"),
                dialog_class_name=args.get("dialog_class_name") or args.get("dialog-class-name") or args.get("dialog_class") or args.get("dialog-class"),
                dialog_process=args.get("dialog_process") or args.get("dialog-process") or args.get("process"),
                name=args.get("name"),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                text=args.get("text", args.get("value")),
                item=args.get("item"),
                row=args.get("row"),
                column=args.get("column", args.get("col")),
                row_text=args.get("row_text") or args.get("row-text"),
                column_name=args.get("column_name") or args.get("column-name") or args.get("header"),
                control_action=args.get("control_action") or args.get("control-action") or args.get("click_action") or args.get("click-action") or args.get("action", "invoke"),
                cell_action=args.get("cell_action") or args.get("cell-action") or "get",
                mode=args.get("mode", "set-text"),
                timeout=args.get("timeout", 10.0),
                action_timeout=args.get("action_timeout", args.get("action-timeout", 5.0)),
                interval=args.get("interval", 0.25),
                input_timeout=args.get("input_timeout", args.get("input-timeout", 1.0)),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                verify=args.get("verify", True),
                diagnostic=args.get("diagnostic", args.get("verbose", False)),
                allow_focus_fallback=args.get("allow_focus_fallback", args.get("allow-focus-fallback", False)),
                allow_coordinate_fallback=args.get("allow_coordinate_fallback", args.get("allow-coordinate-fallback", False)),
                skip_uia=args.get("skip_uia", args.get("skip-uia", args.get("no_uia", args.get("no-uia", False)))),
                include_invisible=args.get("include_invisible", args.get("include-invisible", False)),
                stable_ticks=args.get("stable_ticks", args.get("stable-ticks", args.get("dialog_stable_ticks", args.get("dialog-stable-ticks", 2)))),
                activate=args.get("activate", True),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair", args.get("action_repair", args.get("action-repair"))))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout", args.get("action_repair_timeout", args.get("action-repair-timeout")))))),
            )
        elif command_name in ("dialog_command_action", "dialog-command-action", "dialog_command", "dialog-command", "native_dialog_command", "native-dialog-command", "messagebox_command", "messagebox-command", "message_box_command", "message-box-command"):
            return dialog_command_action(
                args.get("hwnd"),
                action=args.get("action") or args.get("command") or args.get("name") or args.get("text"),
                command_id=args.get("command_id") or args.get("command-id") or args.get("id"),
                name=args.get("name") or args.get("text"),
                dialog_title=args.get("dialog_title") or args.get("dialog-title") or args.get("title"),
                dialog_class_name=args.get("dialog_class_name") or args.get("dialog-class-name") or args.get("dialog_class") or args.get("dialog-class"),
                dialog_process=args.get("dialog_process") or args.get("dialog-process") or args.get("process"),
                match=args.get("match", "contains"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                include_invisible=_coerce_bool(args.get("include_invisible", args.get("include-invisible")), False),
                activate=_coerce_bool(args.get("activate"), True),
                verify_close=_coerce_bool(args.get("verify_close", args.get("verify-close")), False),
                diagnostic=_coerce_bool(args.get("diagnostic", args.get("verbose")), False),
            )
        elif command_name in ("dialog_button_action", "dialog-button-action", "dialog_button", "dialog-button", "native_dialog_button", "native-dialog-button", "messagebox_button", "messagebox-button", "message_box_button", "message-box-button"):
            return dialog_button_action(
                args.get("hwnd"),
                name=args.get("name") or args.get("text"),
                action=args.get("action") or args.get("command"),
                command_id=args.get("command_id") or args.get("command-id") or args.get("id"),
                dialog_title=args.get("dialog_title") or args.get("dialog-title") or args.get("title"),
                dialog_class_name=args.get("dialog_class_name") or args.get("dialog-class-name") or args.get("dialog_class") or args.get("dialog-class"),
                dialog_process=args.get("dialog_process") or args.get("dialog-process") or args.get("process"),
                automation_id=args.get("automation_id") or args.get("automation-id"),
                class_name=args.get("class_name") or args.get("class-name") or args.get("class"),
                control_type=args.get("control_type") or args.get("control-type") or args.get("type"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 500)),
                include_invisible=_coerce_bool(args.get("include_invisible", args.get("include-invisible")), False),
                activate=_coerce_bool(args.get("activate"), True),
                verify_close=_coerce_bool(args.get("verify_close", args.get("verify-close")), False),
                prefer_command=_coerce_bool(args.get("prefer_command", args.get("prefer-command")), True),
                diagnostic=_coerce_bool(args.get("diagnostic", args.get("verbose")), False),
            )
        elif command_name == "related_windows":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return related_windows(hwnd, include_invisible=args.get("include_invisible", False))
        elif command_name == "wait_window":
            if args.get("hwnd") is not None:
                return _wait_stable_window(
                    hwnd=args.get("hwnd"),
                    title=args.get("title"),
                    process=args.get("process"),
                    timeout=args.get("timeout", 10.0),
                    interval=args.get("interval", 0.25),
                    match=args.get("match", "contains"),
                    stable_ticks=args.get("stable_ticks", args.get("stable-ticks", 2)),
                )
            return wait_window(
                title=args.get("title"),
                process=args.get("process"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                match=args.get("match", "contains"),
            )
        elif command_name in ("window_action", "window-action", "window"):
            hwnd = args.get("hwnd")
            action = args.get("action")
            if hwnd is None or not action:
                return {"error": "hwnd and action required"}
            return window_action(
                int(hwnd),
                str(action),
                x=args.get("x"),
                y=args.get("y"),
                width=args.get("width"),
                height=args.get("height"),
                timeout=args.get("timeout", 1.5),
            )
        elif command_name in ("wait_event", "wait-event"):
            return wait_event(
                event=args.get("event"),
                hwnd=args.get("hwnd"),
                pid=args.get("pid"),
                title=args.get("title"),
                class_name=args.get("class_name") or args.get("class"),
                timeout=args.get("timeout", 5.0),
                limit=args.get("limit", 1),
                match=args.get("match", "contains"),
                include_children=args.get("include_children", True),
                skip_own_process=args.get("skip_own_process", True),
            )
        elif command_name == "screen":
            return screen_info()
        elif command_name == "mouse":
            return mouse_position()
        elif command_name in ("mouse_context", "mouse-context", "cursor_context", "cursor-context", "point_context", "point-context"):
            return mouse_context(
                args.get("x"),
                args.get("y"),
                hwnd=args.get("hwnd"),
                screenshot_id=args.get("screenshot_id"),
                include_text=_coerce_bool(args.get("include_text", args.get("include-text")), False),
                include_uia=_coerce_bool(args.get("include_uia", args.get("include-uia")), True),
                include_msaa=_coerce_bool(args.get("include_msaa", args.get("include-msaa")), True),
            )
        elif command_name == "child_windows":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return child_windows(
                hwnd,
                include_invisible=args.get("include_invisible", False),
                include_text=args.get("include_text", False),
                max_count=args.get("max_count", 500),
            )
        elif command_name == "window_from_point":
            return window_from_point(
                args.get("x"),
                args.get("y"),
                hwnd=args.get("hwnd"),
                screenshot_id=args.get("screenshot_id"),
                include_text=args.get("include_text", False),
            )
        elif command_name == "element_from_point":
            return element_from_point(
                args.get("x"),
                args.get("y"),
                hwnd=args.get("hwnd"),
                screenshot_id=args.get("screenshot_id"),
            )
        elif command_name == "msaa_window":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return msaa_window(hwnd, max_children=args.get("max_children", 80))
        elif command_name == "msaa_from_point":
            return msaa_from_point(
                args.get("x"),
                args.get("y"),
                hwnd=args.get("hwnd"),
                screenshot_id=args.get("screenshot_id"),
            )
        elif command_name == "msaa_action":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return msaa_action(
                hwnd,
                path=args.get("path") or [],
                child_id=args.get("child_id", MSAA_SELF),
                action=args.get("action", "default"),
                value=args.get("value"),
            )
        elif command_name == "menu_tree":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return menu_tree(
                hwnd,
                include_system=args.get("include_system", False),
                max_depth=args.get("max_depth", 5),
                max_items=args.get("max_items", 300),
            )
        elif command_name == "menu_action":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return menu_action(
                hwnd,
                path=args.get("path"),
                command_id=args.get("command_id"),
                include_system=args.get("include_system", False),
                async_post=args.get("async_post", False),
                timeout_ms=args.get("timeout_ms", 500),
            )
        elif command_name == "win32_text":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return win32_text(hwnd, timeout_ms=args.get("timeout_ms", 250))
        elif command_name == "win32_set_text":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return win32_set_text(hwnd, args.get("text", ""), timeout_ms=args.get("timeout_ms", 500))
        elif command_name == "win32_click":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return win32_click(hwnd, timeout_ms=args.get("timeout_ms", 500))
        elif command_name in ("win32_control_find",):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return win32_control_find(
                hwnd,
                name=args.get("name"),
                automation_id=args.get("automation_id", args.get("automation-id")),
                control_type=args.get("control_type", args.get("control-type", args.get("type"))),
                class_name=args.get("class_name", args.get("class-name", args.get("class"))),
                text=args.get("text"),
                value=args.get("value"),
                state=args.get("state"),
                expected=args.get("expected", args.get("checked")),
                match=args.get("match", "contains"),
                include_invisible=_coerce_bool(args.get("include_invisible", args.get("include-invisible")), False),
                include_self=_coerce_bool(args.get("include_self", args.get("include-self")), True),
                limit=args.get("limit", 20),
                min_score=args.get("min_score", args.get("min-score")),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 250)),
                max_items=args.get("max_items", args.get("max-items", 200)),
                max_children=args.get("max_children", args.get("max-children", 1000)),
                diagnostic=_coerce_bool(args.get("diagnostic", args.get("verbose")), False),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("win32_selector_repair_find", "win32-selector-repair-find", "native_selector_repair_find", "native-selector-repair-find", "win32_repair_find", "win32-repair-find", "native_repair_find", "native-repair-find"):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"ok": False, "error": "hwnd required"}
            return win32_selector_repair_find(
                hwnd,
                args.get("suggestion") if isinstance(args.get("suggestion"), dict) else {},
                original=args.get("original") if isinstance(args.get("original"), dict) else {},
                limit=args.get("limit", 1),
                include_invisible=args.get("include_invisible", args.get("include-invisible")),
                include_self=args.get("include_self", args.get("include-self")),
                min_score=args.get("min_score", args.get("min-score")),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms")),
                max_items=args.get("max_items", args.get("max-items")),
                max_children=args.get("max_children", args.get("max-children")),
                diagnostic=args.get("diagnostic", args.get("verbose")),
                allow_suggestion_hwnd=_coerce_bool(args.get("allow_suggestion_hwnd", args.get("allow-suggestion-hwnd")), False),
            )
        elif command_name == "win32_control_wait_find":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return win32_control_wait_find(
                hwnd,
                name=args.get("name"),
                automation_id=args.get("automation_id", args.get("automation-id")),
                control_type=args.get("control_type", args.get("control-type", args.get("type"))),
                class_name=args.get("class_name", args.get("class-name", args.get("class"))),
                text=args.get("text"),
                value=args.get("value"),
                state=args.get("state"),
                expected=args.get("expected", args.get("checked")),
                match=args.get("match", "contains"),
                include_invisible=_coerce_bool(args.get("include_invisible", args.get("include-invisible")), False),
                include_self=_coerce_bool(args.get("include_self", args.get("include-self")), True),
                limit=args.get("limit", 20),
                min_score=args.get("min_score", args.get("min-score")),
                timeout=args.get("timeout", 3.0),
                interval=args.get("interval", 0.1),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 250)),
                max_items=args.get("max_items", args.get("max-items", 200)),
                max_children=args.get("max_children", args.get("max-children", 1000)),
                diagnostic=_coerce_bool(args.get("diagnostic", args.get("verbose")), False),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name in ("file_dialog_info", "file-dialog-info", "file_dialog", "file-dialog"):
            return file_dialog_info(
                hwnd=args.get("hwnd"),
                timeout=args.get("timeout", 0.0),
                timeout_ms=args.get("timeout_ms", 300),
                include_children=_coerce_bool(args.get("include_children"), False),
            )
        elif command_name in ("file_dialog_action", "file-dialog-action"):
            return file_dialog_action(
                args.get("action", "info"),
                hwnd=args.get("hwnd"),
                path=args.get("path") or args.get("file_dialog_path") or args.get("filename") or args.get("file"),
                timeout=args.get("timeout", 5.0),
                timeout_ms=args.get("timeout_ms", 500),
                verify_close=_coerce_bool(args.get("verify_close"), False),
            )
        elif command_name == "win32_control_info":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return win32_control_info(
                hwnd,
                timeout_ms=args.get("timeout_ms", 250),
                max_items=args.get("max_items", 200),
            )
        elif command_name == "win32_control_action":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return win32_control_action(
                hwnd,
                args.get("action", "select"),
                index=args.get("index"),
                text=args.get("text"),
                value=args.get("value"),
                checked=args.get("checked"),
                match=args.get("match", "contains"),
                timeout_ms=args.get("timeout_ms", 500),
            )
        elif command_name == "win32_control_wait":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return win32_control_wait(
                hwnd,
                state=args.get("state", args.get("field")),
                expected=args.get("expected", args.get("value", args.get("checked"))),
                index=args.get("index"),
                text=args.get("text", args.get("item")),
                match=args.get("match", "contains"),
                timeout=args.get("timeout", 3.0),
                interval=args.get("interval", 0.1),
                timeout_ms=args.get("timeout_ms", args.get("timeout-ms", 250)),
                max_items=args.get("max_items", args.get("max-items", 200)),
                diagnostic=args.get("diagnostic", False),
                repair=args.get("repair", args.get("native_wait_repair", args.get("native-wait-repair"))),
                repair_match=args.get("repair_match", args.get("repair-match", args.get("native_wait_repair_match", args.get("native-wait-repair-match")))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("native_wait_repair_timeout", args.get("native-wait-repair-timeout")))),
            )
        elif command_name == "doctor":
            return doctor(args.get("hwnd"))
        elif command_name == "selftest":
            return selftest(args.get("target", "notepad"), timeout=args.get("timeout", 15.0))
        elif command_name in ("move", "hover"):
            hwnd = args.get("hwnd")
            result = move_mouse(
                hwnd,
                args.get("x", 0),
                args.get("y", 0),
                args.get("screenshot_id"),
                duration=args.get("duration", 0.0),
                settle=args.get("settle", args.get("pause", 0.05)),
                activate=_coerce_bool(args.get("activate"), True),
            )
            return {"ok": True, "message": result}
        elif command_name == "click":
            hwnd = args.get("hwnd")
            x = args.get("x", 0)
            y = args.get("y", 0)
            button = args.get("button", "left")
            clicks = args.get("clicks", 1)
            screenshot_id = args.get("screenshot_id")
            result = click(hwnd, x, y, button, clicks, screenshot_id)
            return {"ok": True, "message": result}
        elif command_name in ("desktop_move", "desktop-move", "desktop_hover", "desktop-hover"):
            result = desktop_move(
                args.get("x", 0),
                args.get("y", 0),
                args.get("screenshot_id"),
                duration=args.get("duration", 0.0),
                settle=args.get("settle", args.get("pause", 0.05)),
            )
            return {"ok": True, "message": result}
        elif command_name in ("desktop_click", "desktop-click"):
            result = desktop_click(
                args.get("x", 0),
                args.get("y", 0),
                args.get("button", "left"),
                args.get("clicks", 1),
                args.get("screenshot_id"),
            )
            return {"ok": True, "message": result}
        elif command_name == "type":
            hwnd = args.get("hwnd")
            text = args.get("text", "")
            result = type_text(hwnd, text)
            return {"ok": True, "message": result}
        elif command_name in ("type_foreground", "type-foreground", "foreground_type", "foreground-type"):
            text = args.get("text", "")
            result = type_text_foreground(text)
            return {"ok": True, "message": result}
        elif command_name == "key":
            hwnd = args.get("hwnd")
            keys = args.get("keys", "")
            result = press_key(hwnd, keys)
            return {"ok": True, "message": result}
        elif command_name == "scroll":
            hwnd = args.get("hwnd")
            x = args.get("x", 0)
            y = args.get("y", 0)
            dy = args.get("dy", 0)
            screenshot_id = args.get("screenshot_id")
            result = scroll(hwnd, x, y, dy, screenshot_id)
            return {"ok": True, "message": result}
        elif command_name == "drag":
            hwnd = args.get("hwnd")
            result = drag(
                hwnd,
                args.get("start_x", args.get("x1", 0)),
                args.get("start_y", args.get("y1", 0)),
                args.get("end_x", args.get("x2", 0)),
                args.get("end_y", args.get("y2", 0)),
                args.get("duration", 0.5),
                args.get("screenshot_id"),
            )
            return {"ok": True, "message": result}
        elif command_name in ("desktop_scroll", "desktop-scroll"):
            result = desktop_scroll(
                args.get("x", 0),
                args.get("y", 0),
                args.get("scroll_y", args.get("dy", 0)),
                args.get("screenshot_id"),
            )
            return {"ok": True, "message": result}
        elif command_name in ("desktop_drag", "desktop-drag"):
            result = desktop_drag(
                args.get("start_x", args.get("x1", 0)),
                args.get("start_y", args.get("y1", 0)),
                args.get("end_x", args.get("x2", 0)),
                args.get("end_y", args.get("y2", 0)),
                args.get("duration", 0.5),
                args.get("screenshot_id"),
            )
            return {"ok": True, "message": result}
        elif command_name == "screenshot":
            hwnd = args.get("hwnd")
            output = args.get("output", os.path.join(os.path.dirname(__file__), "screenshot.jpg"))
            max_w = args.get("max_width", 1280)
            result = screenshot(hwnd, output, max_w, capture_mode=args.get("capture_mode", args.get("capture", "auto")))
            return result
        elif command_name in ("desktop_screenshot", "desktop-screenshot"):
            output = args.get("output", os.path.join(os.path.dirname(__file__), "desktop.jpg"))
            max_w = args.get("max_width", 1600)
            return desktop_screenshot(output, max_width=max_w)
        elif command_name == "pixel":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return pixel(hwnd, args.get("x", 0), args.get("y", 0), args.get("screenshot_id"))
        elif command_name in ("pixel_wait", "pixel-wait", "wait_pixel", "wait-pixel"):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            color = args.get("color", args.get("expected", args.get("hex")))
            if color is None:
                return {"error": "color required"}
            return pixel_wait(
                hwnd,
                args.get("x", 0),
                args.get("y", 0),
                color,
                tolerance=args.get("tolerance", 0.0),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                mode=args.get("mode", "equals"),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("visual_stable_wait", "visual-stable-wait", "wait_visual_stable", "wait-visual-stable", "visual_wait_stable", "visual-wait-stable"):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return visual_stable_wait(
                hwnd,
                timeout=args.get("timeout", 5.0),
                interval=args.get("interval", 0.25),
                stable_ticks=args.get("stable_ticks", args.get("stable-ticks", 2)),
                difference_threshold=args.get("difference_threshold", args.get("difference-threshold", args.get("diff_threshold", 0.003))),
                pixel_threshold=args.get("pixel_threshold", args.get("pixel-threshold", 8.0)),
                region=args.get("region"),
                max_width=args.get("max_width", args.get("max-width", 1280)),
                comparison_max_width=args.get("comparison_max_width", args.get("comparison-max-width", args.get("stable_max_width", args.get("stable-max-width", 320)))),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("desktop_pixel", "desktop-pixel"):
            return desktop_pixel(args.get("x", 0), args.get("y", 0), args.get("screenshot_id"))
        elif command_name in ("desktop_pixel_wait", "desktop-pixel-wait", "desktop_wait_pixel", "desktop-wait-pixel", "wait_desktop_pixel", "wait-desktop-pixel"):
            color = args.get("color", args.get("expected", args.get("hex")))
            if color is None:
                return {"error": "color required"}
            return desktop_pixel_wait(
                args.get("x", 0),
                args.get("y", 0),
                color,
                tolerance=args.get("tolerance", 0.0),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                mode=args.get("mode", "equals"),
                max_width=args.get("max_width", 1600),
            )
        elif command_name in ("desktop_visual_stable_wait", "desktop-visual-stable-wait", "desktop_wait_visual_stable", "desktop-wait-visual-stable", "wait_desktop_visual_stable", "wait-desktop-visual-stable"):
            return desktop_visual_stable_wait(
                timeout=args.get("timeout", 5.0),
                interval=args.get("interval", 0.25),
                stable_ticks=args.get("stable_ticks", args.get("stable-ticks", 2)),
                difference_threshold=args.get("difference_threshold", args.get("difference-threshold", args.get("diff_threshold", 0.003))),
                pixel_threshold=args.get("pixel_threshold", args.get("pixel-threshold", 8.0)),
                region=args.get("region"),
                max_width=args.get("max_width", args.get("max-width", args.get("max_screenshot_width", args.get("max-screenshot-width", 1600)))),
                comparison_max_width=args.get("comparison_max_width", args.get("comparison-max-width", args.get("stable_max_width", args.get("stable-max-width", 320)))),
            )
        elif command_name in ("uia_stable_wait", "uia-stable-wait", "wait_uia_stable", "wait-uia-stable", "uia_wait_stable", "uia-wait-stable"):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return uia_stable_wait(
                hwnd,
                timeout=args.get("timeout", 5.0),
                interval=args.get("interval", 0.25),
                stable_ticks=args.get("stable_ticks", args.get("stable-ticks", 2)),
                max_depth=args.get("max_depth", args.get("max-depth", 10)),
                max_elements=args.get("max_elements", args.get("max-elements", 500)),
                view=args.get("view", "control"),
                include_values=_coerce_bool(args.get("include_values", args.get("include-values", args.get("values"))), False),
                rect_bucket=args.get("rect_bucket", args.get("rect-bucket", 2)),
            )
        elif command_name in ("desktop_uia_stable_wait", "desktop-uia-stable-wait", "desktop_wait_uia_stable", "desktop-wait-uia-stable", "wait_desktop_uia_stable", "wait-desktop-uia-stable"):
            return desktop_uia_stable_wait(
                timeout=args.get("timeout", 5.0),
                interval=args.get("interval", 0.25),
                stable_ticks=args.get("stable_ticks", args.get("stable-ticks", 2)),
                max_depth=args.get("max_depth", args.get("max-depth", 4)),
                max_elements=args.get("max_elements", args.get("max-elements", 500)),
                view=args.get("view", "control"),
                include_values=_coerce_bool(args.get("include_values", args.get("include-values", args.get("values"))), False),
                rect_bucket=args.get("rect_bucket", args.get("rect-bucket", 2)),
            )
        elif command_name in ("desktop_point", "desktop-point"):
            return desktop_point(args.get("x", 0), args.get("y", 0), args.get("screenshot_id"))
        elif command_name in ("desktop_locate_image", "desktop-locate-image"):
            template = args.get("template") or args.get("template_path")
            if not template:
                return {"error": "template required"}
            return desktop_locate_image(
                template,
                confidence=args.get("confidence", 0.85),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                region=args.get("region"),
                scale_min=args.get("scale_min", 1.0),
                scale_max=args.get("scale_max", 1.0),
                scale_step=args.get("scale_step", 0.0),
            )
        elif command_name in ("desktop_image_wait", "desktop-image-wait", "desktop_wait_image", "desktop-wait-image"):
            template = args.get("template") or args.get("template_path")
            if not template:
                return {"error": "template required"}
            return desktop_image_wait(
                template,
                confidence=args.get("confidence", 0.85),
                max_width=args.get("max_width", 1600),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.5),
                region=args.get("region"),
                scale_min=args.get("scale_min", 1.0),
                scale_max=args.get("scale_max", 1.0),
                scale_step=args.get("scale_step", 0.0),
            )
        elif command_name in ("desktop_image_click", "desktop-image-click", "desktop_click_image", "desktop-click-image"):
            template = args.get("template") or args.get("template_path")
            if not template:
                return {"error": "template required"}
            return desktop_image_click(
                template,
                confidence=args.get("confidence", 0.85),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                timeout=args.get("timeout", 0.0),
                interval=args.get("interval", 0.5),
                region=args.get("region"),
                scale_min=args.get("scale_min", 1.0),
                scale_max=args.get("scale_max", 1.0),
                scale_step=args.get("scale_step", 0.0),
            )
        elif command_name in ("desktop_image_scroll_click", "desktop-image-scroll-click", "desktop_scroll_image_click", "desktop-scroll-image-click"):
            template = args.get("template") or args.get("template_path")
            if not template:
                return {"error": "template required"}
            return desktop_image_scroll_click(
                template,
                confidence=args.get("confidence", 0.85),
                max_width=args.get("max_width", 1600),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                region=args.get("region"),
                scale_min=args.get("scale_min", 1.0),
                scale_max=args.get("scale_max", 1.0),
                scale_step=args.get("scale_step", 0.0),
                max_scrolls=args.get("max_scrolls", 8),
                scroll_amount=args.get("scroll_amount", 5),
                scroll_x=args.get("scroll_x"),
                scroll_y=args.get("scroll_y"),
                pause=args.get("pause", 0.35),
            )
        elif command_name == "locate_image":
            hwnd = args.get("hwnd")
            template = args.get("template") or args.get("template_path")
            if hwnd is None or not template:
                return {"error": "hwnd and template required"}
            return locate_image(
                hwnd,
                template,
                confidence=args.get("confidence", 0.85),
                max_width=args.get("max_width", 1280),
                screenshot_id=args.get("screenshot_id"),
                region=args.get("region"),
                scale_min=args.get("scale_min", 1.0),
                scale_max=args.get("scale_max", 1.0),
                scale_step=args.get("scale_step", 0.0),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("image_wait", "image-wait", "wait_image", "wait-image"):
            hwnd = args.get("hwnd")
            template = args.get("template") or args.get("template_path")
            if hwnd is None or not template:
                return {"error": "hwnd and template required"}
            return image_wait(
                hwnd,
                template,
                confidence=args.get("confidence", 0.85),
                max_width=args.get("max_width", 1280),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.5),
                region=args.get("region"),
                scale_min=args.get("scale_min", 1.0),
                scale_max=args.get("scale_max", 1.0),
                scale_step=args.get("scale_step", 0.0),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("image_click", "image-click", "click_image", "click-image"):
            hwnd = args.get("hwnd")
            template = args.get("template") or args.get("template_path")
            if hwnd is None or not template:
                return {"error": "hwnd and template required"}
            return image_click(
                hwnd,
                template,
                confidence=args.get("confidence", 0.85),
                max_width=args.get("max_width", 1280),
                screenshot_id=args.get("screenshot_id"),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                timeout=args.get("timeout", 0.0),
                interval=args.get("interval", 0.5),
                region=args.get("region"),
                scale_min=args.get("scale_min", 1.0),
                scale_max=args.get("scale_max", 1.0),
                scale_step=args.get("scale_step", 0.0),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("image_scroll_click", "image-scroll-click", "scroll_image_click", "scroll-image-click", "image_wait_scroll_click", "image-wait-scroll-click"):
            hwnd = args.get("hwnd")
            template = args.get("template") or args.get("template_path")
            if hwnd is None or not template:
                return {"error": "hwnd and template required"}
            return image_scroll_click(
                hwnd,
                template,
                confidence=args.get("confidence", 0.85),
                max_width=args.get("max_width", 1280),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                region=args.get("region"),
                scale_min=args.get("scale_min", 1.0),
                scale_max=args.get("scale_max", 1.0),
                scale_step=args.get("scale_step", 0.0),
                max_scrolls=args.get("max_scrolls", 8),
                scroll_amount=args.get("scroll_amount", 5),
                scroll_x=args.get("scroll_x"),
                scroll_y=args.get("scroll_y"),
                pause=args.get("pause", 0.35),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name == "ocr":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return ocr(
                hwnd,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                engine=args.get("engine", "auto"),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("desktop_ocr", "desktop-ocr"):
            return desktop_ocr(
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                engine=args.get("engine", "auto"),
            )
        elif command_name in ("desktop_ocr_find", "desktop-ocr-find"):
            text = args.get("text") or args.get("query")
            if not text:
                return {"error": "text required"}
            return desktop_ocr_find(
                text,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                engine=args.get("engine", "auto"),
                match=args.get("match", "contains"),
                limit=args.get("limit", 10),
                region=args.get("region"),
                max_words=args.get("max_words"),
            )
        elif command_name in ("desktop_ocr_click", "desktop-ocr-click"):
            text = args.get("text") or args.get("query")
            if not text:
                return {"error": "text required"}
            return desktop_ocr_click(
                text,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                engine=args.get("engine", "auto"),
                match=args.get("match", "contains"),
                index=args.get("index", 0),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                region=args.get("region"),
                max_words=args.get("max_words"),
                timeout=args.get("timeout", 0.0),
                interval=args.get("interval", 0.5),
            )
        elif command_name in ("desktop_ocr_scroll_click", "desktop-ocr-scroll-click", "desktop_scroll_ocr_click", "desktop-scroll-ocr-click"):
            text = args.get("text") or args.get("query")
            if not text:
                return {"error": "text required"}
            return desktop_ocr_scroll_click(
                text,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                engine=args.get("engine", "auto"),
                match=args.get("match", "contains"),
                index=args.get("index", 0),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                region=args.get("region"),
                max_words=args.get("max_words"),
                max_scrolls=args.get("max_scrolls", 8),
                scroll_amount=args.get("scroll_amount", 5),
                scroll_x=args.get("scroll_x"),
                scroll_y=args.get("scroll_y"),
                pause=args.get("pause", 0.35),
            )
        elif command_name in ("desktop_ocr_wait", "desktop-ocr-wait", "desktop_wait_ocr", "desktop-wait-ocr"):
            text = args.get("text") or args.get("query")
            if not text:
                return {"error": "text required"}
            return desktop_ocr_wait(
                text,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                engine=args.get("engine", "auto"),
                match=args.get("match", "contains"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.5),
                limit=args.get("limit", 10),
                region=args.get("region"),
                max_words=args.get("max_words"),
            )
        elif command_name in ("ocr_find", "ocr-find"):
            hwnd = args.get("hwnd")
            text = args.get("text") or args.get("query")
            if hwnd is None or not text:
                return {"error": "hwnd and text required"}
            return ocr_find(
                hwnd,
                text,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                engine=args.get("engine", "auto"),
                match=args.get("match", "contains"),
                limit=args.get("limit", 10),
                region=args.get("region"),
                max_words=args.get("max_words"),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("ocr_click", "ocr-click"):
            hwnd = args.get("hwnd")
            text = args.get("text") or args.get("query")
            if hwnd is None or not text:
                return {"error": "hwnd and text required"}
            return ocr_click(
                hwnd,
                text,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                engine=args.get("engine", "auto"),
                match=args.get("match", "contains"),
                index=args.get("index", 0),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                region=args.get("region"),
                max_words=args.get("max_words"),
                timeout=args.get("timeout", 0.0),
                interval=args.get("interval", 0.5),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("ocr_scroll_click", "ocr-scroll-click", "scroll_ocr_click", "scroll-ocr-click", "ocr_wait_scroll_click", "ocr-wait-scroll-click"):
            hwnd = args.get("hwnd")
            text = args.get("text") or args.get("query")
            if hwnd is None or not text:
                return {"error": "hwnd and text required"}
            return ocr_scroll_click(
                hwnd,
                text,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                engine=args.get("engine", "auto"),
                match=args.get("match", "contains"),
                index=args.get("index", 0),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
                region=args.get("region"),
                max_words=args.get("max_words"),
                max_scrolls=args.get("max_scrolls", 8),
                scroll_amount=args.get("scroll_amount", 5),
                scroll_x=args.get("scroll_x"),
                scroll_y=args.get("scroll_y"),
                pause=args.get("pause", 0.35),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("ocr_wait", "ocr-wait", "wait_ocr", "wait-ocr"):
            hwnd = args.get("hwnd")
            text = args.get("text") or args.get("query")
            if hwnd is None or not text:
                return {"error": "hwnd and text required"}
            return ocr_wait(
                hwnd,
                text,
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                engine=args.get("engine", "auto"),
                match=args.get("match", "contains"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.5),
                limit=args.get("limit", 10),
                region=args.get("region"),
                max_words=args.get("max_words"),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("visual_row", "visual-row", "visual_row_find", "visual-row-find"):
            hwnd = args.get("hwnd")
            row = args.get("row")
            if hwnd is None or row is None:
                return {"error": "hwnd and row required"}
            return visual_row(
                hwnd,
                int(row),
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                engine=args.get("engine", "auto"),
                row_region=args.get("row_region", args.get("region")),
                min_row=args.get("min_row", 1),
                max_row=args.get("max_row", 999),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("visual_row_click", "visual-row-click"):
            hwnd = args.get("hwnd")
            row = args.get("row")
            if hwnd is None or row is None:
                return {"error": "hwnd and row required"}
            return visual_row_click(
                hwnd,
                int(row),
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                screenshot_id=args.get("screenshot_id"),
                engine=args.get("engine", "auto"),
                row_region=args.get("row_region", args.get("region")),
                click_x=args.get("click_x"),
                x_offset=args.get("x_offset", 120),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 2),
                min_row=args.get("min_row", 1),
                max_row=args.get("max_row", 999),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("visual_row_scroll", "visual-row-scroll", "visual_row_wait", "visual-row-wait"):
            hwnd = args.get("hwnd")
            row = args.get("row")
            if hwnd is None or row is None:
                return {"error": "hwnd and row required"}
            return visual_row_scroll(
                hwnd,
                int(row),
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                engine=args.get("engine", "auto"),
                row_region=args.get("row_region", args.get("region")),
                min_row=args.get("min_row", 1),
                max_row=args.get("max_row", 999),
                max_scrolls=args.get("max_scrolls", 8),
                scroll_amount=args.get("scroll_amount", 5),
                scroll_x=args.get("scroll_x"),
                scroll_y=args.get("scroll_y"),
                pause=args.get("pause", 0.35),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name in ("visual_row_scroll_click", "visual-row-scroll-click", "visual_row_wait_click", "visual-row-wait-click"):
            hwnd = args.get("hwnd")
            row = args.get("row")
            if hwnd is None or row is None:
                return {"error": "hwnd and row required"}
            return visual_row_scroll_click(
                hwnd,
                int(row),
                lang=args.get("lang", "eng+chi_sim"),
                max_width=args.get("max_width", 1600),
                engine=args.get("engine", "auto"),
                row_region=args.get("row_region", args.get("region")),
                click_x=args.get("click_x"),
                x_offset=args.get("x_offset", 120),
                button=args.get("button", "left"),
                clicks=args.get("clicks", 2),
                min_row=args.get("min_row", 1),
                max_row=args.get("max_row", 999),
                max_scrolls=args.get("max_scrolls", 8),
                scroll_amount=args.get("scroll_amount", 5),
                scroll_x=args.get("scroll_x"),
                scroll_y=args.get("scroll_y"),
                pause=args.get("pause", 0.35),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name == "observe":
            return observe(
                args.get("hwnd"),
                include_screenshot=_coerce_bool(args.get("include_screenshot", args.get("screenshot")), True),
                include_accessibility=_coerce_bool(args.get("include_accessibility", args.get("include_a11y", args.get("accessibility"))), True),
                include_ocr=_coerce_bool(args.get("include_ocr", args.get("ocr")), False),
                ocr_on_accessibility_error=_coerce_bool(args.get("ocr_on_accessibility_error", args.get("ocr_on_a11y_error")), True),
                ocr_engine=args.get("ocr_engine", args.get("engine", "auto")),
                ocr_lang=args.get("ocr_lang", args.get("lang", "eng+chi_sim")),
                max_width=args.get("max_width", 1280),
                max_depth=args.get("max_depth", 10),
                max_elements=args.get("max_elements", 500),
                view=args.get("view", "raw"),
                output=args.get("output"),
                capture_mode=args.get("capture_mode", args.get("capture", "auto")),
            )
        elif command_name == "find":
            hwnd = args.get("hwnd")
            if not hwnd:
                return {"error": "hwnd required"}
            return find_elements(
                hwnd,
                name=args.get("name"),
                automation_id=args.get("automation_id"),
                control_type=args.get("control_type"),
                class_name=args.get("class_name"),
                value=args.get("value"),
                pattern=args.get("pattern"),
                enabled_only=args.get("enabled_only", False),
                visible_only=args.get("visible_only", True),
                match=args.get("match", "contains"),
                limit=args.get("limit", 25),
                max_depth=args.get("max_depth", 10),
                max_elements=args.get("max_elements", 500),
                view=args.get("view", "raw"),
            )
        elif command_name in ("desktop_accessibility", "desktop-accessibility", "desktop_uia", "desktop-uia"):
            return desktop_accessibility(
                max_depth=args.get("max_depth", 4),
                max_elements=args.get("max_elements", 500),
                hydrate=args.get("hydrate", True),
                view=args.get("view", "control"),
            )
        elif command_name in ("desktop_find", "desktop-find", "desktop_find_elements", "desktop-find-elements"):
            return desktop_find_elements(
                name=args.get("name"),
                automation_id=args.get("automation_id"),
                control_type=args.get("control_type"),
                class_name=args.get("class_name"),
                value=args.get("value"),
                pattern=args.get("pattern"),
                enabled_only=args.get("enabled_only", False),
                visible_only=args.get("visible_only", True),
                match=args.get("match", "contains"),
                limit=args.get("limit", 25),
                max_depth=args.get("max_depth", 4),
                max_elements=args.get("max_elements", 500),
                view=args.get("view", "control"),
            )
        elif command_name in ("desktop_wait", "desktop-wait", "desktop_wait_element", "desktop-wait-element"):
            selector = {
                "name": args.get("name"),
                "automation_id": args.get("automation_id"),
                "control_type": args.get("control_type"),
                "class_name": args.get("class_name"),
                "value": args.get("value"),
                "pattern": args.get("pattern"),
                "enabled_only": args.get("enabled_only", False),
                "visible_only": args.get("visible_only", True),
                "match": args.get("match", "contains"),
                "max_depth": args.get("max_depth", 4),
                "max_elements": args.get("max_elements", 500),
                "view": args.get("view", "control"),
            }
            return desktop_wait_for_element(
                selector,
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.5),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
                allow_suggestion_index=_coerce_bool(args.get("allow_suggestion_index", args.get("allow-suggestion-index")), False),
            )
        elif command_name in ("desktop_element", "desktop-element"):
            index = args.get("index")
            if index is None:
                return {"error": "index required"}
            return desktop_element(
                index,
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name in ("desktop_focus", "desktop-focus"):
            index = args.get("index")
            if index is None:
                return {"error": "index required"}
            return desktop_focus_element(
                index,
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name in ("desktop_click_index", "desktop-click-index"):
            index = args.get("index")
            if index is None:
                return {"error": "index required"}
            return _uia_click_message_result(
                desktop_click_index(
                    index,
                    button=args.get("button", "left"),
                    clicks=args.get("clicks", 1),
                    max_depth=args.get("max_depth"),
                    max_elements=args.get("max_elements"),
                    view=args.get("view"),
                ),
                hwnd=_DESKTOP_UIA_KEY,
                index=index,
            )
        elif command_name in ("desktop_action", "desktop-action"):
            index = args.get("index")
            action_name = args.get("action")
            if index is None or not action_name:
                return {"error": "index and action required"}
            return desktop_perform_action(
                index,
                action_name,
                value=args.get("value"),
                horizontal=args.get("horizontal"),
                vertical=args.get("vertical"),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name in ("item_container_find", "find_item_in_container"):
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            return item_container_find(
                hwnd,
                index,
                args.get("property_name", "name"),
                args.get("property_value", args.get("value", "")),
                limit=args.get("limit", 1),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
                include_children=bool(args.get("include_children", False)),
                max_children=int(args.get("max_children", 64) or 64),
            )
        elif command_name in ("uia_cell_selector_repair_find", "uia-cell-selector-repair-find", "uia_cell_repair_find", "uia-cell-repair-find"):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"ok": False, "error": "hwnd required"}
            return uia_cell_selector_repair_find(
                hwnd,
                args.get("suggestion") if isinstance(args.get("suggestion"), dict) else {},
                args.get("original") if isinstance(args.get("original"), dict) else {},
                row=args.get("row"),
                column=args.get("column"),
                row_text=args.get("row_text"),
                column_name=args.get("column_name"),
                limit=args.get("limit", 1),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name == "wait":
            hwnd = args.get("hwnd")
            if not hwnd:
                return {"error": "hwnd required"}
            selector = {
                "name": args.get("name"),
                "automation_id": args.get("automation_id"),
                "control_type": args.get("control_type"),
                "class_name": args.get("class_name"),
                "value": args.get("value"),
                "pattern": args.get("pattern"),
                "enabled_only": args.get("enabled_only", False),
                "visible_only": args.get("visible_only", True),
                "match": args.get("match", "contains"),
                "max_depth": args.get("max_depth", 10),
                "max_elements": args.get("max_elements", 500),
                "view": args.get("view", "raw"),
            }
            return wait_for_element(
                hwnd,
                selector,
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.5),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
                allow_suggestion_index=_coerce_bool(args.get("allow_suggestion_index", args.get("allow-suggestion-index")), False),
            )
        elif command_name == "focus":
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            return focus_element(
                hwnd,
                index,
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name == "click_index":
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            return _uia_click_message_result(
                click_index(
                    hwnd,
                    index,
                    args.get("button", "left"),
                    args.get("clicks", 1),
                    max_depth=args.get("max_depth"),
                    max_elements=args.get("max_elements"),
                    view=args.get("view"),
                ),
                hwnd=hwnd,
                index=index,
            )
        elif command_name == "set_value":
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            return set_value(
                hwnd,
                index,
                args.get("value", ""),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name == "action":
            hwnd = args.get("hwnd")
            index = args.get("index")
            action_name = args.get("action")
            if hwnd is None or index is None or not action_name:
                return {"error": "hwnd, index, and action required"}
            return perform_action(
                hwnd,
                index,
                action_name,
                value=args.get("value"),
                horizontal=args.get("horizontal"),
                vertical=args.get("vertical"),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name == "uia_accessibility":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return build_accessibility_tree(
                hwnd,
                max_depth=args.get("max_depth", 10),
                max_elements=args.get("max_elements", 500),
                hydrate=args.get("hydrate", True),
                view=args.get("view", "raw"),
            )
        elif command_name == "uia_find":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return find_elements(
                hwnd,
                name=args.get("name"),
                automation_id=args.get("automation_id"),
                control_type=args.get("control_type"),
                class_name=args.get("class_name"),
                value=args.get("value"),
                pattern=args.get("pattern"),
                enabled_only=args.get("enabled_only", False),
                visible_only=args.get("visible_only", True),
                match=args.get("match", "contains"),
                limit=args.get("limit", 25),
                max_depth=args.get("max_depth", 10),
                max_elements=args.get("max_elements", 500),
                view=args.get("view", "raw"),
            )
        elif command_name in ("uia_selector_repair_find", "uia-selector-repair-find", "uia_repair_find", "uia-repair-find"):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            return uia_selector_repair_find(
                hwnd,
                args.get("suggestion") or {},
                original=args.get("original") if isinstance(args.get("original"), dict) else {},
                limit=args.get("limit", 1),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
                allow_suggestion_index=_coerce_bool(args.get("allow_suggestion_index", args.get("allow-suggestion-index")), False),
            )
        elif command_name in ("uia_cell_selector_repair_find", "uia-cell-selector-repair-find", "uia_cell_repair_find", "uia-cell-repair-find"):
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"ok": False, "error": "hwnd required"}
            return uia_cell_selector_repair_find(
                hwnd,
                args.get("suggestion") if isinstance(args.get("suggestion"), dict) else {},
                args.get("original") if isinstance(args.get("original"), dict) else {},
                row=args.get("row"),
                column=args.get("column"),
                row_text=args.get("row_text"),
                column_name=args.get("column_name"),
                limit=args.get("limit", 1),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name == "uia_wait":
            hwnd = args.get("hwnd")
            if hwnd is None:
                return {"error": "hwnd required"}
            selector = dict(args.get("selector") or {})
            for key in ("name", "automation_id", "control_type", "class_name", "value", "pattern", "enabled_only", "visible_only", "match", "max_depth", "max_elements", "view"):
                if key not in selector and key in args:
                    selector[key] = args.get(key)
            return wait_for_element(
                hwnd,
                selector,
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.5),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
                allow_suggestion_index=_coerce_bool(args.get("allow_suggestion_index", args.get("allow-suggestion-index")), False),
            )
        elif command_name == "uia_element":
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            _, info = _uia_element_by_index(
                hwnd,
                index,
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
            return info or {"error": f"Element index {index} not found", "hwnd": hwnd, "index": index}
        elif command_name == "uia_focus":
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            return focus_element(
                hwnd,
                index,
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name == "uia_click_index":
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            return _uia_click_message_result(
                click_index(
                    hwnd,
                    index,
                    args.get("button", "left"),
                    args.get("clicks", 1),
                    max_depth=args.get("max_depth"),
                    max_elements=args.get("max_elements"),
                    view=args.get("view"),
                ),
                hwnd=hwnd,
                index=index,
            )
        elif command_name == "uia_set_value":
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            return set_value(
                hwnd,
                index,
                args.get("value", ""),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name == "uia_action":
            hwnd = args.get("hwnd")
            index = args.get("index")
            action_name = args.get("action")
            if hwnd is None or index is None or not action_name:
                return {"error": "hwnd, index, and action required"}
            return perform_action(
                hwnd,
                index,
                action_name,
                value=args.get("value"),
                horizontal=args.get("horizontal"),
                vertical=args.get("vertical"),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
            )
        elif command_name == "uia_item_container_find":
            hwnd = args.get("hwnd")
            index = args.get("index")
            if hwnd is None or index is None:
                return {"error": "hwnd and index required"}
            return item_container_find(
                hwnd,
                index,
                args.get("property_name", "name"),
                args.get("property_value", args.get("value", "")),
                limit=args.get("limit", 1),
                max_depth=args.get("max_depth"),
                max_elements=args.get("max_elements"),
                view=args.get("view"),
                include_children=bool(args.get("include_children", False)),
                max_children=int(args.get("max_children", 64) or 64),
            )
        elif command_name == "smart_select":
            return smart_select(
                args.get("hwnd"),
                item=args.get("item"),
                name=args.get("name"),
                automation_id=args.get("automation_id"),
                control_type=args.get("control_type"),
                class_name=args.get("class_name"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                mode=args.get("mode", "select"),
                timeout_ms=args.get("timeout_ms", 500),
                diagnostic=args.get("diagnostic", False),
                skip_uia=args.get("skip_uia", False),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name == "smart_wait_select":
            return smart_wait_select(
                args.get("hwnd"),
                item=args.get("item"),
                name=args.get("name"),
                automation_id=args.get("automation_id"),
                control_type=args.get("control_type"),
                class_name=args.get("class_name"),
                index=args.get("index"),
                match=args.get("match", "contains"),
                mode=args.get("mode", "select"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                timeout_ms=args.get("timeout_ms", 500),
                diagnostic=args.get("diagnostic", False),
                skip_uia=args.get("skip_uia", False),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name == "smart_cell":
            return smart_cell(
                args.get("hwnd"),
                row=args.get("row"),
                column=args.get("column"),
                row_text=args.get("row_text"),
                column_name=args.get("column_name"),
                text=args.get("text"),
                automation_id=args.get("automation_id"),
                control_type=args.get("control_type"),
                class_name=args.get("class_name"),
                match=args.get("match", "contains"),
                action=args.get("action", "get"),
                timeout_ms=args.get("timeout_ms", 500),
                diagnostic=args.get("diagnostic", False),
                skip_uia=args.get("skip_uia", False),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        elif command_name == "smart_wait_cell":
            return smart_wait_cell(
                args.get("hwnd"),
                row=args.get("row"),
                column=args.get("column"),
                row_text=args.get("row_text"),
                column_name=args.get("column_name"),
                text=args.get("text"),
                automation_id=args.get("automation_id"),
                control_type=args.get("control_type"),
                class_name=args.get("class_name"),
                match=args.get("match", "contains"),
                action=args.get("action", "get"),
                timeout=args.get("timeout", 10.0),
                interval=args.get("interval", 0.25),
                timeout_ms=args.get("timeout_ms", 500),
                diagnostic=args.get("diagnostic", False),
                skip_uia=args.get("skip_uia", False),
                repair=args.get("repair", args.get("selector_repair", args.get("selector-repair"))),
                repair_timeout=args.get("repair_timeout", args.get("repair-timeout", args.get("selector_repair_timeout", args.get("selector-repair-timeout")))),
            )
        else:
            return {"error": f"Unknown local command: {command_name}"}
    except Exception as e:
        return {"error": str(e)}


_HELPER_BATCH_COMMANDS = {"activate", "move", "click", "type", "key", "scroll", "drag", "win32_text", "win32_set_text", "win32_click", "win32_control_find", "win32_selector_repair_find", "win32_control_wait_find", "win32_control_info", "win32_control_action", "win32_control_wait", "menu_tree", "menu_action", "dialog_command_action", "dialog_button_action", "file_dialog_info", "file_dialog_action", "msaa_window", "msaa_from_point", "msaa_action", "child_windows", "window_from_point", "uia_accessibility", "uia_find", "uia_wait", "uia_element", "uia_focus", "uia_click_index", "uia_set_value", "uia_action", "uia_item_container_find", "uia_selector_repair_find", "uia_cell_selector_repair_find", "smart_click", "smart_wait_click", "smart_text", "smart_wait_text", "smart_select", "smart_wait_select", "smart_cell", "smart_wait_cell", "clipboard", "set_clipboard"}
_UIA_BATCH_COMMANDS = {"uia_accessibility", "uia_find", "uia_wait", "uia_element", "uia_focus", "uia_click_index", "uia_set_value", "uia_action", "uia_item_container_find", "uia_selector_repair_find", "uia_cell_selector_repair_find", "smart_click", "smart_wait_click", "smart_text", "smart_wait_text", "smart_select", "smart_wait_select", "smart_cell", "smart_wait_cell"}
_UIA_BATCH_PATHS = {"/uia_accessibility", "/uia_find", "/uia_wait", "/uia_element", "/uia_focus", "/uia_click_index", "/uia_set_value", "/uia_action", "/uia_item_container_find", "/uia_selector_repair_find", "/uia_cell_selector_repair_find", "/smart_click", "/smart_wait_click", "/smart_text", "/smart_wait_text", "/smart_select", "/smart_wait_select", "/smart_cell", "/smart_wait_cell"}
_BATCH_PATH_TO_COMMAND = {
    "/activate": "activate",
    "/move": "move",
    "/click": "click",
    "/type_text": "type",
    "/press_key": "key",
    "/scroll": "scroll",
    "/drag": "drag",
    "/win32_text": "win32_text",
    "/win32_set_text": "win32_set_text",
    "/win32_click": "win32_click",
    "/win32_control_find": "win32_control_find",
    "/win32_selector_repair_find": "win32_selector_repair_find",
    "/win32_control_wait_find": "win32_control_wait_find",
    "/win32_control_info": "win32_control_info",
    "/win32_control_action": "win32_control_action",
    "/win32_control_wait": "win32_control_wait",
    "/menu_tree": "menu_tree",
    "/menu_action": "menu_action",
    "/dialog_command_action": "dialog_command_action",
    "/dialog_button_action": "dialog_button_action",
    "/file_dialog_info": "file_dialog_info",
    "/file_dialog_action": "file_dialog_action",
    "/msaa_window": "msaa_window",
    "/msaa_from_point": "msaa_from_point",
    "/msaa_action": "msaa_action",
    "/child_windows": "child_windows",
    "/window_from_point": "window_from_point",
    "/uia_accessibility": "uia_accessibility",
    "/uia_find": "uia_find",
    "/uia_wait": "uia_wait",
    "/uia_element": "uia_element",
    "/uia_focus": "uia_focus",
    "/uia_click_index": "uia_click_index",
    "/uia_set_value": "uia_set_value",
    "/uia_action": "uia_action",
    "/uia_item_container_find": "uia_item_container_find",
    "/uia_selector_repair_find": "uia_selector_repair_find",
    "/uia_cell_selector_repair_find": "uia_cell_selector_repair_find",
    "/smart_click": "smart_click",
    "/smart_wait_click": "smart_wait_click",
    "/smart_text": "smart_text",
    "/smart_wait_text": "smart_wait_text",
    "/smart_select": "smart_select",
    "/smart_wait_select": "smart_wait_select",
    "/smart_cell": "smart_cell",
    "/smart_wait_cell": "smart_wait_cell",
    "/clipboard": "clipboard",
    "/set_clipboard": "set_clipboard",
}
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
    "get_window_state": "observe",
    "auto_window": "auto_window",
    "ensure_window": "auto_window",
    "ensure_target_window": "auto_window",
    "window_target": "auto_window",
    "target_window": "auto_window",
    "app_window": "auto_window",
    "launch_window": "auto_window",
    "recover_window": "auto_window",
    "window_selector_repair_find": "window_selector_repair_find",
    "window_repair_find": "window_selector_repair_find",
    "window_selector_repair": "window_selector_repair_find",
    "window_rebind": "window_selector_repair_find",
    "helper_status": "helper_status",
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
    "uia_selector_repair": "uia_selector_repair_find",
    "uia_cell_repair_find": "uia_cell_selector_repair_find",
    "uia_cell_selector_repair": "uia_cell_selector_repair_find",
    "batch_value": "batch_value",
    "batch_probe": "batch_value",
    "batch_retry_probe": "batch_retry_probe",
    "batch_rebinding_probe": "batch_rebinding_probe",
    "batch_rebind_target_probe": "batch_rebind_target_probe",
    "batch_repair_plan": "batch_repair_plan",
    "repair_plan": "batch_repair_plan",
    "diagnostic_repair_plan": "batch_repair_plan",
    "repair_batch_plan": "batch_repair_plan",
    "batch_sleep": "batch_sleep",
    "sleep": "batch_sleep",
    "delay": "batch_sleep",
    "wait_delay": "batch_sleep",
    "batch_try": "batch_try",
    "batch_fallback": "batch_try",
    "fallback": "batch_try",
    "try": "batch_try",
    "batch_auto": "batch_auto",
    "batch_auto_action": "batch_auto",
    "auto_action": "batch_auto",
    "auto_control": "batch_auto",
    "app_action": "batch_auto",
    "app_control": "batch_auto",
    "application_action": "batch_auto",
    "window_action_auto": "batch_auto",
    "window_control": "batch_auto",
    "target_action": "batch_auto",
    "ensure_action": "batch_auto",
    "recover_action": "batch_auto",
    "app_sequence": "batch_auto",
    "app_workflow": "batch_auto",
    "window_sequence_auto": "batch_auto",
    "window_workflow": "batch_auto",
    "target_sequence": "batch_auto",
    "auto": "batch_auto",
    "smart_auto": "batch_auto",
    "recover": "batch_auto",
    "fallback_action": "batch_auto",
    "batch_repeat": "batch_repeat",
    "batch_until": "batch_repeat",
    "repeat": "batch_repeat",
    "until": "batch_repeat",
    "desktop_find_elements": "desktop_find",
    "desktop_wait_for_element": "desktop_wait",
    "desktop_get_element": "desktop_element",
    "desktop_focus_element": "desktop_focus",
    "desktop_click_element": "desktop_click_index",
    "desktop_click_text_ocr": "desktop_ocr_click",
    "desktop_find_text_ocr": "desktop_ocr_find",
    "desktop_wait_text_ocr": "desktop_ocr_wait",
    "desktop_click_ocr": "desktop_ocr_click",
    "desktop_find_ocr": "desktop_ocr_find",
    "desktop_wait_ocr": "desktop_ocr_wait",
    "desktop_ocr_scroll_click": "desktop_ocr_scroll_click",
    "desktop_scroll_ocr_click": "desktop_ocr_scroll_click",
    "desktop_click_text_ocr_scroll": "desktop_ocr_scroll_click",
    "desktop_click_image": "desktop_image_click",
    "desktop_wait_image": "desktop_image_wait",
    "desktop_image_scroll_click": "desktop_image_scroll_click",
    "desktop_scroll_image_click": "desktop_image_scroll_click",
    "desktop_click_image_scroll": "desktop_image_scroll_click",
    "desktop_pixel_wait": "desktop_pixel_wait",
    "desktop_wait_pixel": "desktop_pixel_wait",
    "wait_desktop_pixel": "desktop_pixel_wait",
    "desktop_visual_stable_wait": "desktop_visual_stable_wait",
    "desktop_wait_visual_stable": "desktop_visual_stable_wait",
    "desktop_visual_wait_stable": "desktop_visual_stable_wait",
    "wait_desktop_visual_stable": "desktop_visual_stable_wait",
    "desktop_uia_stable_wait": "desktop_uia_stable_wait",
    "desktop_wait_uia_stable": "desktop_uia_stable_wait",
    "desktop_uia_wait_stable": "desktop_uia_stable_wait",
    "wait_desktop_uia_stable": "desktop_uia_stable_wait",
    "click_text_ocr": "ocr_click",
    "find_text_ocr": "ocr_find",
    "wait_text_ocr": "ocr_wait",
    "click_ocr": "ocr_click",
    "find_ocr": "ocr_find",
    "wait_ocr": "ocr_wait",
    "ocr_scroll_click": "ocr_scroll_click",
    "scroll_ocr_click": "ocr_scroll_click",
    "click_text_ocr_scroll": "ocr_scroll_click",
    "wait_scroll_text_ocr": "ocr_scroll_click",
    "click_image": "image_click",
    "wait_image": "image_wait",
    "pixel_wait": "pixel_wait",
    "wait_pixel": "pixel_wait",
    "visual_stable_wait": "visual_stable_wait",
    "wait_visual_stable": "visual_stable_wait",
    "visual_wait_stable": "visual_stable_wait",
    "uia_stable_wait": "uia_stable_wait",
    "wait_uia_stable": "uia_stable_wait",
    "uia_wait_stable": "uia_stable_wait",
    "image_scroll_click": "image_scroll_click",
    "scroll_image_click": "image_scroll_click",
    "click_image_scroll": "image_scroll_click",
    "wait_scroll_image": "image_scroll_click",
    "type_foreground": "type_foreground",
    "foreground_type": "type_foreground",
    "type_into_foreground": "type_foreground",
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
    "smart_dialog": "smart_dialog_action",
    "smart_wait_dialog": "smart_dialog_action",
    "smart_wait_dialog_action": "smart_dialog_action",
    "smart_popup": "smart_dialog_action",
    "smart_modal": "smart_dialog_action",
    "dialog_command": "dialog_command_action",
    "dialog_command_action": "dialog_command_action",
    "native_dialog_command": "dialog_command_action",
    "messagebox_command": "dialog_command_action",
    "message_box_command": "dialog_command_action",
    "dialog_button": "dialog_button_action",
    "dialog_button_action": "dialog_button_action",
    "native_dialog_button": "dialog_button_action",
    "messagebox_button": "dialog_button_action",
    "message_box_button": "dialog_button_action",
    "visual_row": "visual_row",
    "visual_row_find": "visual_row",
    "visual_row_click": "visual_row_click",
    "visual_row_scroll": "visual_row_scroll",
    "visual_row_wait": "visual_row_scroll",
    "visual_row_scroll_click": "visual_row_scroll_click",
    "visual_row_wait_click": "visual_row_scroll_click",
    "desktop_move": "desktop_move",
    "desktop_hover": "desktop_move",
    "move_desktop": "desktop_move",
    "hover_desktop": "desktop_move",
    "mouse_context": "mouse_context",
    "cursor_context": "mouse_context",
    "point_context": "mouse_context",
}
_BATCH_LOCAL_COMMAND_TO_PATH = {
    "batch_value": "/batch_value",
    "batch_retry_probe": "/batch_retry_probe",
    "batch_rebinding_probe": "/batch_rebinding_probe",
    "batch_rebind_target_probe": "/batch_rebind_target_probe",
    "batch_repair_plan": "/batch_repair_plan",
    "batch_sleep": "/batch_sleep",
    "batch_try": "/batch_try",
    "batch_auto": "/batch_auto",
    "batch_repeat": "/batch_repeat",
    "auto_window": "/auto_window",
    "window_selector_repair_find": "/window_selector_repair_find",
    "helper_status": "/helper_status",
    "desktop_move": "/desktop_move",
    "mouse_context": "/mouse_context",
    "visual_row": "/visual_row",
    "visual_row_click": "/visual_row_click",
    "visual_row_scroll": "/visual_row_scroll",
    "visual_row_scroll_click": "/visual_row_scroll_click",
    "ocr_scroll_click": "/ocr_scroll_click",
    "desktop_ocr_scroll_click": "/desktop_ocr_scroll_click",
    "image_scroll_click": "/image_scroll_click",
    "desktop_image_scroll_click": "/desktop_image_scroll_click",
    "pixel_wait": "/pixel_wait",
    "desktop_pixel_wait": "/desktop_pixel_wait",
    "visual_stable_wait": "/visual_stable_wait",
    "desktop_visual_stable_wait": "/desktop_visual_stable_wait",
    "uia_stable_wait": "/uia_stable_wait",
    "desktop_uia_stable_wait": "/desktop_uia_stable_wait",
}
_BATCH_LOCAL_PATH_TO_COMMAND = {path: command for command, path in _BATCH_LOCAL_COMMAND_TO_PATH.items()}
_BATCH_TRY_COMMANDS = {"batch_try", "batch-try", "batch_fallback", "batch-fallback", "fallback", "try"}
_BATCH_AUTO_COMMANDS = {"batch_auto", "batch-auto", "batch_auto_action", "batch-auto-action", "auto_action", "auto-action", "auto_control", "auto-control", "app_action", "app-action", "app_control", "app-control", "application_action", "application-action", "window_action_auto", "window-action-auto", "window_control", "window-control", "target_action", "target-action", "ensure_action", "ensure-action", "recover_action", "recover-action", "app_sequence", "app-sequence", "app_workflow", "app-workflow", "window_sequence_auto", "window-sequence-auto", "window_workflow", "window-workflow", "target_sequence", "target-sequence", "auto", "smart_auto", "smart-auto", "recover", "fallback_action", "fallback-action"}
_BATCH_WINDOW_ACTION_COMMANDS = {"app_action", "app-action", "app_control", "app-control", "application_action", "application-action", "window_action_auto", "window-action-auto", "window_control", "window-control", "target_action", "target-action", "ensure_action", "ensure-action", "recover_action", "recover-action"}
_BATCH_WINDOW_SEQUENCE_COMMANDS = {"app_sequence", "app-sequence", "app_workflow", "app-workflow", "window_sequence_auto", "window-sequence-auto", "window_workflow", "window-workflow", "target_sequence", "target-sequence"}
_BATCH_LOOP_COMMANDS = {"batch_repeat", "batch-repeat", "batch_until", "batch-until", "repeat", "until"}
_BATCH_LOCAL_ONLY_ITEM_KEYS = {
    "timeout_budget", "timeout-budget", "deadline_budget", "deadline-budget",
    "on_failure", "on-failure", "on_error", "on-error", "rescue",
    "finally", "always", "cleanup", "trace",
    "recover_on_failure", "recover-on-failure", "recovery_on_failure", "recovery-on-failure",
    "on_failure_recover", "on-failure-recover", "failure_recovery", "failure-recovery",
    "category_recovery", "category-recovery",
    "auto_repair_diagnostics", "auto-repair-diagnostics", "diagnostic_repair", "diagnostic-repair",
    "repair_diagnostics", "repair-diagnostics", "repair_context", "repair-context",
    "diagnostic_repair_context", "diagnostic-repair-context", "repair_limit", "repair-limit",
    "diagnostic_repair_limit", "diagnostic-repair-limit",
    "diagnostic_repair_retry", "diagnostic-repair-retry", "auto_repair_retry", "auto-repair-retry",
    "retry_after_repair", "retry-after-repair", "diagnostic_repair_retry_limit",
    "diagnostic-repair-retry-limit", "repair_retry_limit", "repair-retry-limit",
    "diagnostic_repair_rebind_retry", "diagnostic-repair-rebind-retry", "rebind_retry_after_repair",
    "rebind-retry-after-repair", "repair_rebind_retry", "repair-rebind-retry",
    "diagnostic_repair_rebind_retry_limit", "diagnostic-repair-rebind-retry-limit",
    "rebind_retry_limit", "rebind-retry-limit", "repair_rebind_retry_limit", "repair-rebind-retry-limit",
}


def _normalize_batch_command_name(command_name: Any) -> str:
    text = str(command_name or "").strip()
    if not text:
        return ""
    underscore = text.replace("-", "_")
    if underscore in _HELPER_BATCH_COMMANDS or underscore in _BATCH_COMMAND_TO_PATH:
        return underscore
    return _BATCH_COMMAND_ALIASES.get(underscore, text)


def _normalize_batch_path(path: Any) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    if text in _BATCH_PATH_TO_COMMAND or text in _BATCH_LOCAL_PATH_TO_COMMAND:
        return text
    path_name = text.lstrip("/").replace("-", "_")
    command_name = _normalize_batch_command_name(path_name)
    if command_name in _BATCH_COMMAND_TO_PATH:
        return _BATCH_COMMAND_TO_PATH[command_name]
    if command_name in _BATCH_LOCAL_COMMAND_TO_PATH:
        return _BATCH_LOCAL_COMMAND_TO_PATH[command_name]
    candidate = "/" + path_name
    return candidate if candidate in _BATCH_PATH_TO_COMMAND or candidate in _BATCH_LOCAL_PATH_TO_COMMAND else text


def _batch_command_from_path(path: Any) -> str:
    normalized_path = _normalize_batch_path(path)
    if normalized_path in _BATCH_PATH_TO_COMMAND:
        return _BATCH_PATH_TO_COMMAND[normalized_path]
    if normalized_path in _BATCH_LOCAL_PATH_TO_COMMAND:
        return _BATCH_LOCAL_PATH_TO_COMMAND[normalized_path]
    path_name = str(path or "").strip().lstrip("/").replace("-", "_")
    command_name = _normalize_batch_command_name(path_name)
    return command_name or str(normalized_path or "")


def _batch_item_for_helper(item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(item)
    if "path" in normalized:
        normalized["path"] = _normalize_batch_path(normalized.get("path"))
        if normalized.get("command"):
            normalized["command"] = _normalize_batch_command_name(normalized.get("command"))
        return normalized
    command_name = _normalize_batch_command_name(normalized.get("command", ""))
    if command_name:
        normalized["command"] = command_name
    return normalized


def _can_helper_handle_batch(commands: List[Dict[str, Any]]) -> bool:
    """Return True only when every batch item maps to helper.py endpoints."""
    for item in commands:
        if not isinstance(item, dict):
            return False
        if any(key in item for key in _BATCH_LOCAL_ONLY_ITEM_KEYS):
            return False
        item_args = _batch_item_args(item, use_data=bool(item.get("path") and not item.get("command")))
        if isinstance(item_args, dict) and any(key in item_args for key in _BATCH_LOCAL_ONLY_ITEM_KEYS):
            return False
        if "path" in item:
            path = _normalize_batch_path(item.get("path"))
            if path not in _BATCH_PATH_TO_COMMAND:
                return False
            continue
        command_name = _normalize_batch_command_name(item.get("command", ""))
        if command_name not in _HELPER_BATCH_COMMANDS:
            return False
    return True


def _batch_target_hwnd(commands: List[Dict[str, Any]]) -> Optional[int]:
    for item in commands:
        if not isinstance(item, dict):
            continue
        args = _batch_item_args(item, use_data=bool(item.get("path") and not item.get("command")))
        if not isinstance(args, dict):
            continue
        hwnd = args.get("hwnd")
        if hwnd:
            try:
                return int(hwnd)
            except Exception:
                continue
        command_name = _normalize_batch_command_name(item.get("command", ""))
        path = _normalize_batch_path(item.get("path", ""))
        if command_name in {"file_dialog_info", "file_dialog_action"} or path in {"/file_dialog_info", "/file_dialog_action"}:
            try:
                found = _find_file_dialog(hwnd=None, timeout=0.0)
                if found.get("ok"):
                    return int(((found.get("window") or {}).get("hwnd")) or 0) or None
            except Exception:
                pass
    state = _load_state()
    target = state.get("target_hwnd")
    try:
        return int(target) if target else None
    except Exception:
        return None


def _batch_contains_uia(commands: List[Dict[str, Any]]) -> bool:
    for item in commands:
        if not isinstance(item, dict):
            continue
        if _normalize_batch_command_name(item.get("command")) in _UIA_BATCH_COMMANDS or _normalize_batch_path(item.get("path")) in _UIA_BATCH_PATHS:
            return True
    return False


def _batch_normalize_result(result: Any) -> Dict[str, Any]:
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


def _uia_click_message_result(message: Any, hwnd: Any = None, index: Any = None) -> Dict[str, Any]:
    if isinstance(message, str):
        try:
            decoded = json.loads(message)
            if isinstance(decoded, dict):
                return decoded
        except Exception:
            pass
    text = str(message)
    ok = not text.lower().startswith("error")
    result: Dict[str, Any] = {"ok": ok, "message": message}
    if not ok:
        result["error"] = text.split(":", 1)[1].strip() if ":" in text else text
    if hwnd is not None:
        result["hwnd"] = hwnd
    if index is not None:
        result["index"] = index
    return result


def _batch_normalize_item(item: Dict[str, Any], fallback_index: int) -> Dict[str, Any]:
    normalized = dict(item) if isinstance(item, dict) else {"result": item}
    normalized.setdefault("index", fallback_index)
    normalized["result"] = _batch_normalize_result(normalized.get("result"))
    return {k: v for k, v in normalized.items() if v is not None}


def _batch_invalid_item(index: int, item: Any) -> Dict[str, Any]:
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


def _batch_item_args(item: Dict[str, Any], use_data: bool = False) -> Dict[str, Any]:
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


def _batch_arg_error(args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if "__batch_arg_error__" not in args:
        return None
    return {
        "ok": False,
        "error": "invalid_batch_args",
        "message": str(args.get("__batch_arg_error__") or "args must be a JSON object"),
        "args_type": args.get("__batch_arg_type__"),
    }


def _batch_step_id(item: Dict[str, Any]) -> Optional[str]:
    for key in ("id", "as", "name", "label"):
        value = item.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _batch_find_result_by_id(results: List[Dict[str, Any]], step_id: str) -> Tuple[bool, Any]:
    for item in reversed(results):
        if isinstance(item, dict) and str(item.get("id", "")) == step_id:
            return True, item
    return False, None


def _batch_list_path_value(items: List[Any], part: str) -> Tuple[bool, Any]:
    try:
        return True, items[int(part)]
    except Exception:
        pass
    return _batch_find_result_by_id(items, part)


def _batch_path_parts(path: Any) -> Optional[List[str]]:
    if not isinstance(path, str):
        return None
    text = path.strip()
    if text == "":
        return []
    parts: List[str] = []
    current: List[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == ".":
            if current:
                parts.append("".join(current))
                current = []
            else:
                return None
            i += 1
            continue
        if char != "[":
            current.append(char)
            i += 1
            continue
        if current:
            parts.append("".join(current))
            current = []
        end = text.find("]", i + 1)
        if end < 0:
            return None
        token = text[i + 1:end].strip()
        if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
            token = token[1:-1]
        if token == "":
            return None
        parts.append(token)
        i = end + 1
        if i < len(text) and text[i] == ".":
            i += 1
    if current:
        parts.append("".join(current))
    return parts


def _batch_context_value(path: str, results: List[Dict[str, Any]]) -> Tuple[bool, Any]:
    if path == "$steps":
        return True, results
    if not (path.startswith("$steps.") or path.startswith("$steps[")):
        return False, None
    current: Any = results
    suffix = path[len("$steps"):]
    if suffix.startswith("."):
        suffix = suffix[1:]
    parts = _batch_path_parts(suffix)
    if parts is None:
        return False, None
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
            found, current = _batch_list_path_value(current, part)
            if not found:
                return False, None
        elif isinstance(current, dict):
            if part not in current:
                return False, None
            current = current.get(part)
        else:
            return False, None
    return True, current


def _batch_resolve_refs(value: Any, results: List[Dict[str, Any]]) -> Any:
    if isinstance(value, str):
        found, resolved = _batch_context_value(value, results)
        return resolved if found else value
    if isinstance(value, list):
        return [_batch_resolve_refs(item, results) for item in value]
    if isinstance(value, dict):
        return {key: _batch_resolve_refs(item, results) for key, item in value.items()}
    return value


def _batch_traverse_value(current: Any, path: str) -> Tuple[bool, Any]:
    parts = _batch_path_parts(path)
    if parts is None:
        return False, None
    for part in parts:
        if part == "":
            return False, None
        if isinstance(current, list):
            found, current = _batch_list_path_value(current, part)
            if not found:
                return False, None
        elif isinstance(current, dict):
            if part not in current:
                return False, None
            current = current.get(part)
        else:
            return False, None
    return True, current


def _batch_expect_path_value(path: Any, result: Dict[str, Any], results: List[Dict[str, Any]]) -> Tuple[bool, Any]:
    if not isinstance(path, str):
        return True, path
    if path == "$result":
        return True, result
    if path.startswith("$result.") or path.startswith("$result["):
        suffix = path[len("$result"):]
        if suffix.startswith("."):
            suffix = suffix[1:]
        return _batch_traverse_value(result, suffix)
    if path == "$steps" or path.startswith("$steps.") or path.startswith("$steps["):
        return _batch_context_value(path, results)
    return _batch_traverse_value(result, path)


def _batch_resolve_expect_value(value: Any, result: Dict[str, Any], results: List[Dict[str, Any]]) -> Any:
    if isinstance(value, str) and (
        value == "$result" or value.startswith("$result.") or value.startswith("$result[")
        or value == "$steps" or value.startswith("$steps.") or value.startswith("$steps[")
    ):
        found, resolved = _batch_expect_path_value(value, result, results)
        return resolved if found else value
    if isinstance(value, list):
        return [_batch_resolve_expect_value(item, result, results) for item in value]
    if isinstance(value, dict):
        return {key: _batch_resolve_expect_value(item, result, results) for key, item in value.items()}
    return value


def _batch_diag_value(value: Any) -> Any:
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


def _batch_expect_contains(actual: Any, expected: Any) -> bool:
    try:
        if isinstance(actual, str):
            return str(expected) in actual
        if isinstance(actual, dict):
            return expected in actual or expected in actual.values()
        return expected in actual
    except Exception:
        return False


def _batch_expect_len(value: Any) -> Optional[int]:
    try:
        return len(value)
    except Exception:
        return None


def _batch_expect_number(value: Any) -> float:
    return float(value)


def _batch_expect_contains_all(actual: Any, expected: Any) -> bool:
    values = expected if isinstance(expected, list) else [expected]
    return all(_batch_expect_contains(actual, item) for item in values)


def _batch_expect_contains_any(actual: Any, expected: Any) -> bool:
    values = expected if isinstance(expected, list) else [expected]
    return any(_batch_expect_contains(actual, item) for item in values)


def _batch_expect_type(value: Any) -> str:
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


def _batch_expectation_spec(item: Dict[str, Any]) -> Any:
    for key in ("expect", "expects", "assert", "assertion"):
        if key in item:
            return item.get(key)
    return None


def _batch_evaluate_expectation(expectation: Any, result: Dict[str, Any], results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

    checks: List[Dict[str, Any]] = []
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


def _batch_evaluate_expectations(expectation: Any, result: Dict[str, Any], results: List[Dict[str, Any]]) -> Dict[str, Any]:
    expectations = expectation if isinstance(expectation, list) else [expectation]
    checks: List[Dict[str, Any]] = []
    for item in expectations:
        checks.extend(_batch_evaluate_expectation(item, result, results))
    return {"ok": all(check.get("ok") is True for check in checks), "checks": checks}


def _batch_apply_expectation(result: Dict[str, Any], expectation: Any, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if expectation is None or _batch_result_failure(result):
        return result
    evaluated = _batch_evaluate_expectations(expectation, result, results)
    checked = dict(result)
    checked["expectation"] = evaluated
    if not evaluated.get("ok"):
        checked["ok"] = False
        checked["error"] = "batch_expectation_failed"
    return checked


def _batch_extract_spec(item: Dict[str, Any]) -> Any:
    for key in ("extract", "select", "pick"):
        if key in item:
            return item.get(key)
    return None


def _batch_extract_value(spec: Any, result: Dict[str, Any], results: List[Dict[str, Any]]) -> Tuple[bool, Any, Optional[Dict[str, Any]]]:
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
        extracted: Dict[str, Any] = {}
        for key, path in spec.items():
            ok, value, error = _batch_extract_value(path, result, results)
            if not ok:
                return False, None, {"field": key, **(error or {"error": "extract_failed"})}
            extracted[str(key)] = value
        return True, extracted, None
    return False, None, {"error": "invalid_extract", "extract_type": type(spec).__name__}


def _batch_apply_extract(result: Dict[str, Any], extract: Any, results: List[Dict[str, Any]]) -> Dict[str, Any]:
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


def _batch_condition_spec(item: Dict[str, Any]) -> Tuple[Any, Any]:
    when = item.get("when", item.get("if"))
    unless = item.get("unless", item.get("if_not", item.get("if-not")))
    return when, unless


def _batch_evaluate_condition(condition: Any, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if condition is None:
        return {"ok": True, "checks": []}
    return _batch_evaluate_expectations(condition, {"ok": True}, results)


def _batch_skip_decision(item: Dict[str, Any], results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    when, unless = _batch_condition_spec(item)
    diagnostics: Dict[str, Any] = {}
    if when is not None:
        diagnostics["when"] = _batch_evaluate_condition(when, results)
        if not diagnostics["when"].get("ok"):
            return {"skip_reason": "when_false", "condition": diagnostics}
    if unless is not None:
        diagnostics["unless"] = _batch_evaluate_condition(unless, results)
        if diagnostics["unless"].get("ok"):
            return {"skip_reason": "unless_true", "condition": diagnostics}
    return None


def _batch_retry_options(item: Dict[str, Any]) -> Tuple[int, float]:
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


def _batch_allows_failure(item: Dict[str, Any]) -> bool:
    for key in ("optional", "allow_failure", "allow-failure", "continue_on_error", "continue-on-error", "soft_fail", "soft-fail"):
        if key in item:
            return bool(item.get(key))
    return False


def _batch_step_recovery_spec(item: Dict[str, Any], args: Dict[str, Any]) -> Any:
    keys = (
        "recover_on_failure", "recover-on-failure", "recovery_on_failure", "recovery-on-failure",
        "on_failure_recover", "on-failure-recover", "failure_recovery", "failure-recovery",
        "category_recovery", "category-recovery",
    )
    for key in keys:
        if key in item:
            return item.get(key)
    if isinstance(args, dict):
        for key in keys:
            if key in args:
                return args.get(key)
    return None


def _batch_step_recovery_steps_config(spec: Any, failure: Optional[Dict[str, Any]]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], bool, Optional[Dict[str, Any]]]:
    if spec is None:
        return None, None, True, None
    category = str((failure or {}).get("failure_category") or "")
    retry_original = True
    selected = spec
    selected_key = "direct"
    if isinstance(spec, dict) and not ("steps" in spec or "commands" in spec or "command" in spec or "path" in spec):
        if "retry_original" in spec or "retry-original" in spec:
            retry_original = _coerce_bool(spec.get("retry_original", spec.get("retry-original")), True)
        if category and category in spec:
            selected = spec.get(category)
            selected_key = category
        elif "default" in spec:
            selected = spec.get("default")
            selected_key = "default"
        elif "*" in spec:
            selected = spec.get("*")
            selected_key = "*"
        else:
            return None, None, retry_original, None
        if isinstance(selected, dict) and ("retry_original" in selected or "retry-original" in selected):
            retry_original = _coerce_bool(selected.get("retry_original", selected.get("retry-original")), retry_original)
    steps, stop_on_error, error = _batch_followup_steps_config(selected)
    if error:
        return None, selected_key, retry_original, error
    if isinstance(selected, dict) and ("stop_on_error" in selected or "stop-on-error" in selected):
        stop_on_error = _coerce_bool(selected.get("stop_on_error", selected.get("stop-on-error")), stop_on_error)
    return steps, selected_key, retry_original, None if not steps else {"stop_on_error": stop_on_error}


def _batch_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _batch_option(source: Any, keys: Tuple[str, ...]) -> Any:
    if not isinstance(source, dict):
        return None
    for key in keys:
        if key in source:
            return source.get(key)
    return None


def _batch_deadline_from_value(value: Any, parent_deadline: Optional[float] = None) -> Optional[float]:
    seconds = _batch_float(value)
    if seconds is None:
        return parent_deadline
    deadline = time.perf_counter() + max(seconds, 0.0)
    return min(parent_deadline, deadline) if parent_deadline is not None else deadline


def _batch_deadline_from_sources(item: Any, args: Any, parent_deadline: Optional[float] = None) -> Optional[float]:
    keys = ("timeout_budget", "timeout-budget", "deadline_budget", "deadline-budget")
    value = _batch_option(item, keys)
    if value is None:
        value = _batch_option(args, keys)
    return _batch_deadline_from_value(value, parent_deadline) if value is not None else parent_deadline


def _batch_remaining_seconds(deadline: Optional[float]) -> Optional[float]:
    if deadline is None:
        return None
    return max(deadline - time.perf_counter(), 0.0)


def _batch_deadline_exceeded(deadline: Optional[float]) -> bool:
    return deadline is not None and time.perf_counter() >= deadline


def _batch_timeout_result(scope: str, deadline: Optional[float], **extra: Any) -> Dict[str, Any]:
    result = {
        "ok": False,
        "error": "batch_timeout",
        "message": f"{scope} exceeded timeout_budget",
        "timeout_budget_exceeded": True,
    }
    remaining = _batch_remaining_seconds(deadline)
    if remaining is not None:
        result["remaining_ms"] = round(remaining * 1000.0, 3)
    result.update({k: v for k, v in extra.items() if v is not None})
    return result


def _batch_apply_timeout(result: Dict[str, Any], deadline: Optional[float], scope: str) -> Dict[str, Any]:
    if not _batch_deadline_exceeded(deadline):
        return result
    if isinstance(result, dict) and result.get("error") == "batch_timeout":
        return result
    return _batch_timeout_result(scope, deadline, original_result=result)


def _batch_sleep_with_deadline(delay: float, deadline: Optional[float]) -> bool:
    delay = max(float(delay or 0.0), 0.0)
    if delay <= 0:
        return not _batch_deadline_exceeded(deadline)
    remaining = _batch_remaining_seconds(deadline)
    if remaining is None:
        time.sleep(delay)
        return True
    if remaining <= 0:
        return False
    time.sleep(min(delay, remaining))
    return delay <= remaining and not _batch_deadline_exceeded(deadline)


def _batch_trace_event(trace: Optional[List[Dict[str, Any]]], event: str, **fields: Any) -> None:
    if trace is None:
        return
    entry = {"event": event}
    entry.update({k: v for k, v in fields.items() if v is not None})
    trace.append(entry)


def _batch_timeout_item(index: int, cmd_item: Any, scope: str, deadline: Optional[float]) -> Dict[str, Any]:
    command_name = None
    path = None
    step_id = None
    if isinstance(cmd_item, dict):
        command_name, path, _ = _batch_command_parts(cmd_item)
        step_id = _batch_step_id(cmd_item)
    return {
        "index": index,
        "id": step_id,
        "command": command_name,
        "path": path or None,
        "result": _batch_timeout_result(scope, deadline),
        "attempts": 0,
        "elapsed_ms": 0.0,
    }


def _batch_payload_parts(payload: Any) -> Tuple[Optional[List[Any]], Dict[str, Any], Optional[Dict[str, Any]]]:
    if isinstance(payload, list):
        return payload, {}, None
    if not isinstance(payload, dict):
        return None, {}, {
            "ok": False,
            "error": "invalid_batch_payload",
            "message": "batch payload must be a command list or an object with commands",
            "payload_type": type(payload).__name__,
        }
    commands = payload.get("commands", payload.get("steps"))
    if not isinstance(commands, list):
        return None, {}, {
            "ok": False,
            "error": "invalid_batch_commands",
            "message": "commands must be a list",
            "commands_type": type(commands).__name__,
        }
    options: Dict[str, Any] = {}
    for key in ("stop_on_error", "stop-on-error", "confirmed", "timeout_budget", "timeout-budget", "deadline_budget", "deadline-budget", "on_failure", "on-failure", "on_error", "on-error", "rescue", "finally", "always", "cleanup", "trace", "auto_repair_diagnostics", "auto-repair-diagnostics", "diagnostic_repair", "diagnostic-repair", "repair_diagnostics", "repair-diagnostics", "repair_context", "repair-context", "diagnostic_repair_context", "diagnostic-repair-context", "repair_limit", "repair-limit", "diagnostic_repair_limit", "diagnostic-repair-limit", "diagnostic_repair_retry", "diagnostic-repair-retry", "auto_repair_retry", "auto-repair-retry", "retry_after_repair", "retry-after-repair", "diagnostic_repair_retry_limit", "diagnostic-repair-retry-limit", "repair_retry_limit", "repair-retry-limit", "diagnostic_repair_rebind_retry", "diagnostic-repair-rebind-retry", "rebind_retry_after_repair", "repair_rebind_retry", "repair-rebind-retry", "diagnostic_repair_rebind_retry_limit", "diagnostic-repair-rebind-retry-limit", "rebind_retry_limit", "rebind-retry-limit", "repair_rebind_retry_limit", "repair-rebind-retry-limit"):
        if key in payload:
            options[key] = payload.get(key)
    return commands, options, None


def _batch_stop_on_error_option(options: Dict[str, Any], default: bool = False) -> bool:
    for key in ("stop_on_error", "stop-on-error"):
        if key in options:
            return _coerce_bool(options.get(key), default)
    return bool(default)


def _batch_execute_options(options: Dict[str, Any]) -> Dict[str, Any]:
    execute_options: Dict[str, Any] = {}
    if "confirmed" in options:
        execute_options["confirmed"] = _coerce_bool(options.get("confirmed"), False)
    for key in ("timeout_budget", "timeout-budget", "deadline_budget", "deadline-budget"):
        if key in options:
            execute_options["timeout_budget"] = options.get(key)
            break
    for key in ("on_failure", "on-failure", "on_error", "on-error", "rescue"):
        if key in options:
            execute_options["on_failure"] = options.get(key)
            break
    for key in ("finally", "always", "cleanup"):
        if key in options:
            execute_options["finally_steps"] = options.get(key)
            break
    if "trace" in options:
        execute_options["trace"] = _coerce_bool(options.get("trace"), False)
    for key in ("auto_repair_diagnostics", "auto-repair-diagnostics", "diagnostic_repair", "diagnostic-repair", "repair_diagnostics", "repair-diagnostics"):
        if key in options:
            execute_options["auto_repair_diagnostics"] = _coerce_bool(options.get(key), False)
            break
    for key in ("repair_context", "repair-context", "diagnostic_repair_context", "diagnostic-repair-context"):
        if key in options:
            execute_options["repair_context"] = options.get(key)
            break
    for key in ("repair_limit", "repair-limit", "diagnostic_repair_limit", "diagnostic-repair-limit"):
        if key in options:
            execute_options["repair_limit"] = options.get(key)
            break
    for key in ("diagnostic_repair_retry", "diagnostic-repair-retry", "auto_repair_retry", "auto-repair-retry", "retry_after_repair", "retry-after-repair"):
        if key in options:
            execute_options["diagnostic_repair_retry"] = _coerce_bool(options.get(key), False)
            if execute_options["diagnostic_repair_retry"] and "auto_repair_diagnostics" not in execute_options:
                execute_options["auto_repair_diagnostics"] = True
            break
    for key in ("diagnostic_repair_retry_limit", "diagnostic-repair-retry-limit", "repair_retry_limit", "repair-retry-limit"):
        if key in options:
            execute_options["diagnostic_repair_retry_limit"] = options.get(key)
            break
    for key in ("diagnostic_repair_rebind_retry", "diagnostic-repair-rebind-retry", "rebind_retry_after_repair", "rebind-retry-after-repair", "repair_rebind_retry", "repair-rebind-retry"):
        if key in options:
            execute_options["diagnostic_repair_rebind_retry"] = _coerce_bool(options.get(key), False)
            execute_options["diagnostic_repair_rebind_retry_explicit"] = True
            if execute_options["diagnostic_repair_rebind_retry"] and "auto_repair_diagnostics" not in execute_options:
                execute_options["auto_repair_diagnostics"] = True
            break
    for key in ("diagnostic_repair_rebind_retry_limit", "diagnostic-repair-rebind-retry-limit", "rebind_retry_limit", "rebind-retry-limit", "repair_rebind_retry_limit", "repair-rebind-retry-limit"):
        if key in options:
            execute_options["diagnostic_repair_rebind_retry_limit"] = options.get(key)
            break
    return execute_options


def _batch_auto_rebind_retry_disabled(args: Dict[str, Any]) -> bool:
    if not isinstance(args, dict):
        return False
    for key in (
        "diagnostic_repair_rebind_retry", "diagnostic-repair-rebind-retry",
        "rebind_retry_after_repair", "rebind-retry-after-repair",
        "repair_rebind_retry", "repair-rebind-retry",
    ):
        if key in args:
            return not _coerce_bool(args.get(key), True)
    return False


_BATCH_RECURSIVE_PLAN_KEYS = (
    "branches", "alternatives", "steps", "commands", "candidates",
    "sequence_steps", "sequence-steps", "actions", "tasks", "workflow",
    "workflow_steps", "workflow-steps",
)


_BATCH_NESTED_STEP_SPEC_KEYS = (
    "on_failure", "on-failure", "on_error", "on-error", "rescue",
    "finally", "always", "cleanup",
    "recover_on_failure", "recover-on-failure", "recovery_on_failure", "recovery-on-failure",
    "on_failure_recover", "on-failure-recover", "failure_recovery", "failure-recovery",
    "category_recovery", "category-recovery",
    "sequence_recovery", "sequence-recovery", "recovery", "recover",
    "recovery_steps", "recovery-steps", "recover_steps", "recover-steps",
    "step_recovery", "step-recovery", "on_step_failure", "on-step-failure",
    "on_step_fail", "on-step-fail",
    "post_steps", "post-steps", "after_steps", "after-steps",
    "verify_steps", "verify-steps", "verification_steps", "verification-steps",
)


_BATCH_NESTED_STEP_SPEC_OPTION_KEYS = {
    "retry_original", "retry-original", "stop_on_error", "stop-on-error",
    "description", "reason", "label", "name",
}


def _batch_plan_spec_auto_recover_requested(spec: Any, *, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if isinstance(spec, list):
        return _batch_auto_recover_rebind_retry_requested(spec, depth=depth + 1)
    if not isinstance(spec, dict):
        return False
    if "steps" in spec or "commands" in spec:
        for key in ("steps", "commands"):
            nested = spec.get(key)
            if isinstance(nested, list) and _batch_auto_recover_rebind_retry_requested(nested, depth=depth + 1):
                return True
    if "command" in spec or "path" in spec:
        return _batch_auto_recover_rebind_retry_requested([spec], depth=depth + 1)
    for key, nested in spec.items():
        if str(key) in _BATCH_NESTED_STEP_SPEC_OPTION_KEYS:
            continue
        if _batch_plan_spec_auto_recover_requested(nested, depth=depth + 1):
            return True
    return False


def _batch_mapping_auto_recover_requested(source: Any, *, depth: int = 0) -> bool:
    if not isinstance(source, dict):
        return False
    for key in _BATCH_RECURSIVE_PLAN_KEYS:
        nested = source.get(key)
        if isinstance(nested, list) and _batch_auto_recover_rebind_retry_requested(nested, depth=depth + 1):
            return True
    for key in _BATCH_NESTED_STEP_SPEC_KEYS:
        if key in source and _batch_plan_spec_auto_recover_requested(source.get(key), depth=depth + 1):
            return True
    return False


def _batch_auto_recover_rebind_retry_requested(commands: Any, *, depth: int = 0) -> bool:
    if depth > 8 or not isinstance(commands, list):
        return False
    window_action_kinds = {
        "window_action", "window_control", "app_action", "app_control",
        "application_action", "target_action", "ensure_action", "recover_action",
        "window_sequence", "window_workflow", "app_sequence", "app_workflow",
        "target_sequence", "workflow", "sequence",
    }
    for item in commands:
        if not isinstance(item, dict):
            continue
        command_name, _, args = _batch_command_parts(item)
        item_disabled = _batch_auto_rebind_retry_disabled(item) or _batch_auto_rebind_retry_disabled(args if isinstance(args, dict) else {})
        if not item_disabled:
            if _batch_mapping_auto_recover_requested(item, depth=depth + 1):
                return True
            if _batch_mapping_auto_recover_requested(args, depth=depth + 1):
                return True
        else:
            continue
        command_key = str(command_name or "").strip().lower().replace("-", "_")
        if command_key not in {name.replace("-", "_") for name in _BATCH_AUTO_COMMANDS}:
            continue
        if not isinstance(args, dict) or "__batch_arg_error__" in args:
            continue
        normalized_args = _batch_auto_normalize_args(args)
        kind = _batch_auto_kind(item, normalized_args)
        if kind not in window_action_kinds:
            continue
        if _batch_auto_rebind_retry_disabled(args) or _batch_auto_rebind_retry_disabled(normalized_args):
            continue
        if _batch_auto_recover_enabled(normalized_args):
            return True
    return False


def _batch_followup_spec(item: Dict[str, Any], args: Dict[str, Any], kind: str) -> Any:
    if kind == "on_failure":
        keys = ("on_failure", "on-failure", "on_error", "on-error", "rescue")
    else:
        keys = ("finally", "always", "cleanup")
    for key in keys:
        if key in item:
            return item.get(key)
    if isinstance(args, dict):
        for key in keys:
            if key in args:
                return args.get(key)
    return None


def _batch_followup_steps_config(spec: Any) -> Tuple[Optional[List[Dict[str, Any]]], bool, Optional[Dict[str, Any]]]:
    if spec is None:
        return None, False, None
    if isinstance(spec, list):
        return spec, False, None
    if isinstance(spec, dict) and ("steps" in spec or "commands" in spec):
        steps = spec.get("steps", spec.get("commands"))
        if not isinstance(steps, list):
            return None, False, {"ok": False, "error": "invalid_batch_followup", "message": "followup steps/commands must be a list"}
        stop_on_error = _coerce_bool(spec.get("stop_on_error", spec.get("stop-on-error", False)), False)
        return steps, stop_on_error, None
    if isinstance(spec, dict):
        return [spec], False, None
    return None, False, {"ok": False, "error": "invalid_batch_followup", "followup_type": type(spec).__name__}


def _batch_run_followup_steps(label: str, spec: Any, context: List[Dict[str, Any]], deadline: Optional[float], trace: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    steps, stop_on_error, error = _batch_followup_steps_config(spec)
    if error:
        return error
    if not steps:
        return None
    _batch_trace_event(trace, "followup_start", label=label, count=len(steps))
    local_context = list(context)
    followup_results: List[Dict[str, Any]] = []
    stopped_on_error = False
    for step in steps:
        if _batch_deadline_exceeded(deadline):
            item = _batch_timeout_item(len(local_context), step, f"{label} followup", deadline)
        else:
            item = _batch_execute_step_item(len(local_context), step, local_context, deadline=deadline, trace=trace, allow_followups=False)
        followup_results.append(item)
        local_context.append(item)
        if _batch_result_failure(item.get("result")):
            stopped_on_error = True
            if stop_on_error:
                break
    summary = _batch_summary(followup_results, total_count=len(steps), stopped_on_error=stopped_on_error)
    _batch_trace_event(trace, "followup_end", label=label, ok=summary.get("ok"), failed_count=summary.get("failed_count"))
    return {"ok": summary.get("ok"), "summary": summary, "results": followup_results}


def _batch_command_parts(item: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    command_name = _normalize_batch_command_name(item.get("command", ""))
    args = _batch_item_args(item)
    path = _normalize_batch_path(item.get("path", ""))
    if not command_name and "path" in item:
        command_name = _batch_command_from_path(path)
        args = _batch_item_args(item, use_data=True)
    return str(command_name or ""), str(path or ""), args


def _batch_supplied_diagnostic_summary(cmd_item: Any, args: Any) -> Dict[str, Any]:
    for source in (args, cmd_item):
        if not isinstance(source, dict):
            continue
        for key in ("diagnostic_summary", "diagnostics", "diagnostic"):
            value = source.get(key)
            if isinstance(value, dict) and value:
                return copy.deepcopy(value)
    return {}


def _batch_attach_supplied_diagnostics(result: Any, cmd_item: Any, args: Any, command: str = "") -> Any:
    if not isinstance(result, dict) or not _batch_result_failure(result, command=command):
        return result
    supplied = _batch_supplied_diagnostic_summary(cmd_item, args)
    if not supplied:
        return result
    patched = copy.deepcopy(result)
    existing = patched.get("diagnostic_summary") if isinstance(patched.get("diagnostic_summary"), dict) else {}
    merged = copy.deepcopy(supplied)
    if existing:
        merged.update(existing)
    patched["diagnostic_summary"] = merged
    return patched


def _batch_try_branches(item: Dict[str, Any], args: Dict[str, Any]) -> Any:
    if isinstance(args, dict) and "__batch_arg_error__" in args:
        return None
    for key in ("branches", "alternatives", "candidates", "steps", "commands"):
        if key in item:
            return item.get(key)
    if isinstance(args, dict):
        for key in ("branches", "alternatives", "candidates", "steps", "commands"):
            if key in args:
                return args.get(key)
    return None


def _batch_branch_steps(branch: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], Optional[str]]:
    if isinstance(branch, list):
        return branch, None, None
    if isinstance(branch, dict) and ("steps" in branch or "commands" in branch):
        steps = branch.get("steps", branch.get("commands"))
        branch_id = _batch_step_id(branch)
        description = branch.get("description") or branch.get("reason")
        return steps if isinstance(steps, list) else None, branch_id, description
    if isinstance(branch, dict):
        return [branch], _batch_step_id(branch), branch.get("description") or branch.get("reason")
    return None, None, None


def _batch_try_success_item(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    selected = None
    for item in items:
        result = item.get("result") if isinstance(item, dict) else None
        if not isinstance(result, dict) or result.get("skipped"):
            continue
        if result.get("tolerated_failure"):
            selected = selected or item
            continue
        selected = item
    return selected


def _batch_try_branch_succeeded(items: List[Dict[str, Any]], summary: Dict[str, Any]) -> bool:
    if not summary.get("ok") or not items:
        return False
    selected = _batch_try_success_item(items)
    if not selected:
        return False
    result = selected.get("result") if isinstance(selected, dict) else None
    return not (isinstance(result, dict) and result.get("tolerated_failure"))


def _batch_compact_dict_list(items: Any, keys: Tuple[str, ...], *, limit: int = 4) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return compacted
    for item in items:
        if not isinstance(item, dict):
            continue
        compact = {
            key: item.get(key)
            for key in keys
            if item.get(key) not in (None, "", [], {})
        }
        suggestion = item.get("selector_suggestion")
        if isinstance(suggestion, dict) and suggestion and "selector_suggestion" not in compact:
            compact["selector_suggestion"] = {
                key: suggestion.get(key)
                for key in ("automation_id", "control_type", "class_name", "name", "match")
                if suggestion.get(key) not in (None, "", [], {})
            }
            if not compact["selector_suggestion"]:
                compact.pop("selector_suggestion", None)
        if compact and compact not in compacted:
            compacted.append(compact)
        if len(compacted) >= limit:
            break
    return compacted


def _batch_compact_repair_payload(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "hwnd", "index", "automation_id", "control_type", "class_name",
        "name", "value", "pattern", "match", "state", "expected", "text",
        "target_text", "target_index", "title", "window_title", "process",
        "process_name", "pid", "reason",
    )
    return {
        key: value.get(key)
        for key in keys
        if value.get(key) not in (None, "", [], {})
    }


def _batch_append_repair_candidate(candidates: List[Dict[str, Any]], candidate: Dict[str, Any], *, limit: int = 8) -> None:
    if len(candidates) >= limit or not isinstance(candidate, dict):
        return
    compact = {
        key: candidate.get(key)
        for key in (
            "kind", "layer", "command", "source", "branch_id", "step_id", "hwnd",
            "step_command", "state", "target_text", "target_index", "match",
            "reason",
        )
        if candidate.get(key) not in (None, "", [], {})
    }
    for nested_key in ("suggestion", "repair_suggestion"):
        nested = _batch_compact_repair_payload(candidate.get(nested_key))
        if nested:
            compact[nested_key] = nested
    if compact and compact not in candidates:
        candidates.append(compact)


def _batch_repair_step_id(candidate: Dict[str, Any], index: int) -> str:
    raw = candidate.get("step_id") or candidate.get("branch_id") or candidate.get("kind") or "repair"
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", str(raw or "repair")).strip("_").lower()
    if not text:
        text = "repair"
    if not text.endswith("_repair"):
        text = f"{text}_repair"
    return f"{text}_{index + 1}"


def _batch_repair_candidate_hwnd(candidate: Dict[str, Any], suggestion: Dict[str, Any], step_id: Optional[Any]) -> Tuple[Any, List[str]]:
    for source in (candidate, suggestion):
        if isinstance(source, dict) and source.get("hwnd") not in (None, "", [], {}):
            return source.get("hwnd"), []
    if step_id not in (None, "", [], {}):
        return f"$steps.{step_id}.result.hwnd", []
    return None, ["hwnd"]


def _batch_repair_candidate_step(candidate: Any, index: int = 0) -> Dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    kind = str(candidate.get("kind") or "").strip().lower()
    command = str(candidate.get("command") or "").strip()
    suggestion = candidate.get("suggestion") if isinstance(candidate.get("suggestion"), dict) else {}
    repair_suggestion = candidate.get("repair_suggestion") if isinstance(candidate.get("repair_suggestion"), dict) else {}
    step_id = candidate.get("step_id")
    requires: List[str] = []
    args: Dict[str, Any] = {}

    if kind == "uia_selector_repair" or command == "uia_selector_repair_find":
        hwnd, missing = _batch_repair_candidate_hwnd(candidate, suggestion, step_id)
        requires.extend(missing)
        args = {
            "suggestion": suggestion,
            "limit": 1,
        }
        if hwnd is not None:
            args["hwnd"] = hwnd
        if suggestion.get("view") not in (None, "", [], {}):
            args["view"] = suggestion.get("view")
        command = "uia_selector_repair_find"
    elif kind == "native_selector_repair" or command == "win32_selector_repair_find":
        hwnd, missing = _batch_repair_candidate_hwnd(candidate, suggestion, step_id)
        requires.extend(missing)
        args = {
            "suggestion": suggestion,
            "limit": 1,
            "diagnostic": True,
        }
        if hwnd is not None:
            args["hwnd"] = hwnd
        command = "win32_selector_repair_find"
    elif kind == "native_wait_repair" or command == "win32_control_wait":
        hwnd, missing = _batch_repair_candidate_hwnd(candidate, repair_suggestion, step_id)
        requires.extend(missing)
        args = {
            "state": repair_suggestion.get("state", candidate.get("state")),
            "expected": repair_suggestion.get("expected", candidate.get("expected", True)),
            "match": repair_suggestion.get("match", candidate.get("match", "contains")),
            "timeout": repair_suggestion.get("timeout", candidate.get("timeout", 1.0)),
            "diagnostic": True,
            "repair": False,
        }
        text_value = repair_suggestion.get("text", repair_suggestion.get("target_text", candidate.get("target_text")))
        index_value = repair_suggestion.get("index", repair_suggestion.get("target_index", candidate.get("target_index")))
        if text_value not in (None, "", [], {}):
            args["text"] = text_value
        if index_value not in (None, "", [], {}):
            args["index"] = index_value
        if hwnd is not None:
            args["hwnd"] = hwnd
        command = "win32_control_wait"
    elif kind == "window_selector_repair" or command == "window_selector_repair_find":
        args = {
            "suggestion": suggestion,
            "probe_original": False,
        }
        if candidate.get("timeout") not in (None, "", [], {}):
            args["timeout"] = candidate.get("timeout")
        command = "window_selector_repair_find"
    else:
        return {}

    args = {key: value for key, value in args.items() if value not in (None, "", [], {})}
    step = {
        "id": _batch_repair_step_id(candidate, index),
        "command": command,
        "args": args,
        "description": candidate.get("reason") or "retry from diagnostic repair candidate",
        "repair_candidate": {
            key: candidate.get(key)
            for key in ("kind", "layer", "source", "branch_id", "step_id", "step_command")
            if candidate.get(key) not in (None, "", [], {})
        },
    }
    if requires:
        step["requires"] = requires
        step["ready"] = False
    else:
        step["ready"] = True
    return step


def _batch_repair_candidate_steps(candidates: Any, *, limit: int = 8) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    if not isinstance(candidates, list):
        return steps
    for candidate in candidates:
        step = _batch_repair_candidate_step(candidate, len(steps))
        if step and step not in steps:
            steps.append(step)
        if len(steps) >= limit:
            break
    return steps


def _batch_repair_plan_payload(args: Dict[str, Any]) -> Any:
    for key in (
        "diagnostic", "diagnostics", "diagnostic_summary", "summary",
        "failure", "failure_summary", "result", "payload", "value",
    ):
        if key in args:
            return args.get(key)
    return args


def _batch_repair_plan_context(args: Dict[str, Any]) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    for key in ("context", "fill", "fills", "defaults"):
        value = args.get(key)
        if isinstance(value, dict):
            context.update({k: v for k, v in value.items() if v not in (None, "", [], {})})
    for key in ("hwnd", "window_hwnd", "window-hwnd", "target_hwnd", "target-hwnd"):
        if args.get(key) not in (None, "", [], {}):
            context["hwnd"] = args.get(key)
            break
    for key in ("view", "timeout", "timeout_budget", "timeout-budget"):
        if args.get(key) not in (None, "", [], {}):
            context[key.replace("-", "_")] = args.get(key)
    return context


def _batch_repair_plan_contains_step_ref(value: Any) -> bool:
    if isinstance(value, str):
        return "$steps." in value
    if isinstance(value, dict):
        return any(_batch_repair_plan_contains_step_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_batch_repair_plan_contains_step_ref(item) for item in value)
    return False


def _batch_repair_plan_add_unique(target: List[Dict[str, Any]], step: Any, *, limit: int) -> None:
    if len(target) >= limit or not isinstance(step, dict) or not step:
        return
    if step not in target:
        target.append(copy.deepcopy(step))


def _batch_repair_plan_collect(payload: Any, candidates: List[Dict[str, Any]], steps: List[Dict[str, Any]], *, limit: int, depth: int = 0) -> None:
    if depth > 8 or len(steps) >= limit * 2 and len(candidates) >= limit * 2:
        return
    if isinstance(payload, list):
        for item in payload:
            _batch_repair_plan_collect(item, candidates, steps, limit=limit, depth=depth + 1)
            if len(steps) >= limit * 2 and len(candidates) >= limit * 2:
                break
        return
    if not isinstance(payload, dict):
        return

    for step in payload.get("next_repair_steps") or payload.get("repair_steps") or []:
        _batch_repair_plan_add_unique(steps, step, limit=limit * 2)

    direct_candidates = payload.get("next_repair_candidates")
    if direct_candidates is None:
        direct_candidates = payload.get("repair_candidates")
    if isinstance(direct_candidates, list):
        for candidate in direct_candidates:
            if isinstance(candidate, dict):
                _batch_append_repair_candidate(candidates, candidate, limit=limit * 2)

    generated_steps = _batch_repair_candidate_steps(direct_candidates, limit=limit * 2) if isinstance(direct_candidates, list) else []
    for step in generated_steps:
        _batch_repair_plan_add_unique(steps, step, limit=limit * 2)

    if isinstance(payload.get("results"), list):
        for item in payload.get("results") or []:
            _batch_repair_plan_collect(item, candidates, steps, limit=limit, depth=depth + 1)
            if len(steps) >= limit * 2 and len(candidates) >= limit * 2:
                break
        try:
            branch_summary = _batch_branch_diagnostic_summary({"results": payload.get("results")})
        except Exception:
            branch_summary = {}
        if branch_summary:
            _batch_repair_plan_collect(branch_summary, candidates, steps, limit=limit, depth=depth + 1)

    for key in (
        "diagnostic_summary", "failure_summary", "selected", "summary",
        "result", "value", "original_result", "original_result_diagnostic",
    ):
        nested = payload.get(key)
        if isinstance(nested, (dict, list)):
            _batch_repair_plan_collect(nested, candidates, steps, limit=limit, depth=depth + 1)

    for report in payload.get("branches") or payload.get("candidates") or []:
        if isinstance(report, dict):
            _batch_repair_plan_collect(report, candidates, steps, limit=limit, depth=depth + 1)


def _batch_repair_plan_prepare_step(step: Dict[str, Any], context: Dict[str, Any], *, allow_step_refs: bool) -> Dict[str, Any]:
    prepared = copy.deepcopy(step)
    args = prepared.get("args")
    if not isinstance(args, dict):
        args = {}
        prepared["args"] = args

    requires = [str(item) for item in prepared.get("requires") or [] if item not in (None, "", [], {})]
    still_missing: List[str] = []
    for requirement in requires:
        key = requirement.replace("-", "_")
        context_value = context.get(key)
        if context_value is None and key == "hwnd":
            context_value = context.get("window_hwnd", context.get("target_hwnd"))
        if context_value not in (None, "", [], {}):
            args[key] = context_value
        else:
            still_missing.append(requirement)

    uses_step_refs = _batch_repair_plan_contains_step_ref(args)
    if uses_step_refs:
        prepared["uses_step_refs"] = True
        if not allow_step_refs and "original_batch_context" not in still_missing:
            still_missing.append("original_batch_context")

    prepared["ready"] = not bool(still_missing)
    prepared["portable_ready"] = prepared["ready"] and not uses_step_refs
    if still_missing:
        prepared["requires"] = still_missing
    else:
        prepared.pop("requires", None)
    return prepared


def _batch_repair_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    payload = _batch_repair_plan_payload(args)
    try:
        limit = max(1, int(args.get("limit", 8)))
    except Exception:
        limit = 8
    include_pending = _coerce_bool(args.get("include_pending", args.get("include-pending", True)), True)
    allow_step_refs = _coerce_bool(args.get("allow_step_refs", args.get("allow-step-refs", False)), False)
    as_try = _coerce_bool(args.get("as_try", args.get("as-try", True)), True)
    context = _batch_repair_plan_context(args)

    candidates: List[Dict[str, Any]] = []
    raw_steps: List[Dict[str, Any]] = []
    _batch_repair_plan_collect(payload, candidates, raw_steps, limit=limit)
    for step in _batch_repair_candidate_steps(candidates, limit=limit * 2):
        _batch_repair_plan_add_unique(raw_steps, step, limit=limit * 2)

    prepared_steps: List[Dict[str, Any]] = []
    for raw_step in raw_steps:
        prepared = _batch_repair_plan_prepare_step(raw_step, context, allow_step_refs=allow_step_refs)
        if prepared and prepared not in prepared_steps:
            prepared_steps.append(prepared)
        if len(prepared_steps) >= limit:
            break

    ready_steps = [step for step in prepared_steps if step.get("ready") is True]
    pending_steps = [step for step in prepared_steps if step.get("ready") is not True]
    selected_steps = ready_steps if not include_pending else prepared_steps

    try_step: Optional[Dict[str, Any]] = None
    if as_try and len(ready_steps) > 1:
        try_step = {
            "id": "diagnostic_repair_try",
            "command": "batch_try",
            "branches": [
                {
                    "id": step.get("id") or f"repair_{index + 1}",
                    "description": step.get("description"),
                    "steps": [step],
                }
                for index, step in enumerate(ready_steps)
            ],
        }

    batch_commands = [try_step] if try_step else ready_steps
    result = {
        "ok": bool(prepared_steps),
        "planned": bool(prepared_steps),
        "ready": bool(ready_steps),
        "count": len(prepared_steps),
        "ready_count": len(ready_steps),
        "pending_count": len(pending_steps),
        "candidates": candidates[:limit],
        "steps": selected_steps[:limit],
        "ready_steps": ready_steps[:limit],
        "pending_steps": pending_steps[:limit],
        "batch": {"commands": batch_commands, "stop_on_error": True},
    }
    if try_step:
        result["try_step"] = try_step
    if context:
        result["context_applied"] = context
    if not prepared_steps:
        result["error"] = "no_repair_steps"
        result["message"] = "No next_repair_steps or next_repair_candidates were found in the supplied diagnostic payload"
    elif not ready_steps:
        result["message"] = "Repair steps were found, but all require missing fields before execution"
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _batch_native_control_find_diagnostic_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    failure_summary = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
    matches = result.get("matches") if isinstance(result.get("matches"), list) else []
    near_matches = result.get("near_matches") if isinstance(result.get("near_matches"), list) else []
    filtered = result.get("filtered_candidates") if isinstance(result.get("filtered_candidates"), list) else []
    native_markers = bool(
        matches
        or near_matches
        or filtered
        or result.get("total_candidates") is not None
        or result.get("available_candidates") is not None
        or result.get("filtered_candidates") is not None
        or failure_summary.get("near_count") is not None
        or failure_summary.get("matched_before_min_score") is not None
        or failure_summary.get("observed_kinds")
    )
    if not native_markers:
        return {}
    sample_native_items = matches or near_matches or filtered
    if result.get("view") is not None and not any(isinstance(item, dict) and item.get("hwnd") for item in sample_native_items):
        return {}
    if not (failure_summary or matches or near_matches or filtered):
        return {}

    summary: Dict[str, Any] = {}
    if result.get("hwnd") not in (None, "", [], {}):
        summary["hwnd"] = result.get("hwnd")
    compact_match_keys = (
        "hwnd", "control_id", "automation_id", "kind", "class_name", "name",
        "text", "value", "selector_score", "checked", "selected", "enabled", "visible",
    )
    if matches:
        summary["matched_count"] = len(matches)
        summary["matches"] = _batch_compact_dict_list(matches, compact_match_keys, limit=4)
    if near_matches:
        summary["near_count"] = len(near_matches)
        summary["near_matches"] = _batch_compact_dict_list(near_matches, compact_match_keys, limit=4)
    if filtered:
        summary["filtered_count"] = len(filtered)
        summary["filtered_candidates"] = _batch_compact_dict_list(filtered, compact_match_keys, limit=4)
    if failure_summary:
        for key in ("scanned", "matched_before_min_score", "miss_counts", "observed_kinds", "observed_classes", "recommendations"):
            if failure_summary.get(key) not in (None, "", [], {}):
                summary[key] = failure_summary.get(key)
        suggestions = failure_summary.get("selector_suggestions")
        if isinstance(suggestions, list) and suggestions:
            summary["selector_repair_available"] = True
            summary["selector_suggestion_count"] = len(suggestions)
            summary["selector_suggestions"] = _batch_compact_dict_list(
                suggestions,
                ("automation_id", "control_type", "class_name", "name", "match"),
                limit=5,
            )
    return {k: v for k, v in summary.items() if v not in (None, "", [], {})}


def _batch_native_control_wait_diagnostic_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    failure_summary = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
    native_markers = bool(
        result.get("state") is not None
        and (
            result.get("matched") is not None
            or result.get("present") is not None
            or failure_summary.get("item_count") is not None
            or failure_summary.get("kind") is not None
            or failure_summary.get("item_preview")
        )
    )
    if not native_markers:
        return {}
    source = failure_summary or result
    summary = {
        key: source.get(key)
        for key in (
            "state", "expected", "actual", "present", "target", "target_text",
            "target_index", "match", "kind", "class_name", "control_id",
            "item_count", "reported_count", "max_items", "item_preview",
            "repair_suggestions", "recommendations",
        )
        if source.get(key) not in (None, "", [], {})
    }
    for key in ("hwnd", "error", "attempts", "elapsed"):
        if result.get(key) not in (None, "", [], {}):
            summary.setdefault(key, result.get(key))
    if result.get("last_result") and isinstance(result.get("last_result"), dict):
        compact_last = {
            key: result.get("last_result", {}).get(key)
            for key in ("state", "expected", "actual", "present", "target", "error")
            if result.get("last_result", {}).get(key) not in (None, "", [], {})
        }
        if compact_last:
            summary["last_result"] = compact_last
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _batch_uia_find_diagnostic_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    if result.get("view") is None and not result.get("desktop") and "focused" not in result and "focused_element" not in result:
        return {}
    failure_summary = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
    matches = result.get("matches") if isinstance(result.get("matches"), list) else []
    near_matches = result.get("near_matches") if isinstance(result.get("near_matches"), list) else []
    if not (failure_summary or matches or near_matches):
        return {}
    compact_keys = (
        "index", "name", "automation_id", "control_type", "class_name",
        "value", "selector_score", "enabled", "visible",
    )
    summary: Dict[str, Any] = {}
    if result.get("hwnd") not in (None, "", [], {}):
        summary["hwnd"] = result.get("hwnd")
    if result.get("view") not in (None, "", [], {}):
        summary["view"] = result.get("view")
    if result.get("scanned") not in (None, "", [], {}):
        summary["scanned"] = result.get("scanned")
    if matches:
        summary["matched_count"] = len(matches)
        summary["matches"] = _batch_compact_dict_list(matches, compact_keys, limit=4)
    if near_matches:
        summary["near_count"] = len(near_matches)
        summary["near_matches"] = _batch_compact_dict_list(near_matches, compact_keys, limit=4)
    if failure_summary:
        for key in ("miss_counts", "observed_control_types", "observed_classes", "recommendations"):
            if failure_summary.get(key) not in (None, "", [], {}):
                summary[key] = failure_summary.get(key)
        suggestions = failure_summary.get("selector_suggestions")
        if isinstance(suggestions, list) and suggestions:
            summary["selector_repair_available"] = True
            summary["selector_suggestion_count"] = len(suggestions)
            summary["selector_suggestions"] = _batch_compact_dict_list(
                suggestions,
                ("index", "automation_id", "control_type", "class_name", "name", "value", "pattern", "match"),
                limit=5,
            )
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _batch_result_diagnostic_summary(result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    summary: Dict[str, Any] = {}
    value = result.get("value")
    if isinstance(value, dict):
        nested = _batch_result_diagnostic_summary(value)
        if nested:
            summary.update(nested)
    original_result = result.get("original_result")
    if isinstance(original_result, dict):
        original_summary = _batch_result_diagnostic_summary(original_result)
        if original_summary:
            for key in ("native_control_find", "native_control_wait", "uia_find", "failure_summary", "failure_categories", "recommendations"):
                if key in original_summary and key not in summary:
                    summary[key] = original_summary.get(key)
            original_compact = {
                key: original_summary.get(key)
                for key in ("native_control_find", "native_control_wait", "uia_find", "failure_summary", "failure_categories", "recommendations")
                if original_summary.get(key) not in (None, "", [], {})
            }
            if original_compact:
                summary["original_result_diagnostic"] = original_compact
    existing_diagnostics = result.get("diagnostic_summary") if isinstance(result.get("diagnostic_summary"), dict) else {}
    if existing_diagnostics:
        if existing_diagnostics.get("relocated") is True:
            summary["relocated"] = True
        for key in ("relocation", "last_uia_relocation"):
            if isinstance(existing_diagnostics.get(key), dict):
                summary[key] = dict(existing_diagnostics.get(key) or {})
        if existing_diagnostics.get("uia_relocation_count"):
            summary["uia_relocation_count"] = existing_diagnostics.get("uia_relocation_count")
        selected = existing_diagnostics.get("selected")
        if isinstance(selected, dict):
            compact_selected = {
                key: selected.get(key)
                for key in ("index", "id", "selected", "relocated", "uia_relocation_count")
                if selected.get(key) not in (None, "", [], {})
            }
            for key in ("relocation", "last_uia_relocation"):
                if isinstance(selected.get(key), dict):
                    compact_selected[key] = dict(selected.get(key) or {})
            if compact_selected:
                summary["selected"] = compact_selected
        for key in ("failure_categories", "recommendations"):
            if isinstance(existing_diagnostics.get(key), list):
                summary[key] = list(existing_diagnostics.get(key) or [])
    if result.get("relocated") is True:
        summary["relocated"] = True
    relocation = result.get("relocation")
    if isinstance(relocation, dict):
        summary["relocated"] = True
        summary["relocation"] = dict(relocation)
    clipboard_payload = _batch_clipboard_restore_payload(result)
    if clipboard_payload is None and isinstance(result.get("value"), dict):
        clipboard_payload = _batch_clipboard_restore_payload(result.get("value"))
    if clipboard_payload is not None:
        clipboard_summary = {
            key: clipboard_payload.get(key)
            for key in (
                "clipboard_saved",
                "clipboard_saved_formats",
                "clipboard_skipped_formats",
                "clipboard_restore_attempted",
                "clipboard_restore_ok",
                "clipboard_restored_formats",
                "clipboard_restore_error",
                "clipboard_restore_failures",
                "clipboard_restore_skipped_formats",
            )
            if clipboard_payload.get(key) not in (None, "", [], {})
        }
        clipboard_summary["failure_category"] = "clipboard_restore"
        summary["clipboard_restore"] = clipboard_summary
    failure_summary = result.get("failure_summary") if isinstance(result.get("failure_summary"), dict) else {}
    if failure_summary:
        compact_failure = {
            key: failure_summary.get(key)
            for key in (
                "last_failure_category",
                "last_error",
                "last_uia_error",
                "last_win32_error",
                "last_focus_error",
                "terminal_uia_error",
                "uia_relocation_count",
                "last_uia_relocation",
                "coordinate_fallback_attempted",
                "failed_methods",
                "visible_window_count",
                "usable_window_count",
                "matched_candidate_count",
                "miss_counts",
                "observed_control_types",
                "observed_classes",
                "observed_processes",
                "observed_titles",
                "selector_suggestions",
                "uia_selector_repair_available",
                "uia_selector_suggestion_count",
                "recommendations",
            )
            if failure_summary.get(key) not in (None, "", [], {})
        }
        if compact_failure:
            summary["failure_summary"] = compact_failure
        smart_uia_suggestions = failure_summary.get("selector_suggestions")
        if (
            isinstance(smart_uia_suggestions, list)
            and smart_uia_suggestions
            and (failure_summary.get("uia_find_count") or failure_summary.get("uia_selector_repair_available"))
        ):
            uia_find = summary.setdefault("uia_find", {})
            for key in ("miss_counts", "observed_control_types", "observed_classes", "recommendations"):
                if failure_summary.get(key) not in (None, "", [], {}) and key not in uia_find:
                    uia_find[key] = failure_summary.get(key)
            uia_find["selector_repair_available"] = True
            uia_find["selector_suggestion_count"] = failure_summary.get("uia_selector_suggestion_count") or len(smart_uia_suggestions)
            uia_find["selector_suggestions"] = _batch_compact_dict_list(
                smart_uia_suggestions,
                ("index", "automation_id", "control_type", "class_name", "name", "value", "pattern", "match"),
                limit=5,
            )
        if failure_summary.get("uia_relocation_count"):
            summary["uia_relocation_count"] = failure_summary.get("uia_relocation_count")
            if isinstance(failure_summary.get("last_uia_relocation"), dict):
                summary["last_uia_relocation"] = dict(failure_summary.get("last_uia_relocation") or {})
    native_find_summary = _batch_native_control_find_diagnostic_summary(result)
    if native_find_summary:
        summary["native_control_find"] = native_find_summary
    native_wait_summary = _batch_native_control_wait_diagnostic_summary(result)
    if native_wait_summary:
        summary["native_control_wait"] = native_wait_summary
    uia_find_summary = _batch_uia_find_diagnostic_summary(result)
    if uia_find_summary:
        summary["uia_find"] = uia_find_summary
    if isinstance(result.get("near_windows"), list) or (
        failure_summary
        and (
            failure_summary.get("observed_processes")
            or failure_summary.get("observed_titles")
            or failure_summary.get("visible_window_count") is not None
            or failure_summary.get("usable_window_count") is not None
            or failure_summary.get("matched_candidate_count") is not None
        )
    ):
        window_find: Dict[str, Any] = {}
        if isinstance(result.get("near_windows"), list):
            window_find["near_windows"] = _batch_compact_dict_list(
                result.get("near_windows"),
                ("hwnd", "title", "pid", "process_name", "process_path", "selector_score", "stable_count"),
                limit=5,
            )
        for key in (
            "visible_window_count", "usable_window_count", "matched_candidate_count",
            "miss_counts", "observed_processes", "observed_titles",
            "selector_suggestions", "recommendations",
        ):
            if failure_summary.get(key) not in (None, "", [], {}):
                window_find[key] = failure_summary.get(key)
        if window_find:
            summary["window_find"] = window_find
    for key in ("method", "error", "helper", "helper_elevated", "smart_action_worker", "view"):
        if result.get(key) not in (None, "", [], {}):
            summary[key] = result.get(key)
    return summary


def _batch_item_diagnostic_summary(item: Any) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    result = item.get("result")
    summary = _batch_result_diagnostic_summary(result)
    if summary:
        for key in ("id", "command", "path", "index"):
            if item.get(key) not in (None, "", [], {}):
                summary.setdefault(key, item.get(key))
    return summary


def _batch_branch_diagnostic_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    details: Dict[str, Any] = {}
    branch_id = report.get("id")
    relocated_steps: List[Dict[str, Any]] = []
    native_find_steps: List[Dict[str, Any]] = []
    native_wait_steps: List[Dict[str, Any]] = []
    native_selector_suggestions: List[Dict[str, Any]] = []
    uia_find_steps: List[Dict[str, Any]] = []
    uia_selector_suggestions: List[Dict[str, Any]] = []
    window_find_steps: List[Dict[str, Any]] = []
    window_selector_suggestions: List[Dict[str, Any]] = []
    clipboard_restore_steps: List[Dict[str, Any]] = []
    repair_candidates: List[Dict[str, Any]] = []
    failure_categories: List[str] = []
    recommendations: List[str] = []
    last_relocation: Optional[Dict[str, Any]] = None
    uia_relocation_count = 0
    for item in report.get("results") or []:
        item_summary = _batch_item_diagnostic_summary(item)
        if not item_summary:
            continue
        if item_summary.get("relocated") or item_summary.get("relocation") or item_summary.get("last_uia_relocation"):
            relocated_steps.append(item_summary)
        relocation = item_summary.get("relocation") or item_summary.get("last_uia_relocation")
        if isinstance(relocation, dict):
            last_relocation = dict(relocation)
        try:
            uia_relocation_count += int(item_summary.get("uia_relocation_count") or (1 if item_summary.get("relocated") else 0))
        except Exception:
            pass
        failure_summary = item_summary.get("failure_summary") if isinstance(item_summary.get("failure_summary"), dict) else {}
        category = failure_summary.get("last_failure_category")
        if category:
            _batch_auto_plan_unique_append(failure_categories, category)
        for recommendation in failure_summary.get("recommendations") or []:
            _batch_auto_plan_unique_append(recommendations, recommendation)
        clipboard_restore = item_summary.get("clipboard_restore") if isinstance(item_summary.get("clipboard_restore"), dict) else {}
        if clipboard_restore:
            compact_clipboard = dict(clipboard_restore)
            for key in ("id", "command", "path", "index"):
                if item_summary.get(key) not in (None, "", [], {}):
                    compact_clipboard.setdefault(key, item_summary.get(key))
            clipboard_restore_steps.append(compact_clipboard)
            _batch_auto_plan_unique_append(failure_categories, "clipboard_restore")
            for recommendation in _batch_failure_recommendations("clipboard_restore"):
                _batch_auto_plan_unique_append(recommendations, recommendation)
        native_find = item_summary.get("native_control_find") if isinstance(item_summary.get("native_control_find"), dict) else {}
        if native_find:
            compact_native = {
                key: native_find.get(key)
                for key in (
                    "hwnd", "matched_count", "near_count", "filtered_count", "scanned",
                    "matched_before_min_score", "miss_counts", "observed_kinds",
                    "observed_classes", "selector_repair_available",
                    "selector_suggestion_count", "matches", "near_matches",
                    "selector_suggestions", "recommendations",
                )
                if native_find.get(key) not in (None, "", [], {})
            }
            for key in ("id", "command", "path", "index"):
                if item_summary.get(key) not in (None, "", [], {}):
                    compact_native.setdefault(key, item_summary.get(key))
            if compact_native:
                native_find_steps.append(compact_native)
            for suggestion in native_find.get("selector_suggestions") or []:
                if isinstance(suggestion, dict) and suggestion and suggestion not in native_selector_suggestions:
                    native_selector_suggestions.append(suggestion)
                    _batch_append_repair_candidate(repair_candidates, {
                        "kind": "native_selector_repair",
                        "layer": "native",
                        "command": "win32_selector_repair_find",
                        "source": "native_control_find",
                        "branch_id": branch_id,
                        "step_id": item_summary.get("id"),
                        "hwnd": native_find.get("hwnd"),
                        "step_command": item_summary.get("command"),
                        "suggestion": suggestion,
                        "reason": "retry native child lookup with failure_summary.selector_suggestions[0]",
                    })
            for recommendation in native_find.get("recommendations") or []:
                _batch_auto_plan_unique_append(recommendations, recommendation)
        native_wait = item_summary.get("native_control_wait") if isinstance(item_summary.get("native_control_wait"), dict) else {}
        if native_wait:
            compact_wait = {
                key: native_wait.get(key)
                for key in (
                    "hwnd", "state", "expected", "actual", "present", "target", "target_text",
                    "target_index", "match", "kind", "class_name", "control_id",
                    "item_count", "reported_count", "max_items", "item_preview",
                    "repair_suggestions", "last_result", "recommendations",
                )
                if native_wait.get(key) not in (None, "", [], {})
            }
            for key in ("id", "command", "path", "index"):
                if item_summary.get(key) not in (None, "", [], {}):
                    compact_wait.setdefault(key, item_summary.get(key))
            if compact_wait:
                native_wait_steps.append(compact_wait)
            for suggestion in native_wait.get("repair_suggestions") or []:
                if isinstance(suggestion, dict) and suggestion:
                    _batch_append_repair_candidate(repair_candidates, {
                        "kind": "native_wait_repair",
                        "layer": "native",
                        "command": "win32_control_wait",
                        "source": "native_control_wait",
                        "branch_id": branch_id,
                        "step_id": item_summary.get("id"),
                        "hwnd": native_wait.get("hwnd"),
                        "step_command": item_summary.get("command"),
                        "state": native_wait.get("state"),
                        "target_text": native_wait.get("target_text"),
                        "target_index": native_wait.get("target_index"),
                        "match": native_wait.get("match"),
                        "repair_suggestion": suggestion,
                        "reason": "retry native wait with repair_suggestions[0]",
                    })
            for recommendation in native_wait.get("recommendations") or []:
                _batch_auto_plan_unique_append(recommendations, recommendation)
        uia_find = item_summary.get("uia_find") if isinstance(item_summary.get("uia_find"), dict) else {}
        if uia_find:
            compact_uia = {
                key: uia_find.get(key)
                for key in (
                    "hwnd", "view", "scanned", "matched_count", "near_count", "miss_counts",
                    "observed_control_types", "observed_classes",
                    "selector_repair_available", "selector_suggestion_count",
                    "matches", "near_matches", "selector_suggestions", "recommendations",
                )
                if uia_find.get(key) not in (None, "", [], {})
            }
            for key in ("id", "command", "path", "index"):
                if item_summary.get(key) not in (None, "", [], {}):
                    compact_uia.setdefault(key, item_summary.get(key))
            if compact_uia:
                uia_find_steps.append(compact_uia)
            for suggestion in uia_find.get("selector_suggestions") or []:
                if isinstance(suggestion, dict) and suggestion and suggestion not in uia_selector_suggestions:
                    uia_selector_suggestions.append(suggestion)
                    _batch_append_repair_candidate(repair_candidates, {
                        "kind": "uia_selector_repair",
                        "layer": "semantic",
                        "command": "uia_selector_repair_find",
                        "source": "uia_find",
                        "branch_id": branch_id,
                        "step_id": item_summary.get("id"),
                        "hwnd": uia_find.get("hwnd"),
                        "step_command": item_summary.get("command"),
                        "suggestion": suggestion,
                        "reason": "retry UIA lookup with failure_summary.selector_suggestions[0]",
                    })
            for recommendation in uia_find.get("recommendations") or []:
                _batch_auto_plan_unique_append(recommendations, recommendation)
        window_find = item_summary.get("window_find") if isinstance(item_summary.get("window_find"), dict) else {}
        if window_find:
            compact_window = {
                key: window_find.get(key)
                for key in (
                    "visible_window_count", "usable_window_count", "matched_candidate_count",
                    "miss_counts", "observed_processes", "observed_titles",
                    "selector_suggestions", "near_windows", "recommendations",
                )
                if window_find.get(key) not in (None, "", [], {})
            }
            for key in ("id", "command", "path", "index"):
                if item_summary.get(key) not in (None, "", [], {}):
                    compact_window.setdefault(key, item_summary.get(key))
            if compact_window:
                window_find_steps.append(compact_window)
            for suggestion in window_find.get("selector_suggestions") or []:
                if isinstance(suggestion, dict) and suggestion and suggestion not in window_selector_suggestions:
                    window_selector_suggestions.append(suggestion)
                    _batch_append_repair_candidate(repair_candidates, {
                        "kind": "window_selector_repair",
                        "layer": "native",
                        "command": "window_selector_repair_find",
                        "source": "window_find",
                        "branch_id": branch_id,
                        "step_id": item_summary.get("id"),
                        "step_command": item_summary.get("command"),
                        "suggestion": suggestion,
                        "reason": "retry window acquisition with failure_summary.selector_suggestions[0]",
                    })
            for recommendation in window_find.get("recommendations") or []:
                _batch_auto_plan_unique_append(recommendations, recommendation)
    if relocated_steps:
        details["relocated"] = True
        details["relocated_steps"] = relocated_steps[:8]
    if native_find_steps:
        details["native_control_find"] = native_find_steps[:8]
    if native_wait_steps:
        details["native_control_wait"] = native_wait_steps[:8]
    if native_selector_suggestions:
        details["native_selector_repair_available"] = True
        details["native_selector_suggestions"] = native_selector_suggestions[:8]
    if uia_find_steps:
        details["uia_find"] = uia_find_steps[:8]
    if uia_selector_suggestions:
        details["uia_selector_repair_available"] = True
        details["uia_selector_suggestions"] = uia_selector_suggestions[:8]
    if window_find_steps:
        details["window_find"] = window_find_steps[:8]
    if window_selector_suggestions:
        details["window_selector_repair_available"] = True
        details["window_selector_suggestions"] = window_selector_suggestions[:8]
    if clipboard_restore_steps:
        details["clipboard_restore"] = clipboard_restore_steps[:8]
    if repair_candidates:
        details["next_repair_candidates"] = repair_candidates[:8]
        repair_steps = _batch_repair_candidate_steps(repair_candidates, limit=8)
        if repair_steps:
            details["next_repair_steps"] = repair_steps
    if last_relocation:
        details["last_uia_relocation"] = last_relocation
    if uia_relocation_count:
        details["uia_relocation_count"] = uia_relocation_count
    if failure_categories:
        details["failure_categories"] = failure_categories
    if recommendations:
        details["recommendations"] = recommendations
    return details




def _batch_result_failure(result: Any, command: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(result, dict):
        result = _batch_normalize_result(result)
    if _batch_clipboard_restore_incomplete(result):
        error = _batch_clipboard_restore_error_text(result)
        return {"error": error, **_batch_failure_details(error, command=command, result=result)}
    if "error" in result:
        error = str(result.get("error") or "error")
        return {"error": error, **_batch_failure_details(error, command=command, result=result)}
    if result.get("ok") is False:
        error = str(result.get("message") or result.get("reason") or "ok_false")
        return {"error": error, **_batch_failure_details(error, command=command, result=result)}
    return None


def _batch_execute_command_core(command_name: str, cmd_item: Dict[str, Any], args: Dict[str, Any], results: List[Dict[str, Any]], step_deadline: Optional[float], trace: Optional[List[Dict[str, Any]]], expectation: Any, extract: Any) -> Dict[str, Any]:
    if _batch_deadline_exceeded(step_deadline):
        r = _batch_timeout_result("batch step", step_deadline)
    elif command_name in _BATCH_AUTO_COMMANDS:
        r = _batch_normalize_result(_batch_execute_auto_command(cmd_item, args, results, deadline=step_deadline, trace=trace))
    elif command_name in _BATCH_TRY_COMMANDS:
        r = _batch_normalize_result(_batch_execute_try_command(cmd_item, args, results, deadline=step_deadline, trace=trace))
    elif command_name in _BATCH_LOOP_COMMANDS:
        r = _batch_normalize_result(_batch_execute_loop_command(cmd_item, args, results, deadline=step_deadline, trace=trace))
    else:
        r = _batch_normalize_result(_batch_execute_local(command_name, args))
    r = _batch_apply_expectation(r, expectation, results)
    r = _batch_apply_extract(r, extract, results)
    return _batch_apply_timeout(r, step_deadline, "batch step")


def _batch_auto_repair_limit(value: Any, default: int = 4) -> int:
    try:
        return max(1, min(int(value), 16))
    except Exception:
        return default


def _batch_diagnostic_retry_limit(value: Any, default: int = 1) -> int:
    try:
        return max(1, min(int(value), 8))
    except Exception:
        return default


def _batch_auto_repair_context(repair_context: Any, commands: List[Dict[str, Any]]) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    if isinstance(repair_context, dict):
        context.update({k: v for k, v in repair_context.items() if v not in (None, "", [], {})})
    if context.get("hwnd") in (None, "", [], {}):
        target_hwnd = _batch_target_hwnd(commands)
        if target_hwnd:
            context["hwnd"] = target_hwnd
    return context


def _batch_compact_repair_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    compact = {
        "ok": plan.get("ok"),
        "planned": plan.get("planned"),
        "ready": plan.get("ready"),
        "count": plan.get("count"),
        "ready_count": plan.get("ready_count"),
        "pending_count": plan.get("pending_count"),
        "ready_steps": plan.get("ready_steps"),
        "pending_steps": plan.get("pending_steps"),
        "batch": plan.get("batch"),
        "message": plan.get("message"),
        "error": plan.get("error"),
        "context_applied": plan.get("context_applied"),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _batch_int_or_none(value: Any) -> Optional[int]:
    try:
        if value in (None, "", [], {}):
            return None
        return int(value)
    except Exception:
        return None


def _batch_compact_repair_match(match: Any, keys: Tuple[str, ...]) -> Dict[str, Any]:
    if not isinstance(match, dict):
        return {}
    compact = {
        key: match.get(key)
        for key in keys
        if match.get(key) not in (None, "", [], {})
    }
    suggestion = match.get("selector_suggestion")
    if isinstance(suggestion, dict) and suggestion:
        compact["selector_suggestion"] = {
            key: suggestion.get(key)
            for key in ("index", "hwnd", "automation_id", "control_id", "control_type", "kind", "class_name", "name", "value", "pattern", "match")
            if suggestion.get(key) not in (None, "", [], {})
        }
    return compact


def _batch_rebinding_key(key: Tuple[Any, ...]) -> Tuple[Any, ...]:
    safe: List[Any] = []
    for item in key:
        if isinstance(item, (str, int, float, bool, type(None))):
            safe.append(item)
        else:
            safe.append(repr(item))
    return tuple(safe)


def _batch_rebinding_entry(key: Tuple[Any, ...], payload: Dict[str, Any], seen: set) -> Optional[Dict[str, Any]]:
    safe_key = _batch_rebinding_key(key)
    if not payload or safe_key in seen:
        return None
    seen.add(safe_key)
    return {item_key: item_value for item_key, item_value in payload.items() if item_value not in (None, "", [], {})}


def _batch_repair_result_rebinding(result: Any, *, source_item: Optional[Dict[str, Any]] = None, seen: Optional[set] = None) -> List[Dict[str, Any]]:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return []
    seen = seen if seen is not None else set()
    source_item = source_item if isinstance(source_item, dict) else {}
    base_source = {
        "source_id": source_item.get("id"),
        "source_command": source_item.get("command"),
        "source_path": source_item.get("path"),
        "source_index": source_item.get("index"),
    }
    entries: List[Dict[str, Any]] = []

    if result.get("window_selector_repair") and isinstance(result.get("window"), dict):
        window = result.get("window") or {}
        hwnd = _batch_int_or_none(result.get("target_hwnd") or result.get("hwnd") or window.get("hwnd"))
        entry = _batch_rebinding_entry(
            ("window", hwnd),
            {
                **base_source,
                "kind": "window",
                "layer": "window",
                "hwnd": hwnd,
                "target_hwnd": hwnd,
                "selector": result.get("selector"),
                "suggestion": result.get("suggestion"),
                "window": _compact_window_info(window),
                "rebound": result.get("rebound"),
            },
            seen,
        )
        if entry:
            entries.append(entry)

    if result.get("selector_repair") and (result.get("native_selector_repair") or result.get("suggestion_hwnd_fallback")):
        matches = result.get("matches") if isinstance(result.get("matches"), list) else []
        for match in matches[:4]:
            if not isinstance(match, dict):
                continue
            child_hwnd = _batch_int_or_none(match.get("hwnd"))
            parent_hwnd = _batch_int_or_none(result.get("hwnd") or match.get("parent_hwnd") or match.get("root_hwnd"))
            entry = _batch_rebinding_entry(
                ("native", parent_hwnd, child_hwnd, match.get("control_id")),
                {
                    **base_source,
                    "kind": "native_control",
                    "layer": "native",
                    "hwnd": parent_hwnd,
                    "child_hwnd": child_hwnd,
                    "selector": result.get("selector"),
                    "suggestion": result.get("suggestion"),
                    "match": _batch_compact_repair_match(
                        match,
                        (
                            "hwnd", "control_id", "automation_id", "kind", "control_type", "class_name",
                            "name", "text", "value", "rect", "selector_score", "checked", "selected",
                            "enabled", "visible",
                        ),
                    ),
                },
                seen,
            )
            if entry:
                entries.append(entry)

    if result.get("selector_repair") and not result.get("native_selector_repair") and not result.get("window_selector_repair"):
        matches = result.get("matches") if isinstance(result.get("matches"), list) else []
        for match in matches[:4]:
            if not isinstance(match, dict):
                continue
            index = _batch_int_or_none(match.get("index"))
            hwnd = _batch_int_or_none(result.get("hwnd"))
            view = result.get("view") or match.get("uia_view") or match.get("view")
            kind = "uia_cell" if result.get("cell_selector_repair") else "uia_element"
            entry = _batch_rebinding_entry(
                (kind, hwnd, view, index, match.get("automation_id"), match.get("name")),
                {
                    **base_source,
                    "kind": kind,
                    "layer": "semantic",
                    "hwnd": hwnd,
                    "index": index,
                    "view": view,
                    "selector": result.get("selector"),
                    "suggestion": result.get("suggestion"),
                    "cell": result.get("cell"),
                    "match": _batch_compact_repair_match(
                        match,
                        (
                            "index", "automation_id", "control_type", "class_name", "name", "value",
                            "pattern", "patterns", "rect", "selector_score", "enabled", "visible",
                            "row", "column", "row_text", "column_name",
                        ),
                    ),
                },
                seen,
            )
            if entry:
                entries.append(entry)

    if result.get("repaired") and result.get("repair") and result.get("matched"):
        entry = _batch_rebinding_entry(
            ("native_wait", result.get("hwnd"), result.get("state"), result.get("text"), result.get("match")),
            {
                **base_source,
                "kind": "native_wait",
                "layer": "native",
                "hwnd": _batch_int_or_none(result.get("hwnd")),
                "state": result.get("state"),
                "expected": result.get("expected"),
                "text": result.get("text"),
                "index": result.get("index"),
                "match": result.get("match"),
                "repair": result.get("repair"),
            },
            seen,
        )
        if entry:
            entries.append(entry)

    return entries


def _batch_collect_rebindings(payload: Any, *, limit: int = 12, seen: Optional[set] = None, source_item: Optional[Dict[str, Any]] = None, depth: int = 0) -> List[Dict[str, Any]]:
    if depth > 10 or limit <= 0:
        return []
    seen = seen if seen is not None else set()
    entries: List[Dict[str, Any]] = []

    def add_many(items: List[Dict[str, Any]]) -> None:
        for item in items:
            if item and len(entries) < limit:
                entries.append(item)

    if isinstance(payload, list):
        for item in payload:
            add_many(_batch_collect_rebindings(item, limit=limit - len(entries), seen=seen, source_item=source_item, depth=depth + 1))
            if len(entries) >= limit:
                break
        return entries
    if not isinstance(payload, dict):
        return entries

    item_source = source_item
    if "result" in payload and any(key in payload for key in ("id", "command", "path", "index")):
        item_source = payload
        add_many(_batch_collect_rebindings(payload.get("result"), limit=limit - len(entries), seen=seen, source_item=item_source, depth=depth + 1))
    else:
        add_many(_batch_repair_result_rebinding(payload, source_item=item_source, seen=seen))

    for key in ("result", "selected_result", "value", "retry", "diagnostic_repair"):
        if len(entries) >= limit:
            break
        nested = payload.get(key)
        if isinstance(nested, (dict, list)):
            add_many(_batch_collect_rebindings(nested, limit=limit - len(entries), seen=seen, source_item=item_source, depth=depth + 1))
    for key in ("results", "candidates", "branches"):
        if len(entries) >= limit:
            break
        nested_list = payload.get(key)
        if isinstance(nested_list, list):
            add_many(_batch_collect_rebindings(nested_list, limit=limit - len(entries), seen=seen, source_item=item_source, depth=depth + 1))
    return entries


def _batch_failed_step_indexes(batch_result: Dict[str, Any], commands: List[Dict[str, Any]], limit: int) -> List[int]:
    indexes: List[int] = []
    for failure in batch_result.get("failures") or []:
        if not isinstance(failure, dict):
            continue
        try:
            index = int(failure.get("index"))
        except Exception:
            continue
        if 0 <= index < len(commands) and index not in indexes:
            indexes.append(index)
        if len(indexes) >= limit:
            return indexes
    for item in batch_result.get("results") or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except Exception:
            continue
        if 0 <= index < len(commands) and index not in indexes and _batch_result_failure(item.get("result"), command=item.get("command")):
            indexes.append(index)
        if len(indexes) >= limit:
            break
    return indexes


def _batch_retry_failed_steps_after_repair(
    batch_result: Dict[str, Any],
    commands: List[Dict[str, Any]],
    *,
    retry_limit: Any = 1,
    deadline: Optional[float] = None,
    trace: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    limit = _batch_diagnostic_retry_limit(retry_limit)
    indexes = _batch_failed_step_indexes(batch_result, commands, limit)
    retry_report: Dict[str, Any] = {
        "enabled": True,
        "executed": False,
        "requested_limit": limit,
        "indexes": indexes,
    }
    if not indexes:
        retry_report["reason"] = "no_failed_steps_to_retry"
        return retry_report
    if _batch_deadline_exceeded(deadline):
        retry_report["reason"] = "batch_timeout"
        retry_report["summary"] = _batch_summary([], total_count=len(indexes), stopped_on_error=True)
        return retry_report

    retry_results: List[Dict[str, Any]] = []
    retry_context = list(batch_result.get("results") or [])
    _batch_trace_event(trace, "diagnostic_repair_retry_start", count=len(indexes), indexes=indexes)
    for index in indexes:
        if _batch_deadline_exceeded(deadline):
            retry_results.append(_batch_timeout_item(index, commands[index], "diagnostic repair retry", deadline))
            break
        retry_item = _batch_execute_step_item(index, commands[index], retry_context, deadline=deadline, trace=trace, allow_followups=False)
        retry_item["retry_of_index"] = index
        retry_results.append(retry_item)
        retry_context.append(retry_item)
    summary = _batch_summary(retry_results, total_count=len(indexes), stopped_on_error=bool(_batch_deadline_exceeded(deadline)))
    _batch_trace_event(trace, "diagnostic_repair_retry_end", ok=summary.get("ok"), failed_count=summary.get("failed_count"), count=len(retry_results))
    retry_report.update({
        "executed": True,
        "ok": bool(summary.get("ok")),
        "summary": summary,
        "results": retry_results,
    })
    return retry_report


def _batch_rebind_retry_limit(value: Any, default: int = 1) -> int:
    try:
        return max(1, min(int(value), 8))
    except Exception:
        return default


def _batch_auto_rebinding_kind(command: str, args: Dict[str, Any]) -> str:
    if command not in _BATCH_AUTO_COMMANDS or not isinstance(args, dict):
        return ""
    try:
        return str(_batch_auto_kind({"command": command}, args) or "").strip().lower().replace("-", "_")
    except Exception:
        return str(args.get("kind") or "").strip().lower().replace("-", "_")


def _batch_auto_rebinding_layers(layers: Any) -> List[str]:
    if layers is None:
        return []
    if isinstance(layers, str):
        values = [part.strip().lower().replace("-", "_") for part in re.split(r"[,|\s]+", layers) if part.strip()]
    elif isinstance(layers, (list, tuple, set)):
        values = [str(part).strip().lower().replace("-", "_") for part in layers if str(part).strip()]
    else:
        return []
    aliases = {
        "semantic": {"semantic", "uia", "smart", "dialog", "popup", "modal"},
        "native": {"native", "win32"},
        "msaa": {"msaa", "accessible", "legacy"},
        "visual": {"visual", "ocr", "image"},
        "input": {"input", "raw", "keyboard", "mouse", "coordinate", "coords"},
    }
    normalized: List[str] = []
    for value in values:
        canonical = next((name for name, names in aliases.items() if value in names), value)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _batch_auto_rebinding_native_only(args: Dict[str, Any]) -> bool:
    if not isinstance(args, dict) or args.get("layers") in (None, "", [], {}):
        return False
    layers = _batch_auto_rebinding_layers(args.get("layers"))
    return bool(layers) and set(layers).issubset({"native"}) and "native" in layers


def _batch_rebinding_matches_step(rebinding: Dict[str, Any], command_name: str, args: Dict[str, Any]) -> bool:
    kind = str(rebinding.get("kind") or "").strip().lower()
    command = str(command_name or "").strip().lower()
    if not kind or not command:
        return False
    arg_kind = str(args.get("kind", "")).lower().replace("-", "_") if isinstance(args, dict) else ""
    auto_kind = _batch_auto_rebinding_kind(command, args)
    if kind == "window":
        if command in _BATCH_AUTO_COMMANDS:
            return auto_kind in {
                "click", "invoke", "press", "button", "check", "uncheck",
                "text", "input", "type", "set_text", "write", "value",
                "select", "selection", "choose", "item", "cell", "grid",
                "table", "row", "dialog", "popup", "modal", "messagebox",
                "message_box", "prompt", "key", "keys", "shortcut", "hotkey",
                "keyboard", "scroll", "wheel", "drag", "mouse_drag", "menu",
                "hmenu", "file_dialog", "window", "app", "application", "target",
                "window_action", "window_control", "app_action", "app_control",
                "application_action", "target_action", "window_sequence",
                "app_sequence", "app_workflow", "target_sequence", "workflow",
                "sequence",
            }
        return command in {
            "activate", "auto_window", "wait_window", "window_action", "focus_hwnd",
            "smart_click", "smart_wait_click", "smart_text", "smart_wait_text",
            "smart_select", "smart_wait_select", "smart_cell", "smart_wait_cell",
            "key", "scroll", "drag", "click", "type",
            "batch_rebind_target_probe", "batch-rebind-target-probe",
        } and arg_kind in ("", "window", "window_selector")
    if kind in ("uia_element", "uia_cell"):
        if command in _BATCH_AUTO_COMMANDS:
            return auto_kind in {
                "click", "invoke", "press", "button", "check", "uncheck",
                "text", "input", "type", "set_text", "write", "value",
                "select", "selection", "choose", "item", "cell", "grid",
                "table", "row", "dialog", "popup", "modal", "messagebox",
                "message_box", "prompt", "window_action", "window_control",
                "app_action", "app_control", "application_action", "target_action",
                "window_sequence", "app_sequence", "app_workflow", "target_sequence",
                "workflow", "sequence",
            }
        return command in {
            "uia_click_index", "uia_action", "uia_set_value", "uia_element", "uia_focus",
            "smart_click", "smart_wait_click", "smart_text", "smart_wait_text",
            "smart_select", "smart_wait_select", "smart_cell", "smart_wait_cell",
            "batch_rebind_target_probe", "batch-rebind-target-probe",
        } and arg_kind in ("", "uia", "uia_element", "uia_cell", "cell")
    if kind == "native_control":
        if command in _BATCH_AUTO_COMMANDS:
            return _batch_auto_rebinding_native_only(args) and auto_kind in {
                "click", "invoke", "press", "button", "check", "uncheck",
                "text", "input", "type", "set_text", "write", "value",
                "select", "selection", "choose", "item", "cell", "grid",
                "table", "row",
            }
        return command in {
            "win32_text", "win32_set_text", "win32_click", "win32_control_info",
            "win32_control_action", "win32_control_wait",
            "batch_rebind_target_probe", "batch-rebind-target-probe",
        } and arg_kind in ("", "native", "win32", "native_selector", "win32_selector")
    if kind == "native_wait":
        return command in {"win32_control_wait", "batch_rebind_target_probe", "batch-rebind-target-probe"} and arg_kind in ("", "native_wait", "win32_wait")
    return False


def _batch_rebinding_patch_args(args: Dict[str, Any], rebinding: Dict[str, Any]) -> Dict[str, Any]:
    patched = copy.deepcopy(args) if isinstance(args, dict) else {}
    kind = str(rebinding.get("kind") or "").strip().lower()
    if kind == "window":
        hwnd = rebinding.get("target_hwnd", rebinding.get("hwnd"))
        if hwnd not in (None, "", [], {}):
            patched["hwnd"] = hwnd
    elif kind in ("uia_element", "uia_cell"):
        for key in ("hwnd", "index", "view"):
            if rebinding.get(key) not in (None, "", [], {}):
                patched[key] = rebinding.get(key)
        if kind == "uia_cell" and isinstance(rebinding.get("cell"), dict):
            for key in ("row", "column", "row_text", "column_name"):
                if rebinding["cell"].get(key) not in (None, "", [], {}):
                    patched[key] = rebinding["cell"].get(key)
    elif kind == "native_control":
        child_hwnd = rebinding.get("child_hwnd") or ((rebinding.get("match") or {}).get("hwnd") if isinstance(rebinding.get("match"), dict) else None)
        if child_hwnd not in (None, "", [], {}):
            patched["hwnd"] = child_hwnd
    elif kind == "native_wait":
        for key in ("hwnd", "state", "expected", "text", "index", "match"):
            if rebinding.get(key) not in (None, "", [], {}):
                patched[key] = rebinding.get(key)
        repair = rebinding.get("repair") if isinstance(rebinding.get("repair"), dict) else {}
        if repair.get("match") not in (None, "", [], {}) and patched.get("match") in (None, "", [], {}):
            patched["match"] = repair.get("match")
    return patched


def _batch_rebinding_set_item_args(item: Dict[str, Any], path: str, patched_args: Dict[str, Any]) -> None:
    if path and "path" in item and "data" in item and "args" not in item:
        item["data"] = patched_args
    else:
        item["args"] = patched_args


def _batch_rebinding_args_preview(args: Any) -> Dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    preview: Dict[str, Any] = {}
    for key in (
        "hwnd", "index", "view", "state", "expected", "text", "match",
        "row", "column", "row_text", "column_name",
    ):
        value = args.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (str, int, float, bool)):
            preview[key] = value
        elif isinstance(value, (list, tuple)):
            preview[key] = list(value[:6])
        elif isinstance(value, dict):
            preview[key] = {
                item_key: item_value
                for item_key, item_value in value.items()
                if item_value not in (None, "", [], {})
            }
    return preview


def _batch_rebinding_changed_keys(before: Any, after: Any) -> List[str]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    changed: List[str] = []
    for key in sorted(set(before.keys()) | set(after.keys())):
        if before.get(key) != after.get(key):
            changed.append(str(key))
    return changed[:16]


def _batch_rebinding_patch_record(
    item_path: str,
    command_name: str,
    endpoint_path: str,
    item: Dict[str, Any],
    before_args: Dict[str, Any],
    patched_args: Dict[str, Any],
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "item_path": item_path or "$",
        "command": command_name,
        "changed_keys": _batch_rebinding_changed_keys(before_args, patched_args),
        "args_preview": _batch_rebinding_args_preview(patched_args),
    }
    step_id = _batch_step_id(item)
    if step_id:
        record["id"] = step_id
    if endpoint_path:
        record["endpoint"] = endpoint_path
    return {key: value for key, value in record.items() if value not in (None, "", [], {})}


def _batch_rebinding_patch_step_spec(value: Any, rebinding: Dict[str, Any], item_path: str) -> Tuple[Any, List[Dict[str, Any]]]:
    if isinstance(value, list):
        return _batch_rebinding_patch_item_tree(value, rebinding, item_path)
    if not isinstance(value, dict):
        return value, []
    if "steps" in value or "commands" in value or "command" in value or "path" in value:
        return _batch_rebinding_patch_item_tree(value, rebinding, item_path)

    patched = copy.deepcopy(value)
    patch_records: List[Dict[str, Any]] = []
    for key, nested in list(patched.items()):
        if str(key) in _BATCH_NESTED_STEP_SPEC_OPTION_KEYS:
            continue
        patched_nested, nested_records = _batch_rebinding_patch_step_spec(nested, rebinding, f"{item_path}.{key}")
        if nested_records:
            patched[key] = patched_nested
            patch_records.extend(nested_records)
    return patched, patch_records


def _batch_rebinding_patch_nested_step_specs(patched: Dict[str, Any], rebinding: Dict[str, Any], item_path: str) -> List[Dict[str, Any]]:
    patch_records: List[Dict[str, Any]] = []
    for key in _BATCH_NESTED_STEP_SPEC_KEYS:
        if key not in patched:
            continue
        patched_nested, nested_records = _batch_rebinding_patch_step_spec(patched.get(key), rebinding, f"{item_path}.{key}")
        if nested_records:
            patched[key] = patched_nested
            patch_records.extend(nested_records)
    return patch_records


def _batch_rebinding_patch_item_tree(value: Any, rebinding: Dict[str, Any], item_path: str = "$") -> Tuple[Any, List[Dict[str, Any]]]:
    if isinstance(value, list):
        patched_items = []
        patch_records: List[Dict[str, Any]] = []
        for offset, item in enumerate(value):
            patched_item, item_records = _batch_rebinding_patch_item_tree(item, rebinding, f"{item_path}[{offset}]")
            patched_items.append(patched_item)
            patch_records.extend(item_records)
        return patched_items, patch_records
    if not isinstance(value, dict):
        return value, []

    patched = copy.deepcopy(value)
    patch_records: List[Dict[str, Any]] = []
    command_name, path, args = _batch_command_parts(patched)
    if command_name and _batch_rebinding_matches_step(rebinding, command_name, args):
        patched_args = _batch_rebinding_patch_args(args, rebinding)
        _batch_rebinding_set_item_args(patched, path, patched_args)
        patch_records.append(_batch_rebinding_patch_record(item_path, command_name, path, patched, args, patched_args))

    for key in _BATCH_RECURSIVE_PLAN_KEYS:
        nested = patched.get(key)
        if isinstance(nested, list):
            patched_nested, nested_records = _batch_rebinding_patch_item_tree(nested, rebinding, f"{item_path}.{key}")
            patched[key] = patched_nested
            patch_records.extend(nested_records)

    patch_records.extend(_batch_rebinding_patch_nested_step_specs(patched, rebinding, item_path))

    for arg_key in ("args", "data"):
        nested_args = patched.get(arg_key)
        if not isinstance(nested_args, dict):
            continue
        for key in _BATCH_RECURSIVE_PLAN_KEYS:
            nested = nested_args.get(key)
            if isinstance(nested, list):
                patched_nested, nested_records = _batch_rebinding_patch_item_tree(nested, rebinding, f"{item_path}.{arg_key}.{key}")
                nested_args[key] = patched_nested
                patch_records.extend(nested_records)
        patch_records.extend(_batch_rebinding_patch_nested_step_specs(nested_args, rebinding, f"{item_path}.{arg_key}"))
    return patched, patch_records


def _batch_rebinding_retry_item(original: Dict[str, Any], rebinding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(original, dict) or not isinstance(rebinding, dict):
        return None
    patched, patch_records = _batch_rebinding_patch_item_tree(original, rebinding)
    if not patch_records:
        return None
    patched["diagnostic_rebinding"] = {
        key: rebinding.get(key)
        for key in ("kind", "layer", "source_id", "source_command", "hwnd", "target_hwnd", "child_hwnd", "index", "view")
        if rebinding.get(key) not in (None, "", [], {})
    }
    for key in ("retries", "retry_count", "retry-count", "retry_delay", "retry-delay", "recover_on_failure", "recover-on-failure", "failure_recovery", "failure-recovery"):
        patched.pop(key, None)
    return {
        "item": patched,
        "patch_records": patch_records,
        "patch_count": len(patch_records),
        "patched_paths": [record.get("item_path") for record in patch_records if record.get("item_path")],
        "patched_args_preview": [record.get("args_preview") for record in patch_records if record.get("args_preview")],
    }


def _batch_rebinding_retry_skip_item(index: int, original: Dict[str, Any], reason: str) -> Dict[str, Any]:
    command_name, path, _ = _batch_command_parts(original)
    return {
        "index": index,
        "id": _batch_step_id(original) if isinstance(original, dict) else None,
        "command": command_name,
        "path": path or None,
        "result": {
            "ok": False,
            "skipped": True,
            "error": "rebind_retry_skipped",
            "reason": reason,
        },
        "attempts": 0,
        "elapsed_ms": 0.0,
    }


def _batch_retry_failed_steps_with_rebindings(
    batch_result: Dict[str, Any],
    commands: List[Dict[str, Any]],
    rebindings: List[Dict[str, Any]],
    *,
    retry_limit: Any = 1,
    deadline: Optional[float] = None,
    trace: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    limit = _batch_rebind_retry_limit(retry_limit)
    indexes = _batch_failed_step_indexes(batch_result, commands, limit)
    report: Dict[str, Any] = {
        "enabled": True,
        "executed": False,
        "requested_limit": limit,
        "indexes": indexes,
        "rebinding_count": len(rebindings) if isinstance(rebindings, list) else 0,
        "patched_count": 0,
        "skipped_count": 0,
        "patch_count": 0,
        "patched_paths": [],
    }
    if not indexes:
        report["reason"] = "no_failed_steps_to_retry"
        return report
    if not isinstance(rebindings, list) or not rebindings:
        report["reason"] = "no_rebindings"
        return report
    if _batch_deadline_exceeded(deadline):
        report["reason"] = "batch_timeout"
        report["summary"] = _batch_summary([], total_count=len(indexes), stopped_on_error=True)
        return report

    retry_results: List[Dict[str, Any]] = []
    attempts: List[Dict[str, Any]] = []
    retry_context = list(batch_result.get("results") or [])
    _batch_trace_event(trace, "diagnostic_repair_rebind_retry_start", count=len(indexes), indexes=indexes, rebinding_count=len(rebindings))
    for index in indexes:
        original = commands[index]
        patched_item = None
        used_rebinding = None
        patch_report: Dict[str, Any] = {}
        for rebinding in rebindings:
            candidate = _batch_rebinding_retry_item(original, rebinding)
            if candidate:
                patched_item = candidate.get("item")
                patch_report = candidate
                used_rebinding = rebinding
                break
        if not patched_item:
            attempts.append({"index": index, "patched": False, "reason": "no_matching_rebinding"})
            retry_results.append(_batch_rebinding_retry_skip_item(index, original, "no_matching_rebinding"))
            continue
        if _batch_deadline_exceeded(deadline):
            retry_results.append(_batch_timeout_item(index, patched_item, "diagnostic repair rebind retry", deadline))
            break
        retry_item = _batch_execute_step_item(index, patched_item, retry_context, deadline=deadline, trace=trace, allow_followups=False)
        retry_item["retry_of_index"] = index
        retry_item["rebind_retry"] = True
        retry_item["rebinding"] = {
            key: used_rebinding.get(key)
            for key in ("kind", "layer", "source_id", "source_command", "hwnd", "target_hwnd", "child_hwnd", "index", "view")
            if isinstance(used_rebinding, dict) and used_rebinding.get(key) not in (None, "", [], {})
        }
        retry_item["rebinding_patches"] = patch_report.get("patch_records") or []
        retry_results.append(retry_item)
        retry_context.append(retry_item)
        attempts.append({
            "index": index,
            "patched": True,
            "kind": (used_rebinding or {}).get("kind") if isinstance(used_rebinding, dict) else None,
            "patch_count": patch_report.get("patch_count", 0),
            "patched_paths": patch_report.get("patched_paths") or [],
            "patched_args_preview": patch_report.get("patched_args_preview") or [],
        })
    summary = _batch_summary(retry_results, total_count=len(indexes), stopped_on_error=bool(_batch_deadline_exceeded(deadline)))
    patched_count = sum(1 for item in attempts if item.get("patched"))
    skipped_count = sum(1 for item in attempts if not item.get("patched"))
    patch_count = sum(int(item.get("patch_count") or 0) for item in attempts if item.get("patched"))
    patched_paths: List[str] = []
    for item in attempts:
        for patched_path in item.get("patched_paths") or []:
            if isinstance(patched_path, str) and patched_path not in patched_paths:
                patched_paths.append(patched_path)
    _batch_trace_event(
        trace,
        "diagnostic_repair_rebind_retry_end",
        ok=summary.get("ok"),
        failed_count=summary.get("failed_count"),
        count=len(retry_results),
        patched_count=patched_count,
        skipped_count=skipped_count,
        patch_count=patch_count,
    )
    report.update({
        "executed": any(item.get("patched") for item in attempts),
        "ok": bool(summary.get("ok")),
        "summary": summary,
        "results": retry_results,
        "attempts": attempts,
        "patched_count": patched_count,
        "skipped_count": skipped_count,
        "patch_count": patch_count,
        "patched_paths": patched_paths[:32],
    })
    if not any(item.get("patched") for item in attempts):
        report["reason"] = "no_retry_steps_patched"
    return report


def _batch_run_diagnostic_repair(
    batch_result: Dict[str, Any],
    commands: List[Dict[str, Any]],
    *,
    repair_context: Any = None,
    repair_limit: Any = 4,
    retry_failed_steps: bool = False,
    retry_limit: Any = 1,
    rebind_retry_failed_steps: bool = False,
    rebind_retry_limit: Any = 1,
    deadline: Optional[float] = None,
    trace: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not isinstance(batch_result, dict) or batch_result.get("ok") is True:
        return {}
    limit = _batch_auto_repair_limit(repair_limit)
    context = _batch_auto_repair_context(repair_context, commands)
    plan_args: Dict[str, Any] = {
        "diagnostic_summary": batch_result,
        "limit": limit,
        "include_pending": True,
        "allow_step_refs": False,
        "as_try": True,
    }
    if context:
        plan_args["context"] = context
    plan = _batch_repair_plan(plan_args)
    ready_commands = list(((plan.get("batch") or {}).get("commands") or [])) if isinstance(plan, dict) else []
    diagnostic = {
        "ok": bool(plan.get("ready")) if isinstance(plan, dict) else False,
        "enabled": True,
        "executed": False,
        "plan": _batch_compact_repair_plan(plan if isinstance(plan, dict) else {}),
    }
    if not ready_commands:
        diagnostic["reason"] = "no_ready_repair_steps"
        return diagnostic
    if _batch_deadline_exceeded(deadline):
        diagnostic["reason"] = "batch_timeout"
        diagnostic["result"] = {
            "ok": False,
            "error": "batch_timeout",
            "timeout_budget_exceeded": True,
        }
        return diagnostic
    _batch_trace_event(trace, "diagnostic_repair_start", count=len(ready_commands), ready_count=plan.get("ready_count"))
    repair_result = _batch_run_followup_steps(
        "diagnostic_repair",
        {"steps": ready_commands, "stop_on_error": True},
        list(batch_result.get("results") or []),
        deadline,
        trace,
    )
    _batch_trace_event(trace, "diagnostic_repair_end", ok=(repair_result or {}).get("ok"), count=len((repair_result or {}).get("results") or []))
    diagnostic["executed"] = True
    diagnostic["result"] = repair_result or {"ok": False, "error": "empty_repair_result"}
    diagnostic["ok"] = bool((repair_result or {}).get("ok"))
    rebindings = _batch_collect_rebindings(repair_result, limit=max(12, limit * 3) if limit else 12)
    if rebindings:
        diagnostic["rebindings"] = rebindings
        diagnostic["rebinding_count"] = len(rebindings)
    if retry_failed_steps:
        if diagnostic["ok"]:
            diagnostic["retry"] = _batch_retry_failed_steps_after_repair(
                batch_result,
                commands,
                retry_limit=retry_limit,
                deadline=deadline,
                trace=trace,
            )
        else:
            diagnostic["retry"] = {
                "enabled": True,
                "executed": False,
                "reason": "repair_probe_failed",
            }
    if rebind_retry_failed_steps:
        if diagnostic["ok"]:
            diagnostic["rebind_retry"] = _batch_retry_failed_steps_with_rebindings(
                batch_result,
                commands,
                rebindings,
                retry_limit=rebind_retry_limit,
                deadline=deadline,
                trace=trace,
            )
        else:
            diagnostic["rebind_retry"] = {
                "enabled": True,
                "executed": False,
                "reason": "repair_probe_failed",
            }
    return diagnostic


def _batch_summary(results: List[Dict[str, Any]], total_count: Optional[int] = None, stopped_on_error: bool = False) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    elapsed_values: List[float] = []
    failure_categories: List[str] = []
    recommendations: List[str] = []
    for fallback_index, item in enumerate(results):
        if isinstance(item, dict) and item.get("elapsed_ms") is not None:
            try:
                elapsed_values.append(float(item.get("elapsed_ms") or 0.0))
            except Exception:
                pass
        result = item.get("result") if isinstance(item, dict) else item
        command = item.get("command") if isinstance(item, dict) else None
        failure = _batch_result_failure(result, command=command)
        if failure:
            entry = {
                "index": int(item.get("index", fallback_index)) if isinstance(item, dict) else fallback_index,
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
            _batch_auto_plan_unique_append(failure_categories, failure.get("failure_category"))
            for recommendation in failure.get("recommendations") or []:
                _batch_auto_plan_unique_append(recommendations, recommendation)
    total = int(total_count if total_count is not None else len(results))
    summary = {
        "ok": not failures and len(results) == total,
        "count": len(results),
        "total_count": total,
        "failed_count": len(failures),
        "failures": failures,
        "stopped_on_error": bool(stopped_on_error),
        "elapsed_ms": round(sum(elapsed_values), 3) if elapsed_values else 0.0,
    }
    if failure_categories:
        summary["failure_categories"] = failure_categories
    if recommendations:
        summary["recommendations"] = recommendations
    diagnostics = _batch_branch_diagnostic_summary({"results": results})
    if diagnostics:
        summary["diagnostic_summary"] = diagnostics
        if diagnostics.get("relocated"):
            summary["relocated"] = True
        if diagnostics.get("uia_relocation_count"):
            summary["uia_relocation_count"] = diagnostics.get("uia_relocation_count")
        if isinstance(diagnostics.get("last_uia_relocation"), dict):
            summary["last_uia_relocation"] = diagnostics.get("last_uia_relocation")
    return summary


def _batch_execute_step_item(index: int, cmd_item: Any, results: List[Dict[str, Any]], deadline: Optional[float] = None, trace: Optional[List[Dict[str, Any]]] = None, allow_followups: bool = True) -> Dict[str, Any]:
    step_start = time.perf_counter()
    if not isinstance(cmd_item, dict):
        item = _batch_invalid_item(index, cmd_item)
        item["elapsed_ms"] = round((time.perf_counter() - step_start) * 1000.0, 3)
        return item

    command_name, path, args = _batch_command_parts(cmd_item)
    step_id = _batch_step_id(cmd_item)
    step_deadline = _batch_deadline_from_sources(cmd_item, args, deadline)
    _batch_trace_event(trace, "step_start", index=index, id=step_id, command=command_name, path=path or None)
    if _batch_deadline_exceeded(step_deadline):
        item = _batch_timeout_item(index, cmd_item, "batch step", step_deadline)
        _batch_trace_event(trace, "step_end", index=index, id=step_id, command=command_name, ok=False, error="batch_timeout")
        return {k: v for k, v in item.items() if v is not None}
    skip = _batch_skip_decision(cmd_item, results)
    if skip:
        item = {
            "index": index,
            "id": step_id,
            "command": command_name,
            "path": path or None,
            "result": {"ok": True, "skipped": True, **skip},
            "attempts": 0,
            "elapsed_ms": round((time.perf_counter() - step_start) * 1000.0, 3),
        }
        _batch_trace_event(trace, "step_skipped", index=index, id=step_id, reason=skip.get("skip_reason"))
        return {k: v for k, v in item.items() if v is not None}

    if isinstance(args, dict) and "__batch_arg_error__" not in args:
        args = _batch_resolve_refs(args, results)
    step_deadline = _batch_deadline_from_sources(cmd_item, args, deadline)
    retry_count, retry_delay = _batch_retry_options(cmd_item)
    expectation = _batch_expectation_spec(cmd_item)
    extract = _batch_extract_spec(cmd_item)
    allow_failure = _batch_allows_failure(cmd_item)
    on_failure_spec = _batch_followup_spec(cmd_item, args, "on_failure") if allow_followups else None
    finally_spec = _batch_followup_spec(cmd_item, args, "finally") if allow_followups else None
    recovery_spec = _batch_step_recovery_spec(cmd_item, args) if allow_followups else None
    arg_error = _batch_arg_error(args)
    attempts = 1
    last_failure = None
    recovery_result = None
    if arg_error:
        r = arg_error
    else:
        r = _batch_execute_command_core(command_name, cmd_item, args, results, step_deadline, trace, expectation, extract)
        last_failure = _batch_result_failure(r, command=command_name)
        while last_failure and attempts <= retry_count:
            if retry_delay > 0:
                if not _batch_sleep_with_deadline(retry_delay, step_deadline):
                    r = _batch_timeout_result("batch retry delay", step_deadline, previous_failure=last_failure)
                    last_failure = _batch_result_failure(r, command=command_name)
                    break
            if _batch_deadline_exceeded(step_deadline):
                r = _batch_timeout_result("batch retry", step_deadline, previous_failure=last_failure)
                last_failure = _batch_result_failure(r, command=command_name)
                break
            attempts += 1
            _batch_trace_event(trace, "step_retry", index=index, id=step_id, attempt=attempts, previous_error=last_failure.get("error") if isinstance(last_failure, dict) else None)
            r = _batch_execute_command_core(command_name, cmd_item, args, results, step_deadline, trace, expectation, extract)
            last_failure = _batch_result_failure(r, command=command_name)
        if last_failure and recovery_spec is not None:
            recovery_steps, recovery_key, retry_original, recovery_options = _batch_step_recovery_steps_config(recovery_spec, last_failure)
            if recovery_options and recovery_options.get("error"):
                recovery_result = recovery_options
            elif recovery_steps:
                recovery_context: List[Dict[str, Any]] = list(results)
                recovery_context.append({"index": index, "id": step_id, "command": command_name, "path": path or None, "result": r, "attempts": attempts})
                label = f"recovery:{recovery_key or last_failure.get('failure_category') or 'default'}"
                _batch_trace_event(trace, "step_recovery_start", index=index, id=step_id, category=last_failure.get("failure_category"), key=recovery_key, count=len(recovery_steps))
                recovery_result = _batch_run_followup_steps(label, {"steps": recovery_steps, "stop_on_error": bool((recovery_options or {}).get("stop_on_error"))}, recovery_context, step_deadline, trace)
                _batch_trace_event(trace, "step_recovery_end", index=index, id=step_id, ok=(recovery_result or {}).get("ok"), key=recovery_key)
                if retry_original and isinstance(recovery_result, dict) and recovery_result.get("ok") and not _batch_deadline_exceeded(step_deadline):
                    attempts += 1
                    _batch_trace_event(trace, "step_recovery_retry", index=index, id=step_id, attempt=attempts, previous_error=last_failure.get("error"), key=recovery_key)
                    r = _batch_execute_command_core(command_name, cmd_item, args, results, step_deadline, trace, expectation, extract)
                    last_failure = _batch_result_failure(r, command=command_name)
    cleanup_context: List[Dict[str, Any]] = list(results)
    preview_item = {"index": index, "id": step_id, "command": command_name, "path": path or None, "result": r, "attempts": attempts}
    cleanup_context.append(preview_item)
    on_failure_result = None
    if on_failure_spec is not None and _batch_result_failure(r, command=command_name):
        on_failure_result = _batch_run_followup_steps("on_failure", on_failure_spec, cleanup_context, step_deadline, trace)
    finally_result = None
    if finally_spec is not None:
        finally_result = _batch_run_followup_steps("finally", finally_spec, cleanup_context, step_deadline, trace)
    if allow_failure:
        tolerated_failure = _batch_result_failure(r, command=command_name)
        if tolerated_failure:
            r = {
                "ok": True,
                "tolerated_failure": True,
                "failure": tolerated_failure,
                "original_result": r,
            }
    r = _batch_attach_supplied_diagnostics(r, cmd_item, args, command=command_name)
    item = {"index": index, "id": step_id, "command": command_name, "path": path or None, "result": r, "attempts": attempts}
    if retry_count:
        item["retries"] = retry_count
        item["retry_delay"] = retry_delay
    if allow_failure:
        item["allow_failure"] = True
    if recovery_result is not None:
        item["recovery"] = recovery_result
    if on_failure_result is not None:
        item["on_failure"] = on_failure_result
    if finally_result is not None:
        item["finally"] = finally_result
    item["elapsed_ms"] = round((time.perf_counter() - step_start) * 1000.0, 3)
    _batch_trace_event(trace, "step_end", index=index, id=step_id, command=command_name, ok=not bool(_batch_result_failure(r, command=command_name)), attempts=attempts, elapsed_ms=item["elapsed_ms"])
    return {k: v for k, v in item.items() if v is not None}


def execute_batch(
    commands: List[Dict[str, Any]],
    stop_on_error: bool = False,
    confirmed: bool = False,
    timeout_budget: Optional[float] = None,
    on_failure: Any = None,
    finally_steps: Any = None,
    trace: bool = False,
    auto_repair_diagnostics: bool = False,
    repair_context: Any = None,
    repair_limit: Any = 4,
    diagnostic_repair_retry: bool = False,
    diagnostic_repair_retry_limit: Any = 1,
    diagnostic_repair_rebind_retry: bool = False,
    diagnostic_repair_rebind_retry_limit: Any = 1,
    diagnostic_repair_rebind_retry_explicit: bool = False,
) -> Dict[str, Any]:
    """Execute mixed automation batch commands with helper acceleration when safe."""
    safety_scope: List[Any] = list(commands or [])
    if on_failure is not None:
        safety_scope.append({"id": "batch_on_failure", "on_failure": on_failure})
    if finally_steps is not None:
        safety_scope.append({"id": "batch_finally", "finally": finally_steps})
    safety_findings = _batch_safety_findings(safety_scope)
    confirmation_granted = _coerce_bool(confirmed, False)
    if safety_findings and not confirmation_granted:
        return {
            "ok": False,
            "error": "confirmation_required",
            "failure_category": "safety",
            "requires_confirmation": True,
            "executed": False,
            "command_count": len(commands),
            "confirmations": safety_findings,
        }
    trace_events: Optional[List[Dict[str, Any]]] = [] if trace else None
    deadline = _batch_deadline_from_value(timeout_budget)
    auto_recover_rebind_retry = (
        not diagnostic_repair_rebind_retry
        and not diagnostic_repair_rebind_retry_explicit
        and _batch_auto_recover_rebind_retry_requested(commands)
    )
    if auto_recover_rebind_retry:
        diagnostic_repair_rebind_retry = True
    effective_auto_repair_diagnostics = bool(auto_repair_diagnostics or diagnostic_repair_retry or diagnostic_repair_rebind_retry)
    has_batch_options = timeout_budget is not None or on_failure is not None or finally_steps is not None or trace or effective_auto_repair_diagnostics
    batch_has_uia = _batch_contains_uia(commands)
    if not has_batch_options and _can_helper_handle_batch(commands):
        helper_commands = [_batch_item_for_helper(item) for item in commands]
        target_hwnd = _batch_target_hwnd(commands)
        if batch_has_uia:
            boundary_result = _elevated_helper_required_result(target_hwnd, "/batch")
            if boundary_result is not None:
                boundary_result["target_hwnd"] = target_hwnd
                boundary_result["command_count"] = len(helper_commands)
                return boundary_result
            helper_ready, helper_elevated = _prepare_helper_for_uia(target_hwnd)
        else:
            helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(target_hwnd, "/batch")
            if boundary_result is not None:
                boundary_result["target_hwnd"] = target_hwnd
                boundary_result["command_count"] = len(helper_commands)
                return boundary_result
        if helper_ready:
            result = _helper_post("/batch", {"commands": helper_commands, "stop_on_error": bool(stop_on_error)}, elevated=helper_elevated)
            if "error" not in result:
                result["helper_elevated"] = helper_elevated
                result["results"] = [
                    _batch_normalize_item(item, index)
                    for index, item in enumerate(list(result.get("results") or []))
                ]
                if "ok" not in result:
                    result.update(_batch_summary(list(result.get("results") or []), total_count=len(helper_commands)))
                else:
                    result.update(_batch_summary(list(result.get("results") or []), total_count=len(helper_commands), stopped_on_error=bool(result.get("stopped_on_error"))))
                if safety_findings:
                    result["safety"] = {"confirmed": True, "confirmations": safety_findings}
                return result
            if batch_has_uia:
                return {
                    "error": "UIA helper batch failed; skipped local UIA fallback to avoid hanging the caller",
                    "helper": True,
                    "helper_elevated": helper_elevated,
                    "helper_error": result.get("error"),
                    "target_hwnd": target_hwnd,
                }

    results = []
    stopped_on_error = False
    _batch_trace_event(trace_events, "batch_start", count=len(commands), stop_on_error=bool(stop_on_error), timeout_budget=timeout_budget)
    if auto_recover_rebind_retry:
        _batch_trace_event(trace_events, "auto_recover_rebind_retry_enabled", reason="window_auto_recover")
    for index, cmd_item in enumerate(commands):
        if _batch_deadline_exceeded(deadline):
            item = _batch_timeout_item(index, cmd_item, "batch", deadline)
            stopped_on_error = True
            results.append(item)
            break
        item = _batch_execute_step_item(index, cmd_item, results, deadline=deadline, trace=trace_events)
        results.append(item)
        item_failed = _batch_result_failure(item.get("result") if isinstance(item, dict) else item)
        if item_failed and (_batch_deadline_exceeded(deadline) or stop_on_error):
            stopped_on_error = True
            break
    summary = _batch_summary(results, total_count=len(commands), stopped_on_error=stopped_on_error)
    batch_result = {"results": results, **summary}
    if safety_findings:
        batch_result["safety"] = {"confirmed": True, "confirmations": safety_findings}
    if timeout_budget is not None:
        batch_result["timeout_budget"] = timeout_budget
        batch_result["timeout_budget_exceeded"] = bool(_batch_deadline_exceeded(deadline) and not summary.get("ok"))
    if on_failure is not None and not summary.get("ok"):
        batch_result["on_failure"] = _batch_run_followup_steps("batch_on_failure", on_failure, results, deadline, trace_events)
    if effective_auto_repair_diagnostics and not summary.get("ok"):
        batch_result["diagnostic_repair"] = _batch_run_diagnostic_repair(
            batch_result,
            commands,
            repair_context=repair_context,
            repair_limit=repair_limit,
            retry_failed_steps=diagnostic_repair_retry,
            retry_limit=diagnostic_repair_retry_limit,
            rebind_retry_failed_steps=diagnostic_repair_rebind_retry,
            rebind_retry_limit=diagnostic_repair_rebind_retry_limit,
            deadline=deadline,
            trace=trace_events,
        )
        if auto_recover_rebind_retry and isinstance(batch_result.get("diagnostic_repair"), dict):
            batch_result["diagnostic_repair"]["auto_recover_rebind_retry"] = True
    if finally_steps is not None:
        batch_result["finally"] = _batch_run_followup_steps("batch_finally", finally_steps, results, deadline, trace_events)
    _batch_trace_event(trace_events, "batch_end", ok=batch_result.get("ok"), failed_count=batch_result.get("failed_count"), count=batch_result.get("count"))
    if trace_events is not None:
        batch_result["trace"] = trace_events
    return batch_result

