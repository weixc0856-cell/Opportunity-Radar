"""Contract tests for the v5 structured analysis record.

These tests define the interface the parser must provide. They are expected to fail
before the implementation lands: `parse_model_json` currently accepts one argument and
knows nothing about facts, inference basis or located quotes.

Business rule under test: derived evidence_quotes contain ONLY located fact quotes.
An unlocated quote never contributes evidence; if every fact is unlocated the derived
list is empty and the item falls to E0 through the existing evidence gate.
"""
import json
import unittest

from opportunity_radar.schema import parse_model_json
from opportunity_radar.scoring import _relevance, score_article

ARTICLE = {
    'title': 'Retail sales, Great Britain: September 2026',
    'summary': ('Statistics published today. Retail sales volumes are estimated to have risen by 0.5% '
                'in September 2026. Volumes remain below their pre-pandemic level.'),
    'url': 'https://example.invalid/retail',
    'published': '2026-10-23T09:30:00+00:00',
}
QUOTE_OK = 'Retail sales volumes are estimated to have risen by 0.5% in September 2026.'
QUOTE_OK_2 = 'Volumes remain below their pre-pandemic level.'
QUOTE_HALLUCINATED = 'Retail sales volumes rose by 4.2% in September 2026.'


def payload(**overrides):
    data = {
        'category': 'market_change',
        'summary_zh': '英国 9 月零售销售环比回升，但材料没有说明驱动因素。',
        'relevance': 'core',
        'confidence': 'medium',
        'revenue_claim': 'none',
        'actionability': 'investigate',
        'facts': [
            {'text': '英国 2026 年 9 月零售销售量环比上升。', 'quote': QUOTE_OK, 'actor': 'UK ONS'},
            {'text': '零售销售仍低于疫情前水平。', 'quote': QUOTE_OK_2, 'actor': 'UK ONS'},
        ],
        'inferences': [
            {'text': '消费需求可能在第三季度末回暖。', 'basis': [1], 'confidence': 'low',
             'assumptions': ['单月数据能代表趋势']},
        ],
        'gaps': [
            {'missing': '分品类与分地区的零售销售明细', 'why_it_matters': '决定回暖是否普遍',
             'how_to_close': '查 ONS 配套数据表'},
        ],
        'actions': [
            {'step': '调取 ONS 原始数据表，核对分品类贡献', 'kind': 'verify_fact',
             'done_when': '确认至少三个品类的变化'},
        ],
        'pain_point': 'unknown',
        'target_customer': 'unknown',
        'commercial_signal': '零售回暖可能带动相关服务需求，但没有采购或付费证据。',
    }
    data.update(overrides)
    return data


def parse(data, article=ARTICLE):
    return parse_model_json(json.dumps(data, ensure_ascii=False), article)


def normalize(text):
    return ' '.join(str(text).lower().split())


class PerfectV5ParseTests(unittest.TestCase):
    def test_v5_parses_and_locates_each_fact_with_offsets(self):
        analysis = parse(payload())
        self.assertEqual(analysis['schema_version'], 5)
        facts = analysis['facts']
        self.assertEqual([f['status'] for f in facts], ['located', 'located'])
        self.assertEqual([f['evidence_id'] for f in facts], ['e1', 'e2'])
        self.assertEqual(analysis['evidence_quotes'], [QUOTE_OK, QUOTE_OK_2])
        self.assertEqual(analysis['uncertainties'], ['分品类与分地区的零售销售明细'])
        self.assertEqual(analysis['suggested_next_step'], '调取 ONS 原始数据表，核对分品类贡献')
        self.assertEqual(analysis['schema_deviations'], [])
        self.assertNotIn('relevance_score', analysis)

    def test_locator_start_and_length_point_at_the_quote(self):
        analysis = parse(payload())
        locator = analysis['facts'][0]['locator']
        summary = normalize(ARTICLE['summary'])
        quote = normalize(QUOTE_OK)
        self.assertEqual(locator['field'], 'summary')
        self.assertEqual(locator['length'], len(quote))
        self.assertGreater(locator['start'], 0)
        self.assertEqual(summary[locator['start']:locator['start'] + locator['length']], quote)

    def test_facts_carry_the_program_bound_source_not_a_model_url(self):
        analysis = parse(payload())
        fact = analysis['facts'][0]
        self.assertEqual(fact['source_url'], ARTICLE['url'])
        self.assertEqual(fact['published'], ARTICLE['published'])

    def test_supported_inference_cites_a_located_fact(self):
        analysis = parse(payload())
        self.assertEqual(analysis['inferences'][0]['status'], 'supported')
        self.assertEqual(analysis['inferences'][0]['basis'], [1])


