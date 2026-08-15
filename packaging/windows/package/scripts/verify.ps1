param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "Nexus-AI-PC"),
    [switch]$StartIfNeeded
)

$ErrorActionPreference = "Stop"
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$marker = Join-Path $InstallRoot ".nexus-ai-pc-install.json"
$python = Join-Path $InstallRoot "app\dashboard\.venv\Scripts\python.exe"
$start = Join-Path $InstallRoot "app\dashboard\start.ps1"

if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    throw "Installation marker is missing: $marker"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment is missing: $python"
}

$installMarker = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ([bool]$installMarker.deeptutor) {
    $deeptutorPython = Join-Path $InstallRoot "tools\deeptutor\.venv-cli\Scripts\python.exe"
    $deeptutorMarker = Join-Path $InstallRoot "tools\deeptutor\.nexus-ai-pc-deeptutor.json"
    if (-not (Test-Path -LiteralPath $deeptutorPython -PathType Leaf)) {
        throw "DeepTutor Python environment is missing: $deeptutorPython"
    }
    if (-not (Test-Path -LiteralPath $deeptutorMarker -PathType Leaf)) {
        throw "DeepTutor installation marker is missing: $deeptutorMarker"
    }
    & $deeptutorPython -c "import deeptutor_cli"
    if ($LASTEXITCODE -ne 0) {
        throw "DeepTutor CLI import verification failed."
    }
}

& $python --version
if ($LASTEXITCODE -ne 0) {
    throw "The bundled Python environment is not runnable."
}

$healthUri = "http://127.0.0.1:8765/api/health"
try {
    $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 3
}
catch {
    if (-not $StartIfNeeded) {
        throw "Dashboard is not running. Start it before verification."
    }
    & $start -NoBrowser
    $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 5
}

if ($health.status -ne "ok") {
    throw "Health endpoint returned an unexpected status."
}

$settings = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/settings" -TimeoutSec 5
$expected = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$actual = [System.IO.Path]::GetFullPath([string]$settings.data_path).TrimEnd('\')
if (-not $actual.Equals($expected, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Runtime data path mismatch. Expected '$expected', got '$actual'."
}

$databasePath = Join-Path $InstallRoot "data\database\ai-pc.sqlite3"
$checkScript = @'
import sqlite3
import sys
from pathlib import Path
database_uri = Path(sys.argv[1]).resolve().as_posix()
con = sqlite3.connect(f"file:{database_uri}?mode=ro", uri=True)
try:
    result = con.execute("PRAGMA quick_check").fetchone()[0]
finally:
    con.close()
if result != "ok":
    raise SystemExit(f"database quick_check failed: {result}")
print("Database quick_check: ok")
'@
$checkScript | & $python - $databasePath
if ($LASTEXITCODE -ne 0) {
    throw "Database integrity verification failed."
}

$listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener -and $listener.LocalAddress -notin @("127.0.0.1", "::1")) {
    throw "Dashboard is listening outside the local loopback interface."
}

Write-Host "Verification passed: health, data root, database integrity, and loopback binding." -ForegroundColor Green
