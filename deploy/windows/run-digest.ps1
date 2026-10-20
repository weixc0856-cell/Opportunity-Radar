$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectRoot
$logDir = Join-Path $ProjectRoot "reports"
New-Item -ItemType Directory -Force $logDir | Out-Null
$runLog = Join-Path $logDir "scheduler-run.log"
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Write-RunLog([string]$Message) {
  [IO.File]::AppendAllText($runLog, "[$(Get-Date -Format o)] $Message`r`n", $utf8)
}

Write-RunLog "Starting Opportunity Radar"

# Ensure FreshRSS's Compose services are started. Docker Desktop/engine must already be running.
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
  $dockerOut = (& cmd /c "docker compose up -d 2>&1" | Out-String).Trim()
  if ($dockerOut) { Write-RunLog "docker compose up -d`r`n$dockerOut" }
  if ($LASTEXITCODE -ne 0) {
    Write-RunLog "ERROR: docker compose up -d failed; check Docker Desktop."
    exit $LASTEXITCODE
  }
} else {
  Write-RunLog "ERROR: docker command not found."
  exit 1
}

# Start the local llama-server if it is not already healthy. Edit start-model.ps1 defaults first.
$modelScript = Join-Path $ProjectRoot "deploy\windows\start-model.ps1"
$modelOut = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $modelScript 2>&1 | Out-String).Trim()
if ($modelOut) { Write-RunLog "start-model`r`n$modelOut" }
if ($LASTEXITCODE -ne 0) {
  Write-RunLog "ERROR: local llama-server failed to start."
  exit $LASTEXITCODE
}

# Run the digest and write raw UTF-8 output, avoiding PowerShell's mixed-encoding redirection.
$env:PYTHONIOENCODING = 'utf-8'
$cliOut = Join-Path $logDir "cli-run.log"
$cliErr = Join-Path $logDir "cli-run.err.log"
$venv = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $venv) {
  $proc = Start-Process -FilePath $venv -ArgumentList @('-m','opportunity_radar.cli') -NoNewWindow -Wait -PassThru -RedirectStandardOutput $cliOut -RedirectStandardError $cliErr
} else {
  $proc = Start-Process -FilePath "py" -ArgumentList @('-3','-m','opportunity_radar.cli') -NoNewWindow -Wait -PassThru -RedirectStandardOutput $cliOut -RedirectStandardError $cliErr
}
$code = $proc.ExitCode
Write-RunLog "CLI exit code $code (stdout: reports\cli-run.log; stderr: reports\cli-run.err.log)"
Write-RunLog "Finished Opportunity Radar with exit code $code"
exit $code
