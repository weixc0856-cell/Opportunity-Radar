from collections import Counter

FUNNEL_STEPS=('fetched','new','updated','queued','analyzed')
FUNNEL_LABELS={'fetched':'本轮获取','new':'新增','updated':'内容更新','queued':'进入分析','analyzed':'分析成功'}
EVIDENCE_ORDER=('full_text','summary','title','untraceable','none')

def funnel(stats):
    """Processing funnel. Every step comes from the same run, so the numbers are comparable."""
    counts=stats.get('counts',{})
    if stats.get('render_only'):
        # A re-render has no run of its own; show the stored set instead of fake zeros.
        return [('已保存分析',stats.get('analyzed',0)),('持续观察',counts.get('watch',0)),('优先验证',counts.get('priority',0))]
    alias={'fetched':stats.get('fetched',stats.get('article_count',0)),'new':stats.get('new',0),'updated':stats.get('updated',0),
           'queued':stats.get('queued',stats.get('analyzed_count',0)),'analyzed':stats.get('analyzed',stats.get('analyzed_count',0))}
    rows=[(FUNNEL_LABELS[k],alias[k]) for k in FUNNEL_STEPS]
    rows.append(('持续观察',counts.get('watch',0))); rows.append(('优先验证',counts.get('priority',0)))
    return rows

def source_breakdown(items):
    """Per-source analysed items and how many of their quotes could be located in the source text."""
    rows={}
    for x in items:
        name=x.get('source_name','Unknown')
        r=rows.setdefault(name,{'source':name,'items':0,'located':0,'evidence':0})
        r['items']+=1
        for e in x.get('evidence') or []:
            r['evidence']+=1
            if e.get('field')!='unlocated': r['located']+=1
    return sorted(rows.values(),key=lambda r:(-r['items'],r['source']))

def evidence_breakdown(items):
    c=Counter(x.get('evidence_level','none') for x in items)
    return [{'level':k,'count':c[k]} for k in EVIDENCE_ORDER if c[k]]

def denominator_note(stats):
    n=stats.get('analyzed',stats.get('analyzed_count',0))
    if stats.get('render_only'): return f'口径：数据库已保存的 {n} 条分析；未重新调用模型。'
    return f'口径：本轮进入分析的 {n} 条；已跳过与失败条目不计入分母。'
