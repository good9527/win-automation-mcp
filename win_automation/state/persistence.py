"""
Concurrency-safe state persistence module.
Guarantees atomic file writes via temporary file replacement and cross-process
synchronization via file locking.
"""

from __future__ import annotations

import os
import sys
import time
import json
import shutil
import tempfile
from typing import Any, Callable, Optional, Union

from .locks import FileLock

# Canonical state file locations
DEFAULT_STATE_FILE = os.path.join(os.path.expanduser("~"), ".win-auto-state.json")
STATE_FILE = DEFAULT_STATE_FILE
DEFAULT_LOCK_FILE = DEFAULT_STATE_FILE + ".lock"


def get_state_lock(filepath: Optional[str] = None, timeout: float = 10.0) -> FileLock:
    """Get a FileLock instance for the given state file path."""
    target_path = os.path.abspath(filepath or DEFAULT_STATE_FILE)
    lock_path = target_path + ".lock"
    return FileLock(lock_path, timeout=timeout)


def load_state(filepath: Optional[str] = None, lock_timeout: float = 5.0) -> dict[str, Any]:
    """
    Load persistent state from disk under lock.
    Returns an empty dict if the file does not exist or cannot be parsed.
    """
    target_path = os.path.abspath(filepath or DEFAULT_STATE_FILE)
    if not os.path.exists(target_path):
        return {}

    with get_state_lock(target_path, timeout=lock_timeout):
        try:
            if not os.path.exists(target_path):
                return {}
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def save_state(state: dict[str, Any], filepath: Optional[str] = None, lock_timeout: float = 5.0) -> str:
    """
    Save state dictionary to disk atomically under lock.
    Uses tempfile.NamedTemporaryFile in the same directory, flushes, fsyncs,
    and replaces the target file via os.replace.
    """
    if not isinstance(state, dict):
        raise TypeError(f"State must be a dict, got {type(state).__name__}")

    target_path = os.path.abspath(filepath or DEFAULT_STATE_FILE)
    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    with get_state_lock(target_path, timeout=lock_timeout):
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=target_dir,
                delete=False,
                encoding="utf-8",
                prefix=".win_auto_state_",
                suffix=".tmp",
            ) as tf:
                temp_path = tf.name
                json.dump(state, tf, ensure_ascii=False, indent=2)
                tf.flush()
                os.fsync(tf.fileno())

            # Atomically replace target file
            os.replace(temp_path, target_path)
            temp_path = None
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        return target_path


def update_state(
    mutator: Union[Callable[[dict[str, Any]], Optional[dict[str, Any]]], dict[str, Any]],
    filepath: Optional[str] = None,
    lock_timeout: float = 10.0,
) -> dict[str, Any]:
    """
    Atomically read, modify, and save state within a single lock acquisition.
    `mutator` can be a callback function modifying the state dict, or a dict to update.
    Returns the updated state.
    """
    target_path = os.path.abspath(filepath or DEFAULT_STATE_FILE)
    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    with get_state_lock(target_path, timeout=lock_timeout):
        # 1. Read existing state
        state: dict[str, Any] = {}
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        state = loaded
            except Exception:
                state = {}

        # 2. Mutate
        if callable(mutator):
            result = mutator(state)
            if isinstance(result, dict):
                state = result
        elif isinstance(mutator, dict):
            state.update(mutator)

        # 3. Atomic write
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=target_dir,
                delete=False,
                encoding="utf-8",
                prefix=".win_auto_state_",
                suffix=".tmp",
            ) as tf:
                temp_path = tf.name
                json.dump(state, tf, ensure_ascii=False, indent=2)
                tf.flush()
                os.fsync(tf.fileno())

            os.replace(temp_path, target_path)
            temp_path = None
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

        return state


# ---------------------------------------------------------------------------
# High-Level State Operations
# ---------------------------------------------------------------------------

def get_state_value(key: Optional[str] = None, filepath: Optional[str] = None) -> dict[str, Any]:
    """Get state value(s). If key is None, return all state."""
    state = load_state(filepath=filepath)
    if key:
        if key in state:
            return {key: state[key]}
        return {"error": f"Key '{key}' not found"}
    return {"state": state}


def set_state_value(key: str, value: Any, filepath: Optional[str] = None) -> dict[str, Any]:
    """Set a state key/value pair atomically."""
    # Attempt to deserialize stringified JSON values
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass

    def _setter(state: dict[str, Any]) -> None:
        state[key] = value

    updated = update_state(_setter, filepath=filepath)
    return {"ok": True, "state": updated}


