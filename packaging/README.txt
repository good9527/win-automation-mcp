Desktop Control Portable
========================

This folder is self-contained. Keep the folder together and copy it anywhere on a
64-bit Windows 10/11 computer. Python does not need to be installed.

FIRST USE
---------
1. Double-click INSTALL-AI-SKILL.cmd.
2. For an MCP-compatible AI application, import or merge:
     config\mcp-config.generated.json
3. Restart the AI application.

The installer also places the portable skill in the standard Codex, Agents, and
Claude-style user skill folders and sets DESKTOP_CONTROL_HOME for CLI fallback.

ENTRY POINTS
------------
START-MCP.cmd       stdio MCP server for AI applications
CONTROL.cmd         command-line and JSON automation interface
START-HELPER.cmd    optional visible normal-integrity helper
DOCTOR.cmd          dependency and capability report
INSTALL-AI-SKILL.cmd install skill and generate integration configuration

GENERIC MCP CONFIG
------------------
The generated JSON directly uses runtime\python.exe with app\server.py as its
argument for maximum client compatibility. START-MCP.cmd provides the same stdio
server for clients that accept command scripts.

LIMITS
------
Only AI applications that support MCP, local command tools, plugins, or skills can
call the engine directly. Applications with no extension or tool interface cannot
import any external computer-control engine.

Tesseract is optional and is not bundled. Windows OCR remains available as a
fallback. Elevated applications may require approval through the elevated helper.
