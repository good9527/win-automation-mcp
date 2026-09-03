@echo off
setlocal
set "ROOT=%~dp0"
set "DESKTOP_CONTROL_HOME=%ROOT%"
set "PYTHONPATH=%ROOT%app"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%ROOT%runtime\python.exe" "%ROOT%app\tools.py" %*
