# Operations

## Services

| Service | Endpoint | Start | Stop |
|---|---|---|---|
| FreshRSS | `http://127.0.0.1:8088` | `docker compose up -d` | `docker compose down` |
| Local model | `http://127.0.0.1:8080/v1` | `.\deploy\windows\start-model.ps1` | stop the pid in `reports\llama-server.pid` |
| Admin UI | `http://127.0.0.1:8090` | `.\deploy\windows\start-admin.ps1` | Ctrl+C |

The production analysis prompt is `prompts/analyst_v7.md` (`OR_PROMPT_PATH`); v6 is rollback only.
The project model instance is **CPU-only** (`-ngl 0`, 64K context, q8_0 not needed on CPU).
The 8 GB Arc A750 is reserved for ComfyUI. The GPU/MoE split measured ~0.8 tok/s at 64K on
2026-11-03; the CPU-only instance measured ~10.8 tok/s on the same model. Do not raise the
timeout to hide a throughput problem.

Only one llama-server may use 8080. `start-model.ps1` waits for a foreign listener, never
opens a second port and never kills another process. `run-digest.ps1` stops only the server
it started (pid file + command line carrying `--api-key`).

The port wait is capped at **1800 s (30 min)** and then exits 75, recorded as
`port 8080 stayed busy for 1800s; this run is deferred`. The old 28800 s default could never
complete inside the task's 180-minute limit: it only made the run look hung and then be killed
with a start line and no ending.

## Analyzer backend

Analysis is one HTTP client (`analyzer.LocalAnalyzer`) with two transports over the same
contract. Two setups are known to work:

| Backend | `OR_LLM_API_STYLE` | `OR_LLM_BASE_URL` | `OR_LLM_MODEL` | `OR_LLM_MAX_TOKENS` |
|---|---|---|---|---|
| Local llama-server (CPU-only) | `openai` | `http://127.0.0.1:8080/v1` | `Qwen3-30B-A3B-Instruct-2507-Q4_K_M` | `1400` |
| cc-switch proxy, Claude Code route | `anthropic` | `http://127.0.0.1:15721/v1` | `claude-sonnet-5` | `4000` |

`OR_LLM_API_STYLE` picks the wire protocol: `openai` posts to `{base}/chat/completions`,
`anthropic` posts to `{base}/messages` (top-level `system`, `x-api-key` +
`anthropic-version`, answer in `content` text blocks). The cc-switch proxy serves both, but
only the Anthropic route is the one Claude Code itself uses; the proxy labels the other
`Codex endpoint`, and it is not used here. Everything above the transport — prompt, parser,
retries, failure causes — is shared, so the backend does not change what is asked or how the
answer is checked.

`run-digest.ps1` starts `start-model.ps1` only when `OR_LLM_BASE_URL` resolves to
`127.0.0.1:8080`; with any other endpoint it logs `analyzer endpoint is external` and leaves
the local model alone.

**The token budget is not a per-backend preference.** On the proxy, the V7 system prompt
spends ~1400-1800 reasoning tokens before any JSON is emitted, and long articles spend
more. With `OR_LLM_MAX_TOKENS=1400` the completion came back empty and looked like a dead
model; at 4000, 3 of 20 articles on 2026-11-08 still returned no text. Keep it at 8000.
An empty answer is recorded as cause `empty_completion` (not a circuit-breaker cause) and
retried once with double the budget before the article is counted as failed.

Health: `health_ok` accepts both `{"status":"ok"}` (llama.cpp) and
`{"status":"healthy"}` (the cc-switch proxy). Anything else is treated as a dead endpoint.

Rollback to the local instance: restore `.env.bak-2026-11-08-local-qwen` over `.env`
(`OR_MODEL_AUTOSTART=1` restarts the local server from the CLI if it is down).

## Daily task

