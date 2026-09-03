"""
Keyboard simulation, hotkey processing, and text typing via SendInput, clipboard, and WM_CHAR.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.types import ActionTimeoutError
from win_automation.core.win32_structures import *
from win_automation.core.utils import is_valid_hwnd, make_lparam, shorten
from win_automation.win32.window import _window_info, activate_window, focus_hwnd, _send_message_timeout
from win_automation.helper.client import _helper_route_for_hwnd, _helper_post, _elevated_helper_required_result, _elevated_helper_required_message, _helper_ok
from win_automation.input.clipboard import _clipboard_snapshot, _clipboard_restore_snapshot, _set_clipboard_text, _open_clipboard_retry, _clipboard_save, _clipboard_restore
from win_automation.state.persistence import resolve_target_hwnd

def _resolve_target(hwnd: Optional[int]) -> Optional[int]:
    return resolve_target_hwnd(hwnd)

# ---------------------------------------------------------------------------

_KEYS: Dict[str, int] = {
    # Letters (a-z)
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12,
    "f": 0x21, "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24,
    "k": 0x25, "l": 0x26, "m": 0x32, "n": 0x31, "o": 0x18,
    "p": 0x19, "q": 0x10, "r": 0x13, "s": 0x1F, "t": 0x14,
    "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D, "y": 0x15, "z": 0x2C,
    # Digits (top row)
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    # Numpad (KP_0 .. KP_9)
    "KP_0": 0x52, "KP_1": 0x4F, "KP_2": 0x50, "KP_3": 0x51,
    "KP_4": 0x4B, "KP_5": 0x4C, "KP_6": 0x4D, "KP_7": 0x47,
    "KP_8": 0x48, "KP_9": 0x49,
    "KP_Multiply": 0x37, "KP_Add": 0x4E, "KP_Separator": 0x53,
    "KP_Subtract": 0x4A, "KP_Decimal": 0x53, "KP_Divide": 0xE035,
    "KP_Enter": 0xE01C,
    # F-keys (F1-F24)
    "F1": 0x3B, "F2": 0x3C, "F3": 0x3D, "F4": 0x3E,
    "F5": 0x3F, "F6": 0x40, "F7": 0x41, "F8": 0x42,
    "F9": 0x43, "F10": 0x44, "F11": 0x57, "F12": 0x58,
    "F13": 0x64, "F14": 0x65, "F15": 0x66, "F16": 0x67,
    "F17": 0x68, "F18": 0x69, "F19": 0x6A, "F20": 0x6B,
    "F21": 0x6C, "F22": 0x6D, "F23": 0x6E, "F24": 0x76,
    # Navigation / editing
    "Insert": 0xE052, "Delete": 0xE053, "Home": 0xE047, "End": 0xE04F,
    "Page_Up": 0xE049, "Page_Down": 0xE051,
    "Up": 0xE048, "Down": 0xE050, "Left": 0xE04B, "Right": 0xE04D,
    # Control keys
    "Return": 0x1C, "Escape": 0x01, "BackSpace": 0x0E, "Tab": 0x0F,
    "space": 0x39,
    # Modifier keys (scan codes)
    "Control_L": 0x1D, "Control_R": 0xE01D,
    "Shift_L": 0x2A, "Shift_R": 0x36,
    "Alt_L": 0x38, "Alt_R": 0xE038,
    "Win_L": 0xE05B, "Win_R": 0xE05C,
    "Menu": 0xE05D,
    # Lock keys
    "CapsLock": 0x3A, "NumLock": 0x45, "ScrollLock": 0x46,
    "PrintScreen": 0xE037, "Pause": 0xE11D45,
    # Misc
    "space": 0x39,
    "minus": 0x0C, "equal": 0x0D, "comma": 0x33, "period": 0x34,
    "bracketleft": 0x1A, "bracketright": 0x1B, "backslash": 0x2B,
    "semicolon": 0x27, "apostrophe": 0x28, "grave": 0x29,
    "slash": 0x35,
}


def _keysym_to_scancode(keysym: str) -> int:
    """Map a keysym name (or single character) to a Windows scancode."""
    keysym = _normalize_key_name(keysym)
    if keysym in _KEYS:
        return _KEYS[keysym]
    # Single uppercase letter -> lowercase scancode
    if len(keysym) == 1 and keysym.isalpha():
        return _KEYS[keysym.lower()]
    raise ValueError(f"Unknown key: {keysym}")


_KEY_ALIASES: Dict[str, str] = {
    "ctrl": "Control_L",
    "control": "Control_L",
    "ctl": "Control_L",
    "lctrl": "Control_L",
    "leftctrl": "Control_L",
    "leftcontrol": "Control_L",
    "rctrl": "Control_R",
    "rightctrl": "Control_R",
    "rightcontrol": "Control_R",
    "shift": "Shift_L",
    "lshift": "Shift_L",
    "leftshift": "Shift_L",
    "rshift": "Shift_R",
    "rightshift": "Shift_R",
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
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "BackSpace",
    "bksp": "BackSpace",
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
    "capslock": "CapsLock",
    "caps-lock": "CapsLock",
    "numlock": "NumLock",
    "num-lock": "NumLock",
    "scrolllock": "ScrollLock",
    "scroll-lock": "ScrollLock",
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


def _normalize_key_name(key: str) -> str:
    raw = str(key or "").strip()
    if raw in _KEYS:
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
        if normalized != chunk or normalized in _KEYS:
            parts.append(chunk)
        else:
            parts.extend(part for part in re.split(r"\s+", chunk) if part)
    return parts


# ---------------------------------------------------------------------------
# Keyboard input via SendInput (item 4 — replaces PyAutoGUI for key/type)
# ---------------------------------------------------------------------------

def _send_input_checked(inp: INPUT, label: str) -> None:
    sent = int(user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp)))
    if sent != 1:
        err = int(kernel32.GetLastError())
        raise RuntimeError(f"SendInput failed for {label}: sent={sent}, last_error={err}")


def _set_cursor_pos_checked(x: int, y: int) -> None:
    if not user32.SetCursorPos(int(x), int(y)):
        err = int(kernel32.GetLastError())
        raise RuntimeError(f"SetCursorPos failed at ({int(x)}, {int(y)}): last_error={err}")


def _send_mouse_input(flags: int, data: int = 0, label: str = "mouse") -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp._input.mi.dx = 0
    inp._input.mi.dy = 0
    inp._input.mi.mouseData = int(data)
    inp._input.mi.dwFlags = int(flags)
    inp._input.mi.time = 0
    inp._input.mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    _send_input_checked(inp, label)


def _send_key_down(scancode: int) -> None:
    """Send a key-down event using the hardware scancode."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._input.ki.wVk = 0
    inp._input.ki.wScan = scancode & 0xFF
    inp._input.ki.dwFlags = KEYEVENTF_SCANCODE
    if scancode & 0xE000:
        inp._input.ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
    inp._input.ki.time = 0
    inp._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    _send_input_checked(inp, f"key down scancode=0x{scancode:X}")


