$ErrorActionPreference = "Stop"
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$path = Join-Path $repoDir "gas\satei_csv_export_webapp.gs"

if (-not (Test-Path -LiteralPath $path)) {
  throw "GAS code was not found: $path"
}

Get-Content -LiteralPath $path -Raw -Encoding UTF8 | Set-Clipboard
Write-Host "Satei CSV export GAS code copied to clipboard."
Write-Host "Paste it into the BANSO査定取得 Google Apps Script project, save, and deploy a new version."
