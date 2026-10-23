import unittest
from types import SimpleNamespace
from opportunity_radar.classifier import classify

def art(title,summary=''): return SimpleNamespace(title=title,summary=summary,url='',source_name='')

def forum(title,url='https://discourse.paraview.org/t/x'): return SimpleNamespace(title=title,summary='',url=url,source_name='ParaView Forum')

def ana(**kw):
    d={'category':'unknown','commercial_signal':'','confidence':'low'}; d.update(kw); return d

class Tests(unittest.TestCase):
 def test_hiring_not_opportunity(self):
  c=classify(art('Evidence (YC S21) Is Hiring Software Engineers'),ana())
  self.assertEqual(c['article_type'],'hiring');self.assertFalse(c['business_relevant'])
 def test_simulation_jobs_are_not_hiring(self):
  self.assertNotEqual(classify(art('Unable to Start CFD or Meshing Jobs'),ana())['article_type'],'hiring')
 def test_funding(self):
  self.assertEqual(classify(art('Acme raises $4M Series A'),ana())['article_type'],'funding')
 def test_user_pain_from_model_category(self):
  self.assertEqual(classify(art('Weekly roster tool'),ana(category='customer_pain'))['article_type'],'user_pain')
 def test_user_pain_from_text(self):
  self.assertIn(classify(art('Why does scheduling take hours every week?'),ana())['article_type'],{'user_pain'})
 def test_tech_release(self):
  self.assertEqual(classify(art('OpenBSD 8.0 release will have Linux 6.18 drivers'),ana())['article_type'],'tech')
 def test_product_launch(self):
  self.assertEqual(classify(art('Introducing MiniMax M3.1 Flash'),ana())['article_type'],'product')
 def test_general(self):
  self.assertEqual(classify(art('Lula supporters protest against Meta'),ana())['article_type'],'general')
 def test_payment_hits(self):
  self.assertGreater(classify(art('Tool pricing page'),ana())['payment_hits'],0)
 def test_model_speculation_is_not_payment_evidence(self):
  self.assertEqual(classify(art('Weekly roster tool'),ana(commercial_signal='customers pay a budget'))['payment_hits'],0)
 def test_pricing_keyword_is_indirect_not_direct_payment(self):
  c=classify(art('Tool pricing page'),ana())
  self.assertEqual(c['payment_evidence'],'indirect')
 def test_already_use_is_not_a_purchase(self):
  c=classify(art('We already use this tool'),ana())
  self.assertNotEqual(c['payment_evidence'],'existing_purchase')
 def test_paid_purchase_is_direct_evidence(self):
  c=classify(art('We already paid for this simulation tool'),ana())
  self.assertEqual(c['payment_evidence'],'existing_purchase')
 def test_content_source_title_only(self):
  self.assertEqual(classify(art('x'),ana())['content_source'],'title_only')
  self.assertEqual(classify(art('x','some summary'),ana())['content_source'],'rss_summary')
 def test_content_metadata(self):
  empty=classify(art('x'),ana()); full=classify(art('x','some summary'),ana())
  self.assertEqual(empty['content_status'],'empty');self.assertEqual(empty['content_length'],0)
  self.assertEqual(full['content_status'],'ok');self.assertEqual(full['content_length'],len('some summary'))
 def test_signal_payment_demand(self):
  c=classify(art('Need someone to automate CFD reporting, budget available'),ana())
  self.assertEqual(c['signal_type'],'payment_demand');self.assertIn(c['payment_evidence'],{'explicit_budget','stated_willingness'})
 def test_signal_user_pain(self):
  self.assertEqual(classify(art('Why does meshing take hours?'),ana())['signal_type'],'user_pain')
 def test_signal_deployment_blocker(self):
  self.assertEqual(classify(art('OpenFOAM install fails on Ubuntu 24.04'),ana())['signal_type'],'deployment_blocker')
 def test_signal_product_gap(self):
  self.assertEqual(classify(art('Missing support for CAD import'),ana())['signal_type'],'product_gap')
 def test_buyer_engineering_team(self):
  self.assertEqual(classify(art('CFD mesh solver question'),ana())['buyer_type'],'engineering_team')
 def test_source_quality_vendor_marketing(self):
  self.assertEqual(classify(art('Introducing version 2.0 release'),ana())['source_quality'],'vendor_marketing')
 def test_forum_post_is_first_party_even_for_feature_request(self):
  self.assertEqual(classify(forum('make crinkle on by default'),ana())['source_quality'],'first_party')
 def test_github_release_is_project_record(self):
  a=SimpleNamespace(title='v2.0 released',summary='',url='https://github.com/o/r/releases',source_name='r')
  self.assertEqual(classify(a,ana())['source_quality'],'project_record')
 def test_declared_provenance_overrides_heuristics(self):
  src=SimpleNamespace(provenance_class='secondhand_report')
  self.assertEqual(classify(forum('make crinkle on by default'),ana(),src)['source_quality'],'secondhand_report')
 def test_delivery_service_when_outsourcing(self):
  self.assertEqual(classify(art('Looking to outsource custom development for simulation automation'),ana())['delivery_fit'],'service')
