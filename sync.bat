@echo off
echo ====================================================
echo             EduMatrix Git Auto-Sync Tool
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

if not exist ".git" (
    echo [STATUS] Initializing git repository...
    git init
    git remote add origin https://github.com/jkl-66/edumatrix.git
    git branch -M main
)

echo [1/3] Staging changes...
git add .

echo [2/3] Committing changes...
git commit -m "Auto-sync"

echo [3/3] Pushing to GitHub...
git push origin main

if %errorlevel% equ 0 (
    echo.
    echo ====================================================
    echo SUCCESS: Code pushed to GitHub successfully!
    echo ====================================================
) else (
    echo.
    echo ====================================================
    echo FAILED: Git push failed. Please check credentials/network.
    echo ====================================================
)
echo.
pause
