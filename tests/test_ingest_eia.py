import unittest

from ingest_support import EIA_SAMPLE, FIXTURES, FakeTransport, eia_handler, have, json_response, load_json

from opportunity_radar.ingest import eia, http
from opportunity_radar.ingest.config import IngestSettings
from opportunity_radar.ingest.http import IngestError


def settings():
    return IngestSettings.from_env()


class QueryTests(unittest.TestCase):
    def test_verified_facets_are_accepted(self):
        q = eia.Query(frequency='monthly', start='2024-01', end='2026-08')
        self.assertIn("COW", q.series_id)

    def test_unverified_fueltype_is_rejected(self):
        with self.assertRaises(IngestError) as ctx:
            eia.Query(frequency='monthly', start='2024-01', end='2026-08', fueltypeid='ZZZ')
        self.assertEqual(ctx.exception.error_class, http.EMPTY_RESULT)

    def test_out_of_scope_route_values_are_rejected(self):
        for kwargs in ({'location': 'CA'}, {'sectorid': '98'}, {'fueltypeid': 'ALL'}):
            with self.assertRaises(IngestError):
                eia.Query(frequency='monthly', start='2024-01', end='2026-08', **kwargs)

    def test_unsupported_frequency_is_rejected(self):
        with self.assertRaises(IngestError):
            eia.Query(frequency='quarterly', start='2024', end='2025')

    def test_the_api_key_never_appears_in_the_recorded_url(self):
        c = eia.EiaClient(settings())
        q = eia.Query(frequency='monthly', start='2024-01', end='2024-02')
        self.assertNotIn('api_key', c.url_without_secret(q, 0, 10))


@unittest.skipUnless(have(EIA_SAMPLE / 'paging_offset0.json'), 'local EIA sample missing')
class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.pages = {off: load_json(EIA_SAMPLE / f'paging_offset{off}.json') for off in (0, 10, 20, 30)}

    def test_four_pages_assemble_the_full_series(self):
        transport = FakeTransport(eia_handler(self.pages))
        client = eia.EiaClient(settings(), transport=transport)
        rows = client.fetch_all(eia.Query(frequency='monthly', start='2024-01', end='2026-08'))
        self.assertEqual(len(rows), 32)
        self.assertEqual([r['period'] for r in rows][0], '2026-08')
        self.assertEqual([r['period'] for r in rows][-1], '2024-01')
        self.assertEqual(len(transport.calls), 4)

    def test_a_short_read_is_truncation_not_success(self):
        transport = FakeTransport(eia_handler({0: self.pages[0]}))
        client = eia.EiaClient(settings(), transport=transport)
        with self.assertRaises(IngestError) as ctx:
            client.fetch_all(eia.Query(frequency='monthly', start='2024-01', end='2026-08'))
        self.assertEqual(ctx.exception.error_class, http.TRUNCATION)

    def test_an_empty_result_is_not_a_zero(self):
        payload = {'response': {'total': '0', 'data': [], 'frequency': 'monthly'}}
        client = eia.EiaClient(settings(), transport=FakeTransport(lambda u: json_response(payload)))
        with self.assertRaises(IngestError) as ctx:
            client.fetch_all(eia.Query(frequency='monthly', start='2024-01', end='2024-02'))
        self.assertEqual(ctx.exception.error_class, http.EMPTY_RESULT)


@unittest.skipUnless(have(FIXTURES / 'eia_missing_units.json'), 'fixtures missing')
class NormalizeTests(unittest.TestCase):
    def test_valid_rows_normalise_with_the_api_unit(self):
        payload = load_json(EIA_SAMPLE / 'monthly_sample.json')
        q = eia.Query(frequency='monthly', start='2024-01', end='2026-08')
        obs = eia.normalize(q, payload['response']['data'], 'hash', 'now')
        self.assertEqual(len(obs), 32)
        self.assertEqual({o['unit'] for o in obs}, {'thousand megawatthours'})
        self.assertTrue(all(o['value_raw'] == str(o['value_num']) or isinstance(o['value_raw'], str)
                            for o in obs))

    def test_missing_units_rejects_the_whole_batch(self):
        payload = load_json(FIXTURES / 'eia_missing_units.json')
        q = eia.Query(frequency='monthly', start='2024-01', end='2024-02')
        with self.assertRaises(IngestError) as ctx:
            eia.normalize(q, payload['response']['data'], 'hash', 'now')
        self.assertEqual(ctx.exception.error_class, http.SCHEMA)

    def test_unexpected_unit_is_rejected_rather_than_assumed(self):
        rows = [{'period': '2024-01', 'generation': '1.0', 'generation-units': 'megawatthours'}]
        with self.assertRaises(IngestError) as ctx:
            eia.normalize(eia.Query('monthly', '2024-01', '2024-01'), rows, 'h', 'now')
        self.assertEqual(ctx.exception.error_class, http.SCHEMA)

    def test_numeric_generation_is_accepted_but_flagged(self):
        payload = load_json(FIXTURES / 'eia_generation_numeric.json')
        obs = eia.normalize(eia.Query('monthly', '2024-01', '2024-01'),
                            payload['response']['data'], 'h', 'now')
        self.assertEqual(len(obs), 1)
        self.assertIn('schema_drift', obs[0]['quality_flags'])
        self.assertEqual(obs[0]['value_num'], 60234.5)

    def test_missing_value_is_an_error_not_a_zero(self):
        rows = [{'period': '2024-01', 'generation': None, 'generation-units': 'thousand megawatthours'}]
        with self.assertRaises(IngestError):
            eia.normalize(eia.Query('monthly', '2024-01', '2024-01'), rows, 'h', 'now')


class YearToDateTests(unittest.TestCase):
    def test_ytd_is_a_partial_year_sum_not_an_annual_value(self):
        obs = [{'period': f'2026-{m:02d}', 'period_kind': 'monthly', 'value_num': 10.0}
               for m in range(1, 9)]
        ytd = eia.year_to_date(obs, 2026)
        self.assertEqual(ytd['months_observed'], 8)
        self.assertTrue(ytd['is_partial_year'])
        self.assertEqual(ytd['sum_gwh'], 80.0)


if __name__ == '__main__':
    unittest.main()
