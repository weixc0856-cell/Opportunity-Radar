import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar import linking
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore


def article_obj(key, title, published='2026-10-01T08:00:00+00:00', source_name='Test'):
    return SimpleNamespace(article_id=key, title=title, url='https://example.org/' + key,
                           published=published, source_name=source_name, summary='body',
                           feed_id='1', fetched_at='', content_source='', retrieval_status='')


def evidence_row(article_key, source_id='bbc-business', family='bbc', independence='independent_secondary',
                 group='', quote='Acme revenue rose 12 percent', evidence_id=None):
    return {'evidence_id': evidence_id or 'ev-' + article_key, 'article_key': article_key,
            'source_id': source_id, 'source_family': family, 'independence': independence,
            'syndication_group': group, 'evidence_kind': 'quote', 'quote': quote,
            'locator_json': json.dumps({'field': 'summary', 'start': 0, 'length': len(quote)}),
            'source_family': family, 'observed_at': None, 'rules_version': 'r1-v1', 'created_at': 't'}


class SourceIndependenceTests(unittest.TestCase):
    def row(self, article, family, status='independent_secondary', group='', source='s'):
        return {'article_key': article, 'evidence_id': 'ev-' + article, 'source_id': source,
                'source_family': family, 'independence': status, 'syndication_group': group}

    def test_two_columns_of_one_family_are_not_two_units(self):
        result = linking.source_independence([
            self.row('k1', 'bbc'), self.row('k2', 'bbc')])
        self.assertEqual(result['source_family_count'], 1)
        self.assertEqual(result['family_article_counts'], {'bbc': 2})
        self.assertEqual(result['same_family_article_count'], 2)
        self.assertEqual(result['independent_source_units'], 1)
        self.assertEqual(result['independence_status'], 'SINGLE_SOURCE')
        self.assertFalse(result['independent_corroboration'])

    def test_two_independent_families_are_two_units(self):
        result = linking.source_independence([
            self.row('k1', 'bbc', source='bbc-business'),
            self.row('k2', 'bea', status='independent_primary', source='us-bea')])
        self.assertEqual(result['source_family_count'], 2)
        self.assertEqual(result['independent_source_units'], 2)
        self.assertEqual(result['independence_status'], 'MULTI_SOURCE')
        self.assertTrue(result['independent_corroboration'])

    def test_an_unknown_family_is_reported_and_not_counted(self):
        result = linking.source_independence([
            self.row('k1', 'bbc'),
            self.row('k2', '', status='unknown', source='unknown-source')])
        self.assertEqual(result['unknown_family_article_count'], 1)
        self.assertEqual(result['unknown_independence_evidence_count'], 1)
        self.assertEqual(result['independent_source_units'], 1)
        self.assertEqual(result['independence_status'], 'PARTIAL')

    def test_a_recorded_syndication_group_collapses_two_families(self):
        result = linking.source_independence([
            self.row('k1', 'bbc', group='wire-1', source='bbc-business'),
            self.row('k2', 'bea', status='independent_primary', group='wire-1', source='us-bea')])
        self.assertEqual(result['source_family_count'], 2)
        self.assertEqual(result['syndicated_article_count'], 2)
        self.assertEqual(result['syndication_groups'], ['wire-1'])
        self.assertEqual(result['independent_source_units'], 1)
        self.assertFalse(result['independent_corroboration'])

    def test_no_evidence_is_insufficient_data(self):
        result = linking.source_independence([])
        self.assertEqual(result['independence_status'], 'INSUFFICIENT_DATA')
        self.assertFalse(result['independent_corroboration'])


class EventCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def tearDown(self):
        self.tmp.cleanup()

    def add_article(self, key, title, published='2026-10-01T08:00:00+00:00', source_name='Test'):
        self.store.save_article(article_obj(key, title, published, source_name), key)
        return self.uni.assign_article(ArticleRef(
            key, 'https://example.org/' + key, title, published))['event_id']

    def add_evidence(self, key, quote, family='bbc', source='bbc-business',
                     independence='independent_secondary'):
        self.uni.add_evidence(evidence_row(key, source_id=source, family=family,
                                           independence=independence, quote=quote))

    def add_entity(self, article_key, entity_id='ent-acme'):
        with self.uni.connect() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO entity_mentions(mention_id,entity_id,target_kind,target_key,method,'
                'matched_text,confidence,created_at) VALUES(?,?,?,?,?,?,?,?)',
                ('men-' + entity_id + '-' + article_key, entity_id, 'article', article_key,
                 'name', 'Acme', 1.0, 't'))

    def test_a_shared_fact_creates_a_strong_candidate_without_merging(self):
        left = self.add_article('k1', 'Acme reports record quarterly revenue')
        right = self.add_article('k2', 'Acme quarterly revenue beats forecasts')
        quote = 'Acme revenue rose 12 percent to 5 billion'
        self.add_evidence('k1', quote, family='bbc', source='bbc-business')
        self.add_evidence('k2', quote, family='nyt', source='nyt-business')
        result = linking.link_event_candidates(self.uni)
        self.assertEqual((result['strong'], result['weak'], result['created']), (1, 0, 1))
        self.assertNotEqual(left, right)
        with self.uni.connect() as conn:
            link = dict(conn.execute('SELECT * FROM event_links').fetchone())
            events = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            members = conn.execute('SELECT COUNT(*) FROM event_articles').fetchone()[0]
        detail = json.loads(link['evidence_json'])
        self.assertEqual(link['relation'], linking.REL_EVENT_CANDIDATE)
        self.assertEqual(link['status'], 'candidate')
        self.assertEqual({link['left_key'], link['right_key']}, {left, right})
        articles_by_event = {detail['left_event_id']: set(detail['left_article_keys']),
                             detail['right_event_id']: set(detail['right_article_keys'])}
        self.assertEqual(articles_by_event[left], {'k1'})
        self.assertEqual(articles_by_event[right], {'k2'})
        self.assertEqual(detail['grade'], 'strong')
        self.assertEqual(detail['shared_quote_evidence_ids'], ['ev-k1', 'ev-k2'])
        self.assertEqual(detail['reprint_status'], 'reprint_candidate')
        self.assertTrue(detail['reprint_candidate'])
        self.assertEqual(result['reprint_candidates'], 1)
        self.assertEqual((events, members), (2, 2))

    def test_a_title_only_match_is_at_most_weak(self):
        self.add_article('k1', 'ParaView Office hours to go on hiatus in 2027')
        self.add_article('k2', 'ParaView Office Hours October 29, 2026')
        self.add_evidence('k1', 'Office hours are paused next year', family='paraview', source='paraview-forum')
        self.add_evidence('k2', 'Office hours will be held on October 29', family='paraview',
                          source='paraview-forum')
        result = linking.link_event_candidates(self.uni)
        self.assertEqual((result['strong'], result['weak']), (0, 1))
        detail = json.loads(self._one_link()['evidence_json'])
        self.assertEqual(detail['grade'], 'weak')
        self.assertEqual(detail['reprint_status'], 'same_source_family')
        self.assertFalse(detail['reprint_candidate'])

    def test_unrelated_titles_stay_unlinked(self):
        self.add_article('k1', 'Alpha wins a contract')
        self.add_article('k2', 'Beta launches a product')
        result = linking.link_event_candidates(self.uni)
        self.assertEqual(result['candidate_count'], 0)
        self.assertEqual(self._links(), [])

    def test_a_pair_outside_the_window_stays_unlinked(self):
        self.add_article('k1', 'Acme reports record revenue', '2026-10-01T08:00:00+00:00')
        self.add_article('k2', 'Acme reports record revenue', '2026-10-10T08:00:00+00:00')
        result = linking.link_event_candidates(self.uni)
        self.assertEqual(result['outside_window'], 1)
        self.assertEqual(result['candidate_count'], 0)

    def test_an_unknown_family_does_not_become_a_reprint_candidate(self):
        self.add_article('k1', 'Acme reports record quarterly revenue')
        self.add_article('k2', 'Acme quarterly revenue beats forecasts')
        quote = 'Acme revenue rose 12 percent to 5 billion'
        self.add_evidence('k1', quote, family='', source='unknown-source')
        self.add_evidence('k2', quote, family='', source='unknown-source')
        result = linking.link_event_candidates(self.uni)
        detail = json.loads(self._one_link()['evidence_json'])
        self.assertEqual(detail['reprint_status'], 'unknown')
        self.assertFalse(detail['reprint_candidate'])
        self.assertEqual(result['unknown_reprint_status'], 1)

    def test_rerunning_candidates_is_idempotent(self):
        self.add_article('k1', 'ParaView Office hours to go on hiatus in 2027')
        self.add_article('k2', 'ParaView Office Hours October 29, 2026')
        first = linking.link_event_candidates(self.uni)
        second = linking.link_event_candidates(self.uni)
        self.assertEqual((first['created'], second['created']), (1, 0))
        self.assertEqual(second['existing'], 1)
        self.assertEqual(len(self._links()), 1)

    def _links(self):
        with self.uni.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM event_links')]

    def _one_link(self):
        links = self._links()
        self.assertEqual(len(links), 1)
        return links[0]


if __name__ == '__main__':
    unittest.main()
