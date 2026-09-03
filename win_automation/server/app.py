"""
Windows Automation MCP Server implementation.
Supports dual-profile tool registration:
- Compact profile (default): 9 high-intent composite tools (<35,000 chars schema)
- Expert profile (WIN_AUTO_PROFILE=expert): full granular toolset
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

try:
    from mcp.server.fastmcp import FastMCP, Context, Image
except ImportError:
    FastMCP = None
    Context = None
    Image = None

from win_automation.server.compact_tools import (
    COMPACT_TOOLS,
    COMPACT_TOOL_SCHEMAS,
    get_compact_tool_schemas,
    calculate_serialized_schema_size,
    register_compact_tools,
)
from win_automation.server.expert_tools import register_expert_tools


def create_app(name: str = "windows-automation") -> Any:
    """Create and initialize the FastMCP application with appropriate profile."""
    if FastMCP is None:
        return None
    app = FastMCP(
        name,
        instructions="Windows Desktop Automation MCP Server providing GUI interaction, observation, OCR, and accessibility inspection.",
    )
    profile = os.environ.get("WIN_AUTO_PROFILE", "compact").strip().lower()
    if profile == "expert":
        register_expert_tools(app)
    else:
        register_compact_tools(app)
    return app


server = create_app() if FastMCP is not None else None


def main() -> None:
    """Main entry point for running the MCP server."""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

    if server is not None:
        server.run(transport="stdio")
    else:
        print("Error: FastMCP is not available. Please install mcp[cli].")
        sys.exit(1)


if __name__ == "__main__":
    main()
