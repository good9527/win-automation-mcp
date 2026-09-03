# Test Infrastructure & Methodology Specification (TEST_INFRA.md)

**Project:** win-automation-mcp (Windows Desktop Automation MCP Server)  
**Document Version:** 1.0.0  
**Target Scope:** Standalone 4-Tier (+ Tier 5 Adversarial) Requirement-Driven Opaque-Box Test Suite  
**Author:** Test Writer (Milestone M_TEST)  
**Date:** 2026-09-03  

---

## 1. Executive Summary & Testing Philosophy

The win-automation-mcp test suite provides a comprehensive, deterministic, and progressive verification framework for the Windows desktop automation MCP server refactoring. The testing architecture is designed around four foundational principles:

1. **Opaque-Box Requirement-Driven Verification:** Tests evaluate behavior against authoritative specifications (PROJECT.md, ORIGINAL_REQUEST.md, spec.md) rather than coupling to internal implementation details.
2. **Progressive Testability Across Milestones:** Tests are structured in tiers that map directly to project milestones (M1 Core, M2 Security, M3 Safety Gate, M4 Vision/OCR, M5 MCP Profiles/CLI, M6 Integration/Audit), allowing incremental verification as modules are implemented.
3. **Strict Isolation & Zero System Side-Effects:** Desktop automation tests use non-destructive sandboxing, mock windowing/GDI contexts where hardware handles are unavailable, and isolated temporary directories for state persistence.
4. **Authoritative Expected Output Derivation:** Every test assertion is derived from explicit specification contracts, mathematical properties (e.g. schema size < 35,000 characters, OCR latency < 100ms), or security threat models (RFC 7230 Host validation, constant-time token comparison).

---

## 2. Multi-Tier Test Architecture

`
                               +------------------------------------------------+
                               |             tests/runner.py                    |
                               |   Unified Test Runner & Summary Aggregator     |
                               +----------------------+-------------------------+
                                                      |
         +------------------+-------------------------+-------------------------+------------------+
         |                  |                         |                         |                  |
         v                  v                         v                         v                  v
+------------------++------------------+    +------------------+    +------------------++------------------+
|     Tier 1       ||     Tier 2       |    |     Tier 3       |    |     Tier 4       ||     Tier 5       |
| Feature Baseline || Boundaries/Edges |    | Cross-Feature    |    | Realistic E2E    || Adversarial &    |
| (F1 - F9, >=5 ea)|| (Extreme/Spoof)  |    | Combinations     |    | Scenarios        || Forensic Stress  |
| test_tier1_*.py  || test_tier2_*.py  |    | test_tier3_*.py  |    | test_tier4_*.py  || test_tier5_*.py  |
+------------------++------------------+    +------------------+    +------------------++------------------+
`

### 2.1 Tier Overview

| Tier | File | Target Focus | Minimum Cases | Key Verification Areas |
|---|---|---|---|---|
| **Tier 1: Feature Verification** | tests/test_tier1_features.py | Primary feature contracts for R1-R6 | >= 5 per feature (>= 45 total) | Modular imports, BOM removal, atomic state, helper auth, safety gate, in-memory OCR, DXCam cache, compact profile (<35k chars), backward compatibility wrappers |
| **Tier 2: Boundaries & Corners** | tests/test_tier2_boundaries.py | Extreme inputs, edge limits, malformed data | >= 30 cases | Empty strings/JSON, giant payloads (100KB+), spoofed Host headers (Host: evil.com), unicode edge cases (emojis, zero-width spaces), negative coordinates, missing/corrupt state files |
| **Tier 3: Combinations** | tests/test_tier3_combinations.py | Pairwise & multi-module integration | >= 20 cases | Safety gate + batch execution, observe_window + act routing, helper token + HTTP request, state persistence + active HWND restoration, UIA-to-Win32 fallback ladder |
| **Tier 4: Realistic Scenarios** | tests/test_tier4_scenarios.py | End-to-end desktop automation workflows | >= 15 cases | Notepad text editing workflow, dangerous financial operation interception, calculator batch operations, window geometry self-repair, high-throughput visual stability polling |
| **Tier 5: Adversarial & Forensic** | tests/test_tier5_adversarial.py | Security penetration & forensic integrity | >= 10 cases | Timing attack resilience on token validation, concurrency race conditions on atomic state, memory leak prevention on GDI/COM handles |

---

## 3. Feature-to-Test Mapping Matrix (Tier 1)

