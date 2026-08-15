param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "Nexus-AI-PC"),
    [switch]$SkipBrowser,
    [switch]$SkipModel,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$packageRoot = Split-Path -Parent $PSScriptRoot
$payloadRoot = Join-Path $packageRoot "payload"
$manifestPath = Join-Path $packageRoot "manifest.json"
$markerName = ".nexus-ai-pc-install.json"

function Write-Step([string]$Message) {
    Write-Host "[Nexus AI-PC] $Message" -ForegroundColor Cyan
}

function Assert-LastExit([string]$Action) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed with exit code $LASTEXITCODE."
    }
}

function Resolve-SafeInstallRoot([string]$PathValue) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        throw "InstallRoot cannot be empty."
    }
    $fullPath = [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\')
    $forbidden = @(
        [System.IO.Path]::GetPathRoot($fullPath).TrimEnd('\'),
        [Environment]::GetFolderPath("UserProfile").TrimEnd('\'),
        $env:LOCALAPPDATA.TrimEnd('\')
    )
    if ($forbidden -contains $fullPath) {
        throw "Refusing to install into a broad system or profile directory: $fullPath"
    }
    return $fullPath
}

function Test-PackageManifest {
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Package manifest is missing: $manifestPath"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $manifest.files) {
        $relative = [string]$entry.path
        $candidate = [System.IO.Path]::GetFullPath((Join-Path $packageRoot $relative))
        if (-not $candidate.StartsWith($packageRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Manifest contains an unsafe path: $relative"
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "Package file is missing: $relative"
        }
        $actual = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash
        if ($actual -ne [string]$entry.sha256) {
            throw "Package checksum mismatch: $relative"
        }
    }
    return $manifest
}

function Copy-DirectoryContents([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
    }
}

function Write-InstalledLaunchers([string]$Root) {
    $utf8 = New-Object System.Text.UTF8Encoding($true)
    $start = @'
@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\dashboard\start.ps1"
if errorlevel 1 pause
endlocal
'@
    $stop = @'
@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\dashboard\stop.ps1"
if errorlevel 1 pause
endlocal
'@
    $verify = @'
@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify.ps1" -InstallRoot "%~dp0"
pause
endlocal
'@
    $uninstall = @'
@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall.ps1" -InstallRoot "%~dp0"
pause
endlocal
'@
    [System.IO.File]::WriteAllText((Join-Path $Root "start-ai-pc.bat"), $start, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $Root "stop-ai-pc.bat"), $stop, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $Root "verify-installation.bat"), $verify, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $Root "uninstall-ai-pc.bat"), $uninstall, $utf8)
}

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "Nexus AI-PC requires 64-bit Windows 10 or Windows 11."
}

$InstallRoot = Resolve-SafeInstallRoot $InstallRoot
$manifest = Test-PackageManifest
$markerPath = Join-Path $InstallRoot $markerName

if (Test-Path -LiteralPath $InstallRoot) {
    $existingItems = @(Get-ChildItem -LiteralPath $InstallRoot -Force -ErrorAction Stop)
    if ($existingItems.Count -gt 0 -and -not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "The target directory is not empty and is not a Nexus AI-PC installation: $InstallRoot"
    }
}

Write-Step "Verified package $($manifest.version)."
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null

$existingStop = Join-Path $InstallRoot "app\dashboard\stop.ps1"
if (Test-Path -LiteralPath $existingStop -PathType Leaf) {
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $existingStop
    }
    catch {
        Write-Warning "The existing service could not be stopped automatically: $($_.Exception.Message)"
    }
}

Write-Step "Copying application files. Existing user data is preserved."
$appRoot = Join-Path $InstallRoot "app\dashboard"
$workspaceRoot = Join-Path $InstallRoot "workspaces\ai-pc-dashboard"
Copy-DirectoryContents (Join-Path $payloadRoot "app\dashboard") $appRoot
Copy-DirectoryContents (Join-Path $payloadRoot "app\dashboard") $workspaceRoot
Copy-DirectoryContents (Join-Path $payloadRoot "vault") (Join-Path $InstallRoot "vault")
Copy-DirectoryContents (Join-Path $packageRoot "scripts") (Join-Path $InstallRoot "scripts")
Copy-DirectoryContents (Join-Path $packageRoot "docs") (Join-Path $InstallRoot "docs")

foreach ($relative in @(
    "data\database",
    "data\library\original",
    "data\library\parsed",
    "data\index",
    "data\agent\tasks",
    "data\zotero",
    "data\codex",
    "backups\database",
    "logs",
    "tools\uv"
)) {
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot $relative) -Force | Out-Null
}

$uvSource = Join-Path $payloadRoot "tools\uv\uv.exe"
$uvTarget = Join-Path $InstallRoot "tools\uv\uv.exe"
Copy-Item -LiteralPath $uvSource -Destination $uvTarget -Force

$marker = @{
    product = "Nexus AI-PC"
    version = [string]$manifest.version
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
    install_root = $InstallRoot
} | ConvertTo-Json
Set-Content -LiteralPath $markerPath -Value $marker -Encoding UTF8
Write-InstalledLaunchers $InstallRoot

Write-Step "Installing managed Python 3.12 and locked runtime dependencies."
& $uvTarget python install 3.12
Assert-LastExit "Python installation"
Push-Location $appRoot
try {
    & $uvTarget sync --frozen --no-dev --python 3.12
    Assert-LastExit "Dependency installation"
}
finally {
    Pop-Location
}

$python = Join-Path $appRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The project virtual environment was not created."
}

if (-not $SkipBrowser) {
    Write-Step "Installing the Chromium runtime for controlled browser automation."
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Chromium installation failed. The Dashboard remains usable; browser automation will be unavailable."
    }
}

if (-not $SkipModel) {
    Write-Step "Downloading and checking the local BGE embedding model."
    & $python (Join-Path $packageRoot "scripts\preload-model.py") $InstallRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "The embedding model could not be downloaded. Keyword search will still work."
    }
}

try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "Nexus AI-PC.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $InstallRoot "start-ai-pc.bat"
    $shortcut.WorkingDirectory = $InstallRoot
    $shortcut.Description = "Start the local Nexus AI-PC Dashboard"
    $shortcut.Save()
}
catch {
    Write-Warning "Desktop shortcut creation failed: $($_.Exception.Message)"
}

Write-Step "Running installation verification."
& (Join-Path $InstallRoot "scripts\verify.ps1") -InstallRoot $InstallRoot -StartIfNeeded

if ($NoStart) {
    & (Join-Path $appRoot "stop.ps1")
}
else {
    & (Join-Path $appRoot "start.ps1")
}

Write-Host "Installed to: $InstallRoot" -ForegroundColor Green
Write-Host "Dashboard: http://127.0.0.1:8765" -ForegroundColor Green
