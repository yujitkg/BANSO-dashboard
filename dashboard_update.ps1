param(
  [string]$RepoDir = $PSScriptRoot,
  [string]$MailMonth = ""
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $RepoDir
$mailSent = $false

$python = "C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  $python = "python"
}

$assessmentDataFolderName = "$([char]0x67FB)$([char]0x5B9A)$([char]0x30C7)$([char]0x30FC)$([char]0x30BF)"
$dataRoot = Join-Path (Join-Path $env:USERPROFILE "Desktop") $assessmentDataFolderName

Write-Host "Updating dashboard..."
& $python "analyze_assessment.py" --root $dataRoot --output "outputs" --no-open
if ($LASTEXITCODE -ne 0) {
  throw "Dashboard update failed."
}

Write-Host ""
Write-Host "Staging dashboard files..."
$dashboardFiles = @(
  "index.html",
  "analyze_assessment.py",
  ".gitignore",
  "GAS_SETUP.md",
  "followup_mail_config.example.json",
  "dashboard_update.bat",
  "dashboard_update.ps1",
  "copy_gas_code.bat",
  "copy_gas_code.ps1",
  "mail_automation_check.bat",
  "setup_followup_mail_config.ps1",
  "send_followup_email_gas.ps1",
  "test_followup_mail_gas.ps1",
  "test_gas_endpoint.ps1",
  "gas/followup_mailer.gs"
)

foreach ($file in $dashboardFiles) {
  if (Test-Path -LiteralPath $file) {
    & git add -- $file
    if ($LASTEXITCODE -ne 0) {
      throw "Git add failed: $file"
    }
  }
}

Get-ChildItem -LiteralPath $RepoDir -Filter "*.bat" -File | ForEach-Object {
  & git add -- $_.FullName
  if ($LASTEXITCODE -ne 0) {
    throw "Git add failed: $($_.FullName)"
  }
}

& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
  $stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
  Write-Host "Committing changes..."
  & git commit -m "dashboard auto update $stamp"
} else {
  Write-Host "No dashboard file changes to commit."
}

Write-Host ""
Write-Host "Pushing to GitHub..."
& git push origin master
if ($LASTEXITCODE -ne 0) {
  throw "Git push failed. Please check authentication."
}

if (Test-Path -LiteralPath "outputs\followup_high_value_unconverted.csv") {
  Write-Host ""
  Write-Host "Sending follow-up email via Google Apps Script..."
  $mailArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $RepoDir "send_followup_email_gas.ps1"),
    "-OutputDir", (Join-Path $RepoDir "outputs"),
    "-ConfigPath", (Join-Path $RepoDir "followup_mail_config.json")
  )
  if (-not [string]::IsNullOrWhiteSpace($MailMonth)) {
    $mailArgs += @("-Month", $MailMonth)
  }
  & powershell @mailArgs
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "GAS email send failed. Opening draft instead..."
    $draft = Join-Path $RepoDir "outputs\followup_high_value_unconverted.eml"
    if (Test-Path -LiteralPath $draft) {
      Start-Process -FilePath $draft
    }
  } else {
    $mailSent = $true
  }
}

Write-Host ""
if ($mailSent) {
  Write-Host "Done: dashboard has been updated, mail was sent, and GitHub was pushed."
} else {
  Write-Host "Done: dashboard has been updated and GitHub was pushed. Mail was not sent automatically; draft was opened instead."
}
Write-Host "GitHub Pages may take a few minutes to refresh. Use Ctrl+F5 on the page."
