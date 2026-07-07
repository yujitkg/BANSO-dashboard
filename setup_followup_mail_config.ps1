param(
  [string]$ConfigPath = "followup_mail_config.json"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Follow-up mail config setup"
Write-Host ""

$webAppUrl = Read-Host "Google Apps Script Web app URL"
if ([string]::IsNullOrWhiteSpace($webAppUrl)) {
  throw "Web app URL is required."
}

$to = Read-Host "Recipient email address [renraku@y-takumi.jp]"
if ([string]::IsNullOrWhiteSpace($to)) {
  $to = "renraku@y-takumi.jp"
}

$token = Read-Host "Token"
if ([string]::IsNullOrWhiteSpace($token)) {
  throw "Token is required."
}

$dashboardUrl = Read-Host "Dashboard URL [https://yujitkg.github.io/BANSO-dashboard/?v=mail]"
if ([string]::IsNullOrWhiteSpace($dashboardUrl)) {
  $dashboardUrl = "https://yujitkg.github.io/BANSO-dashboard/?v=mail"
}

$sourceUrl = Read-Host "Dashboard source URL [https://raw.githubusercontent.com/yujitkg/BANSO-dashboard/master/index.html]"
if ([string]::IsNullOrWhiteSpace($sourceUrl)) {
  $sourceUrl = "https://raw.githubusercontent.com/yujitkg/BANSO-dashboard/master/index.html"
}

$config = [ordered]@{
  WebAppUrl = $webAppUrl.Trim()
  To = $to.Trim()
  Token = $token.Trim()
  DashboardUrl = $dashboardUrl.Trim()
  SourceUrl = $sourceUrl.Trim()
}

$json = $config | ConvertTo-Json -Depth 3
$resolvedConfigPath = if ([System.IO.Path]::IsPathRooted($ConfigPath)) {
  $ConfigPath
} else {
  Join-Path (Resolve-Path ".").Path $ConfigPath
}
[System.IO.File]::WriteAllText($resolvedConfigPath, $json, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "Created: $resolvedConfigPath"
Write-Host "Setup completed. You can now run the dashboard update batch."
