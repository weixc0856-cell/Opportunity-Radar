import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from opportunity_radar.store import Store
from opportunity_radar.review import compute_stats

def row(label,status,key='k',signal='user_pain'):
    return {'article_key':key,'label':label,'score':70,'source_name':'s','title':'t','note':'',
            'result_json':json.dumps({'scoring':{'status':status,'classification':{'signal_type':signal}}})}

class StatsTests(unittest.TestCase):
 def test_counts_hits_and_false_positives(self):
  rows=[row('real_pain','watch','a'),row('real_pain','filtered','b'),
        row('irrelevant','watch','c'),row('technical_reference','filtered','d')]
  s=compute_stats(rows)
  self.assertEqual(s['reviewed'],4);self.assertEqual(s['candidates'],2)
  self.assertEqual(s['false_positives'],1);self.assertEqual(s['demand'],2);self.assertEqual(s['hits'],1)
 def test_ignores_unreviewed(self):
  s=compute_stats([row(None,'watch','x')])
  self.assertEqual(s['reviewed'],0);self.assertEqual(s['candidates'],0)
 def test_signal_cross_table(self):
  s=compute_stats([row('real_pain','watch','a','user_pain'),row('irrelevant','watch','b','tech_trend')])
  self.assertEqual(s['signal_cross'][('user_pain','real_pain')],1)
  self.assertEqual(s['signal_cross'][('tech_trend','irrelevant')],1)

class StoreReviewTests(unittest.TestCase):
 def test_review_roundtrip_and_replace(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'t.sqlite3'))
   a=SimpleNamespace(article_id='1',title='t',url='https://example.invalid/a',published='',source_name='s',summary='x')
   key=Store.key(a.url); s.save_article(a,key)
   s.save_analysis(key,{'category':'unknown'},{'score':10,'risk_flag':''})
   s.set_review(key,'weak_evidence','needs more')
   self.assertEqual(s.get_review(key)['label'],'weak_evidence')
   s.set_review(key,'real_pain','confirmed')
   self.assertEqual(s.get_review(key)['note'],'confirmed')
   rows=s.list_analyses(10); self.assertEqual(rows[0]['label'],'real_pain'); self.assertEqual(rows[0]['score'],10)
 def test_review_history_keeps_previous_labels(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'t.sqlite3'))
   a=SimpleNamespace(article_id='1',title='t',url='https://example.invalid/a',published='',source_name='s',summary='x')
   key=Store.key(a.url); s.save_article(a,key); s.save_analysis(key,{'category':'unknown'},{'score':10,'risk_flag':''})
   s.set_review(key,'weak_evidence','first pass'); s.set_review(key,'real_pain','confirmed')
   h=s.review_history(key)
   self.assertEqual(len(h),2)
   self.assertIsNone(h[0]['previous_label']);self.assertEqual(h[0]['label'],'weak_evidence')
   self.assertEqual(h[1]['previous_label'],'weak_evidence');self.assertEqual(h[1]['label'],'real_pain')
 def test_analysis_meta_is_persisted(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'t.sqlite3'))
   a=SimpleNamespace(article_id='1',title='t',url='https://example.invalid/a',published='',source_name='s',summary='x')
   key=Store.key(a.url); s.save_article(a,key)
   s.save_analysis(key,{'category':'unknown'},{'score':10,'risk_flag':''},{'model':'qwen','prompt_version':1})
   meta=json.loads(s.list_analyses(1)[0]['result_json'])['meta']
   self.assertEqual(meta['model'],'qwen');self.assertEqual(meta['prompt_version'],1)
