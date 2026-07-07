$ErrorActionPreference = "Stop"
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $repoDir "satei_auto_config.json"

$defaultDataRoot = Join-Path (Join-Path (Join-Path $env:USERPROFILE "Desktop") "$([char]0x67FB)$([char]0x5B9A)$([char]0x30C7)$([char]0x30FC)$([char]0x30BF)") "data"

Write-Host ""
Write-Host "BANSO satei auto config setup"
Write-Host ""

$webAppUrl = Read-Host "BANSO data GAS Web app URL"
if ([string]::IsNullOrWhiteSpace($webAppUrl)) {
  throw "Web app URL is required."
}

$token = Read-Host "SATEI_EXPORT_TOKEN"
if ([string]::IsNullOrWhiteSpace($token)) {
  throw "Token is required."
}

$dataRoot = Read-Host "Data root [$defaultDataRoot]"
if ([string]::IsNullOrWhiteSpace($dataRoot)) {
  $dataRoot = $defaultDataRoot
}

$config = [ordered]@{
  WebAppUrl = $webAppUrl.Trim()
  Token = $token.Trim()
  Month = ""
  StartFetch = $true
  PollSeconds = 90
  MaxWaitMinutes = 60
  DataRoot = $dataRoot.Trim()
  RepoDir = $repoDir
}

$json = $config | ConvertTo-Json -Depth 3
[System.IO.File]::WriteAllText($configPath, $json, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "Created: $configPath"
