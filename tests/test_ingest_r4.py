import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ingest_support import EIA_SAMPLE, FakeTransport, have, json_response, load_json, raw_response

from opportunity_radar.ingest import eia, http, rights, sec
from opportunity_radar.ingest.config import IngestSettings
from opportunity_radar.ingest.http import IngestError
from opportunity_radar.ingest.store import IngestStore

PROD = Path('data/opportunity_radar.sqlite3')


def make_settings(**over):
    base = dict(db_path=str(Path(tempfile.mkdtemp(prefix='or-r4-')) / 'ingest.sqlite3'),
                report_dir=str(Path(tempfile.mkdtemp(prefix='or-r4-rep-'))),
                sec_user_agent='contact@example.invalid', eia_api_key='secret-test-key-value',
                timeout=5, sec_max_rps=5.0,
                eia_base_url='https://api.eia.gov/v2', sec_base_url='https://data.sec.gov')
    base.update(over)
    return IngestSettings(**base)


def fact(accn, filed, form='10-K', start='2024-09-29', end='2025-09-27'):
    return {'cik': '0000320193', 'taxonomy': 'us-gaap', 'tag': 'Revenues', 'unit': 'USD',
            'period_start': start, 'period_end': end, 'accn': accn, 'filed': filed,
            'form': form, 'value_num': 1.0, 'value_raw': '1', 'fy': 2025, 'fp': 'FY',
            'entity_name': 'Apple Inc.', 'frame': None, 'metric_id': 'revenue',
            'filing_relation': sec.UNKNOWN, 'selection_status': sec.UNRESOLVED,
            'quality_flags': '', 'snapshot_hash': 'h', 'first_seen_at': 'x', 'last_seen_at': 'x'}


class FilingRelationTests(unittest.TestCase):
    def test_the_earliest_filing_is_original(self):
        facts = [fact('a1', '2025-11-01'), fact('a2', '2026-02-10')]
        sec.assign_filing_relations(facts)
        self.assertEqual(facts[0]['filing_relation'], sec.ORIGINAL)

    def test_a_later_non_amendment_accession_is_subsequent_comparative(self):
        facts = [fact('a1', '2025-11-01'), fact('a2', '2026-02-10')]
        sec.assign_filing_relations(facts)
        self.assertEqual(facts[1]['filing_relation'], sec.SUBSEQUENT_COMPARATIVE)

    def test_a_slash_a_form_is_an_amendment_even_when_it_is_first(self):
        facts = [fact('a1', '2025-11-01', '10-K/A'), fact('a2', '2026-02-10')]
        sec.assign_filing_relations(facts)
        self.assertEqual(facts[0]['filing_relation'], sec.AMENDMENT)

    def test_a_missing_filed_date_is_unknown_not_original(self):
        facts = [fact('a1', None)]
        sec.assign_filing_relations(facts)
        self.assertEqual(facts[0]['filing_relation'], sec.UNKNOWN)

    def test_no_row_is_ever_assumed_original_without_evidence(self):
        facts = [fact('a1', None), fact('a2', None)]
        sec.assign_filing_relations(facts)
        self.assertEqual({f['filing_relation'] for f in facts}, {sec.UNKNOWN})

    def test_all_four_classes_are_reachable(self):
        facts = [fact('a1', '2025-11-01'), fact('a2', '2026-02-10'),
                 fact('a3', '2026-03-01', '10-Q/A')]
        facts.append(fact('a4', None, '10-K', start='2020-01-01', end='2020-12-31'))
        counts = sec.assign_filing_relations(facts)
        self.assertEqual(counts[sec.ORIGINAL], 1)
        self.assertEqual(counts[sec.SUBSEQUENT_COMPARATIVE], 1)
        self.assertEqual(counts[sec.AMENDMENT], 1)
        self.assertEqual(counts[sec.UNKNOWN], 1)


class SelectionRuleTests(unittest.TestCase):
    def test_the_latest_filed_valid_accession_is_selected(self):
        facts = [fact('a1', '2025-11-01'), fact('a2', '2026-02-10', '10-K/A')]
        plan = sec.plan_selection(facts)
        self.assertEqual(plan[0][1], 'a2')

    def test_a_group_with_an_undated_member_is_left_unresolved(self):
        facts = [fact('a1', '2025-11-01'), fact('a2', None)]
        self.assertEqual(sec.plan_selection(facts), [])

    def test_the_same_rule_holds_for_a_large_real_batch(self):
        payload = load_json('data/sec-sample-2026-11-01/aapl_rev.json') if have(
            'data/sec-sample-2026-11-01/aapl_rev.json') else None
        if payload is None:
            self.skipTest('local SEC sample missing')
        req = sec.ConceptRequest('0000320193', 'us-gaap',
                                 'RevenueFromContractWithCustomerExcludingAssessedTax', 'revenue')
        facts, _ = sec.normalize_concept(payload, req, 'h', 'x')
        sec.assign_filing_relations(facts)
        plan = sec.plan_selection(facts)
        self.assertEqual(len(plan), len({(f['period_start'], f['period_end']) for f in facts}))
        for key, accn in plan:
            self.assertTrue(accn)


