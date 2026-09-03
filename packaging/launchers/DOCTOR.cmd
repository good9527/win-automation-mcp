@echo off
setlocal
title Desktop Control Portable - Doctor
set "ROOT=%~dp0"
call "%ROOT%CONTROL.cmd" doctor
echo.
echo Doctor finished. Review the report above.
pause
