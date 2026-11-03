import tempfile
import unittest
from pathlib import Path

from opportunity_radar.ingest.config import IngestConfigError
from opportunity_radar.pilot.store import PilotStore


class PilotStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.production = self.root / 'production.sqlite3'
        self.store = PilotStore(self.root / 'pilot.sqlite3', production=self.production)

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_production_as_pilot_store(self):
        with self.assertRaises(IngestConfigError):
            PilotStore(self.production, production=self.production)

    def test_snapshot_is_content_addressed_and_idempotent(self):
        body = b'{"ok": true}'
        first = self.store.save_snapshot('gdelt', 'https://api.test', 'q|7d', 200, body)
        second = self.store.save_snapshot('gdelt', 'https://api.test', 'q|7d', 200, body)
        self.assertEqual(first[0], second[0])
        self.assertTrue(first[1])
        self.assertFalse(second[1])
        with self.store.connect() as conn:
            count = conn.execute('SELECT COUNT(*) FROM pilot_raw_snapshots').fetchone()[0]
        self.assertEqual(count, 1)
        self.assertTrue((self.store.snapshot_dir / 'gdelt' / f'{first[0]}.json').exists())

    def test_candidate_upsert_and_observation_dedupe(self):
        candidate = {
            'candidate_id': 'c1', 'source_id': 'gdelt',
            'url': 'https://example.com/a', 'canonical_url': 'https://example.com/a',
            'domain': 'example.com', 'title': 'A', 'first_seen_at': '2026-11-02T00:00:00+00:00',
            'last_seen_at': '2026-11-02T00:00:00+00:00', 'matched_article_key': None,
            'matched_event_id': None, 'approved_source_id': None,
            'resolution_status': 'unknown_domain', 'lineage_role': 'aggregator',
            'evidence_role': 'discovery',
        }
        self.assertEqual(self.store.upsert_candidate(candidate), 'inserted')
        self.assertEqual(self.store.upsert_candidate(candidate), 'updated')
        stored = self.store.candidate_by_url('https://example.com/a')
        self.assertEqual(stored['seen_count'], 2)
        self.assertTrue(self.store.add_candidate_observation(
            'c1', 'q1', '20261102T000000Z', 'A', 'English', 'US', 'h1'))
        self.assertFalse(self.store.add_candidate_observation(
            'c1', 'q1', '20261102T000000Z', 'A', 'English', 'US', 'h1'))

    def test_link_candidate_is_idempotent(self):
        self.assertTrue(self.store.record_link_candidate(
            'discovery_candidate', 'c1', 'event', 'e1', 'url_match', 'canonical_url'))
        self.assertFalse(self.store.record_link_candidate(
            'discovery_candidate', 'c1', 'event', 'e1', 'url_match', 'canonical_url'))
        self.assertEqual(self.store.link_count(), 1)

    def test_run_lifecycle(self):
        run_id = self.store.start_run('gdelt', config_hash='c', query_hash='q')
        self.store.finish_run(run_id, 'success', requests=1, records=2, errors=0)
        latest = self.store.latest_run('gdelt')
        self.assertEqual(latest['run_id'], run_id)
        self.assertEqual(latest['status'], 'success')
        self.assertEqual(latest['records'], 2)


if __name__ == '__main__':
    unittest.main()
