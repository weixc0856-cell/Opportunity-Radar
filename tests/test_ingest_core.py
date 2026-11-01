import json
import os
import tempfile
import unittest
from pathlib import Path

from ingest_support import FakeTransport, json_response, raw_response

from opportunity_radar.ingest import http
from opportunity_radar.ingest.config import (IngestConfigError, IngestSettings,
                                             assert_isolated_db, production_db_candidates)
from opportunity_radar.ingest.http import IngestError
from opportunity_radar.ingest.store import IngestStore


def tmp_db(name='ingest.sqlite3'):
    d = tempfile.mkdtemp(prefix='or-ingest-')
    return str(Path(d) / name)


class ConfigIsolationTests(unittest.TestCase):
    def test_refuses_the_production_database_path(self):
        with self.assertRaises(IngestConfigError):
            assert_isolated_db('data/opportunity_radar.sqlite3')

    def test_refuses_a_symlinked_production_path(self):
        target = Path('data/opportunity_radar.sqlite3').resolve()
        with self.assertRaises(IngestConfigError):
            assert_isolated_db(str(target))

    def test_accepts_an_independent_path(self):
        p = assert_isolated_db(tmp_db())
        self.assertTrue(str(p).endswith('ingest.sqlite3'))

    def test_production_candidates_include_the_default(self):
        paths = {str(p) for p in production_db_candidates()}
        self.assertIn(str(Path('data/opportunity_radar.sqlite3').resolve()), paths)

    def test_settings_defaults_point_at_a_separate_file(self):
        s = IngestSettings.from_env()
        self.assertNotEqual(Path(s.db_path).resolve(),
                            Path('data/opportunity_radar.sqlite3').resolve())
        self.assertNotEqual(Path(s.report_dir).resolve(), Path('reports').resolve())


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = IngestStore(tmp_db())

    def test_schema_has_no_production_tables(self):
        from opportunity_radar.ingest.store import SCHEMA
        for forbidden in ('articles', 'analyses', 'analysis_history', 'analysis_sections', 'runs'):
            self.assertNotIn(f'TABLE IF NOT EXISTS {forbidden}(', SCHEMA)

    def test_sec_fact_is_idempotent(self):
        fact = self._fact()
        self.assertEqual(self.store.upsert_sec_fact(fact), 'inserted')
        self.assertEqual(self.store.upsert_sec_fact(dict(fact)), 'updated')
        self.assertEqual(self.store.counts()['sec_facts'], 1)

    def test_eia_observation_keeps_history_on_change(self):
        obs = self._obs('1.0')
        self.assertEqual(self.store.upsert_eia_observation(obs), 'inserted')
        self.assertEqual(self.store.upsert_eia_observation(dict(obs)), 'unchanged')
        changed = dict(obs, value_raw='2.0', value_num=2.0, snapshot_hash='hash-b',
                       last_seen_at='2026-11-02T00:00:00+00:00')
        self.assertEqual(self.store.upsert_eia_observation(changed), 'changed')
        rows = self.store.dump('eia_observations')
        self.assertEqual(len(rows), 1)
        self.assertIn('observed_change', rows[0]['quality_flags'])
        versions = self.store.dump('eia_observation_versions')
        self.assertEqual(len(versions), 2)
        self.assertEqual({v['change_kind'] for v in versions},
                         {'first_observed', 'observed_change'})

    def test_snapshot_is_stored_once_per_hash(self):
        first = self.store.save_snapshot('eia', 'https://example.invalid/x', 'k', 200, b'{"a":1}')
        second = self.store.save_snapshot('eia', 'https://example.invalid/x', 'k', 200, b'{"a":1}')
        self.assertTrue(first[1])
        self.assertFalse(second[1])
        self.assertEqual(self.store.counts()['raw_snapshots'], 1)

    def test_runs_and_failures_are_separate_from_the_rss_runs_table(self):
        rid = self.store.start_run('eia')
        self.store.record_failure(rid, 'eia', 'fetch', http.RATE_LIMIT, 'HTTP 429')
        self.store.finish_run(rid, 'partial_failed', requests=1, records=0, errors=1, exit_code=1)
        latest = self.store.latest_run('eia')
        self.assertEqual(latest['status'], 'partial_failed')
        self.assertEqual(self.store.failures(rid)[0]['error_class'], http.RATE_LIMIT)

    def _fact(self):
        return {'cik': '0000320193', 'entity_name': 'Apple Inc.', 'taxonomy': 'us-gaap',
                'tag': 'Revenues', 'unit': 'USD', 'period_start': '2025-09-28',
                'period_end': '2026-06-27', 'value_num': 1.0, 'value_raw': '1',
                'fy': 2026, 'fp': 'Q3', 'form': '10-Q', 'filed': '2026-07-31',
                'accn': '0000320193-26-000020', 'frame': 'CY2026Q2', 'metric_id': 'revenue',
                'filing_relation': 'original', 'selection_status': 'unresolved',
                'quality_flags': '', 'snapshot_hash': 'h', 'first_seen_at': 'x',
                'last_seen_at': 'x'}

    def _obs(self, value):
        return {'series_id': 'eia:s', 'period': '2026-08', 'value_raw': value,
                'value_num': float(value), 'unit': 'thousand megawatthours',
                'period_kind': 'monthly', 'is_partial_year': 0, 'quality_flags': '',
                'snapshot_hash': 'hash-a', 'first_seen_at': '2026-11-01T00:00:00+00:00',
                'last_seen_at': '2026-11-01T00:00:00+00:00'}


