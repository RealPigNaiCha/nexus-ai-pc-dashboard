param(
    [string]$OutputRoot = "C:\AI-PC\dist",
    [string]$UvExecutable = (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
    [string]$Version = "0.9.0.dev2-portable.2"
)

$ErrorActionPreference = "Stop"
$windowsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent (Split-Path -Parent $windowsRoot)
$templateRoot = Join-Path $windowsRoot "package"
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot).TrimEnd('\')
$releaseName = "Nexus-AI-PC-$Version-Windows-x64"
$stage = Join-Path $OutputRoot $releaseName
$zipPath = Join-Path $OutputRoot ($releaseName + ".zip")

function Assert-SafeOutput([string]$PathValue) {
    $root = [System.IO.Path]::GetPathRoot($PathValue).TrimEnd('\')
    if ($PathValue -eq $root -or $PathValue -eq [Environment]::GetFolderPath("UserProfile").TrimEnd('\')) {
        throw "Unsafe output path: $PathValue"
    }
}

function Copy-DirectoryContents([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
    }
}

Assert-SafeOutput $OutputRoot
if (-not (Test-Path -LiteralPath $UvExecutable -PathType Leaf)) {
    throw "uv executable is missing: $UvExecutable"
}
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
if (Test-Path -LiteralPath $stage) {
    $resolvedStage = [System.IO.Path]::GetFullPath($stage)
    if (-not $resolvedStage.StartsWith($OutputRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean an unsafe staging path: $resolvedStage"
    }
    Remove-Item -LiteralPath $resolvedStage -Recurse -Force
}
Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $stage -Force | Out-Null

Copy-DirectoryContents $templateRoot $stage

$appTarget = Join-Path $stage "payload\app\dashboard"
New-Item -ItemType Directory -Path $appTarget -Force | Out-Null
foreach ($directory in @(".github", "backend", "integrations", "tests")) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $directory) -Destination $appTarget -Recurse -Force
}
foreach ($file in @(
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "app.js",
    "DESIGN.md",
    "LICENSE",
    "index.html",
    "install-codex-skill.ps1",
    "install-startup.ps1",
    "pyproject.toml",
    "run.ps1",
    "start-ai-pc.bat",
    "start.ps1",
    "stop.ps1",
    "styles.css",
    "uv.lock"
)) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $appTarget -Force
}

$vaultTarget = Join-Path $stage "payload\vault"
New-Item -ItemType Directory -Path $vaultTarget -Force | Out-Null
$sourceVault = "C:\AI-PC\vault"
foreach ($directory in @("00-Inbox", "10-Learning", "20-Research", "30-Concepts", "40-Projects", "80-Templates")) {
    $candidate = Join-Path $sourceVault $directory
    if (Test-Path -LiteralPath $candidate -PathType Container) {
        Copy-Item -LiteralPath $candidate -Destination $vaultTarget -Recurse -Force
    }
}
if (Test-Path -LiteralPath (Join-Path $sourceVault "Dashboard.md")) {
    Copy-Item -LiteralPath (Join-Path $sourceVault "Dashboard.md") -Destination $vaultTarget -Force
}

$uvTarget = Join-Path $stage "payload\tools\uv"
New-Item -ItemType Directory -Path $uvTarget -Force | Out-Null
Copy-Item -LiteralPath $UvExecutable -Destination (Join-Path $uvTarget "uv.exe") -Force

$privatePatterns = @(
    "*.sqlite", "*.sqlite3", "*.db", "*.log", "*.pem", "*.key", ".env", ".env.*",
    "*.pkl", "*.pdf", "*.docx", "*.pptx", "*.xlsx", "*.zip"
)
$unexpected = @()
foreach ($pattern in $privatePatterns) {
    $unexpected += Get-ChildItem -LiteralPath (Join-Path $stage "payload") -File -Recurse -Force -Filter $pattern -ErrorAction SilentlyContinue
}
if ($unexpected.Count -gt 0) {
    throw "Sanitization failed; private or generated file found in payload: $($unexpected[0].FullName)"
}

Get-ChildItem -LiteralPath $stage -Directory -Recurse -Force |
    Where-Object { $_.Name -eq "__pycache__" } |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $stage -File -Recurse -Force -Filter "*.pyc" |
    Remove-Item -Force

$files = @()
foreach ($file in Get-ChildItem -LiteralPath $stage -File -Recurse -Force | Sort-Object FullName) {
    if ($file.Name -eq "manifest.json") { continue }
    $relative = $file.FullName.Substring($stage.Length + 1).Replace('\', '/')
    $files += [ordered]@{
        path = $relative
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        size = $file.Length
    }
}
$manifest = [ordered]@{
    product = "Nexus AI-PC"
    version = $Version
    architecture = "windows-x64"
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    files = $files
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stage "manifest.json") -Encoding UTF8

Compress-Archive -LiteralPath $stage -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
$summary = @(
    "File: $(Split-Path -Leaf $zipPath)",
    "SHA256: $zipHash",
    "Size: $((Get-Item -LiteralPath $zipPath).Length)",
    "Version: $Version"
)
$summary | Set-Content -LiteralPath (Join-Path $OutputRoot ($releaseName + ".sha256.txt")) -Encoding UTF8

Write-Host "Release directory: $stage" -ForegroundColor Green
Write-Host "Release ZIP: $zipPath" -ForegroundColor Green
Write-Host "SHA256: $zipHash" -ForegroundColor Green
