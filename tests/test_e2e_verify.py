import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import e2e_verify as e2e  # noqa: E402
from opportunity_radar.schema import CATEGORIES  # noqa: E402


def run_row(**kw):
    row = {'run_id': 1, 'status': 'dry_run', 'article_count': 2, 'analyzed_count': 2,
           'error_count': 0, 'exit_code': 0, 'stage': 'done', 'message': ''}
    row.update(kw)
    return row


def artifacts(text='subject\n\n【执行摘要】', items=None, manifest=None, files=None):
    items = [] if items is None else items
    if manifest is None:
        manifest = {
            'article_count': len(items),
            'report_hash': hashlib.sha256(text.encode('utf-8')).hexdigest()[:16],
            'stats': {'counts': {s: sum(1 for x in items if x.get('status') == s)
                                 for s in ('priority', 'watch', 'filtered')}},
        }
    return {'report_text': text, 'manifest': manifest, 'items': items,
            'files': files or {'text': True, 'html': True, 'archive': True}}


def by_code(checks):
    return {c['code']: c for c in checks}


class SuccessfulRunTests(unittest.TestCase):
    def test_successful_run_passes(self):
        items = [{'title': 'a', 'status': 'watch', 'scoring': {'status': 'watch'}}]
        checks = e2e.evaluate_run(run_row(), artifacts(items=items), [])
        self.assertTrue(e2e._all_ok(checks), [c for c in checks if not c['ok']])

    def test_no_new_content_is_not_a_failure(self):
        checks = e2e.evaluate_run(run_row(status='no_new_content', analyzed_count=0),
                                  artifacts(text='本轮没有新的分析任务，不代表没有机会。'), [])
        self.assertTrue(e2e._all_ok(checks), [c for c in checks if not c['ok']])
        self.assertEqual(e2e.outcome_of(run_row(status='no_new_content', analyzed_count=0)), 'no_new_content')


class FailureSemanticsTests(unittest.TestCase):
    def failed_run(self, **kw):
        row = run_row(status='dry_run', analyzed_count=0, error_count=2, exit_code=0)
        row.update(kw)
        return row

    def test_failed_dry_run_with_zero_exit_is_rejected(self):
        checks = by_code(e2e.evaluate_run(self.failed_run(), artifacts(), []))
        self.assertFalse(checks['failure_status']['ok'])
        self.assertFalse(checks['analysis_failed_not_success']['ok'])
        self.assertFalse(checks['failures_recorded']['ok'])
        self.assertEqual(e2e.outcome_of(self.failed_run()), 'all_analyses_failed')

    def test_analysis_failed_status_but_zero_exit_is_rejected(self):
        checks = by_code(e2e.evaluate_run(self.failed_run(status='analysis_failed'), artifacts(), []))
        self.assertFalse(checks['analysis_failed_not_success']['ok'])

    def test_failures_must_be_recorded_per_article(self):
        row = self.failed_run(status='analysis_failed', exit_code=1)
        missing = by_code(e2e.evaluate_run(row, artifacts(), None))
        self.assertFalse(missing['failures_recorded']['ok'])
        self.assertIn('table missing', missing['failures_recorded']['detail'])
        present = by_code(e2e.evaluate_run(row, artifacts(), [{'url': 'u1'}, {'url': 'u2'}]))
        self.assertTrue(present['failures_recorded']['ok'])
        partial = by_code(e2e.evaluate_run(row, artifacts(), [{'url': 'u1'}]))
        self.assertFalse(partial['failures_recorded']['ok'])

    def test_report_must_not_claim_no_new_tasks_when_analyses_failed(self):
        row = self.failed_run(status='analysis_failed', exit_code=1)
        masked = '本轮没有新增分析任务，结论沿用已有结果；不代表没有机会。'
        checks = by_code(e2e.evaluate_run(row, artifacts(text=masked), [{'url': 'u'}, {'url': 'v'}]))
        self.assertFalse(checks['report_names_the_failure']['ok'])
        explained = '本轮没有新增分析任务。本轮分析结果为空：2 篇尝试分析均未通过。'
        checks = by_code(e2e.evaluate_run(row, artifacts(text=explained), [{'url': 'u'}, {'url': 'v'}]))
        self.assertFalse(checks['report_names_the_failure']['ok'])
        honest = '本轮分析未完成，暂不形成商业判断。本轮分析结果为空：2 篇尝试分析均未通过。'
        checks = by_code(e2e.evaluate_run(row, artifacts(text=honest), [{'url': 'u'}, {'url': 'v'}]))
        self.assertTrue(checks['report_names_the_failure']['ok'])

    def test_partial_failure_with_zero_exit_is_rejected(self):
        row = run_row(status='dry_run', analyzed_count=3, error_count=1, exit_code=0)
        checks = by_code(e2e.evaluate_run(row, artifacts(items=[]), []))
        self.assertFalse(checks['failure_status']['ok'])
        self.assertNotIn('analysis_failed_not_success', checks)  # not an all-failure run

    def test_partial_failure_with_nonzero_exit_passes_that_check(self):
        row = run_row(status='partial_failed', analyzed_count=3, error_count=1, exit_code=1)
        checks = by_code(e2e.evaluate_run(row, artifacts(), []))
        self.assertTrue(checks['failure_status']['ok'])
        self.assertEqual(e2e.outcome_of(row), 'partial_failure')


class ArtifactIntegrityTests(unittest.TestCase):
    def test_report_hash_mismatch_is_detected(self):
        bad = {'article_count': 0, 'report_hash': 'deadbeefdeadbeef', 'stats': {'counts': {}}}
        checks = by_code(e2e.evaluate_run(run_row(), artifacts(manifest=bad), []))
        self.assertFalse(checks['report_hash']['ok'])

    def test_item_count_and_status_counts(self):
        items = [{'title': 'a', 'status': 'priority', 'scoring': {'status': 'priority'}}]
        bad = {'article_count': 9, 'report_hash': hashlib.sha256('subject\n\n【执行摘要】'.encode()).hexdigest()[:16],
               'stats': {'counts': {'priority': 5, 'watch': 0, 'filtered': 0}}}
        checks = by_code(e2e.evaluate_run(run_row(), artifacts(items=items, manifest=bad), []))
        self.assertFalse(checks['item_count']['ok'])
        self.assertFalse(checks['status_counts']['ok'])
        self.assertTrue(checks['scoring_matches_items']['ok'])

    def test_missing_artifacts_are_reported(self):
        checks = by_code(e2e.evaluate_run(run_row(), artifacts(files={'text': False, 'html': True, 'archive': False}), []))
        self.assertFalse(checks['artifacts']['ok'])

    def test_no_run_row_is_reported(self):
        checks = e2e.evaluate_run(None, artifacts(), None)
        self.assertEqual(len(checks), 1)
        self.assertFalse(checks[0]['ok'])


class FaultPayloadTests(unittest.TestCase):
    def test_fault_body_is_valid_json_outside_the_enum(self):
        parsed = json.loads(e2e.FAULT_BODY)
        self.assertIn(parsed['category'], {'policy_change', 'political_event'})
        self.assertNotIn(parsed['category'], CATEGORIES)


if __name__ == '__main__':
    unittest.main()
