# Operations

## Services

| Service | Endpoint | Start | Stop |
|---|---|---|---|
| FreshRSS | `http://127.0.0.1:8088` | `docker compose up -d` | `docker compose down` |
| Local model | `http://127.0.0.1:8080/v1` | `.\deploy\windows\start-model.ps1` | stop the pid in `reports\llama-server.pid` |
| Admin UI | `http://127.0.0.1:8090` | `.\deploy\windows\start-admin.ps1` | Ctrl+C |

The project model instance is **CPU-only** (`-ngl 0`, 64K context, q8_0 not needed on CPU).
The 8 GB Arc A750 is reserved for ComfyUI. The GPU/MoE split measured ~0.8 tok/s at 64K on
2026-11-03; the CPU-only instance measured ~10.8 tok/s on the same model. Do not raise the
timeout to hide a throughput problem.

Only one llama-server may use 8080. `start-model.ps1` waits for a foreign listener, never
opens a second port and never kills another process. `run-digest.ps1` stops only the server
it started (pid file + command line carrying `--api-key`).

## Daily task

`OpportunityRadarDaily` runs at 08:00 and calls:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<project>\deploy\windows\run-digest.ps1"
```

`run-digest.ps1` starts Compose and the model, then runs
`python -m opportunity_radar.cli --period auto`. `OR_PIPELINE_ENABLED=0` disables the
post-analysis pipeline for isolated tests; `OR_CLAIM_PIPELINE_MAX_ARTICLES` (default 8)
bounds how many new articles go through N0–N5 each run. The task has `StartWhenAvailable`,
battery restrictions off, `MultipleInstances=IgnoreNew` and a **180-minute** execution limit.
`--period auto` writes the daily brief, plus a weekly report every 7 days and a monthly
report every 30 days (catch-up uses the last report's mtime).

Failure semantics:

- Model unavailable at preflight: `runs` row `failed` + HOLD, exit 3, no subscription mail.
- Model dies mid-run: bounded retries, health probe, circuit breaker; remaining articles are
  recorded as `not_attempted`, coverage falls, HOLD below 0.5.
- Unified pipeline blocking failure: HOLD with the failing step named in the report.
- No new content: `no_new_content`, no mail.
- Duplicate: report-hash idempotency per recipient, no second send.
- HOLD sends neither subscription nor alert mail; the local report and `runs` row are kept.
- A launcher killed from outside leaves `reports/launcher-inflight.json`; the next run
  reports it.

## Commands

```
py -3 -m opportunity_radar.cli --dry-run                 # real fetch + model + full pipeline, no mail
py -3 -m opportunity_radar.cli --render-only             # re-render latest, read-only
py -3 -m opportunity_radar.cli --period weekly|monthly   # rebuild a period report
py -3 -m opportunity_radar.unified_main audit --db <db>  # read-only end-to-end audit
py -3 -m opportunity_radar.unified_main db-migrate --db <db>                 # preview
py -3 -m opportunity_radar.unified_main db-migrate --db <db> --apply --backup <file>
py -3 -m opportunity_radar.unified_main economic
py -3 -m opportunity_radar.unified_main opportunities
py -3 -m opportunity_radar.unified_main quality
py -3 -m opportunity_radar.unified_main backtest
py -3 -m opportunity_radar.source_audit
py -3 -m opportunity_radar.acceptance                     # real environment checks
```

Tests: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
Offline sample: `python -m opportunity_radar.cli --dry-run --sample`.
End-to-end fault injection: `py -3 tools/e2e_verify.py --limit 3`.

## Database

Production: `data/opportunity_radar.sqlite3`, schema **v9**. Business commands open with
`migrate=False`; a lower schema raises `SchemaVersionError` and points to `db-migrate`.
`audit`, `report`, `--render-only` stay read-only. `db-migrate --apply` requires a different,
integrity-checked backup file. A migration rehearsal and the production backup are in
`data/archive/final-migration-2026-11-03/`.

Isolated stores:

- SEC/EIA: `data/ingest/opportunity_radar_ingest.sqlite3`
- Source Pilot: `data/pilot/source_pilot.sqlite3`
- Claim node runs: `data/claim-pipeline/node_runs.sqlite3`
- Economic: `data/economic/economic.sqlite3`
- Quality: `data/quality/quality.sqlite3`

## Reports and logs

- `reports/latest-digest.{txt,html}`; archive `reports/archive/YYYY/MM/DD/` with text, HTML,
  `items.json` and `manifest.json`.
- Weekly/monthly: `reports/weekly-*.txt|json`, `reports/monthly-*.txt|json`, archived under
  `reports/archive/`.
- Quality: `reports/quality/latest.{json,md}`.
- Logs: `reports/scheduler-run.log`, `cli-run.log`, `cli-run.err.log`,
  `opportunity-radar.log`, `llama-server.log`, `llama-server.err.log`, `model-defer.log`.
- `reports/llama-server.pid` exists only while a project model instance is running.

## SMTP check

`py -3 -m opportunity_radar.mail_test` sends one test message. 465/994 use implicit TLS;
163 mail requires an authorization code, not the account password. Real daily mail is sent
only after the publication gate passes and the report is not a duplicate.
