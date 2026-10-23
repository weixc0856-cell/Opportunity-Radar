import unittest
from datetime import date

import tempfile
from pathlib import Path

from opportunity_radar.fulltext import FullTextFetcher, extract_main_text
from opportunity_radar.source_audit import audit_sources
from opportunity_radar.source_policy import Source, load_sources

PAGE = ("<html><body><nav>Menu Home About</nav>"
        "<article><h1>Title</h1><p>" + "Body sentence. " * 40 + "</p>"
        "<script>track()</script></article><footer>Copyright</footer></body></html>")
ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"
ROBOTS_DENY = "User-agent: *\nDisallow: /\n"


def fetcher(routes, calls=None):
    def _fetch(url, timeout=20):
        if calls is not None:
            calls.append(url)
        return routes.get(url, (404, "", url))
    return _fetch


class ExtractTests(unittest.TestCase):
    def test_prefers_article_and_drops_script_and_nav(self):
        text, container = extract_main_text(PAGE)
        self.assertEqual(container, "article")
        self.assertIn("Body sentence.", text)
        self.assertNotIn("Menu Home", text)
        self.assertNotIn("track()", text)
        self.assertNotIn("Copyright", text)

    def test_falls_back_to_body(self):
        text, container = extract_main_text("<html><body><p>" + "x " * 300 + "</p></body></html>")
        self.assertEqual(container, "body")
        self.assertGreater(len(text), 200)

    def test_empty_page_is_empty(self):
        text, container = extract_main_text("")
        self.assertEqual((text, container), ("", "body"))

    def test_content_div_excludes_the_footer(self):
        page = ('<html><body><div id="content"><div><p>' + "Body text. " * 40 +
                '</p></div></div><div id="footer">Noise</div></body></html>')
        text, container = extract_main_text(page)
        self.assertEqual(container, "content-div")
        self.assertIn("Body text.", text)
        self.assertNotIn("Noise", text)


class FetcherTests(unittest.TestCase):
    URL = "https://example.org/news/item-1"

    def make(self, routes, **kwargs):
        calls = []
        client = FullTextFetcher(fetcher=fetcher(routes, calls), **kwargs)
        return client, calls

    def test_success_returns_body_and_container(self):
        client, _ = self.make({
            "https://example.org/robots.txt": (200, ROBOTS_ALLOW, "https://example.org/robots.txt"),
            self.URL: (200, PAGE, self.URL),
        })
        result = client.fetch(self.URL)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "fetched")
        self.assertEqual(result["container"], "article")

    def test_robots_disallow_prevents_the_page_request(self):
        client, calls = self.make({
            "https://example.org/robots.txt": (200, ROBOTS_DENY, "https://example.org/robots.txt"),
        })
        result = client.fetch(self.URL)
        self.assertEqual(result["status"], "robots_disallowed")
        self.assertNotIn(self.URL, calls)

    def test_missing_robots_allows(self):
        client, _ = self.make({
            "https://example.org/robots.txt": (404, "", "https://example.org/robots.txt"),
            self.URL: (200, PAGE, self.URL),
        })
        self.assertTrue(client.fetch(self.URL)["ok"])

    def test_blocked_status_is_not_retried(self):
        client, calls = self.make({
            "https://example.org/robots.txt": (200, ROBOTS_ALLOW, "https://example.org/robots.txt"),
            self.URL: (403, "", self.URL),
        })
        result = client.fetch(self.URL)
        self.assertEqual((result["status"], result["http"]), ("blocked", 403))
        self.assertEqual(calls.count(self.URL), 1)

    def test_cross_host_redirect_is_refused(self):
        client, _ = self.make({
            "https://example.org/robots.txt": (200, ROBOTS_ALLOW, "https://example.org/robots.txt"),
            self.URL: (200, PAGE, "https://login.elsewhere.example/signin"),
        })
        self.assertEqual(client.fetch(self.URL)["status"], "cross_host_redirect")

    def test_short_page_is_refused(self):
        client, _ = self.make({
            "https://example.org/robots.txt": (200, ROBOTS_ALLOW, "https://example.org/robots.txt"),
            self.URL: (200, "<html><body>tiny</body></html>", self.URL),
        })
        self.assertEqual(client.fetch(self.URL)["status"], "too_short")

    def test_paywall_marker_is_refused(self):
        page = "<html><body><article><p>" + "Text. " * 80 + "Subscribe to continue reading</p></article></body></html>"
        client, _ = self.make({
            "https://example.org/robots.txt": (200, ROBOTS_ALLOW, "https://example.org/robots.txt"),
            self.URL: (200, page, self.URL),
        })
        self.assertEqual(client.fetch(self.URL)["status"], "paywall_suspected")

    def test_non_https_is_refused(self):
        client, _ = self.make({})
        self.assertEqual(client.fetch("http://example.org/a")["status"], "invalid_url")

    def test_text_is_capped(self):
        client, _ = self.make({
            "https://example.org/robots.txt": (200, ROBOTS_ALLOW, "https://example.org/robots.txt"),
            self.URL: (200, PAGE, self.URL),
        }, max_chars=50)
        self.assertEqual(len(client.fetch(self.URL)["text"]), 50)


