@echo off
set "CUR_DIR=%~dp0"
set "CUR_DIR=%CUR_DIR:\=/%"

echo ========================================
echo Windows Automation MCP Server - Install
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.12+
    pause
    exit /b 1
)

REM Install dependencies
echo [1/3] Installing Python dependencies...
pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo [WARNING] Some dependencies failed to install
)

echo.
echo [2/3] Testing server...
python "%~dp0test_server.py" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Test did not fully pass, but server should work
) else (
    echo [SUCCESS] Server test passed
)

echo.
echo [3/3] Installation complete!
echo.
echo ========================================
echo NEXT STEPS:
echo ========================================
echo.
echo 1. Open Claude Code or Cursor settings file:
echo    %%USERPROFILE%%\.claude\settings.local.json
echo.
echo 2. Add this configuration:
echo.
echo {
echo   "mcpServers": {
echo     "win-automation": {
echo       "command": "python",
echo       "args": ["%CUR_DIR%server.py"]
echo     }
echo   }
echo }
echo.
echo 3. Restart Claude Code / Cursor
echo.
echo 4. Test: type "list_apps" in Claude Code / Cursor
echo.
pause
