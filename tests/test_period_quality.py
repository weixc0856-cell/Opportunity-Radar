"""R4 period reports and R6 quality metrics over a small stored graph."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import period_report, quality
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore


class PeriodAndQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'db.sqlite3')
        self.store = Store(self.db)
        self.uni = UnifiedStore(self.db)
        self.article = SimpleNamespace(
            article_id='a1', title='Acme invoice reconciliation',
            url='https://example.org/a1', summary='Acme reconciles invoices manually.',
            published='2026-11-01T00:00:00+00:00', source_name='Example', feed_id='1',
            fetched_at='', content_source='', retrieval_status='')
        self.key = Store.key(self.article.url)
        self.store.save_article(self.article, self.key, source_id='src-a')
        self.event_id = self.uni.assign_article(ArticleRef(
            self.key, self.article.url, self.article.title, self.article.published))['event_id']
        self.uni.add_evidence({
            'evidence_id': 'ev-1', 'article_key': self.key, 'source_id': 'src-a',
            'evidence_kind': 'quote', 'quote': 'Acme reconciles invoices manually.',
            'locator_json': '{"field":"summary","start":0,"length":5}',
            'source_family': 'example', 'independence': 'independent_secondary',
            'observed_at': None, 'rules_version': 'r1-v1', 'created_at': 't'})
        self.uni.add_claim({
            'claim_id': 'cl-1', 'article_key': self.key, 'event_id': self.event_id,
            'fact_ordinal': 1, 'subject': 'Acme', 'predicate': 'assertion',
            'value_num': None, 'value_text': 'Acme reconciles invoices manually.',
            'unit': '', 'unit_raw': '', 'scale': '', 'currency': '', 'region': '',
            'period': '', 'period_raw': '', 'comparison': '', 'denominator': '',
            'seasonality': '', 'revision': '', 'revision_raw': '', 'kind': 'fact',
            'quote': 'Acme reconciles invoices manually.',
            'locator_json': '{"field":"summary","start":0,"length":5}',
            'verification_state': 'unverified', 'extractor': 'skeleton',
            'rules_version': 'r1-v1', 'created_at': 't'})
        with self.uni.connect() as conn:
            conn.execute("INSERT INTO claim_evidence VALUES('cl-1','ev-1','direct','unknown','{}','t')")

    def tearDown(self):
        self.tmp.cleanup()

    def test_weekly_report_uses_article_time_and_counts_events(self):
        report = period_report.build(self.db, 'weekly', end='2026-11-02T00:00:00+00:00',
                                      economic_db=str(Path(self.tmp.name) / 'none.sqlite3'))
        self.assertEqual(report['period'], 'weekly')
        self.assertEqual(report['event_count'], 1)
        self.assertEqual(report['claim_count'], 1)
        self.assertEqual(report['claim_states'], {'unverified': 1})
        text = period_report.render_text(report)
        self.assertIn('周报', text)
        self.assertIn('acme invoice reconciliation', text)
        self.assertIn('event_clustering_precision_recall', text)
        self.assertIn('<svg', period_report.render_html(report))

    def test_quality_metrics_are_measured_and_label_unknowns(self):
        metrics = quality.metrics(self.db)
        self.assertEqual(metrics['status'], 'PASS_MEASURED')
        self.assertEqual(metrics['claims']['total'], 1)
        self.assertEqual(metrics['events']['evidence_coverage_pct'], 100.0)
        self.assertEqual(metrics['events']['clustering']['status'], 'NOT_MEASURED')
        self.assertEqual(metrics['runs']['gate_escape_count'], 0)
        self.assertIn('versions', metrics)
        backtest = quality.backtest(self.db, days=30)
        self.assertEqual(backtest['runs'], 0)


if __name__ == '__main__':
    unittest.main()
