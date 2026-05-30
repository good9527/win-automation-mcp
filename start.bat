@echo off
title win-automation-mcp Dual-Core Launcher
color 0B
echo ===================================================
echo   🌟 win-automation-mcp Dual-Core Launcher 🌟
echo ===================================================
echo.

:: Check python installation
where python >nul 2>nul
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python was not found in your system PATH!
    echo Please download and install Python from https://www.python.org/
    pause
    exit /b 1
)

echo [INFO] Checking and installing Python dependencies...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Failed to install dependencies automatically.
    echo Please run manually: pip install pyautogui pillow comtypes mcp
) else (
    echo [SUCCESS] Dependencies are verified!
)
echo.

echo [INFO] Launching Background Input Helper Daemon (helper.py)...
start /b python helper.py --port 18765
echo [SUCCESS] Background Helper Daemon started on port 18765!
echo.

echo [INFO] Exposing StdIO MCP Server (server.py)...
echo To use this in Claude Desktop or Cursor, run:
echo.
python install.bat
echo.
echo ===================================================
echo   MCP Server is running! Press Ctrl+C to stop.
echo ===================================================
python server.py