`OpportunityRadarDaily` runs at 06:00 and calls:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<project>\deploy\windows\run-digest.ps1"
```

`run-digest.ps1` starts Compose and the model, runs `deploy/windows/run-sources.ps1`
(SEC, EIA, Federal Register, BLS — each into its own database, before the CLI so the
economic engine reads today's observations), then runs
`python -m opportunity_radar.cli --period auto`. `OR_PIPELINE_ENABLED=0` disables the
post-analysis pipeline for isolated tests; `OR_CLAIM_PIPELINE_MAX_ARTICLES` (default 8)
bounds how many new articles go through N0–N5 each run. The task has `StartWhenAvailable`,
battery restrictions off, `MultipleInstances=IgnoreNew` and a **180-minute** execution limit.

Launcher phases and their ceilings (all inside the 180-minute limit, 10200 s in total):

| Phase | Wait | On expiry |
|---|---|---|
| docker | 600 s — starts Docker Desktop if the engine is down (`AutoStart=false` on this machine, so a reboot leaves it closed) | `LAUNCHER ERROR in phase docker` |
| model | 2400 s (1800 s of port wait + 600 s cold load); `start-model` defers on a busy port after 1800 s | exit 75 recorded as deferred |
| sources | 900 s | warning, digest continues |
| cli | 6300 s | exit 124, `TIMEOUT` line |

The CLI gets the largest share because a cold CPU-only run spent 55 minutes on 19 analyses
alone on 2026-11-08, before the post-analysis pipeline; a 3600 s ceiling killed a run that was
still working. Every analysed article now logs `Analyzed n of m article(s)`, and the CLI runs
with `-u`, so a long run shows progress instead of an empty log.

Each child script writes `reports\<phase>.out.log` / `.err.log` and is read back into
`reports/scheduler-run.log` when it exits. Child output must never travel through a
PowerShell pipeline (`| Out-String`): inheritable pipe handles reach grandchildren, and a
`llama-server` holding the write end leaves the launcher waiting for an EOF that never comes.
That was the 2026-11-04..11-07 failure, where every run left a start line, no ending, and an
`launcher-inflight.json` marker that the next day reported.
`--period auto` writes the daily brief, plus a weekly report every 7 days and a monthly
report every 30 days (catch-up uses the last report's mtime).

Source sync semantics:

- Each source writes only its own database (`data/ingest/...`, `data/pilot/...`); SEC/EIA
  never enter the RSS tables, the prompt or the report body.
- `reports/sources/latest.json` records one status per source: `ok`, `not_configured`
  (exit 2, missing credentials or a rights refusal), `failed`. GDELT is recorded as
  `frozen` (HTTP 429) and is not retried by the scheduler.
- A failing or unconfigured source never blocks the digest, but it is logged in
  `reports/scheduler-run.log` and printed in the digest appendix as
  `外部数据源同步（日期）`, so it cannot look like a quiet day.

Failure semantics:

- Model unavailable at preflight: `runs` row `failed` + HOLD, exit 3, no subscription mail.
- Model dies mid-run: bounded retries, health probe, circuit breaker; remaining articles are
  recorded as `not_attempted`, coverage falls, HOLD below 0.5.
- Unified pipeline blocking failure: HOLD with the failing step named in the report.
- No new content: `no_new_content`, no mail.
- Duplicate: report-hash idempotency per recipient, no second send.
- HOLD sends neither subscription nor alert mail; the local report and `runs` row are kept.
- A launcher killed from outside leaves `reports/launcher-inflight.json`; the next run
  reports it, including whether the recorded launcher pid was still alive (a hang) or gone
  (a kill).

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
`migrate=False`; an existing lower schema raises `SchemaVersionError` and points to
`db-migrate`. A database that does not exist yet is created with the current schema by the
first CLI run (fresh install, isolated E2E); the guard only stops an older existing file.
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

- `reports/latest-digest.{txt,html}` is the complete report (with appendices);
  `reports/latest-digest-email.{txt,html}` is the exact edition mailed. Admin resend reads the
  email edition, never the full one.
- Archive `reports/archive/YYYY/MM/DD/` keeps text, HTML, `*.email.txt`, `*.email.html`,
  `items.json` and `manifest.json`.
- Appendix sections are also stored in SQLite `report_sections` keyed by report hash;
  `GET /api/report/sections` returns the latest stored brief and appendices.
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

## Prompt version and rollback

Production uses `prompts/analyst_v7.md` through `OR_PROMPT_PATH`. V6
(`prompts/analyst.md`) is retained only as the rollback prompt. The analysis input hash now
includes the model, prompt version and prompt hash, so changing the prompt invalidates the
old analysis instead of silently reusing it.

Rollback: set `OR_PROMPT_PATH=prompts/analyst.md`, restart the CLI; restore
`data/archive/v7-switch-2026-11-03/pre-v7-run.sqlite3` only if the V7 run's database changes
must be undone. The live task keeps using `--period auto` and the same pipeline.
