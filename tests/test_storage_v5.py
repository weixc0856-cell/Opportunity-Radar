"""Contract tests for the analysis_sections projection table.

Expected to fail before implementation: `Store` has no `analysis_sections` reader and
`save_analysis` does not project facts, inferences, gaps or actions into child rows.

The projection is append-only by analysed_at (the latest version is the default read),
and every write happens in the same SQLite transaction as analyses/analysis_history.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from opportunity_radar.store import Store

KEY = Store.key('https://example.invalid/retail')
STAMP_1 = '2026-10-26T00:00:00+00:00'
STAMP_2 = '2026-10-27T00:00:00+00:00'
Q1 = 'Retail sales volumes are estimated to have risen by 0.5% in September 2026.'
Q2 = 'Volumes remain below their pre-pandemic level.'
Q3 = 'Retail sales volumes rose by 4.2% in September 2026.'


def fact(ordinal, status, evidence_id, quote, text):
    return {
        'ordinal': ordinal,
        'text': text,
        'quote': quote,
        'actor': 'UK ONS',
        'status': status,
        'evidence_id': evidence_id,
        'locator': {'field': 'summary', 'start': 0, 'length': len(quote)} if evidence_id else None,
        'reason': '' if evidence_id else 'quote_not_in_text',
        'source_url': 'https://example.invalid/retail',
        'published': '2026-10-23T09:30:00+00:00',
    }


def analysis_v5():
    return {
        'schema_version': 5,
        'category': 'market_change',
        'summary_zh': '英国 9 月零售销售环比回升，但材料没有说明驱动因素。',
        'relevance': 'core',
        'confidence': 'medium',
        'revenue_claim': 'none',
        'actionability': 'investigate',
        'facts': [
            fact(1, 'located', 'e1', Q1, '英国 2026 年 9 月零售销售量环比上升。'),
            fact(2, 'unlocated', None, Q3, '零售销售量上升 4.2%。'),
        ],
        'inferences': [
            {'ordinal': 1, 'text': '消费需求可能在第三季度末回暖。', 'basis': [1],
             'confidence': 'low', 'assumptions': ['单月数据能代表趋势'], 'status': 'supported'},
            {'ordinal': 2, 'text': '零售商会增加招聘。', 'basis': [2],
             'confidence': 'low', 'assumptions': [], 'status': 'unsupported'},
        ],
        'gaps': [
            {'ordinal': 1, 'missing': '分品类与分地区的零售销售明细',
             'why_it_matters': '决定回暖是否普遍', 'how_to_close': '查 ONS 配套数据表', 'status': 'open'},
        ],
        'actions': [
            {'ordinal': 1, 'step': '调取 ONS 原始数据表，核对分品类贡献', 'kind': 'verify',
             'done_when': '确认至少三个品类的变化', 'status': 'open'},
        ],
        'evidence_quotes': [Q1],
        'uncertainties': ['分品类与分地区的零售销售明细'],
        'suggested_next_step': '调取 ONS 原始数据表，核对分品类贡献',
        'pain_point': 'unknown',
        'target_customer': 'unknown',
        'commercial_signal': '零售回暖可能带动相关服务需求，但没有采购或付费证据。',
        'schema_deviations': [],
    }


def analysis_v4():
    return {
        'schema_version': 4,
        'category': 'market_change',
        'summary_zh': '英国 9 月零售销售环比回升。',
        'pain_point': 'unknown',
        'target_customer': 'unknown',
        'commercial_signal': '材料没有给出采购或付费证据。',
        'revenue_claim': 'none',
        'evidence_quotes': [Q2],
        'uncertainties': ['分品类明细未知'],
        'suggested_next_step': '查 ONS 原始数据表',
        'relevance_score': 85,
        'confidence': 'medium',
        'actionability': 'monitor',
    }


SCORE = {'score': 78, 'status': 'priority', 'risk_flag': ''}


class ProjectionWriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self._tmp.name) / 'test.sqlite3'))

    def tearDown(self):
        self._tmp.cleanup()

    def test_each_entry_becomes_one_row_with_its_kind_and_status(self):
        self.store.save_analysis(KEY, analysis_v5(), SCORE)
        rows = self.store.analysis_sections(KEY)
        self.assertEqual(len(rows), 6)
        facts = [r for r in rows if r['kind'] == 'fact']
        inferences = [r for r in rows if r['kind'] == 'inference']
        gaps = [r for r in rows if r['kind'] == 'gap']
        actions = [r for r in rows if r['kind'] == 'action']
        self.assertEqual([r['ordinal'] for r in facts], [1, 2])
        self.assertEqual([r['status'] for r in facts], ['located', 'unlocated'])
        self.assertEqual([r['evidence_id'] for r in facts], ['e1', None])
        self.assertEqual(facts[0]['text'], '英国 2026 年 9 月零售销售量环比上升。')
        self.assertEqual(len(inferences), 2)
        self.assertEqual([r['status'] for r in inferences], ['supported', 'unsupported'])
        self.assertEqual(len(gaps), 1)
        self.assertEqual(len(actions), 1)

    def test_meta_keeps_the_audit_fields(self):
        self.store.save_analysis(KEY, analysis_v5(), SCORE)
        rows = self.store.analysis_sections(KEY)
        facts = [r for r in rows if r['kind'] == 'fact']
        inferences = [r for r in rows if r['kind'] == 'inference']
        gaps = [r for r in rows if r['kind'] == 'gap']
        actions = [r for r in rows if r['kind'] == 'action']
        self.assertEqual(facts[0]['meta']['actor'], 'UK ONS')
        self.assertEqual(facts[0]['meta']['source_url'], 'https://example.invalid/retail')
        self.assertEqual(facts[0]['meta']['locator']['field'], 'summary')
        self.assertEqual(inferences[0]['meta']['basis'], [1])
        self.assertEqual(inferences[0]['meta']['confidence'], 'low')
        self.assertEqual(gaps[0]['meta']['why_it_matters'], '决定回暖是否普遍')
        self.assertEqual(actions[0]['meta']['kind'], 'verify')
        self.assertEqual(actions[0]['meta']['done_when'], '确认至少三个品类的变化')

    def test_result_json_remains_the_full_replayable_record(self):
        self.store.save_analysis(KEY, analysis_v5(), SCORE)
        with self.store.connect() as c:
            row = c.execute('SELECT result_json FROM analyses WHERE article_key=?', (KEY,)).fetchone()
        stored = json.loads(row['result_json'])
        self.assertEqual(stored['analysis']['schema_version'], 5)
        self.assertEqual(stored['analysis']['facts'][0]['status'], 'located')

    def test_v4_analysis_writes_no_sections(self):
        self.store.save_analysis(KEY, analysis_v4(), SCORE)
        self.assertEqual(self.store.analysis_sections(KEY), [])

    def test_sections_are_versioned_and_latest_is_the_default_read(self):
        with mock.patch('opportunity_radar.store.now', return_value=STAMP_1):
            self.store.save_analysis(KEY, analysis_v5(), SCORE)
        with mock.patch('opportunity_radar.store.now', return_value=STAMP_2):
            self.store.save_analysis(KEY, analysis_v5(), SCORE)
        latest = self.store.analysis_sections(KEY)
        self.assertEqual(len(latest), 6)
        self.assertEqual({r['analyzed_at'] for r in latest}, {STAMP_2})
        first = self.store.analysis_sections(KEY, analyzed_at=STAMP_1)
        self.assertEqual(len(first), 6)
        self.assertEqual({r['analyzed_at'] for r in first}, {STAMP_1})


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self._tmp.name) / 'test.sqlite3'))

    def tearDown(self):
        self._tmp.cleanup()

    def test_duplicate_ordinal_rolls_back_parent_and_child_rows(self):
        broken = analysis_v5()
        broken['facts'] = [
            fact(1, 'located', 'e1', Q1, '事实一'),
            fact(1, 'located', 'e2', Q2, '事实一重复序号'),
        ]
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_analysis(KEY, broken, SCORE)
        with self.store.connect() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM analyses WHERE article_key=?', (KEY,)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM analysis_history WHERE article_key=?', (KEY,)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM analysis_sections WHERE article_key=?', (KEY,)).fetchone())
        # The rollback must leave the store usable for the next, valid analysis.
        self.store.save_analysis(KEY, analysis_v5(), SCORE)
        self.assertEqual(len(self.store.analysis_sections(KEY)), 6)


if __name__ == '__main__':
    unittest.main()
