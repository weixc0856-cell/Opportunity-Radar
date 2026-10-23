#!/usr/bin/env python3
"""Full-text completeness audit for one source (read-only).

Samples 3 articles by feed-summary length, fetches each page through the same
robots-respecting fetcher the pipeline uses, and compares feed text with page text:

  * title present on the page
  * how many 60-character windows of the feed summary appear in the page text
  * page/feed length ratio, extraction container
  * page date metadata vs feed publish date
  * failures: robots, 401/403/429, cross-host redirect, short body, paywall marker

Technical pass criteria (pre-declared, 3 samples):
  - 3/3 fetch ok
  - >=2/3 container in article/main/content-div
  - >=2/3 windows_hit >= 3/5
  - >=2/3 page_chars >= max(600, 1.5 x feed_chars)
  - >=2/3 title present
  - 0 paywall/JS blocks

Technical pass does NOT authorise enabling: the terms must be read separately.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opportunity_radar.config import Settings  # noqa: E402
from opportunity_radar.freshrss_client import FreshRSSClient  # noqa: E402
from opportunity_radar.fulltext import FullTextFetcher  # noqa: E402

DATE_PATTERNS = [
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'property=["\']article:published_time["\']\s+content=["\']([^"\']+)', re.I),
    re.compile(r'<time[^>]+datetime=["\']([^"\']+)', re.I),
]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def windows(feed: str, size: int = 60, count: int = 5) -> list[str]:
    body = norm(feed)
    if len(body) < size:
        return [body] if body else []
    usable = int(len(body) * 0.9)
    starts = [int(i * (usable - size) / max(1, count - 1)) for i in range(count)]
    return [body[s:s + size] for s in starts]


def page_date(html: str) -> str:
    for pattern in DATE_PATTERNS:
        match = pattern.search(html or "")
        if match:
            return match.group(1)[:19]
    return ""


def pick(articles: list, count: int = 3) -> list:
    ordered = sorted(articles, key=lambda a: len(a.summary))
    if len(ordered) <= count:
        return ordered
    picks = []
    for i in range(count):
        index = round(i * (len(ordered) - 1) / (count - 1))
        picks.append(ordered[index])
    return picks


def audit(source_id: str, feed_id: str, samples: int = 3) -> dict:
    settings = Settings.from_env()
    client = FreshRSSClient(settings.freshrss_base_url, settings.freshrss_username,
                            settings.freshrss_api_key, settings.request_timeout)
    articles = client._fetch_feed(feed_id)
    chosen = pick(articles, samples)
    fetcher = FullTextFetcher()
    rows = []
    for article in chosen:
        feed_text = norm(article.summary)
        result = fetcher.fetch(article.url, include_html=True)
        row = {
            "title": article.title,
            "url": article.url,
            "feed_published": article.published[:10],
            "feed_chars": len(feed_text),
            "status": result.get("status"),
        }
        if not result.get("ok"):
            row.update({"page_chars": 0, "windows_hit": "0/5", "title_in_page": False})
            rows.append(row)
            continue
        page_text = result["text"]
        # The title often sits outside the extracted container (e.g. <h1> before <article>),
        # so the presence check uses the whole page, not just the extract.
        full_page = norm(re.sub(r"<[^>]+>", " ", result.get("html", "")))
        wins = windows(feed_text)
        hits = sum(1 for w in wins if w and w in page_text)
        meta_date = page_date(result.get("html", ""))
        row.update({
            "page_chars": result["chars"],
            "ratio": round(result["chars"] / len(feed_text), 2) if feed_text else None,
            "container": result["container"],
            "title_in_page": norm(article.title).lower() in full_page.lower(),
            "windows_hit": f"{hits}/{len(wins)}",
            "page_date": meta_date,
            "date_match": (meta_date[:10] == article.published[:10]) if meta_date else None,
            "tail": page_text[-90:],
        })
        rows.append(row)

    ok = sum(1 for r in rows if r.get("status") == "fetched")
    container_ok = sum(1 for r in rows if r.get("container") in {"article", "main", "content-div"})
    windows_ok = sum(1 for r in rows if r.get("windows_hit", "0/0") != "0/0"
                     and int(r["windows_hit"].split("/")[0]) >= 3)
    length_ok = sum(1 for r in rows if r.get("ratio") is not None
                    and r["page_chars"] >= max(600, 1.5 * r["feed_chars"]))
    title_ok = sum(1 for r in rows if r.get("title_in_page"))
    blocked = sum(1 for r in rows if r.get("status") in {"paywall_suspected", "too_short"})
    technical_pass = (ok == len(rows) and container_ok >= 2 and windows_ok >= 2
                      and length_ok >= 2 and title_ok >= 2 and blocked == 0)
    return {
        "source_id": source_id, "feed_id": feed_id,
        "samples": rows,
        "summary": {"ok": ok, "container_ok": container_ok, "windows_ok": windows_ok,
                    "length_ok": length_ok, "title_ok": title_ok, "blocked": blocked,
                    "total": len(rows)},
        "technical_pass": technical_pass,
        "license_status": "unknown (terms not read)",
        "decision": "technical pass; licence unread -> keep full_text_fetch=none" if technical_pass
                    else "technical criteria not met -> keep full_text_fetch=none",
    }


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Full-text completeness audit for one source")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--feed-id", required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.source_id, args.feed_id, args.samples)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
