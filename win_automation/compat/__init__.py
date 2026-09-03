"""
Compatibility layer submodule.
"""

from .resolver import (
    resolve_server_symbol,
    resolve_tools_symbol,
    get_server_all_symbols,
    get_tools_all_symbols,
)

__all__ = [
    "resolve_server_symbol",
    "resolve_tools_symbol",
    "get_server_all_symbols",
    "get_tools_all_symbols",
]
