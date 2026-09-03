---
name: desktop-control-portable
description: Control Windows desktop applications through UIA, desktop-root UIA, Win32, HMENU, MSAA, OCR, image matching, screenshots, and safe input fallbacks. Use when Codex needs to open, observe, click, type, select, drag, scroll, wait for, verify, or diagnose Windows software, dialogs, taskbar UI, custom-rendered controls, elevated applications, or multi-step desktop workflows.
---

# Desktop Control Portable

This file is the packaging fallback. The portable build overwrites it with the
canonical repository `SKILL.md` and copies the repository `references/` folder,
so the installed skill and source skill stay aligned.

## Safety gate

Treat desktop actions as real user actions. Before destructive, financial,
account, permission, installation, deletion, message-sending, or irreversible
operations, call `check_safety` or `python tools.py confirm "<plain-language action>"`.
Ask the user for explicit confirmation when required. For multi-step work, pass
`confirmed: true` to `execute_batch` or `--confirmed` to `batch` only after that
confirmation. A sensitive batch without confirmation must return
`confirmation_required` and execute no step.

Observe before acting, prefer semantic selectors and waits, and add an explicit
postcondition such as `expect`, `verify`, or a wait/absence check. Verify the
final state and report what changed.

Prefer MCP tools when available. Otherwise resolve the portable package from
`$env:DESKTOP_CONTROL_HOME` and invoke `CONTROL.cmd`. Use UIA/native controls
before smart helpers, visual fallbacks, or raw coordinates.
