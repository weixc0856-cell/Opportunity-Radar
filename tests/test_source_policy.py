import unittest
from opportunity_radar.source_policy import Source,is_approved,load_sources
class Tests(unittest.TestCase):
 def test_disabled_rejected(self): self.assertFalse(is_approved(Source('x','X','https://x','https://x/feed','rss','approved',False,'1')))
 def test_approved_https(self): self.assertTrue(is_approved(Source('x','X','https://x','https://x/feed','rss','approved',True,'1')))
 def test_missing_feed_id_rejected(self): self.assertFalse(is_approved(Source('x','X','https://x','https://x/feed','rss','approved',True,'')))
 def test_http_rejected(self): self.assertFalse(is_approved(Source('x','X','https://x','http://x/feed','rss','approved',True,'1')))
 def test_registry_metadata_loaded(self):
  ss=[s for s in load_sources() if s.source_id=='paraview-forum'][0]
  self.assertEqual(ss.provenance_class,'first_party');self.assertEqual(ss.canonical_domain,'discourse.paraview.org');self.assertTrue(ss.terms_url)
 def test_registry_declares_provenance_for_all_rows(self):
  for s in load_sources():
   if s.source_id=='example-official': continue
   self.assertTrue(s.provenance_class,s.source_id);self.assertTrue(s.canonical_domain,s.source_id)
