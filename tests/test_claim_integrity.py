import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import unified, unified_main
from opportunity_radar.store import Store
from opportunity_radar.unified import UnifiedStore


def article(key='k1', published='2026-11-01T08:00:00+00:00'):
    return SimpleNamespace(article_id=key, title='t-' + key, url='https://example.org/' + key,
                           published=published, source_name='Test', summary='body',
                           feed_id='1', fetched_at='', content_source='', retrieval_status='')


def evidence(evidence_id='ev-1', article_key='k1', source_id='bbc-business',
             locator=None, quote='Revenue rose 5%'):
    return {'evidence_id': evidence_id, 'article_key': article_key, 'source_id': source_id,
            'evidence_kind': 'quote', 'quote': quote,
            'locator_json': json.dumps(locator or {'field': 'summary', 'start': 0, 'length': 14}),
            'source_family': source_id, 'independence': 'unknown', 'observed_at': None,
            'rules_version': 'r1-v1', 'created_at': 't'}


def claim(claim_id='cl-1', article_key='k1', period='', extractor='skeleton',
          state='unverified', locator=None):
    return {'claim_id': claim_id, 'article_key': article_key, 'event_id': None,
            'fact_ordinal': 1, 'subject': 'ONS', 'predicate': 'assertion',
            'value_num': None, 'value_text': 'Revenue rose 5%', 'unit': '', 'currency': '',
            'region': '', 'period': period, 'period_raw': '', 'comparison': '',
            'denominator': '', 'seasonality': '', 'revision': '', 'kind': 'fact',
            'quote': 'Revenue rose 5%',
            'locator_json': json.dumps(locator or {'field': 'summary', 'start': 0, 'length': 14}),
            'verification_state': state, 'extractor': extractor,
            'rules_version': 'r1-v1', 'created_at': 't'}


def link(claim_id='cl-1', evidence_id='ev-1'):
    return (claim_id, evidence_id, 'direct', 'unknown', '{}', 't')


class BulkIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def tearDown(self):
        self.tmp.cleanup()

    def add_article(self, key='k1', published='2026-11-01T08:00:00+00:00'):
        self.store.save_article(article(key, published), key)

    def test_a_valid_claim_evidence_pair_is_written(self):
        self.add_article()
        result = self.uni.bulk_add([evidence()], [claim()], [link()])
        self.assertEqual((result['evidences'], result['claims'], result['links']), (1, 1, 1))
        self.assertEqual(result['claims_rejected'], 0)
        self.assertEqual(self.uni.counts()['claim_evidence'], 1)

    def test_a_claim_and_its_evidence_must_point_at_the_same_article(self):
        self.add_article('k1')
        self.add_article('k2')
        result = self.uni.bulk_add([evidence(article_key='k2')], [claim(article_key='k1')], [link()])
        self.assertEqual((result['claims'], result['links']), (0, 0))
        self.assertEqual(result['links_rejected'], 1)
        reasons = {r for item in result['rejected'] for r in item['reasons']}
        self.assertIn('claim_evidence_article_mismatch', reasons)

    def test_a_claim_without_evidence_is_refused(self):
        self.add_article()
        result = self.uni.bulk_add([evidence()], [claim()], [])
        self.assertEqual((result['evidences'], result['claims']), (1, 0))
        self.assertEqual(result['claims_rejected'], 1)
        self.assertIn('claim_evidence_missing', result['rejected'][0]['reasons'])

    def test_evidence_without_source_is_refused_with_its_claim(self):
        self.add_article()
        result = self.uni.bulk_add([evidence(source_id='')], [claim()], [link()])
        self.assertEqual((result['evidences'], result['claims'], result['links']), (0, 0, 0))
        self.assertEqual(result['evidences_rejected'], 1)
        self.assertEqual(result['claims_rejected'], 1)
        self.assertEqual(result['links_rejected'], 1)
        reasons = {r for item in result['rejected'] for r in item['reasons']}
        self.assertIn('source_id_missing', reasons)

    def test_evidence_for_an_unknown_article_is_refused(self):
        self.add_article()
        result = self.uni.bulk_add([evidence(article_key='missing')], [claim()], [link()])
        self.assertEqual((result['evidences'], result['claims']), (0, 0))
        self.assertEqual(result['evidences_rejected'], 1)
        reasons = {r for item in result['rejected'] for r in item['reasons']}
        self.assertIn('article_not_found', reasons)

    def test_evidence_without_a_locator_is_refused(self):
        self.add_article()
        bad = evidence()
        bad['locator_json'] = '{}'
        result = self.uni.bulk_add([bad], [claim()], [link()])
        self.assertEqual((result['evidences'], result['claims']), (0, 0))
        reasons = {r for item in result['rejected'] for r in item['reasons']}
        self.assertIn('locator_missing', reasons)

    def test_a_verified_claim_cannot_be_inserted_as_new(self):
        self.add_article()
        result = self.uni.bulk_add([evidence()], [claim(state='verified')], [link()])
        self.assertEqual(result['claims'], 0)
        self.assertIn('claim_not_unverified', result['rejected'][0]['reasons'])


class SkeletonPeriodRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))
        self.store.save_article(article('k1', '2026-11-01T08:00:00+00:00'), 'k1')
        self.store.save_article(article('k2', '2026-11-02T08:00:00+00:00'), 'k2')

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, cid, period, article_key='k1', extractor='skeleton', state='unverified'):
        cl = claim(cid, article_key=article_key, period=period, extractor=extractor, state=state)
        self.uni.add_claim(cl)
        return cl

    def test_only_a_publication_date_period_is_corrected(self):
        self.add('safe', '2026-11-01')
        self.add('other', '2026-10-01')
        self.add('raw', '2026-11-01')
        with self.uni.connect() as conn:
            conn.execute("UPDATE claims SET period_raw='september' WHERE claim_id='raw'")
        self.add('structured', '2026-11-01', extractor='structured')

        result = unified.repair_skeleton_periods(self.uni, apply=True)
        self.assertEqual(result['skeleton_claims'], 3)
        self.assertEqual(result['eligible'], 1)
        self.assertEqual(result['corrected'], 1)
        self.assertEqual(result['pending'], 2)
        self.assertEqual(result['pending_reasons'], {'period_not_publication_date': 1,
                                                    'period_raw_present': 1})
        with self.uni.connect() as conn:
            rows = {r['claim_id']: dict(r) for r in conn.execute('SELECT claim_id, period FROM claims')}
            corrections = [dict(r) for r in conn.execute('SELECT * FROM claim_corrections')]
        self.assertEqual(rows['safe']['period'], '')
        self.assertEqual(rows['other']['period'], '2026-10-01')
        self.assertEqual(rows['raw']['period'], '2026-11-01')
        self.assertEqual(rows['structured']['period'], '2026-11-01')
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]['claim_id'], 'safe')

    def test_a_verified_skeleton_claim_is_left_for_review(self):
        self.add('verified', '2026-11-01')
        with self.uni.connect() as conn:
            conn.execute("UPDATE claims SET verification_state='verified' WHERE claim_id='verified'")
        result = unified.repair_skeleton_periods(self.uni, apply=True)
        self.assertEqual(result['corrected'], 0)
        self.assertEqual(result['pending_reasons'], {'claim_not_unverified': 1})
        with self.uni.connect() as conn:
            row = conn.execute("SELECT period, verification_state FROM claims WHERE claim_id='verified'").fetchone()
        self.assertEqual(tuple(row), ('2026-11-01', 'verified'))

    def test_dry_run_reports_the_candidate_without_writing(self):
        self.add('safe', '2026-11-01')
        result = unified.repair_skeleton_periods(self.uni, apply=False)
        self.assertEqual((result['eligible'], result['corrected']), (1, 0))
        with self.uni.connect() as conn:
            period = conn.execute("SELECT period FROM claims WHERE claim_id='safe'").fetchone()[0]
            corrections = conn.execute('SELECT COUNT(*) FROM claim_corrections').fetchone()[0]
        self.assertEqual((period, corrections), ('2026-11-01', 0))


class PeriodAuditReadOnlyTests(unittest.TestCase):
    def test_audit_does_not_migrate_an_old_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'old.sqlite3'
            Store(str(db))
            with contextlib.closing(sqlite3.connect(db)) as conn:
                conn.execute('DROP TABLE claim_corrections')
                conn.execute('PRAGMA user_version = 6')
                conn.commit()
            with contextlib.redirect_stdout(io.StringIO()):
                unified_main.main(['periods', '--db', str(db), '--json'])
            with contextlib.closing(sqlite3.connect(db)) as conn:
                version = conn.execute('PRAGMA user_version').fetchone()[0]
                table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='claim_corrections'").fetchone()
            self.assertEqual(version, 6)
            self.assertIsNone(table)


if __name__ == '__main__':
    unittest.main()