def set_target_hwnd(hwnd: int, filepath: Optional[str] = None) -> dict[str, Any]:
    """Set the active target window HWND in state atomically."""
    hwnd_int = int(hwnd)

    def _setter(state: dict[str, Any]) -> None:
        state["target_hwnd"] = hwnd_int

    update_state(_setter, filepath=filepath)
    return {"ok": True, "target_hwnd": hwnd_int}


def resolve_target_hwnd(hwnd: Optional[int], filepath: Optional[str] = None) -> Optional[int]:
    """Resolve HWND, falling back to persisted target_hwnd if hwnd is None."""
    if hwnd is not None:
        return int(hwnd)
    state = load_state(filepath=filepath)
    target = state.get("target_hwnd")
    if target is not None:
        try:
            return int(target)
        except (ValueError, TypeError):
            pass
    return None


def next_screenshot_id(filepath: Optional[str] = None) -> int:
    """Increment and return the next screenshot counter ID atomically."""
    next_id = [0]

    def _increment(state: dict[str, Any]) -> None:
        current = int(state.get("screenshot_counter", 0) or 0)
        next_id[0] = current + 1
        state["screenshot_counter"] = next_id[0]

    update_state(_increment, filepath=filepath)
    return next_id[0]


def remember_screenshot(
    meta: dict[str, Any],
    filepath: Optional[str] = None,
    max_history: int = 30,
) -> None:
    """Store screenshot metadata in state with bounded history limit."""
    if not isinstance(meta, dict) or "id" not in meta:
        return

    def _record(state: dict[str, Any]) -> None:
        screenshots = state.get("screenshots", {})
        if not isinstance(screenshots, dict):
            screenshots = {}
        screenshots[str(meta["id"])] = meta
        # Bound history to recent entries
        recent_ids = sorted(
            screenshots.keys(),
            key=lambda k: int(k) if str(k).isdigit() else -1,
        )[-max_history:]
        state["screenshots"] = {k: screenshots[k] for k in recent_ids}
        state["last_screenshot"] = meta
        state["last_screenshot_size"] = {
            "width": meta.get("width"),
            "height": meta.get("height"),
        }

    update_state(_record, filepath=filepath)


def load_screenshot_meta(
    screenshot_id: Optional[int] = None,
    filepath: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Load metadata for a specific screenshot ID or the latest screenshot."""
    state = load_state(filepath=filepath)
    if screenshot_id is None:
        return state.get("last_screenshot")
    screenshots = state.get("screenshots", {})
    if isinstance(screenshots, dict):
        return screenshots.get(str(screenshot_id))
    return None


def clear_state(filepath: Optional[str] = None) -> None:
    """Reset state file to an empty dictionary atomically."""
    save_state({}, filepath=filepath)


def state_cli(key: Optional[str] = None, value: Optional[Any] = None, filepath: Optional[str] = None) -> dict[str, Any]:
    """CLI helper for `tools.py state [key] [value]`."""
    if key is None:
        return load_state(filepath=filepath)
    if value is None:
        return get_state_value(key, filepath=filepath)
    return set_state_value(key, value, filepath=filepath)


def migrate_legacy_state(
    state_file: Optional[str] = None,
    backup: bool = True,
) -> bool:
    """
    Safely migrate existing state file to atomic schema without data loss.
    """
    target_file = os.path.abspath(state_file or DEFAULT_STATE_FILE)
    if not os.path.exists(target_file):
        return False

    raw_data = {}
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            parsed = json.load(f)
            if isinstance(parsed, dict):
                raw_data = parsed
    except Exception:
        corrupt_backup = f"{target_file}.corrupt.{int(time.time())}"
        shutil.copy2(target_file, corrupt_backup)
        raw_data = {}

    if backup and os.path.exists(target_file):
        backup_file = f"{target_file}.bak.{int(time.time())}"
        shutil.copy2(target_file, backup_file)

    normalized = {
        "screenshot_counter": int(raw_data.get("screenshot_counter", 0) or 0),
        "screenshots": {},
        "last_screenshot": raw_data.get("last_screenshot") if isinstance(raw_data.get("last_screenshot"), dict) else None,
        "last_screenshot_size": raw_data.get("last_screenshot_size") if isinstance(raw_data.get("last_screenshot_size"), dict) else None,
        "target_hwnd": raw_data.get("target_hwnd"),
        "uia_scans": raw_data.get("uia_scans") if isinstance(raw_data.get("uia_scans"), dict) else {},
    }

    screenshots = raw_data.get("screenshots", {})
    if isinstance(screenshots, dict):
        recent_ids = sorted(
            screenshots.keys(),
            key=lambda k: int(k) if str(k).isdigit() else -1,
        )[-30:]
        normalized["screenshots"] = {k: screenshots[k] for k in recent_ids}

    for k, v in raw_data.items():
        if k not in normalized:
            normalized[k] = v

    save_state(normalized, filepath=target_file)
    return True
