# MCP reference

Use the `win-automation` MCP server when available. Prefer semantic tools and
wait variants over coordinate input.

## Preferred tools

- `list_windows`, `list_apps`, `launch`, `wait_window`, `wait_event`
- `observe_window`, `get_window_state`, `accessibility`, `find_elements`,
  `wait_for_element`, `get_element`, `focus_element`
- `smart_click`, `smart_wait_click`, `smart_text_input`,
  `smart_wait_text_input`, `smart_select`, `smart_wait_select`,
  `smart_cell`, `smart_wait_cell`
- `file_dialog_info`, `file_dialog_action`, `dialog_command_action`,
  `dialog_button_action`, `menu_tree`, `menu_action`
- `control_boundary`, `helper_status`, `activate_window`, `focus_hwnd`
- `desktop_accessibility`, `desktop_find_elements`, `desktop_wait_for_element`,
  `desktop_action`, `desktop_screenshot`
- `find_text_ocr`, `wait_text_ocr`, `click_text_ocr`, `locate_image`,
  `wait_image`, `click_image`, `pixel_wait`, `visual_stable_wait`,
  `uia_stable_wait`
- `execute_batch`, `check_safety`, `selftest_selector`, `selftest_batch`,
  `selftest_server_contracts`

## Selector conventions

Prefer `automation_id`, `control_type`, `class_name`, process/title filters,
and row/column metadata. Use `view="control"` for actionable trees and
`view="content"` for lean document panes. Use `repair=true` only when the
failure diagnostics include a stable selector suggestion.

## Action conventions

Use `verify=true` where the tool supports it. For transitions, use
`wait_event`, a wait variant, or a stability wait. For standard Open/Save
dialogs, use `file_dialog_action` rather than clicking coordinates.

For elevated targets, call `control_boundary` first. Start the elevated helper
only when the result reports `uipi_risk` or `needs_elevation`.

For multi-step work, call `execute_batch` with `stop_on_error=true`, a bounded
`timeout_budget`, and explicit `expect` conditions. Include `confirmed=true`
only after user confirmation for sensitive actions.
