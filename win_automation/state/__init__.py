"""
State management and persistence module for win-automation-mcp.
Exports atomic persistence helpers and file locking primitives.
"""

from .locks import FileLock, FileLockTimeoutError
from .persistence import (
    DEFAULT_STATE_FILE,
    STATE_FILE,
    DEFAULT_LOCK_FILE,
    get_state_lock,
    load_state,
    save_state,
    update_state,
    get_state_value,
    set_state_value,
    set_target_hwnd,
    resolve_target_hwnd,
    next_screenshot_id,
    remember_screenshot,
    load_screenshot_meta,
    clear_state,
    state_cli,
    migrate_legacy_state,
)

__all__ = [
    "FileLock",
    "FileLockTimeoutError",
    "DEFAULT_STATE_FILE",
    "STATE_FILE",
    "DEFAULT_LOCK_FILE",
    "get_state_lock",
    "load_state",
    "save_state",
    "update_state",
    "get_state_value",
    "set_state_value",
    "set_target_hwnd",
    "resolve_target_hwnd",
    "next_screenshot_id",
    "remember_screenshot",
    "load_screenshot_meta",
    "clear_state",
    "state_cli",
    "migrate_legacy_state",
]
