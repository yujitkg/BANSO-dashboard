@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_followup_mail_config.ps1" -ConfigPath "%~dp0followup_mail_config.json"
if errorlevel 1 (
  echo.
  echo Setup failed. Please check the message above.
  exit /b 1
)

echo.
echo Setup completed.
