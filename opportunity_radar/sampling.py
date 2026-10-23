"""Deterministic time-window sampling for comparable shadow runs.

The first E2E comparison compared "the newest 30" from each group, which is not the same
as comparing the same period: a quiet source can reach back weeks while a busy one only
covers days. This module makes the window explicit and fixed in advance.

Rules:
  * a date-only bound means 00:00 UTC;
  * `since` is inclusive, `until` is exclusive;
  * an article with no usable publish time is outside every window — it cannot be shown
    to belong to the period being compared;
  * the caller keeps the interleaved (per-source) order, so slicing afterwards stays
    stratified by source.
"""
from datetime import datetime, timezone


def parse_bound(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) == 10:  # YYYY-MM-DD
        parsed = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    else:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
    return parsed


def parse_window(since: str = "", until: str = "") -> tuple[datetime | None, datetime | None]:
    start = parse_bound(since)
    end = parse_bound(until)
    if start and end and end <= start:
        raise ValueError("sample window: until must be after since")
    return start, end


def in_window(published: str, start: datetime | None, end: datetime | None) -> bool:
    if not start and not end:
        return True
    try:
        stamp = datetime.fromisoformat(str(published or ""))
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    stamp = stamp.astimezone(timezone.utc)
    if start and stamp < start:
        return False
    if end and stamp >= end:
        return False
    return True


def filter_articles(articles, start, end):
    """Keep order and identity; this only removes items outside the declared period."""
    if not start and not end:
        return list(articles)
    return [a for a in articles if in_window(getattr(a, "published", ""), start, end)]
