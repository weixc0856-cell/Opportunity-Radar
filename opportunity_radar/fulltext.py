"""Optional article-page body retrieval.

A feed that ships only a headline and a teaser caps its evidence at E1 forever. Fetching
the linked page can supply the body — but only under rules that are enforced here, not
documented and hoped for:

  * the source must opt in in the registry (`full_text_fetch=article_page`);
  * robots.txt is read first and respected for our user agent;
  * 401/403/429 stop the request; nothing is retried with a different identity;
  * a redirect to another host is refused (that is how login and paywall pages appear);
  * the extracted text is bounded and the container it came from is reported.

This module deliberately does **not** declare a source as full-text. `content_basis()`
still grants E2 only after a reviewer sets `content_access_level=full_text`; fetching a
body that later turns out to be truncated must not promote anything by itself.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

UA = "OpportunityRadar-FullText/0.1 (local personal research; contact: local user)"
MAX_BYTES = 600_000
DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|iframe|nav|header|footer|aside|form)\b[^>]*>.*?</\1\s*>",
    re.I | re.S)
ARTICLE = re.compile(r"<article\b[^>]*>(.*?)</article\s*>", re.I | re.S)
MAIN = re.compile(r"<main\b[^>]*>(.*?)</main\s*>", re.I | re.S)
BODY = re.compile(r"<body\b[^>]*>(.*?)</body\s*>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
DIV_OPEN = re.compile(r"<div\b[^>]*>", re.I)
DIV_TOKEN = re.compile(r"<div\b[^>]*>|</div\s*>", re.I)
CONTENT_DIV = re.compile(r"\b(id|role)\s*=\s*[\"']?(article|content|main)\b", re.I)
PAYWALL = re.compile(
    r"(subscribe to (continue|read)|sign in to continue|create a free account|"
    r"this (article|content) is (for|available to) subscribers|付费阅读|订阅后继续)", re.I)


def _to_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(TAG.sub(" ", fragment))).strip()


def _balanced_div(page: str, start: int) -> str:
    """Inner HTML of a div, counting nested divs. Regex-only parsing needs this."""
    depth = 0
    for match in DIV_TOKEN.finditer(page, start):
        if match.group(0).lower().startswith("</"):
            depth -= 1
            if depth == 0:
                return page[start:match.end()]
        else:
            depth += 1
    return page[start:]


def _content_div(page: str) -> str:
    for match in DIV_OPEN.finditer(page):
        if CONTENT_DIV.search(match.group(0)):
            return _balanced_div(page, match.start())
    return ""


def extract_main_text(page: str) -> tuple[str, str]:
    """Return (text, container). Prefer article, main, a content div, then body.

    Regex parsing is a deliberate trade: the project has no third-party HTML dependency,
    and this is review material, not a claim about the page's structure. The container is
    reported so a reviewer can see how much boilerplate may have leaked in.
    """
    cleaned = DROP_BLOCKS.sub(" ", page or "")
    for pattern, name in ((ARTICLE, "article"), (MAIN, "main")):
        match = pattern.search(cleaned)
        if match:
            text = _to_text(match.group(1))
            if len(text) >= 200:
                return text, name
    div = _content_div(cleaned)
    if div:
        text = _to_text(div)
        if len(text) >= 200:
            return text, "content-div"
    body = BODY.search(cleaned)
    return _to_text(body.group(1) if body else cleaned), "body"


def fetch_page(url: str, timeout: int = 20) -> tuple[int, str, str]:
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as response:
            body = response.read(MAX_BYTES)
            charset = response.headers.get_content_charset() or ""
            if not charset:
                match = re.search(rb'charset=["\']?([\w-]+)', body[:4096], re.I)
                if match:
                    charset = match.group(1).decode("ascii", "ignore")
            for encoding in (charset, "utf-8", "gb18030"):
                if not encoding:
                    continue
                try:
                    return response.status, body.decode(encoding), response.geturl()
                except (LookupError, UnicodeDecodeError):
                    continue
            return response.status, body.decode("utf-8", "replace"), response.geturl()
    except HTTPError as exc:
        return exc.code, "", url
    except (URLError, TimeoutError, OSError):
        return 0, "", url


class FullTextFetcher:
    """Fetches and extracts one article body, with robots and redirect checks."""

    def __init__(self, fetcher=None, max_chars: int = 12000, min_chars: int = 200):
        self._fetch = fetcher or fetch_page
        self.max_chars = max_chars
        self.min_chars = min_chars
        self._robots: dict[str, tuple[list | None, str]] = {}

    def _robot_rules(self, base: str):
        if base not in self._robots:
            from .page_monitor import parse_robots
            status, body, _ = self._fetch(urljoin(base, "/robots.txt"))
            if status == 404:
                self._robots[base] = ([], "robots.txt not found (404)")
            elif status != 200:
                self._robots[base] = (None, f"robots.txt returned HTTP {status}")
            else:
                rules = parse_robots(body, UA.lower())
                self._robots[base] = (rules, f"{len(rules)} applicable rule(s)")
        return self._robots[base]

    def fetch(self, url: str, include_html: bool = False) -> dict:
        parsed = urlparse(url or "")
        if parsed.scheme != "https" or not parsed.hostname:
            return {"ok": False, "status": "invalid_url"}
        base = f"{parsed.scheme}://{parsed.netloc}"
        rules, detail = self._robot_rules(base)
        if rules is None:
            return {"ok": False, "status": "robots_unavailable", "detail": detail}
        from .page_monitor import robots_allows
        if not robots_allows(rules, parsed.path or "/"):
            return {"ok": False, "status": "robots_disallowed", "detail": detail}
        status, page, final = self._fetch(url)
        if status in (401, 403, 429):
            return {"ok": False, "status": "blocked", "http": status}
        if status != 200:
            return {"ok": False, "status": "fetch_failed", "http": status}
        if (urlparse(final).hostname or "").lower() != (parsed.hostname or "").lower():
            return {"ok": False, "status": "cross_host_redirect", "final_url": final}
        text, container = extract_main_text(page)
        if len(text) < self.min_chars:
            return {"ok": False, "status": "too_short", "chars": len(text)}
        if PAYWALL.search(text[:2000]):
            return {"ok": False, "status": "paywall_suspected", "chars": len(text)}
        result = {"ok": True, "status": "fetched", "chars": len(text), "container": container,
                  "text": text[:self.max_chars], "final_url": final}
        if include_html:
            result["html"] = page  # audit only; never stored by the pipeline
        return result


def apply_article_bodies(articles, sources_by_feed, fetcher=None, cap: int = 20) -> int:
    """Replace feed summaries with fetched bodies for opted-in sources only.

    Returns the number of bodies applied. A failed fetch leaves the feed text untouched;
    nothing is retried, and the source's evidence declaration is not changed here.
    """
    import logging
    fetcher = fetcher or FullTextFetcher()
    applied = 0
    for article in articles:
        source = (sources_by_feed or {}).get(getattr(article, "feed_id", ""))
        if getattr(source, "full_text_fetch", "none") != "article_page":
            continue
        if applied >= cap:
            logging.warning("Full-text fetch cap reached; keeping feed text for the rest of this run.")
            break
        result = fetcher.fetch(article.url)
        if not result.get("ok"):
            logging.warning("Article body not fetched (%s): %s", result.get("status"), article.url)
            continue
        article.feed_summary = article.summary
        article.summary = result["text"]
        article.content_source = "article_page"
        article.retrieval_status = "fetched"
        applied += 1
        logging.info("Article body fetched: %s (%d chars, container=%s)",
                     article.url, result["chars"], result["container"])
    return applied


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Try extracting an article body (read-only, no storage)")
    parser.add_argument("--url", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = FullTextFetcher().fetch(args.url)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, indent=1))
    else:
        if result.get("ok"):
            print(f"[OK   ] {result['status']} · {result['chars']} chars · container={result['container']}")
            print("preview:", result["text"][:160])
        else:
            print(f"[{result['status'].upper()}] {result}")
    print("Note: a fetched body is not a reviewer decision; content_access_level stays unchanged.")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
