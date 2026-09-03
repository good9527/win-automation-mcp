"""
Batch execution plan evaluator: branch ladders, try-catch handlers, loop evaluation, and condition tests.
"""

from __future__ import annotations

import os
import sys
import time
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.win32.window import _window_info
from win_automation.state.persistence import resolve_target_hwnd

def _batch_reports_diagnostic_summary(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    summaries: List[Dict[str, Any]] = []
    selected_summary: Optional[Dict[str, Any]] = None
    all_categories: List[str] = []
    all_recommendations: List[str] = []
    all_native_wait_steps: List[Dict[str, Any]] = []
    all_native_selector_suggestions: List[Dict[str, Any]] = []
    all_uia_selector_suggestions: List[Dict[str, Any]] = []
    all_window_selector_suggestions: List[Dict[str, Any]] = []
    all_repair_candidates: List[Dict[str, Any]] = []
    last_relocation: Optional[Dict[str, Any]] = None
    relocation_count = 0
    for report in reports or []:
        if not isinstance(report, dict):
            continue
        summary = _batch_branch_diagnostic_summary(report)
        if not summary:
            continue
        summary = {
            "index": report.get("index"),
            "id": report.get("id"),
            "selected": bool(report.get("selected")),
            **summary,
        }
        summaries.append({k: v for k, v in summary.items() if v not in (None, "", [], {})})
        if report.get("selected"):
            selected_summary = summaries[-1]
        try:
            relocation_count += int(summary.get("uia_relocation_count") or 0)
        except Exception:
            pass
        if isinstance(summary.get("last_uia_relocation"), dict):
            last_relocation = dict(summary.get("last_uia_relocation") or {})
        for category in summary.get("failure_categories") or []:
            _batch_auto_plan_unique_append(all_categories, category)
        for recommendation in summary.get("recommendations") or []:
            _batch_auto_plan_unique_append(all_recommendations, recommendation)
        for wait_step in summary.get("native_control_wait") or []:
            if isinstance(wait_step, dict) and wait_step and wait_step not in all_native_wait_steps:
                all_native_wait_steps.append(wait_step)
        for candidate in summary.get("next_repair_candidates") or []:
            if isinstance(candidate, dict):
                _batch_append_repair_candidate(all_repair_candidates, candidate, limit=12)
        for suggestion in summary.get("native_selector_suggestions") or []:
            if isinstance(suggestion, dict) and suggestion and suggestion not in all_native_selector_suggestions:
                all_native_selector_suggestions.append(suggestion)
        for suggestion in summary.get("uia_selector_suggestions") or []:
            if isinstance(suggestion, dict) and suggestion and suggestion not in all_uia_selector_suggestions:
                all_uia_selector_suggestions.append(suggestion)
        for suggestion in summary.get("window_selector_suggestions") or []:
            if isinstance(suggestion, dict) and suggestion and suggestion not in all_window_selector_suggestions:
                all_window_selector_suggestions.append(suggestion)
    result: Dict[str, Any] = {}
    if summaries:
        result["branches"] = summaries[:12]
    if selected_summary:
        result["selected"] = selected_summary
    if relocation_count:
        result["uia_relocation_count"] = relocation_count
        result["relocated"] = True
    if last_relocation:
        result["last_uia_relocation"] = last_relocation
    if all_categories:
        result["failure_categories"] = all_categories
    if all_recommendations:
        result["recommendations"] = all_recommendations
    if all_native_wait_steps:
        result["native_control_wait"] = all_native_wait_steps[:8]
    if all_native_selector_suggestions:
        result["native_selector_repair_available"] = True
        result["native_selector_suggestions"] = all_native_selector_suggestions[:8]
    if all_uia_selector_suggestions:
        result["uia_selector_repair_available"] = True
        result["uia_selector_suggestions"] = all_uia_selector_suggestions[:8]
    if all_window_selector_suggestions:
        result["window_selector_repair_available"] = True
        result["window_selector_suggestions"] = all_window_selector_suggestions[:8]
    if all_repair_candidates:
        result["next_repair_candidates"] = all_repair_candidates[:12]
        repair_steps = _batch_repair_candidate_steps(all_repair_candidates, limit=12)
        if repair_steps:
            result["next_repair_steps"] = repair_steps
    return result


def _batch_try_failure_summary(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    categories: List[str] = []
    recommendations: List[str] = []
    failed_branch_ids: List[str] = []
    first_failure: Optional[Dict[str, Any]] = None
    diagnostics = _batch_reports_diagnostic_summary(reports)
    for report in reports or []:
        if not isinstance(report, dict) or report.get("selected"):
            continue
        branch_id = report.get("id")
        if branch_id:
            _batch_auto_plan_unique_append(failed_branch_ids, branch_id)
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        failures = summary.get("failures") if isinstance(summary.get("failures"), list) else []
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            first_failure = first_failure or failure
            _batch_auto_plan_unique_append(categories, failure.get("failure_category"))
            for recommendation in failure.get("recommendations") or []:
                _batch_auto_plan_unique_append(recommendations, recommendation)
    result = {
        "failed_branch_count": len([report for report in reports or [] if isinstance(report, dict) and not report.get("selected")]),
        "failed_branch_ids": failed_branch_ids,
        "failure_categories": categories,
        "recommendations": recommendations,
    }
    if first_failure:
        result["first_failure"] = {
            key: first_failure.get(key)
            for key in ("id", "command", "path", "error", "failure_category", "elapsed_ms")
            if first_failure.get(key) is not None
        }
    if diagnostics:
        result["diagnostic_summary"] = diagnostics
        if diagnostics.get("uia_relocation_count"):
            result["uia_relocation_count"] = diagnostics.get("uia_relocation_count")
        if isinstance(diagnostics.get("last_uia_relocation"), dict):
            result["last_uia_relocation"] = diagnostics.get("last_uia_relocation")
    return {k: v for k, v in result.items() if v not in (None, "", [], {})}


def _batch_auto_kind(item: Dict[str, Any], args: Dict[str, Any]) -> str:
    for key in ("kind", "intent", "mode"):
        if key in item and item.get(key) is not None:
            return str(item.get(key) or "").strip().lower().replace("-", "_")
        if isinstance(args, dict) and key in args and args.get(key) is not None:
            return str(args.get(key) or "").strip().lower().replace("-", "_")
    command = str(item.get("command") or "").strip().lower().replace("-", "_")
    if command in {name.replace("-", "_") for name in _BATCH_WINDOW_SEQUENCE_COMMANDS}:
        return "window_sequence"
    if command in {name.replace("-", "_") for name in _BATCH_WINDOW_ACTION_COMMANDS}:
        return "window_action"
    path_command = str(item.get("path") or "").strip().lstrip("/").lower().replace("-", "_")
    if path_command in {name.replace("-", "_") for name in _BATCH_WINDOW_SEQUENCE_COMMANDS}:
        return "window_sequence"
    if path_command in {name.replace("-", "_") for name in _BATCH_WINDOW_ACTION_COMMANDS}:
        return "window_action"
    for key in ("action_kind", "action-kind"):
        if key in item and item.get(key) is not None:
            return str(item.get(key) or "").strip().lower().replace("-", "_")
        if isinstance(args, dict) and key in args and args.get(key) is not None:
            return str(args.get(key) or "").strip().lower().replace("-", "_")
    if command in _BATCH_AUTO_COMMANDS:
        if isinstance(args, dict):
            if args.get("file_dialog_action") is not None or args.get("file_dialog_path") is not None:
                return "file_dialog"
            if args.get("menu_path") is not None or args.get("menu_command_id") is not None or args.get("command_id") is not None:
                return "menu"
            if args.get("hover") is not None or args.get("hover_delay") is not None or args.get("hover_settle") is not None:
                return "hover"
            if args.get("start_x") is not None or args.get("end_x") is not None:
                return "drag"
            if args.get("dy") is not None or args.get("delta") is not None:
                return "scroll"
            if args.get("keys") is not None:
                return "key"
        return "click"
    return command or "click"


def _batch_auto_copy_args(args: Dict[str, Any], keys: Tuple[str, ...]) -> Dict[str, Any]:
    return {key: args.get(key) for key in keys if key in args and args.get(key) is not None}


def _batch_auto_first(args: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in args and args.get(key) is not None:
            return args.get(key)
    return None


def _batch_auto_normalize_args(args: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(args)
    aliases = {
        "automation_id": ("automation-id", "auto_id", "auto-id"),
        "control_type": ("control-type", "type"),
        "class_name": ("class-name", "class"),
        "timeout_ms": ("timeout-ms",),
        "wait_timeout": ("wait-timeout",),
        "action_timeout": ("action-timeout",),
        "input_timeout": ("input-timeout",),
        "row_text": ("row-text", "row_label", "row-label", "row_name", "row-name"),
        "column_name": ("column-name", "column_header", "column-header", "header"),
        "allow_focus_fallback": ("allow-focus-fallback",),
        "allow_coordinate_fallback": ("allow-coordinate-fallback",),
        "include_invisible": ("include-invisible",),
        "skip_uia": ("skip-uia", "no_uia", "no-uia"),
        "template_path": ("template-path", "image_path", "image-path"),
        "screenshot_id": ("screenshot-id",),
        "max_width": ("max-width",),
        "max_words": ("max-words",),
        "row_region": ("row-region", "row_number_region", "row-number-region"),
        "click_x": ("click-x", "target_x", "target-x"),
        "x_offset": ("x-offset",),
        "min_row": ("min-row",),
        "max_row": ("max-row",),
        "max_scrolls": ("max-scrolls", "scroll_limit", "scroll-limit"),
        "scroll_amount": ("scroll-amount",),
        "scroll_x": ("scroll-x", "wheel_x", "wheel-x"),
        "scroll_y": ("scroll-y",),
        "dy": ("delta", "wheel", "wheel_delta", "wheel-delta", "scroll_delta", "scroll-delta"),
        "keyboard_scroll": ("keyboard-scroll",),
        "keyboard_fallback": ("keyboard-fallback", "key_fallback", "key-fallback"),
        "keys": ("key", "shortcut", "hotkey", "keys_sequence", "key-sequence", "key_sequence"),
        "menu_path": ("menu-path", "menu_item", "menu-item", "menu", "hmenu_path", "hmenu-path"),
        "menu_command_id": ("menu-command-id", "menu_command", "menu-command", "command-id", "command_id", "menu_id", "menu-id", "id_command", "id-command"),
        "include_system": ("include-system", "include_system_menu", "include-system-menu", "system_menu", "system-menu"),
        "async_post": ("async-post", "post_async", "post-async"),
        "file_dialog_action": ("file-dialog-action", "dialog_action", "dialog-action", "file_action", "file-action", "file_dialog_op", "file-dialog-op"),
        "file_dialog_path": ("file-dialog-path", "filename", "file", "file_path", "file-path", "target_file", "target-file"),
        "verify_close": ("verify-close", "wait_close", "wait-close", "close_wait", "close-wait"),
        "include_children": ("include-children",),
        "hover_delay": ("hover-delay", "hover_pause", "hover-pause", "mouseover_delay", "mouseover-delay"),
        "hover_settle": ("hover-settle", "hover_wait", "hover-wait", "mouseover_settle", "mouseover-settle"),
        "settle": ("settle-delay", "settle_delay", "pause"),
        "start_x": ("start-x", "x1", "from_x", "from-x"),
        "start_y": ("start-y", "y1", "from_y", "from-y"),
        "end_x": ("end-x", "x2", "to_x", "to-x"),
        "end_y": ("end-y", "y2", "to_y", "to-y"),
        "visual_row": ("visual-row", "row_number", "row-number", "line", "line_number", "line-number"),
        "visual_row_fallback": ("visual-row-fallback", "numbered_row_fallback", "numbered-row-fallback", "row_fallback", "row-fallback"),
        "scale_min": ("scale-min",),
        "scale_max": ("scale-max",),
        "scale_step": ("scale-step",),
        "capture_mode": ("capture-mode", "capture"),
        "control_action": ("control-action",),
        "click_action": ("click-action",),
        "uia_action": ("uia-action",),
        "native_action": ("native-action",),
        "dialog_title": ("dialog-title", "title"),
        "dialog_class_name": ("dialog-class-name", "dialog_class", "dialog-class"),
        "dialog_process": ("dialog-process", "process"),
        "dialog_action_kind": ("dialog-action-kind", "dialog_action", "dialog-action", "target_kind", "target-kind", "inner_kind", "inner-kind"),
        "dialog_stable_ticks": ("dialog-stable-ticks", "dialog_wait_stable_ticks", "dialog-wait-stable-ticks", "dialog_action_stable_ticks", "dialog-action-stable-ticks"),
        "action_kind": ("action-kind", "control_kind", "control-kind", "operation", "op"),
        "action_repair": ("action-repair", "inner_repair", "inner-repair", "dialog_action_repair", "dialog-action-repair"),
        "repair_timeout": ("repair-timeout",),
        "selector_repair_timeout": ("selector-repair-timeout", "selector_repair_seconds", "selector-repair-seconds"),
        "action_repair_timeout": ("action-repair-timeout", "action_repair_seconds", "action-repair-seconds", "inner_repair_timeout", "inner-repair-timeout", "dialog_action_repair_timeout", "dialog-action-repair-timeout"),
        "sequence_steps": ("sequence-steps", "actions", "tasks", "workflow", "workflow_steps", "workflow-steps"),
        "sequence_focus": ("sequence-focus", "refocus", "refocus_each_step", "refocus-each-step", "focus_each_step", "focus-each-step"),
        "step_delay": ("step-delay", "sequence_delay", "sequence-delay", "between_steps", "between-steps"),
        "sequence_recovery": ("sequence-recovery", "recovery", "recover", "recovery_steps", "recovery-steps", "recover_steps", "recover-steps", "step_recovery", "step-recovery", "on_step_failure", "on-step-failure", "on_step_fail", "on-step-fail"),
        "sequence_recovery_focus": ("sequence-recovery-focus", "recovery_focus", "recovery-focus", "refocus_on_recovery", "refocus-on-recovery", "refocus_on_retry", "refocus-on-retry"),
        "sequence_recovery_delay": ("sequence-recovery-delay", "recovery_delay", "recovery-delay", "recover_delay", "recover-delay", "retry_delay_after_recovery", "retry-delay-after-recovery"),
        "recovery_timeout": ("recovery-timeout", "recover_timeout", "recover-timeout", "recovery_wait_timeout", "recovery-wait-timeout", "recover_wait_timeout", "recover-wait-timeout"),
        "recovery_interval": ("recovery-interval", "recover_interval", "recover-interval"),
        "recovery_stable_ticks": ("recovery-stable-ticks", "recover_stable_ticks", "recover-stable-ticks"),
        "recovery_visual_stable": ("recovery-visual-stable", "recover_visual_stable", "recover-visual-stable"),
        "recovery_uia_stable": ("recovery-uia-stable", "recovery_structure_stable", "recovery-structure-stable", "recover_uia_stable", "recover-uia-stable"),
        "auto_recover": ("auto-recover", "auto_recovery", "auto-recovery", "recover_on_failure", "recover-on-failure"),
        "recovery_policy": ("recovery-policy", "failure_policy", "failure-policy"),
        "native_wait_repair": ("native-wait-repair", "win32_wait_repair", "win32-wait-repair", "verify_native_repair", "verify-native-repair", "verify_win32_repair", "verify-win32-repair"),
        "native_wait_repair_match": ("native-wait-repair-match", "win32_wait_repair_match", "win32-wait-repair-match", "verify_native_repair_match", "verify-native-repair-match", "verify_win32_repair_match", "verify-win32-repair-match"),
        "native_wait_repair_timeout": ("native-wait-repair-timeout", "win32_wait_repair_timeout", "win32-wait-repair-timeout", "verify_native_repair_timeout", "verify-native-repair-timeout", "verify_win32_repair_timeout", "verify-win32-repair-timeout"),
        "selector_repair": ("selector-repair", "selector_fallback", "selector-fallback", "semantic_variants", "semantic-variants", "selector_variants", "selector-variants"),
        "uia_selector_repair": ("uia-selector-repair", "semantic_selector_repair", "semantic-selector-repair", "uia_repair", "uia-repair"),
        "native_selector_repair": ("native-selector-repair", "native_repair", "native-repair", "win32_selector_repair", "win32-selector-repair", "win32_repair", "win32-repair"),
        "window_selector_repair": ("window-selector-repair", "window_repair", "window-repair", "window_find_repair", "window-find-repair", "window_rebind", "window-rebind"),
        "selector_variant_limit": ("selector-variant-limit", "selector_fallback_limit", "selector-fallback-limit", "semantic_variant_limit", "semantic-variant-limit"),
        "allow_suggestion_index": ("allow-suggestion-index",),
        "allow_weak_selector_fallback": ("allow-weak-selector-fallback", "weak_selector_fallback", "weak-selector-fallback", "broad_selector_fallback", "broad-selector-fallback"),
        "visual_text": ("visual-text", "target_text", "target-text", "placeholder", "placeholder_text", "placeholder-text", "label", "field", "field_label", "field-label", "input_label", "input-label"),
        "post_delay": ("post-delay", "after_delay", "after-delay", "settle_delay", "settle-delay", "post_wait", "post-wait"),
        "post_timeout": ("post-timeout", "verify_timeout", "verify-timeout", "verification_timeout", "verification-timeout"),
        "post_interval": ("post-interval", "verify_interval", "verify-interval", "verification_interval", "verification-interval"),
        "post_observe": ("post-observe", "observe_after", "observe-after", "after_observe", "after-observe"),
        "post_event": ("post-event", "post_wait_event", "post-wait-event", "wait_event_after", "wait-event-after", "after_event", "after-event"),
        "post_steps": ("post-steps", "after_steps", "after-steps", "verify_steps", "verify-steps", "verification_steps", "verification-steps"),
        "verify_selector": ("verify-selector", "verify_element", "verify-element", "expected_element", "expected-element"),
        "verify_name": ("verify-name", "expected_name", "expected-name"),
        "verify_value": ("verify-value", "expected_value", "expected-value"),
        "verify_automation_id": ("verify-automation-id", "verify_auto_id", "verify-auto-id", "expected_automation_id", "expected-automation-id"),
        "verify_control_type": ("verify-control-type", "expected_control_type", "expected-control-type"),
        "verify_class_name": ("verify-class-name", "expected_class_name", "expected-class-name"),
        "verify_pattern": ("verify-pattern", "expected_pattern", "expected-pattern"),
        "verify_text": ("verify-text", "verify_ocr", "verify-ocr", "expected_text", "expected-text", "wait_text", "wait-text"),
        "verify_image": ("verify-image", "expected_image", "expected-image", "wait_image", "wait-image"),
        "verify_pixel": ("verify-pixel", "expected_pixel", "expected-pixel", "pixel_color", "pixel-color"),
        "verify_pixel_color": ("verify-pixel-color", "expected_pixel_color", "expected-pixel-color"),
        "verify_pixel_x": ("verify-pixel-x", "pixel_x", "pixel-x"),
        "verify_pixel_y": ("verify-pixel-y", "pixel_y", "pixel-y"),
        "verify_pixel_tolerance": ("verify-pixel-tolerance", "pixel_tolerance", "pixel-tolerance", "color_tolerance", "color-tolerance"),
        "verify_pixel_mode": ("verify-pixel-mode", "pixel_mode", "pixel-mode"),
        "post_stable": ("post-stable", "post_visual_stable", "post-visual-stable", "verify_stable", "verify-stable", "verify_visual_stable", "verify-visual-stable", "wait_visual_stable", "wait-visual-stable"),
        "post_stable_region": ("post-stable-region", "post_visual_stable_region", "post-visual-stable-region", "verify_stable_region", "verify-stable-region", "verify_visual_stable_region", "verify-visual-stable-region"),
        "post_stable_ticks": ("post-stable-ticks", "post_visual_stable_ticks", "post-visual-stable-ticks", "verify_stable_ticks", "verify-stable-ticks", "stable_ticks", "stable-ticks"),
        "post_difference_threshold": ("post-difference-threshold", "post_diff_threshold", "post-diff-threshold", "verify_difference_threshold", "verify-difference-threshold", "difference_threshold", "difference-threshold", "diff_threshold", "diff-threshold"),
        "post_pixel_threshold": ("post-pixel-threshold", "verify_pixel_threshold", "verify-pixel-threshold", "pixel_threshold", "pixel-threshold"),
        "post_stable_max_width": ("post-stable-max-width", "post_visual_stable_max_width", "post-visual-stable-max-width", "verify_stable_max_width", "verify-stable-max-width", "stable_max_width", "stable-max-width"),
        "pre_visual_stable": ("pre-visual-stable", "pre_stable", "pre-stable", "before_visual_stable", "before-visual-stable", "visual_stable_before", "visual-stable-before", "wait_visual_stable_before", "wait-visual-stable-before"),
        "pre_stable_region": ("pre-stable-region", "pre_visual_stable_region", "pre-visual-stable-region"),
        "pre_stable_ticks": ("pre-stable-ticks", "pre_visual_stable_ticks", "pre-visual-stable-ticks"),
        "pre_stable_timeout": ("pre-stable-timeout", "pre_visual_stable_timeout", "pre-visual-stable-timeout"),
        "pre_stable_interval": ("pre-stable-interval", "pre_visual_stable_interval", "pre-visual-stable-interval"),
        "pre_difference_threshold": ("pre-difference-threshold", "pre_diff_threshold", "pre-diff-threshold"),
        "pre_pixel_threshold": ("pre-pixel-threshold",),
        "pre_stable_max_width": ("pre-stable-max-width", "pre_visual_stable_max_width", "pre-visual-stable-max-width"),
        "pre_uia_stable": ("pre-uia-stable", "pre_structure_stable", "pre-structure-stable", "before_uia_stable", "before-uia-stable", "uia_stable_before", "uia-stable-before", "wait_uia_stable_before", "wait-uia-stable-before"),
        "pre_uia_stable_ticks": ("pre-uia-stable-ticks", "pre_structure_stable_ticks", "pre-structure-stable-ticks"),
        "pre_uia_stable_timeout": ("pre-uia-stable-timeout", "pre_structure_stable_timeout", "pre-structure-stable-timeout"),
        "pre_uia_stable_interval": ("pre-uia-stable-interval", "pre_structure_stable_interval", "pre-structure-stable-interval"),
        "pre_uia_stable_max_depth": ("pre-uia-stable-max-depth", "pre_structure_stable_max_depth", "pre-structure-stable-max-depth"),
        "pre_uia_stable_max_elements": ("pre-uia-stable-max-elements", "pre_structure_stable_max_elements", "pre-structure-stable-max-elements"),
        "pre_uia_stable_view": ("pre-uia-stable-view", "pre_structure_stable_view", "pre-structure-stable-view"),
        "pre_uia_stable_include_values": ("pre-uia-stable-include-values", "pre_structure_stable_include_values", "pre-structure-stable-include-values"),
        "pre_uia_stable_rect_bucket": ("pre-uia-stable-rect-bucket", "pre_structure_stable_rect_bucket", "pre-structure-stable-rect-bucket"),
        "pre_boundary": ("pre-boundary", "boundary_preflight", "boundary-preflight", "pre_control_boundary", "pre-control-boundary", "control_boundary_preflight", "control-boundary-preflight", "action_boundary", "action-boundary"),
        "pre_helper": ("pre-helper", "helper_preflight", "helper-preflight", "pre_helper_status", "pre-helper-status", "ensure_helper", "ensure-helper", "ensure_elevated_helper", "ensure-elevated-helper", "action_helper", "action-helper"),
        "post_uia_stable": ("post-uia-stable", "post_structure_stable", "post-structure-stable", "verify_uia_stable", "verify-uia-stable", "verify_structure_stable", "verify-structure-stable", "wait_uia_stable", "wait-uia-stable"),
        "post_uia_stable_ticks": ("post-uia-stable-ticks", "post_structure_stable_ticks", "post-structure-stable-ticks", "verify_uia_stable_ticks", "verify-uia-stable-ticks", "verify_structure_stable_ticks", "verify-structure-stable-ticks", "uia_stable_ticks", "uia-stable-ticks"),
        "post_uia_stable_max_depth": ("post-uia-stable-max-depth", "post_structure_stable_max_depth", "post-structure-stable-max-depth", "verify_uia_stable_max_depth", "verify-uia-stable-max-depth", "uia_stable_max_depth", "uia-stable-max-depth"),
        "post_uia_stable_max_elements": ("post-uia-stable-max-elements", "post_structure_stable_max_elements", "post-structure-stable-max-elements", "verify_uia_stable_max_elements", "verify-uia-stable-max-elements", "uia_stable_max_elements", "uia-stable-max-elements"),
        "post_uia_stable_view": ("post-uia-stable-view", "post_structure_stable_view", "post-structure-stable-view", "verify_uia_stable_view", "verify-uia-stable-view", "uia_stable_view", "uia-stable-view"),
        "post_uia_stable_include_values": ("post-uia-stable-include-values", "post_structure_stable_include_values", "post-structure-stable-include-values", "verify_uia_stable_include_values", "verify-uia-stable-include-values", "uia_stable_include_values", "uia-stable-include-values"),
        "post_uia_stable_rect_bucket": ("post-uia-stable-rect-bucket", "post_structure_stable_rect_bucket", "post-structure-stable-rect-bucket", "verify_uia_stable_rect_bucket", "verify-uia-stable-rect-bucket", "uia_stable_rect_bucket", "uia-stable-rect-bucket"),
        "verify_win32_state": ("verify-win32-state", "verify_native_state", "verify-native-state", "verify-state"),
        "verify_win32_present": ("verify-present", "verify_present", "verify-exists", "verify_exists", "verify-win32-present", "verify_native_present", "verify-native-present", "verify-item-present", "verify_item_present", "verify-present-item", "verify_present_item"),
        "verify_win32_absent": ("verify-absent", "verify_absent", "verify-not-present", "verify_not_present", "verify-win32-absent", "verify_native_absent", "verify-native-absent", "verify-item-absent", "verify_item_absent", "verify-absent-item", "verify_absent_item", "verify-missing-item", "verify_missing_item", "verify-gone-item", "verify_gone_item"),
        "verify_checked": ("verify-checked",),
        "verify_selected": ("verify-selected",),
        "verify_expanded": ("verify-expanded",),
        "verify_visited": ("verify-visited",),
        "verify_win32_expected": ("verify-win32-expected", "verify_native_expected", "verify-native-expected", "verify-expected"),
        "verify_win32_index": ("verify-win32-index", "verify_native_index", "verify-native-index", "verify-item-index"),
        "verify_win32_text": ("verify-win32-text", "verify_native_text", "verify-native-text", "verify-item"),
        "verify_win32_match": ("verify-win32-match", "verify_native_match", "verify-native-match"),
        "verify_win32_timeout_ms": ("verify-win32-timeout-ms", "verify_native_timeout_ms", "verify-native-timeout-ms"),
        "verify_win32_max_items": ("verify-win32-max-items", "verify_native_max_items", "verify-native-max-items"),
        "verify_absent_selector": ("verify-absent-selector", "verify_gone_selector", "verify-gone-selector", "verify_missing_selector", "verify-missing-selector", "absent_selector", "absent-selector", "gone_selector", "gone-selector", "missing_selector", "missing-selector"),
        "verify_absent_name": ("verify-absent-name", "verify_gone_name", "verify-gone-name", "verify_missing_name", "verify-missing-name", "absent_name", "absent-name", "gone_name", "gone-name", "missing_name", "missing-name"),
        "verify_absent_value": ("verify-absent-value", "verify_gone_value", "verify-gone-value", "verify_missing_value", "verify-missing-value", "absent_value", "absent-value", "gone_value", "gone-value", "missing_value", "missing-value"),
        "verify_absent_automation_id": ("verify-absent-automation-id", "verify_gone_automation_id", "verify-gone-automation-id", "verify_missing_automation_id", "verify-missing-automation-id", "absent_automation_id", "absent-automation-id", "gone_automation_id", "gone-automation-id", "missing_automation_id", "missing-automation-id"),
        "verify_absent_control_type": ("verify-absent-control-type", "verify_gone_control_type", "verify-gone-control-type", "verify_missing_control_type", "verify-missing-control-type", "absent_control_type", "absent-control-type", "gone_control_type", "gone-control-type", "missing_control_type", "missing-control-type"),
        "verify_absent_class_name": ("verify-absent-class-name", "verify_gone_class_name", "verify-gone-class-name", "verify_missing_class_name", "verify-missing-class-name", "absent_class_name", "absent-class-name", "gone_class_name", "gone-class-name", "missing_class_name", "missing-class-name"),
        "verify_absent_pattern": ("verify-absent-pattern", "verify_gone_pattern", "verify-gone-pattern", "verify_missing_pattern", "verify-missing-pattern", "absent_pattern", "absent-pattern", "gone_pattern", "gone-pattern", "missing_pattern", "missing-pattern"),
        "verify_absent_text": ("verify-absent-text", "verify_gone_text", "verify-gone-text", "verify_missing_text", "verify-missing-text", "absent_text", "absent-text", "gone_text", "gone-text", "missing_text", "missing-text"),
        "verify_absent_image": ("verify-absent-image", "verify_gone_image", "verify-gone-image", "verify_missing_image", "verify-missing-image", "absent_image", "absent-image", "gone_image", "gone-image", "missing_image", "missing-image"),
        "verify_absent_pixel": ("verify-absent-pixel", "verify_gone_pixel", "verify-gone-pixel", "verify_missing_pixel", "verify-missing-pixel", "absent_pixel", "absent-pixel", "gone_pixel", "gone-pixel", "missing_pixel", "missing-pixel"),
        "verify_absent_pixel_color": ("verify-absent-pixel-color", "verify_gone_pixel_color", "verify-gone-pixel-color", "verify_missing_pixel_color", "verify-missing-pixel-color", "absent_pixel_color", "absent-pixel-color", "gone_pixel_color", "gone-pixel-color", "missing_pixel_color", "missing-pixel-color"),
        "window_title": ("window-title", "title"),
        "window_name": ("window-name", "target-window-title", "target_title", "target-title"),
        "window_timeout": ("window-timeout", "target_timeout", "target-timeout"),
        "window_layers": ("window-layers", "target_layers", "target-layers"),
        "action_layers": ("action-layers", "control_layers", "control-layers", "inner_layers", "inner-layers"),
        "process_name": ("process-name", "app_name", "app-name"),
        "path_or_name": ("path-or-name",),
        "control_boundary": ("control-boundary", "boundary"),
        "helper_status": ("helper-status",),
        "observe_window": ("observe-window",),
        "include_screenshot": ("include-screenshot", "screenshot"),
        "include_a11y": ("include-a11y", "accessibility"),
        "include_accessibility": ("include-accessibility",),
        "include_ocr": ("include-ocr",),
        "ocr_engine": ("ocr-engine",),
        "ocr_lang": ("ocr-lang",),
        "plan_only": ("plan-only", "dry_run", "dry-run", "preview"),
        "cell_action": ("cell-action",),
        "msaa_path": ("msaa-path",),
        "child_id": ("child-id",),
        "msaa_action": ("msaa-action",),
        "focused_mode": ("focused-mode",),
        "allow_unverified_check_fallback": ("allow-unverified-check-fallback", "allow_visual_check_fallback", "allow-visual-check-fallback", "unsafe_check_fallback", "unsafe-check-fallback"),
        "row_text": ("row-text",),
        "column_name": ("column-name", "header"),
        "max_items": ("max-items",),
    }
    for canonical, keys in aliases.items():
        if normalized.get(canonical) is not None:
            continue
        for key in keys:
            if key in normalized and normalized.get(key) is not None:
                normalized[canonical] = normalized.get(key)
                break
    if normalized.get("column") is None and normalized.get("col") is not None:
        normalized["column"] = normalized.get("col")
    return normalized


def _batch_auto_expect(expectation: Any) -> Dict[str, Any]:
    if isinstance(expectation, dict):
        return dict(expectation)
    return {"path": "$result.ok", "equals": True}


def _batch_auto_branch(
    branch_id: str,
    command: str,
    args: Dict[str, Any],
    *,
    expect: Any = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    branch: Dict[str, Any] = {"id": branch_id, "command": command, "args": {k: v for k, v in args.items() if v is not None}}
    if expect is not False:
        branch["expect"] = _batch_auto_expect(expect)
    if description:
        branch["description"] = description
    return branch


def _batch_auto_layer_enabled(layers: Any, layer: str) -> bool:
    if layers is None:
        return True
    if isinstance(layers, str):
        values = [part.strip().lower().replace("-", "_") for part in re.split(r"[,|\s]+", layers) if part.strip()]
    elif isinstance(layers, (list, tuple, set)):
        values = [str(part).strip().lower().replace("-", "_") for part in layers if str(part).strip()]
    else:
        return True
    if not values:
        return True
    aliases = {
        "semantic": {"semantic", "uia", "smart", "dialog", "popup", "modal"},
        "native": {"native", "win32"},
        "msaa": {"msaa", "accessible", "legacy"},
        "visual": {"visual", "ocr", "image"},
        "input": {"input", "raw", "keyboard", "mouse", "coordinate", "coords"},
    }
    wanted = aliases.get(layer, {layer})
    return bool(set(values) & wanted)


def _batch_auto_bool(args: Dict[str, Any], key: str, default: bool = False) -> bool:
    return _coerce_bool(args.get(key), default)


def _batch_auto_selector_repair_enabled(args: Dict[str, Any]) -> bool:
    value = args.get("selector_repair")
    if value is not None:
        return _coerce_bool(value, True)
    return True


def _batch_auto_selector_variant_limit(args: Dict[str, Any]) -> int:
    value = args.get("selector_variant_limit")
    try:
        return max(0, min(int(value), 8)) if value is not None else 4
    except Exception:
        return 4


def _batch_auto_selector_signature(selector: Dict[str, Any]) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((str(key), json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)) for key, value in selector.items() if value is not None))


def _batch_auto_selector_variants(base: Dict[str, Any], args: Dict[str, Any], *, text_key: str = "name") -> List[Dict[str, Any]]:
    if not _batch_auto_selector_repair_enabled(args):
        return []
    limit = _batch_auto_selector_variant_limit(args)
    if limit <= 0:
        return []
    stable_keys = ("automation_id", "control_type", "class_name", "index")
    text_value = base.get(text_key) or base.get("name") or base.get("item")
    variants: List[Dict[str, Any]] = []

    def add(selector: Dict[str, Any]) -> None:
        cleaned = {key: value for key, value in selector.items() if value is not None}
        if not cleaned:
            return
        if _batch_auto_selector_signature(cleaned) == _batch_auto_selector_signature(base):
            return
        if any(_batch_auto_selector_signature(cleaned) == _batch_auto_selector_signature(existing) for existing in variants):
            return
        variants.append(cleaned)

    common = {
        key: base.get(key)
        for key in ("hwnd", "text", "item", "timeout_ms", "diagnostic", "allow_focus_fallback", "allow_coordinate_fallback", "skip_uia", "verify", "mode", "button", "clicks", "action")
        if base.get(key) is not None
    }
    stable = {key: base.get(key) for key in stable_keys if base.get(key) is not None}
    if stable and (base.get("automation_id") is not None or base.get("index") is not None):
        add({**common, **stable})
    if text_value is not None:
        for keys in (("control_type", "class_name"), ("control_type",), ("class_name",), ()):
            selector = dict(common)
            selector[text_key] = text_value
            for key in keys:
                if base.get(key) is not None:
                    selector[key] = base.get(key)
            if base.get("match") is not None:
                selector["match"] = base.get("match")
            add(selector)
        if _coerce_bool(args.get("allow_weak_selector_fallback"), False):
            selector = {**common, text_key: text_value, "match": "contains"}
            add(selector)
    return variants[:limit]


def _batch_auto_visual_row_enabled(args: Dict[str, Any]) -> bool:
    value = args.get("visual_row_fallback")
    if value is not None:
        return _coerce_bool(value, True)
    return True


def _batch_auto_visual_row_number(args: Dict[str, Any]) -> Optional[int]:
    value = _batch_auto_first(args, "visual_row", "row_number")
    if value is None:
        value = args.get("row")
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _batch_auto_visual_row_args(args: Dict[str, Any], *, scroll: bool = True) -> Optional[Dict[str, Any]]:
    if not _batch_auto_visual_row_enabled(args):
        return None
    hwnd = args.get("hwnd")
    row = _batch_auto_visual_row_number(args)
    if hwnd is None or row is None:
        return None
    keys = (
        "hwnd", "lang", "engine", "max_width", "row_region", "click_x", "x_offset",
        "button", "clicks", "min_row", "max_row", "max_scrolls", "scroll_amount",
        "scroll_x", "scroll_y", "pause", "capture_mode",
    )
    row_args = _batch_auto_copy_args(args, keys)
    row_args["row"] = row
    if "row_region" not in row_args and args.get("region") is not None:
        row_args["row_region"] = args.get("region")
    if "clicks" not in row_args:
        row_args["clicks"] = 1
    if not scroll:
        for key in ("max_scrolls", "scroll_amount", "scroll_x", "scroll_y", "pause"):
            row_args.pop(key, None)
    return row_args


def _batch_auto_add_visual_row_branch(branches: List[Dict[str, Any]], args: Dict[str, Any], *, branch_id: str = "visual_row_scroll_click", description: str = "OCR numbered-row click") -> None:
    row_args = _batch_auto_visual_row_args(args, scroll=True)
    if row_args is None:
        return
    branches.append(_batch_auto_branch(branch_id, "visual_row_scroll_click", row_args, description=description))


def _batch_auto_smart_wait_repair_args(args: Dict[str, Any]) -> Dict[str, Any]:
    if _coerce_bool(args.get("skip_uia"), False):
        return {}
    repair = _batch_auto_first(args, "repair", "action_repair", "selector_repair", "uia_selector_repair")
    repair_timeout = _batch_auto_first(args, "action_repair_timeout", "selector_repair_timeout", "repair_timeout")
    wait_args: Dict[str, Any] = {}
    if repair is not None or repair_timeout is not None:
        wait_args["repair"] = _batch_auto_smart_wait_repair_requested(args)
    if repair_timeout is not None:
        wait_args["repair_timeout"] = repair_timeout
    return wait_args


def _batch_auto_smart_wait_repair_requested(args: Dict[str, Any]) -> bool:
    if _coerce_bool(args.get("skip_uia"), False):
        return False
    repair = _batch_auto_first(args, "repair", "action_repair", "selector_repair", "uia_selector_repair")
    if repair is not None:
        return _coerce_bool(repair, False)
    return _batch_auto_first(args, "action_repair_timeout", "selector_repair_timeout", "repair_timeout") is not None


def _batch_auto_add_semantic_branches(
    branches: List[Dict[str, Any]],
    args: Dict[str, Any],
    branch_id: str,
    command: str,
    selector_args: Dict[str, Any],
    *,
    timeout: Any = None,
    interval: Any = None,
    wait_id: Optional[str] = None,
    text_key: str = "name",
    description: str = "UIA/Win32 smart action",
) -> None:
    if wait_id and (timeout is not None or _batch_auto_smart_wait_repair_requested(args)):
        wait_args = dict(selector_args)
        if timeout is not None:
            wait_args["timeout"] = timeout
        if interval is not None:
            wait_args["interval"] = interval
        wait_args.update(_batch_auto_smart_wait_repair_args(args))
        if command == "smart_wait_text" and args.get("input_timeout") is not None:
            wait_args["input_timeout"] = args.get("input_timeout")
        branches.append(_batch_auto_branch(wait_id, command, wait_args, description=description))
    elif timeout is not None:
        selector_args = dict(selector_args)
        selector_args.update({"timeout": timeout, "interval": interval})
    branches.append(_batch_auto_branch(branch_id, command.replace("_wait_", "_") if wait_id else command, selector_args, description=description))

    base_command = command.replace("_wait_", "_") if wait_id else command
    for index, variant in enumerate(_batch_auto_selector_variants(selector_args, args, text_key=text_key), start=1):
        variant_id = f"{branch_id}_selector_repair_{index}"
        branches.append(_batch_auto_branch(variant_id, base_command, variant, description=f"{description} selector repair"))


def _batch_auto_native_repair_enabled(args: Dict[str, Any]) -> bool:
    value = args.get("native_selector_repair", args.get("native-repair", args.get("win32_selector_repair", args.get("win32-repair"))))
    if value is not None:
        return _coerce_bool(value, True)
    return _batch_auto_selector_repair_enabled(args)


def _batch_auto_uia_repair_enabled(args: Dict[str, Any]) -> bool:
    value = args.get("uia_selector_repair")
    if value is not None:
        return _coerce_bool(value, True)
    return _batch_auto_selector_repair_enabled(args)


def _batch_auto_window_repair_enabled(args: Dict[str, Any]) -> bool:
    value = args.get("window_selector_repair")
    if value is not None:
        return _coerce_bool(value, True)
    return _batch_auto_selector_repair_enabled(args)


def _batch_auto_native_find_selector(args: Dict[str, Any], *, name_value: Any = None, control_type_default: Optional[str] = None) -> Dict[str, Any]:
    selector = _batch_auto_copy_args(args, (
        "hwnd", "name", "automation_id", "control_type", "class_name", "match",
        "include_invisible", "include_self", "timeout_ms", "max_items", "max_children",
        "diagnostic", "min_score",
    ))
    if name_value is not None and selector.get("name") is None:
        selector["name"] = name_value
    if selector.get("control_type") is None and control_type_default:
        selector["control_type"] = control_type_default
    selector.setdefault("limit", 1)
    selector.setdefault("diagnostic", False)
    return {key: value for key, value in selector.items() if value is not None}


def _batch_auto_native_suggested_find_args(probe_step_id: str, original_find_args: Dict[str, Any]) -> Dict[str, Any]:
    suggestion_root = f"$steps.{probe_step_id}.result.original_result.failure_summary.selector_suggestions.0"
    return {
        "hwnd": original_find_args.get("hwnd"),
        "suggestion": suggestion_root,
        "original": original_find_args,
        "limit": 1,
        "include_invisible": original_find_args.get("include_invisible"),
        "include_self": original_find_args.get("include_self"),
        "min_score": original_find_args.get("min_score"),
        "timeout_ms": original_find_args.get("timeout_ms"),
        "max_items": original_find_args.get("max_items"),
        "max_children": original_find_args.get("max_children"),
        "diagnostic": original_find_args.get("diagnostic"),
    }


def _batch_auto_uia_find_selector(
    args: Dict[str, Any],
    *,
    name_value: Any = None,
    control_type_default: Optional[str] = None,
    pattern_default: Optional[str] = None,
) -> Dict[str, Any]:
    selector = _batch_auto_copy_args(args, (
        "hwnd", "name", "automation_id", "control_type", "class_name", "value",
        "pattern", "match", "enabled_only", "visible_only", "max_depth",
        "max_elements", "view",
    ))
    if name_value is not None and selector.get("name") is None and selector.get("automation_id") is None:
        selector["name"] = name_value
    if selector.get("control_type") is None and control_type_default:
        selector["control_type"] = control_type_default
    if selector.get("pattern") is None and pattern_default:
        selector["pattern"] = pattern_default
    if args.get("include_invisible") is not None and selector.get("visible_only") is None:
        selector["visible_only"] = not _coerce_bool(args.get("include_invisible"), False)
    selector.setdefault("limit", 1)
    return {key: value for key, value in selector.items() if value is not None}


def _batch_auto_uia_suggested_find_args(probe_step_id: str, original_find_args: Dict[str, Any]) -> Dict[str, Any]:
    suggestion_root = f"$steps.{probe_step_id}.result.original_result.failure_summary.selector_suggestions.0"
    return {
        "hwnd": original_find_args.get("hwnd"),
        "suggestion": suggestion_root,
        "original": original_find_args,
        "limit": 1,
        "max_depth": original_find_args.get("max_depth"),
        "max_elements": original_find_args.get("max_elements"),
        "view": f"$steps.{probe_step_id}.result.original_result.view",
        "allow_suggestion_index": True,
    }


def _batch_auto_uia_repair_branch(
    branch_id: str,
    args: Dict[str, Any],
    find_args: Dict[str, Any],
    *,
    action_command: str,
    action_args: Dict[str, Any],
    description: str = "UIA selector repair",
) -> Optional[Dict[str, Any]]:
    if not _batch_auto_uia_repair_enabled(args) or _coerce_bool(args.get("skip_uia"), False):
        return None
    hwnd = args.get("hwnd")
    if hwnd is None:
        return None
    selector_has_signal = any(find_args.get(key) is not None for key in ("name", "automation_id", "control_type", "class_name", "value"))
    if not selector_has_signal:
        return None

    probe_id = f"{branch_id}_probe"
    action_try_id = f"{branch_id}_action"
    suggested_find_id = f"{branch_id}_suggested_find"
    suggestion_ref = f"$steps.{probe_id}.result.original_result.failure_summary.selector_suggestions.0"
    direct_index_ref = f"$steps.{probe_id}.result.matches.0.index"
    direct_view_ref = f"$steps.{probe_id}.result.view"
    suggested_index_ref = f"$steps.{suggested_find_id}.result.matches.0.index"
    suggested_view_ref = f"$steps.{suggested_find_id}.result.view"

    def action_step(step_id: str, index_ref: str, view_ref: str, action_description: str) -> Dict[str, Any]:
        step_args = dict(action_args)
        step_args["hwnd"] = hwnd
        step_args["index"] = index_ref
        step_args["view"] = view_ref
        return _batch_auto_branch(
            step_id,
            action_command,
            step_args,
            expect={"path": "$result.ok", "equals": True},
            description=action_description,
        )

    direct_action = action_step(
        f"{branch_id}_direct_action",
        direct_index_ref,
        direct_view_ref,
        f"{description} direct action",
    )
    direct_action["when"] = {"path": direct_index_ref, "exists": True}

    suggested_find = _batch_auto_branch(
        suggested_find_id,
        "uia_selector_repair_find",
        _batch_auto_uia_suggested_find_args(probe_id, find_args),
        expect={"path": "$result.matches.0.index", "exists": True},
        description=f"{description} suggested selector",
    )
    suggested_find["when"] = {"path": suggestion_ref, "exists": True}

    suggested_action = action_step(
        f"{branch_id}_suggested_action",
        suggested_index_ref,
        suggested_view_ref,
        f"{description} suggested action",
    )
    suggested_action["when"] = {"path": suggested_index_ref, "exists": True}

    return {
        "id": branch_id,
        "description": description,
        "steps": [
            {
                **_batch_auto_branch(
                    probe_id,
                    "uia_find",
                    find_args,
                    expect=False,
                    description=f"{description} probe",
                ),
                "optional": True,
            },
            {
                "id": action_try_id,
                "command": "batch_try",
                "branches": [
                    {
                        "id": f"{branch_id}_direct",
                        "steps": [direct_action],
                    },
                    {
                        "id": f"{branch_id}_suggested",
                        "steps": [suggested_find, suggested_action],
                    },
                ],
                "expect": {"path": "$result.ok", "equals": True},
            },
        ],
    }


def _batch_auto_desktop_uia_repair_branch(
    branch_id: str,
    args: Dict[str, Any],
    find_args: Dict[str, Any],
    *,
    action_args: Dict[str, Any],
    description: str = "desktop-root UIA selector repair",
) -> Optional[Dict[str, Any]]:
    if not _batch_auto_uia_repair_enabled(args) or _coerce_bool(args.get("skip_uia"), False):
        return None
    selector_has_signal = any(find_args.get(key) is not None for key in ("name", "automation_id", "control_type", "class_name", "value", "pattern"))
    if not selector_has_signal:
        return None

    probe_id = f"{branch_id}_probe"
    action_try_id = f"{branch_id}_action"
    suggested_find_id = f"{branch_id}_suggested_find"
    suggestion_ref = f"$steps.{probe_id}.result.original_result.failure_summary.selector_suggestions.0"
    direct_index_ref = f"$steps.{probe_id}.result.matches.0.index"
    direct_view_ref = f"$steps.{probe_id}.result.view"
    suggested_index_ref = f"$steps.{suggested_find_id}.result.matches.0.index"
    suggested_view_ref = f"$steps.{suggested_find_id}.result.view"
    probe_args = dict(find_args)
    probe_args["limit"] = 1
    repair_find_args = dict(find_args)
    repair_find_args["hwnd"] = _DESKTOP_UIA_KEY
    repair_find_args["limit"] = 1

    def action_step(step_id: str, index_ref: str, view_ref: str, action_description: str) -> Dict[str, Any]:
        step_args = dict(action_args)
        step_args["index"] = index_ref
        step_args["view"] = view_ref
        return _batch_auto_branch(
            step_id,
            "desktop_action",
            step_args,
            expect={"path": "$result.ok", "equals": True},
            description=action_description,
        )

    direct_action = action_step(
        f"{branch_id}_direct_action",
        direct_index_ref,
        direct_view_ref,
        f"{description} direct action",
    )
    direct_action["when"] = {"path": direct_index_ref, "exists": True}

    suggested_find = _batch_auto_branch(
        suggested_find_id,
        "uia_selector_repair_find",
        _batch_auto_uia_suggested_find_args(probe_id, repair_find_args),
        expect={"path": "$result.matches.0.index", "exists": True},
        description=f"{description} suggested selector",
    )
    suggested_find["when"] = {"path": suggestion_ref, "exists": True}

    suggested_action = action_step(
        f"{branch_id}_suggested_action",
        suggested_index_ref,
        suggested_view_ref,
        f"{description} suggested action",
    )
    suggested_action["when"] = {"path": suggested_index_ref, "exists": True}

    return {
        "id": branch_id,
        "description": description,
        "steps": [
            {
                **_batch_auto_branch(
                    probe_id,
                    "desktop_find",
                    probe_args,
                    expect=False,
                    description=f"{description} probe",
                ),
                "optional": True,
            },
            {
                "id": action_try_id,
                "command": "batch_try",
                "branches": [
                    {
                        "id": f"{branch_id}_direct",
                        "steps": [direct_action],
                    },
                    {
                        "id": f"{branch_id}_suggested",
                        "steps": [suggested_find, suggested_action],
                    },
                ],
                "expect": {"path": "$result.ok", "equals": True},
            },
        ],
    }


def _batch_auto_uia_cell_identity(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row": args.get("row"),
        "column": args.get("column"),
        "row_text": args.get("row_text"),
        "column_name": args.get("column_name"),
    }


def _batch_auto_uia_cell_identity_complete(identity: Dict[str, Any]) -> bool:
    return bool(
        (identity.get("row") is not None or identity.get("row_text") is not None)
        and (identity.get("column") is not None or identity.get("column_name") is not None)
    )


def _batch_auto_uia_cell_repair_find_args(
    args: Dict[str, Any],
    find_args: Dict[str, Any],
    *,
    probe_step_id: Optional[str] = None,
    suggested: bool = False,
) -> Dict[str, Any]:
    identity = _batch_auto_uia_cell_identity(args)
    original = dict(find_args)
    original.update({key: value for key, value in identity.items() if value is not None})
    if original.get("match") is None:
        original["match"] = args.get("match", "contains")
    repair_args: Dict[str, Any] = {
        "hwnd": find_args.get("hwnd"),
        "original": original,
        "row": identity.get("row"),
        "column": identity.get("column"),
        "row_text": identity.get("row_text"),
        "column_name": identity.get("column_name"),
        "limit": 1,
        "max_depth": find_args.get("max_depth"),
        "max_elements": find_args.get("max_elements"),
        "view": find_args.get("view"),
    }
    if suggested and probe_step_id:
        suggestion_root = f"$steps.{probe_step_id}.result.original_result.failure_summary.selector_suggestions.0"
        repair_args["suggestion"] = suggestion_root
        repair_args["view"] = f"$steps.{probe_step_id}.result.original_result.view"
    return {key: value for key, value in repair_args.items() if value is not None}


def _batch_auto_uia_cell_action_spec(args: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    text = _batch_auto_first(args, "text", "value")
    raw_action = args.get("action")
    action = str(raw_action if raw_action is not None else ("set" if text is not None else "get")).strip().lower().replace("-", "_").replace(" ", "_")
    if action in ("read", "value", "info"):
        action = "get"
    if action in ("write", "set_text", "set_value", "set_cell"):
        action = "set"
    if action == "get":
        return (
            "uia_element",
            {
                "max_depth": args.get("max_depth"),
                "max_elements": args.get("max_elements"),
            },
            {"path": "$result.index", "exists": True},
        )
    if action == "set":
        if text is None:
            return None
        return (
            "uia_set_value",
            {
                "value": text,
                "max_depth": args.get("max_depth"),
                "max_elements": args.get("max_elements"),
            },
            {"path": "$result.ok", "equals": True},
        )
    if action in ("select", "click", "invoke", "open", "press"):
        uia_action = "Invoke" if action in ("click", "invoke", "open", "press") else "Select"
        return (
            "uia_action",
            {
                "action": uia_action,
                "max_depth": args.get("max_depth"),
                "max_elements": args.get("max_elements"),
            },
            {"path": "$result.ok", "equals": True},
        )
    return None


def _batch_auto_uia_cell_repair_branch(
    branch_id: str,
    args: Dict[str, Any],
    *,
    description: str = "UIA cell selector repair",
) -> Optional[Dict[str, Any]]:
    if not _batch_auto_uia_repair_enabled(args) or _coerce_bool(args.get("skip_uia"), False):
        return None
    hwnd = args.get("hwnd")
    if hwnd is None:
        return None
    identity = _batch_auto_uia_cell_identity(args)
    if not _batch_auto_uia_cell_identity_complete(identity):
        return None
    action_spec = _batch_auto_uia_cell_action_spec(args)
    if action_spec is None:
        return None
    action_command, action_args, action_expect = action_spec
    find_args = _batch_auto_uia_find_selector(
        args,
        control_type_default=args.get("control_type"),
        pattern_default=args.get("pattern") or "GridItem",
    )
    if action_command == "uia_set_value":
        find_args.pop("value", None)
    if not any(find_args.get(key) is not None for key in ("name", "automation_id", "control_type", "class_name", "value", "pattern")):
        return None

    probe_id = f"{branch_id}_probe"
    direct_find_id = f"{branch_id}_direct_find"
    suggested_find_id = f"{branch_id}_suggested_find"
    suggestion_ref = f"$steps.{probe_id}.result.original_result.failure_summary.selector_suggestions.0"
    direct_index_ref = f"$steps.{direct_find_id}.result.matches.0.index"
    direct_view_ref = f"$steps.{direct_find_id}.result.view"
    suggested_index_ref = f"$steps.{suggested_find_id}.result.matches.0.index"
    suggested_view_ref = f"$steps.{suggested_find_id}.result.view"

    def action_step(step_id: str, index_ref: str, view_ref: str, action_description: str) -> Dict[str, Any]:
        step_args = dict(action_args)
        step_args["hwnd"] = hwnd
        step_args["index"] = index_ref
        step_args["view"] = view_ref
        return _batch_auto_branch(
            step_id,
            action_command,
            step_args,
            expect=action_expect,
            description=action_description,
        )

    direct_find = _batch_auto_branch(
        direct_find_id,
        "uia_cell_selector_repair_find",
        _batch_auto_uia_cell_repair_find_args(args, find_args),
        expect={"path": "$result.matches.0.index", "exists": True},
        description=f"{description} original selector",
    )
    suggested_find = _batch_auto_branch(
        suggested_find_id,
        "uia_cell_selector_repair_find",
        _batch_auto_uia_cell_repair_find_args(args, find_args, probe_step_id=probe_id, suggested=True),
        expect={"path": "$result.matches.0.index", "exists": True},
        description=f"{description} suggested selector",
    )
    suggested_find["when"] = {"path": suggestion_ref, "exists": True}

    return {
        "id": branch_id,
        "description": description,
        "steps": [
            {
                **_batch_auto_branch(
                    probe_id,
                    "uia_find",
                    find_args,
                    expect=False,
                    description=f"{description} probe",
                ),
                "optional": True,
            },
            {
                "id": f"{branch_id}_action",
                "command": "batch_try",
                "branches": [
                    {
                        "id": f"{branch_id}_direct",
                        "steps": [
                            direct_find,
                            action_step(
                                f"{branch_id}_direct_action",
                                direct_index_ref,
                                direct_view_ref,
                                f"{description} direct action",
                            ),
                        ],
                    },
                    {
                        "id": f"{branch_id}_suggested",
                        "steps": [
                            suggested_find,
                            action_step(
                                f"{branch_id}_suggested_action",
                                suggested_index_ref,
                                suggested_view_ref,
                                f"{description} suggested action",
                            ),
                        ],
                    },
                ],
                "expect": {"path": "$result.ok", "equals": True},
            },
        ],
    }


def _batch_auto_native_repair_branch(
    branch_id: str,
    args: Dict[str, Any],
    *,
    action_command: str,
    action_args: Dict[str, Any],
    name_value: Any = None,
    control_type_default: Optional[str] = None,
    description: str = "Win32 native selector repair",
) -> Optional[Dict[str, Any]]:
    if not _batch_auto_native_repair_enabled(args):
        return None
    hwnd = args.get("hwnd")
    if hwnd is None:
        return None
    find_args = _batch_auto_native_find_selector(args, name_value=name_value, control_type_default=control_type_default)
    selector_has_signal = any(find_args.get(key) is not None for key in ("name", "automation_id", "control_type", "class_name"))
    if not selector_has_signal:
        return None

    probe_id = f"{branch_id}_probe"
    suggested_find_id = f"{branch_id}_suggested_find"
    probe_hwnd_ref = f"$steps.{probe_id}.result.matches.0.hwnd"
    suggested_hwnd_ref = f"$steps.{suggested_find_id}.result.matches.0.hwnd"
    suggestion_ref = f"$steps.{probe_id}.result.original_result.failure_summary.selector_suggestions.0"
    direct_action_args = dict(action_args)
    direct_action_args["hwnd"] = probe_hwnd_ref
    steps: List[Dict[str, Any]] = [
        {
            **_batch_auto_branch(
                probe_id,
                "win32_control_find",
                find_args,
                expect=False,
                description=f"{description} probe",
            ),
            "optional": True,
        },
        {
            **_batch_auto_branch(
                f"{branch_id}_direct_action",
                action_command,
                direct_action_args,
                description=f"{description} direct action",
            ),
            "when": {"path": probe_hwnd_ref, "exists": True},
        },
        _batch_auto_branch(
            suggested_find_id,
            "win32_selector_repair_find",
            _batch_auto_native_suggested_find_args(probe_id, find_args),
            expect={"path": "$result.matches.0.hwnd", "exists": True},
            description=f"{description} suggested selector",
        ),
    ]
    steps[-1]["when"] = {"path": suggestion_ref, "exists": True}
    repaired_action_args = dict(action_args)
    repaired_action_args["hwnd"] = suggested_hwnd_ref
    steps.append({
        **_batch_auto_branch(
            f"{branch_id}_suggested_action",
            action_command,
            repaired_action_args,
            description=f"{description} suggested action",
        ),
        "when": {"path": suggested_hwnd_ref, "exists": True},
    })
    return {
        "id": branch_id,
        "description": description,
        "steps": steps,
    }


def _batch_auto_window_repair_find_args(probe_step_id: str, original_wait_args: Dict[str, Any]) -> Dict[str, Any]:
    suggestion_root = f"$steps.{probe_step_id}.result.original_result.failure_summary.selector_suggestions.0"
    repair_args: Dict[str, Any] = {
        "suggestion": suggestion_root,
        "original": dict(original_wait_args),
        "timeout": original_wait_args.get("timeout"),
        "interval": original_wait_args.get("interval"),
        "match": original_wait_args.get("match"),
        "stable_ticks": original_wait_args.get("stable_ticks", original_wait_args.get("stable-ticks")),
        "probe_original": False,
    }
    return {key: value for key, value in repair_args.items() if value is not None}


def _batch_auto_window_repair_branch(
    args: Dict[str, Any],
    wait_args: Dict[str, Any],
    *,
    activate: bool,
    restore: bool,
    boundary: bool,
    helper: bool,
    observe_window: bool,
) -> Optional[Dict[str, Any]]:
    if not _batch_auto_window_repair_enabled(args):
        return None
    selector_has_signal = any(wait_args.get(key) is not None for key in ("hwnd", "title", "process"))
    if not selector_has_signal:
        return None

    probe_id = "window_selector_repair_probe"
    pick_id = "window_selector_repair_pick"
    suggested_find_id = "window_selector_repair_suggested_find"
    suggestion_ref = f"$steps.{probe_id}.result.original_result.failure_summary.selector_suggestions.0"
    hwnd_ref = f"$steps.{pick_id}.result.value.hwnd"
    window_ref = f"$steps.{pick_id}.result.value.window"

    steps: List[Dict[str, Any]] = [
        {
            **_batch_auto_branch(
                probe_id,
                "wait_window",
                wait_args,
                expect=False,
                description="window selector repair probe",
            ),
            "optional": True,
        },
        {
            "id": pick_id,
            "command": "batch_try",
            "branches": [
                {
                    "id": "window_selector_repair_direct",
                    "command": "batch_value",
                    "args": {
                        "value": {
                            "hwnd": f"$steps.{probe_id}.result.window.hwnd",
                            "window": f"$steps.{probe_id}.result.window",
                            "source": "window_selector_repair_direct",
                        },
                    },
                    "when": {"path": f"$steps.{probe_id}.result.window.hwnd", "exists": True},
                    "expect": {"path": "$result.value.hwnd", "exists": True},
                },
                {
                    "id": "window_selector_repair_suggested",
                    "steps": [
                        {
                            **_batch_auto_branch(
                                suggested_find_id,
                                "window_selector_repair_find",
                                _batch_auto_window_repair_find_args(probe_id, wait_args),
                                expect={"path": "$result.window.hwnd", "exists": True},
                                description="repair using suggested window selector",
                            ),
                            "when": {"path": suggestion_ref, "exists": True},
                            "extract": {"hwnd": "$result.window.hwnd", "window": "$result.window"},
                        },
                        {
                            "id": "window_selector_repair_suggested_ready",
                            "command": "batch_value",
                            "args": {
                                "value": {
                                    "hwnd": f"$steps.{suggested_find_id}.result.value.hwnd",
                                    "window": f"$steps.{suggested_find_id}.result.value.window",
                                    "source": "window_selector_repair_suggested",
                                },
                            },
                            "when": {"path": f"$steps.{suggested_find_id}.result.value.hwnd", "exists": True},
                            "expect": {"path": "$result.value.hwnd", "exists": True},
                        },
                    ],
                },
            ],
            "expect": {"path": "$result.result.value.hwnd", "exists": True},
            "extract": {"hwnd": "$result.result.value.hwnd", "window": "$result.result.value.window"},
        },
    ]
    if activate:
        steps.append({
            "id": "window_selector_repair_focus",
            "command": "focus_hwnd",
            "args": {
                "hwnd": hwnd_ref,
                "timeout": min(float(args.get("timeout") or args.get("wait_timeout") or 1.0), 2.0),
                "restore": restore,
            },
            "expect": {"path": "$result.ok", "equals": True},
        })
    if boundary:
        boundary_step: Dict[str, Any] = {
            "id": "window_selector_repair_boundary",
            "command": "control_boundary",
            "args": {"hwnd": hwnd_ref},
            "expect": {"path": "$result.ok", "equals": True},
        }
        if helper:
            boundary_step["extract"] = {"needs_elevation": "$result.needs_elevation"}
        steps.append(boundary_step)
    if helper:
        steps.append({
            "id": "window_selector_repair_helper",
            "command": "helper_status",
            "args": {
                "elevated": "$steps.window_selector_repair_boundary.result.value.needs_elevation",
                "start": "$steps.window_selector_repair_boundary.result.value.needs_elevation",
            },
            "when": {"path": "$steps.window_selector_repair_boundary.result.value.needs_elevation", "equals": True},
            "optional": True,
        })
    if observe_window:
        observe_args = {
            "hwnd": hwnd_ref,
            "include_accessibility": _batch_auto_bool(args, "include_a11y", False),
            "include_ocr": _batch_auto_bool(args, "ocr", False),
            "ocr_on_accessibility_error": _batch_auto_bool(args, "ocr", False),
            "view": args.get("view"),
            "max_depth": args.get("max_depth"),
            "max_elements": args.get("max_elements"),
            "capture_mode": args.get("capture_mode"),
        }
        steps.append({
            "id": "window_selector_repair_observe",
            "command": "observe",
            "args": {key: value for key, value in observe_args.items() if value is not None},
            "optional": True,
        })
    steps.append({
        "id": "window_selector_repair_ready",
        "command": "batch_value",
        "args": {
            "value": {
                "hwnd": hwnd_ref,
                "window": window_ref,
                "source": "window_selector_repair",
            },
        },
    })
    return {
        "id": "window_selector_repair",
        "description": "probe failed window selector, then retry using diagnostic suggestion",
        "steps": steps,
    }


def _batch_auto_post_spec_present(args: Dict[str, Any]) -> bool:
    if not isinstance(args, dict):
        return False
    keys = (
        "post_delay", "post_observe", "post_event", "post_steps",
        "verify_selector", "verify_name", "verify_value", "verify_automation_id",
        "verify_control_type", "verify_class_name", "verify_pattern",
        "verify_text", "verify_image", "verify_pixel", "verify_pixel_color",
        "verify_pixel_x", "verify_pixel_y",
        "post_stable", "post_stable_region", "post_stable_ticks",
        "post_difference_threshold", "post_pixel_threshold",
        "post_stable_max_width",
        "post_uia_stable", "post_uia_stable_ticks",
        "post_uia_stable_max_depth", "post_uia_stable_max_elements",
        "post_uia_stable_view", "post_uia_stable_include_values",
        "post_uia_stable_rect_bucket",
        "verify_win32_state", "verify_native_state", "verify_state",
        "verify_win32_present", "verify_native_present", "verify_present",
        "verify_win32_absent", "verify_native_absent", "verify_absent",
        "verify_checked", "verify_selected", "verify_expanded", "verify_visited",
        "verify_win32_expected", "verify_native_expected", "verify_expected",
        "verify_win32_index", "verify_native_index", "verify_item_index",
        "verify_win32_text", "verify_native_text", "verify_item",
        "verify_win32_match", "verify_native_match",
        "verify_win32_timeout_ms", "verify_native_timeout_ms",
        "verify_win32_max_items", "verify_native_max_items",
        "verify_absent_selector", "verify_absent_name", "verify_absent_value",
        "verify_absent_automation_id", "verify_absent_control_type",
        "verify_absent_class_name", "verify_absent_pattern",
        "verify_absent_text", "verify_absent_image",
        "verify_absent_pixel", "verify_absent_pixel_color",
    )
    return any(key in args and args.get(key) is not None for key in keys)


def _batch_auto_post_timeout(args: Dict[str, Any]) -> Any:
    return _batch_auto_first(args, "post_timeout", "timeout", "wait_timeout")


def _batch_auto_post_interval(args: Dict[str, Any]) -> Any:
    return _batch_auto_first(args, "post_interval", "interval")


_BATCH_AUTO_POST_ARG_KEYS = (
    "post_delay", "post_timeout", "post_interval", "post_observe", "post_event",
    "post_steps", "verify_selector", "verify_name", "verify_value",
    "verify_automation_id", "verify_control_type", "verify_class_name",
    "verify_pattern", "verify_text", "verify_image", "verify_pixel",
    "verify_pixel_color", "verify_pixel_x", "verify_pixel_y",
    "verify_pixel_tolerance", "verify_pixel_mode",
    "post_stable", "post_stable_region", "post_stable_ticks",
    "post_difference_threshold", "post_pixel_threshold",
    "post_stable_max_width",
    "post_uia_stable", "post_uia_stable_ticks",
    "post_uia_stable_max_depth", "post_uia_stable_max_elements",
    "post_uia_stable_view", "post_uia_stable_include_values",
    "post_uia_stable_rect_bucket",
    "verify_win32_state", "verify_native_state", "verify_state",
    "verify_win32_present", "verify_native_present", "verify_present",
    "verify_win32_absent", "verify_native_absent", "verify_absent",
    "native_wait_repair", "native_wait_repair_match",
    "native_wait_repair_timeout",
    "verify_checked", "verify_selected", "verify_expanded", "verify_visited",
    "verify_win32_expected", "verify_native_expected", "verify_expected",
    "verify_win32_index", "verify_native_index", "verify_item_index",
    "verify_win32_text", "verify_native_text", "verify_item",
    "verify_win32_match", "verify_native_match",
    "verify_win32_timeout_ms", "verify_native_timeout_ms",
    "verify_win32_max_items", "verify_native_max_items",
    "verify_absent_selector", "verify_absent_name", "verify_absent_value",
    "verify_absent_automation_id", "verify_absent_control_type",
    "verify_absent_class_name", "verify_absent_pattern",
    "verify_absent_text", "verify_absent_image",
    "verify_absent_pixel", "verify_absent_pixel_color",
    "match", "max_depth", "max_elements", "view", "capture_mode", "max_width",
    "lang", "engine", "region", "confidence", "scale_min", "scale_max",
    "scale_step",
)


def _batch_auto_post_selector(args: Dict[str, Any], *, absent: bool = False) -> Dict[str, Any]:
    selector: Dict[str, Any] = {}
    prefix = "verify_absent_" if absent else "verify_"
    raw_selector = args.get(f"{prefix}selector")
    if isinstance(raw_selector, dict):
        selector.update(_batch_auto_normalize_args(dict(raw_selector)))
    mapping = {
        "name": f"{prefix}name",
        "value": f"{prefix}value",
        "automation_id": f"{prefix}automation_id",
        "control_type": f"{prefix}control_type",
        "class_name": f"{prefix}class_name",
        "pattern": f"{prefix}pattern",
    }
    for target_key, source_key in mapping.items():
        if selector.get(target_key) is None and args.get(source_key) is not None:
            selector[target_key] = args.get(source_key)
    for key in ("match", "max_depth", "max_elements", "view", "enabled_only", "visible_only"):
        verify_key = f"{prefix}{key}"
        positive_verify_key = f"verify_{key}"
        if selector.get(key) is None and args.get(verify_key) is not None:
            selector[key] = args.get(verify_key)
        elif absent and selector.get(key) is None and args.get(positive_verify_key) is not None:
            selector[key] = args.get(positive_verify_key)
        elif selector.get(key) is None and args.get(key) is not None:
            selector[key] = args.get(key)
    if not any(selector.get(key) is not None for key in ("name", "value", "automation_id", "control_type", "class_name", "pattern")):
        return {}
    return {key: value for key, value in selector.items() if value is not None}


def _batch_auto_post_pixel_args(args: Dict[str, Any], *, absent: bool = False) -> Dict[str, Any]:
    prefix = "verify_absent_" if absent else "verify_"
    spec = args.get(f"{prefix}pixel")
    pixel_args: Dict[str, Any] = {}
    if isinstance(spec, dict):
        pixel_args.update(_batch_auto_normalize_args(dict(spec)))
    elif spec is not None:
        pixel_args["color"] = spec
    color = args.get(f"{prefix}pixel_color")
    if color is not None and pixel_args.get("color") is None:
        pixel_args["color"] = color
    for key in ("x", "y"):
        value = args.get(f"{prefix}pixel_{key}")
        if value is not None and pixel_args.get(key) is None:
            pixel_args[key] = value
    for key in ("tolerance", "mode", "screenshot_id", "max_width", "capture_mode"):
        value = args.get(f"{prefix}pixel_{key}")
        if value is None:
            value = args.get(f"verify_pixel_{key}")
        if value is None:
            value = args.get(key)
        if value is not None and pixel_args.get(key) is None:
            pixel_args[key] = value
    if absent:
        pixel_args["mode"] = "not_equals"
    return {key: value for key, value in pixel_args.items() if value is not None}


def _batch_auto_post_stable_args(args: Dict[str, Any]) -> Dict[str, Any]:
    stable_args: Dict[str, Any] = {}
    spec = args.get("post_stable")
    if isinstance(spec, dict):
        stable_args.update(_batch_auto_normalize_args(dict(spec)))
    for source_key, target_key in (
        ("post_stable_region", "region"),
        ("post_stable_ticks", "stable_ticks"),
        ("post_difference_threshold", "difference_threshold"),
        ("post_pixel_threshold", "pixel_threshold"),
        ("post_stable_max_width", "comparison_max_width"),
    ):
        value = args.get(source_key)
        if value is not None and stable_args.get(target_key) is None:
            stable_args[target_key] = value
    for key in ("region", "stable_ticks", "difference_threshold", "pixel_threshold", "max_width", "comparison_max_width", "capture_mode"):
        value = args.get(key)
        if value is not None and stable_args.get(key) is None:
            stable_args[key] = value
    return {key: value for key, value in stable_args.items() if value is not None}


def _batch_auto_pre_visual_stable_enabled(args: Dict[str, Any]) -> bool:
    spec = args.get("pre_visual_stable")
    if isinstance(spec, dict):
        return True
    return _coerce_bool(spec, False)


def _batch_auto_pre_visual_stable_args(args: Dict[str, Any]) -> Dict[str, Any]:
    stable_args: Dict[str, Any] = {}
    spec = args.get("pre_visual_stable")
    if isinstance(spec, dict):
        stable_args.update(_batch_auto_normalize_args(dict(spec)))
    for source_key, target_key in (
        ("pre_stable_region", "region"),
        ("pre_stable_ticks", "stable_ticks"),
        ("pre_stable_timeout", "timeout"),
        ("pre_stable_interval", "interval"),
        ("pre_difference_threshold", "difference_threshold"),
        ("pre_pixel_threshold", "pixel_threshold"),
        ("pre_stable_max_width", "comparison_max_width"),
    ):
        value = args.get(source_key)
        if value is not None and stable_args.get(target_key) is None:
            stable_args[target_key] = value
    for key in ("region", "stable_ticks", "difference_threshold", "pixel_threshold", "max_width", "comparison_max_width", "capture_mode"):
        value = args.get(key)
        if value is not None and stable_args.get(key) is None:
            stable_args[key] = value
    stable_args.setdefault("timeout", 1.0)
    stable_args.setdefault("interval", 0.1)
    stable_args.setdefault("stable_ticks", 2)
    return {key: value for key, value in stable_args.items() if value is not None}


def _batch_auto_pre_visual_stable_step(args: Dict[str, Any], hwnd_ref: Any, *, id_prefix: str = "visual", default_desktop: bool = False) -> Optional[Dict[str, Any]]:
    if not _batch_auto_pre_visual_stable_enabled(args):
        return None
    desktop = _coerce_bool(args.get("desktop"), default_desktop or hwnd_ref is None)
    stable_args = _batch_auto_pre_visual_stable_args(args)
    command = "desktop_visual_stable_wait" if desktop else "visual_stable_wait"
    if not desktop and hwnd_ref is not None:
        stable_args["hwnd"] = hwnd_ref
    return _batch_auto_branch(
        f"{id_prefix}_pre_visual_stable",
        command,
        stable_args,
        expect={"path": "$result.stable", "equals": True},
        description="wait for visual stability before visual fallback",
    )


def _batch_auto_with_pre_visual_stable(branch: Dict[str, Any], args: Dict[str, Any], hwnd_ref: Any = None, *, id_prefix: Optional[str] = None, default_desktop: bool = False) -> Dict[str, Any]:
    if not isinstance(branch, dict) or not _batch_auto_pre_visual_stable_enabled(args):
        return branch
    resolved_hwnd = hwnd_ref if hwnd_ref is not None else args.get("hwnd")
    prefix = id_prefix or str(branch.get("id") or "visual")
    stable_step = _batch_auto_pre_visual_stable_step(args, resolved_hwnd, id_prefix=prefix, default_desktop=default_desktop)
    if not stable_step:
        return branch
    updated = copy.deepcopy(branch)
    branch_steps, _, _ = _batch_branch_steps(updated)
    if branch_steps:
        updated["steps"] = [stable_step] + copy.deepcopy(branch_steps)
        updated.pop("command", None)
        updated.pop("args", None)
        updated.pop("path", None)
        updated.pop("data", None)
        updated.pop("expect", None)
        return updated
    return updated


def _batch_auto_apply_pre_visual_stable_to_branches(branches: List[Dict[str, Any]], args: Dict[str, Any], hwnd_ref: Any = None, *, start: int = 0, default_desktop: bool = False) -> List[Dict[str, Any]]:
    if not _batch_auto_pre_visual_stable_enabled(args):
        return branches
    updated = list(branches)
    for index in range(max(int(start or 0), 0), len(updated)):
        branch = updated[index]
        branch_id = str(branch.get("id") or f"visual_{index}") if isinstance(branch, dict) else f"visual_{index}"
        updated[index] = _batch_auto_with_pre_visual_stable(branch, args, hwnd_ref, id_prefix=branch_id, default_desktop=default_desktop)
    return updated


def _batch_auto_pre_uia_stable_enabled(args: Dict[str, Any]) -> bool:
    spec = args.get("pre_uia_stable")
    if isinstance(spec, dict):
        return True
    return _coerce_bool(spec, False)


def _batch_auto_pre_uia_stable_args(args: Dict[str, Any]) -> Dict[str, Any]:
    stable_args: Dict[str, Any] = {}
    spec = args.get("pre_uia_stable")
    if isinstance(spec, dict):
        stable_args.update(_batch_auto_normalize_args(dict(spec)))
    for source_key, target_key in (
        ("pre_uia_stable_ticks", "stable_ticks"),
        ("pre_uia_stable_timeout", "timeout"),
        ("pre_uia_stable_interval", "interval"),
        ("pre_uia_stable_max_depth", "max_depth"),
        ("pre_uia_stable_max_elements", "max_elements"),
        ("pre_uia_stable_view", "view"),
        ("pre_uia_stable_include_values", "include_values"),
        ("pre_uia_stable_rect_bucket", "rect_bucket"),
    ):
        value = args.get(source_key)
        if value is not None and stable_args.get(target_key) is None:
            stable_args[target_key] = value
    for key in ("stable_ticks", "max_depth", "max_elements", "view", "include_values", "rect_bucket"):
        value = args.get(key)
        if value is not None and stable_args.get(key) is None:
            stable_args[key] = value
    stable_args.setdefault("timeout", 1.0)
    stable_args.setdefault("interval", 0.1)
    stable_args.setdefault("stable_ticks", 2)
    if stable_args.get("include_values") is not None:
        stable_args["include_values"] = _coerce_bool(stable_args.get("include_values"), False)
    return {key: value for key, value in stable_args.items() if value is not None}


def _batch_auto_pre_uia_stable_step(args: Dict[str, Any], hwnd_ref: Any, *, id_prefix: str = "semantic", default_desktop: bool = False) -> Optional[Dict[str, Any]]:
    if not _batch_auto_pre_uia_stable_enabled(args):
        return None
    desktop = _coerce_bool(args.get("desktop"), default_desktop or hwnd_ref is None)
    stable_args = _batch_auto_pre_uia_stable_args(args)
    command = "desktop_uia_stable_wait" if desktop else "uia_stable_wait"
    if not desktop and hwnd_ref is not None:
        stable_args["hwnd"] = hwnd_ref
    return _batch_auto_branch(
        f"{id_prefix}_pre_uia_stable",
        command,
        stable_args,
        expect={"path": "$result.stable", "equals": True},
        description="wait for UIA tree stability before semantic fallback",
    )


def _batch_auto_with_pre_uia_stable(branch: Dict[str, Any], args: Dict[str, Any], hwnd_ref: Any = None, *, id_prefix: Optional[str] = None, default_desktop: bool = False) -> Dict[str, Any]:
    if not isinstance(branch, dict) or not _batch_auto_pre_uia_stable_enabled(args):
        return branch
    resolved_hwnd = hwnd_ref if hwnd_ref is not None else args.get("hwnd")
    prefix = id_prefix or str(branch.get("id") or "semantic")
    stable_step = _batch_auto_pre_uia_stable_step(args, resolved_hwnd, id_prefix=prefix, default_desktop=default_desktop)
    if not stable_step:
        return branch
    updated = copy.deepcopy(branch)
    branch_steps, _, _ = _batch_branch_steps(updated)
    if branch_steps:
        updated["steps"] = [stable_step] + copy.deepcopy(branch_steps)
        updated.pop("command", None)
        updated.pop("args", None)
        updated.pop("path", None)
        updated.pop("data", None)
        updated.pop("expect", None)
        return updated
    return updated


def _batch_auto_apply_pre_uia_stable_to_branches(branches: List[Dict[str, Any]], args: Dict[str, Any], hwnd_ref: Any = None, *, start: int = 0, default_desktop: bool = False) -> List[Dict[str, Any]]:
    if not _batch_auto_pre_uia_stable_enabled(args):
        return branches
    updated = list(branches)
    for index in range(max(int(start or 0), 0), len(updated)):
        branch = updated[index]
        branch_id = str(branch.get("id") or f"semantic_{index}") if isinstance(branch, dict) else f"semantic_{index}"
        updated[index] = _batch_auto_with_pre_uia_stable(branch, args, hwnd_ref, id_prefix=branch_id, default_desktop=default_desktop)
    return updated


def _batch_auto_post_uia_stable_args(args: Dict[str, Any]) -> Dict[str, Any]:
    stable_args: Dict[str, Any] = {}
    spec = args.get("post_uia_stable")
    if isinstance(spec, dict):
        stable_args.update(_batch_auto_normalize_args(dict(spec)))
    for source_key, target_key in (
        ("post_uia_stable_ticks", "stable_ticks"),
        ("post_uia_stable_max_depth", "max_depth"),
        ("post_uia_stable_max_elements", "max_elements"),
        ("post_uia_stable_view", "view"),
        ("post_uia_stable_include_values", "include_values"),
        ("post_uia_stable_rect_bucket", "rect_bucket"),
    ):
        value = args.get(source_key)
        if value is not None and stable_args.get(target_key) is None:
            stable_args[target_key] = value
    for key in ("stable_ticks", "max_depth", "max_elements", "view", "include_values", "rect_bucket"):
        value = args.get(key)
        if value is not None and stable_args.get(key) is None:
            stable_args[key] = value
    if stable_args.get("include_values") is not None:
        stable_args["include_values"] = _coerce_bool(stable_args.get("include_values"), False)
    return {key: value for key, value in stable_args.items() if value is not None}


def _batch_auto_boolish_literal(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return value.strip().lower() in {
            "1", "0", "true", "false", "yes", "no", "y", "n", "on", "off",
            "enable", "enabled", "disable", "disabled", "none", "null",
        }
    return False


def _batch_auto_post_win32_presence_args(args: Dict[str, Any]) -> Dict[str, Any]:
    spec = None
    state = None
    for key, state_name in (
        ("verify_win32_present", "present"),
        ("verify_native_present", "present"),
        ("verify_present", "present"),
        ("verify_win32_absent", "absent"),
        ("verify_native_absent", "absent"),
        ("verify_absent", "absent"),
    ):
        if args.get(key) is not None:
            spec = args.get(key)
            state = state_name
            break
    if state is None:
        return {}
    result: Dict[str, Any] = {"state": state}
    if isinstance(spec, dict):
        normalized = _batch_auto_normalize_args(dict(spec))
        expected = _batch_auto_first(normalized, "verify_win32_expected", "verify_native_expected", "verify_expected", "expected")
        if expected is not None:
            result["expected"] = expected
        index = _batch_auto_first(normalized, "verify_win32_index", "verify_native_index", "verify_item_index", "index")
        if index is not None:
            result["index"] = index
        text = _batch_auto_first(normalized, "verify_win32_text", "verify_native_text", "verify_item", "item", "text", "name", "value")
        if text is not None:
            result["text"] = text
        for key in ("match", "timeout", "interval", "timeout_ms", "max_items", "diagnostic"):
            value = normalized.get(key)
            if value is not None:
                result[key] = value
        return result
    if spec is not None:
        if _batch_auto_boolish_literal(spec):
            result["expected"] = spec
        else:
            result["text"] = spec
    return result


def _batch_auto_post_win32_state_args(args: Dict[str, Any], hwnd_ref: Any) -> Dict[str, Any]:
    state = _batch_auto_first(args, "verify_win32_state", "verify_native_state", "verify_state")
    expected = _batch_auto_first(args, "verify_win32_expected", "verify_native_expected", "verify_expected")
    presence_args = _batch_auto_post_win32_presence_args(args)
    if state is None and presence_args.get("state") is not None:
        state = presence_args.get("state")
    if expected is None and presence_args.get("expected") is not None:
        expected = presence_args.get("expected")
    for key, state_name in (
        ("verify_checked", "checked"),
        ("verify_selected", "selected"),
        ("verify_expanded", "expanded"),
        ("verify_visited", "visited"),
    ):
        if args.get(key) is not None:
            if state is None:
                state = state_name
            if expected is None:
                expected = args.get(key)
            break
    if state is None:
        return {}
    wait_args: Dict[str, Any] = {"hwnd": hwnd_ref, "state": state}
    if expected is not None:
        wait_args["expected"] = expected
    index = _batch_auto_first(args, "verify_win32_index", "verify_native_index", "verify_item_index")
    if index is None:
        index = presence_args.get("index")
    if index is None and args.get("index") is not None:
        index = args.get("index")
    text = _batch_auto_first(args, "verify_win32_text", "verify_native_text", "verify_item")
    if text is None:
        text = presence_args.get("text")
    if text is None:
        text = _batch_auto_first(args, "item", "text", "name")
    if index is not None:
        wait_args["index"] = index
    if text is not None:
        wait_args["text"] = text
    match = _batch_auto_first(args, "verify_win32_match", "verify_native_match", "match")
    if match is None:
        match = presence_args.get("match")
    if match is not None:
        wait_args["match"] = match
    timeout = _batch_auto_post_timeout(args)
    if timeout is None:
        timeout = presence_args.get("timeout")
    interval = _batch_auto_post_interval(args)
    if interval is None:
        interval = presence_args.get("interval")
    if timeout is not None:
        wait_args["timeout"] = timeout
    if interval is not None:
        wait_args["interval"] = interval
    timeout_ms = _batch_auto_first(args, "verify_win32_timeout_ms", "verify_native_timeout_ms", "timeout_ms")
    if timeout_ms is None:
        timeout_ms = presence_args.get("timeout_ms")
    if timeout_ms is not None:
        wait_args["timeout_ms"] = timeout_ms
    max_items = _batch_auto_first(args, "verify_win32_max_items", "verify_native_max_items", "max_items")
    if max_items is None:
        max_items = presence_args.get("max_items")
    if max_items is not None:
        wait_args["max_items"] = max_items
    diagnostic = args.get("diagnostic")
    if diagnostic is None:
        diagnostic = presence_args.get("diagnostic")
    if diagnostic is not None:
        wait_args["diagnostic"] = diagnostic
    return {key: value for key, value in wait_args.items() if value is not None}


def _batch_auto_native_wait_repair_enabled(args: Dict[str, Any]) -> bool:
    value = _batch_auto_first(args, "native_wait_repair", "verify_win32_repair", "verify_native_repair")
    if value is not None:
        return _coerce_bool(value, True)
    if _batch_auto_first(
        args,
        "native_wait_repair_match",
        "verify_win32_repair_match",
        "verify_native_repair_match",
        "native_wait_repair_timeout",
        "verify_win32_repair_timeout",
        "verify_native_repair_timeout",
    ) is not None:
        return True
    return _batch_auto_recover_enabled(args)


def _batch_auto_native_wait_repair_match(args: Dict[str, Any]) -> str:
    value = _batch_auto_first(args, "native_wait_repair_match", "verify_win32_repair_match", "verify_native_repair_match")
    text = str(value if value is not None else "contains").strip().lower().replace("-", "_")
    return text or "contains"


def _batch_auto_native_wait_repair_timeout(args: Dict[str, Any]) -> Any:
    return _batch_auto_first(
        args,
        "native_wait_repair_timeout",
        "verify_win32_repair_timeout",
        "verify_native_repair_timeout",
    )


def _batch_auto_native_wait_repair_applicable(args: Dict[str, Any], wait_args: Dict[str, Any]) -> bool:
    if not _batch_auto_native_wait_repair_enabled(args):
        return False
    if not isinstance(wait_args, dict) or wait_args.get("text") is None:
        return False
    match = str(wait_args.get("match") or "contains").strip().lower().replace("-", "_")
    repair_match = _batch_auto_native_wait_repair_match(args)
    if match != "exact" or repair_match == match:
        return False
    state = _normalize_win32_wait_state(wait_args.get("state"))
    if state == "absent":
        return False
    expected = _coerce_win32_wait_expected(state, wait_args.get("expected"))
    if state == "present" and expected is False:
        return False
    return True


def _batch_auto_with_native_wait_repair(
    step: Dict[str, Any],
    args: Dict[str, Any],
    wait_args: Dict[str, Any],
    *,
    id_prefix: str,
) -> Dict[str, Any]:
    if not _batch_auto_native_wait_repair_applicable(args, wait_args):
        return step
    base_id = _batch_step_id(step) or f"{id_prefix}_verify_win32_state"
    original_step = copy.deepcopy(step)
    original_step["id"] = f"{base_id}_original"

    probe_args = dict(wait_args)
    probe_args["diagnostic"] = True
    probe_args["timeout"] = 0.0
    probe_args.setdefault("interval", _batch_auto_recovery_interval(args))
    probe_step = {
        **_batch_auto_branch(
            f"{base_id}_diagnostic_probe",
            "win32_control_wait",
            probe_args,
            expect=False,
            description="probe failed native wait diagnostics before relaxed retry",
        ),
        "allow_failure": True,
    }

    relaxed_args = dict(wait_args)
    relaxed_args["match"] = _batch_auto_native_wait_repair_match(args)
    relaxed_args.setdefault("diagnostic", True)
    repair_timeout = _batch_auto_native_wait_repair_timeout(args)
    if repair_timeout is not None:
        relaxed_args["timeout"] = repair_timeout
    elif "timeout" not in relaxed_args:
        relaxed_args["timeout"] = _batch_auto_recovery_timeout(args)
    if "interval" not in relaxed_args:
        relaxed_args["interval"] = _batch_auto_recovery_interval(args)
    relaxed_step = _batch_auto_branch(
        f"{base_id}_relaxed_retry",
        "win32_control_wait",
        relaxed_args,
        expect={"path": "$result.matched", "equals": True},
        description="retry native wait with diagnostic relaxed text match",
    )
    relaxed_step["when"] = [
        {
            "path": f"$steps.{probe_step['id']}.result.original_result.failure_summary.target_text",
            "exists": True,
        },
        {
            "path": f"$steps.{probe_step['id']}.result.original_result.failure_summary.match",
            "equals": "exact",
        },
    ]

    return {
        "id": base_id,
        "command": "batch_try",
        "branches": [
            {
                "id": f"{base_id}_strict",
                "description": "strict native post verification",
                "steps": [original_step],
            },
            {
                "id": f"{base_id}_diagnostic_relaxed_retry",
                "description": "diagnostic native post verification repair",
                "steps": [probe_step, relaxed_step],
            },
        ],
        "expect": {"path": "$result.ok", "equals": True},
        "description": "verify native Win32 control state after action with diagnostic repair",
    }


def _batch_auto_post_probe_loop(
    step: Dict[str, Any],
    *,
    until: Dict[str, Any],
    timeout: Any = None,
    interval: Any = None,
    id_prefix: str = "post",
    suffix: str = "verify_absent",
    description: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        timeout_value = float(timeout) if timeout is not None else 3.0
    except Exception:
        timeout_value = 3.0
    try:
        interval_value = float(interval) if interval is not None else 0.25
    except Exception:
        interval_value = 0.25
    iterations = max(1, int(math.ceil(max(timeout_value, 0.0) / max(interval_value, 0.05))) + 1)
    return {
        "id": f"{id_prefix}_{suffix}",
        "command": "batch_repeat",
        "max_iterations": iterations,
        "interval": interval_value,
        "steps": [step],
        "until": until,
        **({"description": description} if description else {}),
    }


def _batch_auto_post_steps(args: Dict[str, Any], hwnd_ref: Any, *, default_desktop: bool = False, id_prefix: str = "post") -> List[Dict[str, Any]]:
    if not _batch_auto_post_spec_present(args):
        return []
    steps: List[Dict[str, Any]] = []
    timeout = _batch_auto_post_timeout(args)
    interval = _batch_auto_post_interval(args)
    desktop = _coerce_bool(args.get("desktop"), default_desktop or hwnd_ref is None)
    hwnd_value = None if desktop else hwnd_ref

    delay = args.get("post_delay")
    if delay is not None:
        steps.append({
            "id": f"{id_prefix}_delay",
            "command": "batch_sleep",
            "args": {"delay": delay},
            "expect": {"path": "$result.ok", "equals": True},
        })

    event_name = args.get("post_event")
    if event_name is not None:
        event_args = _batch_auto_copy_args(args, ("pid", "title", "class_name", "limit", "match", "include_children", "skip_own_process"))
        event_args["event"] = event_name
        if hwnd_value is not None:
            event_args["hwnd"] = hwnd_value
        if timeout is not None:
            event_args["timeout"] = timeout
        steps.append(_batch_auto_branch(
            f"{id_prefix}_event",
            "wait_event",
            event_args,
            expect={"path": "$result.ok", "equals": True},
            description="wait for post-action WinEvent",
            ))

    if _coerce_bool(args.get("post_stable"), False):
        stable_args = _batch_auto_post_stable_args(args)
        if timeout is not None:
            stable_args["timeout"] = timeout
        if interval is not None:
            stable_args["interval"] = interval
        command = "desktop_visual_stable_wait" if desktop else "visual_stable_wait"
        if hwnd_value is not None:
            stable_args["hwnd"] = hwnd_value
        steps.append(_batch_auto_branch(
            f"{id_prefix}_visual_stable",
            command,
            stable_args,
            expect={"path": "$result.stable", "equals": True},
            description="wait until post-action pixels stop changing",
        ))

    if _coerce_bool(args.get("post_uia_stable"), False):
        uia_stable_args = _batch_auto_post_uia_stable_args(args)
        if timeout is not None:
            uia_stable_args["timeout"] = timeout
        if interval is not None:
            uia_stable_args["interval"] = interval
        command = "desktop_uia_stable_wait" if desktop else "uia_stable_wait"
        if hwnd_value is not None:
            uia_stable_args["hwnd"] = hwnd_value
        steps.append(_batch_auto_branch(
            f"{id_prefix}_uia_stable",
            command,
            uia_stable_args,
            expect={"path": "$result.stable", "equals": True},
            description="wait until post-action UIA tree stops changing",
        ))

    win32_state_args = _batch_auto_post_win32_state_args(args, hwnd_value)
    if win32_state_args and hwnd_value is not None and not desktop:
        win32_wait_step = _batch_auto_branch(
            f"{id_prefix}_verify_win32_state",
            "win32_control_wait",
            win32_state_args,
            expect={"path": "$result.matched", "equals": True},
            description="verify native Win32 control state after action",
        )
        steps.append(_batch_auto_with_native_wait_repair(
            win32_wait_step,
            args,
            win32_state_args,
            id_prefix=id_prefix,
        ))

    selector = _batch_auto_post_selector(args)
    if selector:
        selector_args = dict(selector)
        if timeout is not None:
            selector_args["timeout"] = timeout
        if interval is not None:
            selector_args["interval"] = interval
        if desktop:
            steps.append(_batch_auto_branch(
                f"{id_prefix}_verify_selector",
                "desktop_wait",
                selector_args,
                expect={"path": "$result.match.index", "exists": True},
                description="verify desktop UIA selector after action",
            ))
        elif hwnd_value is not None:
            selector_args["hwnd"] = hwnd_value
            steps.append(_batch_auto_branch(
                f"{id_prefix}_verify_selector",
                "uia_wait",
                selector_args,
                expect={"path": "$result.match.index", "exists": True},
                description="verify UIA selector after action",
            ))

    absent_selector = _batch_auto_post_selector(args, absent=True)
    if absent_selector:
        selector_args = dict(absent_selector)
        selector_args.setdefault("limit", 1)
        if desktop:
            step = _batch_auto_branch(
                f"{id_prefix}_absent_selector_probe",
                "desktop_find",
                selector_args,
                expect=False,
                description="probe desktop UIA selector absence after action",
            )
        else:
            selector_args["hwnd"] = hwnd_value
            step = _batch_auto_branch(
                f"{id_prefix}_absent_selector_probe",
                "uia_find",
                selector_args,
                expect=False,
                description="probe UIA selector absence after action",
            )
        steps.append(_batch_auto_post_probe_loop(
            step,
            until={"path": "$result.results.0.result.count", "equals": 0},
            timeout=timeout,
            interval=interval,
            id_prefix=id_prefix,
            suffix="verify_absent_selector",
            description="verify UIA selector is absent after action",
        ))

    verify_image = args.get("verify_image")
    if verify_image is not None:
        image_args = _batch_auto_copy_args(args, ("confidence", "max_width", "region", "scale_min", "scale_max", "scale_step", "capture_mode"))
        image_args["template_path"] = verify_image
        if timeout is not None:
            image_args["timeout"] = timeout
        if interval is not None:
            image_args["interval"] = interval
        command = "desktop_image_wait" if desktop else "image_wait"
        if hwnd_value is not None:
            image_args["hwnd"] = hwnd_value
        steps.append(_batch_auto_branch(
            f"{id_prefix}_verify_image",
            command,
            image_args,
            expect={"path": "$result.found", "equals": True},
            description="verify image appears after action",
        ))

    verify_absent_image = args.get("verify_absent_image")
    if verify_absent_image is not None:
        image_args = _batch_auto_copy_args(args, ("confidence", "max_width", "region", "scale_min", "scale_max", "scale_step", "capture_mode"))
        image_args["template_path"] = verify_absent_image
        command = "desktop_locate_image" if desktop else "locate_image"
        if hwnd_value is not None:
            image_args["hwnd"] = hwnd_value
        step = _batch_auto_branch(
            f"{id_prefix}_absent_image_probe",
            command,
            image_args,
            expect=False,
            description="probe image absence after action",
        )
        steps.append(_batch_auto_post_probe_loop(
            step,
            until={"path": "$result.results.0.result.found", "equals": False},
            timeout=timeout,
            interval=interval,
            id_prefix=id_prefix,
            suffix="verify_absent_image",
            description="verify image is absent after action",
        ))

    pixel_args = _batch_auto_post_pixel_args(args)
    if pixel_args and pixel_args.get("x") is not None and pixel_args.get("y") is not None and pixel_args.get("color") is not None:
        if timeout is not None:
            pixel_args["timeout"] = timeout
        if interval is not None:
            pixel_args["interval"] = interval
        command = "desktop_pixel_wait" if desktop else "pixel_wait"
        if hwnd_value is not None:
            pixel_args["hwnd"] = hwnd_value
        steps.append(_batch_auto_branch(
            f"{id_prefix}_verify_pixel",
            command,
            pixel_args,
            expect={"path": "$result.matched", "equals": True},
            description="verify pixel color after action",
        ))

    absent_pixel_args = _batch_auto_post_pixel_args(args, absent=True)
    if absent_pixel_args and absent_pixel_args.get("x") is not None and absent_pixel_args.get("y") is not None and absent_pixel_args.get("color") is not None:
        if timeout is not None:
            absent_pixel_args["timeout"] = timeout
        if interval is not None:
            absent_pixel_args["interval"] = interval
        command = "desktop_pixel_wait" if desktop else "pixel_wait"
        if hwnd_value is not None:
            absent_pixel_args["hwnd"] = hwnd_value
        steps.append(_batch_auto_branch(
            f"{id_prefix}_verify_absent_pixel",
            command,
            absent_pixel_args,
            expect={"path": "$result.matched", "equals": True},
            description="verify pixel color is absent after action",
        ))

    verify_text = args.get("verify_text")
    if verify_text is not None:
        ocr_args = _batch_auto_copy_args(args, ("lang", "max_width", "engine", "match", "region", "max_words", "capture_mode"))
        ocr_args["text"] = verify_text
        if timeout is not None:
            ocr_args["timeout"] = timeout
        if interval is not None:
            ocr_args["interval"] = interval
        command = "desktop_ocr_wait" if desktop else "ocr_wait"
        if hwnd_value is not None:
            ocr_args["hwnd"] = hwnd_value
        steps.append(_batch_auto_branch(
            f"{id_prefix}_verify_text",
            command,
            ocr_args,
            expect={"path": "$result.found", "equals": True},
            description="verify OCR text appears after action",
        ))

    verify_absent_text = args.get("verify_absent_text")
    if verify_absent_text is not None:
        ocr_args = _batch_auto_copy_args(args, ("lang", "max_width", "engine", "match", "region", "max_words", "capture_mode"))
        ocr_args["text"] = verify_absent_text
        ocr_args["limit"] = 1
        command = "desktop_ocr_find" if desktop else "ocr_find"
        if hwnd_value is not None:
            ocr_args["hwnd"] = hwnd_value
        step = _batch_auto_branch(
            f"{id_prefix}_absent_text_probe",
            command,
            ocr_args,
            expect=False,
            description="probe OCR text absence after action",
        )
        steps.append(_batch_auto_post_probe_loop(
            step,
            until={"path": "$result.results.0.result.found", "equals": False},
            timeout=timeout,
            interval=interval,
            id_prefix=id_prefix,
            suffix="verify_absent_text",
            description="verify OCR text is absent after action",
        ))

    observe_value = args.get("post_observe")
    if observe_value is not None and _coerce_bool(observe_value, True):
        if desktop:
            steps.append(_batch_auto_branch(
                f"{id_prefix}_observe_desktop",
                "desktop_accessibility",
                _batch_auto_copy_args(args, ("max_depth", "max_elements", "view")),
                expect={"path": "$result.desktop", "equals": True},
                description="observe desktop UIA after action",
            ))
            if _coerce_bool(_batch_auto_first(args, "include_screenshot", "screenshot"), True):
                output = args.get("output") or os.path.join(tempfile.gettempdir(), f"desktop-post-{int(time.time() * 1000)}.jpg")
                steps.append(_batch_auto_branch(
                    f"{id_prefix}_observe_screenshot",
                    "desktop_screenshot",
                    {"output": output, "max_width": args.get("max_width", 1600)},
                    expect={"path": "$result.id", "exists": True},
                    description="capture desktop screenshot after action",
                ))
        else:
            observe_args = _batch_auto_copy_args(args, ("include_screenshot", "include_accessibility", "include_a11y", "include_ocr", "ocr", "ocr_engine", "ocr_lang", "lang", "max_width", "max_depth", "max_elements", "view", "capture_mode"))
            if hwnd_value is not None:
                observe_args["hwnd"] = hwnd_value
            steps.append(_batch_auto_branch(
                f"{id_prefix}_observe",
                "observe",
                observe_args,
                expect={"path": "$result.hwnd", "exists": True},
                description="observe target after action",
            ))

    custom_steps = args.get("post_steps")
    if isinstance(custom_steps, list):
        for index, step in enumerate(custom_steps):
            if not isinstance(step, dict):
                continue
            item = copy.deepcopy(step)
            item.setdefault("id", f"{id_prefix}_step_{index + 1}")
            command, path, step_args = _batch_command_parts(item)
            if isinstance(step_args, dict) and not step_args.get("desktop") and step_args.get("hwnd") is None and hwnd_value is not None:
                if "args" in item or command:
                    item["args"] = {**step_args, "hwnd": hwnd_value}
                    item.pop("data", None)
                else:
                    item["data"] = {**step_args, "hwnd": hwnd_value}
            steps.append(item)
    elif isinstance(custom_steps, dict):
        item = copy.deepcopy(custom_steps)
        item.setdefault("id", f"{id_prefix}_step_1")
        steps.append(item)

    return steps


def _batch_auto_with_post_steps(branch: Dict[str, Any], args: Dict[str, Any], hwnd_ref: Any = None, *, id_prefix: Optional[str] = None, default_desktop: bool = False) -> Dict[str, Any]:
    if not isinstance(branch, dict) or not _batch_auto_post_spec_present(args):
        return branch
    resolved_hwnd = hwnd_ref if hwnd_ref is not None else args.get("hwnd")
    prefix = id_prefix or str(branch.get("id") or "post")
    post_steps = _batch_auto_post_steps(args, resolved_hwnd, default_desktop=default_desktop, id_prefix=prefix)
    if not post_steps:
        return branch
    updated = copy.deepcopy(branch)
    branch_steps, _, _ = _batch_branch_steps(updated)
    if branch_steps:
        updated["steps"] = copy.deepcopy(branch_steps) + post_steps
        updated.pop("command", None)
        updated.pop("args", None)
        updated.pop("path", None)
        updated.pop("data", None)
        updated.pop("expect", None)
        return updated
    return updated


def _batch_auto_apply_post_to_branches(branches: List[Dict[str, Any]], args: Dict[str, Any], hwnd_ref: Any = None, *, id_prefix: Optional[str] = None, default_desktop: bool = False) -> List[Dict[str, Any]]:
    if not _batch_auto_post_spec_present(args):
        return branches
    return [
        _batch_auto_with_post_steps(branch, args, hwnd_ref, id_prefix=id_prefix, default_desktop=default_desktop)
        for branch in branches
    ]


def _batch_auto_focused_input_args(args: Dict[str, Any], hwnd_ref: Any, text: Any) -> Dict[str, Any]:
    timeout = _batch_auto_first(args, "input_timeout", "action_timeout", "timeout")
    return {
        "hwnd": hwnd_ref,
        "text": text,
        "mode": args.get("focused_mode", args.get("mode", "auto")),
        "timeout": timeout if timeout is not None else 1.0,
        "restore": args.get("restore", True),
        "timeout_ms": args.get("timeout_ms", 500),
        "verify": args.get("verify", True),
        "diagnostic": args.get("diagnostic", False),
        "allow_focus_fallback": args.get("allow_focus_fallback", False),
    }


def _batch_auto_visual_text_input_branch(
    branch_id: str,
    click_command: str,
    click_args: Dict[str, Any],
    args: Dict[str, Any],
    text: Any,
    *,
    description: str,
) -> Dict[str, Any]:
    """Build a branch that visually focuses an input before typing into it."""
    hwnd = args.get("hwnd")
    input_command = "focused_input" if hwnd is not None else "type_foreground"
    input_args: Dict[str, Any] = (
        _batch_auto_focused_input_args(args, hwnd, text)
        if input_command == "focused_input"
        else {"text": text}
    )
    steps: List[Dict[str, Any]] = [
        _batch_auto_branch(f"{branch_id}_focus", click_command, click_args, description=f"{description} focus"),
        _batch_auto_branch(
            f"{branch_id}_input",
            input_command,
            input_args,
            expect={"path": "$result.message", "exists": True} if input_command == "type_foreground" else {"path": "$result.ok", "equals": True},
            description=f"{description} input",
        ),
    ]
    return {
        "id": branch_id,
        "description": description,
        "steps": steps,
    }


def _batch_auto_recover_enabled(args: Dict[str, Any]) -> bool:
    if args.get("recovery_policy") is not None:
        return str(args.get("recovery_policy") or "").strip().lower().replace("-", "_") not in ("none", "off", "false", "0", "disabled")
    return _coerce_bool(args.get("auto_recover"), False)


def _batch_auto_recovery_float(args: Dict[str, Any], default: float, *keys: str) -> float:
    value = _batch_auto_first(args, *keys)
    if value is None:
        return default
    try:
        return max(float(value), 0.0)
    except Exception:
        return default


def _batch_auto_recovery_int(args: Dict[str, Any], default: int, *keys: str) -> int:
    value = _batch_auto_first(args, *keys)
    if value is None:
        return default
    try:
        return max(int(value), 1)
    except Exception:
        return default


def _batch_auto_recovery_timeout(args: Dict[str, Any]) -> float:
    return _batch_auto_recovery_float(args, 1.0, "recovery_timeout", "action_timeout", "input_timeout", "post_timeout", "timeout")


def _batch_auto_recovery_interval(args: Dict[str, Any]) -> float:
    return _batch_auto_recovery_float(args, 0.1, "recovery_interval", "post_interval", "interval")


def _batch_auto_recovery_stable_ticks(args: Dict[str, Any]) -> int:
    return _batch_auto_recovery_int(args, 2, "recovery_stable_ticks", "post_stable_ticks", "post_uia_stable_ticks", "stable_ticks")


def _batch_auto_optional_recovery_step(step: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if step is not None:
        step["optional"] = True
    return step


def _batch_auto_recovery_uia_stable_step(args: Dict[str, Any], hwnd_ref: str) -> Optional[Dict[str, Any]]:
    if not _coerce_bool(args.get("recovery_uia_stable"), True):
        return None
    stable_args = _batch_auto_post_uia_stable_args(args)
    stable_args.update({
        "hwnd": hwnd_ref,
        "timeout": _batch_auto_recovery_timeout(args),
        "interval": _batch_auto_recovery_interval(args),
    })
    stable_args.setdefault("stable_ticks", _batch_auto_recovery_stable_ticks(args))
    return _batch_auto_optional_recovery_step(_batch_auto_branch(
        "recover_uia_stable",
        "uia_stable_wait",
        stable_args,
        expect={"path": "$result.stable", "equals": True},
        description="wait for UIA tree stability before retry",
    ))


def _batch_auto_recovery_visual_stable_step(args: Dict[str, Any], hwnd_ref: str) -> Optional[Dict[str, Any]]:
    if not _coerce_bool(args.get("recovery_visual_stable"), True):
        return None
    stable_args = _batch_auto_post_stable_args(args)
    stable_args.update({
        "hwnd": hwnd_ref,
        "timeout": _batch_auto_recovery_timeout(args),
        "interval": _batch_auto_recovery_interval(args),
    })
    stable_args.setdefault("stable_ticks", _batch_auto_recovery_stable_ticks(args))
    return _batch_auto_optional_recovery_step(_batch_auto_branch(
        "recover_visual_stable",
        "visual_stable_wait",
        stable_args,
        expect={"path": "$result.stable", "equals": True},
        description="wait for visual stability before retry",
    ))


def _batch_auto_recovery_steps(*steps: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [step for step in steps if step is not None]


def _batch_auto_default_recovery_policy(args: Dict[str, Any], hwnd_ref: str) -> Optional[Dict[str, Any]]:
    if not _batch_auto_recover_enabled(args):
        return None
    focus_step = {
        "id": "recover_focus",
        "command": "focus_hwnd",
        "args": {
            "hwnd": hwnd_ref,
            "timeout": args.get("focus_timeout", args.get("timeout", 1.0)),
            "restore": _coerce_bool(args.get("restore"), True),
        },
        "optional": True,
    }
    boundary_steps = [
        {
            "id": "recover_boundary",
            "command": "control_boundary",
            "args": {"hwnd": hwnd_ref},
            "extract": {"needs_elevation": "$result.needs_elevation"},
            "optional": True,
        },
        {
            "id": "recover_helper",
            "command": "helper_status",
            "args": {
                "elevated": "$steps.recover_boundary.result.value.needs_elevation",
                "start": "$steps.recover_boundary.result.value.needs_elevation",
            },
            "when": {"path": "$steps.recover_boundary.result.value.needs_elevation", "equals": True},
            "optional": True,
        },
        copy.deepcopy(focus_step),
    ]
    uia_stable_step = _batch_auto_recovery_uia_stable_step(args, hwnd_ref)
    visual_stable_step = _batch_auto_recovery_visual_stable_step(args, hwnd_ref)
    visual_steps = _batch_auto_recovery_steps(
        copy.deepcopy(focus_step),
        {
            "id": "recover_visual_pause",
            "command": "batch_sleep",
            "args": {"delay": max(float(args.get("recovery_delay", 0.05) or 0.05), 0.0)},
            "optional": True,
        },
        copy.deepcopy(visual_stable_step) if visual_stable_step else None,
    )
    selector_steps = _batch_auto_recovery_steps(
        copy.deepcopy(focus_step),
        copy.deepcopy(uia_stable_step) if uia_stable_step else None,
    )
    timeout_steps = _batch_auto_recovery_steps(
        copy.deepcopy(focus_step),
        copy.deepcopy(uia_stable_step) if uia_stable_step else None,
        copy.deepcopy(visual_stable_step) if visual_stable_step else None,
    )
    clipboard_restore_steps = [copy.deepcopy(focus_step)]
    clipboard_text = _batch_auto_first(args, "text", "value")
    if clipboard_text is not None:
        clipboard_restore_steps.append(_batch_auto_branch(
            "recover_clipboard_focused_input",
            "focused_input",
            _batch_auto_focused_input_args(args, hwnd_ref, clipboard_text),
            expect={"path": "$result.ok", "equals": True},
            description="retry text input without clipboard paste after clipboard restore warning",
        ))
    return {
        "focus": [copy.deepcopy(focus_step)],
        "selector": selector_steps,
        "semantic_provider": copy.deepcopy(selector_steps),
        "native_control": copy.deepcopy(selector_steps),
        "visual": visual_steps,
        "input": [copy.deepcopy(focus_step)],
        "clipboard_restore": clipboard_restore_steps,
        "blocked_or_elevation": boundary_steps,
        "timeout": timeout_steps,
        "default": [copy.deepcopy(focus_step)],
    }


def _batch_auto_attach_recovery(step: Dict[str, Any], args: Dict[str, Any], hwnd_ref: str) -> Dict[str, Any]:
    if not isinstance(step, dict):
        return step
    if _batch_step_recovery_spec(step, step.get("args") if isinstance(step.get("args"), dict) else {}) is not None:
        return step
    policy = _batch_auto_default_recovery_policy(args, hwnd_ref)
    if policy is None:
        return step
    step["recover_on_failure"] = policy
    return step


def _batch_auto_window_args(args: Dict[str, Any]) -> Dict[str, Any]:
    window_args = _batch_auto_copy_args(args, (
        "hwnd", "title", "window_title", "process", "process_name", "app", "path",
        "path_or_name", "launch", "timeout", "wait_timeout", "interval", "match",
        "activate", "restore", "boundary", "control_boundary", "helper",
        "helper_status", "observe", "observe_window", "include_a11y", "ocr",
    ))
    if "title" not in window_args and args.get("window_title") is not None:
        window_args["title"] = args.get("window_title")
    if "title" not in window_args and args.get("name") is not None:
        window_args["title"] = args.get("name")
    if "process" not in window_args and args.get("process_name") is not None:
        window_args["process"] = args.get("process_name")
    if "app" not in window_args:
        app = _batch_auto_first(args, "app", "path_or_name", "launch")
        if app is not None:
            window_args["app"] = app
    if "timeout" not in window_args and args.get("wait_timeout") is not None:
        window_args["timeout"] = args.get("wait_timeout")
    return window_args


def _batch_auto_window_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    layers = args.get("layers")
    window_args = _batch_auto_window_args(args)
    title = _batch_auto_first(args, "title", "window_title", "name")
    process = _batch_auto_first(args, "process", "process_name")
    launch_target = _batch_auto_first(args, "app", "path", "path_or_name", "launch")
    hwnd = args.get("hwnd")
    timeout = _batch_auto_first(args, "timeout", "wait_timeout")
    interval = args.get("interval")
    match = args.get("match", "contains")
    activate = _batch_auto_bool(args, "activate", True)
    restore = _batch_auto_bool(args, "restore", True)
    helper = _coerce_bool(_batch_auto_first(args, "helper", "helper_status"), False)
    boundary = bool(_coerce_bool(_batch_auto_first(args, "boundary", "control_boundary"), True) or helper)
    if helper:
        window_args["boundary"] = True
    observe_window = _coerce_bool(_batch_auto_first(args, "observe", "observe_window"), False)

    if _batch_auto_layer_enabled(layers, "semantic"):
        branches.append(_batch_auto_branch(
            "auto_window",
            "auto_window",
            window_args,
            expect={"path": "$result.window.hwnd", "exists": True},
            description="acquire/launch/focus target window",
        ))

    if _batch_auto_layer_enabled(layers, "native") and (title is not None or process is not None or hwnd is not None):
        wait_args = {
            "title": title,
            "process": process,
            "timeout": timeout,
            "interval": interval,
            "match": match,
        }
        if hwnd is not None:
            wait_args["hwnd"] = hwnd
        steps: List[Dict[str, Any]] = [
            {
                "id": "window_wait",
                "command": "wait_window",
                "args": {k: v for k, v in wait_args.items() if v is not None},
                "expect": {"path": "$result.window.hwnd", "exists": True},
                "extract": {"hwnd": "$result.window.hwnd", "window": "$result.window"},
            },
        ]
        if activate:
            steps.append({
                "id": "window_focus",
                "command": "focus_hwnd",
                "args": {
                    "hwnd": "$steps.window_wait.result.value.hwnd",
                    "timeout": min(float(timeout or 1.0), 2.0),
                    "restore": restore,
                },
                "expect": {"path": "$result.ok", "equals": True},
            })
        if boundary:
            boundary_step: Dict[str, Any] = {
                "id": "window_boundary",
                "command": "control_boundary",
                "args": {"hwnd": "$steps.window_wait.result.value.hwnd"},
                "expect": {"path": "$result.ok", "equals": True},
            }
            if helper:
                boundary_step["extract"] = {"needs_elevation": "$result.needs_elevation"}
            steps.append(boundary_step)
        if helper:
            steps.append({
                "id": "window_helper",
                "command": "helper_status",
                "args": {
                    "elevated": "$steps.window_boundary.result.value.needs_elevation",
                    "start": "$steps.window_boundary.result.value.needs_elevation",
                },
                "when": {"path": "$steps.window_boundary.result.value.needs_elevation", "equals": True},
                "optional": True,
            })
        if observe_window:
            observe_args = {
                "hwnd": "$steps.window_wait.result.value.hwnd",
                "include_accessibility": _batch_auto_bool(args, "include_a11y", False),
                "include_ocr": _batch_auto_bool(args, "ocr", False),
                "ocr_on_accessibility_error": _batch_auto_bool(args, "ocr", False),
                "view": args.get("view"),
                "max_depth": args.get("max_depth"),
                "max_elements": args.get("max_elements"),
                "capture_mode": args.get("capture_mode"),
            }
            steps.append({
                "id": "window_observe",
                "command": "observe",
                "args": {k: v for k, v in observe_args.items() if v is not None},
                "optional": True,
            })
        steps.append({
            "id": "window_ready",
            "command": "batch_value",
            "args": {
                "value": {
                    "hwnd": "$steps.window_wait.result.value.hwnd",
                    "window": "$steps.window_wait.result.value.window",
                    "source": "wait_window",
                },
            },
        })
        branches.append({
            "id": "wait_window",
            "description": "wait/focus existing target window",
            "steps": steps,
        })
        repair_branch = _batch_auto_window_repair_branch(
            args,
            {k: v for k, v in wait_args.items() if v is not None},
            activate=activate,
            restore=restore,
            boundary=boundary,
            helper=helper,
            observe_window=observe_window,
        )
        if repair_branch:
            branches.append(repair_branch)

    if _batch_auto_layer_enabled(layers, "input") and launch_target:
        launch_steps: List[Dict[str, Any]] = [
            {
                "id": "window_launch",
                "command": "launch",
                "args": {k: v for k, v in {"app": launch_target, "timeout": timeout}.items() if v is not None},
                "expect": {"path": "$result.window.hwnd", "exists": True},
                "extract": {"hwnd": "$result.window.hwnd", "window": "$result.window"},
            },
        ]
        if activate:
            launch_steps.append({
                "id": "launch_focus",
                "command": "focus_hwnd",
                "args": {
                    "hwnd": "$steps.window_launch.result.value.hwnd",
                    "timeout": min(float(timeout or 1.0), 2.0),
                    "restore": restore,
                },
                "expect": {"path": "$result.ok", "equals": True},
            })
        if boundary:
            launch_boundary_step: Dict[str, Any] = {
                "id": "launch_boundary",
                "command": "control_boundary",
                "args": {"hwnd": "$steps.window_launch.result.value.hwnd"},
                "expect": {"path": "$result.ok", "equals": True},
            }
            if helper:
                launch_boundary_step["extract"] = {"needs_elevation": "$result.needs_elevation"}
            launch_steps.append(launch_boundary_step)
        if helper:
            launch_steps.append({
                "id": "launch_helper",
                "command": "helper_status",
                "args": {
                    "elevated": "$steps.launch_boundary.result.value.needs_elevation",
                    "start": "$steps.launch_boundary.result.value.needs_elevation",
                },
                "when": {"path": "$steps.launch_boundary.result.value.needs_elevation", "equals": True},
                "optional": True,
            })
        launch_steps.append({
            "id": "launch_ready",
            "command": "batch_value",
            "args": {
                "value": {
                    "hwnd": "$steps.window_launch.result.value.hwnd",
                    "window": "$steps.window_launch.result.value.window",
                    "source": "launch",
                },
            },
        })
        branches.append({
            "id": "launch_window",
            "description": "launch app and bind its stable window",
            "steps": launch_steps,
        })

    return branches


def _batch_auto_uia_click_action_name(action: Any) -> str:
    text = str(action or "invoke").strip().lower().replace("-", "_").replace(" ", "_")
    if text in ("click", "press", "default", "invoke"):
        return "Invoke"
    if text in ("select", "selection"):
        return "Select"
    if text in ("check", "uncheck", "toggle", "set_check"):
        return "Toggle"
    if text in ("expand", "collapse"):
        return text.capitalize()
    return str(action or "Invoke")


def _batch_auto_uia_click_pattern(action: Any) -> str:
    text = str(action or "Invoke").strip().lower().replace("-", "_").replace(" ", "_")
    if text in ("toggle", "check", "uncheck", "set_check"):
        return "Toggle"
    if text in ("select", "selection"):
        return "SelectionItem"
    if text in ("expand", "collapse"):
        return "ExpandCollapse"
    return "Invoke"


def _batch_auto_uia_select_action_name(args: Dict[str, Any]) -> str:
    mode = _smart_select_mode_key(str(args.get("mode") or "select"))
    if mode in ("check", "uncheck", "toggle"):
        return "Toggle"
    if mode == "add":
        return "AddToSelection"
    if mode == "remove":
        return "RemoveFromSelection"
    return "Select"


def _batch_auto_click_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    hwnd = args.get("hwnd")
    base_selector = _batch_auto_copy_args(args, ("hwnd", "name", "automation_id", "control_type", "class_name", "index", "match", "timeout_ms", "diagnostic", "button", "clicks"))
    base_selector["action"] = _batch_auto_first(args, "control_action", "click_action", "uia_action", "action") or "invoke"
    timeout = _batch_auto_first(args, "timeout", "wait_timeout")
    interval = args.get("interval")
    layers = args.get("layers")
    semantic_wait_requested = timeout is not None or _batch_auto_smart_wait_repair_requested(args)
    if _batch_auto_layer_enabled(layers, "semantic"):
        semantic_start = len(branches)
        _batch_auto_add_semantic_branches(
            branches,
            args,
            "smart_click",
            "smart_wait_click" if semantic_wait_requested else "smart_click",
            base_selector,
            timeout=timeout,
            interval=interval,
            wait_id="smart_wait_click" if semantic_wait_requested else None,
            text_key="name",
            description="UIA/Win32 smart click",
        )
        uia_action = _batch_auto_uia_click_action_name(base_selector.get("action"))
        repaired = _batch_auto_uia_repair_branch(
            "uia_click_selector_repair",
            args,
            _batch_auto_uia_find_selector(
                args,
                name_value=_batch_auto_first(args, "name", "text", "item"),
                control_type_default=args.get("control_type", "button"),
                pattern_default=_batch_auto_uia_click_pattern(uia_action),
            ),
            action_command="uia_action",
            action_args={
                "action": uia_action,
                "value": args.get("value"),
                "horizontal": args.get("horizontal"),
                "vertical": args.get("vertical"),
                "max_depth": args.get("max_depth"),
                "max_elements": args.get("max_elements"),
            },
            description="UIA find suggested element then perform action",
        )
        if repaired:
            branches.append(repaired)
        branches = _batch_auto_apply_pre_uia_stable_to_branches(
            branches,
            args,
            hwnd,
            start=semantic_start,
            default_desktop=bool(args.get("desktop") or hwnd is None),
        )
    if _batch_auto_layer_enabled(layers, "native") and hwnd is not None:
        branches.append(_batch_auto_branch("win32_click", "win32_click", {"hwnd": hwnd, "timeout_ms": args.get("timeout_ms", 500)}, description="Win32 native click"))
        repaired = _batch_auto_native_repair_branch(
            "win32_click_selector_repair",
            args,
            action_command="win32_click",
            action_args={"timeout_ms": args.get("timeout_ms", 500)},
            name_value=_batch_auto_first(args, "name", "text", "item"),
            control_type_default=args.get("control_type", "button"),
            description="Win32 find suggested native control then click",
        )
        if repaired:
            branches.append(repaired)
    if _batch_auto_layer_enabled(layers, "msaa") and hwnd is not None:
        branches.append(_batch_auto_branch(
            "msaa_default",
            "msaa_action",
            {
                "hwnd": hwnd,
                "path": args.get("msaa_path", args.get("path", [])),
                "child_id": args.get("child_id", 0),
                "action": args.get("msaa_action", "default"),
                "value": args.get("value"),
            },
            description="MSAA default action",
        ))
    if _batch_auto_layer_enabled(layers, "visual"):
        visual_start = len(branches)
        template = _batch_auto_first(args, "template", "template_path", "image")
        text = _batch_auto_first(args, "text", "query", "name")
        _batch_auto_add_visual_row_branch(branches, args)
        if template:
            image_args = _batch_auto_copy_args(args, ("hwnd", "template", "template_path", "confidence", "max_width", "screenshot_id", "button", "clicks", "timeout", "interval", "region", "scale_min", "scale_max", "scale_step", "capture_mode"))
            if "template" not in image_args and "template_path" not in image_args:
                image_args["template"] = template
            command = "desktop_image_click" if args.get("desktop") or hwnd is None else "image_click"
            branches.append(_batch_auto_branch("image_click", command, image_args, description="OpenCV template click"))
            scroll_image_args = _batch_auto_copy_args(args, ("hwnd", "template", "template_path", "confidence", "max_width", "button", "clicks", "region", "scale_min", "scale_max", "scale_step", "max_scrolls", "scroll_amount", "scroll_x", "scroll_y", "pause", "capture_mode"))
            if "template" not in scroll_image_args and "template_path" not in scroll_image_args:
                scroll_image_args["template"] = template
            command = "desktop_image_scroll_click" if args.get("desktop") or hwnd is None else "image_scroll_click"
            branches.append(_batch_auto_branch("image_scroll_click", command, scroll_image_args, description="scrolling image template click"))
        if text:
            ocr_args = _batch_auto_copy_args(args, ("hwnd", "lang", "max_width", "screenshot_id", "engine", "match", "index", "button", "clicks", "region", "max_words", "timeout", "interval", "capture_mode"))
            ocr_args["text"] = text
            command = "desktop_ocr_click" if args.get("desktop") or hwnd is None else "ocr_click"
            branches.append(_batch_auto_branch("ocr_click", command, ocr_args, description="OCR text click"))
            scroll_ocr_args = _batch_auto_copy_args(args, ("hwnd", "lang", "max_width", "engine", "match", "index", "button", "clicks", "region", "max_words", "max_scrolls", "scroll_amount", "scroll_x", "scroll_y", "pause", "capture_mode"))
            scroll_ocr_args["text"] = text
            command = "desktop_ocr_scroll_click" if args.get("desktop") or hwnd is None else "ocr_scroll_click"
            branches.append(_batch_auto_branch("ocr_scroll_click", command, scroll_ocr_args, description="scrolling OCR text click"))
        branches = _batch_auto_apply_pre_visual_stable_to_branches(
            branches,
            args,
            hwnd,
            start=visual_start,
            default_desktop=bool(args.get("desktop") or hwnd is None),
        )
    if _batch_auto_layer_enabled(layers, "input") and (args.get("x") is not None and args.get("y") is not None):
        input_args = _batch_auto_copy_args(args, ("hwnd", "x", "y", "button", "clicks", "screenshot_id"))
        command = "desktop_click" if args.get("desktop") or input_args.get("hwnd") is None else "click"
        branches.append(_batch_auto_branch("coordinate_click", command, input_args, description="coordinate click fallback"))
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=bool(args.get("desktop") or hwnd is None))


def _batch_auto_hover_settle(args: Dict[str, Any]) -> Any:
    value = _batch_auto_first(args, "settle", "pause", "hover_delay", "hover-delay", "hover_settle", "hover-settle")
    return 0.05 if value is None else value


def _batch_auto_hover_move_args(args: Dict[str, Any], *, hwnd: Any = None, x: Any = None, y: Any = None, desktop: bool = False) -> Dict[str, Any]:
    move_args: Dict[str, Any] = {}
    if hwnd is not None and not desktop:
        move_args["hwnd"] = hwnd
    if x is not None:
        move_args["x"] = x
    if y is not None:
        move_args["y"] = y
    for key in ("screenshot_id", "duration", "activate"):
        if args.get(key) is not None:
            move_args[key] = args.get(key)
    move_args["settle"] = _batch_auto_hover_settle(args)
    return move_args


def _batch_auto_hover_has_selector(args: Dict[str, Any], name_value: Any = None) -> bool:
    return bool(
        name_value is not None
        or args.get("automation_id") is not None
        or args.get("control_type") is not None
        or args.get("class_name") is not None
        or args.get("value") is not None
        or args.get("pattern") is not None
    )


def _batch_auto_hover_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    hwnd = args.get("hwnd")
    layers = args.get("layers")
    desktop = _coerce_bool(args.get("desktop"), hwnd is None)
    name_value = _batch_auto_first(args, "name", "text", "query", "item")

    if _batch_auto_layer_enabled(layers, "semantic"):
        semantic_start = len(branches)
        if desktop:
            selector = _batch_auto_copy_args(args, (
                "name", "automation_id", "control_type", "class_name", "value",
                "pattern", "match", "timeout", "interval", "max_depth",
                "max_elements", "view", "enabled_only", "visible_only",
            ))
            if name_value is not None and selector.get("name") is None and selector.get("automation_id") is None:
                selector["name"] = name_value
            selector.setdefault("limit", 1)
            if _batch_auto_hover_has_selector(args, name_value):
                branches.append({
                    "id": "desktop_uia_hover",
                    "description": "desktop-root UIA find then hover element center",
                    "steps": [
                        _batch_auto_branch(
                            "desktop_hover_find",
                            "desktop_wait" if args.get("timeout") is not None else "desktop_find",
                            selector,
                            expect={"path": "$result.match.rect.center_x", "exists": True} if args.get("timeout") is not None else {"path": "$result.matches.0.rect.center_x", "exists": True},
                            description="find desktop UIA hover target",
                        ),
                        _batch_auto_branch(
                            "desktop_hover_move",
                            "desktop_move",
                            _batch_auto_hover_move_args(
                                args,
                                x="$steps.desktop_hover_find.result.match.rect.center_x" if args.get("timeout") is not None else "$steps.desktop_hover_find.result.matches.0.rect.center_x",
                                y="$steps.desktop_hover_find.result.match.rect.center_y" if args.get("timeout") is not None else "$steps.desktop_hover_find.result.matches.0.rect.center_y",
                                desktop=True,
                            ),
                            expect={"path": "$result.message", "exists": True},
                            description="hover desktop UIA target center",
                        ),
                    ],
                })
        elif hwnd is not None and _batch_auto_hover_has_selector(args, name_value):
            selector = _batch_auto_uia_find_selector(
                args,
                name_value=name_value,
                control_type_default=args.get("control_type"),
            )
            if selector:
                branches.append({
                    "id": "uia_hover",
                    "description": "UIA find then hover element center",
                    "steps": [
                        _batch_auto_branch(
                            "hover_find",
                            "uia_wait" if args.get("timeout") is not None else "uia_find",
                            selector,
                            expect={"path": "$result.match.rect.center_x", "exists": True} if args.get("timeout") is not None else {"path": "$result.matches.0.rect.center_x", "exists": True},
                            description="find UIA hover target",
                        ),
                        _batch_auto_branch(
                            "hover_move",
                            "move",
                            _batch_auto_hover_move_args(
                                args,
                                hwnd=hwnd,
                                x="$steps.hover_find.result.match.rect.center_x" if args.get("timeout") is not None else "$steps.hover_find.result.matches.0.rect.center_x",
                                y="$steps.hover_find.result.match.rect.center_y" if args.get("timeout") is not None else "$steps.hover_find.result.matches.0.rect.center_y",
                            ),
                            expect={"path": "$result.message", "exists": True},
                            description="hover UIA target center",
                        ),
                    ],
                })
        branches = _batch_auto_apply_pre_uia_stable_to_branches(
            branches,
            args,
            hwnd,
            start=semantic_start,
            default_desktop=desktop,
        )

    if _batch_auto_layer_enabled(layers, "input") and args.get("x") is not None and args.get("y") is not None:
        command = "desktop_move" if desktop else "move"
        branches.append(_batch_auto_branch(
            "coordinate_hover",
            command,
            _batch_auto_hover_move_args(args, hwnd=hwnd, x=args.get("x"), y=args.get("y"), desktop=desktop),
            expect={"path": "$result.message", "exists": True},
            description="coordinate hover without clicking",
        ))
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=desktop)


def _batch_auto_text_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    hwnd = args.get("hwnd")
    text = _batch_auto_first(args, "text", "value")
    timeout = _batch_auto_first(args, "timeout", "wait_timeout")
    interval = args.get("interval")
    layers = args.get("layers")
    semantic_wait_requested = timeout is not None or _batch_auto_smart_wait_repair_requested(args)
    selector_args = _batch_auto_copy_args(args, ("hwnd", "name", "automation_id", "control_type", "class_name", "index", "match", "mode", "timeout_ms", "verify", "diagnostic", "allow_focus_fallback", "skip_uia"))
    selector_args["text"] = text
    if _batch_auto_layer_enabled(layers, "semantic"):
        semantic_start = len(branches)
        _batch_auto_add_semantic_branches(
            branches,
            args,
            "smart_text",
            "smart_wait_text" if semantic_wait_requested else "smart_text",
            selector_args,
            timeout=timeout,
            interval=interval,
            wait_id="smart_wait_text" if semantic_wait_requested else None,
            text_key="name",
            description="UIA/Win32 smart text",
        )
        repaired = _batch_auto_uia_repair_branch(
            "uia_text_selector_repair",
            args,
            _batch_auto_uia_find_selector(
                args,
                name_value=_batch_auto_first(args, "name", "placeholder", "label", "field_label"),
                control_type_default=args.get("control_type", "edit"),
                pattern_default="Value",
            ),
            action_command="uia_set_value",
            action_args={
                "value": text,
                "max_depth": args.get("max_depth"),
                "max_elements": args.get("max_elements"),
            },
            description="UIA find suggested text element then set value",
        )
        if repaired:
            branches.append(repaired)
        branches = _batch_auto_apply_pre_uia_stable_to_branches(
            branches,
            args,
            hwnd,
            start=semantic_start,
            default_desktop=bool(args.get("desktop") or hwnd is None),
        )
    if _batch_auto_layer_enabled(layers, "native") and hwnd is not None:
        branches.append(_batch_auto_branch("win32_set_text", "win32_set_text", {"hwnd": hwnd, "text": text, "timeout_ms": args.get("timeout_ms", 500)}, description="Win32 set text"))
        repaired = _batch_auto_native_repair_branch(
            "win32_text_selector_repair",
            args,
            action_command="win32_set_text",
            action_args={"text": text, "timeout_ms": args.get("timeout_ms", 500)},
            name_value=_batch_auto_first(args, "name", "placeholder", "label", "field_label"),
            control_type_default=args.get("control_type", "edit"),
            description="Win32 find suggested text control then set text",
        )
        if repaired:
            branches.append(repaired)
    if _batch_auto_layer_enabled(layers, "msaa") and hwnd is not None:
        branches.append(_batch_auto_branch(
            "msaa_set_value",
            "msaa_action",
            {
                "hwnd": hwnd,
                "path": args.get("msaa_path", args.get("path", [])),
                "child_id": args.get("child_id", 0),
                "action": args.get("msaa_action", "set_value"),
                "value": text,
            },
            description="MSAA set value",
        ))
    if _batch_auto_layer_enabled(layers, "visual"):
        visual_start = len(branches)
        template = _batch_auto_first(args, "template", "template_path", "image")
        visual_text = _batch_auto_first(args, "visual_text", "placeholder", "label", "field_label", "input_label", "target_text", "query", "name")
        if template:
            image_args = _batch_auto_copy_args(args, ("hwnd", "template", "template_path", "confidence", "max_width", "screenshot_id", "button", "clicks", "timeout", "interval", "region", "scale_min", "scale_max", "scale_step", "capture_mode"))
            if "template" not in image_args and "template_path" not in image_args:
                image_args["template"] = template
            if "clicks" not in image_args:
                image_args["clicks"] = 1
            command = "desktop_image_click" if args.get("desktop") or hwnd is None else "image_click"
            branches.append(_batch_auto_visual_text_input_branch(
                "image_text_input",
                command,
                image_args,
                args,
                text,
                description="OpenCV template focus then text input",
            ))
            scroll_image_args = _batch_auto_copy_args(args, ("hwnd", "template", "template_path", "confidence", "max_width", "button", "clicks", "region", "scale_min", "scale_max", "scale_step", "max_scrolls", "scroll_amount", "scroll_x", "scroll_y", "pause", "capture_mode"))
            if "template" not in scroll_image_args and "template_path" not in scroll_image_args:
                scroll_image_args["template"] = template
            if "clicks" not in scroll_image_args:
                scroll_image_args["clicks"] = 1
            command = "desktop_image_scroll_click" if args.get("desktop") or hwnd is None else "image_scroll_click"
            branches.append(_batch_auto_visual_text_input_branch(
                "image_scroll_text_input",
                command,
                scroll_image_args,
                args,
                text,
                description="scrolling image focus then text input",
            ))
        if visual_text:
            ocr_args = _batch_auto_copy_args(args, ("hwnd", "lang", "max_width", "screenshot_id", "engine", "match", "index", "button", "clicks", "region", "max_words", "timeout", "interval", "capture_mode"))
            ocr_args["text"] = visual_text
            if "clicks" not in ocr_args:
                ocr_args["clicks"] = 1
            command = "desktop_ocr_click" if args.get("desktop") or hwnd is None else "ocr_click"
            branches.append(_batch_auto_visual_text_input_branch(
                "ocr_text_input",
                command,
                ocr_args,
                args,
                text,
                description="OCR text focus then text input",
            ))
            scroll_ocr_args = _batch_auto_copy_args(args, ("hwnd", "lang", "max_width", "engine", "match", "index", "button", "clicks", "region", "max_words", "max_scrolls", "scroll_amount", "scroll_x", "scroll_y", "pause", "capture_mode"))
            scroll_ocr_args["text"] = visual_text
            if "clicks" not in scroll_ocr_args:
                scroll_ocr_args["clicks"] = 1
            command = "desktop_ocr_scroll_click" if args.get("desktop") or hwnd is None else "ocr_scroll_click"
            branches.append(_batch_auto_visual_text_input_branch(
                "ocr_scroll_text_input",
                command,
                scroll_ocr_args,
                args,
                text,
                description="scrolling OCR text focus then text input",
            ))
        branches = _batch_auto_apply_pre_visual_stable_to_branches(
            branches,
            args,
            hwnd,
            start=visual_start,
            default_desktop=bool(args.get("desktop") or hwnd is None),
        )
    if _batch_auto_layer_enabled(layers, "input"):
        branches.append(_batch_auto_branch(
            "focused_input",
            "focused_input",
            _batch_auto_focused_input_args(args, hwnd, text),
            description="focused input fallback",
        ))
        branches.append(_batch_auto_branch("type_text", "type", {"hwnd": hwnd, "text": text}, expect={"path": "$result.message", "exists": True}, description="clipboard/type fallback"))
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=bool(args.get("desktop") or hwnd is None))


def _batch_auto_select_native_action(args: Dict[str, Any]) -> str:
    explicit = args.get("native_action")
    if explicit is not None:
        return str(explicit or "select").strip().lower().replace("-", "_") or "select"
    mode_key = _smart_select_mode_key(str(args.get("mode") or "select"))
    if mode_key in ("check", "uncheck", "toggle"):
        return mode_key
    return "select"


def _batch_auto_select_native_checked_arg(args: Dict[str, Any], native_action: str) -> Optional[bool]:
    explicit_checked = args.get("checked")
    if explicit_checked is not None:
        return _coerce_bool(explicit_checked, False)
    return _smart_select_native_checked_arg(str(args.get("mode") or "select"), native_action)


def _batch_auto_select_unverified_fallback_enabled(args: Dict[str, Any]) -> bool:
    if not _smart_select_check_mode(str(args.get("mode") or "select")):
        return True
    return _coerce_bool(args.get("allow_unverified_check_fallback"), False)


def _batch_auto_select_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    hwnd = args.get("hwnd")
    item = _batch_auto_first(args, "item", "text", "value", "name")
    timeout = _batch_auto_first(args, "timeout", "wait_timeout")
    interval = args.get("interval")
    layers = args.get("layers")
    allow_unverified_fallback = _batch_auto_select_unverified_fallback_enabled(args)
    semantic_wait_requested = timeout is not None or _batch_auto_smart_wait_repair_requested(args)
    selector_args = _batch_auto_copy_args(args, ("hwnd", "name", "automation_id", "control_type", "class_name", "index", "match", "mode", "timeout_ms", "diagnostic", "skip_uia"))
    selector_args["item"] = item
    if _batch_auto_layer_enabled(layers, "semantic"):
        semantic_start = len(branches)
        _batch_auto_add_semantic_branches(
            branches,
            args,
            "smart_select",
            "smart_wait_select" if semantic_wait_requested else "smart_select",
            selector_args,
            timeout=timeout,
            interval=interval,
            wait_id="smart_wait_select" if semantic_wait_requested else None,
            text_key="item",
            description="UIA/Win32 smart select",
        )
        uia_action = _batch_auto_uia_select_action_name(args)
        repaired = _batch_auto_uia_repair_branch(
            "uia_select_selector_repair",
            args,
            _batch_auto_uia_find_selector(
                args,
                name_value=item,
                control_type_default=args.get("control_type"),
                pattern_default="Toggle" if uia_action == "Toggle" else "SelectionItem",
            ),
            action_command="uia_action",
            action_args={
                "action": uia_action,
                "max_depth": args.get("max_depth"),
                "max_elements": args.get("max_elements"),
            },
            description="UIA find suggested selectable element then select",
        )
        if repaired:
            branches.append(repaired)
        branches = _batch_auto_apply_pre_uia_stable_to_branches(
            branches,
            args,
            hwnd,
            start=semantic_start,
            default_desktop=bool(args.get("desktop") or hwnd is None),
        )
    if _batch_auto_layer_enabled(layers, "native") and hwnd is not None:
        native_action = _batch_auto_select_native_action(args)
        native_checked = _batch_auto_select_native_checked_arg(args, native_action)
        native_args = {
            "hwnd": hwnd,
            "action": native_action,
            "index": args.get("native_index", args.get("index")),
            "text": item,
            "value": args.get("value"),
            "match": args.get("match", "contains"),
            "timeout_ms": args.get("timeout_ms", 500),
        }
        if native_checked is not None:
            native_args["checked"] = native_checked
        branches.append(_batch_auto_branch(
            "win32_select",
            "win32_control_action",
            native_args,
            description="Win32 native selection",
        ))
        repaired_action_args = dict(native_args)
        repaired_action_args.pop("hwnd", None)
        repaired = _batch_auto_native_repair_branch(
            "win32_select_selector_repair",
            args,
            action_command="win32_control_action",
            action_args=repaired_action_args,
            name_value=_batch_auto_first(args, "name", "item", "text", "value"),
            control_type_default=args.get("control_type", "list"),
            description="Win32 find suggested selectable control then select",
        )
        if repaired:
            branches.append(repaired)
    if allow_unverified_fallback and _batch_auto_layer_enabled(layers, "msaa") and hwnd is not None:
        branches.append(_batch_auto_branch(
            "msaa_select",
            "msaa_action",
            {
                "hwnd": hwnd,
                "path": args.get("msaa_path", args.get("path", [])),
                "child_id": args.get("child_id", 0),
                "action": args.get("msaa_action", "select"),
                "value": item,
            },
            description="MSAA selection fallback",
        ))
    if allow_unverified_fallback and _batch_auto_layer_enabled(layers, "visual"):
        visual_start = len(branches)
        template = _batch_auto_first(args, "template", "template_path", "image")
        visual_text = _batch_auto_first(args, "item", "text", "value", "name", "query")
        _batch_auto_add_visual_row_branch(
            branches,
            args,
            branch_id="visual_row_select",
            description="OCR numbered-row selection fallback",
        )
        if template:
            image_args = _batch_auto_copy_args(args, ("hwnd", "template", "template_path", "confidence", "max_width", "screenshot_id", "button", "clicks", "timeout", "interval", "region", "scale_min", "scale_max", "scale_step", "capture_mode"))
            if "template" not in image_args and "template_path" not in image_args:
                image_args["template"] = template
            command = "desktop_image_click" if args.get("desktop") or hwnd is None else "image_click"
            branches.append(_batch_auto_branch("image_select", command, image_args, description="OpenCV template selection fallback"))
            scroll_image_args = _batch_auto_copy_args(args, ("hwnd", "template", "template_path", "confidence", "max_width", "button", "clicks", "region", "scale_min", "scale_max", "scale_step", "max_scrolls", "scroll_amount", "scroll_x", "scroll_y", "pause", "capture_mode"))
            if "template" not in scroll_image_args and "template_path" not in scroll_image_args:
                scroll_image_args["template"] = template
            command = "desktop_image_scroll_click" if args.get("desktop") or hwnd is None else "image_scroll_click"
            branches.append(_batch_auto_branch("image_scroll_select", command, scroll_image_args, description="scrolling image selection fallback"))
        if visual_text:
            ocr_args = _batch_auto_copy_args(args, ("hwnd", "lang", "max_width", "screenshot_id", "engine", "match", "index", "button", "clicks", "region", "max_words", "timeout", "interval", "capture_mode"))
            ocr_args["text"] = visual_text
            command = "desktop_ocr_click" if args.get("desktop") or hwnd is None else "ocr_click"
            branches.append(_batch_auto_branch("ocr_select", command, ocr_args, description="OCR text selection fallback"))
            scroll_ocr_args = _batch_auto_copy_args(args, ("hwnd", "lang", "max_width", "engine", "match", "index", "button", "clicks", "region", "max_words", "max_scrolls", "scroll_amount", "scroll_x", "scroll_y", "pause", "capture_mode"))
            scroll_ocr_args["text"] = visual_text
            command = "desktop_ocr_scroll_click" if args.get("desktop") or hwnd is None else "ocr_scroll_click"
            branches.append(_batch_auto_branch("ocr_scroll_select", command, scroll_ocr_args, description="scrolling OCR text selection fallback"))
        branches = _batch_auto_apply_pre_visual_stable_to_branches(
            branches,
            args,
            hwnd,
            start=visual_start,
            default_desktop=bool(args.get("desktop") or hwnd is None),
        )
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=bool(args.get("desktop") or hwnd is None))


def _batch_auto_cell_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    hwnd = args.get("hwnd")
    timeout = _batch_auto_first(args, "timeout", "wait_timeout")
    interval = args.get("interval")
    layers = args.get("layers")
    cell_args = _batch_auto_copy_args(args, ("hwnd", "row", "column", "row_text", "column_name", "text", "automation_id", "control_type", "class_name", "match", "action", "timeout_ms", "diagnostic", "skip_uia"))
    if _batch_auto_layer_enabled(layers, "semantic"):
        semantic_start = len(branches)
        if timeout is not None or _batch_auto_smart_wait_repair_requested(args):
            wait_args = dict(cell_args)
            if timeout is not None:
                wait_args["timeout"] = timeout
            if interval is not None:
                wait_args["interval"] = interval
            wait_args.update(_batch_auto_smart_wait_repair_args(args))
            branches.append(_batch_auto_branch("smart_wait_cell", "smart_wait_cell", wait_args, description="UIA/Win32 smart wait cell"))
        branches.append(_batch_auto_branch("smart_cell", "smart_cell", cell_args, description="UIA/Win32 smart cell"))
        repaired = _batch_auto_uia_cell_repair_branch(
            "uia_cell_selector_repair",
            args,
            description="UIA find suggested grid/table cell then act on cell",
        )
        if repaired:
            branches.append(repaired)
        branches = _batch_auto_apply_pre_uia_stable_to_branches(
            branches,
            args,
            hwnd,
            start=semantic_start,
            default_desktop=bool(args.get("desktop") or hwnd is None),
        )
    if _batch_auto_layer_enabled(layers, "native") and hwnd is not None:
        native_command = "win32_control_action" if args.get("text") is not None or str(args.get("action", "")).lower() in {"select", "set", "set_cell", "set-cell"} else "win32_control_info"
        native_args = {
            "hwnd": hwnd,
            "action": args.get("native_action", "set_cell" if args.get("text") is not None else "select"),
            "index": args.get("row", args.get("index")),
            "value": args.get("column"),
            "text": args.get("text"),
            "match": args.get("match", "contains"),
            "timeout_ms": args.get("timeout_ms", 500),
            "max_items": args.get("max_items"),
        }
        branches.append(_batch_auto_branch(
            "win32_cell",
            native_command,
            native_args,
            description="Win32 native cell fallback",
        ))
        repaired_action_args = dict(native_args)
        repaired_action_args.pop("hwnd", None)
        repaired = _batch_auto_native_repair_branch(
            "win32_cell_selector_repair",
            args,
            action_command=native_command,
            action_args=repaired_action_args,
            name_value=_batch_auto_first(args, "name", "row_text", "text"),
            control_type_default=args.get("control_type", "listview"),
            description="Win32 find suggested grid/list control then act on cell",
        )
        if repaired:
            branches.append(repaired)
    if _batch_auto_layer_enabled(layers, "visual") and str(args.get("action", "get")).strip().lower().replace("-", "_") in {"click", "select", "invoke", "open"}:
        visual_start = len(branches)
        _batch_auto_add_visual_row_branch(
            branches,
            args,
            branch_id="visual_row_cell",
            description="OCR numbered-row cell/action fallback",
        )
        branches = _batch_auto_apply_pre_visual_stable_to_branches(
            branches,
            args,
            hwnd,
            start=visual_start,
            default_desktop=bool(args.get("desktop") or hwnd is None),
        )
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=bool(args.get("desktop") or hwnd is None))


def _batch_auto_key_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    layers = args.get("layers")
    if not _batch_auto_layer_enabled(layers, "input"):
        return branches
    keys = _batch_auto_first(args, "keys", "text", "value")
    if keys is None:
        return branches
    hwnd = args.get("hwnd")
    key_args = _batch_auto_copy_args(args, ("hwnd", "keys"))
    key_args["keys"] = keys
    branches.append(_batch_auto_branch(
        "key_input",
        "key",
        key_args,
        expect={"path": "$result.message", "exists": True},
        description="keyboard shortcut/key input",
    ))
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=bool(args.get("desktop") or hwnd is None))


def _batch_auto_scroll_delta(args: Dict[str, Any]) -> Any:
    value = _batch_auto_first(args, "dy", "delta")
    if value is None:
        value = _batch_auto_first(args, "scroll_amount", "amount")
    if value is None and args.get("scroll_y") is not None and args.get("y") is None:
        value = args.get("scroll_y")
    return 3 if value is None else value


def _batch_auto_scroll_key(args: Dict[str, Any], delta: Any) -> Optional[str]:
    keys = _batch_auto_first(args, "keys", "key_fallback", "keyboard_fallback", "shortcut", "hotkey")
    if keys is not None and not isinstance(keys, bool):
        return str(keys)
    try:
        value = float(delta)
    except Exception:
        value = 0.0
    if value < 0:
        return "pageup"
    return "pagedown"


def _batch_auto_scroll_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    layers = args.get("layers")
    if not _batch_auto_layer_enabled(layers, "input"):
        return branches
    hwnd = args.get("hwnd")
    delta = _batch_auto_scroll_delta(args)
    has_point = args.get("x") is not None and args.get("y") is not None
    desktop = _coerce_bool(args.get("desktop"), hwnd is None)
    if has_point:
        if desktop:
            scroll_args = _batch_auto_copy_args(args, ("x", "y", "screenshot_id"))
            scroll_args["scroll_y"] = delta
            branches.append(_batch_auto_branch(
                "desktop_scroll",
                "desktop_scroll",
                scroll_args,
                expect={"path": "$result.message", "exists": True},
                description="desktop wheel scroll at coordinate",
            ))
        else:
            scroll_args = _batch_auto_copy_args(args, ("hwnd", "x", "y", "screenshot_id"))
            scroll_args["dy"] = delta
            branches.append(_batch_auto_branch(
                "wheel_scroll",
                "scroll",
                scroll_args,
                expect={"path": "$result.message", "exists": True},
                description="window wheel scroll at coordinate",
            ))
    keyboard_pref = args.get("keyboard_scroll", args.get("keyboard_fallback"))
    if _coerce_bool(keyboard_pref, not desktop):
        key_args = _batch_auto_copy_args(args, ("hwnd",))
        key_args["keys"] = _batch_auto_scroll_key(args, delta)
        branches.append(_batch_auto_branch(
            "keyboard_scroll",
            "key",
            key_args,
            expect={"path": "$result.message", "exists": True},
            description="keyboard scroll fallback",
        ))
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=desktop)


def _batch_auto_drag_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    layers = args.get("layers")
    if not _batch_auto_layer_enabled(layers, "input"):
        return branches
    hwnd = args.get("hwnd")
    desktop = _coerce_bool(args.get("desktop"), hwnd is None)
    required = ("start_x", "start_y", "end_x", "end_y")
    if not all(args.get(key) is not None for key in required):
        return branches
    if desktop:
        drag_args = _batch_auto_copy_args(args, ("start_x", "start_y", "end_x", "end_y", "duration", "screenshot_id"))
        branches.append(_batch_auto_branch(
            "desktop_drag",
            "desktop_drag",
            drag_args,
            expect={"path": "$result.message", "exists": True},
            description="desktop coordinate drag",
        ))
    else:
        drag_args = _batch_auto_copy_args(args, ("hwnd", "start_x", "start_y", "end_x", "end_y", "duration", "screenshot_id"))
        branches.append(_batch_auto_branch(
            "coordinate_drag",
            "drag",
            drag_args,
            expect={"path": "$result.message", "exists": True},
            description="window coordinate drag",
        ))
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=desktop)


