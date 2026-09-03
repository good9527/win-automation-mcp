@echo off
setlocal
title Desktop Control Helper
set "ROOT=%~dp0"
set "DESKTOP_CONTROL_HOME=%ROOT%"
set "PYTHONPATH=%ROOT%app"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%ROOT%runtime\python.exe" "%ROOT%app\helper.py" --port 18765
pause
