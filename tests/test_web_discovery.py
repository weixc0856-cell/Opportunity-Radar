import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opportunity_radar import web_discovery


GOOGLE_XML = """<?xml version="1.0"?><rss><channel>
<item><title>AI data center power demand - Reuters</title>
<link>https://news.google.com/rss/articles/abc</link>
<pubDate>Wed, 12 Nov 2026 10:00:00 GMT</pubDate>
<source url="https://www.reuters.com">Reuters</source></item>
<item><title>Grid constraints slow AI buildout - MIT Technology Review</title>
<link>https://news.google.com/rss/articles/def</link>
<pubDate>Tue, 11 Nov 2026 09:00:00 GMT</pubDate>
<source url="https://www.technologyreview.com">MIT Technology Review</source></item>
<item><title>Old story - Example</title>
<link>https://news.google.com/rss/articles/old</link>
<pubDate>Mon, 01 Jan 2020 09:00:00 GMT</pubDate>
<source url="https://example.com">Example</source></item>
</channel></rss>"""


class FakeHttp:
    def __init__(self, text='', data=None):
        self.text = text
        self.data = data or {}
        self.urls = []

    def get_text(self, url, headers=None, timeout=20):
        self.urls.append(url)
        return self.text

    def get_json(self, url, headers=None, timeout=20):
        self.urls.append(url)
        return self.data


class FakePageFetcher:
    def __init__(self, result):
        self.result = result
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        return self.result


def query(**kw):
    base = {'query_id': 'q1', 'name': 'AI infra', 'provider': 'google_news',
            'query': 'AI data center', 'enabled': True, 'permission_status': 'approved',
            'source_cap': 2, 'max_items': 5, 'fetch_pages': False}
    base.update(kw)
    return base


class GoogleNewsTests(unittest.TestCase):
    def test_parses_headline_publisher_and_date(self):
        rows = web_discovery.fetch_google_news(query(), FakeHttp(GOOGLE_XML))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['publisher'], 'Reuters')
        self.assertEqual(rows[0]['published'], '2026-11-12')
        self.assertEqual(rows[0]['summary'], '')

    def test_collect_filters_old_and_dedupes(self):
        config = {'enabled': True, 'queries': [query()], 'max_items_per_query': 5,
                  'max_age_days': 7, 'page_fetch': False, 'max_summary_chars': 6000,
                  'issues': []}
        articles, stats, issues = web_discovery.collect(config, http=FakeHttp(GOOGLE_XML))
        self.assertEqual(len(articles), 2)
        self.assertEqual(stats['skipped_reason'].get('too_old'), 1)
        self.assertEqual(articles[0].source_id, 'search:q1')
        self.assertEqual(articles[0].source_name, 'Reuters')
        self.assertIn('[公开检索]', articles[0].summary)
        self.assertEqual(articles[0].discovery['provider'], 'google_news')


class NewsApiTests(unittest.TestCase):
    def test_uses_a_snippet_without_page_fetch(self):
        payload = {'status': 'ok', 'articles': [
            {'title': 'AI procurement grows', 'url': 'https://example.com/a',
             'publishedAt': '2026-11-12T08:00:00Z',
             'source': {'name': 'Example News'},
             'description': 'Enterprises are increasing AI procurement budgets, according to a new survey of buyers.'}]}
        with patch.dict('os.environ', {'OR_NEWSAPI_KEY': 'test'}):
            rows = web_discovery.fetch_newsapi(query(provider='newsapi'), FakeHttp(data=payload))
        self.assertEqual(rows[0]['publisher'], 'Example News')
        self.assertIn('procurement budgets', rows[0]['summary'])

    def test_missing_key_is_reported_not_crashed(self):
        with patch.dict('os.environ', {'OR_NEWSAPI_KEY': ''}):
            with self.assertRaises(web_discovery.DiscoveryUnavailable):
                web_discovery.fetch_newsapi(query(provider='newsapi'), FakeHttp())


class GdeltTests(unittest.TestCase):
    def test_parses_articles_and_marks_provider(self):
        payload = {'articles': [
            {'url': 'https://example.com/gdelt', 'title': 'Data center power',
             'seendate': '20261112T090000Z', 'domain': 'example.com',
             'language': 'English', 'sourcecountry': 'United States'}]}
        with patch.object(web_discovery.time, 'sleep'), patch.object(web_discovery, '_last_gdelt', 0):
            rows = web_discovery.fetch_gdelt(query(provider='gdelt'), FakeHttp(data=payload))
        self.assertEqual(rows[0]['publisher'], 'example.com')
        self.assertEqual(rows[0]['published'], '2026-11-12')
        self.assertEqual(rows[0]['country'], 'United States')

    def test_page_fetch_is_used_when_enabled(self):
        payload = {'articles': [
            {'url': 'https://example.com/gdelt', 'title': 'Data center power',
             'seendate': '20261112T090000Z', 'domain': 'example.com'}]}
        page = FakePageFetcher({'ok': True, 'status': 'fetched', 'text': 'Full body about procurement and capacity.',
                                'container': 'article'})
        config = {'enabled': True, 'queries': [query(provider='gdelt', fetch_pages=True)],
                  'max_items_per_query': 5, 'max_age_days': 7, 'page_fetch': True,
                  'max_summary_chars': 6000, 'max_pages_per_run': 3, 'issues': []}
        with patch.object(web_discovery.time, 'sleep'), patch.object(web_discovery, '_last_gdelt', 0):
            articles, stats, issues = web_discovery.collect(
                config, http=FakeHttp(data=payload), page_fetcher=page)
        self.assertEqual(len(articles), 1)
        self.assertIn('Full body about procurement', articles[0].summary)
        self.assertEqual(articles[0].discovery['page_status'], 'fetched')
        self.assertEqual(stats['page_fetched'], 1)


class ConfigTests(unittest.TestCase):
    def test_enabled_query_requires_approval(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'discovery.json'
            path.write_text(json.dumps({'enabled': True, 'queries': [
                {'query_id': 'q', 'provider': 'google_news', 'query': 'x',
                 'enabled': True, 'permission_status': 'review_required'}]}), encoding='utf-8')
            config = web_discovery.load_config(path)
            self.assertTrue(any(i['code'] == 'discovery_not_approved' for i in config['issues']))
            self.assertEqual(web_discovery.enabled_queries(config), [])

    def test_missing_config_means_no_discovery(self):
        config = web_discovery.load_config('reports/does-not-exist-discovery.json')
        self.assertFalse(config['enabled'])
        self.assertEqual(config['queries'], [])
