param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$taskName = "AI-PC Dashboard"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $projectRoot "start.ps1"

if ($Install) {
    $powerShellPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $startScript + '" -NoBrowser'
    $action = New-ScheduledTaskAction -Execute $powerShellPath -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Start the local-only AI-PC Dashboard after user logon (optional)." -Force | Out-Null
    Write-Output "Auto-start installed (optional). Run this script again without -Install to disable it."
    exit 0
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Auto-start disabled."
}
else {
    Write-Output "Auto-start is not enabled."
}

Write-Output "Daily start: double-click C:\AI-PC\start-ai-pc.bat or run app\dashboard\start.ps1."
