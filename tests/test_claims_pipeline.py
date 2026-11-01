"""The v7 output has to survive the production path unchanged.

parse_model_json validates the v5 sections; the claims array is extra data it must carry
through rather than drop, and a malformed claim must cost one claim, not the article.
"""
import json
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import claim_contract, schema
from opportunity_radar.store import Store

ARTICLE = {'title': 'Industrial output rises 3.2%', 'summary': 'Industrial output rose 3.2 percent from a year earlier.',
           'url': 'https://example.org/a', 'published': '2026-11-01T00:00:00+00:00'}

BASE = {
    'category': 'market_change', 'summary_zh': '产出上升', 'pain_point': 'unknown',
    'target_customer': 'unknown', 'commercial_signal': 'unknown', 'revenue_claim': 'none',
    'confidence': 'low', 'relevance': 'adjacent', 'actionability': 'monitor',
    'facts': [{'text': 'output rose', 'quote': 'Industrial output rose 3.2 percent', 'actor': 'office'}],
    'inferences': [], 'gaps': [], 'actions': [{'step': 'check the release', 'kind': 'verify_fact', 'done_when': 'done'}],
}

CLAIM = {'subject': 'industrial output', 'predicate': 'growth', 'value_num': 3.2, 'unit': '%',
         'period': '2026-09', 'comparison': 'year_over_year', 'kind': 'fact',
         'quote': 'Industrial output rose 3.2 percent'}


class ParserCarriesClaimsTests(unittest.TestCase):
    def test_claims_survive_the_v5_parser(self):
        payload = dict(BASE, claims=[CLAIM])
        parsed = schema.parse_model_json(json.dumps(payload), ARTICLE)
        self.assertEqual(parsed['schema_version'], 5)
        self.assertEqual(len(parsed['claims']), 1)
        self.assertEqual(parsed['claims'][0]['value_num'], 3.2)

    def test_a_response_without_claims_still_parses(self):
        parsed = schema.parse_model_json(json.dumps(BASE), ARTICLE)
        self.assertNotIn('claims', parsed)

    def test_a_malformed_claim_does_not_fail_the_article(self):
        payload = dict(BASE, claims=[CLAIM, {'subject': '', 'predicate': 'x'}, 'not an object'])
        parsed = schema.parse_model_json(json.dumps(payload), ARTICLE)
        claims, deviations = claim_contract.parse_claims({'claims': parsed['claims']})
        self.assertEqual(len(claims), 1)
        self.assertTrue(any(d.get('reason') == 'claim_without_subject_or_predicate' for d in deviations))

    def test_an_empty_claims_list_is_valid(self):
        parsed = schema.parse_model_json(json.dumps(dict(BASE, claims=[])), ARTICLE)
        claims, deviations = claim_contract.parse_claims({'claims': parsed['claims']})
        self.assertEqual((claims, deviations), ([], []))


class StorageTests(unittest.TestCase):
    def test_an_analysis_with_claims_is_stored_like_any_other(self):
        parsed = schema.parse_model_json(json.dumps(dict(BASE, claims=[CLAIM])), ARTICLE)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(str(Path(tmp) / 'db.sqlite3'))
            store.save_analysis('k1', parsed, {'score': 60, 'risk_flag': ''}, {'model': 'm'})
            with store.connect() as conn:
                raw = conn.execute("SELECT result_json FROM analyses WHERE article_key='k1'").fetchone()[0]
            self.assertEqual(len(json.loads(raw)['analysis']['claims']), 1)
            sections = store.analysis_sections('k1')
        self.assertTrue(sections)
        kinds = {s['kind'] for s in sections}
        self.assertIn('fact', kinds)

    def test_a_fact_quote_that_cannot_be_located_stays_unlocated(self):
        payload = dict(BASE, facts=[{'text': 'x', 'quote': 'not in the text at all', 'actor': ''}])
        parsed = schema.parse_model_json(json.dumps(payload), ARTICLE)
        self.assertEqual(parsed['facts'][0]['status'], 'unlocated')


if __name__ == '__main__':
    unittest.main()
