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

$runId = [guid]::NewGuid().ToString('N').Substring(0,8)
$markerPath = Join-Path $logDir "launcher-inflight.json"
$phase = 'start'
$stepExit = 0
$code = 1

# A launcher stopped from outside (power state, task stop, console close) cannot write its own
# ending. The marker is what separates "the CLI failed" from "the launcher never finished":
# on 2026-10-29 and 2026-11-01 this log had a start and no ending, and the cause was not the CLI.
if (Test-Path $markerPath) {
  $previous = Get-Content -Path $markerPath -Raw -ErrorAction SilentlyContinue
  if ($previous) { Write-RunLog "WARNING: previous launcher left an unfinished run marker: $($previous.Trim())" }
}
('{"run_id":"' + $runId + '","launcher_pid":' + $PID + ',"started_at":"' + (Get-Date -Format o) + '"}') |
  Set-Content -Path $markerPath -Encoding UTF8
Write-RunLog "Starting Opportunity Radar (run $runId, launcher pid $PID)"

try {
  # Ensure FreshRSS's Compose services are started. Docker Desktop/engine must already be running.
  $phase = 'docker'
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) { throw "docker command not found" }
  $dockerOut = (& cmd /c "docker compose up -d 2>&1" | Out-String).Trim()
  if ($dockerOut) { Write-RunLog "docker compose up -d`r`n$dockerOut" }
  if ($LASTEXITCODE -ne 0) { $stepExit = $LASTEXITCODE; throw "docker compose up -d failed with exit code $LASTEXITCODE" }

  # Start the local llama-server if it is not already healthy. Edit start-model.ps1 defaults first.
  $phase = 'model'
  $modelScript = Join-Path $ProjectRoot "deploy\windows\start-model.ps1"
  $modelOut = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $modelScript 2>&1 | Out-String).Trim()
  if ($modelOut) { Write-RunLog "start-model`r`n$modelOut" }
  if ($LASTEXITCODE -ne 0) { $stepExit = $LASTEXITCODE; throw "local llama-server failed to start with exit code $LASTEXITCODE" }

  # Run the digest and write raw UTF-8 output, avoiding PowerShell's mixed-encoding redirection.
  $phase = 'cli'
  $env:PYTHONIOENCODING = 'utf-8'
  $cliOut = Join-Path $logDir "cli-run.log"
  $cliErr = Join-Path $logDir "cli-run.err.log"
  $venv = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  if (Test-Path $venv) { $cliExe = $venv; $cliArgs = @('-m','opportunity_radar.cli') }
  else { $cliExe = 'py'; $cliArgs = @('-3','-m','opportunity_radar.cli') }
  Write-RunLog "CLI starting: $cliExe $($cliArgs -join ' ')"
  $proc = Start-Process -FilePath $cliExe -ArgumentList $cliArgs -NoNewWindow -PassThru -RedirectStandardOutput $cliOut -RedirectStandardError $cliErr
  # PowerShell 5.1 leaves ExitCode empty on a -PassThru object started without -Wait. Turning on
  # the exit event makes the object track the real code; without it the launcher would report a
  # successful exit for a failed run, which is exactly the kind of quiet lie this work removes.
  try { $proc.EnableRaisingEvents = $true } catch { Write-RunLog "WARNING: cannot track the CLI exit code: $($_.Exception.Message)" }
  # Write the child pid before waiting: if this launcher is terminated mid-run, the marker is
  # the only record that a CLI process was still alive and which pid it had.
  ('{"run_id":"' + $runId + '","launcher_pid":' + $PID + ',"cli_pid":' + $proc.Id + ',"started_at":"' + (Get-Date -Format o) + '"}') |
    Set-Content -Path $markerPath -Encoding UTF8
  Write-RunLog "CLI started (pid $($proc.Id))"
  $proc.WaitForExit()
  if ($null -eq $proc.ExitCode) {
    $code = 1
    Write-RunLog "CLI exit code unknown; the run is recorded as failed"
  } else {
    $code = [int]$proc.ExitCode
    Write-RunLog "CLI exit code $code (stdout: reports\cli-run.log; stderr: reports\cli-run.err.log)"
  }
  $phase = 'done'
}
catch {
  Write-RunLog "LAUNCHER ERROR in phase $phase (run $runId): $($_.Exception.Message)"
  if ($stepExit -ne 0) { $code = $stepExit } else { $code = 1 }
}
finally {
  Write-RunLog ("Finished Opportunity Radar with exit code {0} (run {1}, phase {2})" -f $code, $runId, $phase)
  Remove-Item -Path $markerPath -ErrorAction SilentlyContinue
}
exit $code
