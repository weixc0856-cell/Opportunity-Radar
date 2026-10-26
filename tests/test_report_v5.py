"""Contract tests for the v5 report card.

The card must lead with the structured record (facts / inferences / gaps / actions),
keep unlocated claims out of the fact block, and label the 0-100 number as a ranking
aid rather than a conclusion.
"""
import unittest

from opportunity_radar.digest import render_digest

QUOTE_OK = 'Retail sales volumes are estimated to have risen by 0.5% in September 2026.'
QUOTE_HALLUCINATED = 'Retail sales volumes rose by 4.2% in September 2026.'
DATE = '2026-10-26'

LANE_WEIGHTS = {
    'A': {'importance': 25, 'source_reliability': 20, 'evidence_completeness': 20,
          'novelty': 15, 'relevance': 10, 'timeliness': 10},
    'B': {'pain_severity': 20, 'buyer_clarity': 15, 'payment_evidence': 25,
          'corroboration': 15, 'feasibility': 10, 'solution_gap': 10, 'novelty': 5},
    'C': {'technical_maturity': 25, 'reproducibility': 20, 'impact_scope': 20,
          'source_reliability': 20, 'novelty': 15},
}


def stats(**kwargs):
    data = {
        'fetched': 1, 'new': 1, 'queued': 1, 'analyzed': 1, 'failed': 0, 'skipped': 0,
        'counts': {'priority': 1, 'watch': 0, 'filtered': 0},
        'lane_weights': LANE_WEIGHTS,
        'lane_thresholds': {lane: {'priority': 75, 'watch': 55} for lane in 'ABC'},
        'rules_version': 'v5', 'model': 'fixture', 'prompt_version': '5',
        'prompt_hash': 'fixture00001',
    }
    data.update(kwargs)
    return data


def analysis_v5():
    return {
        'schema_version': 5,
        'category': 'market_change',
        'summary_zh': '英国 9 月零售销售环比回升，但材料没有说明驱动因素。',
        'relevance': 'core',
        'confidence': 'medium',
        'revenue_claim': 'none',
        'actionability': 'investigate',
        'facts': [
            {
                'ordinal': 1,
                'text': '英国 2026 年 9 月零售销售量环比上升。',
                'quote': QUOTE_OK,
                'actor': 'UK ONS',
                'status': 'located',
                'evidence_id': 'e1',
                'locator': {'field': 'summary', 'start': 0, 'length': len(QUOTE_OK)},
                'source_url': 'https://example.invalid/retail',
                'published': '2026-10-23T09:30:00+00:00',
                'reason': '',
            },
            {
                'ordinal': 2,
                'text': '零售销售量上升 4.2%。',
                'quote': QUOTE_HALLUCINATED,
                'actor': 'UK ONS',
                'status': 'unlocated',
                'evidence_id': None,
                'locator': None,
                'source_url': 'https://example.invalid/retail',
                'published': '2026-10-23T09:30:00+00:00',
                'reason': 'quote_not_in_text',
            },
        ],
        'inferences': [
            {'ordinal': 1, 'text': '消费需求可能在第三季度末回暖。', 'basis': [1],
             'confidence': 'low', 'assumptions': ['单月数据能代表趋势'], 'status': 'supported'},
            {'ordinal': 2, 'text': '零售商会增加招聘。', 'basis': [2],
             'confidence': 'low', 'assumptions': [], 'status': 'unsupported'},
        ],
        'gaps': [
            {'ordinal': 1, 'missing': '分品类与分地区的零售销售明细',
             'why_it_matters': '决定回暖是否普遍', 'how_to_close': '查 ONS 配套数据表',
             'status': 'open'},
        ],
        'actions': [
            {'ordinal': 1, 'step': '调取 ONS 原始数据表，核对分品类贡献', 'kind': 'verify',
             'done_when': '确认至少三个品类的变化', 'status': 'open'},
        ],
        'evidence_quotes': [QUOTE_OK],
        'uncertainties': ['分品类与分地区的零售销售明细'],
        'suggested_next_step': '调取 ONS 原始数据表，核对分品类贡献',
        'pain_point': 'unknown',
        'target_customer': 'unknown',
        'commercial_signal': '零售回暖可能带动相关服务需求，但没有采购或付费证据。',
        'schema_deviations': [],
    }


