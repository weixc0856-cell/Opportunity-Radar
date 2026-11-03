# Runs the approved non-RSS sources, each into its own isolated database.
#
# This is not part of the RSS digest. It runs before the CLI so the economic engine
# (R5) reads today's BLS/EIA observations instead of yesterday's. A source that is not
# configured is recorded as not_configured, never as success; a failing source never
# blocks the digest, but its status stays in reports\sources\latest.json and in the
# scheduler log. GDELT stays frozen: it answered HTTP 429 and is not retried here.
$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectRoot
$logDir = Join-Path $ProjectRoot "reports\sources"
New-Item -ItemType Directory -Force $logDir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
$started = Get-Date

$venv = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $venv) { $python = $venv; $pyPrefix = @() }
else { $python = 'py'; $pyPrefix = @('-3') }

$steps = @(
  @{ name = 'sec';              args = @('-m','opportunity_radar.ingest.sec_main') },
  @{ name = 'eia';              args = @('-m','opportunity_radar.ingest.eia_main') },
  @{ name = 'federal-register'; args = @('-m','opportunity_radar.pilot','federal-register','--live') },
  @{ name = 'bls';              args = @('-m','opportunity_radar.pilot','bls','--live') }
)

$results = [ordered]@{}
$anyFailed = $false
foreach ($step in $steps) {
  $name = $step.name
  $outLog = Join-Path $logDir "$name.log"
  $errLog = Join-Path $logDir "$name.err.log"
  $argv = $pyPrefix + $step.args
  try {
    $proc = Start-Process -FilePath $python -ArgumentList $argv -NoNewWindow -PassThru `
      -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    try { $proc.EnableRaisingEvents = $true } catch {}
    $proc.WaitForExit()
    $code = if ($null -eq $proc.ExitCode) { 1 } else { [int]$proc.ExitCode }
  }
  catch {
    $code = 1
    [IO.File]::AppendAllText($errLog, "launcher error: $($_.Exception.Message)`r`n", $utf8)
  }
  # 0 = success, 2 = missing configuration or a rights refusal (the source stays disabled).
  $status = switch ($code) { 0 { 'ok' } 2 { 'not_configured' } default { 'failed' } }
  if ($status -eq 'failed') { $anyFailed = $true }
  $results[$name] = [ordered]@{ status = $status; exit_code = $code;
                                log = "reports/sources/$name.log" }
  Write-Output "$name : $status (exit $code)"
}

# GDELT is recorded, not run: the pilot is frozen on HTTP 429 and retrying it daily would
# be an unapproved change in request volume.
$results['gdelt'] = [ordered]@{ status = 'frozen'; exit_code = $null;
                                log = 'reports/pilot/latest.json';
                                reason = 'HTTP 429; pilot frozen, not retried by the scheduler' }

# ok       = every configured source succeeded (frozen GDELT is recorded separately)
# partial  = a source is not configured, so it stays disabled rather than running with a guess
# failed   = a configured source ran and failed
$notConfigured = @($results.Values | Where-Object { $_.status -eq 'not_configured' }).Count -gt 0
$summary = [ordered]@{
  started_at  = $started.ToString('o')
  finished_at = (Get-Date).ToString('o')
  status      = if ($anyFailed) { 'failed' } elseif ($notConfigured) { 'partial' } else { 'ok' }
  sources     = $results
}
$json = $summary | ConvertTo-Json -Depth 6
$tmp = Join-Path $logDir "latest.json.tmp"
[IO.File]::WriteAllText($tmp, $json, $utf8)
Move-Item -Force $tmp (Join-Path $logDir "latest.json")
[IO.File]::WriteAllText((Join-Path $logDir ("sync-{0}.json" -f $started.ToString('yyyyMMdd-HHmmss'))), $json, $utf8)

if ($anyFailed) { exit 1 } else { exit 0 }