def _batch_auto_menu_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    layers = args.get("layers")
    if not _batch_auto_layer_enabled(layers, "native"):
        return branches
    hwnd = args.get("hwnd")
    menu_path = _batch_auto_first(args, "menu_path")
    command_id = _batch_auto_first(args, "menu_command_id", "command_id")
    if hwnd is None or (menu_path is None and command_id is None):
        return branches
    menu_args = _batch_auto_copy_args(args, ("hwnd", "timeout_ms"))
    menu_args.update({
        "path": menu_path,
        "command_id": command_id,
        "include_system": _coerce_bool(args.get("include_system"), False),
        "async_post": _coerce_bool(args.get("async_post"), False),
    })
    branches.append(_batch_auto_branch(
        "menu_action",
        "menu_action",
        menu_args,
        expect={"path": "$result.ok", "equals": True},
        description="classic Win32 HMENU command",
    ))
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=False)


def _batch_auto_file_dialog_action(args: Dict[str, Any]) -> str:
    path = _batch_auto_first(args, "file_dialog_path")
    action = _batch_auto_first(args, "file_dialog_action", "dialog_action", "action")
    if action is None:
        action = "confirm" if path is not None else "info"
    action_name = str(action or "").strip().lower().replace("-", "_")
    if action_name in ("open", "save", "select", "choose", "ok", "accept"):
        return "confirm"
    if action_name in ("set", "set_path", "set_filename", "filename", "set_file", "set_file_path"):
        return "set_filename"
    if action_name in ("close", "dismiss", "cancel"):
        return "cancel"
    if action_name in ("info", "inspect", "describe", "get"):
        return "info"
    return action_name or "info"