class RightsPolicyTests(unittest.TestCase):
    def test_both_sources_are_approved(self):
        for source in ('sec-edgar', 'eia'):
            self.assertEqual(rights.assert_source_allowed(source)['status'], rights.APPROVED)

    def test_an_unassessed_source_is_refused(self):
        with self.assertRaises(IngestError) as ctx:
            rights.assert_source_allowed('ember')
        self.assertEqual(ctx.exception.error_class, http.RIGHTS)

    def test_third_party_content_without_clearance_is_refused(self):
        with self.assertRaises(IngestError) as ctx:
            rights.assert_content_usable('sec-edgar', third_party=True)
        self.assertEqual(ctx.exception.error_class, http.RIGHTS)

    def test_a_rights_refusal_is_not_an_http_error(self):
        with self.assertRaises(IngestError) as ctx:
            rights.assert_source_allowed('unknown-source')
        self.assertIsNone(ctx.exception.status)

    def test_the_entry_points_enforce_the_policy(self):
        import opportunity_radar.ingest.sec_main as sec_main
        import opportunity_radar.ingest.eia_main as eia_main
        for module, source in ((sec_main, 'sec-edgar'), (eia_main, 'eia')):
            src = Path(module.__file__).read_text(encoding='utf-8')
            self.assertIn(f"assert_source_allowed('{source}')", src)


class RetryAndPartialFailureTests(unittest.TestCase):
    def test_a_rate_limit_then_success_recovers_without_losing_data(self):
        calls = {'n': 0}
        payload = load_json(EIA_SAMPLE / 'annual_sample.json') if have(
            EIA_SAMPLE / 'annual_sample.json') else {'response': {'total': '1', 'data': []}}

        def handler(url):
            calls['n'] += 1
            if calls['n'] == 1:
                return raw_response('slow down', 429)
            return json_response(payload)

        client = eia.EiaClient(make_settings(), transport=FakeTransport(handler), sleep=lambda d: None)
        rows = client.fetch_all(eia.Query('annual', '2024', '2025'))
        self.assertEqual(calls['n'], 2)
        self.assertTrue(rows)

    def test_a_mid_pagination_failure_stores_nothing(self):
        pages = {0: load_json(EIA_SAMPLE / 'paging_offset0.json')} if have(
            EIA_SAMPLE / 'paging_offset0.json') else {}

        def handler(url):
            if 'offset=0' in url:
                return json_response(pages[0])
            return raw_response('boom', 500)

        store = IngestStore(make_settings().db_path)
        client = eia.EiaClient(make_settings(), transport=FakeTransport(handler), sleep=lambda d: None)
        with self.assertRaises(IngestError) as ctx:
            client.fetch_all(eia.Query('monthly', '2024-01', '2026-08'), store=store)
        self.assertEqual(ctx.exception.error_class, 'server')
        self.assertEqual(store.counts()['eia_observations'], 0)

    def test_truncated_json_is_a_schema_error(self):
        t = FakeTransport(lambda u: raw_response('{"response": {"total": "1"', 200))
        with self.assertRaises(IngestError) as ctx:
            http.get_json(t, 'https://x', sleep=lambda d: None)
        self.assertEqual(ctx.exception.error_class, http.SCHEMA)


class TransactionAndCrashTests(unittest.TestCase):
    def setUp(self):
        self.store = IngestStore(make_settings().db_path)

    def test_an_exception_before_commit_rolls_the_whole_transaction_back(self):
        with self.assertRaises(RuntimeError):
            with self.store.connect() as c:
                c.execute("INSERT INTO ingest_runs(source_id,started_at,status) VALUES('x','t','running')")
                raise RuntimeError('crash before commit')
        self.assertEqual(self.store.counts()['ingest_runs'], 0)

    def test_data_written_after_commit_survives_a_restart(self):
        rid = self.store.start_run('eia')
        self.store.finish_run(rid, 'success', 1, 1, 0)
        reopened = IngestStore(self.store.path)
        self.assertEqual(reopened.counts()['ingest_runs'], 1)
        self.assertEqual(reopened.latest_run('eia')['status'], 'success')

    def test_a_reopened_store_still_keeps_writes_idempotent(self):
        obs = {'series_id': 's', 'period': '2026-08', 'value_raw': '1', 'value_num': 1.0,
               'unit': 'thousand megawatthours', 'period_kind': 'monthly', 'is_partial_year': 0,
               'quality_flags': '', 'snapshot_hash': 'h', 'first_seen_at': 't', 'last_seen_at': 't'}
        self.store.upsert_eia_observation(obs)
        IngestStore(self.store.path).upsert_eia_observation(dict(obs))
        self.assertEqual(self.store.counts()['eia_observations'], 1)

    def test_the_database_stays_integrity_clean(self):
        self.store.start_run('sec-edgar')
        with sqlite3.connect(self.store.path) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')


class SecretHygieneTests(unittest.TestCase):
    def test_no_snapshot_or_report_contains_the_api_key(self):
        settings = make_settings()
        store = IngestStore(settings.db_path)
        payload = load_json(EIA_SAMPLE / 'annual_sample.json') if have(
            EIA_SAMPLE / 'annual_sample.json') else {'response': {'total': '1', 'data': []}}
        client = eia.EiaClient(settings, transport=FakeTransport(lambda u: json_response(payload)))
        client.fetch_all(eia.Query('annual', '2024', '2025'), store=store)
        for root, _dirs, files in os.walk(Path(settings.db_path).parent):
            for name in files:
                text = (Path(root) / name).read_bytes().decode('utf-8', 'replace')
                self.assertNotIn(settings.eia_api_key, text, f'{name} leaked the api key')

    def test_the_recorded_url_carries_no_key(self):
        settings = make_settings()
        client = eia.EiaClient(settings)
        url = client.url_without_secret(eia.Query('annual', '2024', '2025'), 0, 10)
        self.assertNotIn('api_key', url)
        self.assertNotIn(settings.eia_api_key, url)


if __name__ == '__main__':
    unittest.main()
