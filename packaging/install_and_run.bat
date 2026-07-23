@echo off
setlocal EnableExtensions
title EduMatrix One-Click Evaluator Launcher

set "ROOT=%~dp0"
cd /d "%ROOT%"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"

echo ============================================================
echo EduMatrix evaluator launcher
echo First run installs Python dependencies from requirements.txt.
echo ============================================================

if not exist "%PYTHON%" (
    set "BOOTSTRAP_PY="
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.11 -c "import sys; print(sys.version)" >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PY=py -3.11"
    )
    if not defined BOOTSTRAP_PY (
        where python >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PY=python"
    )
    if not defined BOOTSTRAP_PY (
        where winget >nul 2>&1
        if not errorlevel 1 (
            echo Python 3.11 was not found. Trying winget automatic installation...
            winget install --id Python.Python.3.11 -e --silent --accept-source-agreements --accept-package-agreements
            if not errorlevel 1 set "BOOTSTRAP_PY=py -3.11"
        )
    )
    if not defined BOOTSTRAP_PY (
        echo [ERROR] Python 3.11 was not found. Install Python 3.11 and retry.
        pause
        exit /b 1
    )
    echo [1/5] Creating local virtual environment...
    %BOOTSTRAP_PY% -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

if not exist "%ROOT%.env" copy /y "%ROOT%.env.runtime.template" "%ROOT%.env" >nul

echo [2/5] Checking Python dependencies...
"%PYTHON%" -c "import fastapi,uvicorn,sqlalchemy,torch,numpy,pandas,sklearn" >nul 2>&1
if errorlevel 1 (
    echo [3/5] Installing dependencies. This may take several minutes...
    "%PYTHON%" -m pip install --upgrade pip
    "%PYTHON%" -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check network access and retry.
        pause
        exit /b 1
    )
) else (
    echo [3/5] Dependencies already installed.
)

echo [4/5] Starting backend and built frontend...
set "EDUMATRIX_ENV=development"
set "EDUMATRIX_RELOAD=0"
set "EDUMATRIX_SANDBOX_MODE=disabled"
start "EduMatrix Backend" "%ComSpec%" /k ""%PYTHON%" "%ROOT%run.py""

echo [5/5] Waiting for http://127.0.0.1:8000 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$deadline=(Get-Date).AddSeconds(60); $ok=$false; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3; if($r.StatusCode -eq 200){$ok=$true; break} } catch {}; Start-Sleep -Seconds 1 }; if(-not $ok){exit 1}"
if errorlevel 1 (
    echo [ERROR] Backend did not become healthy within 60 seconds.
    echo Check the EduMatrix Backend window for the exact error.
    pause
    exit /b 1
)

start "" "http://127.0.0.1:8000/"
echo.
echo SUCCESS: EduMatrix is ready at http://127.0.0.1:8000/
echo Close the backend window or run stop_services.bat to stop it.
echo.
endlocal
exit /b 0
