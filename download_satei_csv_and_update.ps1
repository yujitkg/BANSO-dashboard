param(
  [string]$ConfigPath = "satei_auto_config.json",
  [string]$Month = ""
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
}

function Get-DefaultDataRoot {
  $folderName = "$([char]0x67FB)$([char]0x5B9A)$([char]0x30C7)$([char]0x30FC)$([char]0x30BF)"
  return Join-Path (Join-Path (Join-Path $env:USERPROFILE "Desktop") $folderName) "data"
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
  $ConfigPath = Join-Path $scriptDir $ConfigPath
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  throw "Config file was not found: $ConfigPath. Copy satei_auto_config.example.json to satei_auto_config.json first."
}

$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$webAppUrl = [string]$config.WebAppUrl
$token = [string]$config.Token
$configMonth = [string]$config.Month
$startFetch = $true
if ($null -ne $config.StartFetch) {
  $startFetch = [bool]$config.StartFetch
}
$pollSeconds = 90
if ($null -ne $config.PollSeconds) {
  $pollSeconds = [int]$config.PollSeconds
}
$maxWaitMinutes = 60
if ($null -ne $config.MaxWaitMinutes) {
  $maxWaitMinutes = [int]$config.MaxWaitMinutes
}
$dataRoot = [string]$config.DataRoot
$repoDir = [string]$config.RepoDir

if ([string]::IsNullOrWhiteSpace($Month)) {
  $Month = $configMonth
}
if ([string]::IsNullOrWhiteSpace($Month)) {
  $Month = Get-Date -Format "yyyy-MM"
}
if ($Month -notmatch '^\d{4}-\d{2}$') {
  throw "Month must be YYYY-MM: $Month"
}
if ([string]::IsNullOrWhiteSpace($webAppUrl)) {
  throw "WebAppUrl is empty in $ConfigPath"
}
if (-not $webAppUrl.StartsWith("https://script.google.com/macros/s/")) {
  throw "WebAppUrl must be a Google Apps Script Web App URL. Current value: $webAppUrl"
}
if ([string]::IsNullOrWhiteSpace($token)) {
  throw "Token is empty in $ConfigPath"
}
if ([string]::IsNullOrWhiteSpace($dataRoot)) {
  $dataRoot = Get-DefaultDataRoot
}
if ([string]::IsNullOrWhiteSpace($repoDir)) {
  $repoDir = $scriptDir
}

$targetDir = Join-Path $dataRoot $Month
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

$curl = Join-Path $env:SystemRoot "System32\curl.exe"

function Invoke-GasJson {
  param(
    [string]$Action,
    [int]$TimeoutSeconds = 180
  )

  $uri = $webAppUrl + "?action=" + [uri]::EscapeDataString($Action) + "&month=" + [uri]::EscapeDataString($Month) + "&token=" + [uri]::EscapeDataString($token)
  $text = & $curl -L --http1.1 --max-time $TimeoutSeconds --silent --show-error $uri 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "curl failed for ${Action}: $text"
  }

  $json = $text | ConvertFrom-Json
  if (-not $json.ok) {
    throw "GAS ${Action} failed: $($json.error)"
  }
  return $json
}

if ($startFetch) {
  Write-Step "Starting this month's BANSO data fetch in Google Apps Script..."
  $null = Invoke-GasJson -Action "startThisMonthFetch" -TimeoutSeconds 360

  $deadline = (Get-Date).AddMinutes($maxWaitMinutes)
  while ($true) {
    Start-Sleep -Seconds $pollSeconds
    $progress = Invoke-GasJson -Action "progress" -TimeoutSeconds 60
    Write-Step "Fetch progress: done=$($progress.done) error=$($progress.error) remaining=$($progress.remaining) running=$($progress.running)"

    if ($progress.ready) {
      break
    }
    if ((Get-Date) -gt $deadline) {
      throw "Timed out waiting for GAS detail fetch. Last progress: done=$($progress.done) error=$($progress.error) remaining=$($progress.remaining) running=$($progress.running)"
    }
  }
}

Write-Step "Downloading CSV files from Google Apps Script..."
$uri = $webAppUrl + "?action=exportCsvJson&month=" + [uri]::EscapeDataString($Month) + "&token=" + [uri]::EscapeDataString($token)
$responseText = & $curl -L --http1.1 --max-time 180 --silent --show-error $uri 2>&1
if ($LASTEXITCODE -ne 0) {
  throw "curl failed: $responseText"
}

$response = $responseText | ConvertFrom-Json
if (-not $response.ok) {
  throw "GAS export failed: $($response.error)"
}
if (-not $response.files -or $response.files.Count -eq 0) {
  throw "GAS export returned no files."
}

foreach ($file in $response.files) {
  $name = [string]$file.name
  $contentBase64 = [string]$file.contentBase64
  if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($contentBase64)) {
    throw "Invalid file payload from GAS."
  }

  $safeName = Split-Path -Leaf $name
  $dest = Join-Path $targetDir $safeName
  [System.IO.File]::WriteAllBytes($dest, [Convert]::FromBase64String($contentBase64))
  Write-Step "Saved $safeName to $targetDir"
}

Write-Step "Starting dashboard_update.bat..."
$updateBat = Join-Path $repoDir "dashboard_update.bat"
if (-not (Test-Path -LiteralPath $updateBat)) {
  throw "dashboard_update.bat was not found: $updateBat"
}

Push-Location $repoDir
try {
  & cmd /c "`"$updateBat`""
  if ($LASTEXITCODE -ne 0) {
    throw "dashboard_update.bat failed with exit code $LASTEXITCODE"
  }
} finally {
  Pop-Location
}

Write-Step "Done."
