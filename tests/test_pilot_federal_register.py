import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from opportunity_radar.ingest.http import Response
from opportunity_radar.pilot.config import (
    FederalRegisterWatch, PilotSettings, load_federal_register_watchlist,
)
from opportunity_radar.pilot.federal_register import (
    FederalRegisterClient, FederalRegisterResponse, normalize_document,
    run_federal_register,
)
from opportunity_radar.pilot.store import PilotStore

FIXTURE = Path(__file__).parent / 'fixtures' / 'pilot' / 'fr_documents.json'


class FederalRegisterWatchlistTests(unittest.TestCase):
    def test_watchlist_covers_all_approved_agencies_including_fda(self):
        watches = load_federal_register_watchlist()
        agencies = {watch.agency_slug for watch in watches}
        self.assertEqual(len(watches), 9)
        self.assertEqual(len(agencies), 8)
        self.assertIn('food-and-drug-administration', agencies)
        fda = [watch for watch in watches if watch.watch_id == 'fda-medical-device']
        self.assertEqual(len(fda), 1)
        self.assertEqual(fda[0].term, 'medical device')
        self.assertEqual(fda[0].types, ['RULE', 'PRORULE', 'NOTICE'])


class FederalRegisterNormalisationTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def test_maps_types_and_keeps_metadata(self):
        rule = normalize_document(self.payload['results'][0],
                                  observed_at='2026-11-02T00:00:00+00:00')
        proposed = normalize_document(self.payload['results'][1])
        notice = normalize_document(self.payload['results'][2])
        self.assertEqual(rule['document_type'], 'RULE')
        self.assertEqual(proposed['document_type'], 'PRORULE')
        self.assertEqual(notice['document_type'], 'NOTICE')
        self.assertEqual(rule['document_id'], 'fr:2026-10001')
        self.assertEqual(rule['agency_slugs'], 'commerce-department')
        self.assertEqual(proposed['comments_close_on'], '2026-12-15')
        self.assertEqual(notice['citation'], None)
        self.assertEqual(len(rule['content_hash']), 64)

    def test_unknown_type_is_rejected(self):
        document = dict(self.payload['results'][0], type='Other')
        with self.assertRaises(ValueError):
            normalize_document(document)

    def test_content_hash_is_stable_for_same_selected_fields(self):
        first = normalize_document(self.payload['results'][0])
        second = normalize_document(dict(self.payload['results'][0]))
        self.assertEqual(first['content_hash'], second['content_hash'])

    def test_zero_result_payload_is_valid_empty(self):
        class ZeroTransport:
            def get(self, url, headers=None, timeout=30):
                body = json.dumps({'description': 'no matches', 'count': 0}).encode('utf-8')
                return Response(200, body, {'Content-Type': 'application/json'})

        settings = replace(PilotSettings.from_env(), fr_min_interval=0.0)
        client = FederalRegisterClient(settings, transport=ZeroTransport(), sleep=lambda _: None)
        watch = FederalRegisterWatch('commerce-ai', 'commerce-department',
                                     'artificial intelligence', 'RULE,PRORULE',
                                     True, 50, '')
        response = client.fetch(watch, '2026-11-01')
        self.assertEqual(response.payload['results'], [])
        self.assertEqual(response.payload['total_pages'], 0)

    def test_build_url_contains_filters_and_fields(self):
        settings = replace(PilotSettings.from_env(), fr_min_interval=0.0)
        client = FederalRegisterClient(settings, sleep=lambda _: None)
        watch = FederalRegisterWatch('commerce-ai', 'commerce-department',
                                     'artificial intelligence', 'RULE,PRORULE',
                                     True, 50, '')
        url = client.build_url(watch, '2026-11-01', None, 2, 100)
        self.assertIn('conditions%5Bagencies%5D%5B%5D=commerce-department', url)
        self.assertIn('conditions%5Btype%5D%5B%5D=RULE', url)
        self.assertIn('conditions%5Btype%5D%5B%5D=PRORULE', url)
        self.assertIn('conditions%5Bterm%5D=artificial+intelligence', url)
        self.assertIn('fields%5B%5D=document_number', url)
        self.assertIn('page=2', url)


