from collections import Counter
from .evidence import state_of
from .lanes import LANES, item_lane

FUNNEL_STEPS=('fetched','new','updated','queued','analyzed')
FUNNEL_LABELS={'fetched':'本轮获取','new':'新增','updated':'内容更新','queued':'进入分析','analyzed':'分析成功'}
# Strongest first, so a glance at the bar chart reads as an evidence ladder.
EVIDENCE_ORDER=('primary_source_located','multi_source_coverage','full_text_verified',
                'rss_excerpt_only','title_only','unlocated_quotes','none')

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

def lane_breakdown(items):
    """Per-lane totals, computed from the same records the report renders."""
    rows=[]
    for lane in LANES:
        group=[x for x in items if item_lane(x)==lane]
        rows.append({'lane':lane,'items':len(group),
                     'shown':sum(1 for x in group if x.get('status') in {'priority','watch'}),
                     'priority':sum(1 for x in group if x.get('status')=='priority')})
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
    c=Counter(state_of(x) for x in items)
    return [{'state':k,'count':c[k]} for k in EVIDENCE_ORDER if c[k]]

def denominator_note(stats):
    n=stats.get('analyzed',stats.get('analyzed_count',0))
    if stats.get('render_only'): return f'口径：数据库已保存的 {n} 条分析；未重新调用模型。'
    return f'口径：本轮进入分析的 {n} 条；已跳过与失败条目不计入分母。'
