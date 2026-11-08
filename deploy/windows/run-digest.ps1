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

# The task's ExecutionTimeLimit is 180 minutes and a TerminateProcess kill runs no `finally`
# block. Every wait below therefore has an explicit ceiling, and the ceilings sum to less than
# the task limit, so a stuck phase fails loudly here instead of vanishing at 11:00.
#   600 (docker engine) + 2400 (model) + 900 (sources) + 6300 (cli) = 10200 s < 10800 s
# The CLI gets the largest share on purpose: a cold CPU-only run measured 55 minutes for 19
# analyses alone (2026-11-08) before the post-analysis pipeline. A 3600 s ceiling killed that
# run while it was still working, which is a worse failure than a late report.
$DockerWaitSeconds     = 600
$ModelPortWaitSeconds  = 1800   # start-model gives up on a busy 8080 by itself, before its ceiling
$ModelTimeoutSeconds   = 2400   # 1800 s of port wait + 600 s for a cold model load
$SourcesTimeoutSeconds = 900
$CliTimeoutSeconds     = 6300

function Test-DockerEngine {
  # `docker info` reaches the engine, not just the CLI. cmd preserves the native exit code.
  & cmd /c "docker info >nul 2>&1"
  return ($LASTEXITCODE -eq 0)
}

function Start-DockerDesktopIfNeeded {
  if (Test-DockerEngine) { return $true }
  $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
  if (-not (Test-Path $desktop)) {
    Write-RunLog "docker engine is not reachable and Docker Desktop is not installed at $desktop"
    return $false
  }
  # 2026-11-08: the machine rebooted at 07:46, Docker Desktop has AutoStart=false, and the
  # 08:00 run died in `docker compose up -d`. Starting the engine here, with a bounded wait,
  # is what stops a reboot from becoming a silent day.
  Write-RunLog "docker engine is not reachable; starting Docker Desktop (waiting up to ${DockerWaitSeconds}s)"
  Start-Process -FilePath $desktop | Out-Null
  $waited = 0
  while ($waited -lt $DockerWaitSeconds) {
    Start-Sleep -Seconds 10
    $waited += 10
    if (Test-DockerEngine) {
      Write-RunLog "docker engine is up after ${waited}s"
      return $true
    }
  }
  Write-RunLog "docker engine did not come up within ${DockerWaitSeconds}s"
  return $false
}

function Read-SharedText([string]$Path) {
  # The child's grandchildren inherit the redirected file handle, so the file can still be open
  # when the child exits; [IO.File]::ReadAllText would throw "used by another process".
  if (-not (Test-Path $Path)) { return "" }
  $stream = $null
  try {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    $reader = New-Object System.IO.StreamReader($stream, $utf8)
    return $reader.ReadToEnd().Trim()
  } catch {
    return ""
  } finally {
    if ($stream) { $stream.Dispose() }
  }
}

function Get-EnvValue([string]$Key) {
  # Same source the Python settings read, so the launcher and the CLI cannot disagree about
  # which analyzer is configured.
  $envFile = Join-Path $ProjectRoot ".env"
  if (-not (Test-Path $envFile)) { return "" }
  foreach ($line in Get-Content $envFile -Encoding UTF8) {
    if ($line -match ('^' + [regex]::Escape($Key) + '=(.*)$')) {
      return $matches[1].Trim().Trim('"').Trim("'")
    }
  }
  return ""
}

function Test-LocalLlmEndpoint([string]$BaseUrl) {
  # Only the local llama-server on 8080 is started by this launcher. Any other base URL (the
  # cc-switch proxy on 15721, or a hosted endpoint) is somebody else's process to run.
  try { $parsed = [Uri]$BaseUrl } catch { return $false }
  if (-not $parsed.IsAbsoluteUri) { return $false }
  $hostName = $parsed.Host.ToLower()
  return ((($hostName -eq '127.0.0.1') -or ($hostName -eq 'localhost')) -and ($parsed.Port -eq 8080))
}

