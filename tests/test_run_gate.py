"""R0 gate, exercised through cli.main() rather than through its helpers.

Only the outside world is replaced: FreshRSS, the model, SMTP and the source registry.
Everything the gate touches is real - the store, the migration, the scorer, the digest,
the report writer and the run record - so a passing test here means the run really did
record what it claims to have recorded.
"""
import dataclasses
import logging
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from opportunity_radar.analyzer import ModelCallError
from opportunity_radar.cli import main
from opportunity_radar.config import Settings
from opportunity_radar.store import Store
from opportunity_radar.source_policy import Source

SOURCE = Source('s1', 'Test Source', 'https://example.org', 'https://example.org/feed', 'rss',
                'approved', True, '1', content_access_level='full_text', source_cap=0)

ANALYSIS = {'category': 'market_change', 'summary_zh': '摘要', 'pain_point': 'p', 'target_customer': 'c',
            'commercial_signal': 'none', 'revenue_claim': 'none', 'evidence_quotes': [],
            'uncertainties': [], 'suggested_next_step': 's', 'relevance_score': 55, 'confidence': 'low',
            'actionability': 'monitor'}


def article(i):
    return SimpleNamespace(article_id=str(i), title=f'Article {i}', url=f'https://example.org/{i}',
                           summary=f'Body text for article {i}. ' * 6, source_name='Test Source',
                           published='2026-11-01T00:00:00+00:00', feed_id='1',
                           fetched_at='', content_source='', retrieval_status='')


def settings_for(tmp):
    env = {'OR_DB_PATH': str(tmp / 'run.sqlite3'), 'OR_REPORT_DIR': str(tmp / 'reports'),
           'OR_LOG_PATH': str(tmp / 'run.log'), 'OR_FRESHRSS_USERNAME': 'u',
           'OR_FRESHRSS_API_KEY': 'k', 'OR_LLM_MODEL': 'm', 'OR_SMTP_HOST': '127.0.0.1',
           'OR_SMTP_PORT': '2525', 'OR_EMAIL_FROM': 'qa@example.invalid',
           'OR_EMAIL_TO': 'qa@example.invalid', 'OR_MAX_ARTICLES': '10',
           'OR_MODEL_AUTOSTART': '0'}
    with mock.patch.dict(os.environ, env, clear=False):
        base = Settings.from_env()
    return dataclasses.replace(base, db_path=env['OR_DB_PATH'], report_dir=env['OR_REPORT_DIR'],
                               log_path=env['OR_LOG_PATH'], max_articles=10,
                               alert_after_failures=1)


def behaviour_of(table):
    """table maps article index -> analysis dict or exception."""
    def behaviour(i):
        value = table.get(i, ANALYSIS)
        return value
    return behaviour


class FakeAnalyzer:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    def analyze(self, title, summary, source_name, url, trace=None, published=''):
        self.calls += 1
        result = self.behaviour(int(url.rsplit('/', 1)[-1]))
        if isinstance(result, BaseException):
            raise result
        return dict(result)


class GateRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='or-gate-'))
        self.settings = settings_for(self.tmp)
        Store(str(self.tmp / 'run.sqlite3'))
        logging.disable(logging.CRITICAL)   # the run logs its own failures on purpose
        # The unified pipeline is an external-model step; the gate tests isolate it.
        self._pipeline_env = mock.patch.dict(os.environ, {'OR_PIPELINE_ENABLED': '0'})
        self._pipeline_env.start()

    def tearDown(self):
        self._pipeline_env.stop()
        logging.disable(logging.NOTSET)

    def _run(self, behaviour, articles=None, ensure=(True, 'ok'), health=True, argv=None):
        articles = articles if articles is not None else [article(i) for i in range(1, 6)]
        sent = []

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def fetch_articles(self, limit, feed_ids=None):
                return articles

        def fake_send(host, port, user, pwd, sender, to, subject, body, starttls, html=None, security=''):
            sent.append({'to': list(to), 'subject': subject, 'body': body, 'html': html})
            return [{'ok': True, 'recipient': r} for r in to]

        with mock.patch('opportunity_radar.cli.Settings.from_env', return_value=self.settings), \
             mock.patch('opportunity_radar.cli.ensure_model', return_value=ensure), \
             mock.patch('opportunity_radar.cli.load_sources', return_value=[SOURCE]), \
             mock.patch('opportunity_radar.cli.audit_sources', return_value=[]), \
             mock.patch('opportunity_radar.cli.FreshRSSClient', FakeClient), \
             mock.patch('opportunity_radar.cli.apply_article_bodies', return_value=0), \
             mock.patch('opportunity_radar.analyzer.LocalAnalyzer', lambda *a, **k: FakeAnalyzer(behaviour)), \
             mock.patch('opportunity_radar.cli.parse_recipients', return_value=['qa@example.invalid']), \
             mock.patch('opportunity_radar.cli.send_email_detailed', fake_send), \
             mock.patch('opportunity_radar.cli.health_ok', return_value=health):
            code = main(argv or [])
        return code, sent

    def _run_row(self):
        conn = sqlite3.connect(str(self.tmp / 'run.sqlite3'))
        conn.row_factory = sqlite3.Row
        try:
            return dict(conn.execute('SELECT * FROM runs ORDER BY run_id DESC LIMIT 1').fetchone())
        finally:
            conn.close()

    def _failures(self):
        conn = sqlite3.connect(str(self.tmp / 'run.sqlite3'))
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute('SELECT * FROM analysis_failures ORDER BY failure_id')]
        finally:
            conn.close()

    # ---------------------------------------------------------------- coverage bands
    def test_a_clean_run_passes_and_sends(self):
        code, sent = self._run(behaviour_of({}))
        row = self._run_row()
        self.assertEqual(code, 0)
        self.assertEqual(row['publication_status'], 'PASS')
        self.assertEqual(row['coverage'], 1.0)
        self.assertEqual(len(sent), 1)
        self.assertNotIn('运行完整性', sent[0]['body'])

    def test_sixty_percent_coverage_publishes_with_limitations(self):
        table = {4: ModelCallError('http_5xx', 'boom'), 5: ModelCallError('http_5xx', 'boom')}
        code, sent = self._run(behaviour_of(table))
        row = self._run_row()
        self.assertEqual(row['publication_status'], 'PASS_WITH_LIMITATIONS')
        self.assertAlmostEqual(row['coverage'], 0.6)
        self.assertEqual(code, 1)                    # failures are still reported as failures
        self.assertEqual(len(sent), 1)               # but the issue may still go out
        self.assertIn('覆盖率 60%', sent[0]['body'])
        self.assertIn('运行完整性', sent[0]['body'])
        self.assertIn('覆盖率', sent[0]['html'])

    def test_forty_percent_coverage_is_held_and_not_sent(self):
        table = {3: ModelCallError('http_5xx', 'boom'), 4: ModelCallError('http_5xx', 'boom'),
                 5: ModelCallError('http_5xx', 'boom')}
        code, sent = self._run(behaviour_of(table))
        row = self._run_row()
        self.assertEqual(row['publication_status'], 'HOLD')
        self.assertAlmostEqual(row['coverage'], 0.4)
        self.assertEqual(sent, [])
        self.assertEqual(code, 1)
        self.assertTrue((self.tmp / 'reports' / 'latest-digest.txt').exists())
        self.assertTrue(any((self.tmp / 'reports' / 'archive').rglob('*.html')))

    def test_every_analysis_failing_is_held(self):
        table = {i: ModelCallError('connect_refused', 'dead') for i in range(1, 6)}
        code, sent = self._run(behaviour_of(table))
        row = self._run_row()
        self.assertEqual(row['publication_status'], 'HOLD')
        self.assertEqual(row['coverage'], 0.0)
        self.assertEqual(row['status'], 'analysis_failed')
        self.assertEqual(sent, [])
        self.assertEqual(code, 1)
        # Three consecutive transport failures trip the breaker; the last two are never tried.
        self.assertEqual(row['not_attempted'], 2)
        self.assertEqual(Store_causes(row), {'connect_refused': 3, 'circuit_open': 2})

    def test_failure_rows_carry_cause_and_attempts(self):
        table = {1: ModelCallError('connect_refused', 'dead', attempts=4)}
        self._run(behaviour_of(table))
        rows = self._failures()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['cause'], rows[0]['attempts']), ('connect_refused', 4))

    # ---------------------------------------------------------------- circuit breaker
    def test_a_dead_model_trips_the_breaker_and_the_rest_are_not_attempted(self):
        table = {1: ModelCallError('connect_refused', 'dead')}
        code, sent = self._run(behaviour_of(table), health=False)
        row = self._run_row()
        self.assertEqual(row['not_attempted'], 4)
        self.assertEqual(row['publication_status'], 'HOLD')
        self.assertEqual(sent, [])
        causes = Store_causes(row)
        self.assertEqual(causes, {'connect_refused': 1, 'circuit_open': 4})
        unattempted = [r for r in self._failures() if r['cause'] == 'circuit_open']
        self.assertEqual(len(unattempted), 4)
        self.assertTrue(all(r['attempts'] == 0 for r in unattempted))

    def test_repeated_transport_failures_trip_the_breaker_even_if_health_answers(self):
        table = {i: ModelCallError('connect_reset', 'r') for i in range(1, 6)}
        self._run(behaviour_of(table), health=True)
        row = self._run_row()
        self.assertEqual(row['not_attempted'], 2)   # 3 failures trip it, 2 never attempted
        causes = Store_causes(row)
        self.assertEqual(causes, {'connect_reset': 3, 'circuit_open': 2})

    # ---------------------------------------------------------------- model unavailable
    def test_a_dead_model_at_startup_is_recorded_as_a_held_run(self):
        code, sent = self._run(behaviour_of({}), ensure=(False, 'model is not reachable'))
        row = self._run_row()
        self.assertEqual(code, 3)
        self.assertEqual(sent, [])
        self.assertEqual(row['publication_status'], 'HOLD')
        self.assertEqual(Store_causes(row), {'model_unavailable': 1})

    # ---------------------------------------------------------------- no bypass
    def test_a_held_run_never_reaches_the_mailer_even_with_email_on_empty(self):
        table = {i: ModelCallError('connect_refused', 'dead') for i in range(1, 6)}
        settings = dataclasses.replace(self.settings, email_on_empty=True)
        self.settings = settings
        code, sent = self._run(behaviour_of(table))
        self.assertEqual(sent, [])
        self.assertEqual(code, 1)


def Store_causes(row):
    import json
    return json.loads(row.get('failed_causes') or '{}')


if __name__ == '__main__':
    unittest.main()
