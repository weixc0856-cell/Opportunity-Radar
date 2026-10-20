import unittest
from opportunity_radar.analyzer import load_prompt, PROMPT_VERSION, SYSTEM

class Tests(unittest.TestCase):
 def test_prompt_file_is_versioned_and_loaded(self):
  version,text=load_prompt()
  self.assertEqual(version,'2');self.assertIn('untrusted data',text);self.assertIn('evidence_quotes',text)
 def test_missing_prompt_falls_back_to_builtin(self):
  version,text=load_prompt('prompts/does-not-exist.md')
  self.assertTrue(version);self.assertIn('cautious information triage assistant',text)
 def test_module_prompt_matches_loader(self):
  self.assertEqual((PROMPT_VERSION,SYSTEM),load_prompt())
