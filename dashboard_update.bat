@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dashboard_update.ps1" -RepoDir "%~dp0"
if errorlevel 1 (
  echo.
  echo Dashboard update failed. Please check the message above.
  pause
  exit /b 1
)

echo.
echo Done.
pause
