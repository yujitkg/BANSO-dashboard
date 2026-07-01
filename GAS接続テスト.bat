@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_gas_endpoint.ps1" -ConfigPath "%~dp0followup_mail_config.json"
if errorlevel 1 (
  echo.
  echo GAS endpoint test failed. Please check gas_endpoint_test_log.txt.
  exit /b 1
)

echo.
echo GAS endpoint test completed.
