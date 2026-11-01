import unittest

from ingest_support import FIXTURES, SEC_SAMPLE, have, load_json

from opportunity_radar.ingest import http, labels, sec
from opportunity_radar.ingest.http import IngestError
from opportunity_radar.ingest.sec import ConceptRequest, can_derive_quarter, derive_quarter, filing_relation


class LabelMapTests(unittest.TestCase):
    def test_ten_companies_are_registered(self):
        self.assertEqual(len(labels.companies()), 10)
        self.assertIn('0000320193', labels.COMPANIES)
        self.assertIn('0001046179', labels.COMPANIES)

    def test_jpmorgan_capex_is_unsupported_not_guessed(self):
        self.assertIn(('0000019617', labels.CAPEX), labels.unsupported())
        tags = {(c, m) for c, m, _t, _g, _s in labels.requested_tags()}
        self.assertNotIn(('0000019617', labels.CAPEX), tags)

    def test_tsmc_uses_ifrs(self):
        taxonomies = {t for c, m, t, _g, _s in labels.requested_tags() if c == '0001046179'}
        self.assertEqual(taxonomies, {'ifrs-full'})


@unittest.skipUnless(have(SEC_SAMPLE / 'aapl_rev.json'), 'local SEC sample missing')
class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.payload = load_json(SEC_SAMPLE / 'aapl_rev.json')
        self.req = ConceptRequest(cik='0000320193', taxonomy='us-gaap',
                                  tag='RevenueFromContractWithCustomerExcludingAssessedTax',
                                  metric_id='revenue')

    def test_every_row_becomes_a_fact_with_source_identifiers(self):
        facts, flag = sec.normalize_concept(self.payload, self.req, 'hash', 'now')
        self.assertIsNone(flag)
        self.assertEqual(len(facts), 117)
        first = facts[0]
        for key in ('cik', 'taxonomy', 'tag', 'unit', 'accn', 'form', 'filed', 'period_end'):
            self.assertTrue(first[key], key)
        self.assertEqual(first['cik'], '0000320193')
        self.assertEqual(first['unit'], 'USD')

    def test_values_keep_full_precision(self):
        facts, _ = sec.normalize_concept(self.payload, self.req, 'hash', 'now')
        self.assertEqual(facts[0]['value_num'], 229234000000.0)
        self.assertEqual(facts[0]['value_raw'], '229234000000')

    def test_cik_mismatch_is_rejected(self):
        other = ConceptRequest(cik='0000789019', taxonomy='us-gaap', tag='Revenues',
                               metric_id='revenue')
        with self.assertRaises(IngestError) as ctx:
            sec.normalize_concept(self.payload, other, 'h', 'now')
        self.assertEqual(ctx.exception.error_class, http.SCHEMA)


@unittest.skipUnless(have(FIXTURES / 'sec_empty_units.json'), 'fixtures missing')
class EmptyAndBrokenPayloadTests(unittest.TestCase):
    def test_no_facts_is_flagged_not_zero_valued(self):
        payload = load_json(FIXTURES / 'sec_empty_units.json')
        req = ConceptRequest('0000009999', 'us-gaap', 'Revenues', 'capex')
        facts, flag = sec.normalize_concept(payload, req, 'h', 'now')
        self.assertEqual(facts, [])
        self.assertEqual(flag, 'no_facts')

    def test_units_that_are_not_an_object_are_a_schema_error(self):
        payload = load_json(FIXTURES / 'sec_unexpected_shape.json')
        req = ConceptRequest('0000320193', 'us-gaap', 'Revenues', 'revenue')
        with self.assertRaises(IngestError) as ctx:
            sec.normalize_concept(payload, req, 'h', 'now')
        self.assertEqual(ctx.exception.error_class, http.SCHEMA)

    def test_missing_accession_is_a_schema_error(self):
        payload = {'cik': 320193, 'taxonomy': 'us-gaap', 'tag': 'Revenues',
                   'units': {'USD': [{'start': '2025-01-01', 'end': '2025-12-31', 'val': 1}]}}
        req = ConceptRequest('0000320193', 'us-gaap', 'Revenues', 'revenue')
        with self.assertRaises(IngestError):
            sec.normalize_concept(payload, req, 'h', 'now')


class FilingRelationTests(unittest.TestCase):
    def test_amendment_forms_are_marked(self):
        self.assertEqual(filing_relation('10-K/A'), sec.AMENDMENT)
        self.assertEqual(filing_relation('10-Q/A'), sec.AMENDMENT)

    def test_an_ordinary_form_alone_is_unknown_until_the_batch_decides(self):
        # A single row cannot evidence that it is the first report of the period.
        self.assertEqual(filing_relation('10-K'), sec.UNKNOWN)
        self.assertEqual(filing_relation('20-F'), sec.UNKNOWN)
        self.assertEqual(filing_relation(None), sec.UNKNOWN)

    def test_a_new_accession_without_a_slash_a_is_not_called_an_amendment(self):
        self.assertNotEqual(filing_relation('10-Q'), sec.AMENDMENT)


class SelectionTests(unittest.TestCase):
    def _fact(self, accn, filed, form='10-K'):
        return {'cik': '0000320193', 'taxonomy': 'us-gaap', 'tag': 'Revenues', 'unit': 'USD',
                'period_start': '2024-09-29', 'period_end': '2025-09-27', 'accn': accn,
                'filed': filed, 'form': form}

    def test_the_latest_filing_becomes_current_and_the_original_is_kept(self):
        facts = [self._fact('a1', '2025-11-01'), self._fact('a2', '2026-02-10', '10-K/A')]
        plan = sec.plan_selection(facts)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0][1], 'a2')

    def test_selection_is_deterministic_when_dates_match(self):
        facts = [self._fact('a1', '2025-11-01'), self._fact('a2', '2025-11-01')]
        self.assertEqual(sec.plan_selection(facts)[0][1], 'a2')


class YtdDerivationTests(unittest.TestCase):
    def _ytd(self, **kw):
        base = {'cik': '0000320193', 'taxonomy': 'us-gaap', 'tag': 'Revenues', 'unit': 'USD',
                'fy': 2026, 'period_start': '2025-09-28', 'period_end': '2026-06-27',
                'value_num': 310.0, 'quality_flags': ''}
        base.update(kw)
        return base

    def test_derives_a_quarter_when_all_conditions_hold(self):
        current = self._ytd()
        prior = self._ytd(period_end='2026-03-28', value_num=200.0)
        self.assertEqual(derive_quarter(current, prior), 110.0)

    def test_refuses_when_the_ytd_start_differs(self):
        current = self._ytd()
        prior = self._ytd(period_start='2024-09-28', period_end='2026-03-28', value_num=200.0)
        ok, reasons = can_derive_quarter(current, prior)
        self.assertFalse(ok)
        self.assertIn('different_ytd_start', reasons)
        self.assertIsNone(derive_quarter(current, prior))

    def test_refuses_across_fiscal_years(self):
        ok, reasons = can_derive_quarter(self._ytd(), self._ytd(fy=2025, value_num=1.0,
                                                                period_end='2025-12-27'))
        self.assertFalse(ok)
        self.assertIn('different_fiscal_year', reasons)

    def test_refuses_when_a_value_is_missing(self):
        ok, reasons = can_derive_quarter(self._ytd(value_num=None),
                                         self._ytd(period_end='2026-03-28', value_num=1.0))
        self.assertFalse(ok)
        self.assertIn('missing_value', reasons)

    def test_refuses_when_the_periods_are_not_sequential(self):
        ok, reasons = can_derive_quarter(self._ytd(), self._ytd(period_end='2026-07-01', value_num=1.0))
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
