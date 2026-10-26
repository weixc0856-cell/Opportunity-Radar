import json,re
from html import unescape
CATEGORIES={'customer_pain','small_business','market_change','service_opportunity','distribution','other','unknown'}
CLAIMS={'none','revenue','profit','market_size','mixed','unknown'}
CONFIDENCE={'low','medium','high'}
# Actionability is an observational field: it is recorded and evaluated offline, but it
# does not enter scoring, lanes, status or quotas. Old prompts that omit it stay valid.
ACTIONABILITY_LEVELS=('none','monitor','investigate','decide','act')
# v5: the model states relevance as a coarse enum instead of a 0-100 number. A number
# implied precision the model could not support, and it encouraged tuning the scale
# instead of the judgment. Old v4 records keep relevance_score and are read as before.
RELEVANCE_LEVELS=('core','adjacent','peripheral','none')
ACTION_KINDS={'verify','contact','test','monitor','decide'}
V5_SECTIONS=('facts','inferences','gaps','actions')
V4_REQUIRED={'category','summary_zh','pain_point','target_customer','commercial_signal','revenue_claim',
             'evidence_quotes','uncertainties','suggested_next_step','relevance_score','confidence'}


def _unwrap(raw):
    s=raw.strip()
    # Thinking models may prefix a <think>...</think> block even when asked for JSON only.
    s=re.sub(r'<think\b[^>]*>.*?</think\s*>','',s,flags=re.S|re.I).strip()
    if re.match(r'<think\b',s,flags=re.I):
        raise ValueError('Model output ended inside a thinking block, no JSON returned')
    fence=re.search(r'```(?:json)?\s*(.*?)```',s,flags=re.S|re.I)
    if fence: s=fence.group(1).strip()
    return s


def _repair_quotes(s):
    """Escape stray double quotes inside JSON string values.

    Small models occasionally emit a quote they should have escaped, e.g. mixing a Chinese
    quote with a plain one. Inside a string, a quote is only a terminator when the next
    non-space character is , : } ] or end-of-input; anything else is content.
    """
    out=[]; in_str=False; esc=False; n=len(s); i=0
    while i<n:
        ch=s[i]
        if esc: out.append(ch); esc=False; i+=1; continue
        if in_str and ch=='\\': out.append(ch); esc=True; i+=1; continue
        if ch=='"':
            if not in_str: in_str=True; out.append(ch); i+=1; continue
            j=i+1
            while j<n and s[j] in ' \t\r\n': j+=1
            if j>=n or s[j] in ',:}]': in_str=False; out.append(ch)
            else: out.append('\\"')
            i+=1; continue
        out.append(ch); i+=1
    return ''.join(out)


def _load_object(raw):
    s=_unwrap(raw)
    try: d=json.loads(s)
    except json.JSONDecodeError:
        # Last resort: take the outermost {...} span the model wrapped in prose.
        start,end=s.find('{'),s.rfind('}')
        if start<0 or end<=start: raise
        body=s[start:end+1]
        try: d=json.loads(body)
        except json.JSONDecodeError: d=json.loads(_repair_quotes(body))
    if not isinstance(d,dict): raise ValueError('Model output must be a JSON object')
    return d


def _article_field(article,name,default=''):
    if article is None: return default
    if isinstance(article,dict): return article.get(name,default) or default
    return getattr(article,name,default) or default


def _normalize(value):
    """Same normalisation the deterministic locator uses: tags stripped, entities and
    quote styles unified, whitespace collapsed, case folded."""
    s=re.sub(r'<[^>]+>',' ',str(value or '')); s=unescape(s)
    s=s.replace('“','"').replace('”','"').replace('‘',"'").replace('’',"'")
    return re.sub(r'\s+',' ',s).strip().lower()


def _locate(quote,title,summary):
    """Return {field,start,length} for an exact excerpt after normalisation, else None.

    The offset is computed on the normalised text, which is what the locator can prove;
    it is not an offset into the raw HTML.
    """
    q=_normalize(quote)
    if not q: return None
    t=_normalize(title)
    if t and q in t: return {'field':'title','start':t.find(q),'length':len(q)}
    s=_normalize(summary)
    if s and q in s: return {'field':'summary','start':s.find(q),'length':len(q)}
    return None


