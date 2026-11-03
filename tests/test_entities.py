import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import linking
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore


def article_obj(key, title, source_name='Test News', published='2026-11-01T00:00:00+00:00'):
    return SimpleNamespace(article_id=key, title=title, url='https://example.org/' + key,
                           published=published, source_name=source_name, summary='body',
                           feed_id='1', fetched_at='', content_source='', retrieval_status='')


def evidence_obj(key, article_key, quote):
    return {'evidence_id': 'ev-' + key, 'article_key': article_key, 'source_id': 'test-source',
            'evidence_kind': 'quote', 'quote': quote,
            'locator_json': json.dumps({'field': 'summary', 'start': 0, 'length': len(quote)}),
            'source_family': 'test', 'independence': 'unknown', 'observed_at': None,
            'rules_version': 'r1-v1', 'created_at': 't'}


class EntityExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def tearDown(self):
        self.tmp.cleanup()

    def add_article(self, key, title, source_name='Test News'):
        self.store.save_article(article_obj(key, title, source_name), key)

    def add_evidence(self, key, article_key, quote):
        self.uni.add_evidence(evidence_obj(key, article_key, quote))

    def run_extract(self):
        return linking.extract_entities(self.uni)

    def mentions(self):
        with self.uni.connect() as conn:
            return [dict(r) for r in conn.execute(
                'SELECT m.*, e.canonical_name, e.entity_type FROM entity_mentions m '
                'JOIN entities e USING(entity_id) ORDER BY m.mention_id')]

    def relations(self):
        with self.uni.connect() as conn:
            return [dict(r) for r in conn.execute(
                'SELECT r.*, e.canonical_name FROM entity_relations r '
                'JOIN entities e ON e.entity_id=r.subject_entity_id ORDER BY r.relation_id')]

    def test_known_company_mention_keeps_raw_text_and_title_locator(self):
        linking.seed_entities(self.uni, [{'cik': '0000320193', 'name': 'Apple Inc.', 'ticker': 'AAPL'}])
        self.add_article('k1', 'Apple ships a new phone')
        report = self.run_extract()
        row = next(m for m in self.mentions() if m['canonical_name'] == 'Apple Inc.')
        locator = json.loads(row['locator_json'])
        self.assertEqual(row['matched_text'], 'Apple')
        self.assertEqual(row['target_kind'], 'article')
        self.assertEqual((locator['field'], locator['start'], locator['length']), ('title', 0, 5))
        self.assertEqual(row['article_key'], 'k1')
        self.assertGreater(report['mention_rows'], 0)


    def test_evidence_mention_records_evidence_id_and_source_locator(self):
        linking.seed_entities(self.uni, [{'cik': '0000320193', 'name': 'Apple Inc.', 'ticker': 'AAPL'}])
        self.add_article('k1', 'A product story')
        self.add_evidence('e1', 'k1', 'Apple reported revenue growth.')
        self.run_extract()
        row = next(m for m in self.mentions() if m['evidence_id'] == 'ev-e1')
        locator = json.loads(row['locator_json'])
        self.assertEqual(row['target_kind'], 'evidence')
        self.assertEqual(locator['field'], 'evidence_quote')
        self.assertEqual(locator['source_locator']['field'], 'summary')
        self.assertEqual(row['matched_text'], 'Apple')

    def test_organization_government_and_location_have_categories(self):
        self.add_article('k1', 'Federal Reserve Board meets in France with Small Business Bank')
        self.run_extract()
        names = {m['canonical_name']: m['entity_type'] for m in self.mentions()}
        self.assertEqual(names['Federal Reserve Board'], 'government')
        self.assertEqual(names['France'], 'location')
        self.assertEqual(names['Small Business Bank'], 'organization')

    def test_generic_organization_words_are_not_entities(self):
        candidates = linking.extract_text_candidates(
            'The company and A.I. company and Gen Z group and Small Business Bank', [])
        names = {candidate['canonical_name'] for candidate in candidates}
        self.assertNotIn('company', names)
        self.assertNotIn('A.I. company', names)
        self.assertNotIn('Gen Z group', names)
        self.assertIn('Small Business Bank', names)


    def test_source_name_is_not_a_publisher_or_a_mention(self):
        self.add_article('k1', 'A story without the publisher name')
        report = self.run_extract()
        mentions = self.mentions()
        self.assertFalse([m for m in mentions if m['canonical_name'] == 'Test News'])
        self.assertEqual([r for r in self.relations() if r['relation_type'] == linking.REL_PUBLISHED_BY], [])
        with self.uni.connect() as conn:
            entity = conn.execute("SELECT 1 FROM entities WHERE canonical_name='Test News'").fetchone()
            published = conn.execute("SELECT COUNT(*) FROM entity_relations WHERE relation_type='PUBLISHED_BY'").fetchone()[0]
        self.assertIsNone(entity)
        self.assertEqual(published, 0)
        self.assertEqual(report['relations'][linking.REL_PUBLISHED_BY], 0)

    def test_cues_create_applicant_and_regulated_by_relations(self):
        self.add_article('k1', 'Acme Corp applies for a permit')
        placed = self.uni.assign_article(ArticleRef('k1', 'https://example.org/k1',
                                                    'Acme Corp applies for a permit',
                                                    '2026-11-01T00:00:00+00:00'))
        self.add_evidence('e1', 'k1',
                          'Acme Corp applied for a permit. Acme Corp is regulated by Ofcom.')
        self.run_extract()
        relations = self.relations()
        applicant = next(r for r in relations if r['relation_type'] == linking.REL_APPLICANT)
        regulated = next(r for r in relations if r['relation_type'] == linking.REL_REGULATED_BY)
        self.assertEqual(applicant['subject_entity_id'], regulated['subject_entity_id'])
        self.assertEqual(applicant['object_kind'], 'event')
        self.assertEqual(applicant['object_key'], placed['event_id'])
        self.assertEqual(regulated['object_kind'], 'entity')
        with self.uni.connect() as conn:
            regulator = conn.execute('SELECT canonical_name FROM entities WHERE entity_id=?',
                                     (regulated['object_key'],)).fetchone()[0]
        self.assertEqual(regulator, 'Ofcom')
        self.assertEqual(applicant['verification_state'], 'unverified')
        self.assertEqual(regulated['verification_state'], 'unverified')

    def test_petitioner_cue_and_no_affected_by_inference(self):
        self.add_article('k1', 'Acme Corp petitions the regulator')
        self.add_evidence('e1', 'k1', 'Acme Corp filed a petition. Acme Corp affected by the storm.')
        self.run_extract()
        types = {r['relation_type'] for r in self.relations()}
        self.assertIn(linking.REL_PETITIONER, types)
        self.assertNotIn(linking.REL_AFFECTED_BY, types)

    def test_extraction_is_idempotent(self):
        linking.seed_entities(self.uni, [{'cik': '0000320193', 'name': 'Apple Inc.', 'ticker': 'AAPL'}])
        self.add_article('k1', 'Apple ships a new phone')
        first = self.run_extract()
        second = self.run_extract()
        self.assertGreater(first['mention_rows'], 0)
        self.assertEqual(first['mention_rows'], second['mention_rows'])
        self.assertEqual(first['mention_occurrences'], second['mention_occurrences'])
        self.assertEqual(second['entities_created'], 0)

    def test_shared_location_does_not_create_an_event_candidate(self):
        for key, title in (('k1', 'UK trade'), ('k2', 'UK business')):
            self.add_article(key, title)
            self.uni.assign_article(ArticleRef(key, 'https://example.org/' + key, title,
                                               '2026-11-01T00:00:00+00:00'))
        self.run_extract()
        result = linking.link_event_candidates(self.uni)
        self.assertEqual(result['candidate_count'], 0)


if __name__ == '__main__':
    unittest.main()