def _batch_auto_file_dialog_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    layers = args.get("layers")
    if not _batch_auto_layer_enabled(layers, "native"):
        return branches
    hwnd = args.get("hwnd")
    action_name = _batch_auto_file_dialog_action(args)
    timeout = _batch_auto_first(args, "timeout", "wait_timeout", "action_timeout")
    if action_name == "info":
        info_args = _batch_auto_copy_args(args, ("hwnd", "timeout_ms"))
        if timeout is not None:
            info_args["timeout"] = timeout
        info_args["include_children"] = _coerce_bool(args.get("include_children"), False)
        branches.append(_batch_auto_branch(
            "file_dialog_info",
            "file_dialog_info",
            info_args,
            expect={"path": "$result.ok", "equals": True},
            description="standard Windows Open/Save dialog probe",
        ))
        return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=True)

    action_args = _batch_auto_copy_args(args, ("hwnd", "timeout_ms"))
    if timeout is not None:
        action_args["timeout"] = timeout
    action_args.update({
        "action": action_name,
        "path": _batch_auto_first(args, "file_dialog_path"),
        "verify_close": _coerce_bool(args.get("verify_close"), False),
    })
    branches.append(_batch_auto_branch(
        "file_dialog_action",
        "file_dialog_action",
        action_args,
        expect={"path": "$result.ok", "equals": True},
        description="standard Windows Open/Save dialog native action",
    ))
    return _batch_auto_apply_post_to_branches(branches, args, hwnd, default_desktop=True)


