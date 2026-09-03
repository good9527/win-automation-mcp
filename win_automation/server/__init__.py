"""
Server submodule for win-automation-mcp.
"""

from .app import create_app, server, main
from .compact_tools import (
    COMPACT_TOOLS,
    COMPACT_TOOL_SCHEMAS,
    get_compact_tool_schemas,
    calculate_serialized_schema_size,
)

__all__ = [
    "create_app",
    "server",
    "main",
    "COMPACT_TOOLS",
    "COMPACT_TOOL_SCHEMAS",
    "get_compact_tool_schemas",
    "calculate_serialized_schema_size",
]
