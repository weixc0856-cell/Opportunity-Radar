param([string]$TaskName="OpportunityRadarDaily",[string]$ProjectPath=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,[string]$StartTime="08:00")
$ErrorActionPreference="Stop"
$scriptPath=Join-Path $ProjectPath "deploy\windows\run-digest.ps1"
$action=New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger=New-ScheduledTaskTrigger -Daily -At $StartTime
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Run Opportunity Radar daily digest" -Force
Write-Host "Created task $TaskName at $StartTime. Run interactively once before unattended use."
