param(
  [string]$ConfigPath = "followup_mail_config.json"
)

$ErrorActionPreference = "Stop"
$logPath = "gas_endpoint_test_log.txt"

function Write-Log {
  param([string]$Message)
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
  Write-Host $line
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

Set-Content -LiteralPath $logPath -Value "GAS endpoint test log" -Encoding UTF8

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  throw "Config file was not found: $ConfigPath"
}

$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$webAppUrl = [string]$config.WebAppUrl

Write-Log "Testing GET endpoint..."
Write-Log "WebAppUrl starts with script.google.com: $($webAppUrl.StartsWith('https://script.google.com/macros/s/'))"

$curl = Join-Path $env:SystemRoot "System32\curl.exe"
$curlOutput = & $curl -L --max-time 30 --silent --show-error $webAppUrl 2>&1
$exitCode = $LASTEXITCODE
Write-Log "curl exit code: $exitCode"
Write-Log "Response: $curlOutput"

if ($exitCode -ne 0) {
  throw "curl failed with exit code $exitCode"
}

$response = $curlOutput | ConvertFrom-Json
if (-not $response.ok) {
  throw "GAS endpoint returned error: $($response.error)"
}
if ($response.version -ne "2026-06-30-get-mail-v2") {
  throw "GAS endpoint is reachable, but the deployed code is old. Please paste the latest gas/followup_mailer.gs and deploy a new version."
}

Write-Log "GAS endpoint has the latest mail actions."