def _batch_auto_dialog_action_kind(args: Dict[str, Any]) -> str:
    action_kind = _batch_auto_first(args, "dialog_action_kind", "target_kind", "inner_kind")
    if action_kind is None:
        if args.get("item") is not None:
            action_kind = "select"
        elif args.get("row") is not None or args.get("column") is not None or args.get("row_text") is not None or args.get("column_name") is not None:
            action_kind = "cell"
        else:
            action_kind = "click"
    action_kind = str(action_kind or "click").strip().lower().replace("-", "_")
    if action_kind in ("button", "control", "invoke", "press"):
        return "click"
    if action_kind in ("input", "text_input", "textinput", "edit", "set_text", "write", "value"):
        return "text"
    if action_kind in ("choose", "selection", "select_item", "selectitem", "item"):
        return "select"
    if action_kind in ("grid", "table", "listview", "list_view", "row"):
        return "cell"
    return action_kind or "click"


def _batch_auto_desktop_action_name(args: Dict[str, Any]) -> str:
    action = _batch_auto_first(args, "desktop_action", "control_action", "click_action", "uia_action", "action")
    text = str(action or "Invoke").strip()
    normalized = text.lower().replace("-", "_")
    if normalized in ("click", "press", "button", "default", "invoke"):
        return "Invoke"
    if normalized in ("check", "uncheck", "toggle"):
        return "Toggle"
    if normalized in ("select", "selection"):
        return "Select"
    return text or "Invoke"


