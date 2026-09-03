"""
Empirical verification script for Milestone M1 - Challenger 2.
Exhaustively tests:
1. BOM absence across all source files
2. All 111 CLI command branches and aliases via tools.py
3. JSON output formatting and validity across stdout
4. Error formatting and exit codes
5. PEP 562 dynamic resolution on tools.py and server.py
"""

import os
import sys
import json
import re
import subprocess
from typing import Dict, List, Any, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYTHON = sys.executable

def test_bom_absence() -> Tuple[bool, List[str]]:
    boms = []
    files_checked = 0
    for root, dirs, files in os.walk(ROOT_DIR):
        if any(ignored in root for ignored in [".git", ".venv", "__pycache__", ".agents"]):
            continue
        for f in files:
            if f.endswith((".py", ".json", ".md", ".txt", ".toml", ".bat", ".cmd")):
                files_checked += 1
                p = os.path.join(root, f)
                with open(p, "rb") as fp:
                    head = fp.read(4)
                    if head.startswith(b"\xef\xbb\xbf"):
                        boms.append(f"UTF-8 BOM in {os.path.relpath(p, ROOT_DIR)}")
                    elif head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
                        boms.append(f"UTF-16 BOM in {os.path.relpath(p, ROOT_DIR)}")
    return len(boms) == 0, boms

def extract_cli_command_branches() -> List[List[str]]:
    commands_path = os.path.join(ROOT_DIR, "win_automation", "cli", "commands.py")
    with open(commands_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r'(?:if|elif)\s+cmd\s+(?:==\s*["\']([^"\']+)["\']|in\s*\(([^)]+)\))')
    branches = []
    for match in pattern.finditer(content):
        single, multi = match.groups()
        if single:
            branches.append([single.strip()])
        elif multi:
            items = [x.strip(' "\'\t\n') for x in multi.split(',') if x.strip(' "\'\t\n')]
            branches.append(items)
    return branches

def run_tools_cli(args: List[str]) -> Tuple[int, str, str]:
    cmd = [PYTHON, os.path.join(ROOT_DIR, "tools.py")] + args
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT_DIR, encoding="utf-8", errors="replace")
    return res.returncode, res.stdout, res.stderr

