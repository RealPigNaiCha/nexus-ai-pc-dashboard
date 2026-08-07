$ErrorActionPreference = "Stop"
$connections = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue

if (-not $connections) {
    Write-Output "AI-PC Dashboard is already stopped."
    exit 0
}

$ownerPids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($ownerPid in $ownerPids) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid"
    if (-not $process -or $process.CommandLine -notmatch "uvicorn" -or $process.CommandLine -notmatch "backend\.app:app") {
        throw "Port 8765 is owned by another process. Refusing to stop PID $ownerPid."
    }
    Stop-Process -Id $ownerPid
}

Write-Output "AI-PC Dashboard stopped."