def _batch_auto_dialog_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    branches: List[Dict[str, Any]] = []
    layers = args.get("layers")
    action_kind = _batch_auto_dialog_action_kind(args)
    if action_kind not in ("click", "text", "select", "cell"):
        return branches

    if action_kind == "click" and _batch_auto_layer_enabled(layers, "native"):
        native_command_args = _batch_auto_copy_args(args, (
            "hwnd", "dialog_title", "dialog_class_name", "dialog_process",
            "name", "match", "timeout", "interval", "timeout_ms",
            "include_invisible", "activate", "verify_close", "diagnostic",
        ))
        native_command_action = _batch_auto_first(args, "dialog_command", "dialog_action", "messagebox_action", "command")
        native_dialog_name = _batch_auto_first(args, "name", "text", "query")
        if native_command_action is not None:
            native_command_args["action"] = native_command_action
        if native_dialog_name is not None:
            native_command_args["name"] = native_dialog_name
        native_command_id = _batch_auto_first(args, "dialog_command_id", "command_id", "menu_command_id")
        if native_command_id is not None:
            native_command_args["command_id"] = native_command_id
        branches.append(_batch_auto_branch(
            "native_dialog_command",
            "dialog_command_action",
            native_command_args,
            description="related Win32 standard dialog WM_COMMAND action",
        ))
        native_dialog_args = _batch_auto_copy_args(args, (
            "hwnd", "dialog_title", "dialog_class_name", "dialog_process",
            "name", "automation_id", "control_type", "class_name", "index", "match",
            "timeout", "interval", "timeout_ms", "include_invisible", "activate", "verify_close", "diagnostic",
        ))
        if native_dialog_name is not None:
            native_dialog_args["name"] = native_dialog_name
        native_dialog_args["prefer_command"] = False
        native_dialog_args["control_type"] = args.get("control_type") or "button"
        branches.append(_batch_auto_branch(
            "native_dialog_button",
            "dialog_button_action",
            native_dialog_args,
            description="related Win32 dialog button action",
        ))

    if _batch_auto_layer_enabled(layers, "semantic"):
        semantic_start = len(branches)
        dialog_args = _batch_auto_copy_args(args, (
            "hwnd", "dialog_title", "dialog_class_name", "dialog_process",
            "name", "automation_id", "control_type", "class_name", "index", "match",
            "text", "item", "row", "column", "row_text", "column_name",
            "control_action", "cell_action", "mode", "timeout", "action_timeout", "interval",
            "input_timeout", "timeout_ms", "verify", "diagnostic", "allow_focus_fallback",
            "allow_coordinate_fallback", "skip_uia", "include_invisible", "activate", "button", "clicks",
        ))
        dialog_stable_ticks = _batch_auto_first(args, "dialog_stable_ticks", "stable_ticks", "stable-ticks")
        if dialog_stable_ticks is not None:
            dialog_args["stable_ticks"] = dialog_stable_ticks
        dialog_repair = _batch_auto_first(args, "action_repair", "selector_repair", "uia_selector_repair", "repair")
        dialog_repair_timeout = _batch_auto_first(args, "action_repair_timeout", "selector_repair_timeout", "repair_timeout")
        if dialog_repair is not None or dialog_repair_timeout is not None:
            dialog_args["repair"] = _batch_auto_smart_wait_repair_requested(args)
        if dialog_repair_timeout is not None:
            dialog_args["repair_timeout"] = dialog_repair_timeout
        dialog_args["action_kind"] = action_kind
        branches.append(_batch_auto_branch(
            "smart_dialog",
            "smart_dialog_action",
            dialog_args,
            description="related dialog smart action",
        ))
        branches = _batch_auto_apply_pre_uia_stable_to_branches(
            branches,
            args,
            args.get("hwnd"),
            start=semantic_start,
            default_desktop=bool(args.get("desktop") or args.get("hwnd") is None),
        )

    if action_kind == "click" and _batch_auto_layer_enabled(layers, "semantic"):
        desktop_semantic_start = len(branches)
        desktop_name = _batch_auto_first(args, "desktop_name", "name", "text", "query")
        desktop_selector = _batch_auto_copy_args(args, (
            "automation_id", "class_name", "value", "match", "timeout", "interval",
            "max_depth", "max_elements", "view", "enabled_only", "visible_only",
        ))
        if desktop_name is not None:
            desktop_selector["name"] = desktop_name
        desktop_selector["control_type"] = args.get("control_type") or "button"
        desktop_selector["pattern"] = args.get("pattern") or "Invoke"
        if desktop_name is not None or args.get("automation_id") is not None or args.get("class_name") is not None:
            wait_id = "desktop_dialog_wait"
            desktop_action_args = {
                "action": _batch_auto_desktop_action_name(args),
                "value": args.get("value"),
                "horizontal": args.get("horizontal"),
                "vertical": args.get("vertical"),
                "max_depth": args.get("max_depth"),
                "max_elements": args.get("max_elements"),
                "view": args.get("view"),
            }
            branches.append({
                "id": "desktop_dialog_uia",
                "description": "desktop-root UIA dialog control action",
                "steps": [
                    {
                        "id": wait_id,
                        "command": "desktop_wait",
                        "args": desktop_selector,
                        "expect": {"path": "$result.match.index", "exists": True},
                        "extract": {"index": "$result.match.index"},
                    },
                    {
                        "id": "desktop_dialog_action",
                        "command": "desktop_action",
                        "args": {
                            "index": f"$steps.{wait_id}.result.value.index",
                            **desktop_action_args,
                        },
                    },
                ],
            })
            repaired = _batch_auto_desktop_uia_repair_branch(
                "desktop_dialog_uia_selector_repair",
                args,
                desktop_selector,
                action_args=desktop_action_args,
                description="desktop-root UIA dialog selector repair",
            )
            if repaired:
                branches.append(repaired)
        branches = _batch_auto_apply_pre_uia_stable_to_branches(
            branches,
            args,
            None,
            start=desktop_semantic_start,
            default_desktop=True,
        )

    if action_kind == "click" and _batch_auto_layer_enabled(layers, "visual"):
        visual_start = len(branches)
        template = _batch_auto_first(args, "template", "template_path", "image")
        text = _batch_auto_first(args, "desktop_text", "text", "query", "name")
        if template:
            image_args = _batch_auto_copy_args(args, ("template", "template_path", "confidence", "max_width", "screenshot_id", "button", "clicks", "timeout", "interval", "region", "scale_min", "scale_max", "scale_step"))
            if "template" not in image_args and "template_path" not in image_args:
                image_args["template"] = template
            branches.append(_batch_auto_branch("desktop_dialog_image", "desktop_image_click", image_args, description="desktop image dialog fallback"))
        if text:
            ocr_args = _batch_auto_copy_args(args, ("lang", "max_width", "screenshot_id", "engine", "match", "index", "button", "clicks", "region", "max_words", "timeout", "interval"))
            ocr_args["text"] = text
            branches.append(_batch_auto_branch("desktop_dialog_ocr", "desktop_ocr_click", ocr_args, description="desktop OCR dialog fallback"))
        branches = _batch_auto_apply_pre_visual_stable_to_branches(
            branches,
            args,
            None,
            start=visual_start,
            default_desktop=True,
        )

    if action_kind == "click" and _batch_auto_layer_enabled(layers, "input") and args.get("x") is not None and args.get("y") is not None:
        input_args = _batch_auto_copy_args(args, ("x", "y", "button", "clicks", "screenshot_id"))
        branches.append(_batch_auto_branch("desktop_dialog_coordinate", "desktop_click", input_args, description="desktop coordinate dialog fallback"))

    return _batch_auto_apply_post_to_branches(branches, args, None, default_desktop=True)