def _send_key_up(scancode: int) -> None:
    """Send a key-up event using the hardware scancode."""
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._input.ki.wVk = 0
    inp._input.ki.wScan = scancode & 0xFF
    inp._input.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    if scancode & 0xE000:
        inp._input.ki.dwFlags |= KEYEVENTF_EXTENDEDKEY
    inp._input.ki.time = 0
    inp._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    _send_input_checked(inp, f"key up scancode=0x{scancode:X}")


def _send_char(ch: str) -> None:
    """Send a single Unicode character via SendInput."""
    code = ord(ch)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp._input.ki.wVk = 0
    inp._input.ki.wScan = code
    inp._input.ki.dwFlags = KEYEVENTF_UNICODE
    inp._input.ki.time = 0
    inp._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    _send_input_checked(inp, f"unicode down U+{code:04X}")
    time.sleep(0.02)
    inp._input.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    _send_input_checked(inp, f"unicode up U+{code:04X}")


def _send_ctrl_v() -> None:
    """Send Ctrl+V via SendInput."""
    vk_control = 0x1D  # Left Control scancode
    vk_v = _KEYS["v"]
    _press_scancode_sequence([vk_control, vk_v])


def _press_scancode_sequence(scancodes: List[int], delay: float = 0.02) -> None:
    pressed: List[int] = []
    original_error: Optional[BaseException] = None
    try:
        for sc in scancodes:
            _send_key_down(sc)
            pressed.append(sc)
            time.sleep(delay)
    except BaseException as e:
        original_error = e
    finally:
        release_errors: List[str] = []
        for sc in reversed(pressed):
            try:
                _send_key_up(sc)
                time.sleep(delay)
            except BaseException as e:
                release_errors.append(str(e))
        if original_error is not None:
            if release_errors:
                raise RuntimeError(f"{original_error}; release_errors={release_errors}") from original_error
            raise original_error
        if release_errors:
            raise RuntimeError(f"SendInput release failed: {release_errors}")


