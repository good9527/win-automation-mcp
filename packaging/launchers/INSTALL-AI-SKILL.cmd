@echo off
setlocal
title Desktop Control Portable - AI Setup
set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\install_ai_skill.ps1" -PackageRoot "%ROOT%." %*
echo.
pause
