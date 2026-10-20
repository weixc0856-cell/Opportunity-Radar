import re
from datetime import datetime, timezone
from html import unescape
from .classifier import classify, _field

# Weights must match config/scoring.toml; the CLI passes the TOML values in so a config
# change actually changes the report instead of only the file.
DEFAULT_WEIGHTS={'demand_clarity':25,'payment_evidence':25,'actionability':20,'feasibility':20,'novelty':10}
DEFAULT_THRESHOLDS={'priority':75,'watch':55}
RULES_VERSION='v2'
UNKNOWN={'','unknown','none','n/a','na','null','未知','无','待验证','待补充'}
SPECIFIC_STEP=re.compile(r'\b(interview|survey|prototype|pilot|contact|reach out|test with|call|cold email)\b|访谈|试用|原型|联系|问卷|试点|小规模验证',re.I)
GENERIC_STEP=re.compile(r'\b(verify|research|investigate|check|review|monitor|explore|read|find)\b|研究|核实|了解|关注|调查|查阅',re.I)

def _unknown(v):
    return str(v or '').strip().lower() in UNKNOWN

def _specific(v,min_len=4):
    s=str(v or '').strip()
    return len(s)>=min_len and not _unknown(s)

def _norm(s):
    """Normalise HTML, entities, quote styles and whitespace before locating a quotation."""
    s=re.sub(r'<[^>]+>',' ',str(s or '')); s=unescape(s)
    s=s.replace('“','"').replace('”','"').replace('‘',"'").replace('’',"'")
    return re.sub(r'\s+',' ',s).strip().lower()

def evidence_level(a,article=None):
    """Classify where the quotes came from. A quote absent from the supplied text is not evidence."""
    quotes=[q.strip() for q in a.get('evidence_quotes',[]) if isinstance(q,str) and q.strip()]
    if not quotes: return 'none'
    title=_norm(_field(article,'title')); summary=_norm(_field(article,'summary'))
    seen_summary=False; seen_title=False
    unlocated=False
    for q in quotes:
        ql=_norm(q)
        if ql and ql in title: seen_title=True; continue
        if ql and summary and ql in summary: seen_summary=True; continue
        unlocated=True
    # A mixture of traceable and fabricated/unmatched quotations must not be treated
    # as fully traceable evidence. One valid quote cannot validate the others.
    if unlocated: return 'untraceable'
    if seen_summary: return 'summary'
    if seen_title: return 'title'
    return 'untraceable'

def evidence_items(a,article=None):
    """Give every quote a stable ID and a locator in the normalised title or summary."""
    title=_norm(_field(article,'title')); summary=_norm(_field(article,'summary'))
    out=[]
    for i,q in enumerate([q.strip() for q in a.get('evidence_quotes',[]) if isinstance(q,str) and q.strip()],1):
        ql=_norm(q)
        if ql and ql in title: field,pos='title',title.find(ql)
        elif ql and summary and ql in summary: field,pos='summary',summary.find(ql)
        else: field,pos='unlocated',-1
        out.append({'id':f'e{i}','quote':q,'field':field,'start':pos,'length':len(ql),'locator_basis':'normalized_text'})
    return out

def _demand(a,cls):
    # Base on the deterministic signal type, not on the model's own category label, which
    # tends to answer "service_opportunity" for almost everything.
    d={'payment_demand':3,'user_pain':3,'product_gap':2,'deployment_blocker':2,'tech_trend':1}.get(cls.get('signal_type'),1)
    if _specific(a.get('target_customer')): d+=1
    if _specific(a.get('pain_point'),10): d+=1
    return min(d,5)

def _payment(a,cls,quotes):
    # Score only deterministic evidence classifications from the source text.
    # A model's revenue_claim or a broad keyword such as 'pricing' must not create
    # direct payment evidence by itself.
    kind=str(cls.get('payment_evidence','none')).lower()
    return {'explicit_budget':5,'existing_purchase':5,'stated_willingness':4,
            'indirect':1,'none':0,'unknown':0}.get(kind,0)