# ---------------------------------------------------------------------------
# Clipboard save / restore (item 15)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Type text (items 4, 15 — SendInput, clipboard save/restore)
# ---------------------------------------------------------------------------

def _clipboard_restore_error_detail(restore: Optional[Dict[str, Any]]) -> str:
    if not isinstance(restore, dict):
        return "restored_formats=None, error=missing_restore_result"
    return (
        f"restored_formats={restore.get('restored_formats')}, "
        f"error={restore.get('error') or restore.get('failures') or restore.get('skipped_formats')}"
    )


def type_text(hwnd: int | None, text: str) -> str:
    """Paste *text* into the focused control via clipboard + Ctrl+V.
    Uses helper server for cross-process input (works with NW.js/CEF apps)."""
    hwnd = _resolve_target(hwnd)
    # Try helper server first
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/type_text")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        result = _helper_post("/type_text", {"hwnd": hwnd, "text": text, "activate": True}, elevated=helper_elevated)
        if _helper_ok(result):
            if result.get("clipboard_restore_ok") is False:
                return (
                    f"Warning: pasted {len(text)} characters but clipboard restore may be incomplete "
                    f"(saved_formats={result.get('clipboard_saved_formats')}, "
                    f"restored_formats={result.get('clipboard_restored_formats')}, "
                    f"error={result.get('clipboard_restore_error') or result.get('clipboard_restore_failures') or result.get('clipboard_restore_skipped_formats')})"
                )
            return f"Pasted {len(text)} characters"

    # Fallback to direct implementation
    activate_window(hwnd)
    time.sleep(0.1)

    saved_clip = _clipboard_snapshot()
    paste_error: Optional[Exception] = None
    restore: Dict[str, Any] = {}
    try:
        _set_clipboard_text(text)
        time.sleep(0.05)
        _send_ctrl_v()
        time.sleep(0.05)
    except Exception as e:
        paste_error = e
    finally:
        try:
            restore = _clipboard_restore_snapshot(saved_clip)
        except Exception as e:
            restore = {"ok": False, "restored_formats": 0, "error": str(e)}

    if paste_error is not None:
        if restore.get("ok") is False:
            return f"Error: {paste_error}; clipboard restore may be incomplete ({_clipboard_restore_error_detail(restore)})"
        return f"Error: {paste_error}"

    if restore.get("ok") is False:
        return (
            f"Warning: pasted {len(text)} characters but clipboard restore may be incomplete "
            f"({_clipboard_restore_error_detail(restore)})"
        )
    return f"Pasted {len(text)} characters"


