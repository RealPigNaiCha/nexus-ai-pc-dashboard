[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [Parameter(Mandatory = $true)]
    [string]$UvExecutable,
    [string]$Repository = "https://github.com/HKUDS/DeepTutor.git",
    [string]$Tag = "v1.5.9",
    [string]$Ref = "37c3db6df7e886aee4f61c97ec5e618b8ab379e8",
    [string]$ExpectedVersion = "1.5.9"
)

$ErrorActionPreference = "Stop"

function Invoke-Uv([string[]]$Arguments) {
    & $UvExecutable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv command failed with exit code ${LASTEXITCODE}: uv $($Arguments -join ' ')"
    }
}

function Assert-TemporaryPath([string]$Candidate, [string]$TempRoot) {
    $resolvedCandidate = [System.IO.Path]::GetFullPath($Candidate).TrimEnd('\')
    $resolvedTempRoot = [System.IO.Path]::GetFullPath($TempRoot).TrimEnd('\')
    if (-not $resolvedCandidate.StartsWith($resolvedTempRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the temporary workspace: $resolvedCandidate"
    }
}

$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$deeptutorRoot = Join-Path $InstallRoot "tools\deeptutor"
$venvRoot = Join-Path $deeptutorRoot ".venv-cli"
$python = Join-Path $venvRoot "Scripts\python.exe"
$markerPath = Join-Path $deeptutorRoot ".nexus-ai-pc-deeptutor.json"

if (-not (Test-Path -LiteralPath $UvExecutable -PathType Leaf)) {
    throw "The bundled uv executable is missing: $UvExecutable"
}

$gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $gitCommand) {
    throw "Git for Windows is required to install DeepTutor from its official source. Install it from https://git-scm.com/download/win and run the installer again."
}

if ((Test-Path -LiteralPath $markerPath -PathType Leaf) -and (Test-Path -LiteralPath $python -PathType Leaf)) {
    try {
        $existing = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
        if ([string]$existing.commit -eq $Ref -and [string]$existing.version -eq $ExpectedVersion) {
            Invoke-Uv @("pip", "check", "--python", $python)
            Write-Host "DeepTutor $ExpectedVersion is already installed from the verified commit." -ForegroundColor Green
            return
        }
    }
    catch {
        Write-Warning "Existing DeepTutor marker could not be validated; a fresh managed install will be attempted."
    }
}

if (Test-Path -LiteralPath $deeptutorRoot -PathType Container) {
    $existingItems = @(Get-ChildItem -LiteralPath $deeptutorRoot -Force -ErrorAction Stop)
    if ($existingItems.Count -gt 0 -and -not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "The DeepTutor target is not an installation managed by Nexus AI-PC: $deeptutorRoot"
    }
}

$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\')
$staging = Join-Path $tempRoot ("nexus-deeptutor-" + [guid]::NewGuid().ToString('N'))
$checkout = Join-Path $staging "source"
$createdVenv = $false

try {
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    Write-Host "Fetching DeepTutor from the official repository at $Ref..." -ForegroundColor Cyan
    & $gitCommand.Source clone --depth 1 --no-tags --branch $Tag $Repository $checkout
    if ($LASTEXITCODE -ne 0) {
        throw "DeepTutor source download failed. Check GitHub connectivity and proxy settings."
    }

    $actualCommit = (& $gitCommand.Source -C $checkout rev-parse HEAD).Trim()
    if ($actualCommit -ne $Ref) {
        throw "DeepTutor source commit mismatch. Expected $Ref, got $actualCommit."
    }

    New-Item -ItemType Directory -Path $deeptutorRoot -Force | Out-Null
    if (-not (Test-Path -LiteralPath $venvRoot -PathType Container)) {
        Invoke-Uv @("venv", "--python", "3.12", $venvRoot)
        $createdVenv = $true
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "DeepTutor Python environment was not created: $python"
    }

    # The Dashboard uses the CLI adapter, not DeepTutor's optional web server.
    # Keeping this small runtime set avoids pulling the server authentication
    # stack and its unrelated transitive dependencies into the friend install.
    Invoke-Uv @("pip", "install", "--python", $python, "$checkout\packaging\deeptutor-cli")
    Invoke-Uv @("pip", "install", "--python", $python, "loguru==0.7.3", "json-repair==0.63.2", "croniter==6.2.4")
    Invoke-Uv @("pip", "check", "--python", $python)

    $installedVersion = (& $python -c "import importlib.metadata as m; print(m.version('deeptutor-cli'))").Trim()
    if ($installedVersion -ne $ExpectedVersion) {
        throw "DeepTutor version mismatch. Expected $ExpectedVersion, got $installedVersion."
    }
    & $python -c "import deeptutor_cli"
    if ($LASTEXITCODE -ne 0) {
        throw "DeepTutor CLI import verification failed."
    }

    $marker = [ordered]@{
        product = "DeepTutor CLI"
        version = $installedVersion
        repository = $Repository
        tag = $Tag
        commit = $actualCommit
        install_type = "non-editable-cli"
        runtime_dependencies = @("loguru==0.7.3", "json-repair==0.63.2", "croniter==6.2.4")
        installed_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $marker | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $markerPath -Encoding UTF8
    Write-Host "DeepTutor $installedVersion installed and verified." -ForegroundColor Green
}
catch {
    if ($createdVenv -and (Test-Path -LiteralPath $venvRoot -PathType Container)) {
        Remove-Item -LiteralPath $venvRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $staging -PathType Container) {
        Assert-TemporaryPath $staging $tempRoot
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}
