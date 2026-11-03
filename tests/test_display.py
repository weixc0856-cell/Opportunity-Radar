"""Display tiers and the weak-signal block.

Discovery keeps weak material; these tests fix the contract that the digest still shows
it, with a reason, and that nothing here touches scoring or the publication gate.
"""
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import digest, display, render_html
from opportunity_radar.cli import build_watchlist
from opportunity_radar.store import Store
from opportunity_radar.unified import UnifiedStore


class TierTests(unittest.TestCase):
    def test_verified_claim_is_high_confidence(self):
        self.assertEqual(display.claim_tier({'verification_state': 'verified'})[0], 'L0')

    def test_located_skeleton_is_medium_confidence(self):
        tier, reason = display.claim_tier({'verification_state': 'unverifiable',
                                           'locator_json': '{"field":"summary"}',
                                           'evidence_id': 'e1'})
        self.assertEqual((tier, reason), ('L1', 'skeleton_only'))

    def test_unlocated_claim_is_a_weak_signal(self):
        self.assertEqual(display.claim_tier({'verification_state': 'unverifiable',
                                             'locator_json': '{}'}), ('L2', 'no_locator'))

    def test_signal_detected_opportunity_stays_weak_until_promoted(self):
        self.assertEqual(display.opportunity_tier({'validation_state': 'signal_detected'}),
                         ('L2', 'signal_only'))
        self.assertEqual(display.opportunity_tier({'validation_state': 'problem_supported'}),
                         ('L0', 'promoted'))

    def test_candidate_link_is_weak_and_accepted_is_medium(self):
        self.assertEqual(display.link_tier({'status': 'candidate'}), ('L2', 'candidate_link'))
        self.assertEqual(display.link_tier({'status': 'accepted'}), ('L1', 'accepted_link'))

    def test_label_carries_tier_and_reason(self):
        text = display.label('L2', 'no_claim')
        self.assertIn('L2', text)
        self.assertIn('有数字候选', text)


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'watch.sqlite3'
        self.store = Store(self.db)
        UnifiedStore(self.db)
        with self.store.connect() as conn:
            conn.execute("INSERT INTO articles(article_key,title,url,created_at,source_id) "
                         "VALUES('k1','Numbers article','https://example.invalid/1','2026-11-03','s1')")
            conn.execute("INSERT INTO events(event_id,event_key,title_norm,rules_version,created_at) "
                         "VALUES('evt-a','a','Gemini model launch','v1','2026-11-03')")
            conn.execute("INSERT INTO events(event_id,event_key,title_norm,rules_version,created_at) "
                         "VALUES('evt-b','b','Gemini model release','v1','2026-11-03')")
            conn.execute("INSERT INTO event_links(link_id,left_kind,left_key,right_kind,right_key,"
                         "relation,basis,confidence,status,created_at) "
                         "VALUES('l1','event','evt-a','event','evt-b','event_candidate',"
                         "'title_similarity',0.8,'candidate','2026-11-03')")
            for index in (1, 2):
                conn.execute("INSERT INTO opportunities(opportunity_id,canonical_key,title,"
                             "validation_state,confidence,first_seen_at,last_seen_at,"
                             "rules_version,created_at,updated_at) "
                             "VALUES(?,?,?,'signal_detected',0.2,'2026-11-03','2026-11-03',"
                             "'opp-v1','2026-11-03','2026-11-03')",
                             (f'opp-{index}', f'k{index}', f'Weak signal {index}'))
            conn.execute("INSERT INTO opportunities(opportunity_id,canonical_key,title,"
                         "validation_state,confidence,first_seen_at,last_seen_at,"
                         "rules_version,created_at,updated_at) "
                         "VALUES('opp-3','k3','Weak signal 1','signal_detected',0.2,"
                         "'2026-11-03','2026-11-03','opp-v1','2026-11-03','2026-11-03')")
            conn.execute("INSERT INTO opportunity_links(link_id,opportunity_id,target_kind,"
                         "target_key,role,support,method,confidence,created_at) "
                         "VALUES('ol1','opp-1','article','k1','seed_signal','direct','deterministic',0.5,'2026-11-03')")
        self.pipe = {'steps': {'claim_pipeline': {'result': {
            'details': [{'article_key': 'k1', 'n1_candidates': 4, 'claims': 0},
                        {'article_key': 'k2', 'n1_candidates': 3, 'claims': 2}],
            'unprocessed': 2}}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_each_weak_class(self):
        watch = build_watchlist(self.store, self.pipe, limit=8)
        self.assertEqual(watch['opportunities']['count'], 2)
        self.assertEqual(watch['opportunities']['records'], 3)
        self.assertEqual(watch['opportunities']['items'][0]['tier'], 'L2')
        self.assertEqual(watch['numeric_without_claims']['count'], 1)
        self.assertEqual(watch['numeric_without_claims']['items'][0]['candidates'], 4)
        self.assertNotIn('k2', [x['article_key'] for x in watch['numeric_without_claims']['items']])
        self.assertEqual(watch['candidate_links']['count'], 1)
        self.assertEqual(watch['candidate_links']['items'][0]['basis'], 'title_similarity')
        self.assertEqual(watch['cap_unprocessed'], 2)

    def test_text_report_shows_every_class_with_a_reason(self):
        watch = build_watchlist(self.store, self.pipe, limit=8)
        _subject, body = digest.render_digest([], {'counts': {}, 'watchlist': watch})
        self.assertIn('五、待观察信号（弱信号 / 未确认）', body)
        self.assertIn('低置信 Opportunity：2 个标题', body)
        self.assertIn('原始 3 条记录', body)
        self.assertIn('同标题 2 条', body)
        self.assertIn('有数字但未形成可核验主张：1 篇', body)
        self.assertIn('可能相关事件（未确认合并）：1 对', body)
        self.assertIn('Gemini model launch ↔ Gemini model release', body)
        self.assertIn('未经确认，不作为同一事件', body)
        self.assertIn('N0–N5 本轮上限外：2 篇', body)
        self.assertIn('六、附录', body)

    def test_text_report_truncates_and_says_how_many_are_left(self):
        watch = build_watchlist(self.store, self.pipe, limit=1)
        _subject, body = digest.render_digest([], {'counts': {}, 'watchlist': watch})
        self.assertIn('另有 1 条，见归档 JSON', body)

    def test_html_report_has_the_same_section(self):
        watch = build_watchlist(self.store, self.pipe, limit=8)
        html = render_html.render_html([], {'counts': {}, 'watchlist': watch})
        self.assertIn('待观察信号（弱信号 / 未确认）', html)
        self.assertIn('Gemini model launch', html)
        self.assertIn('signal_detected', html)

    def test_no_watchlist_keeps_the_old_appendix_number(self):
        _subject, body = digest.render_digest([], {'counts': {}})
        self.assertIn('五、附录', body)
        self.assertNotIn('待观察信号', body)


if __name__ == '__main__':
    unittest.main()
