@echo off
cd /d "%~dp0"
set "PY=C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
echo Updating dashboard...
"%PY%" analyze_assessment.py --root "%USERPROFILE%\Desktop\ç∏íËÉfÅ[É^" --output outputs --no-open
if errorlevel 1 (
  echo.
  echo Update failed. Please check the error message above.
  pause
  exit /b 1
)
echo.
echo Done: index.html has been updated.
echo Next: Commit and Push in GitHub Desktop.
pause
