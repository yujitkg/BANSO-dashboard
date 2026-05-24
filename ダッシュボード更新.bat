@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo Updating dashboard...
"%PY%" analyze_assessment.py --root "%USERPROFILE%\Desktop\査定データ" --output outputs --no-open
if errorlevel 1 (
  echo.
  echo Update failed. Please check the error message above.
  pause
  exit /b 1
)

echo.
echo Staging dashboard files...
git add index.html analyze_assessment.py "ダッシュボード更新.bat"
if errorlevel 1 (
  echo.
  echo Git add failed. Please check GitHub Desktop or git settings.
  pause
  exit /b 1
)

git diff --cached --quiet
if errorlevel 1 (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "STAMP=%%i"
  echo Committing changes...
  git commit -m "ダッシュボード自動更新 %STAMP%"
  if errorlevel 1 (
    echo.
    echo Git commit failed. Please check the error message above.
    pause
    exit /b 1
  )
) else (
  echo No dashboard file changes to commit.
)

echo.
echo Pushing to GitHub...
git push origin master
if errorlevel 1 (
  echo.
  echo Push failed. Please open GitHub Desktop and check authentication.
  pause
  exit /b 1
)

echo.
echo Done: dashboard has been updated and pushed to GitHub.
echo GitHub Pages may take a few minutes to refresh. Use Ctrl+F5 on the page.
pause
