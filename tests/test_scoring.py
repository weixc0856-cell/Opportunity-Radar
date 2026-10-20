import unittest
from types import SimpleNamespace
from opportunity_radar.scoring import score_article, evidence_level

def art(title='',summary='',published=''):
    return SimpleNamespace(title=title,summary=summary,published=published,url='https://example.invalid/a',source_name='t')

STRONG={'category':'customer_pain','target_customer':'small bakeries','pain_point':'manual weekly scheduling wastes two hours',
        'commercial_signal':'owners paid for a budget tool','revenue_claim':'revenue',
        'evidence_quotes':['owners paid for a budget tool'],'uncertainties':[],'suggested_next_step':'interview 5 bakery owners',
        'relevance_score':80,'confidence':'high'}

class Tests(unittest.TestCase):
 def test_range(self):
  s=score_article({'relevance_score':80,'evidence_quotes':['quote'],'uncertainties':[],'suggested_next_step':'访谈客户','commercial_signal':'客户采购预算','revenue_claim':'none'})['score'];self.assertGreaterEqual(s,0);self.assertLessEqual(s,100)
 def test_revenue_flag(self):
  s=score_article({'relevance_score':90,'evidence_quotes':[],'uncertainties':['unknown'],'suggested_next_step':'verify','commercial_signal':'revenue','revenue_claim':'revenue'});self.assertEqual(s['risk_flag'],'revenue_claim_without_evidence')
 def test_traceable_summary_can_be_priority(self):
  a=dict(STRONG); s=score_article(a,article=art('Weekly roster', 'small bakeries say owners paid for a budget tool'))
  self.assertEqual(s['evidence_level'],'summary'); self.assertEqual(s['status'],'priority')
 def test_title_only_is_capped_below_priority(self):
  a=dict(STRONG); a['evidence_quotes']=['Weekly roster']
  s=score_article(a,article=art('Weekly roster','small bakeries say owners paid for a budget tool'))
  self.assertEqual(s['evidence_level'],'title'); self.assertNotEqual(s['status'],'priority'); self.assertLessEqual(s['score'],74)
 def test_untraceable_quote_is_not_evidence(self):
  a=dict(STRONG); a['evidence_quotes']=['a sentence that is not in the input']
  s=score_article(a,article=art('Weekly roster',''))
  self.assertEqual(s['evidence_level'],'untraceable'); self.assertLessEqual(s['score'],74)
 def test_config_thresholds_change_status(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  self.assertEqual(score_article(a,article=article)['status'],'priority')
  self.assertEqual(score_article(a,article=article,thresholds={'priority':120,'watch':110})['status'],'filtered')
 def test_window_boundaries_use_configured_thresholds(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  s=score_article(a,article=article,thresholds={'priority':75,'watch':55})
  self.assertEqual(s['status'],'priority')
  s2=score_article(a,article=article,thresholds={'priority':101,'watch':55})
  self.assertEqual(s2['status'],'watch')
 def test_deterministic(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  self.assertEqual(score_article(a,article=article)['score'],score_article(a,article=article)['score'])
 def test_actionability_not_constant(self):
  base=dict(STRONG)
  weak=dict(base); weak['suggested_next_step']='unknown'
  strong=score_article(base,article=art('Weekly roster','owners paid for a budget tool'))
  none=score_article(weak,article=art('Weekly roster','owners paid for a budget tool'))
  self.assertGreater(strong['components']['actionability'],none['components']['actionability'])
 def test_novelty_unknown_scores_zero(self):
  s=score_article(dict(STRONG),article=art('Weekly roster','owners paid for a budget tool'))
  self.assertEqual(s['components']['novelty'],0)
 def test_rules_version_recorded(self):
  self.assertTrue(score_article({'revenue_claim':'none'}).get('rules_version'))
 def test_missing_payment_evidence_is_marked(self):
  s=score_article({'revenue_claim':'none','commercial_signal':'','evidence_quotes':[]},article=art('t','s'))
  self.assertIn('待验证',s['verification_note'])
 def test_evidence_ids_and_locators(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  s=score_article(a,article=art('Weekly roster','small bakeries say owners paid for a budget tool'))
  e=s['evidence'][0]
  self.assertEqual(e['id'],'e1');self.assertEqual(e['field'],'summary');self.assertGreaterEqual(e['start'],0)
  self.assertEqual(s['evidence_integrity'],'ok')
 def test_unlocated_evidence_is_flagged(self):
  a=dict(STRONG); a['evidence_quotes']=['not in the input at all']
  s=score_article(a,article=art('Weekly roster','some summary'))
  self.assertEqual(s['evidence'][0]['field'],'unlocated');self.assertEqual(s['evidence_integrity'],'unlocated_quotes')
 def test_no_evidence_is_flagged(self):
  s=score_article({'revenue_claim':'none','evidence_quotes':[]},article=art('t','s'))
  self.assertEqual(s['evidence_integrity'],'no_evidence')
 def test_quote_inside_html_is_located(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  s=score_article(a,article=art('Weekly roster','<p>small bakeries say owners paid for a budget tool</p>'))
  self.assertEqual(s['evidence'][0]['field'],'summary');self.assertEqual(s['evidence_integrity'],'ok')
  self.assertEqual(s['evidence_level'],'summary')
 def test_quote_with_curly_quotes_is_located(self):
  a=dict(STRONG); a['evidence_quotes']=['he said "hi"']
  s=score_article(a,article=art('Weekly roster','then he said “hi” and left'))
  self.assertEqual(s['evidence'][0]['field'],'summary')
 def test_present_payment_evidence_clears_mark(self):
  a=dict(STRONG); s=score_article(a,article=art('Weekly roster','owners paid for a budget tool'))
  self.assertEqual(s['verification_note'],'')
