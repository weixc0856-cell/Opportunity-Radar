import re
from datetime import datetime, timezone
from html import unescape
from .classifier import classify, _field
from .lanes import LANES, derive_lane
from .evidence import (LEGACY_LEVEL, content_basis, content_basis_estimate, state_for, rank_of,
                       rank_at_least, FULL_TEXT_MIN_CHARS)

# Weights, thresholds and the promotion gate are per lane; config/scoring.toml can
# override each one, and the CLI passes that config in so an edit changes the report.
RULES_VERSION='v4'
DEFAULT_LANE_WEIGHTS={
 'A':{'importance':25,'source_reliability':20,'evidence_completeness':20,'novelty':15,'relevance':10,'timeliness':10},
 'B':{'pain_severity':20,'buyer_clarity':15,'payment_evidence':25,'corroboration':15,'feasibility':10,'solution_gap':10,'novelty':5},
 'C':{'technical_maturity':25,'reproducibility':20,'impact_scope':20,'source_reliability':20,'novelty':15},
}
DEFAULT_LANE_THRESHOLDS={lane:{'priority':75,'watch':55} for lane in LANES}
# Minimum evidence rank before an item may leave the watch band. Lane A reports changes
# at companies and industries, where a located excerpt from a reliable source is already
# worth reading; B and C make claims about buyers and about behaviour, so they need the
# article body, not a teaser.
DEFAULT_PROMOTE_RANK={'A':'E1','B':'E2','C':'E2'}

UNKNOWN={'','unknown','none','n/a','na','null','未知','无','待验证','待补充'}
SPECIFIC_STEP=re.compile(r'\b(interview|survey|prototype|pilot|contact|reach out|test with|call|cold email)\b|访谈|试用|原型|联系|问卷|试点|小规模验证',re.I)
GENERIC_STEP=re.compile(r'\b(verify|research|investigate|check|review|monitor|explore|read|find)\b|研究|核实|了解|关注|调查|查阅',re.I)
REVENUE_EVIDENCE=re.compile(r'\b(\d+\s*-?\s*figure|revenue|income|sales|turnover|\$\s?\d|paid|subscription|pricing)\b|收入|营收|营业额|付费|订阅',re.I)


def _unknown(v):
    return str(v or '').strip().lower() in UNKNOWN


def _specific(v,min_len=4):
    s=str(v or '').strip()
    return len(s)>=min_len and not _unknown(s)


def _clamp(n):
    return max(0,min(5,n))


def _norm(s):
    """Normalise HTML, entities, quote styles and whitespace before locating a quotation."""
    s=re.sub(r'<[^>]+>',' ',str(s or '')); s=unescape(s)
    s=s.replace('“','"').replace('”','"').replace('‘',"'").replace('’',"'")
    return re.sub(r'\s+',' ',s).strip().lower()


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


def _evidence(a,article,source,cls,multi_source,min_chars):
    items=evidence_items(a,article)
    basis=content_basis(article,source,min_chars)
    estimate=content_basis_estimate(article,source,min_chars)
    state=state_for(basis,[e['field'] for e in items],multi_source=multi_source,
                    provenance=cls.get('source_quality',''))
    return items,basis,estimate,state


def evidence_level(a,article=None,source=None,multi_source=False):
    """Legacy E0/E1/E2 vocabulary, kept so archived analyses keep rendering."""
    items,basis,estimate,state=_evidence(a,article,source,{},multi_source,FULL_TEXT_MIN_CHARS)
    return LEGACY_LEVEL[state]


def evidence_state(a,article=None,source=None,multi_source=False,classification=None,
                   min_chars=FULL_TEXT_MIN_CHARS):
    """Explicit evidence state: what the supplied text can actually support."""
    return _evidence(a,article,source,classification or {},multi_source,min_chars)[3]


def _recency(article,now=None):
    published=str(_field(article,'published') or '').strip()
    if not published: return 0
    try: ts=datetime.fromisoformat(published.replace('Z','+00:00'))
    except ValueError: return 0
    if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
    days=((now or datetime.now(timezone.utc))-ts).total_seconds()/86400
    if days<0: days=0
    return 5 if days<=1 else 4 if days<=3 else 3 if days<=7 else 2 if days<=30 else 1


def _novelty(article,now=None,seen_before=None):
    # Incrementality, not just recency: an event already reported has less new to say.
    if seen_before is True: return 2
    if seen_before is False: return 5
    return _recency(article,now)


