@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo FAIL: .venv is missing. Run install_and_run.bat first.
    exit /b 1
)
"%PYTHON%" "%ROOT%scripts\runtime_preflight.py"
if errorlevel 1 exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health -TimeoutSec 3).StatusCode } catch { exit 1 }"
if errorlevel 1 (
    echo INFO: backend is not running. Runtime dependencies are installed.
    exit /b 0
)
echo PASS: backend health endpoint is available.
endlocal
