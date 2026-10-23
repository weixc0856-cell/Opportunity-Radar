#!/usr/bin/env python3
"""Offline experiment: record `actionability` without touching production rules.

Runs a fixed candidate pool through the production analyzer and evaluator, stores the raw
model output and the parsed fields, and leaves scoring, lanes, status bands and quotas
untouched. Results are written per round so a long run can resume after an interruption.

Usage:
    python tools/actionability_experiment.py run --pool .../pool.json --rounds 3 --out-dir .../results
    python tools/actionability_experiment.py report --out-dir .../results
"""
import argparse
import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opportunity_radar.analyzer import LocalAnalyzer, PROMPT_VERSION, PROMPT_HASH  # noqa: E402
from opportunity_radar.cli import evaluate, source_index, resolve_source  # noqa: E402
from opportunity_radar.config import Settings, load_scoring  # noqa: E402
from opportunity_radar.scoring import RULES_VERSION  # noqa: E402
from opportunity_radar.source_policy import load_sources  # noqa: E402

LEVELS = {"none": 0, "monitor": 1, "investigate": 2, "decide": 3, "act": 4}


def article(item):
    from types import SimpleNamespace
    return SimpleNamespace(title=item["title"], summary=item["summary"], url=item["url"],
                           source_name=item["source_name"], published="", feed_id="")


def run(pool_path: Path, out_dir: Path, rounds: int, limit: int | None = None) -> None:
    settings = Settings.from_env()
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    sources = {s.source_id: s for s in load_sources()}
    by_id, by_name, _ = source_index(list(sources.values()))
    lanes = load_scoring().get("lanes")
    analyzer = LocalAnalyzer(settings.llm_base_url, settings.llm_model, settings.llm_timeout,
                             settings.llm_max_tokens, api_key=settings.llm_api_key)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "pool_sha256": hashlib.sha256(pool_path.read_bytes()).hexdigest(),
        "model": settings.llm_model,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": PROMPT_HASH,
        "rules_version": RULES_VERSION,
        "scoring_sha256": hashlib.sha256(Path("config/scoring.toml").read_bytes()).hexdigest(),
        "rounds": rounds,
        "pool_items": len(pool),
    }
    (out_dir / "experiment_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    for round_no in range(1, rounds + 1):
        path = out_dir / f"round-{round_no}.json"
        done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        finished = {row["item_id"] for row in done}
        todo = [item for item in pool if item["item_id"] not in finished]
        if limit:
            todo = todo[:limit]
        print(f"round {round_no}: {len(finished)} done, {len(todo)} to run", flush=True)
        for index, item in enumerate(todo, 1):
            row = {"item_id": item["item_id"], "title": item["title"], "url": item["url"],
                   "source_name": item["source_name"], "source_id": item.get("source_id", ""),
                   "label": item["label"], "original_score": item.get("original_score"),
                   "original_status": item.get("original_status"),
                   "original_importance": item.get("original_importance")}
            trace = []
            try:
                analysis = analyzer.analyze(item["title"], item["summary"], item["source_name"],
                                            item["url"], trace=trace)
                source = sources.get(item.get("source_id", "")) or resolve_source(item, by_id, by_name)
                evaluated = evaluate(article(item), analysis, model=settings.llm_model, source=source,
                                     lanes_config=lanes)
                components = evaluated.get("components") or {}
                row.update({
                    "raw": trace,
                    "actionability": analysis.get("actionability"),
                    "actionability_status": analysis.get("actionability_status"),
                    "importance": components.get("importance"),
                    "components": components,
                    "score": evaluated.get("score"),
                    "lane": evaluated.get("lane"),
                    "band": evaluated.get("status"),
                    "filter_reason": evaluated.get("filter_reason", ""),
                    "source_cap": getattr(source, "source_cap", 0) if source else 0,
                })
            except Exception as exc:  # one bad item must not abort the experiment
                row.update({"raw": trace, "error": f"{type(exc).__name__}: {exc}"})
            done.append(row)
            path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  [{index}/{len(todo)}] {item['item_id']} {row.get('actionability')} "
                  f"{row.get('score')} {row.get('error', '')}", flush=True)


def auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def bootstrap_ci(pos: list[float], neg: list[float], n: int = 1000, seed: int = 20261023):
    if not pos or not neg:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(n):
        p = [rng.choice(pos) for _ in pos]
        q = [rng.choice(neg) for _ in neg]
        values.append(auc(p, q))
    values.sort()
    return [round(values[int(0.025 * n)], 3), round(values[int(0.975 * n) - 1], 3)]


def top_k(rows: list[dict], metric: str, k: int) -> dict:
    usable = [row for row in rows if "error" not in row and row.get(metric) is not None]
    if metric == "actionability":
        usable = [row for row in usable if row.get("actionability_status") == "ok"]
        key = lambda row: (LEVELS.get(row["actionability"], -1), row.get("score") or 0)
    else:
        key = lambda row: (row.get(metric) or 0, row.get("score") or 0)
    ranked = sorted(usable, key=key, reverse=True)[:k]
    return {"k": k, "items": len(ranked),
            "actionable": sum(1 for row in ranked if row["label"] == "actionable")}


def quota_top_k(rows: list[dict], metric: str, k: int) -> dict:
    """Top-K by metric, then each source's cap applied in that order (production semantics)."""
    usable = [row for row in rows if "error" not in row and row.get(metric) is not None]
    if metric == "actionability":
        usable = [row for row in usable if row.get("actionability_status") == "ok"]
        key = lambda row: (LEVELS.get(row["actionability"], -1), row.get("score") or 0)
    else:
        key = lambda row: (row.get(metric) or 0, row.get("score") or 0)
    ranked = sorted(usable, key=key, reverse=True)[:k]
    used, included = {}, []
    for row in ranked:
        source = row.get("source_id") or row.get("source_name")
        cap = row.get("source_cap") or 0
        if cap and used.get(source, 0) >= cap:
            continue
        used[source] = used.get(source, 0) + 1
        included.append(row)
    return {"k": k, "ranked": len(ranked), "included": len(included),
            "actionable": sum(1 for row in included if row["label"] == "actionable")}


AGG_KEY = {"actionability": "actionability_level", "importance": "importance", "score": "score"}


def agg_top_k(rows: list[dict], metric: str, k: int) -> dict:
    key_name = AGG_KEY[metric]
    usable = [row for row in rows if row.get(key_name) is not None]
    ranked = sorted(usable, key=lambda row: (row[key_name], row.get("score") or 0), reverse=True)[:k]
    return {"k": k, "items": len(ranked),
            "actionable": sum(1 for row in ranked if row["label"] == "actionable")}


def agg_quota_top_k(rows: list[dict], metric: str, k: int) -> dict:
    key_name = AGG_KEY[metric]
    usable = [row for row in rows if row.get(key_name) is not None]
    ranked = sorted(usable, key=lambda row: (row[key_name], row.get("score") or 0), reverse=True)[:k]
    used, included = {}, []
    for row in ranked:
        source = row.get("source_id")
        cap = row.get("source_cap") or 0
        if cap and used.get(source, 0) >= cap:
            continue
        used[source] = used.get(source, 0) + 1
        included.append(row)
    return {"k": k, "ranked": len(ranked), "included": len(included),
            "actionable": sum(1 for row in included if row["label"] == "actionable")}


