"""Batch 3: source lineage and independent corroboration.

The rules under test are the ones that decide whether a count may become a claim:
one organisation is one family however many feeds it publishes, an unknown source never
counts, and a shared wire copy is not a second source.
"""
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import lineage, linking
from opportunity_radar.store import Store
from opportunity_radar.unified import ArticleRef, UnifiedStore

ROW = {'source_id': 'x', 'source_family': 'fam-x', 'lineage_kind': 'news_organisation',
       'parent_source': '', 'syndication_group': '', 'ownership_group': 'own-x',
       'independence': 'independent_secondary', 'basis': 'recorded reason',
       'basis_source': 'config/sources.local.csv', 'reviewed_at': '2026-11-01',
       'review_status': 'declared'}


def row(**over):
    data = dict(ROW)
    data.update(over)
    return data


class RegistryTests(unittest.TestCase):
    def test_a_complete_row_is_accepted(self):
        self.assertEqual(lineage.validate({'x': row()}), [])

    def test_a_family_is_required(self):
        problems = lineage.validate({'x': row(source_family='')})
        self.assertTrue(any('source_family' in p for p in problems))

    def test_an_unknown_confident_status_needs_a_basis(self):
        problems = lineage.validate({'x': row(basis='')})
        self.assertTrue(any('basis' in p for p in problems))
        # `unknown` is allowed to carry no basis - it claims nothing.
        self.assertEqual(lineage.validate({'x': row(basis='', independence='unknown')}), [])

    def test_bad_vocabulary_is_rejected(self):
        self.assertTrue(any('lineage_kind' in p for p in lineage.validate({'x': row(lineage_kind='blog')})))
        self.assertTrue(any('independence' in p for p in lineage.validate({'x': row(independence='maybe')})))
        self.assertTrue(any('review_status' in p for p in lineage.validate({'x': row(review_status='guessed')})))

    def test_an_unregistered_source_is_rejected(self):
        problems = lineage.validate({'ghost': row(source_id='ghost')}, known_source_ids={'x'})
        self.assertTrue(any('not a registered source' in p for p in problems))

    def test_the_committed_registry_is_valid(self):
        registry = lineage.load()
        self.assertTrue(registry)
        self.assertEqual(lineage.validate(registry), [])

    def test_families_group_several_feeds(self):
        registry = {'a': row(source_id='a', source_family='bbc'),
                    'b': row(source_id='b', source_family='bbc'),
                    'c': row(source_id='c', source_family='nyt')}
        self.assertEqual(lineage.families_for(registry), {'bbc': ['a', 'b'], 'nyt': ['c']})


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-lineage-'))
        self.db = self.dir / 'db.sqlite3'
        Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def evidence(self, evidence_id, source_id):
        self.uni.add_evidence({'evidence_id': evidence_id, 'article_key': '', 'source_id': source_id,
                               'evidence_kind': 'quote', 'quote': 'q', 'locator_json': '{}',
                               'source_family': source_id, 'independence': 'unknown',
                               'observed_at': None, 'rules_version': 'r1-v1', 'created_at': 't'})

    def test_lineage_rewrites_family_and_independence(self):
        self.evidence('ev-1', 'bbc-business')
        self.evidence('ev-2', 'bbc-technology')
        result = lineage.apply(self.uni, {'bbc-business': row(source_id='bbc-business', source_family='bbc'),
                                          'bbc-technology': row(source_id='bbc-technology', source_family='bbc')})
        self.assertEqual(result['evidences_updated'], 2)
        with self.uni.connect() as conn:
            rows = [tuple(r) for r in conn.execute('SELECT source_id, source_family, independence, lineage_basis FROM evidences ORDER BY source_id')]
        self.assertEqual(rows[0][:3], ('bbc-business', 'bbc', 'independent_secondary'))
        self.assertEqual(rows[0][3], 'recorded reason')

    def test_a_source_without_a_row_keeps_unknown(self):
        self.evidence('ev-1', 'someone-else')
        result = lineage.apply(self.uni, {'bbc-business': row(source_id='bbc-business', source_family='bbc')})
        self.assertEqual(result['unmapped_sources'], ['someone-else'])
        with self.uni.connect() as conn:
            self.assertEqual(tuple(conn.execute('SELECT source_family, independence FROM evidences').fetchone()),
                             ('someone-else', 'unknown'))

    def test_applying_twice_changes_nothing(self):
        self.evidence('ev-1', 'bbc-business')
        registry = {'bbc-business': row(source_id='bbc-business', source_family='bbc')}
        self.assertEqual(lineage.apply(self.uni, registry)['evidences_updated'], 1)
        self.assertEqual(lineage.apply(self.uni, registry)['evidences_updated'], 0)


class CorroborationTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-corr-'))
        self.db = self.dir / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))
        for key, source in (('k1', 'bbc-business'), ('k2', 'bbc-technology'), ('k3', 'us-bea')):
            from types import SimpleNamespace
            article = SimpleNamespace(article_id=key, title='Same story', url='https://example.org/' + key,
                                      published='2026-10-29T00:00:00+00:00', source_name=source,
                                      summary='q', feed_id='1', fetched_at='', content_source='',
                                      retrieval_status='')
            self.store.save_article(article, key)

    def add(self, evidence_id, article_key, source_id, family, independence, group=''):
        with self.uni.connect() as conn:
            conn.execute('INSERT INTO evidences(evidence_id,article_key,source_id,evidence_kind,quote,locator_json,'
                         'source_family,independence,lineage_basis,syndication_group,observed_at,rules_version,created_at) '
                         'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (evidence_id, article_key, source_id, 'quote', 'q', '{}', family, independence,
                          '', group, None, 'r1-v1', 't'))

    def event_with(self, *article_sources):
        event = None
        for key, source in article_sources:
            placed = self.uni.assign_article(ArticleRef(key, 'https://example.org/' + key, 'Same story',
                                                        '2026-10-29T00:00:00+00:00', source))
            event = placed['event_id']
            with self.uni.connect() as conn:
                conn.execute('UPDATE event_articles SET event_id=? WHERE article_key=?', (event, key))
        return event

    def test_two_independent_families_corroborate(self):
        event = self.event_with(('k1', 'bbc-business'), ('k3', 'us-bea'))
        self.add('ev-1', 'k1', 'bbc-business', 'bbc', 'independent_secondary')
        self.add('ev-2', 'k3', 'us-bea', 'bea', 'independent_primary')
        profile = linking.event_profile(self.uni, event)
        self.assertEqual(profile['source_families'], ['bbc', 'bea'])
        self.assertEqual(profile['corroborating_units'], 2)
        self.assertTrue(profile['independent_corroboration'])

    def test_two_columns_of_one_organisation_do_not_corroborate(self):
        event = self.event_with(('k1', 'bbc-business'), ('k2', 'bbc-technology'))
        self.add('ev-1', 'k1', 'bbc-business', 'bbc', 'independent_secondary')
        self.add('ev-2', 'k2', 'bbc-technology', 'bbc', 'independent_secondary')
        profile = linking.event_profile(self.uni, event)
        self.assertEqual(profile['source_families'], ['bbc'])
        self.assertEqual(profile['evidences'], 2)
        self.assertEqual(profile['corroborating_units'], 1)
        self.assertFalse(profile['independent_corroboration'])

    def test_an_unknown_source_never_counts(self):
        event = self.event_with(('k1', 'bbc-business'), ('k2', 'bbc-technology'))
        self.add('ev-1', 'k1', 'bbc-business', 'bbc', 'independent_secondary')
        self.add('ev-2', 'k2', 'bbc-technology', 'bbc', 'unknown')
        profile = linking.event_profile(self.uni, event)
        self.assertEqual(profile['corroborating_units'], 1)
        self.assertFalse(profile['independent_corroboration'])

    def test_a_shared_wire_copy_is_one_unit(self):
        event = self.event_with(('k1', 'bbc-business'), ('k3', 'us-bea'))
        self.add('ev-1', 'k1', 'bbc-business', 'bbc', 'independent_secondary', group='wire-1')
        self.add('ev-2', 'k3', 'us-bea', 'bea', 'independent_primary', group='wire-1')
        profile = linking.event_profile(self.uni, event)
        self.assertEqual(profile['syndication_groups'], ['wire-1'])
        self.assertEqual(profile['corroborating_units'], 1)
        self.assertFalse(profile['independent_corroboration'])


if __name__ == '__main__':
    unittest.main()
