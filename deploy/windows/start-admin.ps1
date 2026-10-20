$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found. Run: py -3 -m venv .venv, then install/verify the project first."
}
Set-Location $ProjectRoot
Write-Host "Starting Opportunity Radar local admin at http://127.0.0.1:8090"
Start-Process "http://127.0.0.1:8090"
& $Python -m opportunity_radar.admin_server
