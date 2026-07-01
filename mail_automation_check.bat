@echo off
setlocal
cd /d "%~dp0"

echo Checking GAS endpoint version...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_gas_endpoint.ps1" -ConfigPath "%~dp0followup_mail_config.json"
if errorlevel 1 (
  echo.
  echo GAS endpoint check failed.
  echo 1. Run copy_gas_code.bat
  echo 2. Paste into Apps Script
  echo 3. Save and deploy a new version
  echo 4. Run this check again
  exit /b 1
)

echo.
echo Sending test mail...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_followup_mail_gas.ps1" -ConfigPath "%~dp0followup_mail_config.json"
if errorlevel 1 (
  echo.
  echo Test mail failed. Please check gas_mail_test_log.txt.
  exit /b 1
)

echo.
echo Mail automation check completed.
echo If the test mail arrived, run dashboard_update.bat or the Japanese dashboard update batch.
