import unittest

from opportunity_radar import publication
from opportunity_radar.publication import PASS, HOLD, PASS_WITH_LIMITATIONS


class ThresholdTests(unittest.TestCase):
    def test_coverage_is_analysed_over_queued(self):
        self.assertEqual(publication.coverage(8, 10), 0.8)
        self.assertEqual(publication.coverage(0, 4), 0.0)

    def test_a_run_with_nothing_to_analyse_is_complete(self):
        # A quiet day is a complete run: coverage must not turn it into a hold.
        self.assertEqual(publication.coverage(0, 0), 1.0)
        self.assertEqual(publication.decide(0, 0), PASS)

    def test_thresholds_are_inclusive_at_the_lower_edge(self):
        self.assertEqual(publication.decide(8, 10), PASS)
        self.assertEqual(publication.decide(7, 10), PASS_WITH_LIMITATIONS)
        self.assertEqual(publication.decide(5, 10), PASS_WITH_LIMITATIONS)
        self.assertEqual(publication.decide(4, 10), HOLD)

    def test_integrity_fault_holds_at_full_coverage(self):
        self.assertEqual(publication.decide(10, 10, integrity_fault=True), HOLD)

    def test_custom_thresholds_are_honoured(self):
        self.assertEqual(publication.decide(9, 10, min_coverage=0.95), PASS_WITH_LIMITATIONS)
        self.assertEqual(publication.decide(6, 10, hold_below=0.7), HOLD)

    def test_only_pass_statuses_may_be_sent(self):
        self.assertTrue(publication.publishable(PASS))
        self.assertTrue(publication.publishable(PASS_WITH_LIMITATIONS))
        self.assertFalse(publication.publishable(HOLD))


class DisclosureTests(unittest.TestCase):
    def test_complete_run_discloses_nothing(self):
        self.assertEqual(publication.headline_notice({'coverage': 1.0}), '')
        self.assertIsNone(publication.disclosure({'coverage': 1.0}))
        self.assertIsNone(publication.disclosure({}))

    def test_partial_run_states_counts_and_causes(self):
        text = publication.disclosure({
            'coverage': 0.2, 'analyzed': 2, 'queued': 10, 'failed': 7, 'not_attempted': 1,
            'failed_causes': {'connect_refused': 6, 'http_5xx': 1}, 'publication_status': HOLD})
        self.assertIn('20%', text)
        self.assertIn('成功 2/10', text)
        self.assertIn('失败 7 篇', text)
        self.assertIn('未尝试 1 篇', text)
        self.assertIn('连接被拒绝 6', text)
        self.assertIn('HOLD', text)

    def test_headline_notice_is_short_and_names_the_gap(self):
        notice = publication.headline_notice({'coverage': 0.5, 'analyzed': 3, 'queued': 6})
        self.assertIn('未完整完成', notice)
        self.assertIn('3/6', notice)


class CauseTests(unittest.TestCase):
    def test_blocking_causes_are_recognised(self):
        self.assertTrue(publication.blocking({'integrity': 1}))
        self.assertFalse(publication.blocking({'connect_refused': 9}))
        self.assertFalse(publication.blocking({'integrity': 0}))

    def test_cause_text_is_deterministic_and_named(self):
        text = publication.cause_text({'http_5xx': 1, 'connect_refused': 2})
        self.assertLess(text.index('连接被拒绝'), text.index('服务端错误'))
        self.assertEqual(publication.cause_text({}), '无')
        self.assertEqual(publication.cause_text({'not_a_real_cause': 3}), 'not_a_real_cause 3')


if __name__ == '__main__':
    unittest.main()
