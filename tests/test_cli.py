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

def _src(sid,name,cap):
    from opportunity_radar.source_policy import Source
    return Source(sid,name,'https://example.org','https://example.org/feed','rss','approved',True,'1',source_cap=cap)

def _item(name,score,status='watch'):
    return {'source_name':name,'score':score,'status':status,'filter_reason':''}

class SourceCapTests(unittest.TestCase):
 def test_cap_defers_extras_without_rewriting_their_verdict(self):
  from opportunity_radar.cli import apply_source_caps
  items=[_item('Chatty',90,'priority'),_item('Chatty',80),_item('Chatty',70),_item('Quiet',40)]
  caps=apply_source_caps(items,[_src('chatty','Chatty',2),_src('quiet','Quiet',0)])
  self.assertEqual(caps,{'deferred':1,'unresolved':0})
  self.assertEqual(items[0]['status'],'priority'); self.assertEqual(items[0]['distribution'],'included')
  self.assertEqual(items[1]['status'],'watch'); self.assertEqual(items[1]['distribution'],'included')
  # Still "worth watching" — it just did not make this issue.
  self.assertEqual(items[2]['status'],'watch'); self.assertEqual(items[2]['distribution'],'deferred')
  self.assertEqual(items[3]['distribution'],'included')

 def test_zero_or_missing_cap_means_uncapped(self):
  from opportunity_radar.cli import apply_source_caps
  items=[_item('Quiet',90),_item('Quiet',80),_item('Quiet',70)]
  self.assertEqual(apply_source_caps(items,[_src('quiet','Quiet',0)])['deferred'],0)
  self.assertTrue(all(i['distribution']=='included' for i in items))

 def test_cap_is_hard_across_the_priority_band(self):
  # A source with more priority items than its cap keeps only the top ones in this issue.
  from opportunity_radar.cli import apply_source_caps
  items=[_item('Wire',95,'priority'),_item('Wire',90,'priority'),_item('Wire',85,'priority')]
  self.assertEqual(apply_source_caps(items,[_src('wire','Wire',1)])['deferred'],2)
  self.assertEqual([i['status'] for i in items],['priority','priority','priority'])
  self.assertEqual([i['distribution'] for i in items],['included','deferred','deferred'])

 def test_equal_scores_keep_their_original_order(self):
  from opportunity_radar.cli import apply_source_caps
  items=[_item('Wire',70),_item('Wire',70),_item('Wire',70)]
  apply_source_caps(items,[_src('wire','Wire',1)])
  self.assertEqual([i['distribution'] for i in items],['included','deferred','deferred'])

 def test_caps_survive_punctuation_differences(self):
  from opportunity_radar.cli import apply_source_caps
  items=[_item('Hacker News Show',90),_item('Hacker News Show',80)]
  self.assertEqual(apply_source_caps(items,[_src('hn-show','Hacker News —— Show',1)])['deferred'],1)

 def test_an_unmatched_item_gets_no_cap_but_is_counted(self):
  from opportunity_radar.cli import apply_source_caps
  items=[_item('Unknown Feed',90,'priority'),_item('Unknown Feed',80)]
  caps=apply_source_caps(items,[_src('x','Something Else',1)])
  self.assertEqual(caps['deferred'],0); self.assertEqual(caps['unresolved'],2)
  self.assertTrue(all(i['distribution']=='included' for i in items))

 def test_colliding_names_are_never_resolved_by_name(self):
  from opportunity_radar.cli import source_index,resolve_source
  a=_src('a','Hacker News — Show',1); b=_src('b','Hacker News Show',5)
  by_id,by_name,ambiguous=source_index([a,b])
  self.assertIn('hackernewsshow',ambiguous)
  self.assertIsNone(resolve_source({'source_name':'Hacker News Show'},by_id,by_name))
  self.assertEqual(resolve_source({'source_id':'b','source_name':'Hacker News Show'},by_id,by_name).source_cap,5)

 def test_source_id_wins_over_a_similar_name(self):
  from opportunity_radar.cli import source_index,resolve_source
  by_id,by_name,_=source_index([_src('a','Alpha',1),_src('b','Beta',2)])
  self.assertEqual(resolve_source({'source_id':'b','source_name':'Alpha'},by_id,by_name).source_cap,2)

