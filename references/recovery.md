# Recovery reference

## Window and dialog recovery

List or wait for windows when a title lookup fails. Prefer process/title/PID
constraints over a cached HWND. After an action that opens a dialog, menu, or
lazy panel, wait for the relevant event or related window before scanning it.

## Selector recovery

Refresh the accessibility tree after navigation or a full layout replacement.
If a smart wait fails and diagnostics contain `selector_suggestions`, retry with
`repair=true`. Do not trust a stale index unless identity metadata still agrees
on control type, AutomationId/name, parent/container, and pattern.

## Integrity and helper recovery

Run `control_boundary` before changing integrity level. Start an elevated helper
only for an explicit `uipi_risk` or `needs_elevation` result. Use
`helper-status --restart` for a normal stale-helper reload.

## Native and visual recovery

For a bad UIA provider, use `skip_uia`/`--no-uia` and native Win32 tools. For a
custom-rendered target, capture a fresh screenshot, limit the region, and use
OCR/image matching. After a visual action, verify with text, pixel, or state
waits. Never retry an uncertain coordinate click without a new observation.

## Failure reporting

Preserve `failure_category`, `failure_summary`, attempted methods, selector
suggestions, boundary diagnostics, and whether a retry changed the target. Use
bounded timeouts and stop when the target identity cannot be proven.
