import contextlib
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import linking
from opportunity_radar.opportunity_candidates import build_candidates, write_outputs
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore


class OpportunityCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def tearDown(self):
        self.tmp.cleanup()

    def article(self, key, title='Acme reconciliation pain'):
        self.store.save_article(SimpleNamespace(
            article_id=key, title=title, url=f'https://example.org/{key}',
            published='2026-11-01T00:00:00+00:00', source_name='Test Source',
            summary=f'{title} teams reconcile invoices manually every month.', feed_id='1',
            fetched_at='', content_source='', retrieval_status=''), key)
        return key

    def event(self, key, title='Acme reconciliation pain'):
        return self.uni.assign_article(ArticleRef(
            key, f'https://example.org/{key}', title, '2026-11-01T00:00:00+00:00'))['event_id']

    def add_b(self, key, status='watch', pain='manual invoice reconciliation',
              buyer='smb', signal='demand', source_id='src-a'):
        self.store.save_analysis(key, {
            'schema_version': 5, 'facts': [], 'inferences': [], 'gaps': [], 'actions': [],
            'pain_point': pain,
        }, {
            'score': 50, 'status': status, 'lane': 'B',
            'classification': {'buyer_type': buyer, 'signal_type': signal},
            'evidence_state': 'rss_excerpt_only',
        }, meta={'source_id': source_id})

    def add_evidence(self, key, evidence_id='ev-1', source_id='src-a',
                     locator='{"field":"summary","start":0,"length":5}'):
        self.uni.add_evidence({
            'evidence_id': evidence_id, 'article_key': key, 'source_id': source_id,
            'evidence_kind': 'quote', 'quote': 'Acme teams reconcile invoices manually.',
            'locator_json': locator, 'source_family': 'example',
            'independence': 'independent_secondary', 'observed_at': None,
            'rules_version': 'r1-v1', 'created_at': 't'})

    def add_claim(self, key, claim_id='cl-1'):
        self.uni.add_claim({
            'claim_id': claim_id, 'article_key': key, 'subject': 'Acme',
            'predicate': 'assertion', 'kind': 'fact', 'verification_state': 'unverified',
            'extractor': 'skeleton', 'rules_version': 'r1-v1', 'created_at': 't'})

    def test_evidence_backed_signal_only_and_mapping_classes(self):
        backed = self.article('k-backed')
        self.event(backed)
        self.add_evidence(backed)
        self.add_claim(backed)
        self.add_b(backed, 'priority')

        signal_only = self.article('k-signal', title='Beta scheduling pain')
        self.event(signal_only, title='Beta scheduling pain')
        self.add_b(signal_only, 'watch')

        invalid = self.article('k-invalid', title='Gamma billing pain')
        self.event(invalid, title='Gamma billing pain')
        self.add_evidence(invalid, evidence_id='ev-bad')
        with self.uni.connect() as conn:
            conn.execute("UPDATE evidences SET locator_json='not-json' WHERE evidence_id='ev-bad'")
        self.add_b(invalid, 'filtered')

        no_event = self.article('k-no-event', title='Delta reporting pain')
        self.add_b(no_event, 'filtered')

        no_claim = self.article('k-no-claim', title='Epsilon expense pain')
        self.event(no_claim, title='Epsilon expense pain')
        self.add_evidence(no_claim, evidence_id='ev-no-claim')
        self.add_b(no_claim, 'filtered')

        report = build_candidates(self.db)
        by_key = {item['article_key']: item for item in report['candidates']}
        self.assertEqual(by_key[backed]['seed_class'], 'EVIDENCE_BACKED_SEED')
        self.assertEqual(by_key[signal_only]['seed_class'], 'SIGNAL_ONLY_SEED')
        self.assertEqual(by_key[invalid]['seed_class'], 'INSUFFICIENT_MAPPING')
        self.assertIn('evidence_present_but_invalid', by_key[invalid]['cannot_form_reason'])
        self.assertEqual(by_key[no_event]['seed_class'], 'INSUFFICIENT_MAPPING')
        self.assertIn('event_or_profile_missing', by_key[no_event]['cannot_form_reason'])
        self.assertEqual(by_key[no_claim]['seed_class'], 'INSUFFICIENT_MAPPING')
        self.assertIn('claim_missing', by_key[no_claim]['cannot_form_reason'])
        self.assertEqual(report['stats']['b_candidates'], 5)
        self.assertEqual(report['stats']['evidence_backed'], 1)
        self.assertEqual(report['stats']['signal_only'], 1)
        self.assertEqual(report['stats']['insufficient_mapping'], 3)
        self.assertEqual(by_key[backed]['daily_display'], 'status_eligible')
        self.assertEqual(by_key[signal_only]['daily_display'], 'status_eligible')
        self.assertEqual(by_key[invalid]['daily_display'], 'not_shown_by_status')
        self.assertEqual(by_key[backed]['review_status'], 'pending')
        self.assertEqual(by_key[backed]['evidence_refs'][0]['evidence_id'], 'ev-1')
        self.assertEqual(by_key[backed]['claim_refs'][0]['verification_state'], 'unverified')

    def test_identity_is_conservative_and_duplicate_clusters_are_suggestions_only(self):
        for key in ('k-a', 'k-b'):
            self.article(key, title=f'{key} reconciliation pain')
            self.event(key, title=f'{key} reconciliation pain')
            self.add_evidence(key, evidence_id=f'ev-{key}')
            self.add_b(key)
        linking.seed_entities(self.uni, [{'cik': '0000000001', 'name': 'Acme Inc.',
                                          'ticker': 'ACME'}])
        linking.index_mentions(self.uni, [('k-a', 'Acme teams reconcile'),
                                           ('k-b', 'Acme teams reconcile')])
        report = build_candidates(self.db)
        self.assertEqual(len(report['candidates']), 2)
        identity = [item['identity'] for item in report['candidates']]
        self.assertEqual({item['subject'] for item in identity}, {'Acme Inc.'})
        self.assertTrue(all(item['problem'] == '' for item in identity))
        self.assertTrue(all(item['canonical_key_candidate'] == '' for item in identity))
        self.assertTrue(all(item['canonical_key_status'] == 'blocked_missing_confirmed_problem'
                            for item in identity))
        clusters = [item['duplicate_cluster_candidate'] for item in report['candidates']]
        self.assertEqual(clusters[0], clusters[1])
        self.assertTrue(clusters[0])
        self.assertEqual(report['stats']['duplicate_clusters'], 1)
        self.assertEqual(sum(1 for item in report['candidates']
                             if 'duplicate_suspected' in item['review_flags']), 2)
        self.assertEqual(report['stats']['identity_complete'], 0)
        self.assertTrue(all('missing_confirmed_problem' in item['identity_missing']
                            for item in identity))
        self.assertEqual(report['stats']['canonical_key_candidates'], 0)

    def test_missing_buyer_is_not_fabricated(self):
        key = self.article('k-buyer')
        self.event(key)
        self.add_b(key, buyer='unknown')
        report = build_candidates(self.db)
        item = report['candidates'][0]
        self.assertEqual(item['identity']['buyer_scope'], '')
        self.assertEqual(item['identity']['buyer_scope_hint'], '')
        self.assertIn('missing_buyer', item['identity']['identity_missing'])

    def test_build_is_read_only_and_creates_no_opportunity(self):
        key = self.article('k-readonly')
        self.event(key)
        self.add_evidence(key)
        self.add_b(key)
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        first = build_candidates(self.db)
        after = hashlib.sha256(self.db.read_bytes()).hexdigest()
        second = build_candidates(self.db)
        self.assertEqual(before, after)
        self.assertEqual(first, second)
        self.assertTrue(first['read_only'])
        self.assertEqual(first['opportunity_rows'], 0)
        with self.uni.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0], 0)
        with self.assertRaises(sqlite3.OperationalError):
            conn = sqlite3.connect(self.db.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                conn.execute('DELETE FROM opportunities')
            finally:
                conn.close()

    def test_write_outputs_json_and_markdown(self):
        key = self.article('k-output')
        self.event(key)
        self.add_evidence(key)
        self.add_claim(key)
        self.add_b(key)
        report = build_candidates(self.db)
        out = Path(self.tmp.name) / 'reports'
        paths = write_outputs(report, out, 'both')
        self.assertTrue(Path(paths['json']).exists())
        self.assertTrue(Path(paths['markdown']).exists())
        parsed = json.loads(Path(paths['json']).read_text(encoding='utf-8'))
        self.assertEqual(parsed['stats']['b_candidates'], 1)
        markdown = Path(paths['markdown']).read_text(encoding='utf-8')
        self.assertIn('EVIDENCE_BACKED_SEED', markdown)
        self.assertEqual(parsed['review_statuses'],
                         ['pending', 'accepted_as_seed', 'rejected', 'needs_more_evidence',
                          'duplicate_suspected'])

    def test_cli_writes_reports_without_writing_db(self):
        key = self.article('k-cli')
        self.event(key)
        self.add_evidence(key)
        self.add_claim(key)
        self.add_b(key)
        out = Path(self.tmp.name) / 'cli-reports'
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        from opportunity_radar import unified_main
        with contextlib.redirect_stdout(io.StringIO()):
            code = unified_main.main(['b-candidates', '--db', str(self.db),
                                      '--output-dir', str(out), '--format', 'json',
                                      '--json'])
        self.assertEqual(code, 0)
        self.assertTrue((out / 'opportunity-candidates.json').exists())
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_review_statuses_are_exposed_without_auto_acceptance(self):
        key = self.article('k-review')
        self.event(key)
        self.add_b(key)
        report = build_candidates(self.db)
        self.assertEqual(report['candidates'][0]['review_status'], 'pending')
        self.assertNotIn('accepted_as_seed',
                         [item['review_status'] for item in report['candidates']])


if __name__ == '__main__':
    unittest.main()
