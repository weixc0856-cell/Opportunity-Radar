import unittest
from types import SimpleNamespace
from opportunity_radar.scoring import score_article, evidence_level, evidence_state
from opportunity_radar.evidence import EVIDENCE_RANK, RANK_ORDER

def art(title='',summary='',published='',url='https://example.invalid/a',source_name='t'):
    return SimpleNamespace(title=title,summary=summary,published=published,url=url,source_name=source_name)

def src(**kw):
    base=dict(source_type='user_forum',provenance_class='first_party',editorial_lanes='',
              content_access_level='auto',canonical_domain='example.org')
    base.update(kw); return SimpleNamespace(**base)

STRONG={'category':'customer_pain','target_customer':'small bakeries','pain_point':'manual weekly scheduling wastes two hours',
        'commercial_signal':'owners paid for a budget tool','revenue_claim':'revenue',
        'evidence_quotes':['owners paid for a budget tool'],'uncertainties':[],'suggested_next_step':'interview 5 bakery owners',
        'relevance_score':80,'confidence':'high'}

NEWS={'category':'market_change','target_customer':'enterprise IT','pain_point':'',
      'commercial_signal':'vendor reports record data-centre demand','revenue_claim':'none',
      'evidence_quotes':['record data-centre demand'],'uncertainties':[],'suggested_next_step':'track the next quarterly filing',
      'relevance_score':85,'confidence':'medium'}

LONG='Acme said record data-centre demand drove the quarter and that capital spending on accelerators will grow again next year. ' * 5

