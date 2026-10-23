"""Structured macro datasets: a registry, not an article source.

A time series is not an article. It has a period, a unit, a seasonal adjustment and a
revision policy, and it cannot be scored by `scoring.py`. This module keeps those
datasets in their own registry so they are never faked into RSS rows.

What it does:
  * parses and validates `config/datasets.csv`;
  * probes an approved endpoint and prints the latest observed period and value, so a
    stale or mis-specified series is visible instead of silently reused.

What it does not do: store series, compute derived indicators, or decide whether a
number is meaningful. A dataset that has not had its reuse terms read stays
`license_status=unknown` and `status=blocked`.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "annual", "irregular"}
ACCESS_KINDS = {"api", "api_key", "download"}
LICENSE_STATUS = {"unknown", "confirmed_attribution", "confirmed_public_domain", "restricted"}
STATUSES = {"candidate", "approved", "blocked", "retired"}
API_KEY_PLACEHOLDER = "{API_KEY}"
UA = "OpportunityRadar-Datasets/0.1 (local personal research)"


@dataclass(frozen=True)
class Dataset:
    dataset_id: str = ""
    institution: str = ""
    name: str = ""
    access_kind: str = ""
    endpoint: str = ""
    homepage: str = ""
    indicator: str = ""
    unit: str = ""
    frequency: str = ""
    seasonality: str = ""
    latest_period: str = ""
    latest_value: str = ""
    latest_updated: str = ""
    last_checked_at: str = ""
    license_status: str = ""
    terms_url: str = ""
    quota_notes: str = ""
    status: str = ""
    notes: str = ""


FIELDS = [f.name for f in fields(Dataset)]


def _get(row: dict, key: str) -> str:
    return str(row.get(key) or "").strip()


def load_datasets(path: str | os.PathLike | None = None) -> list[Dataset]:
    p = Path(path or os.environ.get("OR_DATASETS_PATH") or "config/datasets.csv")
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        return [Dataset(**{k: _get(row, k) for k in FIELDS}) for row in csv.DictReader(fh)]


def _https(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme == "https" and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


def _iso(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def audit_datasets(datasets: list[Dataset], today: date | None = None) -> list[dict[str, str]]:
    """Return actionable registry issues. Permission is never inferred from reachability."""
    today = today or date.today()
    issues: list[dict[str, str]] = []
    seen: dict[str, int] = {}

    def add(dataset_id: str, severity: str, code: str, message: str) -> None:
        issues.append({"dataset_id": dataset_id or "(missing id)", "severity": severity,
                       "code": code, "message": message})

    for d in datasets:
        seen[d.dataset_id] = seen.get(d.dataset_id, 0) + 1
        if d.frequency not in FREQUENCIES:
            add(d.dataset_id, "error", "invalid_frequency",
                f"frequency must be one of: {', '.join(sorted(FREQUENCIES))}.")
        if d.access_kind not in ACCESS_KINDS:
            add(d.dataset_id, "error", "invalid_access_kind",
                f"access_kind must be one of: {', '.join(sorted(ACCESS_KINDS))}.")
        if d.license_status not in LICENSE_STATUS:
            add(d.dataset_id, "error", "invalid_license_status",
                f"license_status must be one of: {', '.join(sorted(LICENSE_STATUS))}.")
        if d.status not in STATUSES:
            add(d.dataset_id, "error", "invalid_status", f"status must be one of: {', '.join(sorted(STATUSES))}.")
        if not _https(d.endpoint):
            add(d.dataset_id, "error", "invalid_endpoint", "endpoint must be an HTTPS URL without credentials.")
        for key in ("last_checked_at", "latest_updated"):
            value = getattr(d, key)
            if value and not _iso(value):
                add(d.dataset_id, "error", f"invalid_{key}", f"{key} must be an ISO date.")
        if d.last_checked_at and _iso(d.last_checked_at) and date.fromisoformat(d.last_checked_at) > today:
            add(d.dataset_id, "error", "future_last_checked_at", "last_checked_at cannot be in the future.")
        if API_KEY_PLACEHOLDER in d.endpoint and d.status == "approved":
            add(d.dataset_id, "error", "placeholder_api_key_approved",
                "An endpoint still containing the API key placeholder cannot be approved.")
        if d.status == "approved":
            if d.license_status == "unknown":
                add(d.dataset_id, "error", "approved_without_license",
                    "Read the reuse terms and record license_status before approving a dataset.")
            if not _https(d.terms_url):
                add(d.dataset_id, "error", "missing_terms_url",
                    "An approved dataset needs the terms/reuse page it was approved under.")
            for key in ("indicator", "unit", "frequency", "latest_period"):
                if not getattr(d, key):
                    add(d.dataset_id, "error", f"missing_{key}",
                        f"An approved dataset must state its {key}; a bare number is not an indicator.")
            if not d.last_checked_at:
                add(d.dataset_id, "error", "missing_last_checked_at",
                    "Record when the endpoint was last observed before approving the dataset.")
        elif d.status == "blocked" and not d.notes:
            add(d.dataset_id, "warning", "blocked_without_reason",
                "A blocked dataset should say why it is blocked in notes.")

    for dataset_id, count in seen.items():
        if not dataset_id or count > 1:
            add(dataset_id, "error", "duplicate_or_missing_dataset_id",
                "Every dataset needs a unique, non-empty dataset_id.")
    if datasets and not any(d.status == "approved" for d in datasets):
        add("(registry)", "info", "no_approved_datasets", "No dataset is approved yet.")
    return issues


def jsonstat_latest(payload: dict) -> dict:
    """Latest time label and value from a JSON-stat 2.0 response, without guessing."""
    time_dim = (payload.get("dimension") or {}).get("time") or {}
    index = (time_dim.get("category") or {}).get("index") or {}
    if isinstance(index, list):  # JSON-stat also allows an ordered list of labels
        index = {label: i for i, label in enumerate(index)}
    if not index:
        raise ValueError("no time dimension in JSON-stat payload")
    latest_label = max(index, key=lambda label: index[label])
    latest_index = index[latest_label]
    values = payload.get("value") or {}
    value = values.get(str(latest_index)) if isinstance(values, dict) else None
    if value is None and isinstance(values, list) and latest_index < len(values):
        value = values[latest_index]
    return {"latest_period": latest_label, "latest_value": value,
            "updated": payload.get("updated", ""), "label": payload.get("label", "")}


def check_endpoint(url: str, timeout: int = 30) -> dict:
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as response:
            body = response.read(2_000_000)
            status = response.status
    except HTTPError as exc:
        return {"ok": False, "http": exc.code, "error": f"HTTP {exc.code}"}
    except (URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "http": 0, "error": type(exc).__name__}
    try:
        payload = json.loads(body)
    except ValueError:
        return {"ok": False, "http": status, "error": "response is not JSON"}
    if not isinstance(payload, dict):
        return {"ok": False, "http": status, "error": "JSON is not an object"}
    try:
        observed = jsonstat_latest(payload)
    except ValueError:
        return {"ok": False, "http": status, "error": "JSON is not JSON-stat 2.0"}
    return {"ok": True, "http": status, **observed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit and probe the macro dataset registry")
    parser.add_argument("--check", nargs="?", const="*", metavar="DATASET_ID",
                        help="probe approved dataset endpoints (optionally one dataset_id)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    datasets = load_datasets()
    issues = audit_datasets(datasets)
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    checks = []
    if args.check:
        for d in datasets:
            if args.check != "*" and d.dataset_id != args.check:
                continue
            if d.status != "approved":
                continue
            if d.access_kind == "api_key" and API_KEY_PLACEHOLDER in d.endpoint:
                checks.append({"dataset_id": d.dataset_id, "ok": False,
                               "error": "missing API key (endpoint placeholder was not substituted)"})
                continue
            checks.append({"dataset_id": d.dataset_id, **check_endpoint(d.endpoint)})

    if args.json:
        print(json.dumps({"datasets": len(datasets), "issues": issues, "checks": checks},
                         ensure_ascii=False, indent=1))
    else:
        print(f"Datasets: {len(datasets)} rows; {sum(d.status == 'approved' for d in datasets)} approved; "
              f"{len(errors)} errors; {len(warnings)} warnings")
        for issue in issues:
            print(f"[{issue['severity'].upper():7}] {issue['dataset_id']} · {issue['code']}: {issue['message']}")
        for check in checks:
            if check.get("ok"):
                print(f"[OK     ] {check['dataset_id']}: latest {check['latest_period']} = {check['latest_value']} "
                      f"(dataset updated {check.get('updated') or '未记录'})")
            else:
                print(f"[FAIL   ] {check['dataset_id']}: {check.get('error')}")
        print("Note: a successful read proves the endpoint responds, not that the series is the right indicator, "
              "current, revised, or licensed for redistribution.")
    failed = bool(errors) or any(not c.get("ok") for c in checks)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