def report(out_dir: Path) -> dict:
    rounds = sorted(out_dir.glob("round-*.json"))
    meta = json.loads((out_dir / "experiment_meta.json").read_text(encoding="utf-8"))
    per_round, pooled = [], []
    for path in rounds:
        rows = json.loads(path.read_text(encoding="utf-8"))
        usable = [row for row in rows if "error" not in row and row.get("actionability_status") == "ok"]
        pos = [LEVELS[row["actionability"]] for row in usable if row["label"] == "actionable"]
        neg = [LEVELS[row["actionability"]] for row in usable if row["label"] == "weak"]
        score_pos = [row["score"] for row in usable if row["label"] == "actionable" and row.get("score") is not None]
        score_neg = [row["score"] for row in usable if row["label"] == "weak" and row.get("score") is not None]
        imp_pos = [row["importance"] for row in usable if row["label"] == "actionable" and row.get("importance") is not None]
        imp_neg = [row["importance"] for row in usable if row["label"] == "weak" and row.get("importance") is not None]
        per_round.append({
            "round": path.stem.split("-")[1],
            "rows": len(rows), "usable": len(usable),
            "errors": sum(1 for row in rows if "error" in row),
            "missing": sum(1 for row in rows if row.get("actionability_status") == "missing"),
            "invalid": sum(1 for row in rows if row.get("actionability_status") == "invalid"),
            "pos": len(pos), "neg": len(neg),
            "auc_actionability": round(auc(pos, neg), 3) if pos and neg else None,
            "auc_actionability_ci": bootstrap_ci(pos, neg),
            "auc_importance": round(auc(imp_pos, imp_neg), 3) if imp_pos and imp_neg else None,
            "auc_score": round(auc(score_pos, score_neg), 3) if score_pos and score_neg else None,
            "top7": {m: top_k(usable, m, 7) for m in ("actionability", "importance", "score")},
            "top13": {m: top_k(usable, m, 13) for m in ("actionability", "importance", "score")},
            "quota7": {m: quota_top_k(usable, m, 7) for m in ("actionability", "importance", "score")},
            "quota13": {m: quota_top_k(usable, m, 13) for m in ("actionability", "importance", "score")},
        })
        pooled.extend(usable)
    # Pooled metrics are aggregated per item: three rounds of one article are not three
    # independent samples, and duplicate rows would distort both the AUC and Top-K.
    by_item: dict[str, list[dict]] = {}
    for row in pooled:
        by_item.setdefault(row["item_id"], []).append(row)
    aggregated = []
    for item_id, rows in by_item.items():
        levels = [LEVELS[row["actionability"]] for row in rows]
        scores = [row["score"] for row in rows if row.get("score") is not None]
        imps = [row["importance"] for row in rows if row.get("importance") is not None]
        aggregated.append({
            "item_id": item_id, "label": rows[0]["label"], "source_id": rows[0].get("source_id"),
            "source_cap": rows[0].get("source_cap") or 0,
            "actionability_level": statistics.mean(levels),
            "score": statistics.mean(scores) if scores else None,
            "importance": statistics.mean(imps) if imps else None,
        })
    pos = [row["actionability_level"] for row in aggregated if row["label"] == "actionable"]
    neg = [row["actionability_level"] for row in aggregated if row["label"] == "weak"]
    imp_pos = [row["importance"] for row in aggregated if row["label"] == "actionable" and row["importance"] is not None]
    imp_neg = [row["importance"] for row in aggregated if row["label"] == "weak" and row["importance"] is not None]
    score_pos = [row["score"] for row in aggregated if row["label"] == "actionable" and row["score"] is not None]
    score_neg = [row["score"] for row in aggregated if row["label"] == "weak" and row["score"] is not None]
    agreement = [len({row.get("actionability") for row in rows}) == 1 for rows in by_item.values()]
    errors = [{"round": path.stem.split("-")[1], "item_id": row.get("item_id"), "error": row.get("error")}
              for path in rounds for row in json.loads(path.read_text(encoding="utf-8")) if row.get("error")]
    return {
        "meta": meta,
        "per_round": per_round,
        "errors": errors,
        "pooled": {
            "items": len(aggregated), "pos": len(pos), "neg": len(neg),
            "auc_actionability": round(auc(pos, neg), 3) if pos and neg else None,
            "auc_actionability_ci": bootstrap_ci(pos, neg),
            "auc_importance": round(auc(imp_pos, imp_neg), 3) if imp_pos and imp_neg else None,
            "auc_score": round(auc(score_pos, score_neg), 3) if score_pos and score_neg else None,
            "agreement_same_level": round(sum(agreement) / len(agreement), 3) if agreement else None,
            "top7": {m: agg_top_k(aggregated, m, 7) for m in ("actionability", "importance", "score")},
            "top13": {m: agg_top_k(aggregated, m, 13) for m in ("actionability", "importance", "score")},
            "quota7": {m: agg_quota_top_k(aggregated, m, 7) for m in ("actionability", "importance", "score")},
            "quota13": {m: agg_quota_top_k(aggregated, m, 13) for m in ("actionability", "importance", "score")},
        },
    }


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Offline actionability experiment")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--pool", required=True, type=Path)
    run_p.add_argument("--out-dir", required=True, type=Path)
    run_p.add_argument("--rounds", type=int, default=3)
    run_p.add_argument("--limit", type=int, help="run at most N items per round (pilot)")
    rep_p = sub.add_parser("report")
    rep_p.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.pool, args.out_dir, args.rounds, args.limit)
        return 0
    print(json.dumps(report(args.out_dir), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
