import hashlib, json, re, sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

def now(): return datetime.now(timezone.utc).isoformat()
class Store:
    def __init__(self,path,read_only=False):
        # read_only skips init(): a re-render must not migrate the schema or backfill rows.
        self.path=Path(path); self.read_only=read_only
        if not read_only:
            self.path.parent.mkdir(parents=True,exist_ok=True); self.init()
    @contextmanager
    def connect(self):
        # sqlite3's connection context manager commits but never closes, so open
        # the connection here and close it ourselves or Windows keeps the file locked.
        c=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True) if self.read_only else sqlite3.connect(self.path)
        c.row_factory=sqlite3.Row
        try:
            with c: yield c
        finally:
            c.close()
    def init(self):
        with self.connect() as c:
            c.executescript('''
        CREATE TABLE IF NOT EXISTS articles(article_key TEXT PRIMARY KEY, article_id TEXT, title TEXT NOT NULL, url TEXT NOT NULL, published TEXT, source_name TEXT, summary_hash TEXT, created_at TEXT NOT NULL, fetched_at TEXT, content_source TEXT, retrieval_status TEXT, event_key TEXT);
        CREATE TABLE IF NOT EXISTS article_versions(article_key TEXT NOT NULL, summary_hash TEXT NOT NULL, content_source TEXT, fetched_at TEXT, created_at TEXT NOT NULL, PRIMARY KEY(article_key,summary_hash));
        CREATE TABLE IF NOT EXISTS analyses(article_key TEXT PRIMARY KEY, result_json TEXT NOT NULL, score INTEGER NOT NULL, risk_flag TEXT, status TEXT NOT NULL, analyzed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS analysis_history(history_id INTEGER PRIMARY KEY AUTOINCREMENT, article_key TEXT NOT NULL, result_json TEXT NOT NULL, score INTEGER NOT NULL, risk_flag TEXT, status TEXT NOT NULL, analyzed_at TEXT NOT NULL, UNIQUE(article_key,analyzed_at));
        CREATE TABLE IF NOT EXISTS runs(run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, article_count INTEGER DEFAULT 0, analyzed_count INTEGER DEFAULT 0, error_count INTEGER DEFAULT 0, message TEXT, report_path TEXT, report_hash TEXT, stage TEXT, exit_code INTEGER, pid INTEGER);
        CREATE TABLE IF NOT EXISTS deliveries(delivery_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, sent_at TEXT, status TEXT NOT NULL, message TEXT, idempotency_key TEXT, recipient TEXT);
        CREATE TABLE IF NOT EXISTS reviews(article_key TEXT PRIMARY KEY, label TEXT NOT NULL, note TEXT, reviewed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS review_history(id INTEGER PRIMARY KEY AUTOINCREMENT, article_key TEXT NOT NULL, previous_label TEXT, label TEXT NOT NULL, note TEXT, reviewed_at TEXT NOT NULL);''')
            cols={r[1] for r in c.execute('PRAGMA table_info(articles)')}
            for name in ('fetched_at','content_source','retrieval_status','event_key'):
                if name not in cols: c.execute(f'ALTER TABLE articles ADD COLUMN {name} TEXT')
            for table,extra in (('runs',(('report_path','TEXT'),('report_hash','TEXT'),('stage','TEXT'),('exit_code','INTEGER'),('pid','INTEGER'))),('deliveries',(('idempotency_key','TEXT'),('recipient','TEXT')))):
                have={r[1] for r in c.execute(f'PRAGMA table_info({table})')}
                for name,typ in extra:
                    if name not in have: c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {typ}')
            # Backfill the current analysis once so pre-upgrade results have a history entry.
            c.execute('''INSERT OR IGNORE INTO analysis_history(article_key,result_json,score,risk_flag,status,analyzed_at)
                         SELECT article_key,result_json,score,risk_flag,status,analyzed_at FROM analyses''')
    @staticmethod
    def key(url): return hashlib.sha256(url.strip().encode()).hexdigest()
    @staticmethod
    def event_key(title):
        s=re.sub(r'[^0-9a-z一-鿿]+',' ',str(title or '').lower())
        return hashlib.sha256(re.sub(r'\s+',' ',s).strip().encode()).hexdigest()
    def event_seen(self,event_key,article_key,summary_hash):
        """True when another analysed article has the same normalised title and identical content."""
        with self.connect() as c:
            row=c.execute('''SELECT 1 FROM articles a JOIN analyses s USING(article_key)
                             WHERE a.event_key=? AND a.article_key<>? AND a.summary_hash=? LIMIT 1''',(event_key,article_key,summary_hash)).fetchone()
            return row is not None
    def event_sources(self,event_key,article_key):
        """Distinct sources that already hold an analysed article for the same event.

        Two sources reporting one event is corroboration; the same feed reporting it
        twice is not, so the result is keyed by source name rather than by article.
        """
        if not event_key: return set()
        with self.connect() as c:
            rows=c.execute("SELECT DISTINCT a.source_name FROM articles a JOIN analyses s USING(article_key) "
                           "WHERE a.event_key=? AND a.article_key<>? AND a.source_name IS NOT NULL",
                           (event_key,article_key)).fetchall()
        return {r['source_name'] for r in rows if (r['source_name'] or '').strip()}
    def analyzed(self,key):
        with self.connect() as c: return c.execute('SELECT 1 FROM analyses WHERE article_key=?',(key,)).fetchone() is not None
    def save_article(self,a,key):
        h=hashlib.sha256(a.summary.encode()).hexdigest()
        stamp=now(); fetched=getattr(a,'fetched_at','') or stamp
        has_text=bool(a.summary.strip())
        cs=getattr(a,'content_source','') or ('rss_summary' if has_text else 'title_only')
        rs=getattr(a,'retrieval_status','') or ('ok' if has_text else 'empty_content')
        with self.connect() as c:
            ekey=self.event_key(a.title)
            inserted=c.execute('INSERT OR IGNORE INTO articles(article_key,article_id,title,url,published,source_name,summary_hash,created_at,fetched_at,content_source,retrieval_status,event_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(key,a.article_id,a.title,a.url,a.published,a.source_name,h,stamp,fetched,cs,rs,ekey)).rowcount
            c.execute('INSERT OR IGNORE INTO article_versions(article_key,summary_hash,content_source,fetched_at,created_at) VALUES(?,?,?,?,?)',(key,h,cs,fetched,stamp))
            if not inserted:
                # articles is the current metadata row; article_versions preserves each observed content hash.
                c.execute('''UPDATE articles SET article_id=?,title=?,url=?,published=?,source_name=?,summary_hash=?,
                             fetched_at=?,content_source=?,retrieval_status=?,event_key=? WHERE article_key=?''',
                          (a.article_id,a.title,a.url,a.published,a.source_name,h,fetched,cs,rs,ekey,key))
            return inserted
    def versions(self,key):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT summary_hash,content_source,fetched_at,created_at FROM article_versions WHERE article_key=? ORDER BY created_at',(key,))]
    def latest_version_hash(self,key):
        with self.connect() as c:
            row=c.execute('SELECT summary_hash FROM article_versions WHERE article_key=? ORDER BY created_at DESC LIMIT 1',(key,)).fetchone()
            return row['summary_hash'] if row else None
    def analysis_input_hash(self,key):
        with self.connect() as c:
            row=c.execute('SELECT result_json FROM analyses WHERE article_key=?',(key,)).fetchone()
            if not row: return None
            try:
                payload=json.loads(row['result_json'])
                return payload.get('meta',{}).get('input_hash')
            except (ValueError,TypeError):
                return None
    def save_analysis(self,key,result,score,meta=None):
        payload={'analysis':result,'scoring':score}
        if meta: payload['meta']=meta
        stamp=now(); raw=json.dumps(payload,ensure_ascii=False)
        with self.connect() as c:
            row=(key,raw,score['score'],score.get('risk_flag',''),'ok',stamp)
            c.execute('INSERT OR IGNORE INTO analysis_history(article_key,result_json,score,risk_flag,status,analyzed_at) VALUES(?,?,?,?,?,?)',row)
            c.execute('INSERT OR REPLACE INTO analyses VALUES(?,?,?,?,?,?)',row)
    def analysis_history(self,key,limit=20):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT history_id,result_json,score,risk_flag,status,analyzed_at FROM analysis_history WHERE article_key=? ORDER BY analyzed_at DESC LIMIT ?',(key,limit))]
    def start_run(self,stage='starting'):
        with self.connect() as c: return c.execute('INSERT INTO runs(started_at,status,stage) VALUES(?,?,?)',(now(),'running',stage)).lastrowid
    def update_run(self,rid,stage=None,pid=None,status=None):
        sets=[]; vals=[]
        if stage is not None: sets.append('stage=?'); vals.append(stage)
        if pid is not None: sets.append('pid=?'); vals.append(pid)
        if status is not None: sets.append('status=?'); vals.append(status)
        if not sets: return
        vals.append(rid)
        with self.connect() as c: c.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id=?",vals)
    def finish_run(self,rid,status,ac,an,err,msg='',report_path='',report_hash='',exit_code=None):
        with self.connect() as c: c.execute('UPDATE runs SET finished_at=?,status=?,article_count=?,analyzed_count=?,error_count=?,message=?,report_path=?,report_hash=?,exit_code=?,stage=? WHERE run_id=?',(now(),status,ac,an,err,msg[:1000],report_path or '',report_hash or '',exit_code,'done',rid))
    def latest_run(self):
        with self.connect() as c:
            r=c.execute('SELECT * FROM runs ORDER BY run_id DESC LIMIT 1').fetchone()
            return dict(r) if r else None
    def active_run(self,max_age_minutes=180):
        """A running row younger than the limit is treated as active across admin restarts."""
        with self.connect() as c:
            r=c.execute("SELECT * FROM runs WHERE status='running' ORDER BY run_id DESC LIMIT 1").fetchone()
        if not r: return None
        try:
            started=datetime.fromisoformat(r['started_at'])
            if (datetime.now(timezone.utc)-started).total_seconds()>max_age_minutes*60: return None
        except (ValueError,TypeError): pass
        return dict(r)
    def delivery(self,rid,status,msg='',key='',recipient=''):
        with self.connect() as c: c.execute('INSERT INTO deliveries(run_id,sent_at,status,message,idempotency_key,recipient) VALUES(?,?,?,?,?,?)',(rid,now(),status,msg[:1000],key or '',recipient or ''))
    def delivery_sent(self,key):
        if not key: return False
        with self.connect() as c: return c.execute("SELECT 1 FROM deliveries WHERE idempotency_key=? AND status='sent'",(key,)).fetchone() is not None
    def sent_recipients(self,key):
        if not key: return set()
        with self.connect() as c:
            return {r['recipient'].casefold() for r in c.execute("SELECT recipient FROM deliveries WHERE idempotency_key=? AND status='sent' AND recipient IS NOT NULL AND recipient<>''",(key,))}
    def run_deliveries(self,rid):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT delivery_id,run_id,sent_at,status,message,recipient,idempotency_key FROM deliveries WHERE run_id=? ORDER BY delivery_id',(rid,))]
    def latest_deliveries(self):
        r=self.latest_run()
        return self.run_deliveries(r['run_id']) if r else []
    def consecutive_failures(self):
        with self.connect() as c:
            rows=[r['status'] for r in c.execute("SELECT status FROM runs WHERE status IN ('success','no_new_content','failed','analysis_failed','partial_failed') ORDER BY run_id DESC LIMIT 30")]
        n=0
        for status in rows:
            if status in {'failed','analysis_failed','partial_failed'}: n+=1
            else: break
        return n
    def invalidate_review(self,key,note='Source content changed; review is stale'):
        prev=self.get_review(key)
        if not prev: return False
        with self.connect() as c:
            c.execute('INSERT INTO review_history(article_key,previous_label,label,note,reviewed_at) VALUES(?,?,?,?,?)',
                      (key,prev['label'],'stale_after_source_update',note[:2000],now()))
            c.execute('DELETE FROM reviews WHERE article_key=?',(key,))
        return True
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
