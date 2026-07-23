@echo off
setlocal
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root=[regex]::Escape((Resolve-Path '%ROOT%').Path); $items=Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match 'run.py' -and $_.CommandLine -match $root }; foreach($item in $items){ Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue; Write-Output ('Stopped PID ' + $item.ProcessId) }"
echo EduMatrix services stopped.
endlocal