class RegistryFieldTests(unittest.TestCase):
    def test_repository_rows_default_to_none(self):
        rows = load_sources()
        self.assertTrue(rows)
        for source in rows:
            self.assertIn(source.full_text_fetch, {"none", "article_page"}, source.source_id)

    def test_invalid_value_is_an_error(self):
        src = Source(source_id="x", name="X", homepage="https://example.org", feed_url="https://example.org/f",
                     access_method="rss", permission_status="review_required", enabled=False,
                     source_type="news_media", provenance_class="secondhand_report",
                     canonical_domain="example.org", terms_url="https://example.org/terms",
                     editorial_lanes="A", intelligence_lines="international_news",
                     full_text_fetch="scrape_everything")
        issues = audit_sources([src], date(2026, 10, 23))
        self.assertIn("invalid_full_text_fetch", {i["code"] for i in issues})

    def test_legacy_csv_without_the_column_defaults_to_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.csv"
            path.write_text("source_id,name,homepage,feed_url,access_method,permission_status,enabled\n"
                            "x,X,https://example.org,https://example.org/f,rss,review_required,false\n",
                            encoding="utf-8")
            self.assertEqual(load_sources(str(path))[0].full_text_fetch, "none")


if __name__ == "__main__":
    unittest.main()


class ApplyTests(unittest.TestCase):
    class Source:
        def __init__(self, mode):
            self.full_text_fetch = mode

    class Fetcher:
        def __init__(self, ok=True):
            self.ok = ok
            self.calls = []

        def fetch(self, url):
            self.calls.append(url)
            if not self.ok:
                return {"ok": False, "status": "blocked"}
            return {"ok": True, "status": "fetched", "text": "BODY " * 100, "chars": 500, "container": "article"}

    def article(self, feed="1", summary="feed teaser"):
        from opportunity_radar.freshrss_client import Article
        return Article("id", "title", "https://example.org/a", summary, "2026-10-20T00:00:00+00:00", "F", feed)

    def test_applies_body_and_keeps_the_feed_summary(self):
        from opportunity_radar.fulltext import apply_article_bodies
        art = self.article()
        fetcher = self.Fetcher()
        count = apply_article_bodies([art], {"1": self.Source("article_page")}, fetcher=fetcher)
        self.assertEqual(count, 1)
        self.assertEqual(art.feed_summary, "feed teaser")
        self.assertTrue(art.summary.startswith("BODY"))
        self.assertEqual(art.content_source, "article_page")

    def test_skips_sources_that_did_not_opt_in(self):
        from opportunity_radar.fulltext import apply_article_bodies
        art = self.article()
        fetcher = self.Fetcher()
        count = apply_article_bodies([art], {"1": self.Source("none")}, fetcher=fetcher)
        self.assertEqual(count, 0)
        self.assertEqual(art.summary, "feed teaser")
        self.assertEqual(fetcher.calls, [])

    def test_failure_keeps_the_feed_text(self):
        from opportunity_radar.fulltext import apply_article_bodies
        art = self.article()
        count = apply_article_bodies([art], {"1": self.Source("article_page")}, fetcher=self.Fetcher(ok=False))
        self.assertEqual(count, 0)
        self.assertEqual(art.summary, "feed teaser")

    def test_cap_bounds_page_requests(self):
        from opportunity_radar.fulltext import apply_article_bodies
        arts = [self.article(str(i)) for i in range(5)]
        sources = {str(i): self.Source("article_page") for i in range(5)}
        fetcher = self.Fetcher()
        count = apply_article_bodies(arts, sources, fetcher=fetcher, cap=2)
        self.assertEqual(count, 2)
        self.assertEqual(len(fetcher.calls), 2)
