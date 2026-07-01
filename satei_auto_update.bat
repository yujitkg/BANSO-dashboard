@echo off
setlocal
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\download_satei_csv_and_update.ps1" -ConfigPath "%REPO%\satei_auto_config.json"
if errorlevel 1 (
  echo.
  echo Satei auto update failed. Please check the message above.
  pause
  exit /b 1
)
echo.
echo Done.
pause
