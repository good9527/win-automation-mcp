"""
MCP Server Entry Point (Backward-compatible thin wrapper).
Delegates core execution to win_automation.server and provides dynamic symbol resolution via PEP 562.
"""
from __future__ import annotations

import sys
from typing import Any

from win_automation.server import create_app, server, main
from win_automation.compat import resolve_server_symbol, get_server_all_symbols


def __getattr__(name: str) -> Any:
    val = resolve_server_symbol(name)
    if val is not None:
        return val
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> list[str]:
    return get_server_all_symbols(list(globals().keys()))


if __name__ == "__main__":
    main()
