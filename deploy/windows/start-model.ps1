param(
  [string]$ModelPath = "D:\AI\models\Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf",
  [string]$ServerExe = "D:\AI\bin-sycl\llama-server.exe",
  [int]$Port = 8080,
  [string]$Device = "SYCL0",
  # The project instance is CPU-only by contract (D:\AI\CLAUDE.md): the 8 GB A750 is
  # reserved for ComfyUI, and the GPU/MoE split measured ~0.8 tok/s at 64K on 2026-11-03.
  # CPU-only keeps the 30B MoE at 3B active parameters and does not touch the card.
  [int]$ContextSize = 65536,
  [int]$BatchSize = 256,
  [int]$UBatchSize = 128,
  [int]$GpuLayers = 0,
  [int]$CpuMoeLayers = 0,
  [string]$ApiKey = "",
  [int]$TimeoutSeconds = 600,
  # Single-port policy: the project owns 8080 while it runs. This launcher waits for the
  # project to release the port instead of starting a second LLM server on another port.
  [int]$MaxWaitSeconds = 28800,
  [int]$PollSeconds = 30,
  [switch]$Foreground
)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not (Test-Path $ServerExe)) { throw "llama-server not found: $ServerExe" }
if (-not (Test-Path $ModelPath)) { throw "Model not found: $ModelPath" }

# The API key lives in .env so the client and server cannot drift apart.
if (-not $ApiKey) {
  $envFile = Join-Path $ProjectRoot ".env"
  if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
      if ($line -match '^OR_LLM_API_KEY=(.*)$') { $ApiKey = $matches[1].Trim().Trim('"').Trim("'"); break }
    }
  }
}
if (-not $ApiKey -or $ApiKey -like 'replace_*') { throw "No local LLM API key. Set OR_LLM_API_KEY in .env or pass -ApiKey." }

$logDir = Join-Path $ProjectRoot "reports"
New-Item -ItemType Directory -Force $logDir | Out-Null
$pidFile = Join-Path $logDir "llama-server.pid"
$deferLog = Join-Path $logDir "model-defer.log"

function Write-Defer([string]$Message) {
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  [IO.File]::AppendAllText($deferLog, "[$(Get-Date -Format o)] $Message`r`n", $utf8)
  Write-Host $Message
}

function Test-Health {
  try { $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2; return ($r.status -eq 'ok') }
  catch { return $false }
}

function Get-ListenerPid {
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
       Select-Object -First 1
  if ($c) { return [int]$c.OwningProcess }
  return 0
}

function Get-CmdLine([int]$procId) {
  if ($procId -le 0) { return "" }
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
  if ($p) { return [string]$p.CommandLine }
  return ""
}

function Test-OwnServer([string]$cmd) {
  if (-not $cmd) { return $false }
  return ($cmd -like "*--api-key*") -and ($cmd -like "*$ModelPath*")
}

function Get-Inflight {
  try {
    $m = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/metrics" -UseBasicParsing -TimeoutSec 2
    $p = [regex]::Match([string]$m.Content, '(?m)^llamacpp:requests_processing\s+(\d+)')
    $q = [regex]::Match([string]$m.Content, '(?m)^llamacpp:requests_deferred\s+(\d+)')
    if ($p.Success) {
      $d = '0'; if ($q.Success) { $d = $q.Groups[1].Value }
      return "$($p.Groups[1].Value) processing / $d deferred"
    }
    return "metrics unavailable"
  } catch { return "metrics unavailable" }
}

$listener = Get-ListenerPid
if ($listener -gt 0) {
  $cmd = Get-CmdLine $listener
  if (Test-OwnServer $cmd) {
    # Reuse, but do not claim ownership: the launcher that started this server stops it.
    # Writing the pid file here would make run-digest.ps1 stop a server it did not start.
    Write-Host "llama-server is already healthy on port $Port (pid $listener); not owned by this run"
    exit 0
  }
  # A foreign llm-server (normally the project instance) owns the port. Wait for it to finish
  # and stop, rather than opening a second port or killing someone else's process.
  Write-Defer "port $Port is held by pid $listener; deferring digest run. cmd=$cmd"
  $waited = 0
  while ($waited -lt $MaxWaitSeconds) {
    Start-Sleep -Seconds $PollSeconds
    $waited += $PollSeconds
    $listener = Get-ListenerPid
    if ($listener -le 0) {
      Write-Defer "port $Port released after ${waited}s; starting the task server"
      break
    }
    Write-Defer "still waiting (${waited}s): pid $listener, inflight $(Get-Inflight)"
  }
  if ((Get-ListenerPid) -gt 0) {
    Write-Defer "gave up after ${waited}s; port $Port is still held. This run is deferred."
    Write-Host "port $Port still occupied after $MaxWaitSeconds s; nothing was started"
    exit 75
  }
} elseif (Test-Health) {
  Write-Host "llama-server is healthy on port $Port but has no resolvable listener; reusing it"
  exit 0
}

$alias = [System.IO.Path]::GetFileNameWithoutExtension($ModelPath)
$outLog = Join-Path $logDir "llama-server.log"
$errLog = Join-Path $logDir "llama-server.err.log"

# The project instance follows D:\AI\CLAUDE.md: CPU-only, 64K context, 256/128 batch.
# `-ngl 0` leaves the A750 free for ComfyUI; KV quantisation is only useful on the GPU
# path, so it is added only when the caller explicitly asks for GPU layers.
# CORS is limited to the local server itself; the API key is required for every request.
$serverArgs = @(
  '-m', $ModelPath,
  '--host', '127.0.0.1',
  '--port', "$Port",
  '-dev', $Device,
  '-ngl', "$GpuLayers",
  '-c', "$ContextSize",
  '--parallel', '1',
  '-b', "$BatchSize",
  '-ub', "$UBatchSize",
  '-fa', 'on',
  '--metrics',
  '--jinja',
  '--reasoning', 'off',
  '--alias', "$alias,default",
  '--api-key', $ApiKey,
  '--cors-origins', "http://127.0.0.1:$Port,http://localhost:$Port"
)
if ($GpuLayers -gt 0) {
  $serverArgs += @('-ctk', 'q8_0', '-ctv', 'q8_0')
}
if ($CpuMoeLayers -gt 0) { $serverArgs += @('--n-cpu-moe', "$CpuMoeLayers") }

if ($Foreground) {
  # Native stderr becomes a terminating NativeCommandError under -Stop on PowerShell 5.1.
  $ErrorActionPreference = "Continue"
  & $ServerExe @serverArgs
  exit $LASTEXITCODE
}

# Redirect the native streams directly: PowerShell does not wrap them into error records,
# so the log shows llama.cpp output instead of "NativeCommandError".
$proc = Start-Process -FilePath $ServerExe -ArgumentList $serverArgs -NoNewWindow -PassThru `
  -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Set-Content -Path $pidFile -Value $proc.Id -Encoding ASCII

for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
  Start-Sleep -Seconds 1
  if ($proc.HasExited) {
    Write-Host "llama-server exited with code $($proc.ExitCode)"
    Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
    if (Test-Path $errLog) { Get-Content $errLog -Tail 20 }
    exit 1
  }
  if (Test-Health) {
    Write-Host "llama-server ready on http://127.0.0.1:$Port (pid $($proc.Id))"
    Write-Host "logs: $outLog ; $errLog"
    exit 0
  }
}
Write-Host "llama-server did not become healthy within $TimeoutSeconds s (pid $($proc.Id))"
if (Test-Path $errLog) { Get-Content $errLog -Tail 20 }
exit 1
