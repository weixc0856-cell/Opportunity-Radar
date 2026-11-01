"""Batch 2: entity alignment and candidate links.

The rules under test are the ones that decide whether two records are connected, so the
tests are about restraint as much as recall: a mention must be a whole word from the
registered name, and every link must start as a candidate that nothing merges.
"""
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import linking
from opportunity_radar.store import Store
from opportunity_radar.unified import UnifiedStore, ArticleRef

COMPANIES = [
    {'cik': '0000320193', 'name': 'Apple Inc.', 'ticker': 'AAPL'},
    {'cik': '0000021344', 'name': 'The Coca-Cola Company', 'ticker': 'KO'},
]


class AliasTests(unittest.TestCase):
    def test_corporate_forms_are_dropped_from_the_alias_not_the_entity(self):
        aliases = linking.derive_aliases('Apple Inc.')
        self.assertIn('Apple Inc.', aliases)
        self.assertIn('Apple', aliases)

    def test_a_leading_the_is_removed_for_matching(self):
        self.assertIn('Coca-Cola', linking.derive_aliases('The Coca-Cola Company'))

    def test_short_aliases_are_not_created(self):
        # "A" or "AA" would match everything; the entity keeps its name, matching stays off.
        self.assertEqual(linking.derive_aliases('A Inc.'), ['A Inc.'])

    def test_a_mention_must_be_a_whole_word(self):
        aliases = [('ent-1', 'Apple', True)]
        self.assertTrue(linking.find_mentions('Apple shipped a phone', aliases))
        self.assertTrue(linking.find_mentions("Apple's phone", aliases))
        self.assertFalse(linking.find_mentions('Applesauce is not a company', aliases))

    def test_the_canonical_name_is_more_confident_than_an_alias(self):
        canonical = linking.find_mentions('Apple Inc. reported', [('ent-1', 'Apple Inc.', True)])
        alias = linking.find_mentions('Apple reported', [('ent-1', 'Apple', False)])
        self.assertGreater(canonical[0][3], alias[0][3])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-linking-'))
        self.db = self.dir / 'db.sqlite3'
        Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def test_seeding_is_idempotent(self):
        first = linking.seed_entities(self.uni, COMPANIES)
        second = linking.seed_entities(self.uni, COMPANIES)
        self.assertEqual((first, second), (2, 0))
        with self.uni.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM entities').fetchone()[0], 2)

    def test_mentions_are_idempotent_and_record_what_matched(self):
        linking.seed_entities(self.uni, COMPANIES)
        texts = [('k1', 'Apple Inc. reported earnings'), ('k2', 'Nothing to do with the list')]
        first = linking.index_mentions(self.uni, texts)
        second = linking.index_mentions(self.uni, texts)
        self.assertEqual(first['mentions'], 1)
        self.assertEqual(second['mentions'], 0)
        with self.uni.connect() as conn:
            row = dict(conn.execute('SELECT * FROM entity_mentions').fetchone())
        self.assertEqual(row['method'], 'name')
        self.assertEqual(row['target_key'], 'k1')


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-links-'))
        self.db = self.dir / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))
        linking.seed_entities(self.uni, COMPANIES)
        self.entity_id = linking.entity_id_for('0000320193')

    def add_event(self, key, published, title='Apple ships something'):
        from types import SimpleNamespace
        article = SimpleNamespace(article_id=key, title=title, url='https://example.org/' + key,
                                  published=published, source_name='Test', summary='Apple body',
                                  feed_id='1', fetched_at='', content_source='', retrieval_status='')
        self.store.save_article(article, key)
        return self.uni.assign_article(ArticleRef(key, article.url, title, published))['event_id']

    def test_a_mention_links_a_claim_to_a_nearby_event(self):
        event_id = self.add_event('k1', '2026-10-27T00:00:00+00:00', 'Apple ships a new phone')
        linking.index_mentions(self.uni, [('k1', 'Apple ships a new phone')])
        created = linking.link_claims_to_events(self.uni, [
            {'claim_id': 'cl-1', 'entity_id': self.entity_id, 'period': '2026-01-01/2026-06-30'}])
        self.assertEqual(created, 1)
        with self.uni.connect() as conn:
            row = dict(conn.execute('SELECT * FROM event_links').fetchone())
        self.assertEqual((row['left_kind'], row['right_kind'], row['status']), ('claim', 'event', 'candidate'))
        self.assertEqual(row['relation'], linking.REL_SAME_SUBJECT)
        self.assertEqual(row['right_key'], event_id)

    def test_a_claim_outside_the_window_is_not_linked(self):
        self.add_event('k1', '2026-10-27T00:00:00+00:00')
        linking.index_mentions(self.uni, [('k1', 'Apple')])
        created = linking.link_claims_to_events(self.uni, [
            {'claim_id': 'cl-1', 'entity_id': self.entity_id, 'period': '2020-01-01/2020-03-31'}])
        self.assertEqual(created, 0)

    def test_a_claim_for_an_entity_with_no_event_is_not_linked(self):
        created = linking.link_claims_to_events(self.uni, [
            {'claim_id': 'cl-1', 'entity_id': self.entity_id, 'period': '2026-01-01/2026-06-30'}])
        self.assertEqual(created, 0)

    def test_two_events_naming_one_company_are_linked_as_candidates(self):
        first = self.add_event('k1', '2026-10-27T00:00:00+00:00', 'Apple ships a new phone')
        second = self.add_event('k2', '2026-10-29T00:00:00+00:00', 'Apple opens a new store')
        linking.index_mentions(self.uni, [('k1', 'Apple ships'), ('k2', 'Apple opens')])
        created = linking.link_events_by_entity(self.uni)
        self.assertEqual(created, 1)
        with self.uni.connect() as conn:
            row = dict(conn.execute('SELECT * FROM event_links').fetchone())
        self.assertEqual({row['left_key'], row['right_key']}, {first, second})
        self.assertEqual(row['relation'], linking.REL_SHARED_ENTITY)
        self.assertEqual(row['status'], 'candidate')

    def test_two_events_far_apart_are_not_linked(self):
        self.add_event('k1', '2026-10-27T00:00:00+00:00', 'Apple ships a new phone')
        self.add_event('k2', '2026-10-30T00:00:00+00:00', 'Apple opens a new store')
        linking.index_mentions(self.uni, [('k1', 'Apple ships'), ('k2', 'Apple opens')])
        self.assertEqual(linking.link_events_by_entity(self.uni, window_days=1), 0)

    def test_a_decision_is_appended_not_rewritten(self):
        self.add_event('k1', '2026-10-27T00:00:00+00:00')
        linking.index_mentions(self.uni, [('k1', 'Apple')])
        linking.link_claims_to_events(self.uni, [
            {'claim_id': 'cl-1', 'entity_id': self.entity_id, 'period': '2026-01-01/2026-06-30'}])
        with self.uni.connect() as conn:
            link_id = conn.execute('SELECT link_id FROM event_links').fetchone()[0]
        linking.record_decision(self.uni, link_id, 'accepted', actor='qa', note='period matches')
        with self.uni.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM event_links WHERE link_id=?', (link_id,)).fetchone()[0], 'accepted')
            correction = dict(conn.execute('SELECT * FROM event_corrections').fetchone())
        self.assertEqual(correction['action'], 'link_accepted')
        self.assertIn('period matches', correction['payload_json'])
        with self.assertRaises(ValueError):
            linking.record_decision(self.uni, link_id, 'maybe')


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-profile-'))
        self.db = self.dir / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def test_a_single_unknown_source_is_not_called_corroboration(self):
        from types import SimpleNamespace
        article = SimpleNamespace(article_id='k1', title='Apple news', url='https://example.org/k1',
                                  published='2026-10-27T00:00:00+00:00', source_name='Test',
                                  summary='q', feed_id='1', fetched_at='', content_source='',
                                  retrieval_status='')
        self.store.save_article(article, 'k1')
        event_id = self.uni.assign_article(ArticleRef('k1', article.url, article.title, article.published))['event_id']
        self.uni.add_evidence({'evidence_id': 'ev-1', 'article_key': 'k1', 'source_id': 's1',
                               'evidence_kind': 'quote', 'quote': 'q',
                               'locator_json': '{"field":"summary","start":0,"length":1}',
                               'source_family': 's1', 'independence': 'unknown',
                               'observed_at': None, 'rules_version': 'r1-v1', 'created_at': 't'})
        profile = linking.event_profile(self.uni, event_id)
        self.assertEqual(profile['evidences'], 1)
        self.assertEqual(profile['source_families'], ['s1'])
        self.assertFalse(profile['independent_corroboration'])
        self.assertIn('独立性未知', profile['quality_note'])


if __name__ == '__main__':
    unittest.main()