_WINDOW_ACTION_KINDS = {"click", "text", "select", "cell", "dialog", "key", "scroll", "drag", "menu", "file_dialog", "hover"}


def _batch_auto_action_kind(args: Dict[str, Any]) -> str:
    action_kind = _batch_auto_first(args, "action_kind", "target_kind", "inner_kind", "dialog_action_kind")
    if action_kind is None:
        if args.get("file_dialog_action") is not None or args.get("file_dialog_path") is not None:
            action_kind = "file_dialog"
        elif args.get("menu_path") is not None or args.get("menu_command_id") is not None or args.get("command_id") is not None:
            action_kind = "menu"
        elif args.get("hover") is not None or args.get("hover_delay") is not None or args.get("hover_settle") is not None:
            action_kind = "hover"
        elif args.get("keys") is not None:
            action_kind = "key"
        elif args.get("start_x") is not None or args.get("end_x") is not None:
            action_kind = "drag"
        elif args.get("dy") is not None or args.get("delta") is not None:
            action_kind = "scroll"
        elif args.get("item") is not None:
            action_kind = "select"
        elif args.get("row") is not None or args.get("column") is not None or args.get("row_text") is not None or args.get("column_name") is not None:
            action_kind = "cell"
        elif args.get("text") is not None or args.get("value") is not None:
            action_kind = "text"
        else:
            action_kind = "click"
    action_kind = str(action_kind or "click").strip().lower().replace("-", "_")
    if action_kind in ("button", "control", "invoke", "press", "check", "uncheck"):
        return "click"
    if action_kind in ("input", "text_input", "textinput", "edit", "set_text", "write", "value"):
        return "text"
    if action_kind in ("choose", "selection", "select_item", "selectitem", "item"):
        return "select"
    if action_kind in ("grid", "table", "listview", "list_view", "row"):
        return "cell"
    if action_kind in ("popup", "modal", "messagebox", "message_box", "prompt"):
        return "dialog"
    if action_kind in ("file_dialog", "filedialog", "file_picker", "filepicker", "file_open", "file_save", "open_dialog", "save_dialog", "open_save_dialog"):
        return "file_dialog"
    if action_kind in ("shortcut", "hotkey", "keyboard", "press_key", "presskey", "key_input"):
        return "key"
    if action_kind in ("wheel", "mouse_wheel", "mousewheel", "wheel_scroll", "page_scroll"):
        return "scroll"
    if action_kind in ("move_drag", "mouse_drag", "coordinate_drag", "slider_drag"):
        return "drag"
    if action_kind in ("hmenu", "menu_item", "menu_action", "system_menu", "sysmenu"):
        return "menu"
    if action_kind in ("hover", "move", "mouse_move", "mousemove", "mouse_hover", "mouseover", "mouse_over", "point"):
        return "hover"
    return action_kind or "click"


def _batch_auto_pre_boundary_enabled(args: Dict[str, Any]) -> bool:
    return bool(
        _coerce_bool(args.get("pre_boundary"), False)
        or _coerce_bool(args.get("pre_helper"), False)
    )


def _batch_auto_pre_helper_enabled(args: Dict[str, Any]) -> bool:
    return _coerce_bool(args.get("pre_helper"), False)


def _batch_auto_boundary_preflight_steps(args: Dict[str, Any], hwnd_ref: str, id_prefix: str) -> List[Dict[str, Any]]:
    if not _batch_auto_pre_boundary_enabled(args):
        return []
    safe_prefix = str(id_prefix or "target").strip().replace("-", "_").replace(" ", "_") or "target"
    boundary_id = f"{safe_prefix}_pre_boundary"
    steps: List[Dict[str, Any]] = [
        {
            "id": boundary_id,
            "command": "control_boundary",
            "args": {"hwnd": hwnd_ref},
            "expect": {"path": "$result.ok", "equals": True},
            "extract": {
                "needs_elevation": "$result.needs_elevation",
                "uipi_risk": "$result.uipi_risk",
                "can_send_input_likely": "$result.can_send_input_likely",
            },
        },
    ]
    if _batch_auto_pre_helper_enabled(args):
        steps.append({
            "id": f"{safe_prefix}_pre_helper",
            "command": "helper_status",
            "args": {
                "elevated": f"$steps.{boundary_id}.result.value.needs_elevation",
                "start": f"$steps.{boundary_id}.result.value.needs_elevation",
            },
            "when": {"path": f"$steps.{boundary_id}.result.value.needs_elevation", "equals": True},
            "optional": True,
        })
    return steps


def _batch_auto_window_action_window_args(args: Dict[str, Any]) -> Dict[str, Any]:
    window_args = dict(args)
    for key in (
        "name", "automation_id", "control_type", "class_name", "index", "item",
        "text", "value", "row", "column", "row_text", "column_name", "template",
        "template_path", "image", "x", "y", "action", "control_action",
        "click_action", "uia_action", "native_action", "cell_action",
        "keys", "dy", "delta", "scroll_amount", "scroll_x", "scroll_y",
        "keyboard_scroll", "keyboard_fallback", "start_x", "start_y", "end_x",
        "end_y", "duration", "hover", "hover_delay", "hover_settle", "settle", "screenshot_id", "menu_path", "menu_command_id",
        "command_id", "include_system", "async_post", "file_dialog_action",
        "file_dialog_path", "verify_close", "include_children", "pre_boundary",
        "pre_helper", "dialog_stable_ticks", "action_repair",
        "action_repair_timeout", "selector_repair_timeout", "repair_timeout",
    ):
        window_args.pop(key, None)
    if args.get("path") is not None and args.get("msaa_path") is None:
        window_args["path"] = args.get("path")
    window_title = _batch_auto_first(args, "window_title", "window_name", "title")
    if window_title is not None:
        window_args["title"] = window_title
    window_timeout = _batch_auto_first(args, "window_timeout", "wait_timeout", "timeout")
    if window_timeout is not None:
        window_args["timeout"] = window_timeout
    window_layers = args.get("window_layers")
    if window_layers is not None:
        window_args["layers"] = window_layers
    return window_args


def _batch_auto_window_action_args(args: Dict[str, Any], hwnd_ref: str, action_kind: str) -> Dict[str, Any]:
    action_args = dict(args)
    for key in (
        "app", "launch", "path_or_name", "process", "process_name",
        "window_title", "window_name", "window_timeout", "window_layers",
        "activate", "restore", "boundary", "control_boundary", "helper",
        "helper_status", "observe", "observe_window", "include_a11y",
        "include_accessibility", "pre_boundary", "pre_helper",
    ):
        action_args.pop(key, None)
    if action_args.get("path") is not None and action_args.get("msaa_path") is None:
        action_args.pop("path", None)
    action_timeout = _batch_auto_first(args, "action_timeout", "input_timeout")
    if action_timeout is not None:
        action_args["timeout"] = action_timeout
    action_args["kind"] = action_kind
    action_args["hwnd"] = hwnd_ref
    if args.get("action_layers") is not None:
        action_args["layers"] = args.get("action_layers")
    if action_kind == "dialog" and action_args.get("dialog_action_kind") is None:
        action_args["dialog_action_kind"] = _batch_auto_dialog_action_kind(action_args)
    return action_args