def _importance(a,cls):
    d={'funding':5,'product':4,'tech':3,'user_pain':3,'general':2,'hiring':0}.get(cls.get('article_type'),2)
    if cls.get('signal_type')=='payment_demand': d+=1
    if str(cls.get('buyer_type') or 'unknown')!='unknown': d+=1
    return _clamp(d)


def _source_reliability(cls):
    return {'first_party':5,'project_record':4,'secondhand_report':3,'vendor_marketing':2}.get(str(cls.get('source_quality') or ''),1)


def _completeness(rank):
    return {'E2':5,'E1':3}.get(rank,1)


def _relevance(a):
    v=a.get('relevance_score')
    if not isinstance(v,(int,float)): return 1
    return 5 if v>=80 else 4 if v>=60 else 3 if v>=40 else 2


def _pain_severity(a,cls):
    d={'payment_demand':4,'user_pain':4,'deployment_blocker':3,'product_gap':3,'tech_trend':1}.get(cls.get('signal_type'),1)
    if _specific(a.get('pain_point'),10): d+=1
    if cls.get('pain_evidence')=='repeated': d+=1
    return _clamp(d)


def _buyer_clarity(a,cls):
    d=3 if str(cls.get('buyer_type') or 'unknown')!='unknown' else 0
    if _specific(a.get('target_customer')): d+=2
    return _clamp(d)


def _buyer_payment(cls):
    """Only buyer-side evidence counts. A seller's price list is not a purchase."""
    return {'explicit_budget':5,'existing_purchase':5,'stated_willingness':4}.get(
        str(cls.get('buyer_payment_evidence') or 'none'),0)


def _corroboration(multi_source,quotes,cls):
    if multi_source: return 5
    if cls.get('pain_evidence')=='repeated': return 4
    if len(quotes)>=2: return 3
    if quotes: return 2
    return 1


def _feasibility(a,cls,basis):
    """Verification feasibility: how much text we hold, and whether the proposed next
    step is a concrete test rather than another round of reading."""
    if cls.get('article_type')=='hiring': return 0
    content={'title_only':1,'excerpt':2,'full_text':3}.get(basis,2)
    if _specific(a.get('target_customer')): content+=1
    return _clamp(round((content+_action(a))/2))


def _solution_gap(cls):
    d={'product_gap':4,'deployment_blocker':3,'payment_demand':3,'user_pain':2}.get(cls.get('signal_type'),1)
    if cls.get('adoption_signal')=='none' and cls.get('signal_type') in {'product_gap','deployment_blocker'}: d+=1
    return _clamp(d)


def _technical_maturity(cls):
    d={'tech':4,'product':4,'user_pain':3,'general':2,'funding':2}.get(cls.get('article_type'),2)
    if cls.get('signal_type')=='tech_trend': d+=1
    return _clamp(d)


def _impact_scope(a,cls):
    d=_relevance(a)
    if cls.get('buyer_type')=='engineering_team': d+=1
    return _clamp(d)


def _action(a):
    step=str(a.get('suggested_next_step','') or '').strip()
    if not step or _unknown(step): return 0
    d=1
    if GENERIC_STEP.search(step): d=2
    if SPECIFIC_STEP.search(step): d=4
    if re.search(r'\d|至少|完成|截止|within|before|一周|两周',step): d=min(5,d+1)
    return min(d,5)


def components(lane,a,cls,article,rank,basis,quotes,multi_source,now=None,seen_before=None):
    """Per-lane component scores, each 0-5. The lane decides what 'good' means."""
    if lane=='A':
        return {'importance':_importance(a,cls),'source_reliability':_source_reliability(cls),
                'evidence_completeness':_completeness(rank),'novelty':_novelty(article,now,seen_before),
                'relevance':_relevance(a),'timeliness':_recency(article,now)}
    if lane=='C':
        return {'technical_maturity':_technical_maturity(cls),'reproducibility':_completeness(rank),
                'impact_scope':_impact_scope(a,cls),'source_reliability':_source_reliability(cls),
                'novelty':_novelty(article,now,seen_before)}
    return {'pain_severity':_pain_severity(a,cls),'buyer_clarity':_buyer_clarity(a,cls),
            'payment_evidence':_buyer_payment(cls),'corroboration':_corroboration(multi_source,quotes,cls),
            'feasibility':_feasibility(a,cls,basis),'solution_gap':_solution_gap(cls),
            'novelty':_novelty(article,now,seen_before)}


