import tempfile,unittest
from pathlib import Path
from opportunity_radar.cli import _validate_report, _atomic_write, _write, send_decision

class Tests(unittest.TestCase):
 def test_validate_accepts_complete_report(self):
  self.assertIsNone(_validate_report('subject','【执行摘要】x','<!doctype html><html></html>'))
 def test_validate_rejects_missing_summary(self):
  with self.assertRaises(ValueError): _validate_report('subject','body','<html></html>')
 def test_atomic_write_replaces_without_leaving_temp(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x.txt'; p.write_text('old',encoding='utf-8')
   _atomic_write(p,'new')
   self.assertEqual(p.read_text(encoding='utf-8'),'new');self.assertFalse(Path(str(p)+'.tmp').exists())
 def test_invalid_report_does_not_overwrite_previous(self):
  with tempfile.TemporaryDirectory() as d:
   latest=Path(d)/'latest-digest.txt'; latest.write_text('previous',encoding='utf-8')
   with self.assertRaises(ValueError): _write(d,'subject','no marker','<html></html>')
   self.assertEqual(latest.read_text(encoding='utf-8'),'previous')
 def test_timestamped_archive_and_hash(self):
  with tempfile.TemporaryDirectory() as d:
   path,h=_write(d,'subject','【执行摘要】x','<!doctype html><html></html>')
   self.assertTrue(Path(path).exists())
   self.assertRegex(Path(path).name,r'^\d{4}-\d{2}-\d{2}-\d{6}\.txt$')
   self.assertTrue(Path(str(path).replace('.txt','.html')).exists())
   self.assertEqual(len(h),16)
 def test_send_decision_separates_failure_from_no_content(self):
  self.assertEqual(send_decision(0,0,2,False),'analysis_failed')
  self.assertEqual(send_decision(0,0,0,False),'no_new_content')
  self.assertEqual(send_decision(0,0,0,True),'send')
  self.assertEqual(send_decision(3,0,0,False),'send')
  self.assertEqual(send_decision(0,2,0,False),'send')
