"""R2 verification: the traps the rules exist for.

Every case here is a claim that *looks* fine and is not: a value that is not in the quote,
a unit that belongs to another family, a period that does not match the evidence record, a
percentage point presented as a percentage, a year-over-year claim resting on a
month-over-month sentence, and two sources disagreeing about the same number.
"""
import json
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import claim_contract, units, verify
from opportunity_radar.unified import UnifiedStore

SCHEMA_FOR_TESTS = None


def evidence(evidence_id, quote, locator=None, source='bbc-business', kind='quote'):
    return {'evidence_id': evidence_id, 'article_key': '', 'source_id': source, 'evidence_kind': kind,
            'quote': quote, 'locator_json': json.dumps(locator or {'field': 'summary', 'start': 0, 'length': 10}),
            'source_family': source, 'independence': 'unknown', 'observed_at': None,
            'rules_version': 'r1-v1', 'created_at': 't'}


def claim(claim_id='cl-1', value=5.2, unit='%', period='2026-Q3', predicate='retail_sales_growth',
          subject='ONS', comparison='unknown', quote='', extractor='structured', kind='fact'):
    return {'claim_id': claim_id, 'article_key': '', 'event_id': None, 'fact_ordinal': None,
            'subject': subject, 'predicate': predicate, 'value_num': value, 'value_text': '',
            'unit': unit, 'currency': '', 'region': 'UK', 'period': period, 'comparison': comparison,
            'denominator': '', 'seasonality': '', 'revision': '', 'kind': kind, 'quote': quote,
            'locator_json': '{}', 'verification_state': 'unverified', 'extractor': extractor,
            'rules_version': 'r1-v1', 'created_at': 't'}


class UnitRuleTests(unittest.TestCase):
    def test_percent_and_percentage_point_are_not_interchangeable(self):
        self.assertIsNone(units.convert(5, '%', 'pp'))
        self.assertNotEqual(units.unit_family('%'), units.unit_family('percentage points'))

    def test_scales_are_read_on_either_side_of_the_unit(self):
        self.assertEqual(units.convert(2, 'USD million', 'USD'), 2_000_000)
        self.assertEqual(units.split_unit('thousand megawatthours'), ('megawatthours', 1000.0))

    def test_numbers_do_not_swallow_a_bare_space(self):
        self.assertEqual([v for v, _ in units.quantities('2026-08 70937.35 thousand')],
                         [2026.0, 8.0, 70937.35 * 1000])

    def test_grouped_numbers_are_parsed(self):
        self.assertEqual(units.parse_number('1,234.5'), 1234.5)
        self.assertEqual(units.parse_number('(1.2)'), -1.2)
        self.assertIsNone(units.parse_number('n/a'))


class ContractTests(unittest.TestCase):
    def test_a_bad_field_becomes_a_deviation_not_a_lost_claim(self):
        parsed, deviations = claim_contract.normalize({
            'subject': 'ONS', 'predicate': 'retail_sales', 'kind': 'fact',
            'value_num': 'not a number', 'unit': 'widgets', 'period': 'next quarter'})
        self.assertTrue(parsed['subject'])
        self.assertIsNone(parsed['value_num'])
        self.assertEqual(parsed['period'], '')
        reasons = {(d['field'], d['reason']) for d in deviations}
        self.assertIn(('value_num', 'not_numeric'), reasons)
        self.assertIn(('period', 'unrecognised_format'), reasons)
        self.assertIn(('unit', 'unknown_unit'), reasons)

    def test_a_claim_without_subject_is_dropped_but_others_survive(self):
        claims, deviations = claim_contract.parse_claims({'claims': [
            {'predicate': 'x', 'kind': 'fact'},
            {'subject': 'ONS', 'predicate': 'y', 'kind': 'fact', 'value_num': 1, 'unit': '%'}]})
        self.assertEqual(len(claims), 1)
        self.assertTrue(any(d['reason'] == 'claim_without_subject_or_predicate' for d in deviations))

    def test_currency_is_derived_from_the_unit_only_when_it_is_a_currency(self):
        parsed, _ = claim_contract.normalize({'subject': 'A', 'predicate': 'b', 'kind': 'fact',
                                              'value_num': 1, 'unit': 'USD million'})
        self.assertEqual(parsed['currency'], 'USD')


