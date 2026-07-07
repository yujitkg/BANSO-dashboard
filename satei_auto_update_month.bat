@echo off
setlocal
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"
echo.
echo Fetch BANSO assessment data for a selected month, then send the follow-up mail for that month.
echo.
set /p TARGET_MONTH=Enter target month YYYY-MM, example 2026-06: 
if "%TARGET_MONTH%"=="" (
  echo.
  echo Target month is empty.
  exit /b 1
)
echo.
echo Running. Please keep this window open until it finishes.
echo Log: "%REPO%\satei_auto_update_%TARGET_MONTH%.log"
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\download_satei_csv_and_update.ps1" -ConfigPath "%REPO%\satei_auto_config.json" -Month "%TARGET_MONTH%" > "%REPO%\satei_auto_update_%TARGET_MONTH%.log" 2>&1
if errorlevel 1 (
  echo.
  echo Satei auto update failed.
  echo Log: "%REPO%\satei_auto_update_%TARGET_MONTH%.log"
  exit /b 1
)
echo.
echo Done.
echo You can close this window manually.
