"""Batch 4: the digest shows events, not one card per article.

The rendering rules matter because they decide what a reader sees: two reports of one
event must read as one item with the other reports listed, and the source counts must be
the ones the R1 tables can actually support.
"""
import json
import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from opportunity_radar import cli
from opportunity_radar.digest import event_summary_lines, group_by_event, render_digest
from opportunity_radar.render_html import render_html
from opportunity_radar.store import Store
from opportunity_radar.unified import UnifiedStore


def item(title, score, url=None, event=None, lane='A', status='priority'):
    return {'title': title, 'url': url or 'https://example.org/' + title, 'source_name': 'Src',
            'score': score, 'status': status, 'lane': lane, 'analysis': {},
            'classification': {}, 'evidence_state': 'rss_excerpt_only', 'event': event or {}}


def event_block(**kw):
    base = {'event_id': 'evt-1', 'members': [{'title': 'A', 'url': 'https://example.org/a', 'source_name': 'BBC'}],
            'sources': ['bbc-business'], 'source_families': ['bbc'], 'independent_corroboration': False,
            'candidate_links': 0}
    base.update(kw)
    return base


class GroupingTests(unittest.TestCase):
    def test_one_card_per_event(self):
        same = event_block(event_id='evt-1')
        reps, siblings = group_by_event([
            item('Story A', 70, url='https://example.org/a', event=same),
            item('Story A (second outlet)', 50, url='https://example.org/b', event=same),
            item('Unrelated', 60, url='https://example.org/c', event=event_block(event_id='evt-2'))])
        self.assertEqual([x['title'] for x in reps], ['Story A', 'Unrelated'])
        self.assertEqual([x['title'] for x in siblings['evt-1']], ['Story A (second outlet)'])

    def test_the_best_scoring_report_represents_the_event(self):
        same = event_block(event_id='evt-1')
        reps, _ = group_by_event([item('Low', 40, url='https://example.org/1', event=same),
                                  item('High', 90, url='https://example.org/2', event=same)])
        self.assertEqual(reps[0]['title'], 'High')

    def test_items_without_an_event_stay_separate(self):
        reps, siblings = group_by_event([item('One', 10), item('Two', 20)])
        self.assertEqual(len(reps), 2)
        self.assertEqual(siblings, {})


class SummaryLineTests(unittest.TestCase):
    def test_a_single_article_event_adds_no_noise(self):
        self.assertEqual(event_summary_lines(item('A', 50, event=event_block())), [])

    def test_a_second_report_is_named(self):
        block = event_block(members=[{'title': 'A', 'url': 'https://example.org/a', 'source_name': 'BBC'},
                                     {'title': 'B', 'url': 'https://example.org/b', 'source_name': 'NYT'}],
                            sources=['bbc-business', 'nyt-business'],
                            source_families=['bbc', 'nyt'], independent_corroboration=True)
        lines = event_summary_lines(item('A', 50, url='https://example.org/a', event=block))
        joined = ' '.join(lines)
        self.assertIn('同事件报道 2 篇', joined)
        self.assertIn('来源族 2 个', joined)
        self.assertIn('独立佐证：是', joined)
        self.assertIn('NYT', joined)

    def test_independent_units_are_not_the_article_count(self):
        block = event_block(members=[{'title': 'A', 'url': 'https://example.org/a', 'source_name': 'BBC'},
                                     {'title': 'B', 'url': 'https://example.org/b', 'source_name': 'NYT'}],
                            sources=['bbc-business', 'nyt-business'],
                            source_families=['bbc', 'nyt'], independent_source_units=2,
                            independent_corroboration=True)
        text = ' '.join(event_summary_lines(item('A', 50, event=block)))
        self.assertIn('同事件报道 2 篇', text)
        self.assertIn('独立来源单元 2 个', text)
        self.assertIn('独立佐证：是', text)

    def test_an_evidence_backed_event_is_labeled_without_overclaiming(self):
        block = event_block(evidence_status='EVIDENCE_BACKED')
        text = ' '.join(event_summary_lines(item('A', 50, event=block)))
        self.assertIn('证据状态：有证据', text)
        self.assertIn('不等于主张已核验', text)

    def test_an_insufficient_evidence_event_is_labeled_explicitly(self):
        block = event_block(evidence_status='INSUFFICIENT_EVIDENCE')
        text = ' '.join(event_summary_lines(item('A', 50, event=block)))
        self.assertIn('证据状态：证据不足', text)
        self.assertIn('不能作为已核实事实', text)

    def test_an_event_without_evidence_is_not_presented_as_verified(self):
        block = event_block(evidence_status='NO_EVIDENCE')
        text = ' '.join(event_summary_lines(item('A', 50, event=block)))
        self.assertIn('证据状态：无证据', text)
        self.assertIn('仅线索', text)
        self.assertIn('不作为已核实事实', text)
        html = render_html([item('A', 50, event=block)],
                           {'counts': {'priority': 0, 'watch': 0, 'filtered': 0}}, '2026-11-01')
        self.assertIn('证据状态：无证据', html)
        self.assertIn('仅线索', html)

    def test_candidates_are_labelled_as_candidates(self):
        block = event_block(candidate_links=3, link_items=[link(link_id=f'lnk-{i}') for i in range(3)])
        text = ' '.join(event_summary_lines(item('A', 50, event=block)))
        self.assertIn('候选关联：3 条', text)
        self.assertIn('未经确认', text)


