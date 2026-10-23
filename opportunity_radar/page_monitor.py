"""Page-change monitoring for official sites that publish no feed.

This is deliberately not a crawler. It watches a short, explicit whitelist of pages,
extracts the links that look like publication entries, fingerprints them, and reports
what is new since the previous observation. It stores only link metadata — never article
bodies — so the traceability chain stays "page → link → original document".

Safety rules that are enforced, not documented:
  * a page is only fetched after robots.txt allows it for our user agent;
  * a 401/403/429 response stops the watch; no retry, no user-agent games;
  * a check happens no more often than the page's declared interval;
  * a page that suddenly yields fewer links than `min_links` is reported as a structure
    change and its previous fingerprint is kept, so a redesign cannot silently erase
    history or manufacture "new" items on the next run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

UA = "OpportunityRadar-PageWatch/0.1 (local personal research; contact: local user)"
UA_TOKEN = UA.lower()  # robots groups match when their agent string appears in our UA
MAX_BYTES = 600_000
TIMEOUT = 25
STATUSES = {"candidate", "approved", "blocked", "retired"}


@dataclass(frozen=True)
class Watch:
    watch_id: str = ""
    institution: str = ""
    name: str = ""
    url: str = ""
    include_pattern: str = ""
    exclude_pattern: str = ""
    min_links: str = "5"
    min_interval_hours: str = "6"
    terms_url: str = ""
    status: str = "candidate"
    notes: str = ""


WATCH_FIELDS = [f.name for f in fields(Watch)]


def _get(row, key):
    return str(row.get(key) or "").strip()


def load_watchlist(path=None) -> list[Watch]:
    p = Path(path or os.environ.get("OR_PAGE_WATCH_PATH") or "config/page_watch.csv")
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        return [Watch(**{k: _get(row, k) for k in WATCH_FIELDS}) for row in csv.DictReader(fh)]


def audit_watchlist(watches: list[Watch]) -> list[dict[str, str]]:
    issues = []
    seen = {}
    for w in watches:
        seen[w.watch_id] = seen.get(w.watch_id, 0) + 1
        if w.status not in STATUSES:
            issues.append({"watch_id": w.watch_id, "severity": "error", "code": "invalid_status",
                           "message": f"status must be one of: {', '.join(sorted(STATUSES))}."})
        parsed = urlparse(w.url)
        if parsed.scheme != "https" or not parsed.hostname:
            issues.append({"watch_id": w.watch_id, "severity": "error", "code": "invalid_url",
                           "message": "Only explicit HTTPS pages can be watched."})
        try:
            int(w.min_links)
        except ValueError:
            issues.append({"watch_id": w.watch_id, "severity": "error", "code": "invalid_min_links",
                           "message": "min_links must be an integer."})
        try:
            if float(w.min_interval_hours) < 1:
                raise ValueError
        except ValueError:
            issues.append({"watch_id": w.watch_id, "severity": "error", "code": "invalid_interval",
                           "message": "min_interval_hours must be a number >= 1."})
    for watch_id, count in seen.items():
        if not watch_id or count > 1:
            issues.append({"watch_id": watch_id, "severity": "error", "code": "duplicate_or_missing_id",
                           "message": "Every watch needs a unique, non-empty watch_id."})
    return issues


# ---------------------------------------------------------------- robots.txt

def parse_robots(text: str, token: str = UA_TOKEN) -> list[tuple[bool, str]]:
    """Return the (allow, path) rules that apply to `token`.

    Longest matching path wins; an empty rule set means allowed. Comments and unknown
    fields are ignored, Sitemap is not a rule.
    """
    groups: list[dict] = []
    current = {"agents": [], "rules": []}
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if not last_was_agent:
                if current["agents"] or current["rules"]:
                    groups.append(current)
                current = {"agents": [], "rules": []}
            current["agents"].append(value.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if key in ("allow", "disallow") and current["agents"]:
            if value:
                current["rules"].append((key == "allow", value))
    if current["agents"] or current["rules"]:
        groups.append(current)
    applicable = [g for g in groups if any(a != "*" and a in token for a in g["agents"])]
    if not applicable:
        applicable = [g for g in groups if "*" in g["agents"]]
    rules: list[tuple[bool, str]] = []
    for group in applicable:
        rules.extend(group["rules"])
    return rules


def robots_allows(rules: list[tuple[bool, str]], path: str) -> bool:
    best_len = -1
    allowed = True
    for allow, rule_path in rules:
        if rule_path == "/" or path.startswith(rule_path.rstrip("*")):
            if len(rule_path) >= best_len:
                best_len = len(rule_path)
                allowed = allow
    return allowed


def robots_check(base_url: str, path: str, opener=None) -> tuple[bool, str]:
    """Return (allowed, detail). Fail closed on 401/403/5xx: we do not guess."""
    opener = opener or _fetch_text
    robots_url = urljoin(base_url, "/robots.txt")
    status, body = opener(robots_url)
    if status == 404:
        return True, "robots.txt not found (404); no rules declared"
    if status != 200:
        return False, f"robots.txt returned HTTP {status}; treating as not authorised"
    rules = parse_robots(body, UA_TOKEN)
    return robots_allows(rules, path), f"{len(rules)} applicable rule(s)"


# ---------------------------------------------------------------- fetching

def _decode(body: bytes, headers) -> str:
    """Decode with the declared charset, then meta charset, then UTF-8, then GB18030.

    Chinese ministry sites often serve GB2312/GBK bytes with no charset in the header;
    guessing UTF-8 first produced replacement characters instead of titles.
    """
    charset = ""
    try:
        charset = headers.get_content_charset() or ""
    except AttributeError:
        charset = ""
    if not charset:
        match = re.search(rb'charset=["\']?([\w-]+)', body[:4096], re.I)
        if match:
            charset = match.group(1).decode("ascii", "ignore")
    for encoding in (charset, "utf-8", "gb18030"):
        if not encoding:
            continue
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def _fetch_text(url: str, timeout: int = TIMEOUT) -> tuple[int, str]:
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as response:
            body = response.read(MAX_BYTES)
            return response.status, _decode(body, response.headers)
    except HTTPError as exc:
        return exc.code, ""
    except (URLError, TimeoutError, OSError):
        return 0, ""


ANCHOR_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def extract_links(html: str, page_url: str, include: str = "", exclude: str = "") -> list[dict]:
    """Publication-like links on a listing page, as (url, title), de-duplicated.

    The page is untrusted: only http(s) URLs on the same host survive, fragments and
    tracking-free duplicates are collapsed, and titles are flattened to text.
    """
    host = (urlparse(page_url).hostname or "").lower()

    def same_site(candidate: str) -> bool:
        # Same host, or one is the parent/subdomain of the other. This covers
        # www/non-www and language subdomains without admitting unrelated sites.
        return candidate == host or candidate.endswith("." + host) or host.endswith("." + candidate)

    seen, out = {}, []
    for match in ANCHOR_RE.finditer(html):
        href, inner = match.group(1).strip(), TAG_RE.sub(" ", match.group(2))
        title = re.sub(r"\s+", " ", inner).strip()
        if not title or len(title) < 4:
            continue
        absolute = urljoin(page_url, href).split("#")[0]
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if not same_site((parsed.hostname or "").lower()):
            continue
        if include and not re.search(include, f"{absolute} {title}", re.I):
            continue
        if exclude and re.search(exclude, f"{absolute} {title}", re.I):
            continue
        # A listing page often repeats one URL in a summary block with a truncated title.
        # Keep one entry per URL and prefer the longer (less truncated) title.
        prior = seen.get(absolute)
        if prior is not None:
            if len(title) > len(prior["title"]):
                prior["title"] = title
            continue
        item = {"url": absolute, "title": title}
        seen[absolute] = item
        out.append(item)
    return out


def fingerprint(items: list[dict]) -> str:
    joined = "\n".join(sorted(f"{item['url']}\t{item['title']}" for item in items))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- state

def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS page_watch_state(
        watch_id TEXT PRIMARY KEY, fingerprint TEXT, item_count INTEGER, checked_at TEXT,
        http_status INTEGER, status TEXT, error TEXT, page_url TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS page_watch_items(
        watch_id TEXT NOT NULL, item_url TEXT NOT NULL, title TEXT, first_seen_at TEXT NOT NULL,
        page_url TEXT, PRIMARY KEY(watch_id, item_url))""")
    conn.commit()
    return conn