class RateLimiterTests(unittest.TestCase):
    def test_spaces_requests_by_the_configured_interval(self):
        clock = {'t': 0.0}
        slept = []
        limiter = http.RateLimiter(5, clock=lambda: clock['t'],
                                   sleep=lambda d: (slept.append(d), clock.__setitem__('t', clock['t'] + d)))
        limiter.wait()
        limiter.wait()
        self.assertAlmostEqual(slept[0], 0.2, places=6)

    def test_zero_rate_disables_waiting(self):
        limiter = http.RateLimiter(0, clock=lambda: 0.0, sleep=lambda d: self.fail('should not sleep'))
        limiter.wait()
        limiter.wait()


class HttpTests(unittest.TestCase):
    def test_rate_limit_is_retried_then_raised(self):
        t = FakeTransport(lambda url: raw_response('slow down', 429))
        with self.assertRaises(IngestError) as ctx:
            http.get_json(t, 'https://x', attempts=3, sleep=lambda d: None)
        self.assertEqual(ctx.exception.error_class, http.RATE_LIMIT)
        self.assertEqual(len(t.calls), 3)

    def test_auth_is_not_retried(self):
        t = FakeTransport(lambda url: raw_response('nope', 403))
        with self.assertRaises(IngestError) as ctx:
            http.get_json(t, 'https://x', attempts=3, sleep=lambda d: None)
        self.assertEqual(ctx.exception.error_class, http.AUTH)
        self.assertEqual(len(t.calls), 1)

    def test_not_found_is_not_retried(self):
        t = FakeTransport(lambda url: raw_response('gone', 404))
        with self.assertRaises(IngestError) as ctx:
            http.get_json(t, 'https://x', attempts=3, sleep=lambda d: None)
        self.assertEqual(ctx.exception.error_class, http.NOT_FOUND)
        self.assertEqual(len(t.calls), 1)

    def test_server_error_is_retried(self):
        t = FakeTransport(lambda url: raw_response('<html>500</html>', 500))
        with self.assertRaises(IngestError) as ctx:
            http.get_json(t, 'https://x', attempts=2, sleep=lambda d: None)
        self.assertEqual(ctx.exception.error_class, http.SERVER)
        self.assertEqual(len(t.calls), 2)

    def test_non_json_body_on_success_is_a_schema_error(self):
        t = FakeTransport(lambda url: raw_response('<html>ok</html>', 200))
        with self.assertRaises(IngestError) as ctx:
            http.get_json(t, 'https://x', sleep=lambda d: None)
        self.assertEqual(ctx.exception.error_class, http.SCHEMA)

    def test_timeout_is_transport_raised(self):
        def boom(url, headers=None, timeout=30):
            raise IngestError(http.TIMEOUT, 'socket timeout')
        t = FakeTransport(lambda url: (_ for _ in ()).throw(IngestError(http.TIMEOUT, 't')))
        with self.assertRaises(IngestError) as ctx:
            http.get_json(t, 'https://x', attempts=2, sleep=lambda d: None)
        self.assertEqual(ctx.exception.error_class, http.TIMEOUT)


if __name__ == '__main__':
    unittest.main()
