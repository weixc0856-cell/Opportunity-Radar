import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from opportunity_radar.ingest.http import EMPTY_RESULT, RATE_LIMIT, IngestError, Response
from opportunity_radar.pilot.config import GdeltQuery, PilotSettings
from opportunity_radar.pilot.gdelt import (
    DomainRegistry, GdeltClient, GdeltResponse, GdeltWindow, ProductionIndex,
    match_candidate, normalize_article, run_gdelt,
)
from opportunity_radar.pilot.store import PilotStore
from opportunity_radar.store import Store

FIXTURE = Path(__file__).parent / 'fixtures' / 'pilot' / 'gdelt_artlist.json'


class GdeltNormalisationTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_normalises_url_title_and_domain(self):
        candidate = normalize_article(self.payload['articles'][0],
                                       observed_at='2026-11-02T00:00:00+00:00')
        self.assertEqual(candidate['canonical_url'],
                         'https://reuters.com/technology/ai-foo')
        self.assertEqual(candidate['domain'], 'reuters.com')
        self.assertEqual(candidate['title'], 'AI & Data Center Investment')
        self.assertEqual(candidate['lineage_role'], 'aggregator')
        self.assertEqual(candidate['evidence_role'], 'discovery')
        self.assertEqual(candidate['resolution_status'], 'new')
        self.assertEqual(len(candidate['candidate_id']), 64)

    def test_candidate_id_is_stable_for_canonical_url(self):
        first = normalize_article(self.payload['articles'][0])
        second = normalize_article(dict(self.payload['articles'][0],
                                        url='https://reuters.com/technology/ai-foo'))
        self.assertEqual(first['candidate_id'], second['candidate_id'])

    def test_invalid_url_is_rejected(self):
        self.assertIsNone(normalize_article(self.payload['articles'][3]))

    def test_controlled_fetch_stops_after_one_429(self):
        settings = replace(PilotSettings.from_env(), gdelt_min_interval=0.0)
        transport = CountingTransport(429, b'Please limit requests to one every 5 seconds.')
        client = GdeltClient(settings, transport=transport, sleep=lambda _: None)
        with self.assertRaises(IngestError) as caught:
            client.fetch('test', GdeltWindow(timespan='1d'), 10, attempts=1, retry_rate_limit=False)
        self.assertEqual(caught.exception.error_class, RATE_LIMIT)
        self.assertEqual(transport.calls, 1)
        self.assertEqual(client.requests, 1)

    def test_empty_200_payload_is_not_treated_as_no_news(self):
        settings = replace(PilotSettings.from_env(), gdelt_min_interval=0.0)
        client = GdeltClient(settings, transport=FakeEmptyTransport(), sleep=lambda _: None)
        with self.assertRaises(IngestError) as caught:
            client.fetch('test', GdeltWindow(timespan='1d'), 10)
        self.assertEqual(caught.exception.error_class, EMPTY_RESULT)

    def test_build_url_contains_expected_parameters(self):
        settings = replace(PilotSettings.from_env(), gdelt_base_url='https://api.test/doc')
        client = GdeltClient(settings, sleep=lambda _: None)
        url = client.build_url('test query', GdeltWindow(timespan='1d'), 50)
        self.assertIn('query=test+query', url)
        self.assertIn('mode=artlist', url)
        self.assertIn('maxrecords=50', url)


class GdeltMatchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.production = self.root / 'production.sqlite3'
        conn = sqlite3.connect(self.production)
        conn.execute('CREATE TABLE articles(article_key TEXT PRIMARY KEY,url TEXT,title TEXT,'
                     'published TEXT,source_name TEXT)')
        conn.execute('CREATE TABLE event_articles(article_key TEXT,event_id TEXT)')
        raw = 'https://www.bbc.com/news/dup-story?utm_source=1'
        key = Store.key(raw)
        conn.execute('INSERT INTO articles VALUES(?,?,?,?,?)',
                     (key, raw, 'Duplicate story', '2026-11-01', 'BBC'))
        conn.execute('INSERT INTO event_articles VALUES(?,?)', (key, 'evt-1'))
        conn.commit()
        conn.close()
        self.index = ProductionIndex(self.production)

    def tearDown(self):
        self.tmp.cleanup()

    def test_canonical_url_matches_production_article_and_event(self):
        candidate = normalize_article({
            'url': 'https://www.bbc.com/news/dup-story', 'title': 'Duplicate story',
            'seendate': '20261101T130000Z', 'domain': 'www.bbc.com',
        })
        domains = DomainRegistry(approved={'bbc.com': 'bbc'}, registered={'bbc.com': 'bbc'})
        matched = match_candidate(candidate, self.index, domains)
        self.assertEqual(matched['resolution_status'], 'duplicate_article')
        self.assertEqual(matched['matched_event_id'], 'evt-1')

    def test_domain_registry_distinguishes_approved_and_unknown(self):
        domains = DomainRegistry(approved={'reuters.com': 'reuters'},
                                 registered={'reuters.com': 'reuters',
                                             'example.org': 'example'})
        self.assertEqual(domains.classify('reuters.com'), ('reuters', 'approved_source'))
        self.assertEqual(domains.classify('sub.reuters.com'), ('reuters', 'approved_source'))
        self.assertEqual(domains.classify('example.org'), (None, 'unapproved_domain'))
        self.assertEqual(domains.classify('other.net'), (None, 'unknown_domain'))


