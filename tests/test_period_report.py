"""Monthly regression verification and line/angle aggregation over a stored graph.

Locks the semantics: confirmed / contradicted / open / insufficient classification,
single-source never counts as independent corroboration, gaps and denominator visible.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import period_report
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore

BASE = '2026-09-01T00:00:00+00:00'   # before the previous-calendar-month window -> baseline
NEW = '2026-10-10T00:00:00+00:00'    # inside the previous calendar month (October)
END = '2026-11-01T00:00:00+00:00'    # start of November -> monthly window = [Oct 1, Nov 1)

SOURCES = [
    {'source_id': 'gov', 'source_type': 'government', 'provenance_class': 'official_primary',
     'intelligence_lines': 'policy_regulation'},
    {'source_id': 'media', 'source_type': 'news_media', 'provenance_class': 'professional_media',
     'intelligence_lines': 'international_news'},
    {'source_id': 'ir', 'source_type': 'investor_relations', 'provenance_class': 'official_primary',
     'intelligence_lines': 'corporate_capital'},
]


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'db.sqlite3')
        self.store = Store(self.db)
        self.uni = UnifiedStore(self.db)
        self._seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def _article(self, aid, source_id, published):
        self._seq += 1
        url = f'https://example.org/{aid}'
        ns = SimpleNamespace(article_id=aid, title=f'title {aid}', url=url, summary='s',
                             published=published, source_name=source_id, feed_id='1',
                             fetched_at='', content_source='', retrieval_status='')
        key = Store.key(url)
        self.store.save_article(ns, key, source_id=source_id)
        return key

    def _evidence(self, eid, key, source_id, family, created):
        self.uni.add_evidence({'evidence_id': eid, 'article_key': key, 'source_id': source_id,
                               'evidence_kind': 'quote', 'quote': 'q',
                               'locator_json': '{"field":"summary","start":0,"length":1}',
                               'source_family': family, 'independence': 'unknown',
                               'observed_at': None, 'rules_version': 'r1-v1', 'created_at': created})

    def _claim(self, cid, key, subject, predicate, created, published, value_num=None,
               state='unverified'):
        self.uni.add_claim({'claim_id': cid, 'article_key': key, 'event_id': None,
                            'fact_ordinal': 1, 'subject': subject, 'predicate': predicate,
                            'value_num': value_num, 'value_text': '' if value_num is not None else 'v',
                            'unit': '', 'unit_raw': '', 'scale': '', 'currency': '', 'region': '',
                            'period': '', 'period_raw': '', 'comparison': '', 'denominator': '',
                            'seasonality': '', 'revision': '', 'revision_raw': '', 'kind': 'fact',
                            'quote': 'q', 'locator_json': '{"field":"summary","start":0,"length":1}',
                            'verification_state': state, 'extractor': 'skeleton',
                            'rules_version': 'r1-v1', 'created_at': created})

    def _link(self, cid, eid, created):
        with self.uni.connect() as conn:
            conn.execute('INSERT INTO claim_evidence VALUES(?,?,?,?,?,?)',
                         (cid, eid, 'direct', 'unknown', '{}', created))

    def _verification(self, vid, cid, state, support, created):
        with self.uni.connect() as conn:
            conn.execute('INSERT INTO claim_verifications VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (vid, cid, 'r1-v1', '', 'h' + vid, state, support, '', '[]', '[]', created))

    def _conflict(self, fid, a, b, created):
        with self.uni.connect() as conn:
            conn.execute('INSERT INTO claim_conflicts VALUES(?,?,?,?,?,?)',
                         (fid, a, b, 'value_mismatch', '{}', created))

    def _build(self):
        return period_report.build(self.db, 'monthly', end=END,
                                   economic_db=str(Path(self.tmp.name) / 'none.sqlite3'),
                                   sources=SOURCES)

    def test_classification_confirmed_open_insufficient_and_revision(self):
        kb = self._article('base', 'gov', BASE)
        self._evidence('ev-base', kb, 'gov', 'gov-fam', BASE)
        self._claim('cl-conf', kb, 'X', 'capex', BASE, BASE, value_num=100)
        self._link('cl-conf', 'ev-base', BASE)
        self._claim('cl-open', kb, 'Y', 'policy', BASE, BASE)
        self._link('cl-open', 'ev-base', BASE)
        self._claim('cl-insuf', kb, 'Z', 'none', BASE, BASE)
        self._claim('cl-rev', kb, 'R', 'revenue', BASE, BASE, value_num=50)
        self._link('cl-rev', 'ev-base', BASE)
        # new bearing signals inside the window
        km = self._article('newmedia', 'media', NEW)
        self._evidence('ev-media', km, 'media', 'media-fam', NEW)
        self._verification('v1', 'cl-conf', 'verified', 'supported', NEW)
        self._link('cl-conf', 'ev-media', NEW)
        self._link('cl-open', 'ev-media', NEW)          # new evidence, no verification -> open
        kn = self._article('newgov', 'gov', NEW)
        self._claim('cl-rev-new', kn, 'R', 'revenue', NEW, NEW, value_num=80)  # revision -> contradicted
        report = self._build()
        rows = {r['claim_id']: r for r in report['regression']['rows']}
        self.assertEqual(rows['cl-conf']['classification'], 'confirmed')
        self.assertEqual(rows['cl-open']['classification'], 'open')
        self.assertEqual(rows['cl-insuf']['classification'], 'insufficient')
        self.assertEqual(rows['cl-rev']['classification'], 'contradicted')
        counts = report['regression']['counts']
        for key in ('confirmed', 'contradicted', 'open', 'insufficient'):
            self.assertGreaterEqual(counts[key], 1)
        self.assertTrue(rows['cl-conf']['basis'])

    def test_conflict_marks_contradicted(self):
        kb = self._article('base', 'gov', BASE)
        self._claim('cl-a', kb, 'C', 'p', BASE, BASE, value_num=1)
        self._claim('cl-b', kb, 'C', 'p', BASE, BASE, value_num=2)
        self._conflict('f1', 'cl-a', 'cl-b', NEW)
        report = self._build()
        rows = {r['claim_id']: r for r in report['regression']['rows']}
        self.assertEqual(rows['cl-a']['classification'], 'contradicted')

    def test_single_source_verified_is_not_independent_confirmation(self):
        kb = self._article('base', 'gov', BASE)
        self._evidence('ev-base', kb, 'gov', 'gov-fam', BASE)
        self._claim('cl-single', kb, 'S', 'p', BASE, BASE)
        with self.uni.connect() as conn:   # add_claim only accepts unverified at insert
            conn.execute("UPDATE claims SET verification_state='verified' WHERE claim_id='cl-single'")
        self._link('cl-single', 'ev-base', BASE)
        kg = self._article('newgov', 'gov', NEW)
        self._evidence('ev-gov2', kg, 'gov', 'gov-fam', NEW)   # same family, not independent
        self._link('cl-single', 'ev-gov2', NEW)
        report = self._build()
        rows = {r['claim_id']: r for r in report['regression']['rows']}
        self.assertEqual(rows['cl-single']['classification'], 'open')
        self.assertEqual(rows['cl-single']['families'], 1)

    def test_aggregation_by_line_and_angle_with_denominator_and_gaps(self):
        kb = self._article('base', 'gov', BASE)
        self._claim('cl-base', kb, 'B', 'p', BASE, BASE)
        kn = self._article('newgov', 'gov', NEW)
        self._claim('cl-gov', kn, 'G', 'p', NEW, NEW)
        km = self._article('newmedia', 'media', NEW)
        self._claim('cl-media', km, 'M', 'p', NEW, NEW)
        ki = self._article('ir', 'ir', NEW)
        self._claim('cl-ir', ki, 'I', 'p', NEW, NEW)
        report = self._build()
        lines = {r['line']: r for r in report['by_line']}
        self.assertGreaterEqual(lines['policy_regulation']['claims'], 1)
        self.assertGreaterEqual(lines['international_news']['claims'], 1)
        self.assertGreaterEqual(lines['corporate_capital']['claims'], 1)
        angles = {r['angle']: r for r in report['by_angle']}
        for angle in ('官方', '媒体', '市场/资本'):
            self.assertIn(angle, angles)
        self.assertGreaterEqual(report['gaps']['claims_without_evidence'], 1)
        self.assertIn('r1-v1', report['versions'])
        text = period_report.render_text(report)
        self.assertIn('回归核验', text)
        self.assertIn('口径', text)
        self.assertIn('数据不足', text)
        self.assertIn('<svg', period_report.render_html(report))
        self.assertIn('回归核验', period_report.render_html(report))

    def test_yearly_edition_label_window_and_heading(self):
        from datetime import datetime
        kb = self._article('base', 'gov', BASE)
        self._claim('cl-base', kb, 'B', 'p', BASE, BASE)
        report = period_report.build(self.db, 'yearly', end=END,
                                     economic_db=str(Path(self.tmp.name) / 'none.sqlite3'),
                                     sources=SOURCES)
        self.assertEqual(report['label'], '年报')
        start = datetime.fromisoformat(report['window']['start'])
        end = datetime.fromisoformat(report['window']['end'])
        self.assertEqual((end - start).days, 365)
        text = period_report.render_text(report)
        self.assertIn('年度回归核验', text)
        self.assertIn('自然年', text)
        self.assertIn('年度回归核验', period_report.render_html(report))

    def test_monthly_window_is_previous_calendar_month(self):
        from datetime import datetime
        report = self._build()
        start = datetime.fromisoformat(report['window']['start'])
        end = datetime.fromisoformat(report['window']['end'])
        self.assertEqual((start.year, start.month, start.day), (2026, 10, 1))
        self.assertEqual((end.year, end.month, end.day), (2026, 11, 1))
        self.assertIn('自然月', period_report.render_text(report))


if __name__ == '__main__':
    unittest.main()