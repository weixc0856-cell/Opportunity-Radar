#!/usr/bin/env python3
"""Prepare and score a blinded review of two shadow runs.

`prepare` strips source/URL/group, shuffles with a fixed seed and writes blind.csv plus a
key.json. `score` joins labels back to groups. The reviewer must finish labelling before
opening key.json — the tool cannot enforce that, the protocol does.

Usage:
    python tools/blind_review.py prepare \
        --baseline reports/.../x.items.json --candidate reports/.../y.items.json \
        --out-dir data/review --seed 20261023
    python tools/blind_review.py score --out-dir data/review
"""
import argparse
import csv
import json
import random
import sys
from pathlib import Path

LABELS = {"actionable", "weak", "noise"}


def load_items(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")).get("items", [])


def prepare(baseline: Path, candidate: Path, out_dir: Path, seed: int = 20261023) -> dict:
    rows = []
    for group, path in (("baseline", baseline), ("candidate", candidate)):
        for item in load_items(path):
            analysis = item.get("analysis") or {}
            rows.append({
                "group": group,
                "source": item.get("source_name", ""),
                "title": item.get("title", ""),
                "summary": (analysis.get("summary_zh") or "").strip(),
                "evidence": item.get("evidence_rank") or item.get("evidence_level") or "",
                "status": item.get("status", ""),
            })
    random.Random(seed).shuffle(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    key, blind = {}, []
    for index, row in enumerate(rows, 1):
        review_id = f"r{index:03d}"
        key[review_id] = {k: row[k] for k in ("group", "source", "title", "status")}
        blind.append({"review_id": review_id, "title": row["title"],
                      "summary": row["summary"], "evidence": row["evidence"]})
    (out_dir / "blind.csv").write_text(_csv(blind, ["review_id", "title", "summary", "evidence"]), encoding="utf-8")
    (out_dir / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    template = [{"review_id": row["review_id"], "label": "", "note": ""} for row in blind]
    (out_dir / "labels.csv").write_text(_csv(template, ["review_id", "label", "note"]), encoding="utf-8")
    return {"rows": len(blind), "out_dir": str(out_dir), "seed": seed}


def _csv(rows, fields):
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def score(out_dir: Path) -> dict:
    key = json.loads((out_dir / "key.json").read_text(encoding="utf-8"))
    labels = {row["review_id"]: row for row in csv.DictReader((out_dir / "labels.csv").open(encoding="utf-8"))}
    missing = [rid for rid in key if not (labels.get(rid, {}).get("label") or "").strip()]
    bad = [rid for rid, row in labels.items() if (row.get("label") or "").strip() and row["label"].strip() not in LABELS]
    if missing or bad:
        raise SystemExit(f"Incomplete review: {len(missing)} unlabelled, {len(bad)} invalid labels "
                         f"(allowed: {', '.join(sorted(LABELS))})")
    summary = {}
    for rid, meta in key.items():
        group = meta["group"]
        bucket = summary.setdefault(group, {"actionable": 0, "weak": 0, "noise": 0, "total": 0})
        bucket[labels[rid]["label"].strip()] += 1
        bucket["total"] += 1
    for bucket in summary.values():
        bucket["actionable_share"] = round(bucket["actionable"] / bucket["total"], 3) if bucket["total"] else None
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Blind review helper")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--baseline", required=True, type=Path)
    prep.add_argument("--candidate", required=True, type=Path)
    prep.add_argument("--out-dir", required=True, type=Path)
    prep.add_argument("--seed", type=int, default=20261023)
    score_p = sub.add_parser("score")
    score_p.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        print(json.dumps(prepare(args.baseline, args.candidate, args.out_dir, args.seed), ensure_ascii=False))
        print("Label blind.csv into labels.csv, then run `score`.")
        return 0
    print(json.dumps(score(args.out_dir), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
