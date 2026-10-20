from collections import Counter
from datetime import datetime
from html import escape
from .digest import (STATUS_LABEL,REASON_LABEL,EVIDENCE_LABEL,SIGNAL_LABEL,BUYER_LABEL,PAY_LABEL,
                     DELIVERY_LABEL,SOURCE_LABEL,WEIGHT_LABEL,decision_headline,management_note,
                     strategic_note,action_items,empty_reason,_pay_strong)
from .analytics import funnel,source_breakdown,evidence_breakdown,denominator_note

INK='#1f2328'; MUTED='#6b7280'; RULE='#d9d9d9'; ORANGE='#d9730d'; SOFT='#fbf7f2'; FAINT='#f3f4f6'
FONT="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,'PingFang SC','Microsoft YaHei',sans-serif"

def _e(v): return escape(str(v if v is not None else ''),quote=True)

def _section(n,title):
    return (f'<div style="margin:34px 0 12px;border-bottom:1px solid {RULE};padding-bottom:7px;">'
            f'<span style="color:{ORANGE};font-weight:700;margin-right:10px;">{n}</span>'
            f'<span style="font-size:17px;font-weight:700;color:{INK};">{_e(title)}</span></div>')

def _kv(k,v):
    return (f'<tr><td style="width:88px;vertical-align:top;padding:5px 12px 5px 0;font-size:12px;color:{MUTED};">{_e(k)}</td>'
            f'<td style="vertical-align:top;padding:5px 0;font-size:13px;line-height:1.65;color:{INK};word-break:break-word;overflow-wrap:anywhere;">{v}</td></tr>')

def _stat(label,value):
    return (f'<td style="width:25%;vertical-align:top;padding:14px 14px 0 0;border-top:1px solid {RULE};">'
            f'<div style="font-size:10px;letter-spacing:.1em;color:{MUTED};text-transform:uppercase;">{_e(label)}</div>'
            f'<div style="font-size:30px;font-weight:700;color:{INK};line-height:1.25;margin-top:4px;">{_e(value)}</div></td>')

def _finding(i,x):
    a=x.get('analysis',{}); cls=x.get('classification',{})
    ev=x.get('evidence') or []
    quotes='；'.join(f"[{e.get('id')}] {e.get('quote','')}" if e.get('id') else e.get('quote','') for e in ev) or '；'.join(a.get('evidence_quotes',[])) or '无可追溯摘录'
    unknown='；'.join(a.get('uncertainties',[])) or '未填写'
    level=EVIDENCE_LABEL.get(x.get('evidence_level'),x.get('evidence_level',''))
    commercial=(f"需求 {SIGNAL_LABEL.get(cls.get('signal_type'),'-')} · 买方 {BUYER_LABEL.get(cls.get('buyer_type'),'-')} · "
                f"付费证据 {PAY_LABEL.get(cls.get('payment_evidence'),'-')} · 交付 {DELIVERY_LABEL.get(cls.get('delivery_fit'),'-')}")
    rows=(_kv('事实',_e(quotes))
          +_kv('初判',_e(f"{a.get('summary_zh','')} {a.get('commercial_signal','')}".strip()))
          +_kv('商业评估',_e(commercial))
          +_kv('关键未知',_e(unknown))
          +_kv('建议验证',_e(a.get('suggested_next_step','人工复核')))
          +_kv('来源',f'{_e(x.get("source_name","Unknown"))} · <a href="{_e(x.get("url",""))}" style="color:{ORANGE};text-decoration:none;">打开原文 ↗</a>'))
    return (f'<div style="padding:18px 0;border-bottom:1px solid #ececec;page-break-inside:avoid;">'
            f'<div style="font-size:15px;font-weight:700;color:{INK};line-height:1.5;">'
            f'<span style="color:{ORANGE};margin-right:6px;">{_e(x.get("score",0))}</span>{_e(x.get("title",""))}</div>'
            f'<div style="font-size:11px;color:{MUTED};margin:5px 0 8px;">初筛得分 {_e(x.get("score",0))}/100 · 证据等级 {_e(level)} · 规则模型相对优先级，不代表成功概率或市场规模</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;border-collapse:collapse;">{rows}</table></div>')

