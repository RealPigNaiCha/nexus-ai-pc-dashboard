param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$aiPcRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$nextchatDir = Join-Path $aiPcRoot "tools\nextchat"
$baseUri = "http://127.0.0.1:3000"

if (Get-Command node -ErrorAction SilentlyContinue) {
    $node = (Get-Command node).Source
}
else {
    $node = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
}

if (-not (Test-Path -LiteralPath $node)) {
    throw "Node.js not found. Install Node.js LTS or restore the Codex bundled runtime."
}
if (-not (Test-Path -LiteralPath (Join-Path $nextchatDir ".next\BUILD_ID"))) {
    throw "NextChat is not built yet. Run the NextChat build first (see README)."
}

function Test-NextChat {
    try {
        $response = Invoke-WebRequest -Uri "$baseUri/" -TimeoutSec 2 -UseBasicParsing
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

if (Test-NextChat) {
    Write-Output "NextChat is already running at $baseUri"
}
else {
    $env:BASE_URL = "http://127.0.0.1:8765"
    $env:OPENAI_API_KEY = "local-nextchat-placeholder"
    $env:HIDE_USER_API_KEY = "1"
    $env:CUSTOM_MODELS = "-all,+reasoning=Reasoning,+fast=Fast"
    $env:DEFAULT_MODEL = "reasoning"
    $env:HOSTNAME = "127.0.0.1"
    $env:PORT = "3000"

    $logDir = Join-Path $aiPcRoot "logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdout = Join-Path $logDir "nextchat.out.log"
    $stderr = Join-Path $logDir "nextchat.err.log"
    Remove-Item -LiteralPath $stdout, $stderr -ErrorAction SilentlyContinue

    Start-Process -FilePath $node `
        -ArgumentList @("node_modules\next\dist\bin\next", "start", "-p", "3000") `
        -WorkingDirectory $nextchatDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr | Out-Null

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if (Test-NextChat) {
            break
        }
    }
    if (-not (Test-NextChat)) {
        throw "NextChat did not become healthy. Check $stderr"
    }
    Write-Output "NextChat started at $baseUri"
}

if (-not $NoBrowser) {
    Start-Process $baseUri
}
