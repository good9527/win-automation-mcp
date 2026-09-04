# Project: win-automation-mcp Optimization & Refactoring

## Architecture
The `win-automation-mcp` project is refactored from two monolithic scripts (`tools.py` 51k lines, `server.py` 33k lines) into a high-performance, modular Python package `win_automation/` with thin backward-compatible root entrypoints and a standalone test suite in `tests/`.

```
win-automation-mcp/
├── win_automation/               # Modular Core Package
│   ├── __init__.py               # Package metadata & exports
│   ├── core/                     # Common types, Win32 structures (29 ctypes classes), DPI awareness, utils
│   ├── win32/                    # Native Win32 window enumeration, rects, menus, native controls (Button, ComboBox, ListBox, TreeView, etc.)
│   ├── uia/                      # UIAutomation COM wrappers, tree building, selector repair, pattern invocations
│   ├── msaa/                     # AccessibleObjectFromWindow, IAccessible inspection and actions
│   ├── vision/                   # Screen capture pipeline, DXCamManager caching singleton, PrintWindow/BitBlt fallbacks, template matching
│   ├── ocr/                      # Direct in-memory WinRT OCR (<100ms), Tesseract fallback, word rect bounding boxes
│   ├── input/                    # SendInput keyboard/mouse injection, clipboard preservation, smart click/input
│   ├── safety/                   # Bilingual (Chinese & English) safety gate classification, destructive/financial/system rules
│   ├── state/                    # Concurrency-safe state management with atomic tempfile+os.replace & file locking
│   ├── helper/                   # Helper client, token generation, X-Helper-Token validation, Host 127.0.0.1 enforcement
│   ├── batch/                    # Batch execution engine, graph traversal, condition evaluation, timeout budgets
│   ├── diagnostics/              # Doctor self-check, environment validation, capability probing
│   ├── server/                   # MCP server implementation, dual profile (Compact 9 tools vs Expert 111 tools), routing engine
│   └── cli/                      # 111-branch CLI command dispatcher, argument parsing, JSON formatter
├── server.py                     # Thin root wrapper (~25 lines) delegating to win_automation.server
├── tools.py                      # Thin root wrapper (~25 lines) delegating to win_automation.cli
├── helper.py                     # Resident background HTTP service with X-Helper-Token & Host security
├── tests/                        # Standalone test suite (Tiers 1-5)
│   ├── runner.py                 # Unified test runner with pass/fail reporting
│   ├── test_tier1_features.py    # Tier 1: Feature coverage (≥5 per feature)
│   ├── test_tier2_boundaries.py  # Tier 2: Boundary & corner cases (≥5 per feature)
│   ├── test_tier3_combinations.py# Tier 3: Cross-feature pairwise interactions
│   ├── test_tier4_scenarios.py   # Tier 4: Real-world desktop automation scenarios
│   └── test_tier5_adversarial.py # Tier 5: Adversarial white-box tests
├── TEST_INFRA.md                 # E2E Test Suite Infrastructure Specification
├── TEST_READY.md                 # E2E Test Readiness Signal & Coverage Checklist
└── .gitignore                    # Cleaned gitignore preventing runtime/artifact leakage
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Core Modular Architecture | Refactor ~586 duplicate functions and 29 ctypes classes into `win_automation` submodules (`core`, `win32`, `uia`, `input`, `msaa`, `batch`, `diagnostics`) | M1 | R5 |
| 2 | Repository Hygiene & BOM Removal | Strip UTF-8 BOM from `server.py`, clean 68 stray test images/logs/zips from root, update `.gitignore` | M1 | R6 |
| 3 | Concurrency-Safe State Persistence | Implement atomic file replacement (`tempfile` + `os.replace`) and file locking (`msvcrt.locking`) for `~/.win-auto-state.json` in `win_automation.state` | M1 | R6 |
| 4 | Helper Security & Authentication Barrier | Generate crypto-random session token, require & verify `X-Helper-Token` on all requests, enforce strict `Host: 127.0.0.1` validation, return HTTP 403 Forbidden | M2 | R2 |
| 5 | Chinese & Destructive Operation Safety Gate | Implement `check_safety` in `win_automation.safety` classifying file destruction, financial transactions, and system shutdown/alterations in Chinese & English | M3 | R3 |
| 6 | In-Memory WinRT OCR Pipeline | Implement direct in-memory WinRT OCR invocation path in Python (<100ms latency, zero powershell.exe spawns) with word rect bounding boxes | M4 | R4 |
| 7 | DXCam & Vision Pipeline Acceleration | Implement singleton `DXCamManager` process-level camera instance caching and capture fallback ladder | M4 | R4 |
| 8 | GDI & UIA COM Resource Management | Wrap all GDI device contexts (CreateCompatibleDC, GetDC, ReleaseDC, DeleteDC, DeleteObject) and UIA COM objects in strict `try...finally` / context managers | M4 | R4 |
| 9 | High-Intent Compact MCP Profile & Routing | Implement default `compact` profile with 9 high-intent tools (`observe_window`, `act`, `type_input`, `key_press`, `wait_state`, `execute_batch`, `check_safety`, `launch_app`, `doctor`) with <35,000 chars schema and UIA->Win32->OCR->Coord fallback | M5 | R1 |
| 10 | Expert MCP Profile (111 Tools Preservation) | Implement `expert` profile preserving all 111 granular tools switchable via environment variable `WIN_AUTO_PROFILE=expert` or config | M5 | R1 |
| 11 | Backward-Compatible Entrypoint Wrappers | Convert root `server.py` and `tools.py` into thin wrappers; preserve 100% of the 111 CLI commands and aliases in `win_automation.cli` | M5 | R5 |
| 12 | E2E Testing Suite & Infrastructure | Establish standalone `tests/` suite with Tiers 1-4 tests covering all requirements, `runner.py`, and `TEST_READY.md` publishing | M_TEST | R5, AC |
| 13 | Final Integration, Hardening & Audit | Run 100% E2E tests, execute Tier 5 adversarial hardening, conduct Forensic Integrity Audit, and verify legacy CLI/MCP compatibility | M6 | AC |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M_TEST | E2E Testing Track Infrastructure | Design test harness `tests/runner.py`, implement Tiers 1-4 tests for R1-R6, publish `TEST_INFRA.md` and `TEST_READY.md` | none | PLANNED |
| M1 | Core Modular Package & Repo Hygiene | Create `win_automation` core package structure, ctypes classes, win32/uia/input/state modules, atomic state persistence, remove BOM, clean stray files, update `.gitignore` | none | PLANNED |
| M2 | Helper Security & Authentication Barrier | Implement session token generation in client, enforce `X-Helper-Token` validation & `Host: 127.0.0.1` checks in `helper.py`, return 403 Forbidden | M1 | PLANNED |
| M3 | Chinese & Destructive Operation Safety Gate | Implement `win_automation.safety` with comprehensive keyword/regex classification for file destruction, financial transactions, system shutdown/alteration | M1 | PLANNED |
| M4 | In-Memory OCR & Pipeline Acceleration | Implement in-memory WinRT OCR (<100ms), `DXCamManager` caching singleton, `try...finally` GDI/UIA COM resource cleanup | M1 | PLANNED |
| M5 | MCP Dual Profile, Action Routing & Wrappers | Implement Compact (9 tools <35k chars) and Expert (111 tools) profiles in `win_automation.server`, action fallback routing, 111-branch CLI in `win_automation.cli`, root thin wrappers `server.py` and `tools.py` | M1, M2, M3, M4 | PLANNED |
| M6 | Final Integration, Hardening & Verification | Phase 1: 100% pass of E2E test suite (Tiers 1-4); Phase 2: Tier 5 adversarial hardening with Challenger; Forensic Auditor verification; CLI backward compatibility verification | M_TEST, M5 | PLANNED |

## Code Layout
- `win_automation/core/`: `types.py`, `win32_structures.py`, `dpi.py`, `utils.py`
- `win_automation/win32/`: `window.py`, `controls.py`, `menu.py`, `dialog.py`, `find.py`
- `win_automation/uia/`: `engine.py`, `tree.py`, `patterns.py`, `repair.py`, `cache.py`
- `win_automation/msaa/`: `accessible.py`
- `win_automation/vision/`: `capture.py`, `dxcam_manager.py`, `match.py`, `pixel.py`
- `win_automation/ocr/`: `winrt_ocr.py`, `tesseract_ocr.py`, `words.py`
- `win_automation/input/`: `keyboard.py`, `mouse.py`, `clipboard.py`, `smart_input.py`
- `win_automation/safety/`: `classifier.py`, `rules.py`
- `win_automation/state/`: `persistence.py`, `locks.py`
- `win_automation/helper/`: `client.py`, `security.py`
- `win_automation/batch/`: `engine.py`, `evaluator.py`
- `win_automation/diagnostics/`: `doctor.py`
- `win_automation/server/`: `app.py`, `compact_tools.py`, `expert_tools.py`, `router.py`
- `win_automation/cli/`: `main.py`, `commands.py`
- `tests/`: `runner.py`, `test_tier1_features.py`, `test_tier2_boundaries.py`, `test_tier3_combinations.py`, `test_tier4_scenarios.py`, `test_tier5_adversarial.py`
- `server.py`: Root wrapper delegating to `win_automation.server.main()`
- `tools.py`: Root wrapper delegating to `win_automation.cli.main()`
- `helper.py`: Resident helper service with `win_automation.helper.security` verification

## Interface Contracts

### `win_automation.safety.check_safety(action: str) -> dict`
- **Input**: `action: str` (e.g., "删除系统文件", "format c:", "支付订单50元")
- **Output**:
  ```python
  {
      "needs_confirmation": bool,
      "risk_level": "none" | "low" | "medium" | "high" | "critical",
      "category": "file_destruction" | "financial_transaction" | "system_alteration" | "none",
      "reason": str,
      "action": str
  }
  ```

### `win_automation.ocr.run_ocr(image_or_bytes, lang="zh-Hans-CN") -> list[dict]`
- **Input**: PIL Image, numpy array, or bytes of BMP/PNG
- **Latency**: < 100ms (in-memory WinRT COM/Ctypes execution path)
- **Output**:
  ```python
  [
      {
          "text": str,
          "confidence": float,
          "rect": {"x": int, "y": int, "width": int, "height": int}
      }
  ]
  ```

### `win_automation.helper.security`
- Session token generation: `generate_session_token() -> str` (256-bit entropy via `secrets.token_urlsafe(32)`)
- Verification: `verify_request(headers: dict, expected_token: str) -> tuple[bool, int, str]`
  - Validates `X-Helper-Token` header using `hmac.compare_digest`.
  - Validates `Host` header strictly equals `127.0.0.1:<port>` or `127.0.0.1`.
  - Returns `(True, 200, "OK")` or `(False, 403, "Forbidden: ...")`.

### `win_automation.state.save_state(state: dict, filepath: str = STATE_FILE)`
- Thread & process-safe persistence.
- Writes to `tempfile.NamedTemporaryFile` in same directory.
- Acquires file lock (`msvcrt.locking` on Windows), flushes, syncs, then atomic `os.replace`.

### `win_automation.server` Dual Profiles
- `compact`: Exposes 9 tools:
  1. `observe_window(hwnd: int | None, screenshot: bool, accessibility: bool, ocr: bool, max_width: int)`
  2. `act(hwnd: int | None, action: str, target: dict | None, coordinates: list[int] | None, value: str | None)`
  3. `type_input(hwnd: int | None, text: str, target: dict | None, clear_first: bool, enter: bool)`
  4. `key_press(keys: str, hwnd: int | None)`
  5. `wait_state(hwnd: int | None, condition: str, target: dict | None, timeout: float)`
  6. `execute_batch(commands: list[dict], stop_on_error: bool, timeout: float)`
  7. `check_safety(action: str)`
  8. `launch_app(app_name_or_path: str, timeout: float)`
  9. `doctor(hwnd: int | None)`
  - Total serialized schema size: < 35,000 characters (actual ~8,000–12,000 chars).
- `expert`: Exposes full 111 granular tools preserving exact legacy names and signatures.
- Profile selection: Environment variable `WIN_AUTO_PROFILE` ("compact" default, "expert") or `--profile` CLI flag.