class SupportTests(unittest.TestCase):
    def check(self, c, e):
        return verify.check_claim(c, e)

    def test_a_value_in_the_quote_is_direct_support(self):
        result = self.check(claim(value=5.2), evidence('ev-1', 'Retail sales rose 5.2% in September'))
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(result['support'], 'direct')

    def test_a_quote_with_a_different_value_is_a_contradiction(self):
        result = self.check(claim(value=5.2), evidence('ev-1', 'Retail sales rose 3.1% in September'))
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(result['support'], 'contradiction')
        self.assertIn('value_in_quote', result['basis'])

    def test_a_quote_without_a_comparable_number_is_unsupported(self):
        result = self.check(claim(value=5.2), evidence('ev-1', 'Retail sales rose in September'))
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(result['support'], 'unsupported')

    def test_a_percentage_point_claimed_as_percent_is_rejected(self):
        result = self.check(claim(value=3, unit='%'), evidence('ev-1', 'The rate rose 3 percentage points'))
        self.assertEqual(result['state'], 'rejected')
        self.assertTrue(any(c['name'] == 'unit' and c['result'] == 'fail' for c in result['checks']))

    def test_a_unit_of_another_family_is_rejected(self):
        result = self.check(claim(value=5.2, unit='%'), evidence('ev-1', 'Revenue reached 5.2 million USD'))
        self.assertEqual(result['state'], 'rejected')
        self.assertTrue(any(c['name'] == 'unit' and c['result'] == 'fail' for c in result['checks']))

    def test_a_period_that_does_not_match_the_evidence_is_rejected(self):
        result = self.check(claim(value=5.2, period='2026-Q3'),
                            evidence('ev-1', 'Retail sales rose 5.2%', locator={'period_end': '2026-06-30'}))
        self.assertEqual(result['state'], 'rejected')
        self.assertIn('period', result['basis'])

    def test_a_period_that_matches_the_evidence_passes(self):
        result = self.check(claim(value=5.2, period='2026-06-30'),
                            evidence('ev-1', 'Retail sales rose 5.2%', locator={'period_end': '2026-06-30'}))
        self.assertEqual(result['state'], 'verified')

    def test_a_yoy_claim_resting_on_a_mom_sentence_is_rejected(self):
        result = self.check(claim(value=5.2, comparison='year_over_year'),
                            evidence('ev-1', 'Retail sales rose 5.2% month-over-month'))
        self.assertEqual(result['state'], 'rejected')
        self.assertIn('comparison', result['basis'])

    def test_a_skeleton_claim_is_never_verified(self):
        skeleton = claim(value=None, unit='', predicate='assertion', extractor='skeleton', quote='something')
        result = self.check(skeleton, evidence('ev-1', 'something'))
        self.assertEqual(result['state'], 'unverifiable')
        self.assertEqual(result['basis'], 'skeleton_no_structured_fields')

    def test_a_claim_without_evidence_is_unverifiable(self):
        result = self.check(claim(value=5.2), None)
        self.assertEqual(result['state'], 'unverifiable')
        self.assertEqual(result['basis'], 'no_evidence')

    def test_energy_units_are_compared_through_their_scale(self):
        result = self.check(claim(value=70937.35658, unit='thousand megawatthours', period='2026-08'),
                            evidence('ev-1', 'series 2026-08 70937.35658 thousand megawatthours',
                                     locator={'period': '2026-08'}))
        self.assertEqual(result['state'], 'verified')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-verify-'))
        self.db = self.dir / 'db.sqlite3'
        self.store = UnifiedStore(str(self.db))

    def add(self, c, ev):
        self.store.add_evidence(ev)
        self.store.add_claim(c)
        self.store.link(c['claim_id'], ev['evidence_id'])

    def test_verification_is_persisted_and_idempotent(self):
        self.add(claim(), evidence('ev-1', 'Retail sales rose 5.2%'))
        first = verify.verify(self.store)
        second = verify.verify(self.store)
        self.assertEqual(first['by_state'], {'verified': 1})
        self.assertEqual(second['written'], 1)          # writes are attempted, rows are ignored
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM claim_verifications').fetchone()[0], 1)
            row = conn.execute('SELECT verification_state, verification_basis FROM claims').fetchone()
            support = conn.execute('SELECT support FROM claim_evidence').fetchone()[0]
        self.assertEqual(row[0], 'verified')
        self.assertEqual(support, 'direct')

    def test_history_is_appended_when_the_evidence_changes(self):
        self.add(claim(), evidence('ev-1', 'Retail sales rose 5.2%'))
        verify.verify(self.store)
        with self.store.connect() as conn:
            conn.execute("UPDATE evidences SET quote='Retail sales rose 3.1%'")
        verify.verify(self.store)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM claim_verifications').fetchone()[0], 2)
            self.assertEqual(conn.execute('SELECT verification_state FROM claims').fetchone()[0], 'rejected')

    def test_conflicting_values_are_recorded(self):
        self.add(claim('cl-1', value=5.2), evidence('ev-1', 'Retail sales rose 5.2%'))
        self.add(claim('cl-2', value=3.1), evidence('ev-2', 'Retail sales rose 3.1%'))
        verify.verify(self.store)
        with self.store.connect() as conn:
            rows = [dict(r) for r in conn.execute('SELECT * FROM claim_conflicts')]
        self.assertEqual(len(rows), 1)
        detail = json.loads(rows[0]['detail_json'])
        self.assertEqual({detail['a'], detail['b']}, {5.2, 3.1})
        self.assertEqual(rows[0]['reason'], 'value_differs_same_measure')

    def test_two_sources_saying_the_same_number_are_not_a_conflict(self):
        self.add(claim('cl-1', value=5.2), evidence('ev-1', 'Retail sales rose 5.2%'))
        self.add(claim('cl-2', value=5.2), evidence('ev-2', 'Retail sales rose 5.2%'))
        verify.verify(self.store)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM claim_conflicts').fetchone()[0], 0)

    def test_dry_run_writes_nothing(self):
        self.add(claim(), evidence('ev-1', 'Retail sales rose 5.2%'))
        report = verify.verify(self.store, dry_run=True)
        self.assertEqual(report['by_state'], {'verified': 1})
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM claim_verifications').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT verification_state FROM claims').fetchone()[0], 'unverified')

    def test_the_verdict_points_back_at_the_evidence(self):
        self.add(claim(), evidence('ev-1', 'Retail sales rose 5.2%'))
        verify.verify(self.store)
        with self.store.connect() as conn:
            row = dict(conn.execute('SELECT * FROM claim_verifications').fetchone())
        checks = {c['name']: c['result'] for c in json.loads(row['checks_json'])}
        self.assertEqual(checks['value_in_quote'], 'pass')
        self.assertEqual(row['rules_version'], verify.RULES_VERSION)



class ConflictDisplayTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-conflicts-'))
        self.store = UnifiedStore(str(self.dir / 'db.sqlite3'))

    def add(self, claim_id, value, revision='', comparison='unknown', period='2026-Q3', unit='%'):
        self.store.add_evidence(evidence('ev-' + claim_id, 'value %s' % value))
        self.store.add_claim(claim(claim_id, value=value, unit=unit, period=period,
                                   comparison=comparison))
        self.store.link(claim_id, 'ev-' + claim_id)
        with self.store.connect() as conn:
            conn.execute('UPDATE claims SET revision=? WHERE claim_id=?', (revision, claim_id))

    def test_a_revision_pair_is_classified_as_a_restatement(self):
        self.add('cl-1', 1750000000.0, revision='original', unit='USD')
        self.add('cl-2', 1675000000.0, revision='subsequent_comparative', unit='USD')
        verify.verify(self.store)
        found = verify.conflicts_report(self.store)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['classification'], 'restatement')
        self.assertEqual({s['value_num'] for s in found[0]['sides']}, {1750000000.0, 1675000000.0})

    def test_two_records_with_the_same_status_stay_unclassified(self):
        self.add('cl-1', 1.0, revision='subsequent_comparative')
        self.add('cl-2', 2.0, revision='subsequent_comparative')
        verify.verify(self.store)
        self.assertEqual(verify.conflicts_report(self.store)[0]['classification'], 'unclassified')

    def test_a_comparison_basis_difference_is_recorded_even_when_values_agree(self):
        self.add('cl-1', 5.2, comparison='year_over_year')
        self.add('cl-2', 5.2, comparison='month_over_month')
        verify.verify(self.store)
        reasons = {c['reason'] for c in verify.conflicts_report(self.store)}
        self.assertEqual(reasons, {'comparison_basis_differs'})

    def test_the_report_lists_both_sides_with_source_and_locator(self):
        self.add('cl-1', 1.0)
        self.add('cl-2', 2.0)
        verify.verify(self.store)
        lines = verify.conflict_lines(verify.conflicts_report(self.store))
        text = chr(10).join(lines)
        self.assertIn('cl-1', text)
        self.assertIn('来源 bbc-business', text)
        self.assertIn('ev-cl-1', text)

    def test_nothing_is_written_when_there_is_no_conflict(self):
        self.add('cl-1', 1.0)
        verify.verify(self.store)
        self.assertEqual(verify.conflicts_report(self.store), [])


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-audit-'))
        self.store = UnifiedStore(str(self.dir / 'db.sqlite3'))

    def test_a_skipped_check_is_reported_as_skipped_not_passed(self):
        self.store.add_evidence(evidence('ev-1', 'Retail sales rose 5.2%'))
        self.store.add_claim(claim(value=5.2, period='', comparison='unknown'))
        self.store.link('cl-1', 'ev-1')
        verify.verify(self.store)
        report = verify.audit(self.store)
        self.assertEqual(report['states'], {'verified': 1})
        self.assertEqual(report['per_check']['value_in_quote']['pass'], 1)
        self.assertEqual(report['per_check']['period']['skip'], 1)
        self.assertEqual(report['verified_with_skipped_check'], {'period': 1, 'comparison': 1})
        self.assertEqual(report['verified_without_any_pass'], 0)

    def test_a_verified_claim_always_has_at_least_one_passing_check(self):
        self.store.add_evidence(evidence('ev-1', 'Retail sales rose 5.2%'))
        self.store.add_claim(claim(value=5.2))
        self.store.link('cl-1', 'ev-1')
        verify.verify(self.store)
        self.assertEqual(verify.audit(self.store)['verified_without_any_pass'], 0)

    def test_a_number_without_a_unit_is_not_verified(self):
        self.store.add_evidence(evidence('ev-1', 'Retail sales rose 5.2%'))
        self.store.add_claim(claim(value=5.2, unit=''))     # no unit declared
        self.store.link('cl-1', 'ev-1')
        verify.verify(self.store)
        report = verify.audit(self.store)
        self.assertEqual(report['states'], {'unverifiable': 1})
        self.assertEqual(report['verified_with_missing_field']['unit'], 0)

    def test_a_skeleton_claim_never_shows_up_as_verified(self):
        self.store.add_evidence(evidence('ev-1', 'some prose'))
        self.store.add_claim(claim(value=None, unit='', predicate='assertion', extractor='skeleton'))
        self.store.link('cl-1', 'ev-1')
        verify.verify(self.store)
        report = verify.audit(self.store)
        self.assertEqual(report['states'], {'unverifiable': 1})
        self.assertEqual(report['verified_with_skipped_check'], {})



if __name__ == '__main__':
    unittest.main()