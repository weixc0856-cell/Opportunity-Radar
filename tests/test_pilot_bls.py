import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from opportunity_radar.ingest.http import EMPTY_RESULT, IngestError, Response
from opportunity_radar.pilot.bls import (
    BlsClient, BlsResponse, normalize_observation, run_bls,
)
from opportunity_radar.pilot.config import PilotSettings, load_bls_series
from opportunity_radar.pilot.store import PilotStore

FIXTURE = Path(__file__).parent / 'fixtures' / 'pilot' / 'bls_timeseries.json'
EXPECTED = {
    'CES0000000001', 'LNS14000000', 'CES0500000003', 'CUSR0000SA0',
    'CUUR0000SA0', 'JTS000000000000000JOL', 'JTS000000000000000HIL',
    'JTS000000000000000QUL', 'PRS85006092',
}


class BlsConfigTests(unittest.TestCase):
    def test_nine_official_series_are_configured(self):
        series = load_bls_series()
        self.assertEqual(len(series), 9)
        self.assertEqual({item.series_id for item in series}, EXPECTED)
        by_id = {item.series_id: item for item in series}
        self.assertEqual(by_id['CUSR0000SA0'].seasonal_adjustment, 'seasonally adjusted')
        self.assertEqual(by_id['CUUR0000SA0'].seasonal_adjustment, 'not seasonally adjusted')
        self.assertEqual(by_id['PRS85006092'].frequency, 'quarterly')
        self.assertEqual(by_id['CES0000000001'].frequency, 'monthly')


class BlsNormalisationTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.series = {item.series_id: item for item in load_bls_series()}

    def test_monthly_values_and_preliminary_flag(self):
        data = self.payload['Results']['series'][0]['data'][0]
        observation = normalize_observation(
            data, self.series['CES0000000001'], 'snap', '2026-11-02T00:00:00+00:00'
        )
        self.assertEqual(observation['period_raw'], 'M09')
        self.assertEqual(observation['period'], '2026-09')
        self.assertEqual(observation['period_name'], 'September')
        self.assertEqual(observation['value_num'], 159044.0)
        self.assertEqual(observation['preliminary'], 1)
        self.assertEqual(observation['latest'], 1)
        self.assertEqual(observation['unit'], 'thousands of employees')

    def test_missing_value_is_preserved_not_invented(self):
        data = self.payload['Results']['series'][4]['data'][1]
        observation = normalize_observation(
            data, self.series['CUUR0000SA0'], 'snap'
        )
        self.assertEqual(observation['value_raw'], '-')
        self.assertIsNone(observation['value_num'])
        self.assertIn('missing_value', observation['quality_flags'])

    def test_quarterly_period_is_not_monthly(self):
        data = self.payload['Results']['series'][8]['data'][0]
        observation = normalize_observation(
            data, self.series['PRS85006092'], 'snap'
        )
        self.assertEqual(observation['period_raw'], 'Q02')
        self.assertEqual(observation['period'], '2026-Q2')
        self.assertEqual(observation['unit'], 'percent')
        self.assertEqual(self.series['PRS85006092'].frequency, 'quarterly')

    def test_unknown_period_is_not_guessed(self):
        data = {'year': '2026', 'period': 'M14', 'periodName': 'Bad', 'value': '1'}
        observation = normalize_observation(
            data, self.series['CES0000000001'], 'snap'
        )
        self.assertIsNone(observation['period'])
        self.assertIn('unknown_period', observation['quality_flags'])


class BlsClientErrorTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(PilotSettings.from_env(), bls_min_interval=0.0)

    def test_empty_results_is_an_error_not_empty_success(self):
        class EmptyTransport:
            def post(self, url, body, headers=None, timeout=30):
                payload = {'status': 'REQUEST_SUCCEEDED', 'Results': {'series': []}}
                return Response(200, json.dumps(payload).encode('utf-8'), {})

        client = BlsClient(self.settings, transport=EmptyTransport(), sleep=lambda _: None)
        with self.assertRaises(IngestError) as caught:
            client.fetch(['CES0000000001'], 2017, 2026)
        self.assertEqual(caught.exception.error_class, EMPTY_RESULT)

    def test_request_failed_is_not_success(self):
        class FailedTransport:
            def post(self, url, body, headers=None, timeout=30):
                payload = {'status': 'REQUEST_FAILED', 'message': ['invalid series']}
                return Response(200, json.dumps(payload).encode('utf-8'), {})

        client = BlsClient(self.settings, transport=FailedTransport(), sleep=lambda _: None)
        with self.assertRaises(IngestError):
            client.fetch(['CES0000000001'], 2017, 2026)


class BlsRunTests(unittest.TestCase):
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
            bls_min_interval=0.0,
        )
        self.store = PilotStore(self.settings.db_path,
                                production=self.settings.production_db,
                                snapshot_dir=self.settings.snapshot_dir)
        self.payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.series = load_bls_series()

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_revision_keeps_old_version(self):
        from opportunity_radar.pilot.bls import series_record
        series = self.series[0]
        record = series_record(series, '2026-11-02T00:00:00+00:00')
        self.store.upsert_macro_series(record)
        data = self.payload['Results']['series'][0]['data'][0]
        observation = normalize_observation(data, series, 'snap1')
        self.assertEqual(self.store.upsert_macro_observation(observation), 'inserted')
        self.assertEqual(self.store.upsert_macro_observation(
            dict(observation, last_seen_at='2026-11-03T00:00:00+00:00', snapshot_hash='snap1')
        ), 'unchanged')
        revised = dict(observation, value_raw='159100', value_num=159100.0,
                       snapshot_hash='snap2', last_seen_at='2026-11-04T00:00:00+00:00')
        self.assertEqual(self.store.upsert_macro_observation(revised), 'updated')
        self.assertEqual(self.store.macro_version_count(), 2)

    def test_run_inserts_then_reports_unchanged(self):
        class FakeClient:
            requests = 1
            last_response = None

            def __init__(self, payload):
                self.payload = payload

            def fetch(self, series_ids, start_year, end_year):
                body = json.dumps(self.payload).encode('utf-8')
                return BlsResponse(200, body, self.payload,
                                   'https://api.bls.gov/publicAPI/v1/timeseries/data/', {})

        first = run_bls(
            self.settings, self.store, self.series, 2017, 2026,
            client=FakeClient(self.payload), config_hash='c', query_hash='q',
        )
        self.assertEqual(first['status'], 'success')
        self.assertEqual(first['series_count'], 9)
        self.assertEqual(first['observations'], 11)
        self.assertEqual(first['inserted'], 11)
        self.assertEqual(first['version_count'], 11)
        second = run_bls(
            self.settings, self.store, self.series, 2017, 2026,
            client=FakeClient(self.payload), config_hash='c', query_hash='q',
        )
        self.assertEqual(second['status'], 'success')
        self.assertEqual(second['unchanged'], 11)
        self.assertEqual(second['version_count'], 11)

    def test_v1_limits_are_enforced(self):
        settings = replace(PilotSettings.from_env(), bls_min_interval=0.0)
        client = BlsClient(settings, sleep=lambda _: None)
        with self.assertRaises(ValueError):
            client.fetch([f'S{i}' for i in range(26)], 2017, 2026)
        with self.assertRaises(ValueError):
            client.fetch(['CES0000000001'], 2010, 2026)


if __name__ == '__main__':
    unittest.main()
