#!/usr/bin/env python3
"""Read-only metrics for an E2E source-quality shadow run.

Inputs are the artifacts a `--dry-run` already produces, plus a FreshRSS snapshot:
  * the run's SQLite database (articles, analyses, runs);
  * the archived `.items.json` and `.manifest.json`;
  * the isolated group config (to know which feeds were enabled);
  * a copy of the FreshRSS `db.sqlite` (to measure what each feed actually supplied).

It never writes to the run database and never calls the model.

Usage:
    python tools/e2e_metrics.py --label baseline \
        --db data/e2e-2026-10-23/baseline.sqlite3 \
        --items reports/.../XXXX.items.json \
        --manifest reports/.../XXXX.manifest.json \
        --config data/e2e-2026-10-23/baseline-community.csv \
        --freshrss data/e2e-2026-10-23/freshrss-snapshot.sqlite3 \
        --out data/e2e-2026-10-23/baseline-metrics.json
"""
import argparse
import csv
import json
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opportunity_radar.evidence import EVIDENCE_RANK  # noqa: E402

TAG = re.compile(r"<[^>]+>")


def plain(value: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", value or "")).strip()


def load_items(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")).get("items", [])


def load_config(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {r["freshrss_feed_id"]: r["source_id"] for r in rows
            if (r.get("enabled") or "").lower() == "true" and r.get("freshrss_feed_id")}


def fresh_rss_health(snapshot: Path, feed_ids: dict[str, str]) -> list[dict]:
    conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    out = []
    for feed_id, source_id in sorted(feed_ids.items(), key=lambda kv: int(kv[0])):
        row = conn.execute("SELECT name, url, error FROM feed WHERE id=?", (feed_id,)).fetchone()
        if not row:
            out.append({"source_id": source_id, "feed_id": feed_id, "feed": "(missing)"})
            continue
        name, url, error = row
        entries = conn.execute(
            "SELECT content, date FROM entry WHERE id_feed=? ORDER BY date DESC LIMIT 30", (feed_id,)
        ).fetchall()
        lengths = [len(plain(content)) for content, _ in entries]
        latest = datetime.fromtimestamp(max(d for _, d in entries), timezone.utc).isoformat() \
            if entries else ""
        out.append({
            "source_id": source_id, "feed_id": feed_id, "feed": name, "url": url,
            "error": error or "",
            "entries_total": conn.execute("SELECT COUNT(*) FROM entry WHERE id_feed=?", (feed_id,)).fetchone()[0],
            "entries_sampled": len(lengths),
            "median_body_chars": int(statistics.median(lengths)) if lengths else 0,
            "empty_body_ratio": round(sum(1 for n in lengths if n < 50) / len(lengths), 3) if lengths else None,
            "latest_entry": latest,
        })
    conn.close()
    return out


def run_metrics(db: Path, items: list[dict], manifest: dict) -> dict:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    run = conn.execute("SELECT started_at, finished_at, status, article_count, analyzed_count, error_count "
                       "FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    published = [r[0] for r in conn.execute("SELECT published FROM articles WHERE published<>''")]
    per_source = conn.execute(
        "SELECT a.source_name, COUNT(*), COUNT(an.article_key) FROM articles a "
        "LEFT JOIN analyses an ON an.article_key=a.article_key GROUP BY a.source_name").fetchall()
    events = conn.execute(
        "SELECT event_key, COUNT(DISTINCT source_name) FROM articles WHERE event_key<>'' "
        "GROUP BY event_key HAVING COUNT(DISTINCT source_name)>1").fetchall()
    conn.close()

    states = Counter(i.get("evidence_state") or "" for i in items)
    ranks = Counter(EVIDENCE_RANK.get(i.get("evidence_state") or "", "E0") for i in items)
    quotes = [e for i in items for e in (i.get("evidence") or [])]
    located = sum(1 for e in quotes if e.get("field") != "unlocated")
    mainlines = Counter(l.strip() for i in items
                        for l in (i.get("intelligence_lines") or "").split(",") if l.strip())
    stats = manifest.get("stats", {})
    started, finished = run[0] if run else "", run[1] if run else ""
    duration = ""
    try:
        duration = round((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds(), 1)
    except (TypeError, ValueError):
        pass
    return {
        "run": {
            "started_at": started, "finished_at": finished,
            "status": run[2] if run else "", "duration_seconds": duration,
            "fetched": stats.get("fetched"), "new": stats.get("new"),
            "queued": stats.get("queued"), "analyzed": stats.get("analyzed"),
            "failed": stats.get("failed"), "skipped_analysis": stats.get("skipped"),
            "duplicate_events": stats.get("duplicate_events"), "deferred": stats.get("deferred"),
            "publish_window": {"min": min(published) if published else "",
                               "max": max(published) if published else ""},
        },
        "sources": [{"source_name": name, "articles": n, "analyses": m}
                    for name, n, m in sorted(per_source, key=lambda r: (-r[1], r[0]))],
        "cross_source_event_keys": len(events),
        "evidence": {"states": dict(states), "ranks": dict(ranks)},
        "lanes": dict(Counter(i.get("lane") or "" for i in items)),
        "statuses": dict(Counter(i.get("status") or "" for i in items)),
        "filter_reasons": dict(Counter(i.get("filter_reason") or "(none)" for i in items)),
        "mainlines": dict(mainlines),
        "quotes": {"total": len(quotes), "located": located, "unlocated": len(quotes) - located,
                   "located_ratio": round(located / len(quotes), 3) if quotes else None},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--items", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--freshrss", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    items = load_items(args.items)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = {
        "label": args.label,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": str(args.config),
        **run_metrics(args.db, items, manifest),
        "feed_health": fresh_rss_health(args.freshrss, load_config(args.config)),
    }
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
