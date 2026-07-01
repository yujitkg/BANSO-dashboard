@echo off
setlocal
set "REPO=%~dp0"
set "REPO=%REPO:~0,-1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO%\copy_satei_export_gas_code.ps1"
if errorlevel 1 (
  echo.
  echo Copy failed.
  exit /b 1
)
echo.
echo Done.
