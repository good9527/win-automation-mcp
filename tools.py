"""
Windows Desktop Automation CLI (Backward-compatible thin wrapper).
Delegates CLI execution to win_automation.cli and provides dynamic symbol resolution via PEP 562.
"""
from __future__ import annotations

import sys
from typing import Any

from win_automation.cli import main
from win_automation.compat import resolve_tools_symbol, get_tools_all_symbols


def __getattr__(name: str) -> Any:
    val = resolve_tools_symbol(name)
    if val is not None:
        return val
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> list[str]:
    return get_tools_all_symbols(list(globals().keys()))


if __name__ == "__main__":
    main()