def _svg_bars(rows):
    """Dependency-free horizontal bar chart. rows: (label, value[, note])."""
    rows=[(r[0],r[1],r[2] if len(r)>2 else '') for r in rows]
    if not rows: return ''
    h=len(rows)*30+8; maxv=max([v for _,v,_ in rows]+[1])
    out=[f'<svg viewBox="0 0 700 {h}" width="100%" role="img" style="display:block;margin:4px 0 0;">']
    for i,(label,val,note) in enumerate(rows):
        y=i*30+6; w=round(280*val/maxv) if maxv else 0
        out.append(f'<text x="0" y="{y+13}" font-size="12" fill="{MUTED}">{_e(str(label)[:26])}</text>')
        out.append(f'<rect x="195" y="{y+2}" width="{w}" height="16" fill="{ORANGE}" opacity="0.85"/>')
        out.append(f'<text x="{195+w+8}" y="{y+14}" font-size="12" fill="{INK}">{_e(val)}</text>')
        if note: out.append(f'<text x="520" y="{y+14}" font-size="11" fill="{MUTED}">{_e(note)}</text>')
    out.append('</svg>'); return ''.join(out)

def _chart_block(title,rows,color_note=''):
    return (f'<div style="margin:14px 0 0;"><div style="font-size:12px;font-weight:600;color:{INK};margin-bottom:2px;">{_e(title)}</div>'
            f'{_svg_bars(rows)}</div>')

