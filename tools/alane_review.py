#!/usr/bin/env python3
"""Offline review of the A-lane score against human labels.

Joins a shadow run's items with its blind-review labels and reports how well the current
score, and each component, separates "actionable" from "weak". Read-only: it never
touches scoring rules, the database, or archived files.

Usage:
    python tools/alane_review.py \
        --items-baseline ...items.json --items-candidate ...items.json \
        --key .../key.json --labels .../labels.csv --out data/.../alane-review.json
"""
import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

A_COMPONENTS = ("importance", "source_reliability", "evidence_completeness",
                "novelty", "relevance", "timeliness")


def load_items(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")).get("items", [])


def join(items_by_group: dict[str, list[dict]], key: dict, labels: dict) -> list[dict]:
    pools = {group: list(items) for group, items in items_by_group.items()}
    rows = []
    for review_id, meta in key.items():
        group = meta["group"]
        for index, item in enumerate(pools.get(group, [])):
            if item.get("title") == meta["title"] and item.get("source_name") == meta["source"]:
                pools[group].pop(index)
                rows.append({"review_id": review_id, "group": group, "label": labels[review_id],
                             "item": item})
                break
    return rows


def auc(positives: list[float], negatives: list[float]) -> float | None:
    """Rank-based AUC; ties count 0.5. None when either side is empty."""
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for n in negatives:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return round(wins / (len(positives) * len(negatives)), 3)


def group_stats(rows: list[dict]) -> dict:
    by_label = defaultdict(list)
    for row in rows:
        by_label[row["label"]].append(row)
    status = Counter((row["item"].get("status"), row["label"]) for row in rows)
    actionable = [row for row in rows if row["label"] == "actionable"]
    weak = [row for row in rows if row["label"] == "weak"]
    priority = [row for row in rows if row["item"].get("status") == "priority"]

    components = {}
    for name in A_COMPONENTS:
        values = [row["item"].get("components", {}).get(name) for row in rows
                  if row["item"].get("components", {}).get(name) is not None]
        if not values:
            continue
        pos = [row["item"]["components"][name] for row in actionable
               if name in (row["item"].get("components") or {})]
        neg = [row["item"]["components"][name] for row in weak
               if name in (row["item"].get("components") or {})]
        components[name] = {
            "mean_actionable": round(statistics.mean(pos), 2) if pos else None,
            "mean_weak": round(statistics.mean(neg), 2) if neg else None,
            "auc_actionable_vs_weak": auc(pos, neg),
            "distribution": dict(sorted(Counter(values).items())),
            "share_at_max": round(values.count(max(values)) / len(values), 3),
        }

    score_pos = [row["item"]["score"] for row in actionable]
    score_neg = [row["item"]["score"] for row in weak]
    return {
        "rows": len(rows),
        "labels": dict(Counter(row["label"] for row in rows)),
        "status_by_label": {f"{status_value}/{label}": count for (status_value, label), count in status.items()},
        "priority": {
            "count": len(priority),
            "actionable": sum(1 for row in priority if row["label"] == "actionable"),
            "weak": sum(1 for row in priority if row["label"] == "weak"),
            "noise": sum(1 for row in priority if row["label"] == "noise"),
            "precision": round(sum(1 for row in priority if row["label"] == "actionable") / len(priority), 3)
            if priority else None,
            "recall": round(sum(1 for row in priority if row["label"] == "actionable") / len(actionable), 3)
            if actionable else None,
        },
        "score": {"auc_actionable_vs_weak": auc(score_pos, score_neg),
                  "mean_actionable": round(statistics.mean(score_pos), 1) if score_pos else None,
                  "mean_weak": round(statistics.mean(score_neg), 1) if score_neg else None},
        "components": components,
        "priority_items": [
            {"title": row["item"].get("title"), "source": row["item"].get("source_name"),
             "score": row["item"].get("score"), "label": row["label"],
             "article_type": (row["item"].get("classification") or {}).get("article_type"),
             "signal_type": (row["item"].get("classification") or {}).get("signal_type")}
            for row in sorted(priority, key=lambda row: -row["item"].get("score", 0))
        ],
    }


def duplicate_titles(rows: list[dict]) -> list[list[str]]:
    seen = defaultdict(list)
    for row in rows:
        seen[row["item"].get("title")].append(row["review_id"])
    return [titles for titles in seen.values() if len(titles) > 1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline A-lane score review")
    parser.add_argument("--items-baseline", required=True, type=Path)
    parser.add_argument("--items-candidate", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    items_by_group = {"baseline": load_items(args.items_baseline),
                      "candidate": load_items(args.items_candidate)}
    key = json.loads(args.key.read_text(encoding="utf-8"))
    labels = {row["review_id"]: row["label"] for row in csv.DictReader(args.labels.open(encoding="utf-8"))}
    rows = join(items_by_group, key, labels)
    result = {
        "joined": len(rows),
        "unmatched": len(key) - len(rows),
        "groups": {group: group_stats([row for row in rows if row["group"] == group])
                   for group in items_by_group},
        "duplicate_titles": duplicate_titles(rows),
    }
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
