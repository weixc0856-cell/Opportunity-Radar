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
 def test_content_change_is_versioned_without_overwriting_article(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(str(Path(d)/'test.sqlite3'))
   base=dict(article_id='1',title='t',url='https://example.invalid/a',published='',source_name='s')
   a=SimpleNamespace(summary='first',fetched_at='2026-10-20T00:00:00+00:00',content_source='rss_summary',retrieval_status='ok',**base)
   key=Store.key(a.url); self.assertEqual(s.save_article(a,key),1)
   b=SimpleNamespace(summary='second',fetched_at='2026-10-21T00:00:00+00:00',content_source='rss_summary',retrieval_status='ok',**base)
   self.assertEqual(s.save_article(b,key),0)
   self.assertEqual(len(s.versions(key)),2)
   with s.connect() as c: row=c.execute('SELECT summary_hash FROM articles WHERE article_key=?',(key,)).fetchone()
   self.assertEqual(row['summary_hash'],hashlib.sha256(b'first').hexdigest())
 def test_old_articles_table_is_migrated(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'old.sqlite3'
   c=sqlite3.connect(p);c.execute('CREATE TABLE articles(article_key TEXT PRIMARY KEY, article_id TEXT, title TEXT NOT NULL, url TEXT NOT NULL, published TEXT, source_name TEXT, summary_hash TEXT, created_at TEXT NOT NULL)');c.commit();c.close()
   s=Store(str(p))
   with s.connect() as c: cols={r[1] for r in c.execute('PRAGMA table_info(articles)')}
   self.assertTrue({'fetched_at','content_source','retrieval_status'} <= cols)
