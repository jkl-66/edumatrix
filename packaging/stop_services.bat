@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1" -Stop
if errorlevel 1 pause
endlocal
