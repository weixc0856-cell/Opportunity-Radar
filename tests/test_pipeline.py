"""The unified post-analysis pipeline: N5 promotion, opportunity discovery, and the
single production chain that the daily run now executes."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from opportunity_radar import opportunity_discovery, pipeline
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'db.sqlite3')
        self.store = Store(self.db)
        self.uni = UnifiedStore(self.db)
        self.article = SimpleNamespace(
            article_id='https://example.org/a', title='Acme reconciles invoices',
            url='https://example.org/a',
            summary='Acme teams reconcile invoices manually every month.',
            published='2026-11-01T00:00:00+00:00', source_name='Example',
            feed_id='1', fetched_at='', content_source='', retrieval_status='')
        self.key = Store.key(self.article.url)
        self.store.save_article(self.article, self.key, source_id='src-a')
        self.event_id = self.uni.assign_article(ArticleRef(
            self.key, self.article.url, self.article.title, self.article.published))['event_id']

    def tearDown(self):
        self.tmp.cleanup()

    def n5_payload(self):
        quote = 'Acme teams reconcile invoices manually every month.'
        return {
            'status': 'success',
            'claims': [{
                'claim_id': 'n5-claim-1', 'subject': 'Acme', 'predicate': 'invoice volume',
                'value_num': 12.5, 'value_text': quote, 'unit': 'USD',
                'unit_raw': 'USD billion', 'scale': 'billion', 'currency': 'USD',
                'region': '', 'period': '2026-10',
                'period_raw': 'October 2026', 'comparison': 'month_over_month',
                'denominator': '', 'seasonality': 'unknown', 'revision': 'unknown',
                'revision_raw': 'unknown', 'kind': 'fact', 'quote': quote,
                'trace': {'evidence_field': 'summary', 'evidence_start': 0,
                          'evidence_end': len(quote)},
            }],
        }

    def test_promote_n5_writes_claim_evidence_and_link(self):
        document = {'document_id': 'doc-1', 'content_hash': 'hash'}
        result = pipeline._promote(self.db, self.article, self.key, document,
                                   self.n5_payload(), 'src-a', self.event_id)
        self.assertEqual(result['claims'], 1)
        self.assertEqual(result['evidences'], 1)
        self.assertEqual(result['links'], 1)
        with self.uni.connect() as conn:
            claim = conn.execute("SELECT * FROM claims WHERE extractor='n5'").fetchone()
            evidence = conn.execute('SELECT * FROM evidences').fetchone()
            link = conn.execute('SELECT * FROM claim_evidence').fetchone()
        self.assertEqual(claim['value_num'], 12.5)
        self.assertEqual(claim['unit'], 'USD')
        self.assertEqual(claim['unit_raw'], 'USD billion')
        self.assertEqual(claim['scale'], 'billion')
        self.assertEqual(claim['period'], '2026-10')
        self.assertEqual(claim['verification_state'], 'unverified')
        self.assertIn('document_id', json.loads(claim['locator_json']))
        self.assertEqual(evidence['source_id'], 'src-a')
        self.assertEqual(link['claim_id'], claim['claim_id'])
        # Running the promotion again is idempotent.
        again = pipeline._promote(self.db, self.article, self.key, document,
                                  self.n5_payload(), 'src-a', self.event_id)
        self.assertEqual(again['claims'], 0)
        with self.uni.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0], 1)

    def test_discover_creates_signal_detected_with_links(self):
        self.store.save_analysis(self.key, {
            'schema_version': 5, 'facts': [], 'inferences': [], 'gaps': [], 'actions': [],
            'pain_point': 'manual invoice reconciliation',
            'target_customer': 'small accounting teams',
        }, {
            'score': 60, 'status': 'watch', 'lane': 'B',
            'classification': {'buyer_type': 'small_business', 'signal_type': 'demand'},
            'evidence_state': 'rss_excerpt_only',
        }, meta={'source_id': 'src-a'})
        self.uni.add_evidence({
            'evidence_id': 'ev-1', 'article_key': self.key, 'source_id': 'src-a',
            'evidence_kind': 'quote', 'quote': 'Acme teams reconcile invoices manually.',
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
        result = opportunity_discovery.discover(self.db)
        self.assertEqual(result['created'], 1)
        with self.uni.connect() as conn:
            row = conn.execute('SELECT * FROM opportunities').fetchone()
            links = conn.execute('SELECT * FROM opportunity_links').fetchall()
            revision = conn.execute('SELECT * FROM opportunity_revisions').fetchone()
        self.assertEqual(row['validation_state'], 'signal_detected')
        self.assertEqual(row['confidence'], opportunity_discovery.AUTO_CONFIDENCE)
        self.assertGreaterEqual(len(links), 3)
        self.assertEqual(revision['validation_state'], 'signal_detected')

    def test_pipeline_can_be_disabled_for_isolated_unit_runs(self):
        with mock.patch.dict(os.environ, {'OR_PIPELINE_ENABLED': '0'}):
            result = pipeline.run_after_analysis(self.db, [], set(), None)
        self.assertEqual(result['status'], 'disabled')
        self.assertEqual(result['blocking_failures'], [])


if __name__ == '__main__':
    unittest.main()
