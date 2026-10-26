#!/usr/bin/env python3
"""End-to-end verification: FreshRSS -> local model -> SQLite -> report.

This is not a configuration smoke test. It runs the real pipeline into an isolated
database and report directory, then inspects the artifacts it left behind. One rule
shapes every check: a failed analysis must never look like a quiet day with no news.

Two runs:
  happy  - the configured model, a few articles; must produce analyses and a report.
  fault  - a local server that returns well-formed JSON with an invalid category
           (ISSUE-001). By then some articles are already analysed, so the run has
           both skipped and failed articles - the exact combination that used to print
           "no new analysis tasks" while every attempt had failed.

Exit codes: 0 pass, 1 verification failure, 2 preflight/environment failure,
3 baseline packaging failure.

Usage:
    python tools/e2e_verify.py --limit 3
    python tools/e2e_verify.py --limit 3 --baseline-dir tests/baselines/2026-10-26
    python tools/e2e_verify.py --skip-fault --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_radar.config import Settings  # noqa: E402
from opportunity_radar.freshrss_client import FreshRSSClient, ordered_feed_ids  # noqa: E402
from opportunity_radar.model_service import health_ok  # noqa: E402
from opportunity_radar.source_audit import audit_sources  # noqa: E402
from opportunity_radar.source_policy import is_approved, load_sources  # noqa: E402

# The phrase a clean-but-empty run may use. It must not appear when analyses failed.
MASKING_PHRASE = "本轮没有新增分析任务"
FAILURE_PHRASES = ("分析结果为空", "本轮分析未完成")

# A complete object with a semantically valid category outside the schema enum.
# This reproduces ISSUE-001 without a live model.
FAULT_ANALYSIS = {
    "category": "policy_change",
    "summary_zh": "测试用：政府发布了一项政策，但分类不在允许枚举内。",
    "pain_point": "unknown",
    "target_customer": "unknown",
    "commercial_signal": "unknown",
    "revenue_claim": "unknown",
    "evidence_quotes": [],
    "uncertainties": ["fault injection"],
    "suggested_next_step": "unknown",
    "relevance_score": 50,
    "confidence": "low",
}
FAULT_BODY = json.dumps(FAULT_ANALYSIS, ensure_ascii=False)


def _check(code, ok, detail):
    return {"code": code, "ok": bool(ok), "detail": str(detail)[:500]}


def _all_ok(checks):
    return all(c["ok"] for c in checks)


def preflight(settings, limit):
    """Checks that must pass before spending model time. Returns (checks, pool)."""
    checks = []
    missing = settings.validate(mail=False)
    checks.append(_check("config", not missing, "ok" if not missing else "missing: " + ", ".join(missing)))

    registry = load_sources()
    errors = [x for x in audit_sources(registry) if x["severity"] == "error"]
    approved = [s for s in registry if is_approved(s)]
    checks.append(_check("sources", not errors and bool(approved),
                         f"{len(approved)} approved; {len(errors)} audit error(s)"))

    pool = []
    try:
        client = FreshRSSClient(settings.freshrss_base_url, settings.freshrss_username,
                                settings.freshrss_api_key, settings.request_timeout)
        feeds = {f["id"]: f["title"] for f in client.list_feeds()}
        unmapped = [s.source_id for s in approved if s.freshrss_feed_id not in feeds]
        checks.append(_check("freshrss_feeds", not unmapped,
                             f"{len(feeds)} feed(s); unmapped: {', '.join(unmapped) or 'none'}"))
        pool = client.fetch_articles(max(limit + 4, 8),
                                     feed_ids=ordered_feed_ids({s.freshrss_feed_id for s in approved}))
        checks.append(_check("freshrss_pool", len(pool) >= limit,
                             f"{len(pool)} article(s) in pool, need {limit}"))
    except Exception as exc:  # a dead FreshRSS must be a named failure, not an empty digest
        checks.append(_check("freshrss", False, f"{type(exc).__name__}: {exc}"))

    healthy = health_ok(settings.llm_base_url)
    checks.append(_check("model_health", healthy,
                         "ok" if healthy else f"no healthy model at {settings.llm_base_url}"))
    return checks, pool


def run_pipeline(workdir, limit, llm_base_url=None):
    """Run `python -m opportunity_radar.cli --dry-run` against an isolated store."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "OR_DB_PATH": str(workdir / "run.sqlite3"),
        "OR_LOG_PATH": str(workdir / "run.log"),
        "OR_REPORT_DIR": str(workdir / "reports"),
        "OR_MAX_ARTICLES": str(limit),
        "OR_MODEL_AUTOSTART": "0",
        "PYTHONIOENCODING": "utf-8",
    })
    if llm_base_url:
        env["OR_LLM_BASE_URL"] = llm_base_url
    proc = subprocess.run([sys.executable, "-m", "opportunity_radar.cli", "--dry-run"],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=3600)
    (workdir / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (workdir / "stderr.txt").write_text(proc.stderr, encoding="utf-8")
    return proc


def read_run(workdir):
    """Latest run row plus its recorded per-article failures (None if the table is absent)."""
    db = Path(workdir) / "run.sqlite3"
    if not db.exists():
        return None, None
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
        run = dict(row) if row else None
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        failures = None
        if "analysis_failures" in tables and run:
            failures = [dict(r) for r in conn.execute(
                "SELECT failure_id, run_id, article_key, url, stage, error FROM analysis_failures "
                "WHERE run_id=? ORDER BY failure_id", (run["run_id"],))]
    finally:
        conn.close()
    return run, failures


def load_artifacts(workdir):
    """Latest report text, archive manifest and analysed items from an isolated run."""
    reports = Path(workdir) / "reports"
    text_path = reports / "latest-digest.txt"
    html_path = reports / "latest-digest.html"
    manifests = sorted((reports / "archive").rglob("*.manifest.json")) if (reports / "archive").exists() else []
    manifest = items = None
    if manifests:
        newest = max(manifests, key=lambda p: p.stat().st_mtime)
        manifest = json.loads(newest.read_text(encoding="utf-8"))
        items_path = newest.with_name(newest.name.replace(".manifest.json", ".items.json"))
        if items_path.exists():
            items = json.loads(items_path.read_text(encoding="utf-8")).get("items", [])
    return {
        "report_text": text_path.read_text(encoding="utf-8") if text_path.exists() else None,
        "manifest": manifest,
        "items": items,
        "files": {"text": text_path.exists(), "html": html_path.exists(), "archive": bool(manifests)},
    }


def evaluate_run(run, artifacts, failures):
    """Pure verification of one run. `failures` is None when the table does not exist."""
    out = [_check("run_recorded", run is not None, f"run_id={run.get('run_id')}" if run else "no run row")]
    if not run:
        return out
    analyzed = int(run.get("analyzed_count") or 0)
    errors = int(run.get("error_count") or 0)
    status = str(run.get("status") or "")
    exit_code = run.get("exit_code")
    files = artifacts.get("files") or {}
    out.append(_check("artifacts", all(files.get(k) for k in ("text", "html", "archive")),
                      ", ".join(f"{k}={'yes' if files.get(k) else 'no'}" for k in ("text", "html", "archive"))))

    if errors:
        out.append(_check("failure_status", status in {"partial_failed", "analysis_failed", "failed"}
                          and exit_code not in (0, None),
                          f"status={status} exit={exit_code} errors={errors}"))
    if analyzed == 0 and errors:
        out.append(_check("analysis_failed_not_success", status == "analysis_failed" and exit_code not in (0, None),
                          f"status={status} exit={exit_code} analyzed=0 errors={errors}"))
        recorded = None if failures is None else len(failures)
        out.append(_check("failures_recorded", recorded == errors,
                          f"{recorded} failure row(s), expected {errors}"
                          + ("" if recorded is not None else " (analysis_failures table missing)")))
        text = artifacts.get("report_text") or ""
        masked = MASKING_PHRASE in text
        explained = any(p in text for p in FAILURE_PHRASES)
        out.append(_check("report_names_the_failure", (not masked) and explained,
                          ("masking phrase present; " if masked else "")
                          + ("failure explanation present" if explained else "no failure explanation")))

    manifest = artifacts.get("manifest")
    items = artifacts.get("items")
    text = artifacts.get("report_text")
    if manifest and text is not None:
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        out.append(_check("report_hash", manifest.get("report_hash") == expected,
                          f"manifest={manifest.get('report_hash')} file={expected}"))
    if manifest and items is not None:
        out.append(_check("item_count", len(items) == int(manifest.get("article_count") or 0),
                          f"items={len(items)} manifest={manifest.get('article_count')}"))
        expected_counts = {s: sum(1 for x in items if x.get("status") == s)
                           for s in ("priority", "watch", "filtered")}
        actual_counts = (manifest.get("stats") or {}).get("counts")
        out.append(_check("status_counts", actual_counts == expected_counts,
                          f"manifest={actual_counts} items={expected_counts}"))
        divergent = [x.get("title", "?") for x in items
                     if (x.get("scoring") or {}).get("status") != x.get("status")]
        out.append(_check("scoring_matches_items", not divergent,
                          "ok" if not divergent else f"{len(divergent)} item(s) diverge: {divergent[:3]}"))
    return out


def outcome_of(run):
    if not run:
        return "no_run"
    analyzed = int(run.get("analyzed_count") or 0)
    errors = int(run.get("error_count") or 0)
    if analyzed == 0 and errors:
        return "all_analyses_failed"
    if errors:
        return "partial_failure"
    if run.get("status") == "no_new_content" or (analyzed == 0 and not errors):
        return "no_new_content"
    return "ok"


class _FaultModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # health and model listing
        path = self.path.rstrip("/")
        if path.endswith("/health"):
            self._send({"status": "ok"})
        elif path.endswith("/models"):
            self._send({"data": [{"id": "e2e-fault-model"}]})
        else:
            self._send({})

    def do_POST(self):  # chat completions: always the invalid-category object
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._send({"choices": [{"message": {"content": FAULT_BODY}}]})


class FakeModelServer:
    """A local OpenAI-compatible endpoint that always fails schema validation."""

    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FaultModel)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        return False


