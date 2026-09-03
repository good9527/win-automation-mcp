"""
Windows Desktop Automation MCP Server & Tools Package.
High-performance desktop automation library for Windows supporting UIA, Win32, MSAA,
SendInput injection, OCR, computer vision, and concurrency-safe state persistence.
"""

__version__ = "1.0.0"

from win_automation.win32 import (
    enum_windows,
    foreground_window,
    get_window,
    get_window_info,
    activate_window,
    focus_hwnd,
    window_action,
    control_boundary,
    gui_thread_info,
)
from win_automation.uia import (
    build_accessibility_tree,
    desktop_accessibility,
    find_elements,
    click_index,
    perform_action,
)
from win_automation.input import (
    click,
    move_mouse,
    scroll,
    drag,
    type_text,
    press_key,
    focused_input,
    smart_click,
    smart_text_input,
    smart_select,
    smart_cell,
    smart_dialog_action,
)
from win_automation.vision import (
    observe_window,
    capture_window_screenshot,
    capture_desktop_screenshot,
)
from win_automation.ocr import (
    run_ocr,
    run_desktop_ocr,
)
from win_automation.safety import (
    check_safety,
    confirm_action,
)
from win_automation.state import (
    load_state,
    save_state,
    update_state,
    get_state_value,
    set_state_value,
    set_target_hwnd,
    resolve_target_hwnd,
)
from win_automation.diagnostics import (
    doctor,
    run_doctor,
)
from win_automation.batch import (
    execute_batch,
    execute_batch_file,
)

__all__ = [
    "__version__",
    "enum_windows",
    "foreground_window",
    "get_window",
    "get_window_info",
    "activate_window",
    "focus_hwnd",
    "window_action",
    "control_boundary",
    "gui_thread_info",
    "build_accessibility_tree",
    "desktop_accessibility",
    "find_elements",
    "click_index",
    "perform_action",
    "click",
    "move_mouse",
    "scroll",
    "drag",
    "type_text",
    "press_key",
    "focused_input",
    "smart_click",
    "smart_text_input",
    "smart_select",
    "smart_cell",
    "smart_dialog_action",
    "observe_window",
    "capture_window_screenshot",
    "capture_desktop_screenshot",
    "run_ocr",
    "run_desktop_ocr",
    "check_safety",
    "confirm_action",
    "load_state",
    "save_state",
    "update_state",
    "get_state_value",
    "set_state_value",
    "set_target_hwnd",
    "resolve_target_hwnd",
    "doctor",
    "run_doctor",
    "execute_batch",
    "execute_batch_file",
]
