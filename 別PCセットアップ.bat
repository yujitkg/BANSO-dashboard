@echo off
setlocal
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"
cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\setup_other_pc.ps1"