class RangeTests(unittest.TestCase):
 def test_range(self):
  s=score_article({'relevance_score':80,'evidence_quotes':['quote'],'uncertainties':[],'suggested_next_step':'访谈客户','commercial_signal':'客户采购预算','revenue_claim':'none'})['score']
  self.assertGreaterEqual(s,0);self.assertLessEqual(s,100)
 def test_deterministic(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  self.assertEqual(score_article(a,article=article)['score'],score_article(a,article=article)['score'])
 def test_rules_version_recorded(self):
  self.assertTrue(score_article({'revenue_claim':'none'}).get('rules_version'))

class EvidenceGateTests(unittest.TestCase):
 def test_summary_evidence_is_watch_at_most(self):
  a=dict(STRONG); s=score_article(a,article=art('Weekly roster','small bakeries say owners paid for a budget tool'))
  self.assertEqual(s['evidence_level'],'summary'); self.assertEqual(s['evidence_rank'],'E1')
  self.assertEqual(s['evidence_state'],'rss_excerpt_only')
  self.assertEqual(s['status'],'watch'); self.assertLessEqual(s['score'],74)
 def test_title_only_never_enters_the_briefing(self):
  a=dict(STRONG); a['evidence_quotes']=['Weekly roster']
  s=score_article(a,article=art('Weekly roster','small bakeries say owners paid for a budget tool'))
  self.assertEqual(s['evidence_level'],'title'); self.assertEqual(s['evidence_rank'],'E0')
  self.assertEqual(s['status'],'filtered'); self.assertEqual(s['filter_reason'],'insufficient_evidence'); self.assertLessEqual(s['score'],54)
 def test_untraceable_quote_is_not_evidence(self):
  a=dict(STRONG); a['evidence_quotes']=['a sentence that is not in the input']
  s=score_article(a,article=art('Weekly roster',''))
  self.assertEqual(s['evidence_level'],'untraceable'); self.assertEqual(s['evidence_rank'],'E0')
  self.assertEqual(s['status'],'filtered'); self.assertEqual(s['filter_reason'],'insufficient_evidence'); self.assertLessEqual(s['score'],54)
 def test_mixed_traceable_and_untraceable_quotes_are_capped(self):
  a=dict(STRONG); a['evidence_quotes']=['small bakeries say owners paid for a budget tool','invented quote not in source']
  s=score_article(a,article=art('Weekly roster','small bakeries say owners paid for a budget tool'))
  self.assertEqual(s['evidence_state'],'unlocated_quotes'); self.assertEqual(s['status'],'filtered')
  self.assertEqual(s['filter_reason'],'insufficient_evidence'); self.assertLessEqual(s['score'],54)
 def test_unlocated_evidence_is_flagged(self):
  a=dict(STRONG); a['evidence_quotes']=['not in the input at all']
  s=score_article(a,article=art('Weekly roster','some summary'))
  self.assertEqual(s['evidence'][0]['field'],'unlocated');self.assertEqual(s['evidence_integrity'],'unlocated_quotes')
 def test_no_evidence_is_flagged(self):
  s=score_article({'revenue_claim':'none','evidence_quotes':[]},article=art('t','s'))
  self.assertEqual(s['evidence_integrity'],'no_evidence'); self.assertEqual(s['evidence_state'],'none')
 def test_quote_inside_html_is_located(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  s=score_article(a,article=art('Weekly roster','<p>small bakeries say owners paid for a budget tool</p>'))
  self.assertEqual(s['evidence'][0]['field'],'summary');self.assertEqual(s['evidence_integrity'],'ok')
 def test_quote_with_curly_quotes_is_located(self):
  a=dict(STRONG); a['evidence_quotes']=['he said "hi"']
  s=score_article(a,article=art('Weekly roster','then he said “hi” and left'))
  self.assertEqual(s['evidence'][0]['field'],'summary')
 def test_evidence_ids_and_locators(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  s=score_article(a,article=art('Weekly roster','small bakeries say owners paid for a budget tool'))
  e=s['evidence'][0]
  self.assertEqual(e['id'],'e1');self.assertEqual(e['field'],'summary');self.assertGreaterEqual(e['start'],0)

class FullTextReachabilityTests(unittest.TestCase):
 """The old model could never emit E2, so 'priority' was unreachable by construction."""
 def test_declared_full_text_source_reaches_e2(self):
  a=dict(STRONG); a['evidence_quotes']=['record data-centre demand']
  s=score_article(a,article=art('Acme raises guidance',LONG),source=src(content_access_level='full_text',source_type='investor_relations'))
  self.assertEqual(s['evidence_basis'],'full_text'); self.assertEqual(s['evidence_rank'],'E2')
  self.assertEqual(s['evidence_state'],'primary_source_located')
 def test_truncated_feed_is_only_an_excerpt(self):
  a=dict(STRONG); a['evidence_quotes']=['read more']
  s=score_article(a,article=art('Acme raises guidance',LONG+' Read more'),source=src(content_access_level='auto',source_type='news_media'))
  self.assertEqual(s['evidence_basis'],'excerpt'); self.assertEqual(s['evidence_rank'],'E1')
 def test_pinned_excerpt_source_never_reaches_e2(self):
  a=dict(STRONG); a['evidence_quotes']=['record data-centre demand']
  s=score_article(a,article=art('Acme raises guidance',LONG),source=src(content_access_level='excerpt',source_type='news_media'))
  self.assertEqual(s['evidence_rank'],'E1')
 def test_auto_source_estimates_a_complete_body_but_does_not_grant_e2(self):
  from opportunity_radar.evidence import content_basis_estimate
  self.assertEqual(content_basis_estimate(art('Acme',LONG)),'full_text')
  self.assertEqual(evidence_state({'evidence_quotes':['record data-centre demand']},art('Acme',LONG)),'rss_excerpt_only')
 def test_vendor_marketing_is_not_primary_verification(self):
  a=dict(STRONG); a['evidence_quotes']=['record data-centre demand']
  s=score_article(a,article=art('Acme',LONG),source=src(content_access_level='full_text',provenance_class='vendor_marketing'))
  self.assertEqual(s['evidence_state'],'full_text_verified')
 def test_multiple_sources_raise_the_state_to_coverage_only(self):
  a=dict(STRONG); a['evidence_quotes']=['record data-centre demand']
  s=score_article(a,article=art('Acme',LONG),source=src(content_access_level='full_text',provenance_class='secondhand_report'),multi_source=True)
  self.assertEqual(s['evidence_state'],'multi_source_coverage')
  self.assertEqual(s['market_validation'],'multi_source')
 def test_unreviewed_source_is_not_promotable_in_lane_b(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  article=art('Weekly roster','small bakeries say owners paid for a budget tool. '+LONG)
  s=score_article(a,article=article,source=src(source_type='user_forum',content_access_level='auto'),
                  thresholds={'priority':40,'watch':20})
  self.assertEqual(s['evidence_rank'],'E1'); self.assertEqual(s['status'],'watch')
  self.assertEqual(s['content_basis_estimate'],'full_text')
 def test_rank_order_is_consistent(self):
  self.assertEqual(EVIDENCE_RANK['full_text_verified'],'E2')
  self.assertEqual(EVIDENCE_RANK['rss_excerpt_only'],'E1')
  self.assertEqual(EVIDENCE_RANK['title_only'],'E0')
  self.assertEqual(RANK_ORDER['E2'],2)

class LaneTests(unittest.TestCase):
 def test_business_news_routes_to_lane_a(self):
  s=score_article(dict(NEWS),article=art('Acme raises guidance',LONG))
  self.assertEqual(s['lane'],'A')
 def test_community_pain_routes_to_lane_b(self):
  s=score_article(dict(STRONG),article=art('Weekly roster','owners paid for a budget tool'),source=src(source_type='user_forum'))
  self.assertEqual(s['lane'],'B')
 def test_tech_release_routes_to_lane_c(self):
  s=score_article(dict(NEWS),article=art('OpenFOAM 12 release ships a new solver',LONG),
                  source=src(source_type='open_source_project',provenance_class='project_record'))
  self.assertEqual(s['lane'],'C')
 def test_source_declaration_restricts_the_lane(self):
  s=score_article(dict(NEWS),article=art('Acme raises guidance',LONG),source=src(editorial_lanes='B,C'))
  self.assertIn(s['lane'],{'B','C'})
 def test_lane_a_promotes_on_a_located_excerpt(self):
  a=dict(NEWS); a['evidence_quotes']=['record data-centre demand']
  article=art('Acme raises guidance','Acme said record data-centre demand drove the quarter.')
  s=score_article(a,article=article,source=src(source_type='news_media'),
                  thresholds={'priority':40,'watch':20})
  self.assertEqual(s['lane'],'A'); self.assertEqual(s['status'],'priority')
 def test_lane_b_does_not_promote_on_an_excerpt(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  article=art('Weekly roster','small bakeries say owners paid for a budget tool')
  s=score_article(a,article=article,source=src(source_type='user_forum'),thresholds={'priority':40,'watch':20})
  self.assertEqual(s['lane'],'B'); self.assertEqual(s['status'],'watch'); self.assertTrue(s['capped_by_evidence'])
 def test_lanes_score_the_same_article_differently(self):
  a=dict(NEWS); a['evidence_quotes']=['record data-centre demand']
  article=art('Acme raises guidance',LONG)
  a_lane=score_article(dict(a),article=article,lane='A')
  c_lane=score_article(dict(a),article=article,lane='C')
  self.assertNotEqual(set(a_lane['components']),set(c_lane['components']))

class ConfigTests(unittest.TestCase):
 def test_config_thresholds_change_status(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  self.assertEqual(score_article(a,article=article)['status'],'watch')
  self.assertEqual(score_article(a,article=article,thresholds={'priority':120,'watch':110})['status'],'filtered')
 def test_window_boundaries_use_configured_thresholds(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  self.assertEqual(score_article(a,article=article,thresholds={'priority':75,'watch':55})['status'],'watch')
  self.assertEqual(score_article(a,article=article,thresholds={'priority':75,'watch':90})['status'],'filtered')
 def test_lane_config_is_applied(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  cfg={'B':{'weights':{'payment_evidence':100,'pain_severity':1,'buyer_clarity':1,'corroboration':1,
                       'feasibility':1,'solution_gap':1,'novelty':1}}}
  s=score_article(a,article=article,lanes_config=cfg)
  self.assertEqual(s['weights']['payment_evidence'],100)
 def test_weights_are_normalized(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  base=score_article(a,article=article)['score']
  scaled=score_article(a,article=article,weights={k:v*2 for k,v in score_article(a,article=article)['weights'].items()})['score']
  self.assertEqual(base,scaled)
 def test_negative_weights_rejected(self):
  with self.assertRaises(ValueError): score_article(dict(STRONG),weights={'payment_evidence':-1})

class SignalTests(unittest.TestCase):
 def test_actionability_is_not_constant(self):
  base=dict(STRONG); weak=dict(base); weak['suggested_next_step']='unknown'
  strong=score_article(base,article=art('Weekly roster','owners paid for a budget tool'))
  none=score_article(weak,article=art('Weekly roster','owners paid for a budget tool'))
  self.assertGreater(strong['components']['feasibility'],none['components']['feasibility'])
 def test_novelty_unknown_scores_zero(self):
  s=score_article(dict(STRONG),article=art('Weekly roster','owners paid for a budget tool'))
  self.assertEqual(s['components']['novelty'],0)
 def test_seen_event_reduces_novelty(self):
  a=dict(STRONG); article=art('Weekly roster','owners paid for a budget tool')
  self.assertGreater(score_article(a,article=article,event_seen_before=False)['components']['novelty'],
                     score_article(a,article=article,event_seen_before=True)['components']['novelty'])
 def test_missing_payment_evidence_is_marked(self):
  s=score_article({'revenue_claim':'none','commercial_signal':'','evidence_quotes':[]},
                  article=art('Why does meshing take hours?','s'))
  self.assertEqual(s['lane'],'B'); self.assertIn('待验证',s['verification_note'])
 def test_present_payment_evidence_clears_mark(self):
  a=dict(STRONG); s=score_article(a,article=art('Weekly roster','owners paid for a budget tool'))
  self.assertEqual(s['verification_note'],'')
 def test_seller_pricing_is_not_buyer_payment(self):
  a=dict(STRONG); a['evidence_quotes']=['pricing page']
  s=score_article(a,article=art('Weekly roster','See our pricing page for the roster tool'))
  self.assertEqual(s['components']['payment_evidence'],0)
  self.assertIn('待验证',s['verification_note'])
 def test_market_validation_is_recorded(self):
  a=dict(STRONG); s=score_article(a,article=art('Weekly roster','owners paid for a budget tool'))
  self.assertEqual(s['market_validation'],'buyer_confirmed')

class RevenueRiskTests(unittest.TestCase):
 def test_revenue_claim_without_evidence(self):
  s=score_article({'relevance_score':90,'evidence_quotes':[],'uncertainties':['unknown'],'suggested_next_step':'verify','commercial_signal':'revenue','revenue_claim':'revenue'})
  self.assertEqual(s['risk_flag'],'revenue_claim_without_evidence')
 def test_revenue_evidence_contradiction_is_flagged(self):
  a={'revenue_claim':'unknown','commercial_signal':'none','evidence_quotes':['This months marks my first 5 figure month'],'uncertainties':[]}
  s=score_article(a,article=art('Startup phone number','This months marks my first 5 figure month'))
  self.assertEqual(s['risk_flag'],'revenue_evidence_contradicts_claim')

class AdmissionMatrixTests(unittest.TestCase):
 """The lane/E rank matrix, pinned so a config edit cannot silently widen it."""
 def test_e0_is_filtered_in_every_lane(self):
  a=dict(STRONG); a['evidence_quotes']=[]
  for lane in ('A','B','C'):
   s=score_article(dict(a),article=art('Unrelated headline','some body'),lane=lane,thresholds={'priority':10,'watch':5})
   self.assertEqual(s['status'],'filtered',lane); self.assertEqual(s['filter_reason'],'insufficient_evidence',lane)
 def test_e1_promotes_in_a_only(self):
  a=dict(NEWS); a['evidence_quotes']=['record data-centre demand']
  article=art('Acme raises guidance','Acme said record data-centre demand drove the quarter.')
  low={'priority':10,'watch':5}
  self.assertEqual(score_article(dict(a),article=article,lane='A',thresholds=low)['status'],'priority')
  self.assertEqual(score_article(dict(a),article=article,lane='B',thresholds=low)['status'],'watch')
  self.assertEqual(score_article(dict(a),article=article,lane='C',thresholds=low)['status'],'watch')
 def test_e2_can_promote_in_b(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  article=art('Weekly roster','small bakeries say owners paid for a budget tool. '+LONG)
  s=score_article(dict(a),article=article,lane='B',
                  source=src(source_type='user_forum',content_access_level='full_text'),
                  thresholds={'priority':10,'watch':5})
  self.assertEqual(s['evidence_rank'],'E2'); self.assertEqual(s['status'],'priority')
 def test_unreviewed_source_cannot_reach_e2_in_any_lane(self):
  a=dict(STRONG); a['evidence_quotes']=['record data-centre demand']
  article=art('Acme raises guidance',LONG)
  for lane in ('A','B','C'):
   s=score_article(dict(a),article=article,lane=lane,source=src(content_access_level='auto'))
   self.assertEqual(s['evidence_rank'],'E1',lane)
   self.assertEqual(s['content_basis_estimate'],'full_text',lane)

class DeclarationVersusLengthTests(unittest.TestCase):
 """E2 must follow the reviewed declaration, never the length of the body."""
 def test_a_declared_source_reaches_e2_with_a_short_body(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  article=art('Weekly roster','owners paid for a budget tool')   # far below the 400-char heuristic
  s=score_article(a,article=article,source=src(content_access_level='full_text'),lane='B')
  self.assertEqual(s['evidence_rank'],'E2')
  self.assertEqual(s['evidence_basis'],'full_text')
 def test_a_long_undeclared_body_stays_at_e1(self):
  a=dict(STRONG); a['evidence_quotes']=['owners paid for a budget tool']
  article=art('Weekly roster','owners paid for a budget tool. '+LONG)
  s=score_article(a,article=article,source=src(content_access_level='auto'),lane='B')
  self.assertEqual(s['evidence_rank'],'E1')
  self.assertEqual(s['content_basis_estimate'],'full_text')   # estimate says complete; it still does not count
