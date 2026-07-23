@echo off
setlocal EnableExtensions
title EduMatrix One-Click Launcher

echo ====================================================
echo             EduMatrix One-Click Launcher
echo ====================================================
echo.

set "PROJECT_ROOT=%~dp0"
set "PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "BACKEND_URL=http://127.0.0.1:8000"
set "FRONTEND_URL=http://127.0.0.1:5173"
cd /d "%PROJECT_ROOT%"

if not exist "%PYTHON%" (
    echo [ERROR] Project virtual environment was not found:
    echo         %PYTHON%
    echo.
    echo Create it and install requirements first.
    pause
    exit /b 1
)

echo [0/5] Verifying project interpreter and scientific dependencies...
"%PYTHON%" "%PROJECT_ROOT%scripts\runtime_preflight.py"
if errorlevel 1 (
    echo [ERROR] Runtime preflight failed. The backend was not started.
    pause
    exit /b 1
)

echo [1/5] Checking database health...
"%PYTHON%" "%PROJECT_ROOT%scripts\db_heal.py"
if errorlevel 1 (
    echo [WARN] Database heal check returned a non-zero code; continuing with startup.
)

echo [2/5] Starting backend with the project .venv...
set "EDUMATRIX_RELOAD=0"
rem Local research/demo mode: enable the restricted child-process runner.
set "EDUMATRIX_SANDBOX_MODE=trusted_local"
start "EduMatrix Backend (project .venv)" "%ComSpec%" /k ""%PYTHON%" "%PROJECT_ROOT%run.py""

echo [3/5] Waiting for backend health check...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$deadline=(Get-Date).AddSeconds(45); $ok=$false; while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri '%BACKEND_URL%/api/health' -TimeoutSec 2; if($r.StatusCode -eq 200){$ok=$true; break} } catch {}; Start-Sleep -Seconds 1 }; if(-not $ok){exit 1}"
if errorlevel 1 (
    echo [ERROR] Backend did not become healthy within 45 seconds.
    echo Check the backend window for the exact error.
    pause
    exit /b 1
)

echo [4/5] Starting frontend...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$connections=@(Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue); if(-not $connections){exit 2}; $project=$false; $foreign=$false; foreach($c in $connections){$p=Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $c.OwningProcess) -ErrorAction SilentlyContinue; $cmd=[string]$p.CommandLine; if(($cmd -match 'edumatrix-main.*frontend') -and ($cmd -match 'vite')){$project=$true}else{$foreign=$true}}; if($project -and -not $foreign){exit 0}; if($foreign){exit 1}; exit 2"
set "FRONTEND_STATE=%ERRORLEVEL%"
if "%FRONTEND_STATE%"=="0" (
    echo [frontend] Existing EduMatrix Vite service detected; reusing port 5173.
    goto frontend_ready
)
if "%FRONTEND_STATE%"=="1" (
    echo [ERROR] Port 5173 is occupied by a non-EduMatrix process.
    pause
    exit /b 1
)
start "EduMatrix Frontend (Vite)" "%ComSpec%" /k "cd /d ""%PROJECT_ROOT%frontend"" && npm run dev -- --host 127.0.0.1"

:frontend_ready
echo [frontend] Ready on %FRONTEND_URL%

echo [5/5] Opening EduMatrix in 3 seconds...
timeout /t 3 >nul
start "" "%FRONTEND_URL%"

echo.
echo ====================================================
echo SUCCESS: EduMatrix backend and frontend are ready.
echo Backend:  %BACKEND_URL%
echo Frontend: %FRONTEND_URL%
echo ====================================================
echo.
endlocal
exit /b 0