def _db_path() -> str:
    return os.environ.get("OR_DB_PATH") or "data/opportunity_radar.sqlite3"


def _last_check(conn, watch_id: str) -> datetime | None:
    row = conn.execute("SELECT checked_at FROM page_watch_state WHERE watch_id=?", (watch_id,)).fetchone()
    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(row[0])
    except ValueError:
        return None


def check_watch(watch: Watch, conn: sqlite3.Connection, now: datetime | None = None,
                fetcher=None, robots=None) -> dict:
    """Observe one page and persist the outcome. Returns a machine-readable result."""
    now = now or datetime.now(timezone.utc)
    fetcher = fetcher or _fetch_text
    robots = robots or robots_check
    result = {"watch_id": watch.watch_id, "url": watch.url, "checked_at": now.isoformat(timespec="seconds")}

    if watch.status != "approved":
        # 'blocked' means a reviewer already found the page unusable; keep that distinct
        # from 'candidate', which simply has not been approved yet.
        status = "blocked" if watch.status == "blocked" else "not_approved"
        return {**result, "status": status}
    last = _last_check(conn, watch.watch_id)
    if last and now - last < timedelta(hours=float(watch.min_interval_hours)):
        return {**result, "status": "skipped_interval", "last_checked_at": last.isoformat(timespec="seconds")}

    parsed = urlparse(watch.url)
    allowed, detail = robots(f"{parsed.scheme}://{parsed.netloc}", parsed.path, fetcher)
    result["robots"] = detail
    if not allowed:
        _save_state(conn, watch, result, fingerprint_=None, item_count=None, http_status=0,
                    status="robots_disallowed", error=detail)
        return {**result, "status": "robots_disallowed", "error": detail}

    status, html = fetcher(watch.url)
    result["http"] = status
    if status in (401, 403, 429):
        _save_state(conn, watch, result, None, None, status, "blocked", f"HTTP {status}")
        return {**result, "status": "blocked", "error": f"HTTP {status}; not retried"}
    if status == 404:
        _save_state(conn, watch, result, None, None, status, "not_found", "HTTP 404")
        return {**result, "status": "not_found", "error": "HTTP 404"}
    if status != 200:
        _save_state(conn, watch, result, None, None, status, "fetch_failed", f"HTTP {status}")
        return {**result, "status": "fetch_failed", "error": f"HTTP {status}"}

    items = extract_links(html, watch.url, watch.include_pattern, watch.exclude_pattern)
    result["items"] = len(items)
    if len(items) < int(watch.min_links):
        # Keep the previous fingerprint: a redesign must not look like "everything is new".
        previous = conn.execute("SELECT fingerprint FROM page_watch_state WHERE watch_id=?",
                                (watch.watch_id,)).fetchone()
        _save_state(conn, watch, result, previous[0] if previous else None, len(items), status,
                    "structure_changed", f"only {len(items)} links, expected >= {watch.min_links}")
        return {**result, "status": "structure_changed", "error": f"only {len(items)} links"}

    current = fingerprint(items)
    row = conn.execute("SELECT fingerprint FROM page_watch_state WHERE watch_id=?", (watch.watch_id,)).fetchone()
    previous = row[0] if row else None
    new_items = []
    if previous != current:
        for item in items:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO page_watch_items(watch_id,item_url,title,first_seen_at,page_url) "
                "VALUES(?,?,?,?,?)",
                (watch.watch_id, item["url"], item["title"], now.isoformat(timespec="seconds"), watch.url))
            if cursor.rowcount:
                new_items.append({**item, "page_url": watch.url})
    conn.commit()
    _save_state(conn, watch, result, current, len(items), 200,
                "new_items" if new_items else "unchanged", "")
    return {**result, "status": "new_items" if new_items else "unchanged", "new_items": new_items}