def render_html(items,stats,date_label=None):
    date_label=date_label or datetime.now().astimezone().strftime('%Y-%m-%d')
    counts=stats.get('counts',{}); strong=sum(1 for x in items if _pay_strong(x))
    shown=sorted([x for x in items if x.get('status') in {'priority','watch'}],key=lambda v:v.get('score',0),reverse=True)
    filtered=[x for x in items if x.get('status')=='filtered']
    reason=stats.get('empty_reason') or empty_reason(stats)
    parts=[]
    parts.append('<div style="font-size:10px;letter-spacing:.24em;color:'+ORANGE+';font-weight:700;">OPPORTUNITY RADAR</div>'
                 f'<div style="font-size:30px;font-weight:700;color:{INK};line-height:1.25;margin-top:8px;">商业机会情报简报</div>'
                 f'<div style="font-size:13px;color:{MUTED};margin-top:6px;">每日信号筛选 · {_e(date_label)}</div>')
    parts.append(f'<div style="margin:26px 0 0;border-left:4px solid {ORANGE};padding:2px 0 2px 16px;">'
                 f'<div style="font-size:19px;font-weight:700;color:{INK};line-height:1.55;">{_e(decision_headline(items,stats))}</div></div>')
    parts.append(f'<div style="margin:16px 0 0;background:{SOFT};border:1px solid #f0e3d3;padding:14px 16px;font-size:13px;line-height:1.75;color:#4a3b2a;">'
                 f'{_e(management_note(items))}</div>')
    tiles=(_stat('已保存分析',len(items)) if stats.get('render_only') else _stat('新增信号',stats.get('new',stats.get('analyzed',0))))
    parts.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:22px 0 0;table-layout:fixed;border-collapse:collapse;"><tr>'
                 +tiles+_stat('持续观察',counts.get('watch',0))
                 +_stat('优先验证',counts.get('priority',0))+_stat('明确付费证据',strong)+'</tr></table>')
    n=1
    parts.append(_section(f'{n:02d}','关键发现')); n+=1
    if shown:
        parts += [_finding(i,x) for i,x in enumerate(shown,1)]
    else:
        parts.append(f'<div style="background:#fff;border:1px solid {RULE};padding:14px 16px;font-size:13px;line-height:1.7;color:#4b5563;">{_e(reason)}</div>')
    parts.append(_section(f'{n:02d}','数据概览')); n+=1
    parts.append(_chart_block('处理漏斗（条目数）',funnel(stats)))
    src_rows=[(r['source'],r['items'],f"引文 {r['located']}/{r['evidence']}" if r['evidence'] else '无引文') for r in source_breakdown(items)]
    parts.append(_chart_block('来源贡献（分析条目）',src_rows))
    ev_rows=[(EVIDENCE_LABEL.get(e['level'],e['level']),e['count']) for e in evidence_breakdown(items)]
    parts.append(_chart_block('证据强度（条目数）',ev_rows))
    parts.append(f'<div style="font-size:11px;color:{MUTED};margin-top:10px;line-height:1.6;">{_e(denominator_note(stats))}</div>')
    parts.append(_section(f'{n:02d}','商业评估')); n+=1
    if shown:
        head=(f'<tr style="background:{FAINT};">'+''.join(f'<th align="left" style="padding:8px 10px;font-size:11px;color:{MUTED};font-weight:600;border-bottom:1px solid {RULE};">{h}</th>'
              for h in ('条目','需求','付费证据','交付可行性','证据等级'))+'</tr>')
        body=''
        for x in shown:
            cls=x.get('classification',{})
            body+=(f'<tr><td style="padding:8px 10px;font-size:12px;color:{INK};border-bottom:1px solid #eee;">{_e(x.get("title","")[:32])}</td>'
                   +''.join(f'<td style="padding:8px 10px;font-size:12px;color:{INK};border-bottom:1px solid #eee;">{_e(v)}</td>'
                            for v in (SIGNAL_LABEL.get(cls.get('signal_type'),'-'),PAY_LABEL.get(cls.get('payment_evidence'),'-'),
                                      DELIVERY_LABEL.get(cls.get('delivery_fit'),'-'),EVIDENCE_LABEL.get(x.get('evidence_level'),'-')))+'</tr>')
        parts.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;">{head}{body}</table>')
    else:
        parts.append(f'<div style="font-size:13px;color:#4b5563;">本期没有进入观察区的条目，无法形成商业评估。</div>')
    parts.append(_section(f'{n:02d}','战略含义')+f'<div style="font-size:13.5px;line-height:1.85;color:{INK};">{_e(strategic_note(items))}</div>'); n+=1
    parts.append(_section(f'{n:02d}','建议行动')+'<ol style="margin:0;padding-left:20px;font-size:13.5px;line-height:1.85;color:'+INK+';">'
                 +''.join(f'<li style="margin-bottom:8px;">{_e(a)}</li>' for a in action_items(items))+'</ol>')
    parts.append(_section(f'{n:02d}','附录'))
    sources=', '.join(f'{k} {v}' for k,v in Counter(x.get('source_name','Unknown') for x in items).most_common()) or '无'
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.8;"><strong style="color:{INK};">来源分布：</strong>{_e(sources)}</div>')
    if filtered:
        rows=''
        for r,label in REASON_LABEL.items():
            group=[x for x in filtered if x.get('filter_reason')==r]
            if group: rows+=f'<div style="margin-top:8px;"><span style="color:{INK};font-weight:600;">{_e(label)}：{len(group)} 篇</span><br>'+ '<br>'.join(_e(f"[{x.get('score',0)}/100] {x.get('title','')}") for x in group[:10])+'</div>'
        parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:12px;"><strong style="color:{INK};">已过滤与待补充：</strong>{rows}</div>')
    quality=Counter(EVIDENCE_LABEL.get(x.get('evidence_level'),x.get('evidence_level','')) for x in items)
    q=', '.join(f'{k} {v}' for k,v in quality.most_common()) or '无'
    weights=' · '.join(f'{WEIGHT_LABEL.get(k,k)} {v}' for k,v in (stats.get('weights') or {}).items())
    th=stats.get('thresholds') or {}
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:12px;"><strong style="color:{INK};">数据质量：</strong>证据等级分布 {_e(q)}。仅标题或无法在原文中定位的摘录不能作为已验证需求。</div>')
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:8px;"><strong style="color:{INK};">评分规则：</strong>版本 {_e(stats.get("rules_version","v2"))}{" · 权重 "+_e(weights) if weights else ""} · 阈值 优先 {_e(th.get("priority",75))} / 观察 {_e(th.get("watch",55))}。初筛分数只表示相对优先级。</div>')
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:8px;"><strong style="color:{INK};">分析记录：</strong>模型 {_e(stats.get("model") or "未记录")} · 提示词 v{_e(stats.get("prompt_version") or "未记录")} · 规则 {_e(stats.get("rules_version","v2"))}</div>')
    evs=[e for x in items for e in (x.get('evidence') or [])]
    unlocated=sum(1 for e in evs if e.get('field')=='unlocated')
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:6px;"><strong style="color:{INK};">引文定位：</strong>{len(evs)-unlocated} 条可定位 · {unlocated} 条无法在原文中定位</div>')
    parts.append(f'<div style="margin-top:26px;padding-top:12px;border-top:1px solid {RULE};font-size:11px;color:{MUTED};line-height:1.7;">免责声明：本报告为自动化初筛，不构成商业、法律或投资结论。营收、利润、市场规模和法律许可等主张必须核对原始来源及独立证据。</div>')
    html=('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
          '<meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>{_e("Opportunity Radar "+date_label)}</title>'
          '<style>@media print{body{background:#fff!important}.page{max-width:100%!important;padding:0!important}}</style>'
          f'<style>body{{margin:0;background:#ffffff;}}a{{color:{ORANGE};}}</style></head>'
          f'<body style="margin:0;background:#ffffff;font-family:{FONT};color:{INK};">'
          f'<div class="page" style="max-width:760px;margin:0 auto;padding:36px 28px 48px;box-sizing:border-box;overflow-wrap:anywhere;">'
          +''.join(parts)+'</div></body></html>')
    return html
