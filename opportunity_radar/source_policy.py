from dataclasses import dataclass
import csv, os
from pathlib import Path

@dataclass(frozen=True)
class Source:
    source_id:str; name:str; homepage:str; feed_url:str; access_method:str; permission_status:str; enabled:bool
    freshrss_feed_id:str=''
    source_type:str=''; provenance_class:str=''; canonical_domain:str=''; terms_url:str=''; last_verified_at:str=''; reviewed_at:str=''; feed_provider:str=''; feed_provider_terms_url:str=''
    # Editorial governance: which channels a source may feed, how much of each article it
    # actually delivers, and how many items it may contribute per issue. These are review
    # decisions, not scraping settings.
    editorial_lanes:str=''; topic_tags:str=''; source_authority:str=''
    content_access_level:str='auto'; source_cap:int=0

def _g(r,k):
    return (r.get(k) or '').strip()

def _cap(value):
    try: return max(0,int(str(value or '0').strip() or 0))
    except (TypeError,ValueError): return -1

def load_sources(path=None):
    # A local registry keeps instance-specific Feed IDs and review dates out of the public repo.
    p=Path(path or os.environ.get('OR_SOURCES_PATH') or 'config/sources.csv')
    if not p.exists(): return []
    out=[]
    with p.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            out.append(Source(_g(r,'source_id'),_g(r,'name'),_g(r,'homepage'),_g(r,'feed_url'),
                              _g(r,'access_method').lower(),_g(r,'permission_status').lower() or 'disabled',
                              _g(r,'enabled').lower()=='true',_g(r,'freshrss_feed_id'),
                              _g(r,'source_type').lower(),_g(r,'provenance_class').lower(),
                              _g(r,'canonical_domain').lower(),_g(r,'terms_url'),_g(r,'last_verified_at'),_g(r,'reviewed_at'),_g(r,'feed_provider'),_g(r,'feed_provider_terms_url'),
                              _g(r,'editorial_lanes'),_g(r,'topic_tags'),_g(r,'source_authority'),
                              _g(r,'content_access_level').lower() or 'auto',_cap(_g(r,'source_cap'))))
    return out
def is_approved(s):
    return s.enabled and s.permission_status=='approved' and s.access_method in {'rss','atom','official_api','authorized_email_export'} and s.feed_url.startswith('https://') and bool(s.freshrss_feed_id)
