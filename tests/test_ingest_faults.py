import os
import tempfile
import unittest
from pathlib import Path

from ingest_support import (EIA_SAMPLE, FIXTURES, SEC_SAMPLE, FakeTransport, eia_handler,
                            have, json_response, load_json, raw_response)

from opportunity_radar.ingest import eia, http, sec
from opportunity_radar.ingest.config import IngestSettings
from opportunity_radar.ingest.http import IngestError
from opportunity_radar.ingest.sec_main import run as run_sec
from opportunity_radar.ingest.eia_main import run as run_eia
from opportunity_radar.ingest.store import IngestStore

PROD = Path('data/opportunity_radar.sqlite3')


def settings(**over):
    base = dict(db_path=str(Path(tempfile.mkdtemp(prefix='or-fi-')) / 'ingest.sqlite3'),
                report_dir=str(Path(tempfile.mkdtemp(prefix='or-fi-rep-'))),
                sec_user_agent='OpportunityRadar test contact@example.invalid',
                eia_api_key='test-key-not-real', timeout=5, sec_max_rps=5.0,
                eia_base_url='https://api.eia.gov/v2', sec_base_url='https://data.sec.gov')
    base.update(over)
    return IngestSettings(**base)


def prod_fingerprint():
    if not PROD.exists():
        return None
    st = PROD.stat()
    return (st.st_size, st.st_mtime_ns)


@unittest.skipUnless(have(FIXTURES / 'manifest.json'), 'fixtures missing')
class FailureMatrixTests(unittest.TestCase):
    """Each fixture must land in the error class its manifest declares."""

    def setUp(self):
        self.manifest = {f['fixture_id']: f for f in
                         load_json(FIXTURES / 'manifest.json')['fixtures']}

    def _expect(self, fixture_id):
        return self.manifest[fixture_id]['expected']['error_class']

    def test_eia_transport_and_payload_failures(self):
        # 403 without a key is served by the real capture referenced in the manifest.
        self.assertEqual(self._expect('EIA-01'), 'auth')
        body = (Path('data/eia-sample-2026-11-01/no_key.json')).read_bytes()
        client = eia.EiaClient(settings(), transport=FakeTransport(lambda u: http.Response(403, body)))
        with self.assertRaises(IngestError) as ctx:
            client.fetch_all(eia.Query('monthly', '2024-01', '2024-01'))
        self.assertEqual(ctx.exception.error_class, 'auth')

        for fixture, klass, status in (('eia_rate_limited_429.json', 'rate_limit', 429),
                                       ('eia_server_error_500.html', 'server', 500)):
            body = (FIXTURES / fixture).read_bytes()
            t = FakeTransport(lambda u, b=body, s=status: http.Response(s, b))
            c = eia.EiaClient(settings(), transport=t, sleep=lambda d: None)
            with self.assertRaises(IngestError) as ctx:
                c.fetch_all(eia.Query('monthly', '2024-01', '2024-01'))
            self.assertEqual(ctx.exception.error_class, klass, fixture)
        self.assertEqual(self._expect('EIA-04'), 'rate_limit')
        self.assertEqual(self._expect('EIA-05'), 'server')

    def test_eia_timeout(self):
        def boom(url):
            raise IngestError(http.TIMEOUT, 'socket timeout')
        c = eia.EiaClient(settings(), transport=FakeTransport(boom), sleep=lambda d: None)
        with self.assertRaises(IngestError) as ctx:
            c.fetch_all(eia.Query('monthly', '2024-01', '2024-01'))
        self.assertEqual(ctx.exception.error_class, 'timeout')
        self.assertEqual(self._expect('EIA-06'), 'timeout')

    def test_eia_empty_schema_and_truncation(self):
        empty = FakeTransport(lambda u: json_response(load_json(EIA_SAMPLE / 'invalid_facet.json')))
        with self.assertRaises(IngestError) as ctx:
            eia.EiaClient(settings(), transport=empty).fetch_all(
                eia.Query('monthly', '2024-01', '2024-02'))
        self.assertEqual(ctx.exception.error_class, 'empty_result')

        missing_total = FakeTransport(lambda u: json_response(load_json(FIXTURES / 'eia_missing_total.json')))
        with self.assertRaises(IngestError) as ctx:
            eia.EiaClient(settings(), transport=missing_total).fetch_all(
                eia.Query('monthly', '2024-01', '2024-01'))
        self.assertEqual(ctx.exception.error_class, 'schema')

        short = FakeTransport(lambda u: json_response(load_json(FIXTURES / 'eia_incomplete_pagination.json')))
        with self.assertRaises(IngestError) as ctx:
            eia.EiaClient(settings(), transport=short).fetch_all(
                eia.Query('monthly', '2024-01', '2026-08'))
        self.assertEqual(ctx.exception.error_class, 'truncation')

    def test_sec_transport_failures(self):
        for fixture, klass, status in (
                ('sec_forbidden_403.html', 'auth', 403),
                ('sec_not_found_404.html', 'not_found', 404),
                ('sec_rate_limited_429.html', 'rate_limit', 429),
                ('sec_server_error_500.html', 'server', 500)):
            body = (FIXTURES / fixture).read_bytes()
            t = FakeTransport(lambda u, b=body, s=status: http.Response(s, b))
            c = sec.SecClient(settings(), transport=t, sleep=lambda d: None)
            req = sec.ConceptRequest('0000320193', 'us-gaap', 'Revenues', 'revenue')
            with self.assertRaises(IngestError) as ctx:
                c.companyconcept(req)
            self.assertEqual(ctx.exception.error_class, klass, fixture)


