import unittest
from types import SimpleNamespace
from opportunity_radar.lanes import lanes_of, content_lane, derive_lane, item_lane

def src(**kw):
    base=dict(source_type='',editorial_lanes='')
    base.update(kw); return SimpleNamespace(**base)

class Tests(unittest.TestCase):
 def test_lane_declaration_parsing(self):
  self.assertEqual(lanes_of(src(editorial_lanes='A,C')),('A','C'))
  self.assertEqual(lanes_of(src(editorial_lanes='c b')),('B','C'))
  self.assertEqual(lanes_of(src(editorial_lanes='')),())
  self.assertEqual(lanes_of(None),())
 def test_hiring_goes_to_the_opportunity_lane(self):
  self.assertEqual(content_lane({},{'article_type':'hiring'}),'B')
 def test_payment_demand_goes_to_b(self):
  self.assertEqual(content_lane({},{'article_type':'general','signal_type':'payment_demand'}),'B')
 def test_funding_is_business_news(self):
  self.assertEqual(content_lane({},{'article_type':'funding'}),'A')
 def test_tech_is_tracking(self):
  self.assertEqual(content_lane({},{'article_type':'tech'}),'C')
 def test_general_defaults_to_a_inside_a_news_source(self):
  self.assertEqual(derive_lane({},{},src(source_type='news_media'),{'article_type':'general'}),'A')
 def test_general_defaults_to_b_inside_a_community_source(self):
  self.assertEqual(derive_lane({},{},src(source_type='user_forum'),{'article_type':'general'}),'B')
 def test_declared_lanes_narrow_the_choice(self):
  self.assertEqual(derive_lane({},{},src(editorial_lanes='C'),{'article_type':'funding'}),'C')
 def test_declared_lane_is_kept_when_content_matches(self):
  self.assertEqual(derive_lane({},{},src(editorial_lanes='A,B'),{'article_type':'funding'}),'A')
 def test_research_release_note_is_tracking(self):
  cls={'article_type':'product','source_quality':'project_record'}
  self.assertEqual(derive_lane({},{},src(source_type='open_source_project'),cls),'C')
 def test_item_lane_reads_the_recorded_lane(self):
  self.assertEqual(item_lane({'lane':'C'}),'C')
 def test_item_lane_falls_back_to_classification(self):
  self.assertEqual(item_lane({'classification':{'article_type':'user_pain'}}),'B')
