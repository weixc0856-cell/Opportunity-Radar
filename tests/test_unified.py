import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import unified
from opportunity_radar.store import Store
from opportunity_radar.unified import UnifiedStore, ArticleRef


class NormalisationTests(unittest.TestCase):
    def test_tracking_parameters_and_fragments_are_not_part_of_the_identity(self):
        plain = unified.canonical_url('https://ons.gov.uk/releases/x')
        noisy = unified.canonical_url('http://www.ons.gov.uk/releases/x/?utm_source=feed&fbclid=1#top')
        self.assertEqual(plain, noisy)

    def test_a_query_that_matters_is_kept(self):
        self.assertIn('page=2', unified.canonical_url('https://example.org/a?page=2'))

    def test_publisher_suffixes_are_stripped_only_at_the_end(self):
        self.assertEqual(unified.canonical_title('UK trade: September 2026 — time series'),
                         unified.canonical_title('UK trade: September 2026'))
        self.assertNotEqual(unified.canonical_title('UK trade time series review'),
                            unified.canonical_title('UK trade'))

    def test_punctuation_and_case_do_not_change_the_title(self):
        self.assertEqual(unified.canonical_title('ONS: Retail Sales, Sept 2026'),
                         unified.canonical_title('ons retail sales sept 2026'))

    def test_time_gaps_are_absolute_and_timezone_aware(self):
        self.assertAlmostEqual(unified.hours_apart('2026-10-29T00:00:00+00:00',
                                                   '2026-10-30T12:00:00+00:00'), 36.0)
        self.assertIsNone(unified.hours_apart('', '2026-10-30T12:00:00+00:00'))


class RelationTests(unittest.TestCase):
    def article(self, **kw):
        base = dict(article_key='a', url='https://example.org/1', title='Retail sales rise',
                    published='2026-10-29T08:00:00+00:00')
        base.update(kw)
        return ArticleRef(**base)

    def test_same_url_is_the_same_story_at_full_confidence(self):
        relation, confidence, reason = unified.match_relation(
            self.article(), object(), {'https://example.org/1'}, set(),
            '2026-10-29T08:00:00+00:00', '2026-10-29T08:00:00+00:00')
        self.assertEqual((relation, confidence, reason), (unified.SAME_STORY, 1.0, 'canonical_url'))

    def test_a_title_inside_the_window_joins_the_event(self):
        relation, confidence, _ = unified.match_relation(
            self.article(title='Retail sales rise — time series'), object(),
            {'https://elsewhere.example/1'}, {'retail sales rise'},
            '2026-10-29T08:00:00+00:00', '2026-10-29T08:00:00+00:00')
        self.assertEqual(relation, unified.SAME_STORY)
        self.assertLess(confidence, 1.0)

    def test_a_title_outside_the_window_is_a_different_event(self):
        relation, _, reason = unified.match_relation(
            self.article(published='2026-11-20T08:00:00+00:00'), object(),
            set(), {'retail sales rise'}, '2026-10-29T08:00:00+00:00',
            '2026-10-29T08:00:00+00:00')
        self.assertIsNone(relation)
        self.assertEqual(reason, 'title_outside_window')

    def test_shared_keywords_alone_never_merge(self):
        relation, _, reason = unified.match_relation(
            self.article(title='Retail sales rise in Germany'), object(),
            set(), {'retail sales rise'}, '2026-10-29T08:00:00+00:00', '2026-10-29T08:00:00+00:00')
        self.assertIsNone(relation)
        self.assertEqual(reason, 'no_rule_matched')


class EventAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-unified-'))
        self.db = self.dir / 'store.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def add_article(self, key, url, title, published, summary='body'):
        from types import SimpleNamespace
        article = SimpleNamespace(article_id=key, title=title, url=url, published=published,
                                  source_name='Test', summary=summary, feed_id='1',
                                  fetched_at='', content_source='', retrieval_status='')
        self.store.save_article(article, key)

    def test_the_ons_shape_merges_and_an_unrelated_title_does_not(self):
        self.add_article('k1', 'https://ons.gov.uk/releases/retail', 'Retail sales: September 2026',
                         '2026-10-29T08:00:00+00:00')
        # Same release published as a second entry with the publisher's own suffix.
        self.add_article('k2', 'https://ons.gov.uk/releases/retail-series',
                         'Retail sales: September 2026 time series', '2026-10-29T09:00:00+00:00')
        self.add_article('k3', 'https://ons.gov.uk/releases/other', 'Retail sales in Germany',
                         '2026-10-29T09:00:00+00:00')
        first = self.uni.assign_article(ArticleRef('k1', 'https://ons.gov.uk/releases/retail',
                                                   'Retail sales: September 2026', '2026-10-29T08:00:00+00:00'))
        second = self.uni.assign_article(ArticleRef('k2', 'https://ons.gov.uk/releases/retail-series',
                                                    'Retail sales: September 2026 time series', '2026-10-29T09:00:00+00:00'))
        third = self.uni.assign_article(ArticleRef('k3', 'https://ons.gov.uk/releases/other',
                                                   'Retail sales in Germany', '2026-10-29T09:00:00+00:00'))
        self.assertEqual(first['event_id'], second['event_id'])
        self.assertEqual(second['relation'], unified.SAME_STORY)
        self.assertNotEqual(first['event_id'], third['event_id'])
        self.assertEqual(len(self.uni.event_members(first['event_id'])), 2)

    def test_assigning_the_same_article_twice_creates_nothing(self):
        self.add_article('k1', 'https://example.org/a', 'A', '2026-10-29T08:00:00+00:00')
        ref = ArticleRef('k1', 'https://example.org/a', 'A', '2026-10-29T08:00:00+00:00')
        first = self.uni.assign_article(ref)
        second = self.uni.assign_article(ref)
        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        self.assertEqual(first['event_id'], second['event_id'])
        self.assertEqual(self.uni.counts()['events'], 1)
        self.assertEqual(self.uni.counts()['event_articles'], 1)

    def test_a_database_without_articles_still_accepts_records(self):
        bare = self.dir / 'ingest.sqlite3'
        uni = UnifiedStore(str(bare))
        self.assertFalse(uni.has_articles)
        result = uni.assign_article(ArticleRef('', 'https://example.org/x', 'x', '2026-10-29T00:00:00+00:00'))
        self.assertTrue(result['created'])


