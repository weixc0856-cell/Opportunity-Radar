import tempfile,unittest
from pathlib import Path
from opportunity_radar.cli import _validate_report, _atomic_write, _write, send_decision, run_status

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
 def test_run_status_marks_partial_failures(self):
  self.assertEqual(run_status(0,0),'success')
  self.assertEqual(run_status(1,0),'partial_failed')
  self.assertEqual(run_status(0,1),'partial_failed')
 def test_archive_contains_structured_snapshot_and_manifest(self):
  import json
  with tempfile.TemporaryDirectory() as d:
   items=[{'title':'sample','url':'https://example.invalid/a','source_name':'test','analysis':{'summary_zh':'generated'},
           'score':60,'status':'watch','evidence':[{'id':'e1','quote':'short quote'}]}]
   stats={'fetched':1,'analyzed':1,'counts':{'watch':1}}
   path,_=_write(d,'subject','【执行摘要】x','<!doctype html><html></html>',items=items,stats=stats,run_id=42)
   p=Path(path)
   self.assertRegex(p.parent.parent.parent.name,r'^\d{4}$')
   self.assertRegex(p.parent.parent.name,r'^\d{2}$')
   self.assertRegex(p.parent.name,r'^\d{2}$')
   snapshot=json.loads(p.with_name(p.stem+'.items.json').read_text(encoding='utf-8'))
   manifest=json.loads(p.with_name(p.stem+'.manifest.json').read_text(encoding='utf-8'))
   self.assertEqual(snapshot['run_id'],42);self.assertEqual(snapshot['items'][0]['title'],'sample')
   self.assertEqual(manifest['stats']['analyzed'],1);self.assertEqual(manifest['files']['html'],p.stem+'.html')
   self.assertIn('storage_note',manifest)
