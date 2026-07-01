param(
  [string]$ConfigPath = "followup_mail_config.json"
)

$ErrorActionPreference = "Stop"
$logPath = "gas_mail_test_log.txt"

function Write-Log {
  param([string]$Message)
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
  Write-Host $line
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

Set-Content -LiteralPath $logPath -Value "GAS mail test log" -Encoding UTF8

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  throw "Config file was not found: $ConfigPath"
}

$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$webAppUrl = [string]$config.WebAppUrl
$to = [string]$config.To
$token = [string]$config.Token

if ([string]::IsNullOrWhiteSpace($webAppUrl)) {
  throw "WebAppUrl is empty in $ConfigPath"
}
if ([string]::IsNullOrWhiteSpace($to)) {
  throw "To is empty in $ConfigPath"
}

Write-Log "Sending dummy test mail to $to"
Write-Log "WebAppUrl starts with script.google.com: $($webAppUrl.StartsWith('https://script.google.com/macros/s/'))"
Write-Log "Sending GET trigger..."

$curl = Join-Path $env:SystemRoot "System32\curl.exe"
$uri = $webAppUrl + "?action=sendTest&to=" + [uri]::EscapeDataString($to) + "&token=" + [uri]::EscapeDataString($token)
$curlOutput = & $curl -L --http1.1 --max-time 60 --silent --show-error $uri 2>&1
$exitCode = $LASTEXITCODE
Write-Log "curl exit code: $exitCode"
Write-Log "Response: $curlOutput"

if ($exitCode -ne 0) {
  throw "curl failed with exit code $exitCode"
}

$response = $curlOutput | ConvertFrom-Json
if (-not $response.ok) {
  throw "GAS test mail failed: $($response.error)"
}
if ($response.action -ne "sendTest") {
  throw "GAS endpoint is reachable, but sendTest action is not active. Please paste the latest gas/followup_mailer.gs into Apps Script and deploy a new version."
}

Write-Log "GAS test mail sent."
