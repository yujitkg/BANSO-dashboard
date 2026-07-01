@echo off
setlocal
cd /d "%~dp0"
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dashboard_update.ps1" -RepoDir "%REPO%" *> "%REPO%\dashboard_update.log"
if errorlevel 1 (
  echo.
  echo Dashboard update failed. Please check the message above.
  echo Log: "%REPO%\dashboard_update.log"
  exit /b 1
)

echo.
echo Done.