| Feature ID | Feature Name | Requirement Ref | Target Module / Interface | Minimum Test Cases |
|---|---|---|---|---|
| **F1** | Modular Import Structure | R5 | win_automation.* (core, win32, uia, vision, ocr, input, safety, state, helper, server, cli) | 5 |
| **F2** | BOM Absence & Repo Hygiene | R6 | server.py, tools.py, helper.py, .gitignore | 5 |
| **F3** | Atomic State Persistence & File Locking | R6 | win_automation.state (save_state, load_state, lock handling) | 5 |
| **F4** | Helper Authentication & Host Validation | R2 | win_automation.helper.security (verify_request, generate_session_token) | 6 |
| **F5** | Chinese & English Safety Classification | R3 | win_automation.safety (check_safety) | 6 |
| **F6** | In-Memory WinRT OCR (<100ms) | R4 | win_automation.ocr (run_ocr, bounding boxes, language support) | 5 |
| **F7** | DXCam Instance Reuse & Capture Ladder | R4 | win_automation.vision (DXCamManager, capture ladder, GDI cleanup) | 5 |
| **F8** | Compact Profile Schema & Tool Registry | R1 | win_automation.server (9 tools, schema length < 35,000 chars) | 5 |
| **F9** | Backward Compatibility Entry Points | R5 | server.py, tools.py CLI dispatcher | 5 |

---

## 4. Test Execution & Reporting Protocol

### 4.1 Running Tests with tests/runner.py

The test runner provides a zero-dependency CLI interface built on Python standard unittest with colored terminal output, tier filtering, pattern matching, and JSON export.

`powershell
# Run all test tiers (Tiers 1-4, and 5 if present)
python tests/runner.py

# Run a specific tier
python tests/runner.py --tier 1
python tests/runner.py --tier 2
python tests/runner.py --tier 3
python tests/runner.py --tier 4

# Run with verbose output (display each test method)
python tests/runner.py -v

# Run with fail-fast mode (stop on first failure)
python tests/runner.py -f

# Filter tests by keyword pattern
python tests/runner.py -k safety
python tests/runner.py -k token

# Export structured JSON execution report
python tests/runner.py --json report.json
`

### 4.2 Running Tests with pytest

The test suite is fully compatible with standard pytest:

`powershell
# Run all tests via pytest
pytest tests/ -v

# Run specific tier file
pytest tests/test_tier1_features.py -v
`

### 4.3 Exit Codes & CI Integration

- **0**: All executed tests passed (or were legitimately skipped due to hardware constraints).
- **1**: One or more test assertions failed.
- **2**: Unhandled test execution error or syntax error.

---

## 5. Security & Safety Test Isolation Sandbox

1. **Non-Destructive Testing:** Tests asserting destructive command blocking in check_safety pass raw command strings to the classifier without executing system commands (del, format, shutdown).
2. **State Isolation:** All state persistence tests use isolated temporary directories via tempfile.TemporaryDirectory(), preventing modification of the user's real ~/.win-auto-state.json.
3. **Helper Mock Daemon:** Network and authentication tests spin up ephemeral test HTTP servers on dynamic high ports or test verify_request directly in memory, avoiding conflicts with running production helper instances.
4. **DirectX & OCR Fallback Grace:** OCR and screen capture tests execute against synthetic in-memory RGB/BGRA image buffers (e.g. generated PIL bitmaps) to ensure tests execute reliably in headless CI and non-display environments.

---

## 6. Milestone Traceability & Progressive Test Readiness

| Milestone | Modules Under Test | Validating Test Suites |
|---|---|---|
| **M1** | Core Package, State Persistence, BOM, Hygiene | test_tier1_features.py (F1, F2, F3), test_tier2_boundaries.py (State/Files) |
| **M2** | Helper Security & Host Barrier | test_tier1_features.py (F4), test_tier2_boundaries.py (Headers/Tokens), test_tier3_combinations.py (Helper Auth) |
| **M3** | Chinese & English Safety Gate | test_tier1_features.py (F5), test_tier2_boundaries.py (Unicode/Payloads), test_tier3_combinations.py (Safety + Batch) |
| **M4** | In-Memory WinRT OCR & DXCam Cache | test_tier1_features.py (F6, F7), test_tier4_scenarios.py (Visual Stability) |
| **M5** | MCP Dual Profiles, Routers, CLI Wrappers | test_tier1_features.py (F8, F9), test_tier3_combinations.py (Routing Ladder), test_tier4_scenarios.py (Notepad/Calc) |
| **M6** | Final Integration, Hardening & Audit | Full Suite (Tiers 1-4 + Tier 5 Adversarial) |
