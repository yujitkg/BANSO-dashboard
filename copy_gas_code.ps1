param(
  [string]$SourcePath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SourcePath)) {
  $SourcePath = Join-Path $PSScriptRoot "gas\followup_mailer.gs"
}

if (-not (Test-Path -LiteralPath $SourcePath)) {
  throw "GAS source file was not found: $SourcePath"
}

$code = Get-Content -LiteralPath $SourcePath -Raw -Encoding UTF8
Set-Clipboard -Value $code

Write-Host "GAS code copied to clipboard."
Write-Host "Paste it into Google Apps Script, save, then deploy a new version."
