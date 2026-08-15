param(
    [string]$CodexHome = ''
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'integrations\codex\skills\nexus-ai-pc-bridge'
$aiPcRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ([string]::IsNullOrWhiteSpace($CodexHome)) {
    $CodexHome = Join-Path $aiPcRoot 'data\codex'
}
$skillsRoot = Join-Path $CodexHome 'skills'
$target = Join-Path $skillsRoot 'nexus-ai-pc-bridge'

if (-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md'))) {
    throw "Skill source is incomplete: $source"
}

New-Item -ItemType Directory -Path $skillsRoot -Force | Out-Null
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'SKILL.md') -Destination $target -Force
Copy-Item -LiteralPath (Join-Path $source 'agents') -Destination $target -Recurse -Force
Copy-Item -LiteralPath (Join-Path $source 'references') -Destination $target -Recurse -Force

Write-Output "Installed nexus-ai-pc-bridge to $target"