def _batch_auto_steps_with_hwnd(steps: List[Dict[str, Any]], action_kind: str, action_args: Dict[str, Any]) -> List[Dict[str, Any]]:
    rewritten: List[Dict[str, Any]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            rewritten.append(step)
            continue
        item = dict(step)
        item.setdefault("id", f"{action_kind}_{item.get('id') or index}")
        step_args = dict(item.get("args") or {})
        step_args["hwnd"] = action_args["hwnd"]
        item["args"] = step_args
        rewritten.append(item)
    return rewritten


def _batch_auto_window_action_branch(window_branch: Dict[str, Any], action_kind: str, args: Dict[str, Any], branch_index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(window_branch, dict):
        return None
    branch_id = str(window_branch.get("id") or f"window_{branch_index}")
    description = window_branch.get("description") or "acquire target window"
    steps: List[Dict[str, Any]] = []
    if "steps" in window_branch or "commands" in window_branch:
        raw_steps = window_branch.get("steps", window_branch.get("commands"))
        if not isinstance(raw_steps, list) or not raw_steps:
            return None
        steps.extend(copy.deepcopy(raw_steps))
        ready_id = str((steps[-1] or {}).get("id") or f"{branch_id}_ready")
        hwnd_ref = f"$steps.{ready_id}.result.value.hwnd"
    else:
        target_step = copy.deepcopy(window_branch)
        target_step["id"] = f"{branch_id}_target"
        target_step["extract"] = {"hwnd": "$result.window.hwnd", "window": "$result.window"}
        steps.append(target_step)
        hwnd_ref = f"$steps.{target_step['id']}.result.value.hwnd"

    steps.extend(_batch_auto_boundary_preflight_steps(args, hwnd_ref, branch_id))

    action_args = _batch_auto_window_action_args(args, hwnd_ref, action_kind)
    action_branches = _batch_auto_branches({"command": "batch_auto"}, action_args)
    if not action_branches:
        return None

    if len(action_branches) == 1 and isinstance(action_branches[0], dict) and "steps" not in action_branches[0] and "commands" not in action_branches[0]:
        action_steps = _batch_auto_steps_with_hwnd([action_branches[0]], action_kind, action_args)
        action_steps = [_batch_auto_attach_recovery(step, args, hwnd_ref) for step in action_steps]
    else:
        rewritten_branches: List[Dict[str, Any]] = []
        for action_branch_index, action_branch in enumerate(action_branches):
            if not isinstance(action_branch, dict):
                continue
            rewritten_branch = copy.deepcopy(action_branch)
            action_branch_id = str(rewritten_branch.get("id") or f"action_{action_branch_index}")
            rewritten_branch["id"] = f"{action_kind}_{action_branch_id}"
            branch_steps, _, _ = _batch_branch_steps(rewritten_branch)
            if branch_steps:
                rewritten_branch["steps"] = _batch_auto_steps_with_hwnd(branch_steps, action_kind, action_args)
                rewritten_branch.pop("command", None)
                rewritten_branch.pop("args", None)
            rewritten_branches.append(rewritten_branch)
        action_steps = [{
            "id": f"{action_kind}_action",
            "command": "batch_try",
            "branches": rewritten_branches,
            "expect": {"path": "$result.ok", "equals": True},
        }]
        action_steps[-1] = _batch_auto_attach_recovery(action_steps[-1], args, hwnd_ref)

    steps.extend(action_steps)
    steps.append({
        "id": "window_action_ready",
        "command": "batch_value",
        "args": {
            "value": {
                "hwnd": hwnd_ref,
                "action_kind": action_kind,
                "window_source": branch_id,
                "action_result": f"$steps.{action_steps[-1].get('id')}.result",
            },
        },
    })
    return {
        "id": f"{branch_id}_{action_kind}",
        "description": f"{description}; then run {action_kind} action in that window",
        "steps": steps,
    }


def _batch_auto_window_action_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    action_kind = _batch_auto_action_kind(args)
    if action_kind not in _WINDOW_ACTION_KINDS:
        return []
    window_args = _batch_auto_window_action_window_args(args)
    window_branches = _batch_auto_window_branches(window_args)
    branches: List[Dict[str, Any]] = []
    for index, window_branch in enumerate(window_branches):
        branch = _batch_auto_window_action_branch(window_branch, action_kind, args, index)
        if branch is not None:
            branches.append(branch)
    return branches


def _batch_auto_sequence_steps(args: Dict[str, Any]) -> List[Any]:
    steps = _batch_auto_first(args, "sequence_steps", "steps", "commands", "actions", "tasks", "workflow", "workflow_steps")
    return steps if isinstance(steps, list) else []


def _batch_auto_sequence_focus_enabled(args: Dict[str, Any]) -> bool:
    return _coerce_bool(_batch_auto_first(args, "sequence_focus", "refocus", "focus_each_step"), False)


def _batch_auto_sequence_step_delay(args: Dict[str, Any]) -> float:
    value = _batch_auto_first(args, "step_delay", "sequence_delay", "between_steps")
    try:
        return max(float(value or 0.0), 0.0)
    except Exception:
        return 0.0


def _batch_auto_sequence_recovery_steps(base_args: Dict[str, Any], step: Dict[str, Any]) -> List[Any]:
    normalized_step = _batch_auto_normalize_args(step) if isinstance(step, dict) else {}
    step_recovery = _batch_auto_first(normalized_step, "recovery", "recover", "sequence_recovery", "recovery_steps", "recover_steps", "on_step_failure", "on_step_fail")
    if step_recovery is None:
        step_args = step.get("args") if isinstance(step.get("args"), dict) else step.get("data") if isinstance(step.get("data"), dict) else None
        if isinstance(step_args, dict):
            step_args = _batch_auto_normalize_args(step_args)
            step_recovery = _batch_auto_first(step_args, "sequence_recovery", "recovery", "recover", "recovery_steps", "recover_steps", "on_step_failure", "on_step_fail")
    if step_recovery is None:
        step_recovery = _batch_auto_first(base_args, "sequence_recovery", "recovery", "recover", "recovery_steps", "recover_steps", "on_step_failure", "on_step_fail")
    if step_recovery is None:
        return []
    if isinstance(step_recovery, list):
        return list(step_recovery)
    if isinstance(step_recovery, dict) and ("steps" in step_recovery or "commands" in step_recovery):
        recovery_steps = step_recovery.get("steps", step_recovery.get("commands"))
        return list(recovery_steps) if isinstance(recovery_steps, list) else []
    if isinstance(step_recovery, dict):
        return [step_recovery]
    return []


def _batch_auto_sequence_recovery_focus_enabled(base_args: Dict[str, Any], step: Dict[str, Any]) -> bool:
    normalized_step = _batch_auto_normalize_args(step) if isinstance(step, dict) else {}
    step_value = _batch_auto_first(normalized_step, "sequence_recovery_focus", "recovery_focus", "refocus_on_recovery", "refocus_on_retry")
    if step_value is None:
        step_args = step.get("args") if isinstance(step.get("args"), dict) else step.get("data") if isinstance(step.get("data"), dict) else None
        if isinstance(step_args, dict):
            step_args = _batch_auto_normalize_args(step_args)
            step_value = _batch_auto_first(step_args, "sequence_recovery_focus", "recovery_focus", "refocus_on_recovery", "refocus_on_retry")
    if step_value is None:
        step_value = _batch_auto_first(base_args, "sequence_recovery_focus", "recovery_focus", "refocus_on_recovery", "refocus_on_retry")
    return _coerce_bool(step_value, True)


def _batch_auto_sequence_recovery_delay(base_args: Dict[str, Any], step: Dict[str, Any]) -> float:
    normalized_step = _batch_auto_normalize_args(step) if isinstance(step, dict) else {}
    value = _batch_auto_first(normalized_step, "sequence_recovery_delay", "recovery_delay", "recover_delay", "retry_delay_after_recovery")
    if value is None:
        step_args = step.get("args") if isinstance(step.get("args"), dict) else step.get("data") if isinstance(step.get("data"), dict) else None
        if isinstance(step_args, dict):
            step_args = _batch_auto_normalize_args(step_args)
            value = _batch_auto_first(step_args, "sequence_recovery_delay", "recovery_delay", "recover_delay", "retry_delay_after_recovery")
    if value is None:
        value = _batch_auto_first(base_args, "sequence_recovery_delay", "recovery_delay", "recover_delay", "retry_delay_after_recovery")
    try:
        return max(float(value or 0.0), 0.0)
    except Exception:
        return 0.0


def _batch_auto_sequence_step_option_present(base_args: Dict[str, Any], step: Dict[str, Any], keys: Tuple[str, ...]) -> bool:
    for source in (base_args, step):
        if isinstance(source, dict):
            normalized = _batch_auto_normalize_args(source)
            if any(key in normalized and normalized.get(key) is not None for key in keys):
                return True
    for nested_key in ("args", "data"):
        nested = step.get(nested_key) if isinstance(step, dict) else None
        if isinstance(nested, dict):
            normalized = _batch_auto_normalize_args(nested)
            if any(key in normalized and normalized.get(key) is not None for key in keys):
                return True
    return False


def _batch_auto_sequence_recovery_requested(base_args: Dict[str, Any], step: Dict[str, Any]) -> bool:
    if _batch_auto_sequence_recovery_steps(base_args, step):
        return True
    if _batch_auto_sequence_recovery_delay(base_args, step) > 0:
        return True
    return _batch_auto_sequence_step_option_present(
        base_args,
        step,
        ("sequence_recovery_focus", "recovery_focus", "refocus_on_recovery", "refocus_on_retry"),
    )


def _batch_auto_sequence_focus_step(args: Dict[str, Any], hwnd_ref: str, step_id: str) -> Dict[str, Any]:
    return {
        "id": step_id,
        "command": "focus_hwnd",
        "args": {
            "hwnd": hwnd_ref,
            "timeout": args.get("focus_timeout", args.get("timeout", 1.0)),
            "restore": _coerce_bool(args.get("restore"), True),
        },
        "expect": {"path": "$result.ok", "equals": True},
    }


def _batch_auto_sequence_recovery_action_steps(base_args: Dict[str, Any], step: Dict[str, Any], hwnd_ref: str, index: int) -> List[Dict[str, Any]]:
    recovery_items: List[Dict[str, Any]] = []
    if _batch_auto_sequence_recovery_focus_enabled(base_args, step):
        recovery_items.append(_batch_auto_sequence_focus_step(base_args, hwnd_ref, f"sequence_{index + 1}_recovery_focus"))
    for recovery_index, recovery_step in enumerate(_batch_auto_sequence_recovery_steps(base_args, step)):
        generated = _batch_auto_sequence_action_step(base_args, recovery_step, hwnd_ref, index, allow_recovery=False)
        if generated is None:
            continue
        item = copy.deepcopy(generated)
        recovery_id = str(item.get("id") or f"step")
        item["id"] = f"sequence_{index + 1}_recovery_{recovery_index + 1}_{recovery_id}"
        recovery_items.append(item)
    recovery_delay = _batch_auto_sequence_recovery_delay(base_args, step)
    if recovery_delay > 0:
        recovery_items.append({
            "id": f"sequence_{index + 1}_recovery_delay",
            "command": "batch_sleep",
            "args": {"delay": recovery_delay},
            "expect": {"path": "$result.ok", "equals": True},
        })
    return recovery_items


def _batch_auto_sequence_with_recovery(base_args: Dict[str, Any], step: Dict[str, Any], hwnd_ref: str, index: int, generated: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(step, dict) or not _batch_auto_sequence_recovery_requested(base_args, step):
        return generated
    step_id = str(generated.get("id") or step.get("id") or step.get("as") or step.get("name") or step.get("label") or f"sequence_{index + 1}")
    primary_step = copy.deepcopy(generated)
    primary_step["id"] = f"{step_id}_attempt"
    retry_step = copy.deepcopy(generated)
    retry_step["id"] = f"{step_id}_retry"
    recovery_steps = _batch_auto_sequence_recovery_action_steps(base_args, step, hwnd_ref, index)
    if not recovery_steps:
        return generated
    recovery_steps.append(retry_step)
    return {
        "id": step_id,
        "command": "batch_try",
        "branches": [
            {
                "id": f"{step_id}_primary",
                "description": "try sequence step",
                "steps": [primary_step],
            },
            {
                "id": f"{step_id}_recover",
                "description": "recover target window and retry sequence step",
                "steps": recovery_steps,
            },
        ],
        "expect": {"path": "$result.ok", "equals": True},
    }


def _batch_auto_sequence_step_args(base_args: Dict[str, Any], step: Dict[str, Any], hwnd_ref: str, index: int) -> Tuple[str, Dict[str, Any]]:
    step_args = _batch_auto_normalize_args(dict(step.get("args") if isinstance(step.get("args"), dict) else step.get("data") if isinstance(step.get("data"), dict) else step))
    action_kind = _batch_auto_action_kind(step_args)
    if action_kind not in _WINDOW_ACTION_KINDS:
        action_kind = "click"
    merged: Dict[str, Any] = {}
    for key in (
        "layers", "action_layers", "timeout", "action_timeout", "interval", "timeout_ms",
        "diagnostic", "skip_uia", "allow_coordinate_fallback", "allow_focus_fallback",
        "repair", "selector_repair", "uia_selector_repair", "native_selector_repair",
        "selector_variant_limit", "allow_weak_selector_fallback",
        "dialog_stable_ticks", "action_repair", "repair_timeout",
        "selector_repair_timeout", "action_repair_timeout",
        "capture_mode", "post_delay", "post_timeout", "post_interval", "post_observe",
        "post_event", "post_steps", "verify_selector", "verify_name", "verify_value",
        "verify_automation_id", "verify_control_type", "verify_class_name",
        "verify_pattern", "verify_text", "verify_image", "verify_pixel",
        "verify_pixel_color", "verify_pixel_x", "verify_pixel_y",
        "verify_pixel_tolerance", "verify_pixel_mode",
        "post_stable", "post_stable_region", "post_stable_ticks",
        "post_difference_threshold", "post_pixel_threshold",
        "post_stable_max_width", "post_uia_stable",
        "post_uia_stable_ticks", "post_uia_stable_max_depth",
        "post_uia_stable_max_elements", "post_uia_stable_view",
        "post_uia_stable_include_values", "post_uia_stable_rect_bucket",
        "verify_win32_state", "verify_native_state", "verify_state",
        "verify_win32_present", "verify_native_present", "verify_present",
        "verify_win32_absent", "verify_native_absent", "verify_absent",
        "native_wait_repair", "native_wait_repair_match",
        "native_wait_repair_timeout",
        "verify_checked", "verify_selected", "verify_expanded", "verify_visited",
        "verify_win32_expected", "verify_native_expected", "verify_expected",
        "verify_win32_index", "verify_native_index", "verify_item_index",
        "verify_win32_text", "verify_native_text", "verify_item",
        "verify_win32_match", "verify_native_match",
        "verify_win32_timeout_ms", "verify_native_timeout_ms",
        "verify_win32_max_items", "verify_native_max_items",
        "verify_absent_selector", "verify_absent_name", "verify_absent_value",
        "verify_absent_automation_id", "verify_absent_control_type",
        "verify_absent_class_name", "verify_absent_pattern",
        "verify_absent_text", "verify_absent_image",
        "verify_absent_pixel", "verify_absent_pixel_color",
    ):
        if key in base_args and base_args.get(key) is not None:
            merged[key] = base_args.get(key)
    merged.update(step_args)
    merged["kind"] = action_kind
    if "action_timeout" in merged and "timeout" not in step_args:
        merged["timeout"] = merged.get("action_timeout")
    if merged.get("action_layers") is not None and "layers" not in step_args:
        merged["layers"] = merged.get("action_layers")
    merged["hwnd"] = hwnd_ref
    merged.setdefault("sequence_index", index)
    return action_kind, merged


def _batch_auto_sequence_action_step(base_args: Dict[str, Any], step: Any, hwnd_ref: str, index: int, allow_recovery: bool = True) -> Optional[Dict[str, Any]]:
    if not isinstance(step, dict):
        return {
            "id": f"sequence_{index + 1}_invalid",
            "command": "batch_value",
            "args": {"value": {"ok": False, "error": "invalid_sequence_step", "index": index, "step_type": type(step).__name__}},
            "expect": {"path": "$result.value.ok", "equals": True},
        }
    if step.get("command") or step.get("path"):
        item = copy.deepcopy(step)
        step_id = _batch_step_id(item) or f"sequence_{index + 1}_command"
        item["id"] = step_id
        args = dict(_batch_item_args(item, use_data=bool(item.get("path") and not item.get("command"))))
        normalized_item = _batch_auto_normalize_args(dict(step))
        normalized_step = _batch_auto_normalize_args(dict(args))
        post_args = {key: base_args.get(key) for key in _BATCH_AUTO_POST_ARG_KEYS if base_args.get(key) is not None}
        post_args.update({key: value for key, value in normalized_item.items() if key in _BATCH_AUTO_POST_ARG_KEYS})
        post_args.update({key: value for key, value in normalized_step.items() if key in _BATCH_AUTO_POST_ARG_KEYS})
        if not args.get("desktop") and args.get("hwnd") is None:
            args["hwnd"] = hwnd_ref
        if "args" in item or "command" in item:
            item["args"] = args
            item.pop("data", None)
        else:
            item["data"] = args
        if _batch_auto_post_spec_present(post_args):
            post_branch = _batch_auto_with_post_steps(item, {**post_args, "hwnd": hwnd_ref}, hwnd_ref, id_prefix=step_id)
            for cleanup_key in (
                "post-delay", "post_delay", "post-timeout", "post_timeout",
                "post-interval", "post_interval", "post-observe", "post_observe",
                "post-event", "post_event", "post-steps", "post_steps",
                "post-stable", "post_stable", "post-visual-stable", "post_visual_stable",
                "post-stable-region", "post_stable_region",
                "post-stable-ticks", "post_stable_ticks",
                "post-difference-threshold", "post_difference_threshold",
                "post-pixel-threshold", "post_pixel_threshold",
                "post-stable-max-width", "post_stable_max_width",
                "post-uia-stable", "post_uia_stable",
                "post-structure-stable", "post_structure_stable",
                "post-uia-stable-ticks", "post_uia_stable_ticks",
                "post-uia-stable-max-depth", "post_uia_stable_max_depth",
                "post-uia-stable-max-elements", "post_uia_stable_max_elements",
                "post-uia-stable-view", "post_uia_stable_view",
                "post-uia-stable-include-values", "post_uia_stable_include_values",
                "post-uia-stable-rect-bucket", "post_uia_stable_rect_bucket",
                "verify-present", "verify_present", "verify-exists", "verify_exists",
                "verify-win32-present", "verify_win32_present",
                "verify-native-present", "verify_native_present",
                "verify-item-present", "verify_item_present",
                "verify-present-item", "verify_present_item",
                "verify-absent", "verify_absent", "verify-not-present", "verify_not_present",
                "verify-win32-absent", "verify_win32_absent",
                "verify-native-absent", "verify_native_absent",
                "verify-item-absent", "verify_item_absent",
                "verify-absent-item", "verify_absent_item",
                "verify-missing-item", "verify_missing_item",
                "verify-gone-item", "verify_gone_item",
                "native-wait-repair", "native_wait_repair",
                "win32-wait-repair", "win32_wait_repair",
                "verify-native-repair", "verify_native_repair",
                "verify-win32-repair", "verify_win32_repair",
                "native-wait-repair-match", "native_wait_repair_match",
                "win32-wait-repair-match", "win32_wait_repair_match",
                "verify-native-repair-match", "verify_native_repair_match",
                "verify-win32-repair-match", "verify_win32_repair_match",
                "native-wait-repair-timeout", "native_wait_repair_timeout",
                "win32-wait-repair-timeout", "win32_wait_repair_timeout",
                "verify-native-repair-timeout", "verify_native_repair_timeout",
                "verify-win32-repair-timeout", "verify_win32_repair_timeout",
                "verify-name", "verify_name", "verify-value", "verify_value",
                "verify-automation-id", "verify_automation_id",
                "verify-control-type", "verify_control_type",
                "verify-class-name", "verify_class_name",
                "verify-pattern", "verify_pattern", "verify-text", "verify_text",
                "verify-image", "verify_image", "verify-selector", "verify_selector",
                "verify-pixel", "verify_pixel", "verify-pixel-color", "verify_pixel_color",
                "verify-pixel-x", "verify_pixel_x", "verify-pixel-y", "verify_pixel_y",
                "verify-pixel-tolerance", "verify_pixel_tolerance",
                "verify-pixel-mode", "verify_pixel_mode",
                "verify-absent-name", "verify_absent_name",
                "verify-gone-name", "verify_missing_name",
                "verify-absent-value", "verify_absent_value",
                "verify-gone-value", "verify_missing_value",
                "verify-absent-automation-id", "verify_absent_automation_id",
                "verify-gone-automation-id", "verify_missing_automation_id",
                "verify-absent-control-type", "verify_absent_control_type",
                "verify-gone-control-type", "verify_missing_control_type",
                "verify-absent-class-name", "verify_absent_class_name",
                "verify-gone-class-name", "verify_missing_class_name",
                "verify-absent-pattern", "verify_absent_pattern",
                "verify-gone-pattern", "verify_missing_pattern",
                "verify-absent-text", "verify_absent_text",
                "verify-gone-text", "verify_missing_text",
                "verify-absent-image", "verify_absent_image",
                "verify-gone-image", "verify_missing_image",
                "verify-absent-pixel", "verify_absent_pixel",
                "verify-gone-pixel", "verify_missing_pixel",
                "verify-absent-pixel-color", "verify_absent_pixel_color",
                "verify-gone-pixel-color", "verify_missing_pixel_color",
                "verify-absent-selector", "verify_absent_selector",
                "verify-gone-selector", "verify_missing_selector",
            ):
                post_branch.pop(cleanup_key, None)
                for nested in post_branch.get("steps") or []:
                    if isinstance(nested, dict):
                        nested.pop(cleanup_key, None)
            item = {
                "id": step_id,
                "command": "batch_try",
                "branches": [post_branch],
                "expect": {"path": "$result.ok", "equals": True},
            }
        return _batch_auto_sequence_with_recovery(base_args, step, hwnd_ref, index, item) if allow_recovery else item

    action_kind, action_args = _batch_auto_sequence_step_args(base_args, step, hwnd_ref, index)
    action_branches = _batch_auto_branches({"command": "batch_auto"}, action_args)
    if not action_branches:
        return {
            "id": str(step.get("id") or f"sequence_{index + 1}_{action_kind}"),
            "command": "batch_value",
            "args": {"value": {"ok": False, "error": "invalid_sequence_action", "index": index, "kind": action_kind}},
            "expect": {"path": "$result.value.ok", "equals": True},
        }
    rewritten_branches: List[Dict[str, Any]] = []
    for branch_index, action_branch in enumerate(action_branches):
        if not isinstance(action_branch, dict):
            continue
        rewritten_branch = copy.deepcopy(action_branch)
        action_branch_id = str(rewritten_branch.get("id") or f"action_{branch_index}")
        rewritten_branch["id"] = f"step{index + 1}_{action_branch_id}"
        branch_steps, _, _ = _batch_branch_steps(rewritten_branch)
        if branch_steps:
            rewritten_branch["steps"] = _batch_auto_steps_with_hwnd(branch_steps, action_kind, action_args)
            rewritten_branch.pop("command", None)
            rewritten_branch.pop("args", None)
        rewritten_branches.append(rewritten_branch)
    generated = {
        "id": str(step.get("id") or step.get("as") or step.get("name") or step.get("label") or f"sequence_{index + 1}_{action_kind}"),
        "command": "batch_try",
        "branches": rewritten_branches,
        "expect": step.get("expect", {"path": "$result.ok", "equals": True}),
    }
    return _batch_auto_sequence_with_recovery(base_args, step, hwnd_ref, index, generated) if allow_recovery else generated


def _batch_auto_window_sequence_branch(window_branch: Dict[str, Any], args: Dict[str, Any], branch_index: int) -> Optional[Dict[str, Any]]:
    sequence_steps = _batch_auto_sequence_steps(args)
    if not sequence_steps:
        return None
    if not isinstance(window_branch, dict):
        return None
    branch_id = str(window_branch.get("id") or f"window_{branch_index}")
    description = window_branch.get("description") or "acquire target window"
    steps: List[Dict[str, Any]] = []
    if "steps" in window_branch or "commands" in window_branch:
        raw_steps = window_branch.get("steps", window_branch.get("commands"))
        if not isinstance(raw_steps, list) or not raw_steps:
            return None
        steps.extend(copy.deepcopy(raw_steps))
        ready_id = str((steps[-1] or {}).get("id") or f"{branch_id}_ready")
        hwnd_ref = f"$steps.{ready_id}.result.value.hwnd"
    else:
        target_step = copy.deepcopy(window_branch)
        target_step["id"] = f"{branch_id}_target"
        target_step["extract"] = {"hwnd": "$result.window.hwnd", "window": "$result.window"}
        steps.append(target_step)
        hwnd_ref = f"$steps.{target_step['id']}.result.value.hwnd"

    preflight_steps = _batch_auto_boundary_preflight_steps(args, hwnd_ref, branch_id)
    steps.extend(preflight_steps)

    action_step_ids: List[str] = [str(step.get("id")) for step in preflight_steps if isinstance(step, dict) and step.get("id")]
    refocus = _batch_auto_sequence_focus_enabled(args)
    step_delay = _batch_auto_sequence_step_delay(args)
    for index, sequence_step in enumerate(sequence_steps):
        if refocus:
            focus_id = f"sequence_{index + 1}_focus"
            action_step_ids.append(focus_id)
            steps.append(_batch_auto_sequence_focus_step(args, hwnd_ref, focus_id))
        generated = _batch_auto_sequence_action_step(args, sequence_step, hwnd_ref, index)
        if generated is None:
            return None
        generated = _batch_auto_attach_recovery(generated, args, hwnd_ref)
        action_step_ids.append(str(generated.get("id") or f"sequence_{index + 1}"))
        steps.append(generated)
        if step_delay > 0 and index < len(sequence_steps) - 1:
            delay_id = f"sequence_{index + 1}_delay"
            action_step_ids.append(delay_id)
            steps.append({
                "id": delay_id,
                "command": "batch_sleep",
                "args": {"delay": step_delay},
                "expect": {"path": "$result.ok", "equals": True},
            })
    steps.append({
        "id": "window_sequence_ready",
        "command": "batch_value",
        "args": {
            "value": {
                "hwnd": hwnd_ref,
                "window_source": branch_id,
                "step_ids": action_step_ids,
                "step_count": len(action_step_ids),
            },
        },
    })
    return {
        "id": f"{branch_id}_sequence",
        "description": f"{description}; then run {len(action_step_ids)} actions in that window",
        "steps": steps,
    }


def _batch_auto_window_sequence_branches(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not _batch_auto_sequence_steps(args):
        return []
    window_args = _batch_auto_window_action_window_args(args)
    window_branches = _batch_auto_window_branches(window_args)
    branches: List[Dict[str, Any]] = []
    for index, window_branch in enumerate(window_branches):
        branch = _batch_auto_window_sequence_branch(window_branch, args, index)
        if branch is not None:
            branches.append(branch)
    return branches


def _batch_auto_branches(item: Dict[str, Any], args: Dict[str, Any]) -> List[Dict[str, Any]]:
    explicit = item.get("branches", item.get("alternatives"))
    if explicit is None and isinstance(args, dict):
        explicit = args.get("branches", args.get("alternatives"))
    if isinstance(explicit, list) and explicit:
        return explicit
    args = _batch_auto_normalize_args(args)
    kind = _batch_auto_kind(item, args)
    if kind in ("window_sequence", "window_workflow", "app_sequence", "app_workflow", "target_sequence", "workflow", "sequence"):
        return _batch_auto_window_sequence_branches(args)
    if kind in ("window_action", "window_control", "app_action", "app_control", "application_action", "target_action", "ensure_action", "recover_action"):
        return _batch_auto_window_action_branches(args)
    if kind in ("click", "invoke", "press", "button", "check", "uncheck"):
        auto_args = dict(args)
        if kind in ("check", "uncheck") and "action" not in auto_args:
            auto_args["action"] = kind
        return _batch_auto_click_branches(auto_args)
    if kind in ("text", "input", "type", "set_text", "write", "value"):
        return _batch_auto_text_branches(args)
    if kind in ("select", "selection", "choose", "item"):
        return _batch_auto_select_branches(args)
    if kind in ("cell", "grid", "table", "row"):
        return _batch_auto_cell_branches(args)
    if kind in ("dialog", "popup", "modal", "messagebox", "message_box", "prompt"):
        return _batch_auto_dialog_branches(args)
    if kind in ("file_dialog", "filedialog", "file_picker", "file-picker", "filepicker", "open_dialog", "save_dialog", "open_save_dialog", "file_open", "file_save"):
        return _batch_auto_file_dialog_branches(args)
    if kind in ("key", "keys", "shortcut", "hotkey", "keyboard", "press_key", "presskey"):
        return _batch_auto_key_branches(args)
    if kind in ("hover", "move", "mouse_move", "mousemove", "mouse_hover", "mouseover", "mouse_over", "point"):
        return _batch_auto_hover_branches(args)
    if kind in ("scroll", "wheel", "mouse_wheel", "mousewheel", "wheel_scroll", "page_scroll"):
        return _batch_auto_scroll_branches(args)
    if kind in ("drag", "mouse_drag", "coordinate_drag", "move_drag", "slider_drag"):
        return _batch_auto_drag_branches(args)
    if kind in ("menu", "hmenu", "menu_item", "menu_action", "system_menu", "sysmenu"):
        return _batch_auto_menu_branches(args)
    if kind in ("window", "app", "application", "target", "launch_window", "ensure_window", "recover_window"):
        return _batch_auto_window_branches(args)
    return []


def _batch_auto_plan_layer(command: str, step_id: Optional[str] = None) -> str:
    text = str(command or "").strip().lower().replace("-", "_")
    ident = str(step_id or "").strip().lower().replace("-", "_")
    probe = f"{ident} {text}"
    if text in ("batch_try", "batch_repeat", "batch_until", "batch_value", "batch_sleep"):
        return "orchestration"
    if text.startswith("smart_") or text in ("uia_accessibility", "uia_find", "uia_selector_repair_find", "uia_cell_selector_repair_find", "uia_wait", "uia_stable_wait", "uia_element", "uia_click_index", "uia_set_value", "uia_action", "desktop_accessibility", "desktop_find", "desktop_wait", "desktop_uia_stable_wait", "desktop_element", "desktop_focus", "desktop_click_index", "desktop_action", "observe", "auto_window"):
        return "semantic"
    if text.startswith("win32_") or text in ("wait_window", "window_selector_repair_find", "window_action", "focus_hwnd", "activate", "foreground", "control_boundary", "helper_status", "gui_thread_info", "focused_input", "file_dialog_info", "file_dialog_action", "dialog_command_action", "dialog_button_action", "child_windows", "window_from_point", "menu_tree", "menu_action"):
        return "native"
    if text.startswith("msaa_") or "msaa" in probe or "legacy" in probe:
        return "msaa"
    if "ocr" in probe or "image" in probe or "pixel" in probe or text in ("screenshot", "desktop_screenshot", "element_from_point", "visual_row", "visual_row_click", "visual_row_scroll", "visual_row_scroll_click", "ocr_scroll_click", "desktop_ocr_scroll_click", "image_scroll_click", "desktop_image_scroll_click"):
        return "visual"
    if text in ("move", "desktop_move", "click", "type", "type_foreground", "key", "scroll", "drag", "desktop_click", "desktop_scroll", "desktop_drag", "launch") or "coordinate" in probe:
        return "input"
    return "other"


def _batch_auto_plan_unique_append(values: List[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in values:
        values.append(text)


def _batch_auto_plan_extract_selectors(args: Any) -> Dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    selector: Dict[str, Any] = {}
    for key in ("hwnd", "title", "window_title", "dialog_title", "dialog_class_name", "dialog_process", "process", "process_name", "app", "path_or_name", "name", "automation_id", "control_type", "class_name", "text", "item", "row", "column", "row_text", "column_name", "template", "template_path", "x", "y", "timeout", "action", "action_kind", "dialog_action_kind", "mode", "hover", "settle"):
        value = args.get(key)
        if value is not None:
            selector[key] = value
    return selector


def _batch_auto_plan_args(args: Any) -> Any:
    if not isinstance(args, dict) or "__batch_arg_error__" in args:
        return args
    return _batch_auto_normalize_args(args)


def _batch_auto_plan_extract_options(args: Any) -> Dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    options: Dict[str, Any] = {}
    for key in (
        "repair", "repair_timeout", "selector_repair", "uia_selector_repair",
        "native_selector_repair", "action_repair", "selector_repair_timeout",
        "action_repair_timeout", "stable_ticks", "dialog_stable_ticks",
        "native_wait_repair", "native_wait_repair_match",
        "native_wait_repair_timeout",
        "allow_suggestion_index",
        "verify", "diagnostic", "skip_uia", "allow_focus_fallback",
        "allow_coordinate_fallback",
    ):
        value = args.get(key)
        if value is not None:
            options[key] = value
    return options


def _batch_auto_plan_smart_wait_repair_requested(args: Any) -> bool:
    if not isinstance(args, dict):
        return False
    return _batch_auto_smart_wait_repair_requested(args)


def _batch_auto_plan_native_wait_repair_requested(args: Any) -> bool:
    if not isinstance(args, dict):
        return False
    repair = _batch_auto_first(args, "repair", "native_wait_repair", "verify_win32_repair", "verify_native_repair")
    return _win32_repair_requested(
        repair,
        _batch_auto_first(args, "repair_match", "native_wait_repair_match", "verify_win32_repair_match", "verify_native_repair_match"),
        _batch_auto_first(args, "repair_timeout", "native_wait_repair_timeout", "verify_win32_repair_timeout", "verify_native_repair_timeout"),
    )


def _batch_auto_plan_add_risk(summary: Dict[str, Any], flag: str, recommendation: Optional[str] = None, detail: Optional[Dict[str, Any]] = None) -> None:
    _batch_auto_plan_unique_append(summary.setdefault("risk_flags", []), flag)
    if recommendation:
        _batch_auto_plan_unique_append(summary.setdefault("recommendations", []), recommendation)
    if detail:
        details = summary.setdefault("risk_details", [])
        if isinstance(details, list) and len(details) < 16:
            details.append({k: v for k, v in detail.items() if v not in (None, "", [], {})})


def _batch_auto_plan_selector_is_stable(args: Dict[str, Any]) -> bool:
    if not isinstance(args, dict):
        return False
    stable_keys = (
        "automation_id", "control_type", "class_name", "index", "pattern",
        "process", "process_name", "app", "path_or_name", "title", "window_title",
        "row", "column", "row_text", "column_name",
    )
    return any(args.get(key) is not None for key in stable_keys)


def _batch_auto_plan_selector_is_weak(args: Dict[str, Any]) -> bool:
    if not isinstance(args, dict):
        return False
    has_human_text = any(args.get(key) is not None for key in ("name", "text", "item", "value"))
    has_position = args.get("x") is not None and args.get("y") is not None
    return bool((has_human_text or has_position) and not _batch_auto_plan_selector_is_stable(args))


def _batch_auto_plan_safety_probe(step: Dict[str, Any], args: Dict[str, Any], command_name: str, step_id: Optional[str]) -> Optional[Dict[str, Any]]:
    values: List[str] = []
    for value in (step_id, command_name, step.get("description"), step.get("reason")):
        if value is not None:
            values.append(str(value))
    if isinstance(args, dict):
        for key in ("action", "control_action", "click_action", "uia_action", "name", "item"):
            value = args.get(key)
            if value is not None:
                values.append(str(value))
    for value in values:
        result = check_safety(value)
        if result.get("needs_confirmation"):
            return result
    return None


def _batch_auto_plan_mark_risks(step: Dict[str, Any], args: Dict[str, Any], summary: Dict[str, Any], command_name: str, step_id: Optional[str], layer: str) -> None:
    lowered = f"{step_id or ''} {command_name or ''} {step.get('path') or ''}".lower().replace("-", "_")
    if command_name == "launch" or "launch" in lowered:
        _batch_auto_plan_add_risk(
            summary,
            "requires_launch",
            "Prefer a title/process/app acquisition branch before launch so existing windows are reused when possible.",
            {"id": step_id, "command": command_name},
        )
    if command_name in ("control_boundary", "helper_status") or "elevat" in lowered or (isinstance(args, dict) and args.get("elevated") is not None):
        _batch_auto_plan_add_risk(
            summary,
            "may_need_elevation",
            "Run control_boundary first and start the elevated helper only when needs_elevation/uipi_risk is reported.",
            {"id": step_id, "command": command_name},
        )
    if layer == "input" and (command_name in ("move", "desktop_move", "click", "desktop_click") or "coordinate" in lowered or (isinstance(args, dict) and args.get("x") is not None and args.get("y") is not None)):
        _batch_auto_plan_add_risk(
            summary,
            "uses_coordinate_fallback",
            "Prefer semantic/native selectors first; use coordinates with a fresh screenshot_id and verified focus.",
            {"id": step_id, "command": command_name, "x": args.get("x") if isinstance(args, dict) else None, "y": args.get("y") if isinstance(args, dict) else None},
        )
    if layer == "visual":
        _batch_auto_plan_add_risk(
            summary,
            "uses_visual_fallback",
            "Constrain visual fallbacks with capture_mode/region and keep semantic selectors before OCR/image branches.",
            {"id": step_id, "command": command_name},
        )
    if layer == "semantic" and _batch_auto_plan_selector_is_weak(args):
        _batch_auto_plan_add_risk(
            summary,
            "lacks_stable_selector",
            "Add automation_id, control_type, class_name, index, row/column metadata, or process/title constraints when available.",
            {"id": step_id, "command": command_name, "selectors": _batch_auto_plan_extract_selectors(args)},
        )
    safety = _batch_auto_plan_safety_probe(step, args, command_name, step_id)
    if safety:
        _batch_auto_plan_add_risk(
            summary,
            "contains_sensitive_or_destructive_action",
            "Require explicit user confirmation before executing destructive, account, permission, message, install, or payment actions.",
            {"id": step_id, "command": command_name, "category": safety.get("category"), "action": safety.get("action")},
        )


def _batch_auto_plan_visit_step(step: Any, summary: Dict[str, Any], preview: List[Dict[str, Any]], depth: int = 0, preview_limit: int = 12) -> None:
    if not isinstance(step, dict):
        summary["invalid_step_count"] = int(summary.get("invalid_step_count", 0)) + 1
        return
    command, path, raw_args = _batch_command_parts(step)
    args = _batch_auto_plan_args(raw_args)
    step_id = _batch_step_id(step)
    command_name = command or _batch_command_from_path(path) if path else command
    layer = _batch_auto_plan_layer(command_name, step_id)
    summary["step_count"] = int(summary.get("step_count", 0)) + 1
    summary["max_depth"] = max(int(summary.get("max_depth", 0)), depth)
    _batch_auto_plan_unique_append(summary.setdefault("commands", []), command_name or path or "step")
    _batch_auto_plan_unique_append(summary.setdefault("layers", []), layer)
    if step_id:
        _batch_auto_plan_unique_append(summary.setdefault("step_ids", []), step_id)
    lowered = f"{step_id or ''} {command_name or ''} {path or ''}".lower().replace("-", "_")
    if "recover" in lowered or "recovery" in lowered or _batch_step_recovery_spec(step, args) is not None:
        summary["has_recovery"] = True
    if command_name == "control_boundary" or (command_name == "auto_window" and _coerce_bool(_batch_auto_first(args, "boundary", "control_boundary"), True)):
        summary["has_boundary_preflight"] = True
    if command_name == "helper_status":
        summary["has_conditional_helper"] = bool(step.get("when")) or str((args or {}).get("elevated", "")).startswith("$")
    if command_name == "auto_window" and _coerce_bool(_batch_auto_first(args, "helper", "helper_status"), False):
        summary["has_conditional_helper"] = True
    if "selector_repair" in lowered:
        summary["has_selector_repair"] = True
        if "uia_selector_repair" in lowered or command_name in ("uia_selector_repair_find", "uia_cell_selector_repair_find"):
            summary["has_uia_selector_repair"] = True
        if "window_selector_repair" in lowered:
            summary["has_window_selector_repair"] = True
        if "win32" in lowered or command_name == "win32_control_find":
            summary["has_native_selector_repair"] = True
    if command_name == "smart_dialog_action":
        summary["has_wait"] = True
        summary["has_dialog_stable_wait"] = True
        if _batch_auto_plan_smart_wait_repair_requested(args):
            summary["has_dialog_action_repair"] = True
            summary["has_selector_repair"] = True
            if not _coerce_bool(args.get("skip_uia"), False):
                summary["has_uia_selector_repair"] = True
    if command_name in ("smart_wait_click", "smart_wait_text", "smart_wait_select", "smart_wait_cell") and _batch_auto_plan_smart_wait_repair_requested(args):
        summary["has_smart_wait_repair"] = True
        summary["has_selector_repair"] = True
        if not _coerce_bool(args.get("skip_uia"), False):
            summary["has_uia_selector_repair"] = True
    if command_name == "win32_control_wait" and ("relaxed_retry" in lowered or _batch_auto_plan_native_wait_repair_requested(args)):
        summary["has_native_wait_repair"] = True
    if "retry" in lowered:
        summary["has_retry"] = True
    if command_name == "batch_try":
        summary["fallback_count"] = int(summary.get("fallback_count", 0)) + 1
        branches = _batch_try_branches(step, args)
        if isinstance(branches, list):
            summary["nested_branch_count"] = int(summary.get("nested_branch_count", 0)) + len(branches)
            branch_ids = summary.setdefault("nested_branch_ids", [])
            for branch in branches:
                _, branch_id, _ = _batch_branch_steps(branch)
                if branch_id:
                    _batch_auto_plan_unique_append(branch_ids, branch_id)
    if command_name in ("focus_hwnd", "activate") or "focus" in lowered:
        summary["has_focus_repair"] = True
    if command_name in ("wait_window", "wait_event") or command_name.startswith("smart_wait") or command_name.endswith("_wait") or "wait" in lowered:
        summary["has_wait"] = True
    if (
        "post" in lowered
        or "verify" in lowered
        or command_name in ("ocr_wait", "desktop_ocr_wait", "image_wait", "desktop_image_wait", "uia_wait", "desktop_wait")
    ) and command_name not in ("wait_window",):
        summary["has_post_verification"] = True
    if command_name == "win32_control_wait":
        summary["has_post_verification"] = True
        state_name = str((args or {}).get("state") or "").strip().lower().replace("-", "_")
        if state_name in ("absent", "missing", "gone", "not_present", "not_exists", "does_not_exist", "item_absent", "item_missing"):
            summary["has_negative_post_verification"] = True
    if "absent" in lowered or "gone" in lowered or "missing" in lowered:
        summary["has_negative_post_verification"] = True
    if layer == "visual":
        summary["has_visual_fallback"] = True
    if layer == "input":
        summary["has_input_fallback"] = True
    _batch_auto_plan_mark_risks(step, args, summary, command_name, step_id, layer)
    if len(preview) < preview_limit:
        item = {
            "id": step_id,
            "command": command_name or None,
            "path": path or None,
            "layer": layer,
            "selectors": _batch_auto_plan_extract_selectors(args),
            "options": _batch_auto_plan_extract_options(args),
        }
        preview.append({k: v for k, v in item.items() if v not in (None, "", {})})
    branches = _batch_try_branches(step, args) if command_name == "batch_try" else None
    if isinstance(branches, list):
        for branch in branches:
            branch_steps, _, _ = _batch_branch_steps(branch)
            for nested in branch_steps or []:
                _batch_auto_plan_visit_step(nested, summary, preview, depth=depth + 1, preview_limit=preview_limit)
        return
    for key in ("steps", "commands"):
        nested_steps = step.get(key)
        if isinstance(nested_steps, list):
            for nested in nested_steps:
                _batch_auto_plan_visit_step(nested, summary, preview, depth=depth + 1, preview_limit=preview_limit)


def _batch_auto_plan_summary(kind: str, branches: List[Dict[str, Any]]) -> Dict[str, Any]:
    branch_summaries: List[Dict[str, Any]] = []
    all_layers: List[str] = []
    all_commands: List[str] = []
    all_risk_flags: List[str] = []
    all_recommendations: List[str] = []
    flags = {
        "has_recovery": False,
        "has_retry": False,
        "has_focus_repair": False,
        "has_wait": False,
        "has_post_verification": False,
        "has_negative_post_verification": False,
        "has_visual_fallback": False,
        "has_input_fallback": False,
        "has_selector_repair": False,
        "has_uia_selector_repair": False,
        "has_native_selector_repair": False,
        "has_native_wait_repair": False,
        "has_window_selector_repair": False,
        "has_smart_wait_repair": False,
        "has_dialog_action_repair": False,
        "has_dialog_stable_wait": False,
        "has_boundary_preflight": False,
        "has_conditional_helper": False,
    }
    for index, branch in enumerate(branches):
        branch_steps, branch_id, branch_description = _batch_branch_steps(branch)
        summary: Dict[str, Any] = {
            "index": index,
            "id": branch_id,
            "description": branch_description,
            "step_count": 0,
            "fallback_count": 0,
            "nested_branch_count": 0,
            "max_depth": 0,
            "layers": [],
            "commands": [],
            "step_ids": [],
        }
        preview: List[Dict[str, Any]] = []
        for step in branch_steps or []:
            _batch_auto_plan_visit_step(step, summary, preview)
        for layer in summary.get("layers") or []:
            _batch_auto_plan_unique_append(all_layers, layer)
        for command in summary.get("commands") or []:
            _batch_auto_plan_unique_append(all_commands, command)
        for risk_flag in summary.get("risk_flags") or []:
            _batch_auto_plan_unique_append(all_risk_flags, risk_flag)
        for recommendation in summary.get("recommendations") or []:
            _batch_auto_plan_unique_append(all_recommendations, recommendation)
        for key in flags:
            flags[key] = bool(flags[key] or summary.get(key))
        compact = {
            "index": summary.get("index"),
            "id": summary.get("id"),
            "description": summary.get("description"),
            "step_count": summary.get("step_count"),
            "fallback_count": summary.get("fallback_count"),
            "nested_branch_count": summary.get("nested_branch_count"),
            "max_depth": summary.get("max_depth"),
            "layers": summary.get("layers"),
            "commands": summary.get("commands"),
            "step_ids": (summary.get("step_ids") or [])[:32],
            "preview": preview,
            "risk_flags": summary.get("risk_flags"),
            "risk_count": len(summary.get("risk_flags") or []),
            "risk_details": summary.get("risk_details"),
            "recommendations": summary.get("recommendations"),
        }
        for key in flags:
            if summary.get(key):
                compact[key] = True
        branch_summaries.append({k: v for k, v in compact.items() if v not in (None, "", [], {})})
    if branches and not flags.get("has_post_verification"):
        _batch_auto_plan_unique_append(
            all_recommendations,
            "Add post verification such as verify-name/verify-text or verify-absent-name/verify-absent-text for actions where final UI state matters.",
        )
    return {
        "kind": kind,
        "branch_count": len(branches),
        "branch_ids": [item.get("id") for item in branch_summaries if item.get("id")],
        "layers": all_layers,
        "commands": all_commands,
        **flags,
        "risk_flags": all_risk_flags,
        "risk_count": len(all_risk_flags),
        "recommendations": all_recommendations,
        "branches": branch_summaries,
    }


def _batch_execute_auto_command(item: Dict[str, Any], args: Dict[str, Any], results: List[Dict[str, Any]], deadline: Optional[float] = None, trace: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if not isinstance(args, dict) or "__batch_arg_error__" in args:
        return {"ok": False, "error": "invalid_batch_auto", "message": "batch_auto requires object args"}
    normalized_args = _batch_auto_normalize_args(args)
    branches = _batch_auto_branches(item, normalized_args)
    if not branches:
        return {
            "ok": False,
            "error": "invalid_batch_auto",
            "message": "batch_auto could not build any fallback branches for the requested kind/layers",
            "kind": _batch_auto_kind(item, normalized_args),
        }
    if _coerce_bool(normalized_args.get("plan_only"), False):
        kind = _batch_auto_kind(item, normalized_args)
        return {
            "ok": True,
            "planned": True,
            "kind": kind,
            "branch_count": len(branches),
            "plan_summary": _batch_auto_plan_summary(kind, branches),
            "branches": branches,
        }
    auto_item = dict(item)
    auto_item["command"] = "batch_try"
    auto_item["branches"] = branches
    _batch_trace_event(trace, "auto_start", id=_batch_step_id(item), kind=_batch_auto_kind(item, normalized_args), branches=len(branches))
    result = _batch_execute_try_command(auto_item, normalized_args, results, deadline=deadline, trace=trace)
    if isinstance(result, dict):
        result.setdefault("kind", _batch_auto_kind(item, normalized_args))
        result.setdefault("branch_count", len(branches))
        compact_branches: List[Dict[str, Any]] = []
        candidate_by_id = {
            report.get("id"): report
            for report in (result.get("candidates") or [])
            if isinstance(report, dict) and report.get("id") is not None
        }
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            branch_id = branch.get("id")
            compact = {
                "id": branch_id,
                "command": branch.get("command"),
                "description": branch.get("description"),
            }
            candidate = candidate_by_id.get(branch_id)
            if isinstance(candidate, dict):
                compact["ok"] = candidate.get("ok")
                compact["selected"] = bool(candidate.get("selected"))
                branch_diagnostics = _batch_branch_diagnostic_summary(candidate)
                if branch_diagnostics:
                    compact["diagnostic_summary"] = branch_diagnostics
                    if branch_diagnostics.get("relocated"):
                        compact["relocated"] = True
                    if branch_diagnostics.get("uia_relocation_count"):
                        compact["uia_relocation_count"] = branch_diagnostics.get("uia_relocation_count")
            compact_branches.append({k: v for k, v in compact.items() if v not in (None, "", [], {})})
        result.setdefault("branches", compact_branches)
    _batch_trace_event(trace, "auto_end", id=_batch_step_id(item), ok=result.get("ok") if isinstance(result, dict) else None, selected_id=result.get("selected_id") if isinstance(result, dict) else None)
    return result


def _batch_execute_try_command(item: Dict[str, Any], args: Dict[str, Any], results: List[Dict[str, Any]], deadline: Optional[float] = None, trace: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    branches = _batch_try_branches(item, args)
    if not isinstance(branches, list) or not branches:
        return {"ok": False, "error": "invalid_batch_try", "message": "batch_try requires a non-empty branches/alternatives/steps list"}

    deadline = _batch_deadline_from_sources(item, args, deadline)
    reports: List[Dict[str, Any]] = []
    _batch_trace_event(trace, "try_start", id=_batch_step_id(item), branches=len(branches))
    for branch_index, branch in enumerate(branches):
        if _batch_deadline_exceeded(deadline):
            reports.append({
                "index": branch_index,
                "ok": False,
                "error": "batch_timeout",
                "selected": False,
                "summary": _batch_summary([], total_count=1, stopped_on_error=True),
            })
            return {"ok": False, "error": "batch_timeout", "timeout_budget_exceeded": True, "candidates": reports}
        branch_steps, branch_id, branch_description = _batch_branch_steps(branch)
        if not branch_steps:
            report = {
                "index": branch_index,
                "id": branch_id,
                "ok": False,
                "error": "invalid_batch_try_branch",
                "message": "branch must be a step object, a step list, or an object with steps/commands",
                "branch_type": type(branch).__name__,
            }
            reports.append({k: v for k, v in report.items() if v is not None})
            continue

        branch_context = list(results)
        branch_results: List[Dict[str, Any]] = []
        stopped_on_error = False
        _batch_trace_event(trace, "try_branch_start", index=branch_index, id=branch_id, count=len(branch_steps))
        for branch_step in branch_steps:
            if _batch_deadline_exceeded(deadline):
                step_item = _batch_timeout_item(len(branch_context), branch_step, "batch_try branch", deadline)
            else:
                step_item = _batch_execute_step_item(len(branch_context), branch_step, branch_context, deadline=deadline, trace=trace)
            branch_results.append(step_item)
            branch_context.append(step_item)
            if _batch_result_failure(step_item.get("result")):
                stopped_on_error = True
                break

        summary = _batch_summary(branch_results, total_count=len(branch_steps), stopped_on_error=stopped_on_error)
        selected = _batch_try_success_item(branch_results)
        report = {
            "index": branch_index,
            "id": branch_id,
            "description": branch_description,
            "ok": summary.get("ok"),
            "selected": bool(_batch_try_branch_succeeded(branch_results, summary)),
            "summary": summary,
            "results": branch_results,
        }
        reports.append({k: v for k, v in report.items() if v is not None})
        _batch_trace_event(trace, "try_branch_end", index=branch_index, id=branch_id, selected=report.get("selected"), failed_count=summary.get("failed_count"))
        if _batch_try_branch_succeeded(branch_results, summary):
            _batch_trace_event(trace, "try_selected", index=branch_index, id=branch_id)
            try_result = {
                "ok": True,
                "selected": branch_index,
                "selected_id": branch_id,
                "selected_result": selected,
                "result": selected.get("result") if isinstance(selected, dict) else None,
                "candidates": reports,
            }
            diagnostics = _batch_reports_diagnostic_summary(reports)
            if diagnostics:
                try_result["diagnostic_summary"] = diagnostics
            return try_result

    _batch_trace_event(trace, "try_failed", branches=len(reports))
    failure_summary = _batch_try_failure_summary(reports)
    diagnostics = _batch_reports_diagnostic_summary(reports)
    return {
        "ok": False,
        "error": "batch_try_failed",
        "candidates": reports,
        **({"diagnostic_summary": diagnostics} if diagnostics else {}),
        **({"failure_summary": failure_summary} if failure_summary else {}),
    }


def _batch_loop_steps(item: Dict[str, Any], args: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    if isinstance(args, dict) and "__batch_arg_error__" in args:
        return None
    for key in ("steps", "commands"):
        if key in item and isinstance(item.get(key), list):
            return item.get(key)
    if isinstance(args, dict):
        for key in ("steps", "commands"):
            if key in args and isinstance(args.get(key), list):
                return args.get(key)
    return None


def _batch_loop_until(item: Dict[str, Any], args: Dict[str, Any]) -> Any:
    for key in ("until", "expect", "stop_when", "stop-when"):
        if key in item:
            return item.get(key)
    if isinstance(args, dict):
        for key in ("until", "expect", "stop_when", "stop-when"):
            if key in args:
                return args.get(key)
    return None


def _batch_loop_options(item: Dict[str, Any], args: Dict[str, Any]) -> Tuple[int, float]:
    source = args if isinstance(args, dict) else {}
    max_iterations = item.get("max_iterations", item.get("max-iterations", item.get("iterations", item.get("count"))))
    if max_iterations is None:
        max_iterations = source.get("max_iterations", source.get("max-iterations", source.get("iterations", source.get("count", 1))))
    interval = item.get("interval", item.get("delay"))
    if interval is None:
        interval = source.get("interval", source.get("delay", 0.0))
    try:
        max_iterations_int = max(int(max_iterations or 1), 1)
    except Exception:
        max_iterations_int = 1
    try:
        interval_float = max(float(interval or 0.0), 0.0)
    except Exception:
        interval_float = 0.0
    return max_iterations_int, interval_float


def _batch_loop_result_context(iteration_index: int, iteration_results: List[Dict[str, Any]], summary: Dict[str, Any], selected_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    last_item = selected_result if isinstance(selected_result, dict) else (iteration_results[-1] if iteration_results else None)
    last_result = last_item.get("result") if isinstance(last_item, dict) else None
    return {
        "ok": True,
        "iteration": iteration_index + 1,
        "results": iteration_results,
        "steps": iteration_results,
        "summary": summary,
        "last": last_item,
        "last_result": last_result,
        "selected_result": selected_result,
    }


def _batch_execute_loop_command(item: Dict[str, Any], args: Dict[str, Any], results: List[Dict[str, Any]], deadline: Optional[float] = None, trace: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    steps = _batch_loop_steps(item, args)
    if not steps:
        return {"ok": False, "error": "invalid_batch_loop", "message": "batch_repeat requires a non-empty steps/commands list"}
    until = _batch_loop_until(item, args)
    deadline = _batch_deadline_from_sources(item, args, deadline)
    max_iterations, interval = _batch_loop_options(item, args)
    iterations: List[Dict[str, Any]] = []
    selected_result = None

    loop_context = list(results)
    _batch_trace_event(trace, "loop_start", id=_batch_step_id(item), max_iterations=max_iterations, count=len(steps))
    for iteration_index in range(max_iterations):
        if _batch_deadline_exceeded(deadline):
            return {
                "ok": False,
                "error": "batch_timeout",
                "timeout_budget_exceeded": True,
                "iterations": len(iterations),
                "selected_result": selected_result,
                "history": iterations,
            }
        if iteration_index > 0 and interval > 0:
            if not _batch_sleep_with_deadline(interval, deadline):
                return {
                    "ok": False,
                    "error": "batch_timeout",
                    "timeout_budget_exceeded": True,
                    "iterations": len(iterations),
                    "selected_result": selected_result,
                    "history": iterations,
                }
        iteration_results: List[Dict[str, Any]] = []
        stopped_on_error = False
        _batch_trace_event(trace, "loop_iteration_start", iteration=iteration_index + 1)
        for step in steps:
            if _batch_deadline_exceeded(deadline):
                step_item = _batch_timeout_item(len(loop_context), step, "batch_repeat iteration", deadline)
            else:
                step_item = _batch_execute_step_item(len(loop_context), step, loop_context, deadline=deadline, trace=trace)
            iteration_results.append(step_item)
            loop_context.append(step_item)
            if _batch_result_failure(step_item.get("result")):
                stopped_on_error = True
                break
        summary = _batch_summary(iteration_results, total_count=len(steps), stopped_on_error=stopped_on_error)
        selected_result = _batch_try_success_item(iteration_results)
        loop_result_context = _batch_loop_result_context(iteration_index, iteration_results, summary, selected_result)
        until_eval = _batch_evaluate_expectations(until, loop_result_context, loop_context) if until is not None else {"ok": bool(summary.get("ok")), "checks": []}
        report = {
            "iteration": iteration_index + 1,
            "ok": summary.get("ok"),
            "summary": summary,
            "until": until_eval,
            "results": iteration_results,
            "steps": iteration_results,
            "last": loop_result_context.get("last"),
            "last_result": loop_result_context.get("last_result"),
            "selected_result": selected_result,
        }
        iterations.append(report)
        _batch_trace_event(trace, "loop_iteration_end", iteration=iteration_index + 1, ok=summary.get("ok"), until=until_eval.get("ok"))
        if summary.get("ok") and until_eval.get("ok"):
            _batch_trace_event(trace, "loop_satisfied", iteration=iteration_index + 1)
            return {
                "ok": True,
                "iterations": iteration_index + 1,
                "selected_result": selected_result,
                "result": selected_result.get("result") if isinstance(selected_result, dict) else None,
                "history": iterations,
            }
        if stopped_on_error:
            break

    _batch_trace_event(trace, "loop_failed", iterations=len(iterations))
    return {
        "ok": False,
        "error": "batch_until_not_satisfied",
        "iterations": len(iterations),
        "selected_result": selected_result,
        "history": iterations,
    }



