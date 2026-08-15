param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "Nexus-AI-PC"),
    [switch]$RemoveData,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$marker = Join-Path $InstallRoot ".nexus-ai-pc-install.json"

if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    throw "Refusing to uninstall because the Nexus AI-PC marker is missing: $InstallRoot"
}
$metadata = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ([string]$metadata.product -ne "Nexus AI-PC") {
    throw "Refusing to uninstall because the installation marker is invalid."
}

if (-not $Force) {
    $choice = Read-Host "Uninstall Nexus AI-PC from '$InstallRoot'? Type YES to continue"
    if ($choice -ne "YES") {
        Write-Host "Uninstall cancelled."
        exit 0
    }
}

$stop = Join-Path $InstallRoot "app\dashboard\stop.ps1"
if (Test-Path -LiteralPath $stop -PathType Leaf) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stop
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "The Dashboard service could not be stopped automatically."
    }
}

$task = Get-ScheduledTask -TaskName "AI-PC Dashboard" -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName "AI-PC Dashboard" -Confirm:$false
}

$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Nexus AI-PC.lnk"
Remove-Item -LiteralPath $desktopShortcut -Force -ErrorAction SilentlyContinue

$removeTargets = @("app", "tools", "workspaces", "logs", "scripts", "docs")
foreach ($name in $removeTargets) {
    $target = Join-Path $InstallRoot $name
    $resolved = [System.IO.Path]::GetFullPath($target)
    if ($resolved.StartsWith($InstallRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
    }
}

foreach ($file in @(
    "start-ai-pc.bat",
    "stop-ai-pc.bat",
    "verify-installation.bat",
    "uninstall-ai-pc.bat",
    ".nexus-ai-pc-install.json"
)) {
    Remove-Item -LiteralPath (Join-Path $InstallRoot $file) -Force -ErrorAction SilentlyContinue
}

if ($RemoveData) {
    foreach ($name in @("data", "vault", "backups")) {
        $target = [System.IO.Path]::GetFullPath((Join-Path $InstallRoot $name))
        if ($target.StartsWith($InstallRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $InstallRoot -Force -ErrorAction SilentlyContinue
    Write-Host "Application and user data were removed." -ForegroundColor Green
}
else {
    Write-Host "Application removed. User data was preserved under: $InstallRoot" -ForegroundColor Green
}
