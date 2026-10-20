param(
  [string]$ModelPath = "D:\AI\models\Qwen3.5-4B_Q4_k_m.gguf",
  [string]$ServerExe = "D:\AI\bin\llama-server.exe",
  [int]$Port = 8080,
  [string]$Device = "Vulkan0",
  [int]$ContextSize = 32768,
  [string]$ApiKey = "",
  [int]$TimeoutSeconds = 120,
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

# Keep the model's own GGUF chat template. The shared start_server.bat forces
# "--chat-template chatml" for Qwen; that drops Qwen3.5's thinking switch, so the model
# spends the whole token budget inside <think> and never returns the JSON this project needs.
# CORS is limited to the local server itself; the API key is required for every request.
$serverArgs = @(
  '-m', $ModelPath,
  '--host', '127.0.0.1',
  '--port', "$Port",
  '--device', $Device,
  '-ngl', 'all',
  '-c', "$ContextSize",
  '--parallel', '1',
  '-b', '512',
  '-ub', '512',
  '-fa', 'on',
  '--alias', "$alias,default",
  '--reasoning', 'off',
  '--api-key', $ApiKey,
  '--cors-origins', "http://127.0.0.1:$Port,http://localhost:$Port"
)

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
