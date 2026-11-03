import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import audit
from opportunity_radar.store import Store
from opportunity_radar.unified import UnifiedStore


def article(key='k1', source_name='Test News'):
    return SimpleNamespace(article_id=key, title='A test article', url='https://example.org/' + key,
                           published='2026-11-01T00:00:00+00:00', source_name=source_name,
                           summary='body', feed_id='1', fetched_at='', content_source='',
                           retrieval_status='')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, result, check_id):
        return next(item for item in result['checks'] if item['id'] == check_id)

    def test_audit_is_read_only_and_reports_missing_source_id(self):
        self.store.save_article(article('k1'), 'k1')
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            before = conn.execute('PRAGMA user_version').fetchone()[0]
        result = audit.audit(str(self.db))
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            after = conn.execute('PRAGMA user_version').fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(self.check(result, 'source.article_missing_source_id')['count'], 1)
        self.assertIn(result['status'], ('PARTIAL', 'FAIL'))

    def test_audit_flags_published_by_from_source_name(self):
        with self.uni.connect() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO entities(entity_id,entity_type,canonical_name,canonical_key,'
                'cik,ticker,created_at) VALUES(?,?,?,?,?,?,?)',
                ('ent-feed', 'organization', 'Test Feed', 'organization:test feed', '', '', 't'))
            conn.execute(
                'INSERT OR IGNORE INTO entity_relations(relation_id,subject_entity_id,relation_type,'
                'object_kind,object_key,article_key,evidence_id,claim_id,locator_json,method,confidence,'
                'verification_state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('rel-bad', 'ent-feed', 'PUBLISHED_BY', 'article', 'k1', 'k1', '', '',
                 '{"field":"articles.source_name"}', 'source_name', 0.8, 'unverified', 't'))
        result = audit.audit(str(self.db))
        item = self.check(result, 'source.published_by_without_explicit_publisher')
        self.assertEqual((item['severity'], item['count']), ('ERROR', 1))
        self.assertEqual(result['status'], 'FAIL')

    def test_an_incomplete_chain_names_the_missing_layers(self):
        self.store.save_article(article('k1'), 'k1')
        self.uni.assign_article(__import__('opportunity_radar.unified', fromlist=['ArticleRef']).ArticleRef(
            'k1', 'https://example.org/k1', 'A test article', '2026-11-01T00:00:00+00:00'))
        result = audit.audit(str(self.db))
        chain = result['chains'][0]
        self.assertFalse(chain['complete'])
        self.assertIn('evidence', chain['missing'])
        self.assertIn('claim', chain['missing'])
        self.assertIn('entity_mention', chain['missing'])


if __name__ == '__main__':
    unittest.main()