def git_state():
    """Commit and whether the working tree was dirty when the baseline was taken."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        if commit.returncode != 0:
            return "", False
        return commit.stdout.strip(), bool(status.stdout.strip())
    except OSError:
        return "", False


def write_baseline(baseline_dir, workdir, payload):
    """Copy the run's database, logs and reports, then hash every file."""
    baseline_dir = Path(baseline_dir)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    for name in ("run.sqlite3", "run.log", "stdout.txt", "stderr.txt"):
        src = Path(workdir) / name
        if src.exists():
            shutil.copy2(src, baseline_dir / name)
    reports = Path(workdir) / "reports"
    if reports.exists():
        shutil.copytree(reports, baseline_dir / "reports", dirs_exist_ok=True)
    payload = dict(payload)
    commit, dirty = git_state()
    payload["git_commit"] = commit
    payload["git_dirty"] = dirty
    # Explicit LF: git normalises text files on commit, and a CRLF hash would stop
    # matching the manifest as soon as the baseline is checked out on another machine.
    (baseline_dir / "verification.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    files = []
    for path in sorted(baseline_dir.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.json":
            files.append({"path": path.relative_to(baseline_dir).as_posix(),
                          "bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(),
        "git_commit": payload["git_commit"],
        "git_dirty": payload["git_dirty"],
        "files": files,
        "note": "Local verification baseline. Article text is feed-supplied excerpts, not "
                "full articles; the database and reports are gitignored by tests/baselines/.gitignore.",
    }
    (baseline_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def _print_checks(title, checks):
    print(title)
    for c in checks:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['code']}: {c['detail']}")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="End-to-end verification of the daily pipeline")
    parser.add_argument("--limit", type=int, default=3, help="articles for the happy run")
    parser.add_argument("--skip-fault", action="store_true", help="skip the injected-failure run")
    parser.add_argument("--baseline-dir", type=Path, help="copy the run into this directory")
    parser.add_argument("--workdir", type=Path, help="reuse a working directory instead of a timestamped one")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    limit = max(1, args.limit)
    settings = Settings.from_env()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = args.workdir or (ROOT / "data" / f"e2e-verify-{stamp}")
    workdir.mkdir(parents=True, exist_ok=True)

    payload = {"workdir": str(workdir), "limit": limit, "runs": {}, "checks": []}
    checks, _pool = preflight(settings, limit)
    payload["checks"].extend({"stage": "preflight", **c} for c in checks)
    if not args.json:
        _print_checks("preflight", checks)
    if not _all_ok(checks):
        payload["result"] = "preflight_failed"
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        print("Preflight failed; not spending model time on a run that cannot be trusted.", file=sys.stderr)
        return 2

    happy_dir = workdir / "happy"
    proc = run_pipeline(happy_dir, limit)
    run, failures = read_run(happy_dir)
    happy_checks = evaluate_run(run, load_artifacts(happy_dir), failures)
    payload["runs"]["happy"] = {"returncode": proc.returncode, "run": run,
                                "failures": failures, "checks": happy_checks}
    if not args.json:
        print(f"happy run: exit={proc.returncode} status={run and run.get('status')} "
              f"analyzed={run and run.get('analyzed_count')} failed={run and run.get('error_count')}")
        _print_checks("happy verification", happy_checks)

    fault_checks = []
    if not args.skip_fault:
        fault_dir = workdir / "fault"
        fault_dir.mkdir(parents=True, exist_ok=True)
        if (happy_dir / "run.sqlite3").exists():
            # Reuse the happy store so some articles are already analysed: the fault run
            # then has skipped>0 and failed>0, which is where the masking bug lived.
            shutil.copy2(happy_dir / "run.sqlite3", fault_dir / "run.sqlite3")
        with FakeModelServer() as fault_url:
            fault_proc = run_pipeline(fault_dir, limit + 2, llm_base_url=fault_url)
        fault_run, fault_failures = read_run(fault_dir)
        fault_checks = evaluate_run(fault_run, load_artifacts(fault_dir), fault_failures)
        payload["runs"]["fault"] = {"returncode": fault_proc.returncode, "run": fault_run,
                                    "failures": fault_failures, "checks": fault_checks}
        if not args.json:
            print(f"fault run: exit={fault_proc.returncode} status={fault_run and fault_run.get('status')} "
                  f"analyzed={fault_run and fault_run.get('analyzed_count')} "
                  f"failed={fault_run and fault_run.get('error_count')}")
            _print_checks("fault verification", fault_checks)

    payload["result"] = "pass" if _all_ok(happy_checks + fault_checks) else "fail"
    exit_code = 0 if payload["result"] == "pass" else 1
    if args.baseline_dir:
        try:
            manifest = write_baseline(args.baseline_dir, happy_dir, payload)
            payload["baseline"] = {"dir": str(args.baseline_dir), "files": len(manifest["files"])}
            if not args.json:
                print(f"baseline written: {args.baseline_dir} ({len(manifest['files'])} files)")
        except OSError as exc:
            payload["baseline"] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"Baseline packaging failed: {exc}", file=sys.stderr)
            exit_code = 3

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"\nresult: {payload['result']} (workdir {workdir})")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