def item(analysis=None):
    return {
        'title': 'Retail sales, Great Britain: September 2026',
        'url': 'https://example.invalid/retail',
        'source_name': 'UK ONS Release Calendar',
        'analysis': analysis or analysis_v5(),
        'score': 78,
        'status': 'priority',
        'filter_reason': '',
        'lane': 'A',
        'distribution': 'included',
        'evidence_level': 'summary',
        'evidence_state': 'rss_excerpt_only',
        'evidence_rank': 'E1',
        'evidence': [{'id': 'e1', 'quote': QUOTE_OK, 'field': 'summary', 'start': 0,
                      'length': len(QUOTE_OK), 'locator_basis': 'normalized_text'}],
        'classification': {'article_type': 'market_change', 'signal_type': 'tech_trend',
                           'buyer_type': 'unknown', 'source_quality': 'secondhand_report'},
        'market_validation': 'single_source',
        'risk_flag': '',
        'verification_note': '',
        'components': {'importance': 5, 'source_reliability': 3, 'evidence_completeness': 3,
                       'novelty': 5, 'relevance': 5, 'timeliness': 5},
        'meta': {},
        'scoring': {'status': 'priority', 'evidence_state': 'rss_excerpt_only'},
    }


def render(one=None):
    subject, body = render_digest([one or item()], stats(), DATE)
    return subject, body


class ReportCardTests(unittest.TestCase):
    def test_card_renders_four_sections(self):
        _, body = render()
        self.assertIn('事实（可在原文定位）', body)
        self.assertIn('推断（基于 F1，置信度 低）', body)
        self.assertIn('消费需求可能在第三季度末回暖', body)
        self.assertIn('证据缺口', body)
        self.assertIn('分品类与分地区的零售销售明细', body)
        self.assertIn('决定回暖是否普遍', body)
        self.assertIn('建议行动', body)
        self.assertIn('调取 ONS 原始数据表，核对分品类贡献', body)
        self.assertIn('确认至少三个品类的变化', body)

    def test_fact_section_contains_only_located_claims(self):
        _, body = render()
        fact_block = body.split('事实（可在原文定位）', 1)[1].split('推断（基于', 1)[0]
        self.assertIn('英国 2026 年 9 月零售销售量环比上升', fact_block)
        self.assertNotIn(QUOTE_HALLUCINATED, fact_block)
        self.assertNotIn('零售销售量上升 4.2%', fact_block)

    def test_unlocated_claim_is_listed_under_its_own_label(self):
        _, body = render()
        self.assertIn('未能定位（不作为事实）', body)
        unlocated_block = body.split('未能定位（不作为事实）', 1)[1]
        self.assertIn(QUOTE_HALLUCINATED, unlocated_block)

    def test_unsupported_inference_is_listed_separately(self):
        _, body = render()
        self.assertIn('未获事实支持的推断', body)
        supported_block = body.split('推断（基于', 1)[1].split('未获事实支持的推断', 1)[0]
        self.assertNotIn('零售商会增加招聘', supported_block)
        unsupported_block = body.split('未获事实支持的推断', 1)[1]
        self.assertIn('零售商会增加招聘', unsupported_block)

    def test_score_is_labelled_as_a_ranking_aid(self):
        _, body = render()
        self.assertIn('排序分', body)
        self.assertIn('仅用于本期排序', body)

    def test_v4_item_still_renders(self):
        legacy = item(analysis={
            'category': 'market_change',
            'summary_zh': '英国 9 月零售销售环比回升。',
            'pain_point': 'unknown',
            'target_customer': 'unknown',
            'commercial_signal': '材料没有给出采购或付费证据。',
            'revenue_claim': 'none',
            'evidence_quotes': [QUOTE_OK],
            'uncertainties': ['分品类明细未知'],
            'suggested_next_step': '查 ONS 原始数据表',
            'relevance_score': 85,
            'confidence': 'medium',
            'actionability': 'monitor',
        })
        _, body = render(legacy)
        self.assertIn('事实（可在原文定位）', body)
        self.assertIn('英国 9 月零售销售环比回升', body)


if __name__ == '__main__':
    unittest.main()
