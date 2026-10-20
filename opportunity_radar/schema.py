import json,re
CATEGORIES={'customer_pain','small_business','market_change','service_opportunity','distribution','other','unknown'}
CLAIMS={'none','revenue','profit','market_size','mixed','unknown'}
CONFIDENCE={'low','medium','high'}
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
def parse_model_json(raw):
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
    required={'category','summary_zh','pain_point','target_customer','commercial_signal','revenue_claim','evidence_quotes','uncertainties','suggested_next_step','relevance_score','confidence'}
    missing=required-d.keys()
    if missing: raise ValueError('Missing fields: '+', '.join(sorted(missing)))
    if d['category'] not in CATEGORIES: raise ValueError('Invalid category')
    if d['revenue_claim'] not in CLAIMS: raise ValueError('Invalid revenue_claim')
    if d['confidence'] not in CONFIDENCE: raise ValueError('Invalid confidence')
    if not isinstance(d['relevance_score'],(int,float)) or not 0<=d['relevance_score']<=100: raise ValueError('Invalid relevance_score')
    for k in ('summary_zh','pain_point','target_customer','commercial_signal','suggested_next_step'):
        if not isinstance(d[k],str) or len(d[k])>1200: raise ValueError(f'Invalid {k}')
    for k in ('evidence_quotes','uncertainties'):
        # Models sometimes collapse a one-item list into a bare string; that is a shape
        # deviation, not bad content, so wrap it instead of discarding the whole article.
        if isinstance(d[k],str): d[k]=[d[k]] if d[k].strip() else []
        if not isinstance(d[k],list) or len(d[k])>10 or any(not isinstance(x,str) or len(x)>500 for x in d[k]): raise ValueError(f'Invalid {k}')
    return d