def type_text_foreground(text: str) -> str:
    """Paste text into the current foreground focus without requiring a target HWND."""
    saved_clip = _clipboard_snapshot()
    paste_error: Optional[Exception] = None
    restore: Dict[str, Any] = {}
    try:
        _set_clipboard_text(text)
        time.sleep(0.05)
        _send_ctrl_v()
        time.sleep(0.05)
    except Exception as e:
        paste_error = e
    finally:
        try:
            restore = _clipboard_restore_snapshot(saved_clip)
        except Exception as e:
            restore = {"ok": False, "restored_formats": 0, "error": str(e)}
    if paste_error is not None:
        if restore.get("ok") is False:
            return f"Error: {paste_error}; clipboard restore may be incomplete ({_clipboard_restore_error_detail(restore)})"
        return f"Error: {paste_error}"
    if restore.get("ok") is False:
        return (
            f"Warning: pasted {len(text)} characters to foreground focus but clipboard restore may be incomplete "
            f"({_clipboard_restore_error_detail(restore)})"
        )
    return f"Pasted {len(text)} characters to foreground focus"


# ---------------------------------------------------------------------------
# Press key (item 4 — SendInput with scancodes)
# ---------------------------------------------------------------------------

def press_key(hwnd: int | None, keys: str) -> str:
    """
    Press one or more keys specified in + separated notation.
    Uses helper server for cross-process input (works with NW.js/CEF apps).
    """
    hwnd = _resolve_target(hwnd)
    # Try helper server first (works across processes, including CEF apps)
    helper_ready, helper_elevated, boundary_result = _helper_route_for_hwnd(hwnd, "/press_key")
    if boundary_result is not None:
        return _elevated_helper_required_message(boundary_result)
    if helper_ready:
        result = _helper_post("/press_key", {"hwnd": hwnd, "keys": keys, "activate": True}, elevated=helper_elevated)
        if _helper_ok(result):
            return f"Pressed: {keys}"

    # Fallback to direct SendInput
    activate_window(hwnd)
    time.sleep(0.1)

    parts = _split_key_sequence(keys)
    if not parts:
        return "Error: No keys provided"
    scancodes = []
    for part in parts:
        try:
            scancodes.append((part, _keysym_to_scancode(part)))
        except ValueError:
            if len(part) == 1:
                scancodes.append((part, _keysym_to_scancode(part.lower())))
            else:
                return f"Error: Unknown key '{part}'"


    if not isinstance(info, dict):
        return None
    return {
        "hwnd": info.get("hwnd"),
        "title": info.get("title"),
        "class_name": info.get("class_name"),
        "control_id": info.get("control_id"),
        "pid": info.get("pid"),
        "thread_id": info.get("thread_id"),
        "process_name": info.get("process_name"),
        "visible": info.get("visible"),
        "enabled": info.get("enabled"),
        "is_child": info.get("is_child"),
        "parent_hwnd": info.get("parent_hwnd"),
        "root_hwnd": info.get("root_hwnd"),
        "root_owner_hwnd": info.get("root_owner_hwnd"),
        "rect": info.get("rect"),
        "text": info.get("text"),
    }


def _send_text_unicode(text: str) -> Dict[str, Any]:
    sent = 0
    for ch in str(text):
        _send_char(ch)
        sent += 1
    return {"ok": True, "method": "SendInputUnicode", "sent": sent}


def _send_text_wm_char(hwnd: int, text: str, timeout_ms: int = 100) -> Dict[str, Any]:
    sent = 0
    failures: List[Dict[str, Any]] = []
    for ch in str(text):
        code = ord("\r" if ch == "\n" else ch)
        ok, result = _send_message_timeout(hwnd, WM_CHAR, code, 1, timeout_ms=timeout_ms)
        if ok:
            sent += 1
        else:
            failures.append({"index": sent, "char": ch, "code": code, "result": result})
            break
    return {"ok": not failures, "method": "WM_CHAR", "sent": sent, "failures": failures}


from win_automation.input.smart_input import focused_input
