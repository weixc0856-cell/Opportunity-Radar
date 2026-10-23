"""Audit source-registry completeness. Reachability is not proof of permission or truth."""
from __future__ import annotations
import argparse
import re
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from .config import load_dotenv
from .source_policy import Source, is_approved, load_sources

MAX_REVIEW_AGE_DAYS = 180
ALLOWED_PROVENANCE = {"first_party", "project_record", "secondhand_report", "vendor_marketing", "unknown"}
# A source must be given an editorial job, not just an access method. Legal access does
# not establish that a feed belongs in the business briefing.
ALLOWED_LANES = {"A", "B", "C"}
ALLOWED_ACCESS = {"auto", "full_text", "excerpt", "title_only"}
MAX_SOURCE_CAP = 50


def editorial_lanes(value: str) -> set[str]:
    return {token for token in re.split(r"[\s,;|/]+", str(value or "").upper()) if token}


def _https(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme == "https" and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


def audit_sources(sources: list[Source], today: date | None = None) -> list[dict[str, str]]:
    """Return actionable registry issues; this function does not make legal determinations."""
    today = today or date.today()
    issues: list[dict[str, str]] = []
    ids: dict[str, int] = {}
    feed_ids: dict[str, str] = {}

    def add(source: str, severity: str, code: str, message: str) -> None:
        issues.append({"source_id": source or "(missing id)", "severity": severity, "code": code, "message": message})

    for s in sources:
        ids[s.source_id] = ids.get(s.source_id, 0) + 1
        lanes = editorial_lanes(s.editorial_lanes)
        unknown = lanes - ALLOWED_LANES
        if unknown:
            add(s.source_id, "error", "invalid_editorial_lane",
                f"Unknown editorial lane(s): {', '.join(sorted(unknown))}. Use A, B or C.")
        if s.content_access_level not in ALLOWED_ACCESS:
            add(s.source_id, "error", "invalid_content_access_level",
                "content_access_level must be auto, full_text, excerpt or title_only; evidence cannot be graded without it.")
        if s.source_cap < 0 or s.source_cap > MAX_SOURCE_CAP:
            add(s.source_id, "error", "invalid_source_cap",
                f"source_cap must be a whole number from 0 (uncapped) to {MAX_SOURCE_CAP}.")
        if s.enabled:
            if not lanes:
                add(s.source_id, "error", "missing_editorial_lanes",
                    "Assign the source to at least one editorial lane (A, B or C) before enabling it.")
            if s.freshrss_feed_id:
                previous = feed_ids.get(s.freshrss_feed_id)
                if previous:
                    add(s.source_id, "error", "duplicate_feed_id", f"Feed ID {s.freshrss_feed_id} is also assigned to {previous}.")
                else:
                    feed_ids[s.freshrss_feed_id] = s.source_id
            if not is_approved(s):
                add(s.source_id, "error", "not_approved", "Enabled source must be approved, use HTTPS, use an allowed access method and map to a FreshRSS feed ID.")
            for field, value in (("homepage", s.homepage), ("feed_url", s.feed_url), ("terms_url", s.terms_url)):
                if not _https(value):
                    add(s.source_id, "error", f"invalid_{field}", f"{field} must be an HTTPS URL without embedded credentials.")
            if not s.canonical_domain:
                add(s.source_id, "error", "missing_canonical_domain", "Declare the expected source domain or source-owner domain.")
            try:
                feed_host = (urlparse(s.feed_url).hostname or '').lower()
                owner_host = s.canonical_domain.lower().removeprefix('www.')
                same_owner = feed_host == owner_host or feed_host.endswith('.' + owner_host)
                if feed_host and not same_owner:
                    if not s.feed_provider:
                        add(s.source_id, "error", "missing_feed_provider", "Feed host differs from the source-owner domain; identify the feed provider/bridge.")
                    if not _https(s.feed_provider_terms_url):
                        add(s.source_id, "error", "missing_feed_provider_terms", "Feed host differs from the source-owner domain; review and record the provider's terms URL before enabling.")
            except ValueError:
                pass
            if s.provenance_class not in ALLOWED_PROVENANCE or not s.provenance_class:
                add(s.source_id, "error", "invalid_provenance", "Declare how the content originated (user statement, project record, secondhand report, etc.).")
            for field, value in (("reviewed_at", s.reviewed_at), ("last_verified_at", s.last_verified_at)):
                try:
                    stamp = date.fromisoformat(value)
                    if stamp > today:
                        add(s.source_id, "error", f"future_{field}", f"{field} cannot be in the future.")
                    elif (today - stamp).days > MAX_REVIEW_AGE_DAYS:
                        add(s.source_id, "error", f"stale_{field}", f"{field} is older than {MAX_REVIEW_AGE_DAYS} days; re-review before use.")
                except (TypeError, ValueError):
                    add(s.source_id, "error", f"missing_{field}", f"Set {field} only after the corresponding manual review has actually occurred.")
        elif s.permission_status == "approved":
            # Do not block an inactive row, but make stale claims visible to maintainers.
            if not s.reviewed_at or not s.last_verified_at:
                add(s.source_id, "warning", "approval_without_review_dates", "Inactive row says approved but has no review dates; do not enable until verified.")

    for source_id, count in ids.items():
        if not source_id or count > 1:
            add(source_id, "error", "duplicate_or_missing_source_id", "Every source needs a unique, non-empty source_id.")
    if not any(s.enabled for s in sources):
        add("(registry)", "info", "no_enabled_sources", "All sources are disabled. This is the safe repository default; review and enable sources locally when ready.")
    return issues


def check_url(url: str, timeout: int = 8) -> tuple[bool, str]:
    """Check URL reachability only. A 200 response is not proof of source authenticity or permission."""
    if not _https(url):
        return False, "not a valid HTTPS URL"
    request = Request(url, headers={"User-Agent": "OpportunityRadar-SourceAudit/0.1"}, method="HEAD")
    try:
        with urlopen(request, timeout=timeout) as response:
            final = response.geturl()
            if not _https(final):
                return False, "redirected away from HTTPS"
            return 200 <= response.status < 400, f"HTTP {response.status}; final URL {final}"
    except HTTPError as exc:
        if exc.code not in {403, 405, 501}:
            return False, f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError) as exc:
        return False, f"request failed: {type(exc).__name__}"
    # Some sites reject HEAD; retry a bounded GET and read no article body.
    request = Request(url, headers={"User-Agent": "OpportunityRadar-SourceAudit/0.1", "Range": "bytes=0-0"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            final = response.geturl()
            if not _https(final):
                return False, "redirected away from HTTPS"
            return 200 <= response.status < 400, f"HTTP {response.status}; final URL {final}"
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        code = getattr(exc, "code", None)
        return False, f"request failed: HTTP {code}" if code else f"request failed: {type(exc).__name__}"


def url_targets(source: Source) -> list[tuple[str, str]]:
    """Only check URLs that are actually declared; an unused provider field is not a failure."""
    candidates = (("homepage", source.homepage), ("feed", source.feed_url),
                  ("terms", source.terms_url), ("feed_provider_terms", source.feed_provider_terms_url))
    return [(label, url) for label, url in candidates if url]

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the Opportunity Radar source registry")
    parser.add_argument("--check-urls", action="store_true", help="make explicit HTTPS reachability checks for enabled source homepage/feed/terms URLs")
    args = parser.parse_args(argv)
    load_dotenv()
    sources = load_sources()
    issues = audit_sources(sources)
    errors = sum(i["severity"] == "error" for i in issues)
    warnings = sum(i["severity"] == "warning" for i in issues)
    print(f"Source registry: {len(sources)} rows; {sum(s.enabled for s in sources)} enabled; {errors} errors; {warnings} warnings")
    for issue in issues:
        print(f"[{issue['severity'].upper():7}] {issue['source_id']} · {issue['code']}: {issue['message']}")
    if args.check_urls:
        for source in sources:
            if not source.enabled:
                continue
            for label, url in url_targets(source):
                ok, detail = check_url(url)
                print(f"[{'OK' if ok else 'FAIL':7}] {source.source_id} · {label}: {detail}")
                if not ok:
                    errors += 1
    print("Note: URL reachability does not establish legal permission, ownership, content accuracy, or permission to retain/redistribute content.")
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
