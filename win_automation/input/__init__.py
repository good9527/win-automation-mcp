"""
Input automation submodule of win-automation-mcp.
Provides SendInput keyboard injection, mouse events, clipboard management, and multi-layer smart input.
"""

from win_automation.input.keyboard import (
    type_text,
    press_key,
    focused_input,
)
from win_automation.input.mouse import (
    click,
    mouse_position,
    move_mouse,
    scroll,
    drag,
    desktop_click,
    desktop_move,
    desktop_hover,
    desktop_scroll,
    desktop_drag,
)
from win_automation.input.clipboard import (
    _open_clipboard_retry,
    _clipboard_snapshot,
    _clipboard_restore_snapshot,
    _clipboard_save,
    _clipboard_restore,
    _set_clipboard_text,
)
from win_automation.input.smart_input import (
    smart_click,
    smart_wait_click,
    smart_text_input,
    smart_wait_text_input,
    smart_select,
    smart_wait_select,
    smart_cell,
    smart_wait_cell,
    smart_dialog_action,
)

# Additional aliases
smart_select_item = smart_select
smart_wait_select_item = smart_wait_select
smart_cell_action = smart_cell
smart_wait_cell_action = smart_wait_cell
mouse_click = click
mouse_move = move_mouse
mouse_scroll = scroll
mouse_drag = drag
get_mouse_position = mouse_position

__all__ = [
    "type_text",
    "press_key",
    "focused_input",
    "click",
    "mouse_click",
    "mouse_position",
    "get_mouse_position",
    "move_mouse",
    "mouse_move",
    "scroll",
    "mouse_scroll",
    "drag",
    "mouse_drag",
    "desktop_click",
    "desktop_move",
    "desktop_hover",
    "desktop_scroll",
    "desktop_drag",
    "_open_clipboard_retry",
    "_clipboard_snapshot",
    "_clipboard_restore_snapshot",
    "_clipboard_save",
    "_clipboard_restore",
    "_set_clipboard_text",
    "smart_click",
    "smart_wait_click",
    "smart_text_input",
    "smart_wait_text_input",
    "smart_select",
    "smart_select_item",
    "smart_wait_select",
    "smart_wait_select_item",
    "smart_cell",
    "smart_cell_action",
    "smart_wait_cell",
    "smart_wait_cell_action",
    "smart_dialog_action",
]