class CapOrderingTests(unittest.TestCase):
 def test_cap_runs_after_scoring_not_after_arrival(self):
  # The high-value announcement arrives last; it must keep the slot.
  from opportunity_radar.cli import apply_source_caps
  items=[_item('Wire',40),_item('Wire',70),_item('Wire',95,'priority')]
  self.assertEqual(apply_source_caps(items,[_src('wire','Wire',1)])['deferred'],2)
  self.assertEqual(items[2]['distribution'],'included')
  self.assertEqual([items[0]['distribution'],items[1]['distribution']],['deferred','deferred'])

 def test_capped_items_keep_their_verdict_and_score(self):
  from opportunity_radar.cli import apply_source_caps
  items=[_item('Wire',95,'priority'),_item('Wire',90)]
  apply_source_caps(items,[_src('wire','Wire',1)])
  self.assertEqual(items[1]['score'],90)
  self.assertEqual(items[1]['status'],'watch')
  self.assertEqual(items[1]['distribution'],'deferred')

 def test_caps_are_read_from_the_registry(self):
  from opportunity_radar.cli import source_index
  by_id,_,_=source_index([_src('a','A',3),_src('b','B',0)])
  self.assertEqual(by_id['a'].source_cap,3); self.assertEqual(by_id['b'].source_cap,0)

class ReportGuardTests(unittest.TestCase):
 def test_count_mismatch_keeps_the_previous_report(self):
  with tempfile.TemporaryDirectory() as d:
   latest=Path(d)/'latest-digest.txt'; latest.write_text('previous',encoding='utf-8')
   items=[{'title':'a','status':'watch'}]
   stats={'counts':{'priority':1,'watch':0,'filtered':0}}
   with self.assertRaises(ValueError):
    _write(d,'subject','【执行摘要】x','<!doctype html><html></html>',items=items,stats=stats)
   self.assertEqual(latest.read_text(encoding='utf-8'),'previous')
 def test_matching_counts_pass(self):
  with tempfile.TemporaryDirectory() as d:
   items=[{'title':'a','status':'watch'}]
   stats={'counts':{'priority':0,'watch':1,'filtered':0}}
   path,_=_write(d,'subject','【执行摘要】x','<!doctype html><html></html>',items=items,stats=stats)
   self.assertTrue(Path(path).exists())

class RenderOnlyUpgradeTests(unittest.TestCase):
 """Re-rendering a database written by the previous version must work unchanged."""
 def test_legacy_analysis_renders_and_routes_by_source(self):
  import io, json
  from contextlib import redirect_stdout
  from types import SimpleNamespace
  from opportunity_radar.store import Store
  from opportunity_radar.cli import _render_only
  with tempfile.TemporaryDirectory() as d:
   store=Store(str(Path(d)/'legacy.sqlite3'))
   a=SimpleNamespace(article_id='1',title='Why does meshing take hours?',url='https://example.invalid/a',
                     published='',source_name='ParaView Forum',summary='a body long enough to analyse')
   key=Store.key(a.url); store.save_article(a,key)
   # Shape written by the pre-lane version: no lane, no evidence_state, no source_id.
   store.save_analysis(key,{'summary_zh':'用户报告网格耗时','evidence_quotes':['a body long enough']},
                       {'score':61,'status':'watch','filter_reason':'','evidence_level':'summary',
                        'classification':{'article_type':'user_pain','source_quality':'first_party'},
                        'evidence':[{'id':'e1','quote':'a body long enough','field':'summary'}]},
                       {'model':'legacy-model','prompt_version':'3'})
   s=SimpleNamespace(report_dir=d)
   buf=io.StringIO()
   with redirect_stdout(buf): rc=_render_only(store,s,{'lanes':{}})
   out=buf.getvalue()
   self.assertEqual(rc,0)
   self.assertIn('E1 · 摘要引文已定位',out)
   self.assertIn('二、值得验证的商业机会',out)   # user_pain routes to lane B
   self.assertIn('legacy-model',out)
   self.assertTrue(Path(d,'latest-digest.txt').exists())
   self.assertTrue(Path(d,'latest-digest.html').exists())

class CallSiteTests(unittest.TestCase):
 """A mistyped keyword only fails when the pipeline actually runs."""
 def test_every_keyword_passed_to_evaluate_exists(self):
  import ast, inspect
  from opportunity_radar import cli
  params=set(inspect.signature(cli.evaluate).parameters)
  tree=ast.parse(inspect.getsource(cli)); checked=0
  for node in ast.walk(tree):
   if isinstance(node,ast.Call) and getattr(node.func,'id',None)=='evaluate':
    for kw in node.keywords:
     if kw.arg is None: continue
     checked+=1
     self.assertIn(kw.arg,params,f'unknown kwarg {kw.arg!r} at line {node.lineno}')
  self.assertGreater(checked,0,'no evaluate() call sites found')
