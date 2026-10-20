# Operations

Start FreshRSS: `docker compose up -d`; inspect with `docker compose ps` and `docker compose logs -f freshrss`.

Open `http://127.0.0.1:8088`, initialize FreshRSS, verify API availability and add only approved feeds.

Check model: `Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8080/v1/models"`.

Test: `py -3 -m unittest discover -s tests -v`; offline sample: `py -3 -m opportunity_radar.cli --dry-run --sample`.

Real run: `deploy\windows\run-digest.ps1`.

Task Scheduler uses `powershell.exe` with `-NoProfile -ExecutionPolicy Bypass -File "D:\opportunity-radar\deploy\windows\run-digest.ps1"`. Run interactively first.

Source registry audit (metadata only): `py -3 -m opportunity_radar.source_audit`. Optional HTTPS reachability checks: `py -3 -m opportunity_radar.source_audit --check-urls`. Reachability is not legal approval.

SMTP check before a real run: `py -3 -m opportunity_radar.mail_test`. It sends one test message only. Ports 465/994 use implicit TLS; 163 mail requires an authorization code, not the account password.

Each run writes a timestamped archive under `reports/archive/` and records the path plus report hash in the `runs` table. Duplicate reports are not sent twice; runs with no new analyses record `skipped_no_new_content`; repeated failures trigger an alert after `OR_ALERT_AFTER_FAILURES` runs.

Scheduled runs (`run-digest.ps1`) start Docker Compose and the local model first, then write `reports/scheduler-run.log` with step-level status and `reports/cli-run.log` / `cli-run.err.log` with the raw CLI output. Multiple recipients in `OR_EMAIL_TO` (comma or semicolon separated) receive separate copies.