class FederalRegisterRunTests(unittest.TestCase):
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
            fr_min_interval=0.0,
        )
        self.store = PilotStore(self.settings.db_path,
                                production=self.settings.production_db,
                                snapshot_dir=self.settings.snapshot_dir)
        self.payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.watch = FederalRegisterWatch('commerce-ai', 'commerce-department',
                                          'artificial intelligence', 'RULE,PRORULE',
                                          True, 50, '')

    def tearDown(self):
        self.tmp.cleanup()

    def test_policy_upsert_versions_and_unchanged(self):
        doc = normalize_document(self.payload['results'][0])
        doc['latest_snapshot_hash'] = 'h1'
        self.assertEqual(self.store.upsert_policy_document(doc), 'inserted')
        changed = dict(doc, latest_snapshot_hash='h2')
        self.assertEqual(self.store.upsert_policy_document(changed), 'unchanged')
        updated = dict(doc, title='Changed title',
                       content_hash='b' * 64, latest_snapshot_hash='h3')
        self.assertEqual(self.store.upsert_policy_document(updated), 'updated')
        stored = self.store.policy_document_by_number('2026-10001')
        self.assertEqual(stored['title'], 'Changed title')
        self.assertEqual(self.store.policy_version_count(), 2)

    def test_run_paginates_and_deduplicates_across_watches(self):
        class FakeClient:
            requests = 0
            last_response = None

            def __init__(self, payload):
                self.payload = payload

            def fetch(self, watch, since, until=None, page=1, per_page=100):
                self.requests += 1
                return FederalRegisterResponse(
                    200, json.dumps(self.payload).encode('utf-8'), self.payload,
                    f'https://api.test/documents.json?page={page}', {},
                )

        second_watch = FederalRegisterWatch('commerce-chip', 'commerce-department',
                                            'semiconductor', 'RULE,PRORULE,NOTICE',
                                            True, 50, '')
        summary = run_federal_register(
            self.settings, self.store, [self.watch, second_watch],
            since='2026-11-01', client=FakeClient(self.payload),
            config_hash='c', query_hash='q',
        )
        self.assertEqual(summary['status'], 'success')
        self.assertEqual(summary['documents'], 3)
        self.assertEqual(summary['inserted'], 3)
        self.assertEqual(summary['duplicates'], 3)
        self.assertEqual(summary['requests'], 2)
        self.assertEqual(summary['by_type'], {'NOTICE': 1, 'PRORULE': 1, 'RULE': 1})
        self.assertEqual(self.store.policy_version_count(), 3)

    def test_run_follows_pagination_until_total_pages(self):
        first = dict(self.payload['results'][0])
        second = dict(self.payload['results'][1])

        class PagedClient:
            requests = 0
            last_response = None

            def fetch(self, watch, since, until=None, page=1, per_page=100):
                self.requests += 1
                docs = [first] if page == 1 else [second]
                payload = {'count': 2, 'total_pages': 2, 'results': docs}
                return FederalRegisterResponse(
                    200, json.dumps(payload).encode('utf-8'), payload,
                    f'https://api.test/documents.json?page={page}', {},
                )

        summary = run_federal_register(
            self.settings, self.store, [self.watch], since='2026-11-01',
            client=PagedClient(), config_hash='c', query_hash='q',
        )
        self.assertEqual(summary['status'], 'success')
        self.assertEqual(summary['requests'], 2)
        self.assertEqual(summary['pages'], 2)
        self.assertEqual(summary['documents'], 2)

    def test_empty_results_are_not_an_api_failure(self):
        class EmptyClient:
            requests = 1
            last_response = None

            def fetch(self, watch, since, until=None, page=1, per_page=100):
                payload = {'count': 0, 'total_pages': 0, 'results': []}
                return FederalRegisterResponse(200, b'{}', payload,
                                               'https://api.test/empty', {})

        summary = run_federal_register(
            self.settings, self.store, [self.watch], since='2026-11-01',
            client=EmptyClient(), config_hash='c', query_hash='q',
        )
        self.assertEqual(summary['status'], 'success')
        self.assertEqual(summary['documents'], 0)
        self.assertEqual(summary['errors'], 0)


if __name__ == '__main__':
    unittest.main()
