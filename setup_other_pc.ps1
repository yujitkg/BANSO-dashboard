$ErrorActionPreference = "Stop"
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "BANSO dashboard setup for another PC"
Write-Host ""

$python = Get-Command python -ErrorAction SilentlyContinue
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $python -and -not $py) {
  Write-Host "WARNING: Python was not found. Install Python 3 and enable Add python.exe to PATH."
} else {
  Write-Host "Python check: OK"
}

Write-Host ""
Write-Host "Step 1: setup BANSO data fetch config"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoDir "satei_auto_setup.ps1")

Write-Host ""
Write-Host "Step 2: setup follow-up mail config"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoDir "setup_followup_mail_config.ps1") -ConfigPath (Join-Path $repoDir "followup_mail_config.json")

Write-Host ""
Write-Host "Setup completed."
Write-Host "Use these batches:"
Write-Host "  satei_auto_update.bat"
Write-Host "  satei_auto_update_month.bat"