def lane_config(lane,lanes_config=None,weights=None,thresholds=None):
    cfg=(lanes_config or {}).get(lane) or {}
    w=dict(DEFAULT_LANE_WEIGHTS[lane]); w.update(cfg.get('weights') or {})
    th=dict(DEFAULT_LANE_THRESHOLDS[lane]); th.update(cfg.get('thresholds') or {})
    promote=str(cfg.get('promote_rank') or DEFAULT_PROMOTE_RANK[lane]).upper()
    if weights: w.update({k:v for k,v in weights.items() if k in w})
    if thresholds: th.update(thresholds)
    return w,th,promote


def score_article(a,weights=None,article=None,classification=None,thresholds=None,now=None,
                  source=None,lane=None,lanes_config=None,multi_source=False,
                  event_seen_before=None,min_full_text_chars=FULL_TEXT_MIN_CHARS):
    """Deterministic 0-100 score inside one editorial lane.

    The model supplies judged fields; the rules decide the number, the lane and the
    evidence gate. Evidence rank is a hard gate, not a hint: E0 never enters the
    briefing, and a lane whose promotion gate is E2 caps E1 at the watch band.
    """
    cls=classification or classify(article or {},a,source)
    lane=lane if lane in LANES else derive_lane(article,a,source,cls)
    w,th,promote=lane_config(lane,lanes_config,weights,thresholds)
    quotes=[q for q in a.get('evidence_quotes',[]) if isinstance(q,str) and q.strip()]
    items,basis,estimate,state=_evidence(a,article,source,cls,multi_source,min_full_text_chars)
    rank=rank_of(state)
    parts=components(lane,a,cls,article,rank,basis,quotes,multi_source,now,event_seen_before)
    if any(float(w.get(k,0))<0 for k in parts):
        raise ValueError('Scoring weights cannot be negative')
    total=sum(max(0,float(w.get(k,0))) for k in parts)
    if total<=0:
        raise ValueError('Scoring weights must have a positive total')
    raw=round(sum(parts[k]*max(0,float(w.get(k,0))) for k in parts)/total*20)
    capped=not rank_at_least(rank,promote)
    if capped: raw=min(raw,th['priority']-1)
    if rank=='E0': raw=min(raw,th['watch']-1)
    if cls.get('article_type')=='hiring': raw=min(raw,th['watch']-1)
    score=max(0,min(100,raw))
    if cls.get('article_type')=='hiring': status,reason='filtered','hiring'
    elif rank=='E0': status,reason='filtered','insufficient_evidence'
    elif score>=th['priority']: status,reason='priority',''
    elif score>=th['watch']: status,reason='watch',''
    elif lane=='B' and not cls.get('business_relevant'): status,reason='filtered','no_business_signal'
    else: status,reason='filtered','low_score'
    claimed=str(a.get('revenue_claim','unknown')).lower()
    if claimed not in {'none','unknown'} and not quotes: risk='revenue_claim_without_evidence'
    elif claimed in {'none','unknown'} and any(REVENUE_EVIDENCE.search(q) for q in quotes): risk='revenue_evidence_contradicts_claim'
    else: risk=''
    integrity='no_evidence' if not items else ('ok' if all(e['field']!='unlocated' for e in items) else 'unlocated_quotes')
    return {'score':score,'components':parts,'status':status,'filter_reason':reason,'lane':lane,
            'evidence_level':LEGACY_LEVEL[state],'evidence_state':state,'evidence_rank':rank,
            'evidence_basis':basis,'content_basis_estimate':estimate,'classification':cls,'risk_flag':risk,
            'evidence':items,'evidence_integrity':integrity,
            'market_validation':('multi_source' if multi_source else
                                 'seller_claim' if cls.get('source_quality')=='vendor_marketing' else
                                 'buyer_confirmed' if cls.get('buyer_payment_evidence') in {'explicit_budget','existing_purchase'} else
                                 'single_source' if items else 'none'),
            'verification_note':'待验证（缺少买方付费证据）' if lane=='B' and parts.get('payment_evidence',0)==0 else '',
            'rules_version':RULES_VERSION,'thresholds':th,'weights':w,'promote_rank':promote,
            'capped_by_evidence':capped}