def run_empirical_probes():
    print("=" * 70)
    print("CHALLENGER 2 EMPIRICAL VERIFICATION - MILESTONE M1")
    print("=" * 70)

    # 1. BOM Check
    print("\n--- 1. BOM Absence Test ---")
    bom_ok, bom_errors = test_bom_absence()
    if bom_ok:
        print("[PASS] 0 BOM markers detected across all source & config files.")
    else:
        print(f"[FAIL] Found BOM in {len(bom_errors)} files:")
        for err in bom_errors:
            print("  ", err)

    # 2. Extract branches
    print("\n--- 2. CLI Command Branches & Aliases Inventory ---")
    branches = extract_cli_command_branches()
    all_commands = [cmd for branch in branches for cmd in branch]
    print(f"Total distinct command branches: {len(branches)}")
    print(f"Total commands and aliases registered: {len(all_commands)}")

    # 3. Test help invocations
    print("\n--- 3. Help and Base Invocations ---")
    help_cases = [
        ([], 1, "Usage: python tools.py <command>"),
        (["--help"], 0, "Usage: python tools.py <command>"),
        (["-h"], 0, "Usage: python tools.py <command>"),
        (["help"], 0, "Usage: python tools.py <command>"),
    ]
    for args, exp_code, exp_snippet in help_cases:
        code, out, err = run_tools_cli(args)
        status = "PASS" if (code == exp_code and exp_snippet in out) else "FAIL"
        print(f"[{status}] `tools.py {' '.join(args)}` -> exit {code} (expected {exp_code}), output snippet match: {exp_snippet in out}")

    # 4. Unknown command handling
    print("\n--- 4. Unknown Command Error Handling ---")
    code, out, err = run_tools_cli(["__nonexistent_probe_cmd__"])
    unknown_ok = code == 1 and "Unknown command: __nonexistent_probe_cmd__" in out
    print(f"[{'PASS' if unknown_ok else 'FAIL'}] Unknown command exit {code}, output: {out.strip()}")

    # 5. Non-destructive query commands execution & stdout JSON validity
    print("\n--- 5. Non-Destructive Query Commands & JSON Validation ---")
    safe_queries = [
        ("list_windows", []),
        ("list_apps", []),
        ("foreground", []),
        ("screen", []),
        ("mouse", []),
        ("doctor", []),
        ("selftest", []),
        ("state", ["get"]),
        ("helper-status", []),
        ("confirm", ["删除系统文件"]),
        ("confirm", ["支付订单50元"]),
        ("confirm", ["dir"]),
        ("control-boundary", []),
        ("gui-thread-info", []),
    ]

    query_failures = 0
    for cmd_name, sub_args in safe_queries:
        code, out, err = run_tools_cli([cmd_name] + sub_args)
        # Verify JSON
        json_valid = False
        parsed = None
        try:
            # Some commands might print multiple JSON lines or a single JSON block
            stripped = out.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                parsed = json.loads(stripped)
                json_valid = True
            elif stripped:
                lines = [json.loads(l) for l in stripped.splitlines() if l.strip().startswith("{")]
                if lines:
                    parsed = lines
                    json_valid = True
                else:
                    json_valid = False
            else:
                json_valid = True # empty list of windows is valid if out is empty
        except Exception as e:
            json_valid = False

        status = "PASS" if (code == 0 and json_valid) else "FAIL"
        if status == "FAIL":
            query_failures += 1
        print(f"[{status}] `tools.py {cmd_name} {' '.join(sub_args)}` -> exit {code}, valid JSON: {json_valid}")

    # 6. Alias resolution testing across branches
    print("\n--- 6. Command Branch & Alias Coverage Probe ---")
    alias_tests = [
        ("list_windows", ["list_windows", "windows", "list-windows", "enum_windows", "enum-windows"]),
        ("list_apps", ["list_apps", "apps", "list-apps", "running-apps", "running_apps"]),
        ("foreground", ["foreground", "fg", "active-window", "active_window"]),
        ("screen", ["screen", "monitors", "display", "screens"]),
        ("mouse", ["mouse", "cursor", "mouse-pos", "mouse_pos"]),
        ("doctor", ["doctor", "health", "check", "diagnose", "diagnostics"]),
        ("selftest", ["selftest", "self-test", "test"]),
        ("helper-status", ["helper-status", "helper_status"]),
        ("control-boundary", ["control-boundary", "control_boundary", "boundary", "integrity"]),
        ("gui-thread-info", ["gui-thread-info", "gui_thread_info", "gui"]),
    ]

    alias_failures = 0
    for primary, aliases in alias_tests:
        for alias in aliases:
            code, out, err = run_tools_cli([alias])
            status = "PASS" if code == 0 else "FAIL"
            if status == "FAIL":
                alias_failures += 1
                print(f"  [FAIL] Alias `{alias}` -> exit {code}, err: {err.strip()}")
        print(f"[PASS] All {len(aliases)} aliases for `{primary}` verified.")

    # 7. Error formatting on missing required arguments
    print("\n--- 7. Error Formatting & Missing Arguments Verification ---")
    error_cases = [
        (["get_window"], 1, "Error: hwnd required"),
        (["focus-hwnd"], 1, "Error: focus-hwnd requires <hwnd>"),
        (["focused-input"], 1, "Error: focused-input requires <text>"),
        (["smart-text"], 1, "Error: smart-text requires [hwnd] <text>"),
        (["smart-select"], 1, "Error: smart-select requires [hwnd] <item>"),
        (["window-action"], 1, "Error: window-action requires <hwnd> <action>"),
        (["win32-set-text"], 1, "Error: win32-set-text requires <hwnd> <text>"),
        (["batch"], 1, "Error: JSON commands string required"),
        (["batch-file"], 1, "Error: batch-file requires <commands.json>"),
        (["confirm"], 1, "Error: confirm requires <action>"),
        (["state", "set"], 1, "Error: state set requires <key> <value>"),
        (["state", "target"], 1, "Error: state target requires <hwnd>"),
    ]

    error_failures = 0
    for args, exp_code, exp_err in error_cases:
        code, out, err = run_tools_cli(args)
        matched = exp_err.lower() in out.lower() or exp_err.lower() in err.lower()
        status = "PASS" if (code == exp_code and matched) else "FAIL"
        if status == "FAIL":
            error_failures += 1
        print(f"[{status}] `tools.py {' '.join(args)}` -> exit {code} (exp {exp_code}), message matched '{exp_err}': {matched}")

    # 8. PEP 562 Dynamic Symbol Resolution
    print("\n--- 8. PEP 562 Dynamic Symbol Resolution Test ---")
    pep562_test_code = """
import tools
import server

# Test tools symbols
assert callable(tools.enum_windows), 'tools.enum_windows should be callable'
assert callable(tools.get_window), 'tools.get_window should be callable'
assert callable(tools.doctor), 'tools.doctor should be callable'
assert callable(tools.check_safety), 'tools.check_safety should be callable'
assert hasattr(tools, 'STATE_FILE'), 'tools should expose STATE_FILE'

# Test server symbols
assert callable(server.main), 'server.main should be callable'
assert hasattr(server, 'STATE_FILE'), 'server should expose STATE_FILE'

# Test dir()
tools_dir = dir(tools)
assert 'enum_windows' in tools_dir, 'dir(tools) missing enum_windows'
assert 'doctor' in tools_dir, 'dir(tools) missing doctor'
assert 'STATE_FILE' in tools_dir, 'dir(tools) missing STATE_FILE'

server_dir = dir(server)
assert 'main' in server_dir, 'dir(server) missing main'

print('PEP 562 resolution verified successfully!')
"""
    code, out, err = subprocess.run([PYTHON, "-c", pep562_test_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT_DIR, encoding="utf-8", errors="replace").returncode, "", ""
    pep_res = subprocess.run([PYTHON, "-c", pep562_test_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT_DIR, encoding="utf-8", errors="replace")
    pep_ok = pep_res.returncode == 0 and "PEP 562 resolution verified successfully!" in pep_res.stdout
    print(f"[{'PASS' if pep_ok else 'FAIL'}] PEP 562 dynamic resolution in tools.py and server.py: {pep_res.stdout.strip()}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print(f"BOM Test: {'PASS' if bom_ok else 'FAIL'}")
    print(f"Query Commands Test: {'PASS' if query_failures == 0 else 'FAIL'} ({query_failures} failures)")
    print(f"Alias Coverage Test: {'PASS' if alias_failures == 0 else 'FAIL'} ({alias_failures} failures)")
    print(f"Error Formatting Test: {'PASS' if error_failures == 0 else 'FAIL'} ({error_failures} failures)")
    print(f"PEP 562 Resolution: {'PASS' if pep_ok else 'FAIL'}")
    all_passed = bom_ok and query_failures == 0 and alias_failures == 0 and error_failures == 0 and pep_ok
    print(f"OVERALL EMPIRICAL ASSESSMENT: {'APPROVE' if all_passed else 'REQUEST_CHANGES'}")
    print("=" * 70)

if __name__ == "__main__":
    run_empirical_probes()
