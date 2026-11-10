param([switch]$Stop, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location -LiteralPath $root
if (-not $env:EDUMATRIX_VENV_PATH) {
    $env:EDUMATRIX_VENV_PATH = Join-Path $env:LOCALAPPDATA 'EduMatrix\current\.venv'
}
$python = Join-Path $env:EDUMATRIX_VENV_PATH 'Scripts\python.exe'
$env:EDUMATRIX_DB_PATH = Join-Path $root 'edumatrix.db'
$env:EDUMATRIX_RELOAD = '0'
$env:EDUMATRIX_SANDBOX_MODE = 'trusted_local'
$env:PYTHONUTF8 = '1'
if ($Stop) {
    if (-not (Test-Path -LiteralPath $python)) { Write-Host 'No runtime installed.'; exit 0 }
    & $python (Join-Path $root 'run.py') --stop
    exit $LASTEXITCODE
}
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'Creating Python 3.11 environment...'
    $bootstrap = Get-Command py -ErrorAction SilentlyContinue
    if ($bootstrap) {
        & $bootstrap.Source -3.11 -m venv $env:EDUMATRIX_VENV_PATH
    } else {
        $bootstrap = Get-Command python -ErrorAction SilentlyContinue
        if (-not $bootstrap) { throw 'Install Python 3.11 from https://www.python.org/downloads/ and run this launcher again.' }
        & $bootstrap.Source -m venv $env:EDUMATRIX_VENV_PATH
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
$envFile = Join-Path $root '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $root '.env.runtime.template') -Destination $envFile
}
$envText = [System.IO.File]::ReadAllText($envFile)
if (-not $env:EDUMATRIX_AUTH_SECRET_KEY -and $envText -notmatch '(?m)^\s*EDUMATRIX_AUTH_SECRET_KEY\s*=\s*[^\s\r\n]+') {
    # Keep this installation's sessions valid across normal restarts.
    $random = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($random)
    $generator.Dispose()
    $setting = 'EDUMATRIX_AUTH_SECRET_KEY=' + [Convert]::ToBase64String($random)
    $envText = [regex]::Replace($envText, '(?m)^\s*EDUMATRIX_AUTH_SECRET_KEY\s*=[^\r\n]*', '')
    [System.IO.File]::WriteAllText($envFile, $envText.TrimEnd() + "`r`n" + $setting + "`r`n", (New-Object System.Text.UTF8Encoding $false))
}
$requirements = Join-Path $root 'requirements-lock.txt'
if (-not (Test-Path -LiteralPath $requirements)) { $requirements = Join-Path $root 'requirements-runtime.txt' }
& $python (Join-Path $root 'scripts\runtime_preflight.py') *> $null
$ready = $LASTEXITCODE -eq 0
& $python -m pip check *> $null
if (-not $ready -or $LASTEXITCODE -ne 0) {
    Write-Host 'Installing required packages...'
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the connection and run again.' }
}
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
& $python (Join-Path $root 'scripts\runtime_preflight.py')
if ($LASTEXITCODE -ne 0) { throw 'Runtime check failed.' }
$runtime = Join-Path $root '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$instanceFile = Join-Path $runtime 'instance.json'
$service = $null
if (Test-Path -LiteralPath $instanceFile) {
    $instance = Get-Content -LiteralPath $instanceFile -Raw | ConvertFrom-Json
    $running = Get-CimInstance Win32_Process -Filter "ProcessId = $($instance.pid)" -ErrorAction SilentlyContinue
    if ($running -and $running.CommandLine.Contains((Join-Path $root 'run.py'))) {
        $service = Get-Process -Id $instance.pid
    }
}
$port = 8000
foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*EDUMATRIX_PORT\s*=\s*(\d+)\s*$') { $port = [int]$Matches[1] }
}
if ($env:EDUMATRIX_PORT) { $port = [int]$env:EDUMATRIX_PORT }
if ($service) { $port = [int]$instance.port }
$url = "http://127.0.0.1:$port/"
if (-not $service) {
    $service = Start-Process -FilePath $python -ArgumentList @('-u','-X','utf8',('"' + (Join-Path $root 'run.py') + '"')) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'server.log') -RedirectStandardError (Join-Path $runtime 'server-error.log')
}
$nextProgress = Get-Date
while ($true) {
    $service.Refresh()
    if ($service.HasExited) { throw "Service exited. See $runtime\server-error.log" }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ($url + 'api/health') -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            Write-Host "EduMatrix is ready: $url"
            if (-not $NoBrowser) { Start-Process $url }
            exit 0
        }
    } catch { }
    if ((Get-Date) -ge $nextProgress) {
        Write-Host 'Preparing courses and local search. Keep this window open; the first start can take several minutes.'
        $nextProgress = (Get-Date).AddSeconds(30)
    }
    Start-Sleep -Seconds 1
}
