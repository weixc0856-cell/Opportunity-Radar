import unittest
from opportunity_radar.acceptance import summarize

class Tests(unittest.TestCase):
 def test_critical_failure_counts(self):
  results=[{'name':'a','ok':True,'critical':True},{'name':'b','ok':False,'critical':True},{'name':'c','ok':False,'critical':False}]
  s=summarize(results)
  self.assertEqual(s['passed'],1);self.assertEqual(len(s['failed']),2);self.assertEqual(len(s['critical_failed']),1)
 def test_non_critical_failure_does_not_block(self):
  s=summarize([{'name':'scheduler','ok':False,'critical':False}])
  self.assertEqual(len(s['critical_failed']),0)
