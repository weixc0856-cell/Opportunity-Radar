import tempfile
import unittest
from datetime import date
from pathlib import Path

from opportunity_radar.datasets import (
    Dataset, audit_datasets, jsonstat_latest, load_datasets,
)

TODAY = date(2026, 10, 23)


def dataset(**overrides):
    values = dict(dataset_id='eu-hicp', institution='Eurostat', name='HICP',
                  access_kind='api', endpoint='https://example.org/api/data',
                  homepage='https://example.org/', indicator='HICP annual rate',
                  unit='percent', frequency='monthly', seasonality='nsa',
                  latest_period='2025-12', latest_value='2.0', latest_updated='2026-02-06',
                  last_checked_at='2026-10-23', license_status='confirmed_attribution',
                  terms_url='https://example.org/terms', quota_notes='', status='approved',
                  notes='')
    values.update(overrides)
    return Dataset(**values)


def codes(issues):
    return {i['code'] for i in issues}


class AuditTests(unittest.TestCase):
    def test_approved_dataset_is_clean(self):
        self.assertEqual([i for i in audit_datasets([dataset()], TODAY) if i['severity'] == 'error'], [])

    def test_approved_requires_a_known_license(self):
        self.assertIn('approved_without_license', codes(audit_datasets([dataset(license_status='unknown')], TODAY)))

    def test_approved_requires_terms_url(self):
        self.assertIn('missing_terms_url', codes(audit_datasets([dataset(terms_url='')], TODAY)))

    def test_approved_requires_indicator_and_period(self):
        missing = codes(audit_datasets([dataset(indicator='', latest_period='')], TODAY))
        self.assertIn('missing_indicator', missing)
        self.assertIn('missing_latest_period', missing)

    def test_placeholder_key_cannot_be_approved(self):
        issues = audit_datasets([dataset(endpoint='https://example.org/api?key={API_KEY}')], TODAY)
        self.assertIn('placeholder_api_key_approved', codes(issues))

    def test_invalid_frequency_and_status(self):
        issues = audit_datasets([dataset(frequency='sometimes', status='live')], TODAY)
        self.assertIn('invalid_frequency', codes(issues))
        self.assertIn('invalid_status', codes(issues))

    def test_duplicate_ids_rejected(self):
        issues = audit_datasets([dataset(), dataset()], TODAY)
        self.assertIn('duplicate_or_missing_dataset_id', codes(issues))

    def test_blocked_without_reason_warns(self):
        issues = audit_datasets([dataset(status='blocked', notes='')], TODAY)
        self.assertIn('blocked_without_reason', codes(issues))

    def test_future_check_date_rejected(self):
        issues = audit_datasets([dataset(last_checked_at='2027-01-01')], TODAY)
        self.assertIn('future_last_checked_at', codes(issues))


class JsonStatTests(unittest.TestCase):
    def payload(self, index, value):
        return {'label': 'L', 'updated': '2026-02-06', 'value': value,
                'dimension': {'time': {'category': {'index': index}}}}

    def test_latest_period_is_the_highest_index(self):
        observed = jsonstat_latest(self.payload({'2025-10': 0, '2025-11': 1, '2025-12': 2},
                                                {'0': 2.1, '1': 2.1, '2': 2.0}))
        self.assertEqual(observed['latest_period'], '2025-12')
        self.assertEqual(observed['latest_value'], 2.0)

    def test_accepts_list_index_and_list_values(self):
        observed = jsonstat_latest(self.payload(['2025-10', '2025-11'], [1.5, 1.7]))
        self.assertEqual(observed['latest_period'], '2025-11')
        self.assertEqual(observed['latest_value'], 1.7)

    def test_missing_time_dimension_raises(self):
        with self.assertRaises(ValueError):
            jsonstat_latest({'value': {}})


class RegistryFileTests(unittest.TestCase):
    def test_repository_registry_loads_and_validates(self):
        rows = load_datasets()
        self.assertTrue(rows)
        self.assertFalse([i for i in audit_datasets(rows) if i['severity'] == 'error'])

    def test_missing_file_is_empty(self):
        self.assertEqual(load_datasets('does/not/exist.csv'), [])

    def test_loader_reads_quoted_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'datasets.csv'
            path.write_text(
                'dataset_id,institution,name,access_kind,endpoint,homepage,indicator,unit,'
                'frequency,seasonality,latest_period,latest_value,latest_updated,last_checked_at,'
                'license_status,terms_url,quota_notes,status,notes\n'
                'x,Org,Name,api,https://example.org/a,https://example.org/,CPI,percent,monthly,nsa,'
                '2025-12,1.0,2026-01-01,2026-10-23,confirmed_attribution,https://example.org/t,'
                '"quota, with comma",approved,"note, with comma"\n', encoding='utf-8')
            rows = load_datasets(path)
            self.assertEqual(rows[0].quota_notes, 'quota, with comma')
            self.assertEqual(rows[0].notes, 'note, with comma')


if __name__ == '__main__':
    unittest.main()
