@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

notepad "%~dp0gas\followup_mailer.gs"

