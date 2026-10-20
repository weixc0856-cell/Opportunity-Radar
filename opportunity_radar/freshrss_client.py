import hashlib, json, urllib.parse, urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
@dataclass
class Article:
    article_id:str; title:str; url:str; summary:str; published:str; source_name:str='FreshRSS'; feed_id:str=''
    fetched_at:str=''; content_source:str=''; retrieval_status:str=''
class FreshRSSClient:
    """Fever API client; confirm API availability in the installed FreshRSS version."""
    def __init__(self,base_url,username,api_key,timeout=20):
        self.endpoint=base_url.rstrip('/')+'/api/fever.php'; self.username=username; self.api_key=api_key; self.timeout=timeout
    def _request(self,params):
        p=dict(params); p['api']=''; p['api_key']=hashlib.md5(f'{self.username}:{self.api_key}'.encode()).hexdigest()
        # FreshRSS reads api_key from $_POST only; a GET request always answers auth:0.
        body=urllib.parse.urlencode(p).encode('utf-8')
        req=urllib.request.Request(self.endpoint,data=body,headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'OpportunityRadar/0.1'},method='POST')
        with urllib.request.urlopen(req,timeout=self.timeout) as r: data=json.loads(r.read().decode('utf-8','replace'))
        if data.get('auth')==0: raise RuntimeError('FreshRSS Fever API authentication failed; verify API enablement and credentials.')
        if data.get('api') is False: raise RuntimeError('FreshRSS Fever API unavailable or disabled.')
        return data
    def _articles(self,data):
        feeds={str(x.get('id')):x.get('title','Unknown feed') for x in data.get('feeds',[])}; out=[]
        fetched=datetime.now(timezone.utc).isoformat()
        for x in data.get('items',[]):
            title=str(x.get('title','')).strip(); url=str(x.get('url','')).strip()
            if not title or not url.startswith('https://'): continue
            try: published=datetime.fromtimestamp(int(x.get('created_on_time',0)),tz=timezone.utc).isoformat()
            except (TypeError,ValueError,OSError): published=''
            summary=str(x.get('html') or x.get('description') or x.get('content') or '')
            has_text=bool(summary.strip())
            out.append(Article(str(x.get('id','')),title,url,summary[:12000],published,feeds.get(str(x.get('feed_id')),'FreshRSS feed'),str(x.get('feed_id','')),
                               fetched_at=fetched,content_source='rss_summary' if has_text else 'title_only',
                               retrieval_status='ok' if has_text else 'empty_content'))
        out.sort(key=lambda a:a.published,reverse=True); return out
    def list_feeds(self):
        """Return FreshRSS Fever API feed metadata for local source-to-feed mapping."""
        data = self._request({'feeds': '1'})
        out = []
        for item in data.get('feeds', []):
            feed_id = str(item.get('id', '')).strip()
            title = str(item.get('title', '')).strip()
            if feed_id and title:
                out.append({'id': feed_id, 'title': title, 'url': str(item.get('url', '')).strip(), 'site_url': str(item.get('site_url', '')).strip()})
        return out

    def _fetch_feed(self,feed_id=None):
        # Fever caps items at 50 and sorts since_id ascending, so since_id would pin us to the
        # oldest rows once the database grows. max_id returns the newest rows, descending.
        p={'items':'','feeds':'1','max_id':str(2**63-1)}
        if feed_id is not None: p['feed_ids']=str(feed_id)
        return self._articles(self._request(p))
    def fetch_articles(self,limit=10,feed_ids=None):
        if not feed_ids: return self._fetch_feed()[:limit]
        # One high-volume feed would otherwise fill the whole window; interleave per feed.
        queues=[self._fetch_feed(fid) for fid in feed_ids]; out=[]; seen=set()
        while len(out)<limit and any(queues):
            for q in queues:
                if not q: continue
                a=q.pop(0)
                if a.url in seen: continue
                seen.add(a.url); out.append(a)
                if len(out)>=limit: break
        return out
