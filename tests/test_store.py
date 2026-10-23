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

 def test_run_stage_and_recipient_delivery(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'run.sqlite3')); rid=s.start_run(stage='starting')
   s.update_run(rid,stage='analyzing',pid=123)
   latest=s.latest_run(); self.assertEqual(latest['stage'],'analyzing');self.assertEqual(latest['pid'],123)
   s.delivery(rid,'sent','',key='k1',recipient='a@example.com')
   s.delivery(rid,'failed','smtp boom',key='k1',recipient='b@example.com')
   self.assertEqual(s.sent_recipients('k1'),{'a@example.com'})
   rows=s.run_deliveries(rid); self.assertEqual([r['recipient'] for r in rows],['a@example.com','b@example.com'])
   s.finish_run(rid,'partial_failed',1,1,1,'one recipient failed',exit_code=1)
   latest=s.latest_run(); self.assertEqual(latest['status'],'partial_failed');self.assertEqual(latest['exit_code'],1);self.assertEqual(latest['stage'],'done')
 def test_active_run_detection(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'active.sqlite3')); rid=s.start_run()
   self.assertEqual(s.active_run()['run_id'],rid)
   s.finish_run(rid,'success',0,0,0)
   self.assertIsNone(s.active_run())

 def test_event_key_detects_duplicate_events(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'events.sqlite3'))
   base=dict(article_id='1',published='',source_name='s')
   a=SimpleNamespace(title='Same Event',summary='same text',url='https://example.invalid/a',**base)
   key=Store.key(a.url); s.save_article(a,key); s.save_analysis(key,{'category':'unknown'},{'score':10,'risk_flag':''})
   b=SimpleNamespace(title='Same  Event!',summary='same text',url='https://example.invalid/b',source_name='s',article_id='2',published='')
   key2=Store.key(b.url); s.save_article(b,key2)
   same=hashlib.sha256(b'same text').hexdigest(); changed=hashlib.sha256(b'changed').hexdigest()
   self.assertTrue(s.event_seen(Store.event_key(b.title),key2,same))
   self.assertFalse(s.event_seen(Store.event_key(b.title),key2,changed))

class EventSourceTests(unittest.TestCase):
 def test_prior_source_for_the_same_event_is_reported(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'event.sqlite3'))
   first=SimpleNamespace(article_id='1',title='Acme raises guidance',url='https://news.example/a',published='',source_name='News',summary='x')
   key=Store.key(first.url); s.save_article(first,key); s.save_analysis(key,{}, {'score':1,'risk_flag':''})
   second=SimpleNamespace(article_id='2',title='Acme raises guidance',url='https://other.example/b',published='',source_name='Other',summary='x')
   key2=Store.key(second.url); s.save_article(second,key2)
   self.assertEqual(s.event_sources(Store.event_key(second.title),key2),{'News'})
 def test_unrelated_article_is_not_corroboration(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'event.sqlite3'))
   a=SimpleNamespace(article_id='1',title='Acme raises guidance',url='https://news.example/a',published='',source_name='News',summary='x')
   key=Store.key(a.url); s.save_article(a,key); s.save_analysis(key,{}, {'score':1,'risk_flag':''})
   self.assertEqual(s.event_sources(Store.event_key('Something else entirely'),key),set())

class SchemaMigrationTests(unittest.TestCase):
 def test_reopening_the_database_is_idempotent(self):
  with tempfile.TemporaryDirectory() as d:
   path=str(Path(d)/'upgrade.sqlite3')
   first=Store(path)
   a=SimpleNamespace(article_id='1',title='t',url='https://example.invalid/a',published='',source_name='s',summary='x')
   key=Store.key(a.url); first.save_article(a,key)
   first.save_analysis(key,{'summary_zh':'x'},{'score':10,'risk_flag':''},{'input_hash':'h'})
   second=Store(path)   # re-runs CREATE TABLE IF NOT EXISTS and every ALTER guard
   third=Store(path)
   self.assertEqual(len(third.analysis_history(key)),1)
   with third.connect() as c:
    cols={r[1] for r in c.execute('PRAGMA table_info(runs)')}
   self.assertTrue({'report_path','stage','exit_code','pid'} <= cols)

class ReadOnlyStoreTests(unittest.TestCase):
 def test_read_only_store_refuses_writes(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as d:
   path=str(Path(d)/'x.sqlite3'); Store(path)
   ro=Store(path,read_only=True)
   with self.assertRaises(sqlite3.OperationalError):
    with ro.connect() as c: c.execute("INSERT INTO runs(started_at,status) VALUES('x','y')")
 def test_read_only_store_does_not_create_a_database(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'missing.sqlite3'
   ro=Store(path,read_only=True)
   self.assertFalse(path.exists())
   with self.assertRaises(Exception):
    with ro.connect() as c: c.execute('SELECT 1 FROM analyses')
   self.assertFalse(path.exists())