@unittest.skipUnless(have(EIA_SAMPLE / 'paging_offset0.json') and have(SEC_SAMPLE / 'aapl_rev.json'),
                     'local samples missing')
class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.before = prod_fingerprint()
        self.settings = settings()
        self.store = IngestStore(self.settings.db_path)

    def tearDown(self):
        self.assertEqual(prod_fingerprint(), self.before,
                         'the production database must not change')

    def test_eia_entry_point_stores_and_is_idempotent(self):
        pages = {off: load_json(EIA_SAMPLE / f'paging_offset{off}.json') for off in (0, 10, 20, 30)}
        annual = {0: load_json(EIA_SAMPLE / 'annual_sample.json')}

        def handler(url):
            return eia_handler(pages if 'frequency=monthly' in url else annual)(url)

        client = eia.EiaClient(self.settings, transport=FakeTransport(handler))
        first = run_eia(self.settings, self.store, client=client)
        self.assertEqual(first['status'], 'success')
        self.assertEqual(first['errors'], 0)
        self.assertEqual(self.store.counts()['eia_observations'], 34)  # 32 monthly + 2 annual
        self.assertEqual(first['ytd']['months_observed'], 8)
        self.assertTrue(first['ytd']['is_partial_year'])

        client2 = eia.EiaClient(self.settings, transport=FakeTransport(handler))
        second = run_eia(self.settings, self.store, client=client2)
        self.assertEqual(second['status'], 'success')
        self.assertEqual(self.store.counts()['eia_observations'], 34, 're-run must not duplicate')
        self.assertEqual(self.store.counts()['eia_observation_versions'], 34)

    def test_eia_entry_point_isolates_failure_per_frequency(self):
        def handler(url):
            if 'frequency=monthly' in url:
                return http.Response(500, b'boom')
            return json_response(load_json(EIA_SAMPLE / 'annual_sample.json'))

        client = eia.EiaClient(self.settings, transport=FakeTransport(handler),
                               sleep=lambda d: None)
        report = run_eia(self.settings, self.store, client=client)
        self.assertEqual(report['status'], 'partial_failed')
        self.assertEqual(self.store.counts()['eia_observations'], 2)
        classes = {f['error_class'] for f in report['failures']}
        self.assertEqual(classes, {'server'})

    def test_sec_entry_point_records_selection_and_survives_one_bad_company(self):
        payload = load_json(SEC_SAMPLE / 'aapl_rev.json')

        def handler(url):
            if 'companyconcept' in url and 'CIK0000320193' in url:
                return json_response(payload)
            return http.Response(404, b'not found')

        client = sec.SecClient(self.settings, transport=FakeTransport(handler))
        report = run_sec(self.settings, self.store, client=client)
        self.assertEqual(report['status'], 'partial_failed')
        self.assertGreater(report['records'], 0)
        rows = self.store.dump('sec_facts')
        selected = [r for r in rows if r['selection_status'] == 'current_selected']
        self.assertTrue(selected)
        for row in rows:
            self.assertIn(row['selection_status'], {'current_selected', 'superseded'})
        self.assertTrue(any(f['error_class'] == 'not_found' for f in report['failures']))


class IsolationTests(unittest.TestCase):
    def test_ingest_store_refuses_the_production_file(self):
        from opportunity_radar.ingest.config import IngestConfigError
        with self.assertRaises(IngestConfigError):
            IngestStore('data/opportunity_radar.sqlite3')

    def test_entry_modules_are_not_imported_by_the_rss_pipeline(self):
        import opportunity_radar.cli as cli
        source = Path(cli.__file__).read_text(encoding='utf-8')
        self.assertNotIn('ingest', source)
        self.assertNotIn('sec_main', source)
        self.assertNotIn('eia_main', source)


if __name__ == '__main__':
    unittest.main()
