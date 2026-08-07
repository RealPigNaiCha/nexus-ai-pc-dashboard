$ErrorActionPreference = "Stop"
$connections = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue

if (-not $connections) {
    Write-Output "NextChat is already stopped."
    exit 0
}

$ownerPids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($ownerPid in $ownerPids) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid"
    if (-not $process -or $process.CommandLine -notmatch "next start") {
        throw "Port 3000 is owned by another process. Refusing to stop PID $ownerPid."
    }
    Stop-Process -Id $ownerPid
}

Write-Output "NextChat stopped."
