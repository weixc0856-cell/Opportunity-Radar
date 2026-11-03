import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import linking, opportunity
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))
        self.article_key = 'k1'
        self.store.save_article(SimpleNamespace(
            article_id='k1', title='Acme reconciliation pain', url='https://example.org/k1',
            published='2026-11-01T00:00:00+00:00', source_name='Test Source',
            summary='Acme teams reconcile invoices manually every month.', feed_id='1',
            fetched_at='', content_source='', retrieval_status=''), self.article_key)
        self.event_id = self.uni.assign_article(ArticleRef(
            self.article_key, 'https://example.org/k1', 'Acme reconciliation pain',
            '2026-11-01T00:00:00+00:00'))['event_id']
        self.evidence_id = 'ev-opportunity-1'
        self.uni.add_evidence({
            'evidence_id': self.evidence_id, 'article_key': self.article_key,
            'source_id': 'bbc-business', 'evidence_kind': 'quote',
            'quote': 'Acme teams reconcile invoices manually every month.',
            'locator_json': '{"field":"summary","start":0,"length":49}',
            'source_family': 'bbc', 'independence': 'independent_secondary',
            'observed_at': None, 'rules_version': 'r1-v1', 'created_at': 't'})
        linking.seed_entities(self.uni, [{'cik': '0000000001', 'name': 'Acme Inc.', 'ticker': 'ACME'}])
        self.entity_id = linking.entity_id_for('0000000001')
        self.claim_id = 'cl-opportunity-1'
        self.uni.add_claim({
            'claim_id': self.claim_id, 'article_key': self.article_key, 'subject': 'Acme',
            'predicate': 'assertion', 'kind': 'fact', 'verification_state': 'unverified',
            'extractor': 'skeleton', 'rules_version': 'r1-v1', 'created_at': 't'})

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **kw):
        defaults = dict(subject='Acme', problem_statement='manual invoice reconciliation',
                        buyer_scope='smb', opportunity_kind='demand', title='Acme reconciliation',
                        stage='active', validation_state='signal_detected', confidence=0.2)
        defaults.update(kw)
        return opportunity.create_opportunity(self.uni, **defaults)

    def add(self, oid, kind, key, role, support='context', locator=None, method='manual',
            confidence=0.5):
        return opportunity.add_link(self.uni, oid, kind, key, role, support,
                                    locator or {'field': 'test', 'start': 0, 'length': 1},
                                    method, confidence)

    def lid(self, oid, kind, key, role):
        return opportunity.link_id_for(oid, kind, key, role)

    def append(self, oid, state, **kw):
        return opportunity.append_revision(self.uni, oid, stage=kw.pop('stage', 'active'),
                                            validation_state=state, **kw)

    def test_canonical_key_is_stable_and_requires_subject_and_problem(self):
        key = opportunity.canonical_key_for(' Acme ', 'Manual invoice reconciliation', 'SMB', 'Demand')
        self.assertEqual(key, opportunity.canonical_key_for('acme', 'manual invoice reconciliation',
                                                            'smb', 'demand'))
        self.assertEqual(opportunity.opportunity_id_for(key),
                         opportunity.opportunity_id_for(key))
        with self.assertRaises(opportunity.OpportunityError):
            opportunity.canonical_key_for('', 'problem', 'smb', 'demand')
        with self.assertRaises(opportunity.OpportunityError):
            opportunity.canonical_key_for('Acme', '', 'smb', 'demand')

    def test_create_is_idempotent_and_has_an_initial_revision(self):
        first = self.create()
        second = self.create(title='different title')
        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        self.assertEqual(first['opportunity_id'], second['opportunity_id'])
        self.assertTrue(first['current_revision_id'])
        stored = opportunity.get_opportunity(self.uni, first['opportunity_id'])
        self.assertEqual(stored['canonical_key'],
                         opportunity.canonical_key_for('Acme', 'manual invoice reconciliation',
                                                       'smb', 'demand'))
        self.assertEqual(opportunity.current_projection_problems(self.uni,
                                                                 first['opportunity_id']), [])
        with self.uni.connect() as conn:
            revision = conn.execute('SELECT * FROM opportunity_revisions WHERE revision_id=?',
                                    (first['current_revision_id'],)).fetchone()
        self.assertEqual(revision['stage'], 'active')
        self.assertEqual(revision['validation_state'], 'signal_detected')

    def test_link_idempotence_and_target_validation(self):
        oid = self.create()['opportunity_id']
        self.assertTrue(self.add(oid, 'article', self.article_key, 'seed_signal'))
        self.assertFalse(self.add(oid, 'article', self.article_key, 'seed_signal'))
        with self.assertRaises(opportunity.OpportunityError):
            self.add(oid, 'article', 'missing', 'seed_signal')
        with self.assertRaises(opportunity.OpportunityError):
            self.add(oid, 'article', self.article_key, 'buyer')
        with self.assertRaises(opportunity.OpportunityError):
            opportunity.add_link(self.uni, oid, 'article', self.article_key, 'seed_signal',
                                 locator='not json')

    def test_claim_fact_basis_requires_verified_claim(self):
        oid = self.create()['opportunity_id']
        with self.assertRaises(opportunity.OpportunityError):
            self.add(oid, 'claim', self.claim_id, 'fact_basis')
        self.assertTrue(self.add(oid, 'claim', self.claim_id, 'unverified_claim'))
        with self.uni.connect() as conn:
            conn.execute("UPDATE claims SET verification_state='verified' WHERE claim_id=?",
                         (self.claim_id,))
        self.assertTrue(self.add(oid, 'claim', self.claim_id, 'fact_basis'))

    def test_hypothesis_supersedes_and_history_is_append_only(self):
        oid = self.create()['opportunity_id']
        first = opportunity.create_hypothesis(self.uni, oid, 'need',
                                              'SM teams need reconciliation',
                                              'basis-1', 0.4)
        second = opportunity.create_hypothesis(self.uni, oid, 'need',
                                               'SM teams need reconciliation with approval',
                                               'basis-2', 0.5, supersedes=first)
        self.assertNotEqual(first, second)
        self.assertEqual(opportunity.create_hypothesis(self.uni, oid, 'need',
                                                       'SM teams need reconciliation',
                                                       'basis-1', 0.4), first)
        other = self.create(subject='Other', problem_statement='different problem')['opportunity_id']
        with self.assertRaises(opportunity.OpportunityError):
            opportunity.create_hypothesis(self.uni, other, 'need', 'x', 'basis-3',
                                          supersedes=first)
        with self.uni.connect() as conn:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE opportunity_hypotheses SET statement='changed' WHERE hypothesis_id=?",
                             (first,))

    def test_revision_state_gates_and_link_ownership(self):
        oid = self.create()['opportunity_id']
        with self.assertRaises(opportunity.OpportunityError):
            self.append(oid, 'problem_supported')
        with self.uni.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM opportunity_revisions').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT validation_state FROM opportunities WHERE opportunity_id=?',
                                          (oid,)).fetchone()[0], 'signal_detected')
        self.assertTrue(self.add(oid, 'evidence', self.evidence_id, 'fact_basis', 'direct'))
        fact_link = self.lid(oid, 'evidence', self.evidence_id, 'fact_basis')
        created = self.append(oid, 'problem_supported', link_ids=[fact_link])
        self.assertTrue(created['created'])
        self.assertTrue(self.add(oid, 'entity', self.entity_id, 'buyer', 'context'))
        buyer_link = self.lid(oid, 'entity', self.entity_id, 'buyer')
        self.append(oid, 'buyer_identified', link_ids=[fact_link, buyer_link])
        self.assertTrue(self.add(oid, 'evidence', self.evidence_id, 'payment_evidence', 'direct'))
        payment_link = self.lid(oid, 'evidence', self.evidence_id, 'payment_evidence')
        self.append(oid, 'payment_verified', link_ids=[fact_link, buyer_link, payment_link])
        self.append(oid, 'opportunity_candidate',
                    link_ids=[fact_link, buyer_link, payment_link])
        current = opportunity.get_opportunity(self.uni, oid)
        self.assertEqual(current['validation_state'], 'opportunity_candidate')
        self.assertEqual(opportunity.current_projection_problems(self.uni, oid), [])

        other = self.create(subject='Other', problem_statement='other problem')['opportunity_id']
        other_link = self.lid(other, 'evidence', self.evidence_id, 'fact_basis')
        self.add(other, 'evidence', self.evidence_id, 'fact_basis', 'direct')
        with self.assertRaises(opportunity.OpportunityError):
            self.append(oid, 'signal_detected', link_ids=[other_link])

    def test_revision_idempotence_and_immutability(self):
        oid = self.create()['opportunity_id']
        self.add(oid, 'evidence', self.evidence_id, 'fact_basis', 'direct')
        link_id = self.lid(oid, 'evidence', self.evidence_id, 'fact_basis')
        first = self.append(oid, 'problem_supported', link_ids=[link_id])
        second = self.append(oid, 'problem_supported', link_ids=[link_id])
        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        with self.uni.connect() as conn:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE opportunity_revisions SET note='changed' WHERE revision_id=?",
                             (first['revision_id'],))
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM opportunity_revisions WHERE revision_id=?",
                             (first['revision_id'],))

    def test_projection_mismatch_is_detected(self):
        oid = self.create()['opportunity_id']
        with self.uni.connect() as conn:
            conn.execute("UPDATE opportunities SET stage='monitoring' WHERE opportunity_id=?", (oid,))
        self.assertIn('current projection does not match current revision',
                      opportunity.current_projection_problems(self.uni, oid))

    def test_declared_lineage_is_not_counted_as_verified_independence(self):
        oid = self.create()['opportunity_id']
        self.add(oid, 'evidence', self.evidence_id, 'fact_basis', 'direct')
        result = opportunity.independence(self.uni, oid)
        self.assertEqual(result['independent_source_units'], 0)
        self.assertGreaterEqual(result['declared_only_evidence_count'], 1)

    def test_audit_flags_missing_target_and_projection_mismatch(self):
        from opportunity_radar import opportunity_audit
        oid = self.create()['opportunity_id']
        with self.uni.connect() as conn:
            conn.execute(
                'INSERT INTO opportunity_links(link_id,opportunity_id,target_kind,target_key,'
                'role,support,locator_json,method,confidence,observed_at,created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                ('lnk-bad', oid, 'article', 'missing', 'seed_signal', 'context', '{}',
                 'manual', 0.0, None, 't'))
            conn.execute("UPDATE opportunities SET stage='monitoring' WHERE opportunity_id=?", (oid,))
            checks, info = opportunity_audit.check(conn)
        by_id = {item['id']: item for item in checks}
        self.assertEqual(by_id['opportunity.link_target_missing']['count'], 1)
        self.assertEqual(by_id['opportunity.projection_inconsistent']['count'], 1)

    def test_empty_opportunity_audit_passes_and_reports_zero(self):
        from opportunity_radar import opportunity_audit
        with self.uni.connect() as conn:
            checks, info = opportunity_audit.check(conn)
        self.assertTrue(info['tables_present'])
        self.assertEqual(info['opportunities'], 0)
        self.assertFalse([check for check in checks if check['severity'] == 'ERROR' and check['count']])


if __name__ == '__main__':
    unittest.main()
