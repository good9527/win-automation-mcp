"""
Comprehensive CLI branch and alias exhaustive probe script.
Tests every registered command branch and alias in win_automation.cli.commands.
"""

import os
import sys
import json
import re
import subprocess
from typing import Dict, List, Any, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PYTHON = sys.executable

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

def run_cmd(args: List[str]) -> Tuple[int, str, str]:
    cmd = [PYTHON, os.path.join(ROOT_DIR, "tools.py")] + args
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT_DIR,
        encoding="utf-8",
        errors="replace"
    )
    return res.returncode, res.stdout, res.stderr

def main():
    branches = extract_cli_command_branches()
    print(f"Discovered {len(branches)} command branches:")

    results = []
    for i, branch in enumerate(branches, 1):
        primary = branch[0]
        aliases = branch
        print(f"\n--- Branch #{i}: {primary} (aliases: {len(aliases)}) ---")

        for alias in aliases:
            # Try running alias with no args or --help or mock args
            code, out, err = run_cmd([alias])
            has_traceback = "Traceback (most recent call last)" in err or "Traceback (most recent call last)" in out
            has_name_error = "NameError:" in err or "NameError:" in out
            has_type_error = "TypeError:" in err or "TypeError:" in out
            has_import_error = "ImportError:" in err or "ImportError:" in out or "ModuleNotFoundError:" in err or "ModuleNotFoundError:" in out

            # Check if stdout contains valid JSON or expected error
            is_json = False
            try:
                stripped = out.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    json.loads(stripped)
                    is_json = True
                elif stripped:
                    for line in stripped.splitlines():
                        if line.strip().startswith("{"):
                            json.loads(line)
                            is_json = True
                            break
            except Exception:
                is_json = False

            crashed = has_traceback or has_name_error or has_type_error or has_import_error
            results.append({
                "branch_id": i,
                "primary": primary,
                "alias": alias,
                "code": code,
                "stdout_snippet": out[:200].replace("\n", " "),
                "stderr_snippet": err[:200].replace("\n", " "),
                "is_json": is_json,
                "crashed": crashed,
            })
            status = "CRASH" if crashed else ("JSON_OK" if is_json else f"EXIT_{code}")
            print(f"  [{status}] `{alias}` -> exit {code} | {err.strip()[:100] if crashed else out.strip()[:100]}")

    crashes = [r for r in results if r["crashed"]]
    print("\n" + "=" * 70)
    print(f"TOTAL COMMANDS/ALIASES PROBED: {len(results)}")
    print(f"TOTAL UNHANDLED CRASHES / EXCEPTIONS: {len(crashes)}")
    if crashes:
        print("\nCRASH SUMMARY:")
        for c in crashes:
            print(f"  Branch #{c['branch_id']} (`{c['alias']}`): {c['stderr_snippet']}")

if __name__ == "__main__":
    main()
