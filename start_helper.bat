@echo off
title Win Automation Helper Server
echo ========================================
echo  Windows Automation Helper Server
echo ========================================
echo.
echo Starting helper server on port 18765...
echo Press Ctrl+C to stop.
echo.
python "%~dp0helper.py" --port 18765
pause
