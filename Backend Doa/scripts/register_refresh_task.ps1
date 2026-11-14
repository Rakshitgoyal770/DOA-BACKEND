# scripts/register_refresh_task.ps1
# Registers (or replaces) the daily Windows scheduled task that keeps the data up to date:
#     python -m features.sync.refresh     (backup, data sync, identity re-check, index sync, index check)
#
# Run once, from any folder:      powershell -ExecutionPolicy Bypass -File scripts\register_refresh_task.ps1
# Another time of day:            ... -File scripts\register_refresh_task.ps1 -At 21:30
# Remove the task:                Unregister-ScheduledTask -TaskName "DAO data refresh" -Confirm:$false
# Run it right now:               Start-ScheduledTask -TaskName "DAO data refresh"
# How the last run went:          logs\last_refresh.json   ("ok", "problems", "warnings")
#
# The task runs as the current user, only while that user is logged in (no password is stored).
# If the computer was off at the scheduled time, the task runs as soon as it is on again.
param(
    [string]$At = "10:00",
    [string]$TaskName = "DAO data refresh"
)

$project = Split-Path -Parent $PSScriptRoot                      # the folder that holds features\, db\, .venv\
$python = Join-Path $project ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python not found at $python (create the virtual environment first)" }

$action = New-ScheduledTaskAction -Execute $python -Argument "-m features.sync.refresh" -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "DAO governance data: backup, Snapshot + Discourse sync, identity re-check, search index sync and check." `
    -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo |
    Select-Object TaskName, NextRunTime, LastRunTime, LastTaskResult | Format-List
