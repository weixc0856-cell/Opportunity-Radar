# Operations

Start FreshRSS: `docker compose up -d`; inspect with `docker compose ps` and `docker compose logs -f freshrss`.

Open `http://127.0.0.1:8088`, initialize FreshRSS, verify API availability and add only approved feeds.

Check model: `Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8080/v1/models"`.

Test: `py -3 -m unittest discover -s tests -v`; offline sample: `py -3 -m opportunity_radar.cli --dry-run --sample`.

End-to-end verification: `py -3 tools/e2e_verify.py --limit 3` runs the real FreshRSS -> model -> SQLite -> report chain, then repeats it against a local server that returns an invalid category. It exits non-zero if a failed analysis is reported as a clean run. See `docs/E2E_VERIFICATION.md`.

Real run: `deploy\windows\run-digest.ps1`.

Task Scheduler runs `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<project>\deploy\windows\run-digest.ps1"`, where `<project>` is the checkout path registered by `install-task.ps1`. Run interactively first.

Source registry audit (metadata only): `py -3 -m opportunity_radar.source_audit`. Optional HTTPS reachability checks: `py -3 -m opportunity_radar.source_audit --check-urls`. Reachability is not legal approval.

SMTP check before a real run: `py -3 -m opportunity_radar.mail_test`. It sends one test message only. Ports 465/994 use implicit TLS; 163 mail requires an authorization code, not the account password.

Each run writes a timestamped archive under `reports/archive/` and records the path plus report hash in the `runs` table. Duplicate reports are not sent twice; runs with no new analyses record `skipped_no_new_content`. Publication is gated on analysis coverage: `PASS` at 0.8 and above, `PASS_WITH_LIMITATIONS` between 0.5 and 0.8 (the report states the coverage), `HOLD` below 0.5 or after an integrity fault. A held run sends no subscription mail and no alert mail; it keeps the local report and the run row.

Local admin UI: `.\deploy\windows\start-admin.ps1` (or `.\.venv\Scripts\python.exe -m opportunity_radar.admin_server`) serves http://127.0.0.1:8090. It binds loopback only and has no authentication. It edits the registry selected by `OR_SOURCES_PATH` and stores recipients in `config/recipients.json`; SMTP secrets stay in `.env`.

Scheduled runs (`run-digest.ps1`) start Docker Compose and the local model first, then write `reports/scheduler-run.log` with the run id, each phase, the CLI pid and its exit code, and `reports/cli-run.log` / `cli-run.err.log` with the raw CLI output. A launcher killed from outside cannot write its own ending, so it leaves `reports/launcher-inflight.json`; the next run reports that unfinished marker. Multiple recipients in `OR_EMAIL_TO` (comma or semicolon separated) receive separate copies.

## 本地模型按需启动

`OR_MODEL_AUTOSTART=1`（Windows）时，`cli` 在分析前检查 `OR_LLM_BASE_URL/health`；若模型未运行，
会调用 `deploy/windows/start-model.ps1` 并在 `OR_MODEL_START_TIMEOUT`（默认 600 秒）内轮询，成功才继续。
默认关闭；关闭时模型不可用会让这次运行以退出码 3 结束，而不是产生 30 条连接失败。
