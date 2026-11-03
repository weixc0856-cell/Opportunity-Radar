import contextlib
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import linking, opportunity, opportunity_audit, opportunity_candidates
from opportunity_radar.opportunity_review import (
    FORMAL_ALLOWLIST, PRODUCTION_DB, ManifestError, apply_manifest, preview_manifest,
    validate_manifest)
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore


class ReviewManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))
        self.reports = Path(self.tmp.name) / 'reports'
        self.article_key = 'k1'
        self.event_id = ''
        self.evidence_id = 'ev-1'
        self.claim_id = 'cl-1'
        self.entity_id = ''

    def tearDown(self):
        self.tmp.cleanup()

    def add_candidate(self, key='k1', title='Acme reconciliation pain',
                      pain='manual invoice reconciliation', buyer='unknown', status='priority'):
        self.store.save_article(SimpleNamespace(
            article_id=key, title=title, url=f'https://example.org/{key}',
            published='2026-11-01T00:00:00+00:00', source_name='Test Source',
            summary=f'{title} teams reconcile invoices manually every month.', feed_id='1',
            fetched_at='', content_source='', retrieval_status=''), key)
        event_id = self.uni.assign_article(ArticleRef(
            key, f'https://example.org/{key}', title,
            '2026-11-01T00:00:00+00:00'))['event_id']
        evidence_id = f'ev-{key}'
        self.uni.add_evidence({
            'evidence_id': evidence_id, 'article_key': key, 'source_id': 'src-a',
            'evidence_kind': 'quote', 'quote': 'Acme teams reconcile invoices manually.',
            'locator_json': '{"field":"summary","start":0,"length":5}',
            'source_family': 'example', 'independence': 'independent_secondary',
            'observed_at': None, 'rules_version': 'r1-v1', 'created_at': 't'})
        claim_id = f'cl-{key}'
        self.uni.add_claim({
            'claim_id': claim_id, 'article_key': key, 'subject': 'Acme',
            'predicate': 'assertion', 'kind': 'fact', 'verification_state': 'unverified',
            'extractor': 'skeleton', 'rules_version': 'r1-v1', 'created_at': 't'})
        linking.seed_entities(self.uni, [{'cik': '0000000001', 'name': 'Acme Inc.',
                                          'ticker': 'ACME'}])
        linking.index_mentions(self.uni, [(key, 'Acme teams reconcile')])
        self.entity_id = linking.entity_id_for('0000000001')
        self.store.save_analysis(key, {
            'schema_version': 5, 'facts': [], 'inferences': [], 'gaps': [], 'actions': [],
            'pain_point': pain,
        }, {
            'score': 50, 'status': status, 'lane': 'B',
            'classification': {'buyer_type': buyer, 'signal_type': 'demand'},
            'evidence_state': 'rss_excerpt_only',
        }, meta={'source_id': 'src-a'})
        self.article_key = key
        self.event_id = event_id
        self.evidence_id = evidence_id
        self.claim_id = claim_id
        return key

    def build_report(self):
        report = opportunity_candidates.build_candidates(self.db)
        paths = opportunity_candidates.write_outputs(report, self.reports, 'json')
        self.report_path = Path(paths['json'])
        self.report_hash = hashlib.sha256(self.report_path.read_bytes()).hexdigest()
        self.report = report
        return report

    def candidate_for(self, key='k1'):
        return next(item for item in self.report['candidates'] if item['article_key'] == key)

    def manifest_candidate(self, candidate, **overrides):
        item = {
            'candidate_id': candidate['candidate_id'],
            'article_key': candidate['article_key'],
            'event_id': candidate['event_id'],
            'review_status': 'accepted_as_seed',
            'promotion_decision': 'create_opportunity',
            'identity': {
                'subject': 'Acme Inc.',
                'problem_statement': 'manual invoice reconciliation',
                'buyer_scope': 'unknown',
                'opportunity_kind': 'demand',
            },
            'review_notes': 'AI-assisted test review; provisional, not human approval.',
            'evidence_refs': [self.evidence_id],
            'entity_refs': [self.entity_id],
            'claim_refs': [{'claim_id': self.claim_id, 'role': 'unverified_claim'}],
        }
        item.update(overrides)
        return item

    def write_manifest(self, candidates, **overrides):
        data = {
            'manifest_version': 1,
            'source_report_hash': self.report_hash,
            'created_at': '2026-11-03T00:00:00+00:00',
            'reviewer': 'Test Reviewer',
            'review_mode': 'human',
            'candidates': candidates,
        }
        data.update(overrides)
        path = Path(self.tmp.name) / 'manifest.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        self.manifest_path = path
        return path

    def one_valid(self, **candidate_overrides):
        self.add_candidate()
        self.build_report()
        candidate = self.candidate_for()
        self.write_manifest([self.manifest_candidate(candidate, **candidate_overrides)])
        return candidate

    def test_cli_b_review_validate_and_apply_guard(self):
        self.one_valid()
        from opportunity_radar import unified_main
        with contextlib.redirect_stdout(io.StringIO()):
            code = unified_main.main([
                'b-review', 'validate', '--manifest', str(self.manifest_path),
                '--db', str(self.db), '--report', str(self.report_path)])
        self.assertEqual(code, 0)
        with contextlib.redirect_stdout(io.StringIO()):
            code = unified_main.main([
                'b-review', 'apply', '--manifest', str(self.manifest_path),
                '--db', str(self.db), '--report', str(self.report_path)])
        self.assertEqual(code, 2)
        with self.uni.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0], 0)

    def test_ai_assisted_create_requires_human_or_test_override(self):
        self.one_valid()
        manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        manifest['review_mode'] = 'ai_assisted'
        self.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        self.assertFalse(result['valid'])
        self.assertIn('human_approval_required', {item['code'] for item in result['errors']})
        manifest['candidates'][0]['promotion_decision'] = 'none'
        self.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        pending = validate_manifest(self.manifest_path, self.db, self.report_path)
        self.assertFalse(pending['valid'])
        self.assertIn('human_approval_required', {item['code'] for item in pending['errors']})
        allowed = validate_manifest(self.manifest_path, self.db, self.report_path,
                                    allow_ai_create=True)
        self.assertTrue(allowed['valid'], allowed['errors'])

    def test_apply_rejects_outside_allowlist_v9(self):
        self.one_valid()
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        with self.assertRaises(ManifestError):
            apply_manifest(self.manifest_path, self.db, self.report_path, apply=True)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_apply_rejects_path_traversal_and_missing(self):
        self.one_valid()
        traversal = str(self.db.parent / '..' / self.db.parent.name / self.db.name)
        with self.assertRaises(ManifestError):
            apply_manifest(self.manifest_path, traversal, self.report_path, apply=True,
                           allowed_paths=(self.db,))
        missing = Path(self.tmp.name) / 'missing.sqlite3'
        with self.assertRaises(ManifestError):
            apply_manifest(self.manifest_path, missing, self.report_path, apply=True,
                           allowed_paths=(missing,))

    def test_apply_rejects_symlink_to_outside(self):
        self.one_valid()
        link = Path(self.tmp.name) / 'outside-link.sqlite3'
        try:
            link.symlink_to(self.db)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks are not available')
        with self.assertRaises(ManifestError):
            apply_manifest(self.manifest_path, link, self.report_path, apply=True)

    def test_apply_symlink_check_is_fail_closed(self):
        # Windows without symlink privilege cannot create the real link. The production
        # path check must still fail closed on a path classified as a symlink.
        self.one_valid()
        with mock.patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaises(ManifestError):
                apply_manifest(self.manifest_path, self.db, self.report_path, apply=True,
                               allowed_paths=(self.db,))

    def test_apply_rejects_production_hardlink(self):
        if not PRODUCTION_DB.exists():
            self.skipTest('production database is absent')
        self.one_valid()
        with tempfile.TemporaryDirectory(dir=str(PRODUCTION_DB.parent)) as folder:
            link = Path(folder) / 'production-hardlink.sqlite3'
            try:
                os.link(PRODUCTION_DB, link)
            except OSError:
                self.skipTest('hardlinks are not available')
            with self.assertRaises(ManifestError):
                apply_manifest(self.manifest_path, link, self.report_path, apply=True)

    def test_formal_allowlist_existing_v9_is_accepted_for_noop_apply(self):
        manifest = Path('reports/opportunity-review-manifest.json')
        report = Path('reports/opportunity-candidates.json')
        if not (FORMAL_ALLOWLIST.exists() and manifest.exists() and report.exists()):
            self.skipTest('formal validation artifacts are absent')
        result = apply_manifest(manifest, FORMAL_ALLOWLIST, report, apply=True,
                                result_dir=self.tmp.name)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['counts']['created'], 0)

    def test_validate_valid_manifest(self):
        self.one_valid()
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['counts']['create_requests'], 1)
        self.assertEqual(result['counts']['would_create'], 1)
        self.assertTrue(result['read_only'])
        self.assertEqual(result['schema_version'], 9)

    def test_manifest_version_source_hash_and_candidate_errors(self):
        self.one_valid()
        bad = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        bad['manifest_version'] = 2
        bad['source_report_hash'] = 'wrong'
        bad['candidates'][0]['candidate_id'] = 'missing'
        self.manifest_path.write_text(json.dumps(bad), encoding='utf-8')
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        self.assertFalse(result['valid'])
        codes = {item['code'] for item in result['errors']}
        self.assertIn('manifest_version_invalid', codes)
        self.assertIn('source_report_hash_mismatch', codes)

    def test_article_event_and_review_field_mismatches(self):
        self.one_valid()
        manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        candidate = manifest['candidates'][0]
        candidate['article_key'] = 'other-article'
        candidate['event_id'] = 'other-event'
        candidate['review_status'] = 'not-a-status'
        candidate['promotion_decision'] = 'auto_create'
        self.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        codes = {item['code'] for item in result['errors']}
        self.assertIn('article_key_mismatch', codes)
        self.assertIn('event_id_mismatch', codes)
        self.assertIn('review_status_invalid', codes)
        self.assertIn('promotion_decision_invalid', codes)

    def test_accepted_without_promotion_is_valid_and_not_created(self):
        self.add_candidate()
        self.build_report()
        candidate = self.candidate_for()
        self.write_manifest([self.manifest_candidate(
            candidate, promotion_decision='none', identity={}, review_notes='')])
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['counts']['accepted_without_promotion'], 1)
        preview = preview_manifest(self.manifest_path, self.db, self.report_path)
        self.assertEqual(preview['preview'][0]['action'], 'not_promoted')

    def test_non_accepted_cannot_request_creation(self):
        self.one_valid(review_status='pending')
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        self.assertFalse(result['valid'])
        self.assertIn('promotion_not_accepted', {item['code'] for item in result['errors']})

    def test_missing_identity_fields_and_allowed_unknown_buyer(self):
        self.one_valid()
        manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        identity = manifest['candidates'][0]['identity']
        identity['subject'] = ''
        identity['problem_statement'] = ''
        identity['opportunity_kind'] = ''
        identity['buyer_scope'] = 'unknown'
        self.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        codes = {item['code'] for item in result['errors']}
        self.assertIn('identity_field_missing', codes)
        self.assertGreaterEqual(sum(1 for item in result['errors']
                                    if item['code'] == 'identity_field_missing'), 3)

    def test_missing_evidence_entity_and_unverified_claim_fact_basis(self):
        self.one_valid(evidence_refs=['missing-evidence'], entity_refs=['missing-entity'])
        manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        manifest['candidates'][0]['claim_refs'] = [
            {'claim_id': self.claim_id, 'role': 'fact_basis'}]
        self.manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        codes = {item['code'] for item in result['errors']}
        self.assertIn('evidence_not_found', codes)
        self.assertIn('entity_not_found', codes)
        self.assertIn('claim_fact_basis_unverified', codes)

    def test_preview_does_not_write(self):
        self.one_valid()
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = preview_manifest(self.manifest_path, self.db, self.report_path)
        after = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(result['counts']['preview_create'], 1)
        with self.uni.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0], 0)

    def test_apply_requires_apply_flag_production_path_and_v5(self):
        self.one_valid()
        with self.assertRaises(ManifestError):
            apply_manifest(self.manifest_path, self.db, self.report_path, apply=False)
        production = Path('data/opportunity_radar.sqlite3')
        if production.exists():
            before = hashlib.sha256(production.read_bytes()).hexdigest()
            with self.assertRaises(ManifestError):
                apply_manifest(self.manifest_path, production, self.report_path, apply=True)
            self.assertEqual(before, hashlib.sha256(production.read_bytes()).hexdigest())
        v5 = Path(self.tmp.name) / 'v5.sqlite3'
        conn = sqlite3.connect(v5)
        conn.execute('PRAGMA user_version=5')
        conn.commit()
        conn.close()
        with self.assertRaises(ManifestError):
            apply_manifest(self.manifest_path, v5, self.report_path, apply=True,
                           allowed_paths=(v5,))

    def test_v9_apply_creates_one_signal_detected_opportunity_and_audit_passes(self):
        candidate = self.one_valid()
        result = apply_manifest(self.manifest_path, self.db, self.report_path, apply=True,
                                result_dir=self.tmp.name, allowed_paths=(self.db,))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['counts']['created'], 1)
        self.assertEqual(len(result['created']), 1)
        created = result['created'][0]
        stored = opportunity.get_opportunity(self.uni, created['opportunity_id'])
        self.assertEqual(stored['stage'], 'active')
        self.assertEqual(stored['validation_state'], 'signal_detected')
        history = opportunity.history(self.uni, created['opportunity_id'])
        self.assertEqual(len(history['revisions']), 1)
        self.assertEqual(history['revisions'][0]['validation_state'], 'signal_detected')
        roles = {(link['target_kind'], link['role']) for link in history['links']}
        self.assertIn(('article', 'seed_signal'), roles)
        self.assertIn(('evidence', 'fact_basis'), roles)
        self.assertIn(('entity', 'subject'), roles)
        self.assertIn(('claim', 'unverified_claim'), roles)
        self.assertTrue((Path(self.tmp.name) / 'opportunity-review-result.json').exists())
        with self.uni.connect() as conn:
            checks, _ = opportunity_audit.check(conn)
        self.assertFalse([check for check in checks
                          if check['severity'] == 'ERROR' and check['count']])
        self.assertEqual(candidate['seed_class'], 'EVIDENCE_BACKED_SEED')

    def test_repeated_apply_is_idempotent_and_does_not_overwrite_history(self):
        self.one_valid()
        first = apply_manifest(self.manifest_path, self.db, self.report_path, apply=True,
                               result_dir=self.tmp.name, allowed_paths=(self.db,))
        second = apply_manifest(self.manifest_path, self.db, self.report_path, apply=True,
                                result_dir=self.tmp.name, allowed_paths=(self.db,))
        self.assertEqual(first['counts']['created'], 1)
        self.assertEqual(second['counts']['created'], 0)
        self.assertEqual(second['counts']['idempotent'], 1)
        oid = first['created'][0]['opportunity_id']
        history = opportunity.history(self.uni, oid)
        self.assertEqual(len(history['revisions']), 1)

    def test_canonical_conflict_is_not_merged(self):
        self.one_valid()
        existing = opportunity.create_opportunity(
            self.uni, subject='Acme Inc.', problem_statement='manual invoice reconciliation',
            buyer_scope='unknown', opportunity_kind='demand', title='existing',
            validation_state='signal_detected', actor='existing')
        oid = existing['opportunity_id']
        result = apply_manifest(self.manifest_path, self.db, self.report_path, apply=True,
                                result_dir=self.tmp.name, allowed_paths=(self.db,))
        self.assertFalse(result['valid'])
        self.assertEqual(result['counts']['created'], 0)
        self.assertIn('canonical_key_conflict', {item['code'] for item in result['errors']})
        history = opportunity.history(self.uni, oid)
        self.assertEqual(len(history['revisions']), 1)

    def test_transaction_rolls_back_opportunity_when_a_link_fails(self):
        self.add_candidate()
        self.build_report()
        candidate = self.candidate_for()
        links = [
            {'target_kind': 'article', 'target_key': candidate['article_key'],
             'role': 'seed_signal', 'support': 'context', 'locator': {'field': 'article'}},
            {'target_kind': 'evidence', 'target_key': 'missing-evidence',
             'role': 'fact_basis', 'support': 'direct', 'locator': {}},
        ]
        with self.assertRaises(opportunity.OpportunityError):
            opportunity.create_opportunity_with_links(
                self.uni, subject='Rollback Subject',
                problem_statement='rollback problem', buyer_scope='unknown',
                opportunity_kind='demand', links=links)
        self.assertIsNone(opportunity.get_by_canonical_key(
            self.uni, opportunity.canonical_key_for('Rollback Subject', 'rollback problem',
                                                    'unknown', 'demand')))
        with self.uni.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM opportunity_links').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM opportunity_revisions').fetchone()[0], 0)

    def test_duplicate_application_is_rejected(self):
        self.add_candidate('k1', title='Acme reconciliation pain')
        self.add_candidate('k2', title='Acme reconciliation pain two')
        self.build_report()
        one = self.manifest_candidate(self.candidate_for('k1'))
        two = self.manifest_candidate(self.candidate_for('k2'))
        self.write_manifest([one, two])
        result = validate_manifest(self.manifest_path, self.db, self.report_path)
        self.assertFalse(result['valid'])
        self.assertIn('duplicate_application', {item['code'] for item in result['errors']})

    def test_apply_rejects_manifest_validation_errors_without_writes(self):
        self.one_valid(identity={
            'subject': '', 'problem_statement': '', 'buyer_scope': 'unknown',
            'opportunity_kind': ''})
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = apply_manifest(self.manifest_path, self.db, self.report_path, apply=True,
                                result_dir=self.tmp.name, allowed_paths=(self.db,))
        self.assertFalse(result['valid'])
        self.assertFalse(result['applied'])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
