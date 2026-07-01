param(
  [string]$OutputDir = "outputs",
  [string]$ConfigPath = "followup_mail_config.json"
)

$ErrorActionPreference = "Stop"
$logPath = Join-Path $OutputDir "followup_mail_send_log.txt"

function Write-Log {
  param([string]$Message)
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
  Write-Host $line
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  throw "Config file was not found: $ConfigPath"
}

$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$webAppUrl = [string]$config.WebAppUrl
$to = [string]$config.To
$token = [string]$config.Token
$dashboardUrl = [string]$config.DashboardUrl

if ([string]::IsNullOrWhiteSpace($webAppUrl)) {
  throw "WebAppUrl is empty in $ConfigPath"
}
if ([string]::IsNullOrWhiteSpace($to)) {
  throw "To is empty in $ConfigPath"
}
if ([string]::IsNullOrWhiteSpace($dashboardUrl)) {
  $dashboardUrl = "https://yujitkg.github.io/BANSO-dashboard/?v=mail"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
Set-Content -LiteralPath $logPath -Value "Follow-up mail send log" -Encoding UTF8
Write-Log "Config loaded. To=$to"
Write-Log "WebAppUrl starts with script.google.com: $($webAppUrl.StartsWith('https://script.google.com/macros/s/'))"
Write-Log "DashboardUrl=$dashboardUrl"
Write-Log "Sending GET trigger to Google Apps Script..."

$curl = Join-Path $env:SystemRoot "System32\curl.exe"
$uri = $webAppUrl + "?action=sendDashboard&to=" + [uri]::EscapeDataString($to) + "&token=" + [uri]::EscapeDataString($token) + "&dashboardUrl=" + [uri]::EscapeDataString($dashboardUrl)
$curlOutput = & $curl -L --http1.1 --max-time 60 --silent --show-error $uri 2>&1
$exitCode = $LASTEXITCODE
Write-Log "curl exit code: $exitCode"
Write-Log "Response: $curlOutput"

if ($exitCode -ne 0) {
  throw "curl failed with exit code $exitCode"
}

$response = $curlOutput | ConvertFrom-Json
if (-not $response.ok) {
  throw "GAS mail send failed: $($response.error)"
}
if ($response.action -ne "sendDashboard") {
  throw "GAS endpoint is reachable, but sendDashboard action is not active. Please paste the latest gas/followup_mailer.gs into Apps Script and deploy a new version."
}

Write-Log "Follow-up mail sent via Google Apps Script to $to"