class RecordTests(unittest.TestCase):
    fact = {'ordinal': 2, 'text': 'Revenue rose 5%', 'status': 'located',
            'meta': {'quote': 'Revenue rose 5%', 'actor': 'Apple',
                     'locator': {'field': 'summary', 'start': 10, 'length': 14},
                     'published': '2026-10-29T00:00:00+00:00'}}

    def test_a_fact_becomes_evidence_and_a_skeleton_claim(self):
        evidence = unified.evidence_from_fact('k1', self.fact, 'bbc-business')
        claim = unified.claim_from_fact('k1', self.fact, 'evt-1')
        self.assertEqual(evidence['evidence_kind'], 'quote')
        self.assertEqual(evidence['source_id'], 'bbc-business')
        self.assertEqual(evidence['independence'], 'unknown')
        self.assertEqual(evidence['observed_at'], self.fact['meta']['published'])
        self.assertEqual(claim['subject'], 'Apple')
        self.assertEqual(claim['extractor'], 'skeleton')
        self.assertEqual(claim['verification_state'], 'unverified')
        self.assertIsNone(claim['value_num'])
        self.assertEqual(json.loads(claim['locator_json'])['field'], 'summary')

    def test_a_skeleton_claim_does_not_use_the_publication_date_as_period(self):
        claim = unified.claim_from_fact('k1', self.fact, 'evt-1')
        self.assertEqual(claim['period'], '')
        self.assertEqual(claim['period_raw'], '')

    def test_an_explicit_valid_period_is_kept_on_a_fact_claim(self):
        claim = unified.claim_from_fact('k1', dict(self.fact, period='2026-09'), 'evt-1')
        self.assertEqual((claim['period'], claim['period_raw']), ('2026-09', '2026-09'))

    def test_an_invalid_explicit_period_is_not_normalised_into_a_guess(self):
        claim = unified.claim_from_fact('k1', dict(self.fact, period='next quarter'), 'evt-1')
        self.assertEqual(claim['period'], '')
        self.assertEqual(claim['period_raw'], 'next quarter')

    def test_ids_are_content_hashes_not_timestamps(self):
        a = unified.evidence_from_fact('k1', self.fact, 'src')
        b = unified.evidence_from_fact('k1', self.fact, 'src')
        self.assertEqual(a['evidence_id'], b['evidence_id'])
        other = dict(self.fact, meta=dict(self.fact['meta'], quote='Revenue fell 5%'))
        self.assertNotEqual(a['evidence_id'], unified.evidence_from_fact('k1', other, 'src')['evidence_id'])

    def test_an_unlocated_fact_cannot_become_evidence(self):
        bad = {'ordinal': 1, 'text': 'x', 'status': 'unlocated', 'meta': {'quote': 'x', 'locator': None}}
        with self.assertRaises(ValueError):
            unified.evidence_from_fact('k1', bad, 'src')

    def test_a_sec_fact_keeps_its_filing_reference(self):
        fact = {'cik': '0000320193', 'entity_name': 'Apple Inc.', 'taxonomy': 'us-gaap',
                'tag': 'Revenues', 'unit': 'USD', 'value_num': 100.0, 'value_raw': '100',
                'period_start': '2024-09-29', 'period_end': '2025-09-27', 'accn': '0000320193-25-000001',
                'form': '10-K', 'filed': '2025-10-31', 'metric_id': 'revenue',
                'filing_relation': 'original', 'last_seen_at': '2026-11-01T00:00:00+00:00'}
        evidence = unified.sec_evidence(fact)
        claim = unified.sec_claim(fact)
        locator = json.loads(evidence['locator_json'])
        self.assertEqual(locator['accn'], fact['accn'])
        self.assertEqual(evidence['independence'], 'independent_primary')
        self.assertEqual(claim['value_num'], 100.0)
        self.assertEqual(claim['currency'], 'USD')
        self.assertEqual(claim['revision'], 'original')

    def test_an_eia_observation_keeps_the_series_and_period(self):
        obs = {'series_id': 'eia:coal', 'period': '2026-08', 'value_raw': '123', 'value_num': 123.0,
               'unit': 'thousand megawatthours', 'period_kind': 'monthly', 'quality_flags': '',
               'snapshot_hash': 'h', 'last_seen_at': '2026-11-01T00:00:00+00:00'}
        series = {'series_id': 'eia:coal', 'dataset': 'electric-power-operational-data',
                  'route': '/x', 'metric': 'generation'}
        claim = unified.eia_claim(obs, series)
        locator = json.loads(claim['locator_json'])
        self.assertEqual(locator['period'], '2026-08')
        self.assertEqual(claim['predicate'], 'generation')


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-backfill-'))
        self.db = self.dir / 'store.sqlite3'
        self.store = Store(str(self.db))
        self.uni = UnifiedStore(str(self.db))

    def save(self, key, title, facts, schema_version=5, source_id='bbc-business', article_source_id=''):
        from types import SimpleNamespace
        article = SimpleNamespace(article_id=key, title=title, url='https://example.org/' + key,
                                  published='2026-10-29T08:00:00+00:00', source_name='Test',
                                  summary='Revenue rose 5% on strong demand.', feed_id='1',
                                  fetched_at='', content_source='', retrieval_status='')
        self.store.save_article(article, key, source_id=article_source_id)
        result = {'schema_version': schema_version, 'facts': facts, 'inferences': [], 'gaps': [], 'actions': []}
        self.store.save_analysis(key, result, {'score': 50, 'risk_flag': ''},
                                 {'source_id': source_id, 'model': 'm'})
        return article

    def backfill(self):
        from opportunity_radar.unified_main import backfill_rss
        return backfill_rss(str(self.db))

    def test_located_facts_become_linked_claims(self):
        self.save('k1', 'Retail sales rise', [
            {'ordinal': 1, 'text': 'Revenue rose 5%', 'status': 'located',
             'quote': 'Revenue rose 5%', 'actor': 'ONS',
             'locator': {'field': 'summary', 'start': 0, 'length': 15}},
            {'ordinal': 2, 'text': 'unlocatable', 'status': 'unlocated',
             'quote': '', 'locator': None}])
        report = self.backfill()
        self.assertEqual((report['claims'], report['evidences'], report['links']), (1, 1, 1))
        self.assertEqual(report['facts_skipped_unlocated'], 1)
        counts = self.uni.counts()
        self.assertEqual((counts['claims'], counts['claim_evidence']), (1, 1))

    def test_v4_records_get_an_event_but_no_invented_claim(self):
        self.save('k1', 'Old record', [], schema_version=4)
        report = self.backfill()
        self.assertEqual(report['articles_skipped_v4'], 1)
        self.assertEqual(report['claims'], 0)
        self.assertEqual(self.uni.counts()['events'], 1)

    def test_running_twice_adds_nothing(self):
        self.save('k1', 'Retail sales rise', [
            {'ordinal': 1, 'text': 'x', 'status': 'located',
             'quote': 'Revenue rose 5%', 'locator': {'field': 'summary', 'start': 0, 'length': 15}}])
        first = self.backfill()
        second = self.backfill()
        self.assertEqual(first['claims'], 1)
        self.assertEqual((second['claims'], second['evidences'], second['links']), (0, 0, 0))
        self.assertEqual(second['events_new'], 0)

    def test_every_claim_can_be_traced_back_to_its_article_and_position(self):
        self.save('k1', 'Retail sales rise', [
            {'ordinal': 1, 'text': 'x', 'status': 'located',
             'quote': 'Revenue rose 5%', 'locator': {'field': 'summary', 'start': 0, 'length': 15}}])
        self.backfill()
        with self.uni.connect() as conn:
            claim = dict(conn.execute('SELECT * FROM claims').fetchone())
            evidence = dict(conn.execute('SELECT * FROM evidences WHERE evidence_id=?',
                                         (conn.execute('SELECT evidence_id FROM claim_evidence').fetchone()[0],)).fetchone())
        self.assertEqual(claim['article_key'], 'k1')
        self.assertEqual(json.loads(claim['locator_json']), {'field': 'summary', 'start': 0, 'length': 15})
        self.assertEqual(evidence['quote'], 'Revenue rose 5%')
        self.assertEqual(evidence['source_id'], 'bbc-business')

    def test_article_source_binding_is_used_when_analysis_meta_lacks_it(self):
        self.save('k1', 'Retail sales rise', [
            {'ordinal': 1, 'text': 'x', 'status': 'located',
             'quote': 'Revenue rose 5%', 'locator': {'field': 'summary', 'start': 0, 'length': 15}}],
            source_id='', article_source_id='bbc-business')
        self.backfill()
        with self.uni.connect() as conn:
            row = conn.execute('SELECT source_id FROM evidences').fetchone()
        self.assertEqual(row['source_id'], 'bbc-business')

    def test_unknown_source_does_not_produce_evidence_or_a_claim(self):
        self.save('k1', 'Retail sales rise', [
            {'ordinal': 1, 'text': 'x', 'status': 'located',
             'quote': 'Revenue rose 5%', 'locator': {'field': 'summary', 'start': 0, 'length': 15}}],
            source_id='')
        report = self.backfill()
        self.assertEqual(report['claims'], 0)
        self.assertEqual(report['evidences'], 0)
        self.assertEqual(report['evidences_rejected'], 1)
        self.assertEqual(report['claims_rejected'], 1)
        self.assertEqual(report['links_rejected'], 1)
        self.assertEqual(self.uni.counts()['evidences'], 0)
        self.assertEqual(self.uni.counts()['claims'], 0)


if __name__ == '__main__':
    unittest.main()