class FakeEmptyTransport:
    def get(self, url, headers=None, timeout=30):
        return Response(200, b'{}', {})


class CountingTransport:
    def __init__(self, status, body):
        self.status = status
        self.body = body
        self.calls = 0

    def get(self, url, headers=None, timeout=30):
        self.calls += 1
        return Response(self.status, self.body, {})


class FailingClient:
    requests = 1
    last_response = Response(429, b'Please limit requests to one every 5 seconds.',
                             {'Content-Type': 'text/plain'})

    def fetch(self, query, window, max_records, attempts=3, retry_rate_limit=True):
        raise IngestError(RATE_LIMIT, 'HTTP 429', 429)


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def fetch(self, query, window, max_records, attempts=3, retry_rate_limit=True):
        body = json.dumps(self.payload).encode('utf-8')
        return GdeltResponse(200, body, self.payload, 'https://api.test/doc?q=1', {})


class GdeltRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        base = PilotSettings.from_env()
        self.settings = replace(
            base,
            db_path=str(self.root / 'pilot.sqlite3'),
            snapshot_dir=str(self.root / 'snapshots'),
            report_dir=str(self.root / 'reports'),
            production_db=str(self.root / 'production.sqlite3'),
        )
        self.payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
        conn = sqlite3.connect(self.settings.production_db)
        conn.execute('CREATE TABLE articles(article_key TEXT PRIMARY KEY,url TEXT,title TEXT,'
                     'published TEXT,source_name TEXT)')
        conn.execute('CREATE TABLE event_articles(article_key TEXT,event_id TEXT)')
        raw = 'https://www.bbc.com/news/dup-story?utm_source=1'
        key = Store.key(raw)
        conn.execute('INSERT INTO articles VALUES(?,?,?,?,?)',
                     (key, raw, 'Duplicate story', '2026-11-01', 'BBC'))
        conn.execute('INSERT INTO event_articles VALUES(?,?)', (key, 'evt-1'))
        conn.commit()
        conn.close()
        self.production_before = Path(self.settings.production_db).read_bytes()
        self.store = PilotStore(self.settings.db_path,
                                production=self.settings.production_db,
                                snapshot_dir=self.settings.snapshot_dir)
        self.query = GdeltQuery('q1', 'test', '1d', 10, '', '', True, '')

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_writes_candidates_and_links_without_production_writes(self):
        summary = run_gdelt(
            self.settings, self.store, [self.query], client=FakeClient(self.payload),
            config_hash='config', query_hash='query',
        )
        self.assertEqual(summary['status'], 'success')
        self.assertEqual(summary['candidate_observations'], 3)
        self.assertEqual(summary['unique_candidates'], 3)
        self.assertEqual(summary['invalid'], 1)
        self.assertGreaterEqual(summary['duplicates'], 1)
        self.assertEqual(summary['links_created'], 1)
        self.assertEqual(self.store.link_count(), 1)
        self.assertEqual(Path(self.settings.production_db).read_bytes(), self.production_before)

    def test_controlled_429_records_one_request_and_stops(self):
        summary = run_gdelt(
            self.settings, self.store, [self.query], client=FailingClient(),
            config_hash='config', query_hash='query', controlled=True,
        )
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(summary['requests'], 1)
        self.assertEqual(len(summary['requests_log']), 1)
        self.assertEqual(summary['requests_log'][0]['status'], 429)
        self.assertIn('Please limit requests', summary['requests_log'][0]['body_preview'])
        self.assertEqual(self.store.failures()[0]['error_class'], 'rate_limit')

    def test_empty_payload_is_a_visible_failure(self):
        summary = run_gdelt(
            self.settings, self.store, [self.query], client=FakeClient({}),
            config_hash='config', query_hash='query',
        )
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(summary['errors'], 1)
        failures = self.store.failures()
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['error_class'], 'empty_result')


if __name__ == '__main__':
    unittest.main()
