@echo off
REM kill_port.bat — 强制释放指定端口（默认 8000 和 8001）
REM 用法: kill_port.bat [端口号]

set PORT=%~1
if "%PORT%"=="" set PORT=8000 8001

for %%p in (%PORT%) do (
    echo [Kill] 正在释放端口 %%p ...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%%p ^| findstr LISTENING') do (
        if not "%%a"=="0" (
            echo [Kill] 结束进程 PID %%a
            taskkill /F /PID %%a >nul 2>&1
        )
    )
)

echo [Kill] 端口已释放，请启动服务。