def _action(a):
    step=str(a.get('suggested_next_step','') or '').strip()
    if not step or _unknown(step): return 0
    d=1
    if GENERIC_STEP.search(step): d=2
    if SPECIFIC_STEP.search(step): d=4
    if re.search(r'\d|至少|完成|截止|within|before|一周|两周',step): d=min(5,d+1)
    return min(d,5)

def _feasibility(a,cls):
    if cls.get('article_type')=='hiring': return 0
    d={'title_only':1,'rss_summary':2,'full_text':3}.get(cls.get('content_source'),2)
    if str(a.get('category','')).lower() in {'customer_pain','small_business','service_opportunity'}: d+=1
    if _specific(a.get('target_customer')): d+=1
    return min(d,5)

def _novelty(article,now=None):
    published=str(_field(article,'published') or '').strip()
    if not published: return 0
    try: ts=datetime.fromisoformat(published.replace('Z','+00:00'))
    except ValueError: return 0
    if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
    days=((now or datetime.now(timezone.utc))-ts).total_seconds()/86400
    if days<0: days=0
    return 5 if days<=1 else 4 if days<=3 else 3 if days<=7 else 2 if days<=30 else 1

def score_article(a,weights=None,article=None,classification=None,thresholds=None,now=None,source=None):
    """Deterministic 0-100 opportunity score. The model supplies judged fields; the rules decide the number."""
    w=dict(DEFAULT_WEIGHTS); w.update(weights or {})
    th=dict(DEFAULT_THRESHOLDS); th.update(thresholds or {})
    cls=classification or classify(article or {},a,source)
    quotes=[q for q in a.get('evidence_quotes',[]) if isinstance(q,str) and q.strip()]
    level=evidence_level(a,article)
    parts={'demand_clarity':_demand(a,cls),'payment_evidence':_payment(a,cls,quotes),
           'actionability':_action(a),'feasibility':_feasibility(a,cls),'novelty':_novelty(article,now)}
    total=sum(max(0,float(w.get(k,0))) for k in parts)
    if total <= 0:
        raise ValueError('Scoring weights must have a positive total')
    if any(float(w.get(k,0)) < 0 for k in parts):
        raise ValueError('Scoring weights cannot be negative')
    # Normalize weights so valid alternative weight sets still map to 0–100.
    raw=round(sum(parts[k]*max(0,float(w.get(k,0))) for k in parts)/total*20)
    # Untraceable or title-only evidence cannot reach "priority": cap it inside the watch band.
    capped=level not in {'summary','full_text'}
    if capped: raw=min(raw,th['priority']-1)
    if cls.get('article_type')=='hiring': raw=min(raw,th['watch']-1)
    score=max(0,min(100,raw))
    traceable=not capped
    if cls.get('article_type')=='hiring': status,reason='filtered','hiring'
    elif score>=th['priority']: status,reason='priority',''
    elif score>=th['watch']: status,reason='watch',''
    elif not cls.get('business_relevant'): status,reason='filtered','no_business_signal'
    elif not traceable: status,reason='filtered','content_insufficient'
    else: status,reason='filtered','low_score'
    risk='revenue_claim_without_evidence' if a.get('revenue_claim') not in {'none','unknown'} and not quotes else ''
    ev=evidence_items(a,article)
    integrity='no_evidence' if not ev else ('ok' if all(e['field']!='unlocated' for e in ev) else 'unlocated_quotes')
    return {'score':score,'components':parts,'status':status,'filter_reason':reason,
            'evidence_level':level,'classification':cls,'risk_flag':risk,
            'evidence':ev,'evidence_integrity':integrity,
            'verification_note':'待验证（缺少付费证据）' if parts['payment_evidence']==0 else '',
            'rules_version':RULES_VERSION,'thresholds':th,'weights':w,'capped_by_evidence':capped}
