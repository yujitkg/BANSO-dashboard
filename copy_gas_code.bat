@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0copy_gas_code.ps1" -SourcePath "%~dp0gas\followup_mailer.gs"
if errorlevel 1 (
  echo.
  echo Copy failed. Please open gas\followup_mailer.gs and copy it manually.
  exit /b 1
)

echo.
echo Done.