def _save_state(conn, watch, result, fingerprint_, item_count, http_status, status, error):
    conn.execute("""INSERT INTO page_watch_state(watch_id,fingerprint,item_count,checked_at,http_status,status,error,page_url)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(watch_id) DO UPDATE SET fingerprint=excluded.fingerprint,item_count=excluded.item_count,
        checked_at=excluded.checked_at,http_status=excluded.http_status,status=excluded.status,
        error=excluded.error,page_url=excluded.page_url""",
                 (watch.watch_id, fingerprint_, item_count, result["checked_at"], http_status, status, error,
                  watch.url))
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    try:  # Chinese titles must survive redirection on Windows (cp936 default).
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Check whitelisted official pages for new items")
    parser.add_argument("--watch-id", help="limit to one watch_id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    watches = load_watchlist()
    issues = audit_watchlist(watches)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        for issue in errors:
            print(f"[ERROR] {issue['watch_id']} · {issue['code']}: {issue['message']}", file=sys.stderr)
        return 2
    conn = init_db(_db_path())
    results = []
    for watch in watches:
        if args.watch_id and watch.watch_id != args.watch_id:
            continue
        results.append(check_watch(watch, conn))
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        print(f"Page watches: {len(watches)} rows; {sum(w.status == 'approved' for w in watches)} approved")
        for r in results:
            line = f"[{r['status'].upper():17}] {r['watch_id']}: {r.get('error') or r.get('items', '')}"
            print(line)
            for item in r.get("new_items") or []:
                print(f"    new: {item['title']} -> {item['url']}")
        print("Note: link presence is not a publication event; open the original page before treating it as one.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
