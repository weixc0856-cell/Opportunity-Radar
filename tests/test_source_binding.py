import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opportunity_radar.source_binding import backfill_article_sources
from opportunity_radar.store import Store


def article(key, source_name, source_id=''):
    return SimpleNamespace(article_id=key, title='t-' + key, url='https://example.org/' + key,
                           published='2026-11-01T00:00:00+00:00', source_name=source_name,
                           summary='body', feed_id='1', fetched_at='', content_source='',
                           retrieval_status=''), source_id


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        self.store = Store(str(self.db))
        self.sources = [
            SimpleNamespace(source_id='bbc-business', name='BBC Business'),
            SimpleNamespace(source_id='nyt-business', name='NYT Business'),
            SimpleNamespace(source_id='same-a', name='Same Name'),
            SimpleNamespace(source_id='same-b', name='Same  Name'),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, key, source_name, source_id='', meta_source=''):
        obj, bound = article(key, source_name, source_id)
        self.store.save_article(obj, key, source_id=bound)
        if meta_source is not None:
            self.store.save_analysis(key, {}, {'score': 1, 'risk_flag': ''},
                                     {'source_id': meta_source})

    def source_ids(self):
        with self.store.connect() as conn:
            return {row[0]: row[1] for row in conn.execute(
                'SELECT article_key, source_id FROM articles ORDER BY article_key')}

    def test_save_article_binds_source_and_does_not_erase_it(self):
        obj, _ = article('k1', 'BBC Business', 'bbc-business')
        self.store.save_article(obj, 'k1', source_id='bbc-business')
        self.assertEqual(self.source_ids()['k1'], 'bbc-business')
        obj2, _ = article('k1', 'BBC Business', '')
        self.store.save_article(obj2, 'k1', source_id='')
        self.assertEqual(self.source_ids()['k1'], 'bbc-business')

    def test_dry_run_does_not_write(self):
        self.add('k1', 'BBC Business', meta_source='bbc-business')
        report = backfill_article_sources(self.store, self.sources, dry_run=True)
        self.assertEqual(report['changed'], 1)
        self.assertEqual(report['from_meta'], 1)
        self.assertEqual(self.source_ids()['k1'], '')

    def test_meta_then_name_fallback_then_unresolved(self):
        self.add('k1', 'Some Feed', meta_source='bbc-business')
        self.add('k2', 'BBC Business', meta_source='')
        self.add('k3', 'Unknown Feed', meta_source='')
        report = backfill_article_sources(self.store, self.sources)
        self.assertEqual(report['from_meta'], 1)
        self.assertEqual(report['from_name'], 1)
        self.assertEqual(report['unresolved'], 1)
        self.assertEqual(self.source_ids(), {'k1': 'bbc-business', 'k2': 'bbc-business',
                                             'k3': ''})
        self.assertIn('Unknown Feed', report['unresolved_names'])

    def test_existing_valid_binding_is_kept_and_ambiguous_name_is_not_guessed(self):
        self.add('k1', 'Whatever', source_id='nyt-business', meta_source='')
        self.add('k2', 'Same Name', meta_source='')
        report = backfill_article_sources(self.store, self.sources)
        self.assertEqual(self.source_ids(), {'k1': 'nyt-business', 'k2': ''})
        self.assertEqual(report['already_bound'], 1)
        self.assertEqual(report['unresolved'], 1)
        self.assertEqual(report['ambiguous_names'], ['same name'])

    def test_a_reviewed_feed_alias_binds_without_fuzzy_matching(self):
        self.sources.append(SimpleNamespace(source_id='simscale-forum', name='SimScale Community Forum'))
        self.add('k1', 'SimScale Forum', meta_source='')
        report = backfill_article_sources(self.store, self.sources)
        self.assertEqual(report['from_alias'], 1)
        self.assertEqual(self.source_ids()['k1'], 'simscale-forum')

    def test_rerun_is_idempotent(self):
        self.add('k1', 'BBC Business', meta_source='')
        first = backfill_article_sources(self.store, self.sources)
        second = backfill_article_sources(self.store, self.sources)
        self.assertEqual(first['changed'], 1)
        self.assertEqual(second['changed'], 0)
        self.assertEqual(second['already_bound'], 1)


if __name__ == '__main__':
    unittest.main()
