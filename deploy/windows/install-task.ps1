param([string]$TaskName="OpportunityRadarDaily",[string]$ProjectPath=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,[string]$StartTime="08:00")
$ErrorActionPreference="Stop"
$scriptPath=Join-Path $ProjectPath "deploy\windows\run-digest.ps1"
$action=New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger=New-ScheduledTaskTrigger -Daily -At $StartTime
# Power settings are set explicitly. The defaults left both battery switches ON, and on
# 2026-10-29 and 2026-11-01 the running task was terminated while llama-server was still
# starting (scheduler-run.log has "start-model" but no "CLI exit code"). A daily digest that
# silently does not run is worse than one that runs late. Logon type is deliberately left at
# Interactive: changing it changes the security context, which is a separate decision.
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 60) `
  -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Run Opportunity Radar daily digest" -Force | Out-Null
# Read the task back: the registered object, not this script, is the source of truth.
$registered=Get-ScheduledTask -TaskName $TaskName
$applied=$registered.Settings
Write-Host "Created task $TaskName at $StartTime. Run interactively once before unattended use."
Write-Host ("Registered settings: ExecutionTimeLimit={0} StopIfGoingOnBatteries={1} AllowStartIfOnBatteries={2} StartWhenAvailable={3}" -f `
  $applied.ExecutionTimeLimit, $applied.StopIfGoingOnBatteries, $applied.DisallowStartIfOnBatteries, $applied.StartWhenAvailable)
