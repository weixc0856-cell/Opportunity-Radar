import hashlib, json, sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

def now(): return datetime.now(timezone.utc).isoformat()
class Store:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.init()
    @contextmanager
    def connect(self):
        # sqlite3's connection context manager commits but never closes, so open
        # the connection here and close it ourselves or Windows keeps the file locked.
        c=sqlite3.connect(self.path); c.row_factory=sqlite3.Row
        try:
            with c: yield c
        finally:
            c.close()
    def init(self):
        with self.connect() as c:
            c.executescript('''
        CREATE TABLE IF NOT EXISTS articles(article_key TEXT PRIMARY KEY, article_id TEXT, title TEXT NOT NULL, url TEXT NOT NULL, published TEXT, source_name TEXT, summary_hash TEXT, created_at TEXT NOT NULL, fetched_at TEXT, content_source TEXT, retrieval_status TEXT);
        CREATE TABLE IF NOT EXISTS article_versions(article_key TEXT NOT NULL, summary_hash TEXT NOT NULL, content_source TEXT, fetched_at TEXT, created_at TEXT NOT NULL, PRIMARY KEY(article_key,summary_hash));
        CREATE TABLE IF NOT EXISTS analyses(article_key TEXT PRIMARY KEY, result_json TEXT NOT NULL, score INTEGER NOT NULL, risk_flag TEXT, status TEXT NOT NULL, analyzed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, article_count INTEGER DEFAULT 0, analyzed_count INTEGER DEFAULT 0, error_count INTEGER DEFAULT 0, message TEXT);
        CREATE TABLE IF NOT EXISTS deliveries(delivery_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, sent_at TEXT, status TEXT NOT NULL, message TEXT);
        CREATE TABLE IF NOT EXISTS reviews(article_key TEXT PRIMARY KEY, label TEXT NOT NULL, note TEXT, reviewed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS review_history(id INTEGER PRIMARY KEY AUTOINCREMENT, article_key TEXT NOT NULL, previous_label TEXT, label TEXT NOT NULL, note TEXT, reviewed_at TEXT NOT NULL);''')
            cols={r[1] for r in c.execute('PRAGMA table_info(articles)')}
            for name in ('fetched_at','content_source','retrieval_status'):
                if name not in cols: c.execute(f'ALTER TABLE articles ADD COLUMN {name} TEXT')
    @staticmethod
    def key(url): return hashlib.sha256(url.strip().encode()).hexdigest()
    def analyzed(self,key):
        with self.connect() as c: return c.execute('SELECT 1 FROM analyses WHERE article_key=?',(key,)).fetchone() is not None
    def save_article(self,a,key):
        h=hashlib.sha256(a.summary.encode()).hexdigest()
        stamp=now(); fetched=getattr(a,'fetched_at','') or stamp
        has_text=bool(a.summary.strip())
        cs=getattr(a,'content_source','') or ('rss_summary' if has_text else 'title_only')
        rs=getattr(a,'retrieval_status','') or ('ok' if has_text else 'empty_content')
        with self.connect() as c:
            inserted=c.execute('INSERT OR IGNORE INTO articles(article_key,article_id,title,url,published,source_name,summary_hash,created_at,fetched_at,content_source,retrieval_status) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(key,a.article_id,a.title,a.url,a.published,a.source_name,h,stamp,fetched,cs,rs)).rowcount
            c.execute('INSERT OR IGNORE INTO article_versions(article_key,summary_hash,content_source,fetched_at,created_at) VALUES(?,?,?,?,?)',(key,h,cs,fetched,stamp))
            return inserted
    def versions(self,key):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT summary_hash,content_source,fetched_at,created_at FROM article_versions WHERE article_key=? ORDER BY created_at',(key,))]
    def save_analysis(self,key,result,score,meta=None):
        payload={'analysis':result,'scoring':score}
        if meta: payload['meta']=meta
        with self.connect() as c: c.execute('INSERT OR REPLACE INTO analyses VALUES(?,?,?,?,?,?)',(key,json.dumps(payload,ensure_ascii=False),score['score'],score.get('risk_flag',''),'ok',now()))
    def start_run(self):
        with self.connect() as c: return c.execute('INSERT INTO runs(started_at,status) VALUES(?,?)',(now(),'running')).lastrowid
    def finish_run(self,rid,status,ac,an,err,msg=''):
        with self.connect() as c: c.execute('UPDATE runs SET finished_at=?,status=?,article_count=?,analyzed_count=?,error_count=?,message=? WHERE run_id=?',(now(),status,ac,an,err,msg[:1000],rid))
    def delivery(self,rid,status,msg=''):
        with self.connect() as c: c.execute('INSERT INTO deliveries(run_id,sent_at,status,message) VALUES(?,?,?,?)',(rid,now(),status,msg[:1000]))
    def set_review(self,key,label,note=''):
        prev=self.get_review(key)
        with self.connect() as c:
            c.execute('INSERT INTO review_history(article_key,previous_label,label,note,reviewed_at) VALUES(?,?,?,?,?)',
                      (key,prev['label'] if prev else None,label,note[:2000],now()))
            c.execute('INSERT OR REPLACE INTO reviews VALUES(?,?,?,?)',(key,label,note[:2000],now()))
    def review_history(self,key):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT previous_label,label,note,reviewed_at FROM review_history WHERE article_key=? ORDER BY id',(key,))]
    def get_review(self,key):
        with self.connect() as c:
            r=c.execute('SELECT label,note,reviewed_at FROM reviews WHERE article_key=?',(key,)).fetchone()
            return dict(r) if r else None
    def list_analyses(self,limit=50):
        """Analysed articles with their machine verdict and human label, newest first."""
        with self.connect() as c:
            return [dict(r) for r in c.execute('''SELECT a.article_key,a.title,a.url,a.source_name,s.score,s.result_json,r.label,r.note
                FROM analyses s JOIN articles a USING(article_key) LEFT JOIN reviews r USING(article_key)
                ORDER BY s.analyzed_at DESC LIMIT ?''',(limit,))]