def _validate_base(d):
    if d['category'] not in CATEGORIES: raise ValueError('Invalid category')
    if d['revenue_claim'] not in CLAIMS: raise ValueError('Invalid revenue_claim')
    if d['confidence'] not in CONFIDENCE: raise ValueError('Invalid confidence')
    for k in ('summary_zh','pain_point','target_customer','commercial_signal'):
        if not isinstance(d[k],str) or len(d[k])>1200: raise ValueError(f'Invalid {k}')


def _normalize_actionability(d):
    # A non-scoring field must never fail an otherwise valid analysis. Missing or invalid
    # values are recorded as sentinels so the offline experiment can count them.
    action=d.get('actionability')
    if action is None:
        d['actionability']='missing'; d['actionability_status']='missing'
    elif isinstance(action,str) and action.strip().lower() in ACTIONABILITY_LEVELS:
        d['actionability']=action.strip().lower(); d['actionability_status']='ok'
    else:
        d['actionability']='invalid'; d['actionability_status']='invalid'


def _parse_v4(d):
    missing=V4_REQUIRED-d.keys()
    if missing: raise ValueError('Missing fields: '+', '.join(sorted(missing)))
    _validate_base(d)
    if not isinstance(d['relevance_score'],(int,float)) or not 0<=d['relevance_score']<=100: raise ValueError('Invalid relevance_score')
    if not isinstance(d['suggested_next_step'],str) or len(d['suggested_next_step'])>1200: raise ValueError('Invalid suggested_next_step')
    for k in ('evidence_quotes','uncertainties'):
        # Models sometimes collapse a one-item list into a bare string; that is a shape
        # deviation, not bad content, so wrap it instead of discarding the whole article.
        if isinstance(d[k],str): d[k]=[d[k]] if d[k].strip() else []
        if not isinstance(d[k],list) or len(d[k])>10 or any(not isinstance(x,str) or len(x)>500 for x in d[k]): raise ValueError(f'Invalid {k}')
    _normalize_actionability(d)
    d['schema_version']=4
    return d


def _int_basis(value,index,deviations):
    if not isinstance(value,list): return []
    out=[]
    for raw in value:
        try: out.append(int(raw))
        except (TypeError,ValueError):
            deviations.append({'section':'inferences','ordinal':index,'reason':'invalid_basis_index'})
    return out


def _string_list(value,index,section,deviations,limit=10,max_len=300):
    if isinstance(value,str): value=[value] if value.strip() else []
    if not isinstance(value,list):
        deviations.append({'section':section,'ordinal':index,'reason':'invalid_list'})
        return []
    return [str(x).strip()[:max_len] for x in value[:limit] if str(x).strip()]


