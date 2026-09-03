"""
Clipboard snapshot, multi-format backup, safe restore, and Unicode clipboard access.
"""

from __future__ import annotations

import os
import sys
import time
import ctypes
import ctypes.wintypes
from typing import Any, Dict, List, Optional, Tuple, Union

from win_automation.core.win32_structures import *
from win_automation.core.utils import is_valid_hwnd

CLIPBOARD_RETRY_TIMEOUT = 2.0
CLIPBOARD_RETRY_INTERVAL = 0.05

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


def _clipboard_dispose_snapshot_handles(
    snapshot: Optional[Dict[str, Any]],
    exclude_indexes: Optional[set[int]] = None,
) -> List[Dict[str, Any]]:
    disposed: List[Dict[str, Any]] = []
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


def _clipboard_copy_handle_format(fmt: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
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


def _clipboard_read_memory_format(fmt: int) -> Tuple[Optional[bytes], Optional[str]]:
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


def _clipboard_snapshot() -> Dict[str, Any]:
    """Snapshot memory-backed clipboard formats so paste fallback can restore them."""
    snapshot: Dict[str, Any] = {"ok": False, "formats": [], "skipped_formats": []}
    if not _open_clipboard_retry():
        snapshot["error"] = "open_clipboard_failed"
        return snapshot
    try:
        snapshot["ok"] = True
        seen: set[int] = set()
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


def _clipboard_restore_snapshot(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(snapshot, dict) or not snapshot.get("ok"):
        return {"ok": False, "restored": False, "error": "no_valid_clipboard_snapshot"}
    if not _open_clipboard_retry():
        disposed = _clipboard_dispose_snapshot_handles(snapshot)
        result = {"ok": False, "restored": False, "error": "open_clipboard_failed"}
        if disposed:
            result["disposed_handles"] = disposed
        return result
    restored = 0
    failures: List[Dict[str, Any]] = []
    transferred_handle_indexes: set[int] = set()
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


def _clipboard_save() -> Optional[bytes]:
    """Read current clipboard CF_UNICODETEXT; return raw bytes or None."""
    if not _open_clipboard_retry():
        return None
    try:
        h_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_data:
            return None
        p_data = kernel32.GlobalLock(h_data)
        if not p_data:
            return None
        # Read the wide string until the null terminator
        raw = ctypes.string_at(p_data, 0)
        # string_at with size=0 reads until null — decode to get bytes
        text = ctypes.wstring_at(p_data)
        kernel32.GlobalUnlock(h_data)
        return text.encode("utf-16-le") + b"\x00\x00"
    except Exception:
        return None
    finally:
        user32.CloseClipboard()


def _clipboard_restore(saved: Optional[bytes]) -> None:
    """Restore a previously saved CF_UNICODETEXT to the clipboard."""
    if saved is None:
        return
    if not _open_clipboard_retry():
        return
    try:
        user32.EmptyClipboard()
        _clipboard_set_memory_format(CF_UNICODETEXT, saved)
    except Exception:
        pass
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# Screenshot (items 1, 3, 5, 10 — scaling, IDs, BitBlt fallback, metadata)
# ---------------------------------------------------------------------------

def _set_clipboard_text(text: str) -> None:
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
            user32.CloseClipboard()

