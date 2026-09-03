---
name: desktop-control-portable
description: Control Windows desktop applications through UIA, desktop-root UIA, Win32, HMENU, MSAA, OCR, image matching, screenshots, and safe input fallbacks. Use when Codex needs to open, observe, focus, click, type, select, drag, scroll, wait for, verify, or diagnose Windows software, dialogs, taskbar UI, custom-rendered controls, elevated applications, or multi-step desktop workflows.
---

# Desktop Control

Use the enhanced local engine in this repository. Prefer MCP tools when the
client exposes the `win-automation` server. Use `CONTROL.cmd` when MCP is not
available, or run `python tools.py ...` from this repository during development.

## Safety gate

Treat desktop actions as real user actions. Before destructive, financial,
account, permission, installation, deletion, message-sending, or irreversible
operations:

1. Call `check_safety` or `python tools.py confirm "<plain-language action>"`.
2. Ask the user for explicit confirmation when the result says confirmation is required.
3. For multi-step work, execute through `execute_batch` or `batch` with
   `confirmed: true` only after that confirmation. Without it, the engine must
   return `confirmation_required` and perform no step.
4. Verify the final state and report what changed.

Never treat a risk diagnostic as approval. Do not use coordinate clicks to
evade the safety gate.

See [safety and verification](references/safety.md) for the payload contract.

## Standard workflow

1. Acquire a stable target with `list_windows`, `list_apps`, `launch`,
   `wait_window`, or `wait_event`. Reuse an existing window when possible.
2. Run `observe` or `get_window_state` before acting. Refresh the observation
   after navigation, dialog creation, layout replacement, or a stale index.
3. Activate the top-level window and focus the actual input control before
   typing or sending shortcuts.
4. Select the most semantic available action using the order below.
5. Prefer waits over fixed sleeps when the UI is asynchronous.
6. Add a postcondition such as `verify`, `uia_wait`, `win32_control_wait`,
   `pixel_wait`, `visual_stable_wait`, or a negative absence check.
7. Return the normalized result, including whether the action was verified.

## Action priority

Use these layers in order and descend only when the higher layer is missing,
unreliable, or explicitly skipped:

1. UIA selectors/actions, desktop-root UIA, Win32 controls, HMENU, and MSAA.
2. Smart helpers: `smart-click`, `smart-text`, `smart-select`, `smart-cell`,
   and their wait variants.
3. OCR, screenshots, image matching, pixel probes, and visual row helpers.
4. Raw mouse and keyboard input only when semantic paths are unavailable.

Use stable selectors whenever possible: `automation_id`, `control_type`,
`class_name`, process/title constraints, row/column metadata, or a fresh
observation index. Coordinate and image actions must use a fresh screenshot,
bounded region, and explicit verification.

## Common commands

```powershell
python tools.py list_windows
python tools.py observe <hwnd>
python tools.py activate <hwnd>
python tools.py smart-click <hwnd> --name "Save" --type button
python tools.py smart-wait-click <hwnd> --name "OK" --type button --timeout 10
python tools.py smart-text <hwnd> "text" --name "Search" --type edit
python tools.py smart-select <hwnd> "Beta" --type listbox
python tools.py smart-cell <hwnd> --row-text "Beta" --column-name "State"
python tools.py wait-event object-show --hwnd <hwnd> --timeout 5
python tools.py file-dialog open "C:\Path\file.txt" --verify-close
python tools.py control-boundary <hwnd>
python tools.py helper-status
python tools.py selftest selector
```

For the full CLI surface, read [CLI reference](references/cli.md). For MCP
tool names and argument conventions, read [MCP reference](references/mcp.md).

## Recovery rules

- Window not found: list or wait for windows, then rebind by title/process/PID.
- Stale UIA index: refresh the accessibility tree; use selector repair only
  when the returned suggestion preserves identity and control constraints.
- Dynamic dialog or menu: use `wait-event`, `wait-window`, or the smart dialog
  action; do not guess a coordinate.
- UIPI/elevation failure: run `control-boundary`; start the elevated helper
  only when it reports `uipi_risk` or `needs_elevation`.
- Bad UIA provider: use `skip_uia`/`--no-uia` and try native Win32 controls.
- Visual-only target: capture a fresh screenshot, constrain the region, use
  OCR/image matching, then verify the resulting state.
- Timeout: preserve the failure category and diagnostics, and retry only with
  a documented recovery branch and a bounded timeout budget.

See [recovery reference](references/recovery.md) for detailed patterns.

## Batch execution

Use `execute_batch` or `batch` for multi-step workflows. Include
`stop_on_error`, a bounded `timeout_budget`, and cleanup/failure branches when
appropriate. Add `expect` to steps whose final state matters. Use
`plan_only: true` to inspect an automatic fallback plan before execution.

Example:

```json
{
  "commands": [
    {"command": "activate", "args": {"hwnd": 123}},
    {"command": "smart_click", "args": {"hwnd": 123, "name": "Save", "control_type": "button"}, "expect": {"ok": true}},
    {"command": "wait_event", "args": {"event": "object-show", "hwnd": 123, "timeout": 5}}
  ],
  "stop_on_error": true,
  "timeout_budget": 30
}
```

## References

- [CLI reference](references/cli.md): command families, flags, and examples.
- [MCP reference](references/mcp.md): preferred MCP tools and parameters.
- [Safety and verification](references/safety.md): confirmation and result contract.
- [Recovery](references/recovery.md): window, selector, helper, and visual fallback recovery.
