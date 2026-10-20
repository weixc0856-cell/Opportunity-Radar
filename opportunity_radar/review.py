import argparse, json, sys
from collections import Counter
from .config import Settings
from .digest import STATUS_LABEL
from .store import Store

# Human labels are the ground truth the machine is measured against.
LABELS={
    'real_pain':'真实问题，原文证据充分',
    'commercial_intent':'出现采购、预算或付费意愿',
    'competitive_signal':'竞品或解决方案发布',
    'technical_reference':'技术参考，不构成商业机会',
    'weak_evidence':'可能有价值，但证据不足',
    'irrelevant':'与当前个人变现方向无关',
}
CANDIDATE={'priority','watch'}
DEMAND={'real_pain','commercial_intent'}
NOISE={'irrelevant','weak_evidence'}

def _status(row):
    try: return json.loads(row['result_json']).get('scoring',{}).get('status','')
    except (ValueError,TypeError): return ''

def _signal(row):
    try: return json.loads(row['result_json']).get('scoring',{}).get('classification',{}).get('signal_type','-')
    except (ValueError,TypeError): return '-'

def _short(key): return key[:8]

def _line(i,r):
    st=_status(r); label=r.get('label') or '-'
    return f"{i:>2} | {int(r['score'] or 0):>3} | {STATUS_LABEL.get(st,st or '-'):<4} | {label:<18} | {_short(r['article_key'])} | {r['source_name'][:20]:<20} | {r['title'][:60]}"

def cmd_list(store,limit):
    rows=store.list_analyses(limit)
    if not rows: print('没有已分析的文章。'); return 0
    print('  # | 分数 | 状态 | 人工标签           | key      | 来源                 | 标题')
    print('-'*130)
    for i,r in enumerate(rows,1): print(_line(i,r))
    print(f'\n共 {len(rows)} 条。用 review label <key前缀> <标签> 记录人工判断。可用标签：')
    for k,v in LABELS.items(): print(f'  {k:<20} {v}')
    return 0

def cmd_label(store,prefix,label,note):
    if label not in LABELS:
        print(f'未知标签：{label}。可用：{", ".join(LABELS)}',file=sys.stderr); return 2
    rows=store.list_analyses(500)
    matches=[r for r in rows if r['article_key'].startswith(prefix)]
    if len(matches)!=1:
        print(f'key 前缀 {prefix!r} 匹配到 {len(matches)} 条，请提供更精确的前缀。',file=sys.stderr); return 2
    r=matches[0]; store.set_review(r['article_key'],label,note)
    print(f"已记录：{_short(r['article_key'])} → {label}（{LABELS[label]}）")
    print(f"  {r['title']}")
    return 0

def compute_stats(rows):
    reviewed=[r for r in rows if r.get('label')]
    cand=[r for r in reviewed if _status(r) in CANDIDATE]
    demand=[r for r in reviewed if r['label'] in DEMAND]
    return {'analyzed':len(rows),'reviewed':len(reviewed),
            'labels':Counter(r['label'] for r in reviewed),
            'candidates':len(cand),
            'false_positives':sum(1 for r in cand if r['label'] in NOISE),
            'demand':len(demand),
            'hits':sum(1 for r in demand if _status(r) in CANDIDATE),
            'cross':Counter((_status(r) or '-',r['label']) for r in reviewed),
            'signal_cross':Counter((_signal(r),r['label']) for r in reviewed)}

def cmd_stats(store):
    rows=store.list_analyses(1000); st=compute_stats(rows)
    print(f"已分析 {st['analyzed']} 条，已复核 {st['reviewed']} 条。")
    if not st['reviewed']: print('还没有人工标签。先运行 review list 和 review label。'); return 0
    print('\n标签分布：')
    for k,v in st['labels'].most_common(): print(f'  {k:<20} {v:>3}  {LABELS.get(k,"")}')
    print('\n机器排序对照：')
    if st['candidates']: print(f"  机器候选 {st['candidates']} 条，人工判为噪声 {st['false_positives']} 条 → 误报率 {100*st['false_positives']/st['candidates']:.0f}%")
    else: print('  机器候选 0 条')
    if st['demand']: print(f"  人工认定需求 {st['demand']} 条，机器排在候选区 {st['hits']} 条 → 命中率 {100*st['hits']/st['demand']:.0f}%")
    else: print('  人工认定需求 0 条')
    print('\n机器状态 × 人工标签：')
    for (status,label),n in sorted(st['cross'].items()): print(f'  {STATUS_LABEL.get(status,status):<6} {label:<20} {n}')
    print('\n机器信号分类 × 人工标签：')
    for (signal,label),n in sorted(st['signal_cross'].items()): print(f'  {signal:<20} {label:<20} {n}')
    return 0

def main(argv=None):
    p=argparse.ArgumentParser(prog='opportunity_radar.review',description='人工复核机会信号')
    sub=p.add_subparsers(dest='cmd',required=True)
    lp=sub.add_parser('list'); lp.add_argument('--limit',type=int,default=30)
    ap=sub.add_parser('label'); ap.add_argument('key'); ap.add_argument('label'); ap.add_argument('--note',default='')
    sub.add_parser('stats')
    args=p.parse_args(argv)
    s=Settings.from_env(); store=Store(s.db_path)
    if args.cmd=='list': return cmd_list(store,args.limit)
    if args.cmd=='label': return cmd_label(store,args.key,args.label,args.note)
    return cmd_stats(store)

if __name__=='__main__': raise SystemExit(main())