class HallucinationPenaltyTests(unittest.TestCase):
    def test_quote_not_found_in_source_is_unlocated_and_not_evidence(self):
        data = payload()
        data['facts'][1]['quote'] = QUOTE_HALLUCINATED
        analysis = parse(data)
        fact = analysis['facts'][1]
        self.assertEqual(fact['status'], 'unlocated')
        self.assertIsNone(fact['evidence_id'])
        self.assertIsNone(fact['locator'])
        self.assertEqual(fact['reason'], 'quote_not_in_text')
        self.assertEqual(analysis['evidence_quotes'], [QUOTE_OK])

    def test_fact_without_quote_is_unlocated_and_not_evidence(self):
        data = payload()
        del data['facts'][1]['quote']
        analysis = parse(data)
        fact = analysis['facts'][1]
        self.assertEqual(fact['status'], 'unlocated')
        self.assertEqual(fact['reason'], 'missing_quote')
        self.assertIsNone(fact['evidence_id'])
        self.assertEqual(analysis['evidence_quotes'], [QUOTE_OK])
        self.assertEqual(fact['text'], '零售销售仍低于疫情前水平。')

    def test_all_facts_unlocated_derives_no_evidence_and_falls_to_e0(self):
        data = payload()
        data['facts'][0]['quote'] = QUOTE_HALLUCINATED
        data['facts'][1]['quote'] = QUOTE_HALLUCINATED
        analysis = parse(data)
        self.assertEqual(analysis['evidence_quotes'], [])
        result = score_article(analysis, article=ARTICLE)
        self.assertEqual(result['evidence_rank'], 'E0')
        self.assertEqual(result['status'], 'filtered')
        self.assertEqual(result['filter_reason'], 'insufficient_evidence')


class InferenceCascadeTests(unittest.TestCase):
    def test_basis_on_unlocated_or_out_of_range_fact_is_unsupported(self):
        data = payload()
        data['facts'][1]['quote'] = QUOTE_HALLUCINATED
        data['inferences'] = [
            {'text': 'a', 'basis': [1], 'confidence': 'low', 'assumptions': []},
            {'text': 'b', 'basis': [2], 'confidence': 'low', 'assumptions': []},
            {'text': 'c', 'basis': [99], 'confidence': 'low', 'assumptions': []},
            {'text': 'd', 'basis': [], 'confidence': 'low', 'assumptions': []},
        ]
        analysis = parse(data)
        self.assertEqual([i['status'] for i in analysis['inferences']],
                         ['supported', 'unsupported', 'unsupported', 'unsupported'])
        self.assertEqual(analysis['inferences'][1]['basis'], [2])


class StructureTests(unittest.TestCase):
    def test_missing_fact_list_is_a_hard_failure(self):
        data = payload()
        del data['facts']
        with self.assertRaises(ValueError):
            parse(data)

    def test_fact_list_that_is_not_a_list_is_a_hard_failure(self):
        with self.assertRaises(ValueError):
            parse(payload(facts={'text': 'x', 'quote': QUOTE_OK}))


class LegacyCompatibilityTests(unittest.TestCase):
    V4 = {
        'category': 'market_change',
        'summary_zh': '英国 9 月零售销售环比回升。',
        'pain_point': 'unknown',
        'target_customer': 'unknown',
        'commercial_signal': '材料没有给出采购或付费证据。',
        'revenue_claim': 'none',
        'evidence_quotes': [QUOTE_OK_2],
        'uncertainties': ['分品类明细未知'],
        'suggested_next_step': '查 ONS 原始数据表',
        'relevance_score': 85,
        'confidence': 'medium',
        'actionability': 'monitor',
    }

    def test_v4_output_keeps_numeric_score_and_marks_schema_version(self):
        analysis = parse_model_json(json.dumps(self.V4, ensure_ascii=False))
        self.assertEqual(analysis['schema_version'], 4)
        self.assertEqual(analysis['relevance_score'], 85)
        self.assertEqual(analysis['evidence_quotes'], [QUOTE_OK_2])
        self.assertEqual(analysis['suggested_next_step'], '查 ONS 原始数据表')


class RelevanceMappingTests(unittest.TestCase):
    def test_enum_maps_to_the_five_four_three_two_scale(self):
        self.assertEqual(_relevance({'relevance': 'core'}), 5)
        self.assertEqual(_relevance({'relevance': 'adjacent'}), 4)
        self.assertEqual(_relevance({'relevance': 'peripheral'}), 3)
        self.assertEqual(_relevance({'relevance': 'none'}), 2)

    def test_legacy_numeric_still_maps(self):
        self.assertEqual(_relevance({'relevance_score': 85}), 5)
        self.assertEqual(_relevance({'relevance_score': 65}), 4)
        self.assertEqual(_relevance({'relevance_score': 45}), 3)
        self.assertEqual(_relevance({'relevance_score': 10}), 2)

    def test_v5_analysis_scores_relevance_in_lane_a(self):
        analysis = parse(payload())
        result = score_article(analysis, article=ARTICLE)
        self.assertEqual(result['lane'], 'A')
        self.assertEqual(result['components']['relevance'], 5)


if __name__ == '__main__':
    unittest.main()
