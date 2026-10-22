param(
  [string]$ModelPath = "D:\AI\models\Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf",
  [string]$ServerExe = "D:\AI\bin-sycl\llama-server.exe",
  [int]$Port = 8080,
  [string]$Device = "SYCL0",
  [int]$ContextSize = 16384,
  [int]$BatchSize = 256,
  [int]$UBatchSize = 128,
  [int]$CpuMoeLayers = 48,
  [string]$ApiKey = "",
  [int]$TimeoutSeconds = 600,
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

function Test-Health {
  try { $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2; return ($r.status -eq 'ok') }
  catch { return $false }
}

if (Test-Health) { Write-Host "llama-server is already healthy on port $Port"; exit 0 }

$alias = [System.IO.Path]::GetFileNameWithoutExtension($ModelPath)
$logDir = Join-Path $ProjectRoot "reports"
New-Item -ItemType Directory -Force $logDir | Out-Null
$outLog = Join-Path $logDir "llama-server.log"
$errLog = Join-Path $logDir "llama-server.err.log"

# Mirrors start_server.bat's Qwen3-30B-A3B profile: SYCL, built-in Jinja template,
# CPU MoE offload for the expert layers, 16K context, 256/128 batch.
# CORS is limited to the local server itself; the API key is required for every request.
$serverArgs = @(
  '-m', $ModelPath,
  '--host', '127.0.0.1',
  '--port', "$Port",
  '-dev', $Device,
  '-ngl', '99',
  '-c', "$ContextSize",
  '--parallel', '1',
  '-b', "$BatchSize",
  '-ub', "$UBatchSize",
  '-fa', 'on',
  '--metrics',
  '--jinja',
  '--alias', "$alias,default",
  '--api-key', $ApiKey,
  '--cors-origins', "http://127.0.0.1:$Port,http://localhost:$Port"
)
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

for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
  Start-Sleep -Seconds 1
  if ($proc.HasExited) {
    Write-Host "llama-server exited with code $($proc.ExitCode)"
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
