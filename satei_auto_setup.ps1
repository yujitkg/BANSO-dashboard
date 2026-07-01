$ErrorActionPreference = "Stop"
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $repoDir "satei_auto_config.json"
$examplePath = Join-Path $repoDir "satei_auto_config.example.json"

if (-not (Test-Path -LiteralPath $configPath)) {
  Copy-Item -LiteralPath $examplePath -Destination $configPath
}

Write-Host ""
Write-Host "Created/checked: $configPath"
Write-Host "Open this file and set WebAppUrl and Token."
Write-Host ""
Write-Host "After setup, run:"
Write-Host "  査定データ取得から更新.bat"
