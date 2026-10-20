from dataclasses import dataclass
import csv
from pathlib import Path
@dataclass(frozen=True)
class Source:
    source_id:str; name:str; homepage:str; feed_url:str; access_method:str; permission_status:str; enabled:bool
    freshrss_feed_id:str=''
    source_type:str=''; provenance_class:str=''; canonical_domain:str=''; terms_url:str=''; last_verified_at:str=''
def _g(r,k):
    return (r.get(k) or '').strip()
def load_sources(path='config/sources.csv'):
    p=Path(path)
    if not p.exists(): return []
    out=[]
    with p.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            out.append(Source(_g(r,'source_id'),_g(r,'name'),_g(r,'homepage'),_g(r,'feed_url'),
                              _g(r,'access_method').lower(),_g(r,'permission_status').lower() or 'disabled',
                              _g(r,'enabled').lower()=='true',_g(r,'freshrss_feed_id'),
                              _g(r,'source_type').lower(),_g(r,'provenance_class').lower(),
                              _g(r,'canonical_domain').lower(),_g(r,'terms_url'),_g(r,'last_verified_at')))
    return out
def is_approved(s):
    return s.enabled and s.permission_status=='approved' and s.access_method in {'rss','atom','official_api','authorized_email_export'} and s.feed_url.startswith('https://') and bool(s.freshrss_feed_id)
