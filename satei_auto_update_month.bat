@echo off
setlocal
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"
set /p TARGET_MONTH=YYYY-MMを入力してください 例 2026-06: 
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\download_satei_csv_and_update.ps1" -ConfigPath "%REPO%\satei_auto_config.json" -Month "%TARGET_MONTH%" *> "%REPO%\satei_auto_update_%TARGET_MONTH%.log"
if errorlevel 1 (
  echo.
  echo Satei auto update failed.
  echo Log: "%REPO%\satei_auto_update_%TARGET_MONTH%.log"
  exit /b 1
)
echo.
echo Done.
