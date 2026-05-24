@echo off
echo ====================================================
echo             EduMatrix Git One-Click Pull Tool
echo ====================================================
echo.

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed or not in PATH.
    echo Please install Git from https://git-scm.com/
    echo.
    pause
    exit /b
)

echo [1/1] Fetching and merging remote updates...
git pull origin main --rebase

if %errorlevel% equ 0 (
    echo.
    echo ====================================================
    echo SUCCESS: Code updated successfully from GitHub!
    echo ====================================================
) else (
    echo.
    echo ====================================================
    echo FAILED: Pull failed. Please resolve conflicts or check network.
    echo ====================================================
)
echo.
pause
