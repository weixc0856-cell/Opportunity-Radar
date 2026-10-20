$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..\..")
$venv = Resolve-Path (Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe") -ErrorAction SilentlyContinue
if ($venv) { & $venv.Path -m opportunity_radar.cli } else { py -3 -m opportunity_radar.cli }
exit $LASTEXITCODE
