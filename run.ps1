$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$aiPcRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
Set-Location $projectRoot

if (-not $env:AI_PC_ROOT) {
    $env:AI_PC_ROOT = $aiPcRoot
}

if (-not $env:AI_PC_DB_PATH) {
    $env:AI_PC_DB_PATH = Join-Path $aiPcRoot "data\database\ai-pc.sqlite3"
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv run uvicorn backend.app:app --host 127.0.0.1 --port 8765
    exit $LASTEXITCODE
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
    exit $LASTEXITCODE
}

throw "uv or the project .venv was not found. Install uv, then run: uv sync --dev"