class ReportTests(unittest.TestCase):
    def test_the_text_report_prints_the_event_once(self):
        block = event_block(members=[{'title': 'A', 'url': 'https://example.org/a', 'source_name': 'BBC'},
                                     {'title': 'B', 'url': 'https://example.org/b', 'source_name': 'NYT'}],
                            source_families=['bbc', 'nyt'], independent_corroboration=True)
        items = [item('A', 80, url='https://example.org/a', event=block),
                 item('B', 60, url='https://example.org/b', event=block)]
        stats = {'fetched': 2, 'queued': 2, 'analyzed': 2,
                 'counts': {'priority': 2, 'watch': 0, 'filtered': 0}, 'lane_weights': {}, 'lane_thresholds': {}}
        _, body = render_digest(items, stats, '2026-11-01')
        self.assertEqual(body.count('[80/100] A'), 1)
        self.assertNotIn('[60/100] B', body)
        self.assertIn('同事件其他报道', body)
        html = render_html(items, stats, '2026-11-01')
        self.assertEqual(html.count('打开原文'), 1)
        self.assertIn('事件结构', html)


class AttachTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='or-event-view-'))
        self.db = self.dir / 'db.sqlite3'
        self.store = Store(str(self.db))
        UnifiedStore(str(self.db))

    def test_articles_of_one_event_share_its_context(self):
        articles = [('k1', 'Same headline', 'https://example.org/1', '2026-10-29T08:00:00+00:00'),
                    ('k2', 'Same headline', 'https://example.org/2', '2026-10-29T09:00:00+00:00')]
        for _, title, url, published in articles:
            # Production keys articles by URL hash; the event join relies on that.
            self.store.save_article(SimpleNamespace(article_id='x', title=title, url=url, published=published,
                                                    source_name='Src', summary='body', feed_id='1',
                                                    fetched_at='', content_source='', retrieval_status=''),
                                    Store.key(url))
        items = [{'url': url, 'title': title, 'published': published, 'source_id': 'bbc-business'}
                 for _, title, url, published in articles]
        grouped = cli.attach_event_context(self.store, items, write=True)
        self.assertEqual(grouped, 2)
        self.assertEqual(items[0]['event']['event_id'], items[1]['event']['event_id'])
        self.assertEqual(len(items[0]['event']['members']), 2)
        self.assertIn('source_families', items[0]['event'])
        self.assertEqual(items[0]['event_context']['status'], 'AVAILABLE')

    def test_a_failure_never_stops_the_digest(self):
        logging.disable(logging.CRITICAL)   # the failure is logged on purpose
        self.addCleanup(logging.disable, logging.NOTSET)
        items = [{'url': 'https://example.org/x', 'title': 'x'}]
        with mock.patch('opportunity_radar.unified.UnifiedStore', side_effect=RuntimeError('boom')):
            self.assertEqual(cli.attach_event_context(self.store, items, write=True), 0)
        self.assertNotIn('event', items[0])
        self.assertEqual(items[0]['event_context']['status'], 'READ_FAILED')

    def test_no_evidence_event_does_not_label_article_facts_as_event_facts(self):
        block = event_block(evidence_status='NO_EVIDENCE')
        it = item('A', 80, event=block)
        it['analysis'] = {'schema_version': 5,
                          'facts': [{'status': 'located', 'text': 'article fact', 'quote': 'article fact',
                                     'evidence_id': 'e1', 'actor': '', 'source_url': ''}],
                          'inferences': [{'status': 'supported', 'text': 'article inference',
                                          'basis': [1], 'confidence': 'low'}],
                          'gaps': [], 'actions': []}
        stats = {'counts': {'priority': 1, 'watch': 0, 'filtered': 0}}
        _, body = render_digest([it], stats, '2026-11-01')
        html = render_html([it], stats, '2026-11-01')
        self.assertIn('文章内可定位文本（不代表事件已核实）', body)
        self.assertIn('article fact', body)
        self.assertIn('article inference', body)
        self.assertNotIn('   事实（可在原文定位）', body)
        self.assertIn('文章内可定位文本（不代表事件已核实）', html)
        self.assertIn('article inference', html)

    def test_event_context_unavailable_is_explicit_in_text_html_and_json(self):
        it = item('A', 80)
        it['event_context'] = {'status': 'SCHEMA_UNSUPPORTED', 'reason': 'no such table'}
        stats = {'counts': {'priority': 1, 'watch': 0, 'filtered': 0}}
        subject, body = render_digest([it], stats, '2026-11-01')
        html = render_html([it], stats, '2026-11-01')
        self.assertIn('事件上下文不可用（schema 不支持）', body)
        self.assertIn('不是事件级核验结论', body)
        self.assertIn('事件上下文不可用（schema 不支持）', html)
        cli._write(str(self.dir / 'reports'), subject, body, html, items=[it], stats=stats)
        archived = next((self.dir / 'reports' / 'archive').rglob('*.items.json'))
        payload = json.loads(archived.read_text(encoding='utf-8'))
        self.assertEqual(payload['items'][0]['event_context']['status'], 'SCHEMA_UNSUPPORTED')
        self.assertFalse(payload['items'][0].get('event'))

    def test_event_evidence_status_is_preserved_in_json_archive(self):
        block = event_block(evidence_status='NO_EVIDENCE')
        it = item('A', 80, event=block)
        stats = {'counts': {'priority': 1, 'watch': 0, 'filtered': 0}}
        subject, body = render_digest([it], stats, '2026-11-01')
        html = render_html([it], stats, '2026-11-01')
        cli._write(str(self.dir / 'reports'), subject, body, html,
                   items=[it], stats=stats)
        archived = next((self.dir / 'reports' / 'archive').rglob('*.items.json'))
        payload = json.loads(archived.read_text(encoding='utf-8'))
        self.assertEqual(payload['items'][0]['event']['evidence_status'], 'NO_EVIDENCE')

    def test_a_missing_database_is_marked_unavailable_not_no_evidence(self):
        items = [{'url': 'https://example.org/x', 'title': 'x'}]
        missing = Store(str(self.dir / 'missing.sqlite3'), read_only=True)
        self.assertEqual(cli.attach_event_context(missing, items, write=False), 0)
        self.assertEqual(items[0]['event_context']['status'], 'UNAVAILABLE')

    def test_missing_event_tables_degrade_as_schema_unsupported(self):
        bare = self.dir / 'bare.sqlite3'
        with sqlite3.connect(bare) as conn:
            conn.execute('CREATE TABLE articles(article_key TEXT PRIMARY KEY, title TEXT, url TEXT, '
                         'published TEXT, source_name TEXT)')
        bare_store = Store(str(bare), read_only=True)
        items = [{'url': 'https://example.org/x', 'title': 'x'}]
        self.assertEqual(cli.attach_event_context(bare_store, items, write=False), 0)
        self.assertEqual(items[0]['event_context']['status'], 'SCHEMA_UNSUPPORTED')

    def test_render_only_lookups_do_not_create_events(self):
        from opportunity_radar.unified import UnifiedStore
        UnifiedStore(str(self.db))          # tables exist but are empty
        items = [{'url': 'https://example.org/unknown', 'title': 'unknown'}]
        self.assertEqual(cli.attach_event_context(self.store, items, write=False), 0)
        self.assertEqual(items[0]['event_context']['status'], 'NOT_FOUND')
        with UnifiedStore(str(self.db)).connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)



