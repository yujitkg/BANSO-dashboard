@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_followup_mail_gas.ps1" -ConfigPath "%~dp0followup_mail_config.json"
if errorlevel 1 (
  echo.
  echo GAS mail test failed. Please check gas_mail_test_log.txt.
  exit /b 1
)

echo.
echo GAS mail test completed. Please check your inbox.
