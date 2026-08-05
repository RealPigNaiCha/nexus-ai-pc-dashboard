param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$baseUri = "http://127.0.0.1:8765"
$healthUri = "$baseUri/api/health"

function Test-Dashboard {
    try {
        $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 2
        return $health.status -eq "ok"
    }
    catch {
        return $false
    }
}

if (-not (Test-Dashboard)) {
    $aiPcRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
    $logDir = Join-Path $aiPcRoot "logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null

    $runScript = Join-Path $projectRoot "run.ps1"
    $stdoutLog = Join-Path $logDir "dashboard.stdout.log"
    $stderrLog = Join-Path $logDir "dashboard.stderr.log"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runScript) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog | Out-Null

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if (Test-Dashboard) {
            break
        }
    }
}

if (-not (Test-Dashboard)) {
    throw "AI-PC Dashboard did not become healthy. Check C:\AI-PC\logs\dashboard.stderr.log"
}

if (-not $NoBrowser) {
    Start-Process $baseUri
}