function Invoke-ChildScript {
  # Child output goes to files, never through a pipeline. PowerShell passes inheritable pipe
  # handles down to grandchildren, so a llama-server started inside start-model.ps1 kept the
  # write end of `| Out-String` open and the launcher never saw EOF: 2026-11-04..11-07 each
  # logged a start and no ending, then were killed by the 180-minute limit.
  param(
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)][string]$ScriptPath,
    [string]$ExtraArgs = "",
    [int]$TimeoutSeconds = 1800
  )
  $outFile = Join-Path $logDir "$Name.out.log"
  $errFile = Join-Path $logDir "$Name.err.log"
  # Start-Process joins an argument array with spaces without quoting, and this project path
  # contains one. Pass a quoted argument line instead.
  $argLine = '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $ScriptPath
  if ($ExtraArgs) { $argLine = "$argLine $ExtraArgs" }
  Write-RunLog "$Name starting (timeout ${TimeoutSeconds}s; output: reports\$Name.out.log, reports\$Name.err.log)"
  $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList $argLine -NoNewWindow -PassThru `
    -RedirectStandardOutput $outFile -RedirectStandardError $errFile
  # PowerShell 5.1 leaves ExitCode empty on a -PassThru object without an exit event.
  try { $proc.EnableRaisingEvents = $true } catch { Write-RunLog "WARNING: cannot track $Name exit code: $($_.Exception.Message)" }
  $watch = [Diagnostics.Stopwatch]::StartNew()
  while (-not $proc.HasExited) {
    if ($watch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
      Write-RunLog "TIMEOUT: $Name did not finish within ${TimeoutSeconds}s; stopping pid $($proc.Id) (output: reports\$Name.out.log)"
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
      return [pscustomobject]@{ exit = 124; timed_out = $true; seconds = [int]$watch.Elapsed.TotalSeconds }
    }
    Start-Sleep -Milliseconds 500
  }
  $exitCode = 1
  if ($null -ne $proc.ExitCode) { $exitCode = [int]$proc.ExitCode }
  foreach ($file in @($outFile, $errFile)) {
    $text = Read-SharedText $file
    if ($text) { Write-RunLog "$Name output ($(Split-Path $file -Leaf))`r`n$text" }
  }
  Write-RunLog "$Name finished with exit $exitCode after $([int]$watch.Elapsed.TotalSeconds)s"
  return [pscustomobject]@{ exit = $exitCode; timed_out = $false; seconds = [int]$watch.Elapsed.TotalSeconds }
}

$runId = [guid]::NewGuid().ToString('N').Substring(0,8)
$markerPath = Join-Path $logDir "launcher-inflight.json"
$phase = 'start'
$stepExit = 0
$code = 1

# A launcher stopped from outside (time limit, power state, task stop, console close) cannot
# write its own ending. The marker is what separates "the CLI failed" from "the launcher never
# finished": on 2026-10-29, 2026-11-01 and 2026-11-04..11-07 this log had a start and no
# ending, and the cause was not the CLI. Recording whether the old process is still alive
# separates a hang from a kill.
if (Test-Path $markerPath) {
  $previous = Get-Content -Path $markerPath -Raw -ErrorAction SilentlyContinue
  if ($previous) {
    $note = ""
    try {
      $prev = $previous | ConvertFrom-Json
      if ($prev.launcher_pid) {
        if (Get-Process -Id ([int]$prev.launcher_pid) -ErrorAction SilentlyContinue) {
          $note = "; that launcher pid $($prev.launcher_pid) is STILL RUNNING"
        } else {
          $note = "; that launcher pid $($prev.launcher_pid) is gone"
        }
      }
    } catch { }
    Write-RunLog "WARNING: previous launcher left an unfinished run marker: $($previous.Trim())$note"
  }
}
('{"run_id":"' + $runId + '","launcher_pid":' + $PID + ',"started_at":"' + (Get-Date -Format o) + '"}') |
  Set-Content -Path $markerPath -Encoding UTF8
Write-RunLog "Starting Opportunity Radar (run $runId, launcher pid $PID)"

try {
  # Ensure FreshRSS's Compose services are started. The engine is started first if a reboot
  # left Docker Desktop closed (AutoStart=false on this machine).
  $phase = 'docker'
  if (-not (Start-DockerDesktopIfNeeded)) { throw "docker engine is not available" }
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) { throw "docker command not found" }
  $dockerOut = (& cmd /c "docker compose up -d 2>&1" | Out-String).Trim()
  if ($dockerOut) { Write-RunLog "docker compose up -d`r`n$dockerOut" }
  if ($LASTEXITCODE -ne 0) { $stepExit = $LASTEXITCODE; throw "docker compose up -d failed with exit code $LASTEXITCODE" }

  # Start the local llama-server only when the configured analyzer is the local one. When
  # OR_LLM_BASE_URL points elsewhere (the cc-switch proxy, or a hosted endpoint), loading a
  # 19 GB local model is pointless work and can delay the run by minutes.
  $phase = 'model'
  $llmBaseUrl = Get-EnvValue 'OR_LLM_BASE_URL'
  if ($llmBaseUrl -and -not (Test-LocalLlmEndpoint $llmBaseUrl)) {
    Write-RunLog "analyzer endpoint is external ($llmBaseUrl); not starting llama-server"
  } else {
    $modelScript = Join-Path $ProjectRoot "deploy\windows\start-model.ps1"
    $model = Invoke-ChildScript -Name 'start-model' -ScriptPath $modelScript `
      -ExtraArgs "-MaxWaitSeconds $ModelPortWaitSeconds" -TimeoutSeconds $ModelTimeoutSeconds
    if ($model.timed_out) { $stepExit = 124; throw "start-model did not return within ${ModelTimeoutSeconds}s" }
    if ($model.exit -eq 75) { $stepExit = 75; throw "port 8080 stayed busy for ${ModelPortWaitSeconds}s; this run is deferred (see reports\model-defer.log)" }
    if ($model.exit -ne 0) { $stepExit = $model.exit; throw "local llama-server failed to start with exit code $($model.exit)" }
  }

  # Approved non-RSS sources, each into its own database, before the CLI reads them.
  # A source failure is recorded and the digest continues: an outage must stay visible,
  # not become a quiet day of RSS news, and it must not silently block the digest either.
  $phase = 'sources'
  $sourceScript = Join-Path $ProjectRoot "deploy\windows\run-sources.ps1"
  $sources = Invoke-ChildScript -Name 'run-sources' -ScriptPath $sourceScript -TimeoutSeconds $SourcesTimeoutSeconds
  if ($sources.timed_out) {
    Write-RunLog "WARNING: source sync timed out after ${SourcesTimeoutSeconds}s; the digest continues without it (see reports\run-sources.out.log)"
  } elseif ($sources.exit -ne 0) {
    Write-RunLog "WARNING: source sync reported a failure or missing configuration (exit $($sources.exit)); see reports\sources\latest.json"
  }

  # Run the digest and write raw UTF-8 output, avoiding PowerShell's mixed-encoding redirection.
  $phase = 'cli'
  $env:PYTHONIOENCODING = 'utf-8'
  $cliOut = Join-Path $logDir "cli-run.log"
  $cliErr = Join-Path $logDir "cli-run.err.log"
  $venv = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  # -u keeps stdout unbuffered: a blocked phase must show progress in cli-run.log, not only
  # after exit, which a killed process never reaches.
  if (Test-Path $venv) { $cliExe = $venv; $cliArgs = @('-u','-m','opportunity_radar.cli','--period','auto') }
  else { $cliExe = 'py'; $cliArgs = @('-3','-u','-m','opportunity_radar.cli','--period','auto') }
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
  $cliWatch = [Diagnostics.Stopwatch]::StartNew()
  $cliTimedOut = $false
  while (-not $proc.HasExited) {
    if ($cliWatch.Elapsed.TotalSeconds -ge $CliTimeoutSeconds) {
      Write-RunLog "TIMEOUT: the CLI did not finish within ${CliTimeoutSeconds}s; stopping pid $($proc.Id)"
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
      $cliTimedOut = $true
      break
    }
    Start-Sleep -Milliseconds 500
  }
  if ($cliTimedOut) {
    $code = 124
  } elseif ($null -eq $proc.ExitCode) {
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
  # Single-port policy: stop only the llama-server this run started, so 8080 is free again
  # for the project. The pid file is written by start-model.ps1 and its process carries
  # --api-key; a project server does not, so it can never be killed by this cleanup.
  $modelPidFile = Join-Path $ProjectRoot "reports\llama-server.pid"
  if (Test-Path $modelPidFile) {
    $modelPid = 0
    [void][int]::TryParse(((Get-Content $modelPidFile -Raw).Trim()), [ref]$modelPid)
    if ($modelPid -gt 0) {
      $modelProc = Get-Process -Id $modelPid -ErrorAction SilentlyContinue
      if ($modelProc -and $modelProc.ProcessName -eq 'llama-server') {
        $modelCmd = [string](Get-CimInstance Win32_Process -Filter "ProcessId=$modelPid" -ErrorAction SilentlyContinue).CommandLine
        if ($modelCmd -like '*--api-key*') {
          Stop-Process -Id $modelPid -Force -ErrorAction SilentlyContinue
          Write-RunLog "stopped llama-server pid $modelPid; port released"
        }
      }
    }
    Remove-Item -Path $modelPidFile -Force -ErrorAction SilentlyContinue
  }
  Write-RunLog ("Finished Opportunity Radar with exit code {0} (run {1}, phase {2})" -f $code, $runId, $phase)
  Remove-Item -Path $markerPath -ErrorAction SilentlyContinue
}
exit $code