def claim(**kw):
    base = {'claim_id': 'cl-1', 'article_key': 'k1', 'subject': 'ONS', 'predicate': 'assertion',
            'value_text': 'Retail sales rose 1.2% in September', 'kind': 'fact',
            'verification_state': 'unverified', 'extractor': 'skeleton',
            'locator_json': '{"field": "summary", "start": 3, "length": 20}',
            'evidence_id': 'ev-1', 'evidence_source_id': 'bbc-business'}
    base.update(kw)
    return base


def link(**kw):
    base = {'link_id': 'lnk-1', 'left_kind': 'claim', 'left_key': 'cl-1', 'right_kind': 'event',
            'right_key': 'evt-1', 'relation': 'same_subject', 'basis': 'entity_period_window',
            'status': 'candidate', 'confidence': 0.6}
    base.update(kw)
    return base


class ClaimDisplayTests(unittest.TestCase):
    def lines(self, block):
        return ' '.join(event_summary_lines(item('A', 50, event=block)))

    def test_a_claim_is_shown_with_its_evidence_and_position(self):
        block = event_block(claim_items=[claim()])
        text = self.lines(block)
        self.assertIn('事实主张：1 条', text)
        self.assertIn('事实·未核验', text)
        self.assertIn('Retail sales rose', text)
        self.assertIn('证据 ev-1', text)
        self.assertIn('summary@3-23', text)
        self.assertIn('bbc-business', text)

    def test_a_claim_is_never_called_confirmed(self):
        block = event_block(claim_items=[claim()])
        text = self.lines(block)
        self.assertNotIn('已核验', text.replace('未核验', ''))

    def test_kinds_are_labelled(self):
        block = event_block(claim_items=[claim(kind='system_inference', verification_state='unverified')])
        self.assertIn('系统推断·未核验', self.lines(block))

    def test_only_the_first_claims_are_printed(self):
        block = event_block(claim_items=[claim(claim_id=f'cl-{i}') for i in range(6)])
        self.assertIn('另有 4 条主张', self.lines(block))

    def test_candidate_links_are_labelled_as_unconfirmed(self):
        block = event_block(link_items=[link()], candidate_links=1)
        text = self.lines(block)
        self.assertIn('候选关联：1 条', text)
        self.assertIn('未经确认', text)
        self.assertIn('candidate', text)

    def test_an_accepted_link_still_reports_its_status(self):
        block = event_block(link_items=[link(status='accepted')], candidate_links=1)
        self.assertIn('accepted', self.lines(block))

    def test_an_event_with_only_claims_still_gets_a_block(self):
        self.assertTrue(event_summary_lines(item('A', 50, event=event_block(claim_items=[claim()]))))



if __name__ == '__main__':
    unittest.main()