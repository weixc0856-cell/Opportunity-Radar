import hashlib,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from opportunity_radar.store import Store
class Tests(unittest.TestCase):
 def test_run_lifecycle(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'test.sqlite3'));rid=s.start_run();s.finish_run(rid,'success',2,1,1)
   with s.connect() as c:r=c.execute('SELECT status,article_count FROM runs WHERE run_id=?',(rid,)).fetchone()
   self.assertEqual(r['status'],'success');self.assertEqual(r['article_count'],2)
 def test_save_article_reports_whether_new(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'test.sqlite3'))
   a=SimpleNamespace(article_id='1',title='t',url='https://example.invalid/a',published='',source_name='s',summary='x')
   self.assertEqual(s.save_article(a,Store.key(a.url)),1)
   self.assertEqual(s.save_article(a,Store.key(a.url)),0)
 def test_content_change_is_versioned_and_current_metadata_updates(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'test.sqlite3'))
   base=dict(article_id='1',title='t',url='https://example.invalid/a',published='',source_name='s')
   a=SimpleNamespace(summary='first',fetched_at='2026-10-20T00:00:00+00:00',content_source='rss_summary',retrieval_status='ok',**base)
   key=Store.key(a.url); self.assertEqual(s.save_article(a,key),1)
   b=SimpleNamespace(summary='second',fetched_at='2026-10-21T00:00:00+00:00',content_source='rss_summary',retrieval_status='ok',**base)
   self.assertEqual(s.save_article(b,key),0)
   self.assertEqual(len(s.versions(key)),2)
   with s.connect() as c: row=c.execute('SELECT summary_hash FROM articles WHERE article_key=?',(key,)).fetchone()
   self.assertEqual(row['summary_hash'],hashlib.sha256(b'second').hexdigest())
 def test_analysis_history_preserves_replaced_results(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'history.sqlite3')); key=Store.key('https://example.invalid/a')
   s.save_analysis(key,{'summary_zh':'first'},{'score':10,'risk_flag':''},{'input_hash':'hash1'})
   s.save_analysis(key,{'summary_zh':'second'},{'score':20,'risk_flag':''},{'input_hash':'hash2'})
   self.assertEqual(s.analysis_input_hash(key),'hash2')
   history=s.analysis_history(key)
   self.assertEqual(len(history),2)
   self.assertEqual([x['score'] for x in reversed(history)],[10,20])
 def test_source_update_invalidates_current_review(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'review.sqlite3')); key=Store.key('https://example.invalid/a')
   a=SimpleNamespace(article_id='1',title='t',url='https://example.invalid/a',published='',source_name='s',summary='x')
   s.save_article(a,key); s.save_analysis(key,{'category':'unknown'},{'score':10,'risk_flag':''})
   s.set_review(key,'real_pain','checked')
   self.assertTrue(s.invalidate_review(key))
   self.assertIsNone(s.get_review(key))
   self.assertEqual(s.review_history(key)[-1]['label'],'stale_after_source_update')
 def test_old_articles_table_is_migrated(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old.sqlite3'
   c=sqlite3.connect(p);c.execute('CREATE TABLE articles(article_key TEXT PRIMARY KEY, article_id TEXT, title TEXT NOT NULL, url TEXT NOT NULL, published TEXT, source_name TEXT, summary_hash TEXT, created_at TEXT NOT NULL)');c.commit();c.close()
   s=Store(str(p))
   with s.connect() as c: cols={r[1] for r in c.execute('PRAGMA table_info(articles)')}
   self.assertTrue({'fetched_at','content_source','retrieval_status'} <= cols)
 def test_run_records_report_and_delivery_is_idempotent(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'run.sqlite3')); rid=s.start_run()
   s.finish_run(rid,'success',1,1,0,'','reports/archive/2026-10-20-083000.txt','abc123')
   with s.connect() as c: row=c.execute('SELECT report_path,report_hash FROM runs WHERE run_id=?',(rid,)).fetchone()
   self.assertEqual(row['report_path'],'reports/archive/2026-10-20-083000.txt');self.assertEqual(row['report_hash'],'abc123')
   self.assertFalse(s.delivery_sent('k1'))
   s.delivery(rid,'sent','',key='k1')
   self.assertTrue(s.delivery_sent('k1'))
   s.delivery(rid,'skipped_duplicate','',key='k2')
   self.assertFalse(s.delivery_sent('k2'))
 def test_consecutive_failures_resets_after_success(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'fail.sqlite3'))
   for status in ('failed','failed','success','failed'):
    rid=s.start_run(); s.finish_run(rid,status,0,0,1 if status!='success' else 0)
   self.assertEqual(s.consecutive_failures(),1)