def _parse_v5(d,article):
    required={'category','summary_zh','pain_point','target_customer','commercial_signal',
              'revenue_claim','confidence','relevance'}|set(V5_SECTIONS)
    missing=required-d.keys()
    if missing: raise ValueError('Missing fields: '+', '.join(sorted(missing)))
    _validate_base(d)
    relevance=str(d['relevance'] or '').strip().lower()
    if relevance not in RELEVANCE_LEVELS: raise ValueError('Invalid relevance')
    d['relevance']=relevance
    # A missing section or a section that is not a list is a structural violation: the
    # model did not follow the v5 contract, so retry rather than guessing.
    for key in V5_SECTIONS:
        if not isinstance(d[key],list): raise ValueError(f'Invalid {key}')

    title=_article_field(article,'title'); summary=_article_field(article,'summary')
    source_url=str(_article_field(article,'url') or '')
    published=str(_article_field(article,'published') or '')
    deviations=[]
    facts=[]
    for index,entry in enumerate(d['facts'],1):
        if not isinstance(entry,dict):
            deviations.append({'section':'facts','ordinal':index,'reason':'not_an_object'}); continue
        text=str(entry.get('text') or '').strip()
        if not text or len(text)>500:
            deviations.append({'section':'facts','ordinal':index,'reason':'invalid_text'}); continue
        quote=entry.get('quote')
        if not isinstance(quote,str) or not quote.strip():
            quote=''; status='unlocated'; reason='missing_quote'; locator=None
        else:
            quote=quote.strip()
            locator=_locate(quote,title,summary)
            status='located' if locator else 'unlocated'
            reason='' if locator else 'quote_not_in_text'
        facts.append({'ordinal':index,'text':text,'quote':quote,
                      'actor':str(entry.get('actor') or '').strip()[:200],
                      'status':status,'evidence_id':None,'locator':locator,'reason':reason,
                      'source_url':source_url,'published':published})
    # Evidence IDs are assigned only to located quotes, in fact order, deduplicated by
    # normalised text. The derived quote list is the ONLY evidence input for scoring.
    seen={}; evidence_quotes=[]
    for fact in facts:
        if fact['status']!='located': continue
        key=_normalize(fact['quote'])
        if key not in seen:
            seen[key]=f'e{len(seen)+1}'
            evidence_quotes.append(fact['quote'])
        fact['evidence_id']=seen[key]

    fact_by_ordinal={f['ordinal']:f for f in facts}
    inferences=[]
    for index,entry in enumerate(d['inferences'],1):
        if not isinstance(entry,dict):
            deviations.append({'section':'inferences','ordinal':index,'reason':'not_an_object'}); continue
        text=str(entry.get('text') or '').strip()
        if not text or len(text)>500:
            deviations.append({'section':'inferences','ordinal':index,'reason':'invalid_text'}); continue
        basis=_int_basis(entry.get('basis'),index,deviations)
        supported=bool(basis) and all(b in fact_by_ordinal and fact_by_ordinal[b]['status']=='located' for b in basis)
        confidence=str(entry.get('confidence') or '').strip().lower()
        if confidence not in CONFIDENCE:
            confidence='low'
            deviations.append({'section':'inferences','ordinal':index,'reason':'invalid_confidence'})
        assumptions=_string_list(entry.get('assumptions',[]),index,'inferences',deviations)
        inferences.append({'ordinal':index,'text':text,'basis':basis,'confidence':confidence,
                           'assumptions':assumptions,'status':'supported' if supported else 'unsupported'})

    gaps=[]
    for index,entry in enumerate(d['gaps'],1):
        if not isinstance(entry,dict):
            deviations.append({'section':'gaps','ordinal':index,'reason':'not_an_object'}); continue
        missing=str(entry.get('missing') or '').strip()
        if not missing:
            deviations.append({'section':'gaps','ordinal':index,'reason':'invalid_missing'}); continue
        gaps.append({'ordinal':index,'missing':missing[:500],
                     'why_it_matters':str(entry.get('why_it_matters') or '').strip()[:500],
                     'how_to_close':str(entry.get('how_to_close') or '').strip()[:500],
                     'status':'open'})

    actions=[]
    for index,entry in enumerate(d['actions'],1):
        if not isinstance(entry,dict):
            deviations.append({'section':'actions','ordinal':index,'reason':'not_an_object'}); continue
        step=str(entry.get('step') or '').strip()
        if not step:
            deviations.append({'section':'actions','ordinal':index,'reason':'invalid_step'}); continue
        kind=str(entry.get('kind') or '').strip().lower()
        if kind not in ACTION_KINDS:
            kind='monitor'
            deviations.append({'section':'actions','ordinal':index,'reason':'invalid_kind'})
        actions.append({'ordinal':index,'step':step[:500],'kind':kind,
                        'done_when':str(entry.get('done_when') or '').strip()[:500],'status':'open'})

    d['schema_version']=5
    d['facts']=facts; d['inferences']=inferences; d['gaps']=gaps; d['actions']=actions
    d['evidence_quotes']=evidence_quotes
    d['uncertainties']=[g['missing'] for g in gaps]
    d['suggested_next_step']=actions[0]['step'] if actions else ''
    d['schema_deviations']=deviations
    # The numeric relevance is gone in v5; keeping a stale value would let an old score
    # silently outrank the enum.
    d.pop('relevance_score',None)
    _normalize_actionability(d)
    return d


def parse_model_json(raw,article=None):
    """Parse one model response into a v4-compatible or v5 structured record.

    `article` supplies the text used to locate fact quotes (title/summary) and the
    program-owned source binding (url/published). It is optional so archived v4 outputs
    and offline fixtures can still be parsed.
    """
    d=_load_object(raw)
    # Presence of any v5 section means the model was answering the v5 contract; a missing
    # or malformed sibling section is a structural failure, not a v4 fallback.
    if any(key in d for key in V5_SECTIONS):
        return _parse_v5(d,article)
    return _parse_v4(d)
