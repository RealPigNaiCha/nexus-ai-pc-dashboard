param(
    [switch]$NoBrowser,
    [switch]$WithChat
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

    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if (Test-Dashboard) {
            break
        }
    }
}

if (-not (Test-Dashboard)) {
    $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        throw "端口 8765 已被进程 $($listener.OwningProcess) 占用，但健康检查未通过。请先停止旧服务或检查该进程，再重新启动。日志：C:\AI-PC\logs\dashboard.stderr.log"
    }
    throw "AI-PC Dashboard 未在 120 秒内通过健康检查。请查看日志：C:\AI-PC\logs\dashboard.stderr.log"
}

if (-not $NoBrowser) {
    Start-Process $baseUri
}

if ($WithChat) {
    $nextChatScript = Join-Path $projectRoot "start-nextchat.ps1"
    & $nextChatScript -NoBrowser:$NoBrowser
}
