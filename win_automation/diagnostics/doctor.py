"""
Diagnostics and environment validation doctor probe.
Probes display, DPI, Win32, UIA, MSAA, helper daemon, OCR, and GDI resources.
"""

from __future__ import annotations

import os
import sys
import json
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.state.persistence import STATE_FILE
from win_automation.helper.client import _helper_available, _helper_current, _helper_health
from win_automation.win32.window import enum_windows, get_window
from win_automation.vision.capture import capture_window_screenshot
from win_automation.vision.pixel import pixel
from win_automation.uia.tree import build_accessibility_tree
from win_automation.diagnostics.selftest import (
    selftest_uia_patterns,
    selftest_text_pattern,
    selftest_winevent,
    selftest_uia_view_modes,
    selftest_window_management,
    selftest_ocr,
)

def run_doctor(hwnd: Optional[int] = None, detailed: bool = False) -> Dict[str, Any]:
    return doctor(hwnd=hwnd, detailed=detailed)


def doctor(hwnd: Optional[int] = None, detailed: bool = False) -> Dict[str, Any]:
    """Run a lightweight self-check across window, screenshot, UIA, vision, and input layers."""
    report: Dict[str, Any] = {
        "status": "ok",
        "detailed": detailed,
        "python": sys.version.split()[0],
        "state_file": STATE_FILE,
        "helper_available": _helper_available(),
        "helper_current": _helper_current(),
        "helper_health": _helper_health(),
        "checks": {},
    }
    windows = enum_windows()
    report["checks"]["list_windows"] = {"ok": bool(windows), "count": len(windows)}
    if hwnd is None and windows:
        hwnd = windows[0]["hwnd"]
    if hwnd is not None:
        report["target_hwnd"] = hwnd
        report["checks"]["get_window"] = json.loads(get_window(hwnd))
        try:
            img, meta = capture_image(hwnd, max_width=640)
            report["checks"]["screenshot"] = {
                "ok": True,
                "width": img.width,
                "height": img.height,
                "id": meta.get("id"),
                "path": meta.get("path"),
                "capture_method": meta.get("capture_method"),
            }
            px = pixel(hwnd, min(5, max(img.width - 1, 0)), min(5, max(img.height - 1, 0)), meta.get("id"))
            report["checks"]["pixel"] = {"ok": "error" not in px, "value": px.get("hex"), "error": px.get("error")}
        except Exception as e:
            report["checks"]["screenshot"] = {"ok": False, "error": str(e)}
        try:
            acc = build_accessibility_tree(hwnd, max_depth=3, max_elements=80)
            report["checks"]["uia"] = {
                "ok": "error" not in acc,
                "element_count": len(acc.get("elements", [])),
                "error": acc.get("error"),
            }
        except Exception as e:
            report["checks"]["uia"] = {"ok": False, "error": str(e)}
        try:
            uia_probe = selftest_uia_patterns(timeout=3.0)
            report["checks"]["uia_patterns_probe"] = {
                "ok": bool(uia_probe.get("ok")),
                "error": uia_probe.get("error"),
                "hwnd": uia_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["uia_patterns_probe"] = {"ok": False, "error": str(e)}
        try:
            text_probe = selftest_text_pattern(timeout=6.0)
            report["checks"]["uia_text_pattern_probe"] = {
                "ok": bool(text_probe.get("ok")),
                "error": text_probe.get("error"),
                "hwnd": text_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["uia_text_pattern_probe"] = {"ok": False, "error": str(e)}
        try:
            winevent_probe = selftest_winevent(timeout=4.0)
            report["checks"]["winevent_probe"] = {
                "ok": bool(winevent_probe.get("ok")),
                "error": winevent_probe.get("error"),
                "hwnd": winevent_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["winevent_probe"] = {"ok": False, "error": str(e)}
        try:
            view_probe = selftest_uia_view_modes(timeout=3.0)
            report["checks"]["uia_view_modes_probe"] = {
                "ok": bool(view_probe.get("ok")),
                "error": view_probe.get("error"),
                "hwnd": view_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["uia_view_modes_probe"] = {"ok": False, "error": str(e)}
        try:
            window_probe = selftest_window_management(timeout=3.0)
            report["checks"]["window_actions_probe"] = {
                "ok": bool(window_probe.get("ok")),
                "error": window_probe.get("error"),
                "hwnd": window_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["window_actions_probe"] = {"ok": False, "error": str(e)}
        try:
            focus_probe = selftest_focus_hwnd(timeout=3.0)
            report["checks"]["focus_hwnd_probe"] = {
                "ok": bool(focus_probe.get("ok")),
                "error": focus_probe.get("error"),
                "hwnd": focus_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["focus_hwnd_probe"] = {"ok": False, "error": str(e)}
        try:
            focused_input_probe = selftest_focused_input(timeout=3.0)
            report["checks"]["focused_input_probe"] = {
                "ok": bool(focused_input_probe.get("ok")),
                "error": focused_input_probe.get("error"),
                "hwnd": focused_input_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["focused_input_probe"] = {"ok": False, "error": str(e)}
        try:
            gui_probe = gui_thread_info(hwnd)
            report["checks"]["gui_thread_info"] = {
                "ok": bool(gui_probe.get("ok")),
                "thread_id": gui_probe.get("thread_id"),
                "focus_hwnd": (gui_probe.get("handles") or {}).get("focus"),
                "error": gui_probe.get("error"),
            }
        except Exception as e:
            report["checks"]["gui_thread_info"] = {"ok": False, "error": str(e)}
        try:
            children = child_windows(hwnd, max_count=80)
            report["checks"]["win32_children"] = {
                "ok": "error" not in children,
                "count": children.get("count", 0),
                "error": children.get("error"),
            }
        except Exception as e:
            report["checks"]["win32_children"] = {"ok": False, "error": str(e)}
        try:
            native = selftest_win32(timeout=3.0)
            report["checks"]["win32_native_probe"] = {
                "ok": bool(native.get("ok")),
                "error": native.get("error"),
                "hwnd": native.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_native_probe"] = {"ok": False, "error": str(e)}
        try:
            msaa = msaa_window(hwnd, max_children=40)
            report["checks"]["msaa"] = {
                "ok": "error" not in msaa,
                "child_count": msaa.get("child_count", 0),
                "role": (msaa.get("root") or {}).get("role_text"),
                "error": msaa.get("error"),
            }
        except Exception as e:
            report["checks"]["msaa"] = {"ok": False, "error": str(e)}
        try:
            msaa_probe = selftest_msaa(timeout=3.0)
            report["checks"]["msaa_native_probe"] = {
                "ok": bool(msaa_probe.get("ok")),
                "error": msaa_probe.get("error"),
                "hwnd": msaa_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["msaa_native_probe"] = {"ok": False, "error": str(e)}
        try:
            menus = menu_tree(hwnd, max_depth=4, max_items=120)
            report["checks"]["hmenu"] = {
                "ok": "error" not in menus,
                "present": (menus.get("menu") or {}).get("present"),
                "count": len((menus.get("menu") or {}).get("items") or []),
                "error": menus.get("error"),
            }
        except Exception as e:
            report["checks"]["hmenu"] = {"ok": False, "error": str(e)}
        try:
            menu_probe = selftest_menu(timeout=3.0)
            report["checks"]["hmenu_native_probe"] = {
                "ok": bool(menu_probe.get("ok")),
                "error": menu_probe.get("error"),
                "hwnd": menu_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["hmenu_native_probe"] = {"ok": False, "error": str(e)}
        try:
            controls_probe = selftest_controls(timeout=3.0)
            report["checks"]["win32_controls_probe"] = {
                "ok": bool(controls_probe.get("ok")),
                "error": controls_probe.get("error"),
                "hwnd": controls_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_controls_probe"] = {"ok": False, "error": str(e)}
        try:
            common_probe = selftest_common_controls(timeout=3.0)
            report["checks"]["win32_common_controls_probe"] = {
                "ok": bool(common_probe.get("ok")),
                "error": common_probe.get("error"),
                "hwnd": common_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_common_controls_probe"] = {"ok": False, "error": str(e)}
        try:
            header_probe = selftest_header_controls(timeout=3.0)
            report["checks"]["win32_header_controls_probe"] = {
                "ok": bool(header_probe.get("ok")),
                "error": header_probe.get("error"),
                "hwnd": header_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_header_controls_probe"] = {"ok": False, "error": str(e)}
        try:
            bars_probe = selftest_bars(timeout=3.0)
            report["checks"]["win32_bars_probe"] = {
                "ok": bool(bars_probe.get("ok")),
                "error": bars_probe.get("error"),
                "hwnd": bars_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_bars_probe"] = {"ok": False, "error": str(e)}
        try:
            numeric_probe = selftest_numeric_controls(timeout=3.0)
            report["checks"]["win32_numeric_controls_probe"] = {
                "ok": bool(numeric_probe.get("ok")),
                "error": numeric_probe.get("error"),
                "hwnd": numeric_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_numeric_controls_probe"] = {"ok": False, "error": str(e)}
        try:
            date_ip_probe = selftest_date_ip_controls(timeout=3.0)
            report["checks"]["win32_date_ip_controls_probe"] = {
                "ok": bool(date_ip_probe.get("ok")),
                "error": date_ip_probe.get("error"),
                "hwnd": date_ip_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_date_ip_controls_probe"] = {"ok": False, "error": str(e)}
        try:
            richedit_probe = selftest_richedit_controls(timeout=3.0)
            report["checks"]["win32_richedit_controls_probe"] = {
                "ok": bool(richedit_probe.get("ok")),
                "error": richedit_probe.get("error"),
                "hwnd": richedit_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_richedit_controls_probe"] = {"ok": False, "error": str(e)}
        try:
            light_probe = selftest_light_controls(timeout=3.0)
            report["checks"]["win32_light_controls_probe"] = {
                "ok": bool(light_probe.get("ok")),
                "error": light_probe.get("error"),
                "hwnd": light_probe.get("hwnd"),
            }
        except Exception as e:
            report["checks"]["win32_light_controls_probe"] = {"ok": False, "error": str(e)}
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        report["checks"]["opencv"] = {"ok": True}
    except Exception as e:
        report["checks"]["opencv"] = {"ok": False, "error": str(e)}
    try:
        import dxcam  # noqa: F401
        report["checks"]["dxcam"] = {"ok": True}
    except Exception as e:
        report["checks"]["dxcam"] = {"ok": False, "error": str(e)}
    try:
        import pytesseract
        try:
            version = str(pytesseract.get_tesseract_version())
            report["checks"]["tesseract"] = {"ok": True, "version": version}
        except Exception as e:
            report["checks"]["tesseract"] = {"ok": False, "error": str(e)}
    except Exception as e:
            report["checks"]["tesseract"] = {"ok": False, "error": str(e)}
    try:
        ocr_probe = selftest_ocr(timeout=4.0)
        report["checks"]["windows_ocr"] = {
            "ok": bool(ocr_probe.get("ok")),
            "error": ocr_probe.get("error"),
            "text": ((ocr_probe.get("steps") or {}).get("windows_ocr") or {}).get("text"),
        }
        report["checks"]["ocr"] = {
            "ok": bool(ocr_probe.get("ok") or (report["checks"].get("tesseract") or {}).get("ok")),
            "windows_ocr": bool(ocr_probe.get("ok")),
            "tesseract": bool((report["checks"].get("tesseract") or {}).get("ok")),
        }
    except Exception as e:
        report["checks"]["windows_ocr"] = {"ok": False, "error": str(e)}
        report["checks"]["ocr"] = {"ok": bool((report["checks"].get("tesseract") or {}).get("ok")), "error": str(e)}
    return report


