@echo off
echo ====================================================
echo             EduMatrix System Quick Launcher
echo ====================================================
echo.

:: 0. Run database fast diagnostic and heal check
echo [0/3] Checking database health and updating cold backup...
python scripts\db_heal.py
echo.

:: 1. Launch the FastAPI backend server in a new window
echo [1/3] Starting Backend Server (FastAPI on Port 8000)...
start "EduMatrix Backend (FastAPI)" cmd /c "cd /d "%~dp0" && python run.py"

:: 2. Launch the Vite frontend dev server in a new window
echo [2/3] Starting Frontend Server (Vite on Port 5173)...
start "EduMatrix Frontend (Vite)" cmd /c "cd /d "%~dp0frontend" && npm run dev"

:: 3. Wait for servers to initialize, then launch the browser
echo [3/3] Launching your browser in 3 seconds...
timeout /t 3 >nul
start http://127.0.0.1:5173

echo.
echo ====================================================
echo SUCCESS: System launched! Check the spawned terminal windows.
echo ====================================================
echo.
timeout /t 2 >nul
exit
