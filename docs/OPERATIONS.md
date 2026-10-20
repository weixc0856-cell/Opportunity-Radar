# Operations

Start FreshRSS: `docker compose up -d`; inspect with `docker compose ps` and `docker compose logs -f freshrss`.

Open `http://127.0.0.1:8088`, initialize FreshRSS, verify API availability and add only approved feeds.

Check model: `Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8080/v1/models"`.

Test: `py -3 -m unittest discover -s tests -v`; offline sample: `py -3 -m opportunity_radar.cli --dry-run --sample`.

Real run: `.deploy\windows\run-digest.ps1` (replace escaped sequences if copying from plain text; intended path is `deploy\windows\run-digest.ps1`).

Task Scheduler uses `powershell.exe` with `-NoProfile -ExecutionPolicy Bypass -File "D:\opportunity-radar\deploy\windows\run-digest.ps1"`. Run interactively first.
