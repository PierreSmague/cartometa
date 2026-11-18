# Installs (or removes) the daily `cartometa-carmeta sync` on Windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-carmeta-sync.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-carmeta-sync.ps1 -Uninstall
#
# The job only ever writes under data\cache\carmeta\ and logs\: it can run
# while you work on any branch.
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$TaskName = 'Cartometa-Carmeta-Sync'
$Repo = Split-Path -Parent $PSScriptRoot

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
if ($Uninstall) {
    Write-Host "Removed $TaskName."
    exit 0
}

$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) { throw 'uv not found in PATH: install it first.' }
New-Item -ItemType Directory -Force -Path (Join-Path $Repo 'logs') | Out-Null

$Action = New-ScheduledTaskAction -Execute $Uv -Argument 'run cartometa-carmeta sync' -WorkingDirectory $Repo
$Trigger = New-ScheduledTaskTrigger -Daily -At 9:00
# StartWhenAvailable: a machine that was off at 09:00 runs the job once it is on.
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description 'Mirrors the carmeta repository and refreshes the Cartometa analysis.' | Out-Null

Write-Host "Installed $TaskName: every day at 09:00, from $Repo."
Write-Host "Run it now:   Start-ScheduledTask -TaskName $TaskName"
Write-Host "Its trace:    $Repo\logs\carmeta-sync.log"
