$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..\..")
$venv = Resolve-Path (Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe") -ErrorAction SilentlyContinue
if ($venv) { $python = $venv.Path; $pre = @() } else { $python = "py"; $pre = @("-3") }
# unittest logs to stderr; in PowerShell 5.1 that raises NativeCommandError under -Stop,
# so rely on $LASTEXITCODE instead.
& $python @pre -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python @pre -m opportunity_radar.cli --dry-run --sample
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
