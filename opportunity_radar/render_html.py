from collections import Counter
from datetime import datetime
from html import escape
from urllib.parse import urlparse
from .digest import (REASON_LABEL,SOURCE_LABEL,MARKET_LABEL,WEIGHT_LABEL,
                     decision_headline,management_note,strategic_note,empty_reason,_pay_strong,_judgment,
                     _why,_evidence_text,_market,_commercial_line,_by_lane,_lane,_state,_shown,_deferred,STATUS_LABEL)
from .analytics import funnel,source_breakdown,evidence_breakdown,denominator_note,lane_breakdown
from .intelligence_lines import INTELLIGENCE_LINE_LABEL,summarize
from .evidence import STATE_LABEL,STATE_MEANING,EVIDENCE_STATES
from .lanes import LANES,LANE_LABEL,LANE_PROMISE

INK='#1f2328'; MUTED='#6b7280'; RULE='#d9d9d9'; ORANGE='#d9730d'; SOFT='#fbf7f2'; FAINT='#f3f4f6'
FONT="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,'PingFang SC','Microsoft YaHei',sans-serif"

def _e(v): return escape(str(v if v is not None else ''),quote=True)

def _safe_href(value):
    """Only render secure web links from untrusted source metadata."""
    raw=str(value or '').strip()
    try:
        parsed=urlparse(raw)
        if parsed.scheme.lower()!='https' or not parsed.hostname or parsed.username or parsed.password:
            return ''
        return _e(raw)
    except ValueError:
        return ''

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

def _quote_rows(ev):
    """Unlocated quotations get their own row and their own label, never 事实."""
    verified=[e for e in ev if e.get('field')!='unlocated']
    unverified=[e for e in ev if e.get('field')=='unlocated']
    fmt=lambda e: _e(f"[{e.get('id')}] {e.get('quote','')}" if e.get('id') else e.get('quote',''))
    rows=_kv('事实','；'.join(fmt(e) for e in verified) if verified else '无可定位引文')
    if unverified:
        rows+=_kv('未核实引文',f'<span style="color:#9a3412;">原文中未找到，不作为事实：</span>'+'；'.join(fmt(e) for e in unverified))
    return rows

def _estimate_row(x):
    """Distinguish 'the text looks complete' from 'a reviewer confirmed the source'."""
    if x.get('content_basis_estimate')=='full_text' and x.get('evidence_basis')!='full_text':
        return _kv('内容完整性估计','文本看起来是全文；只有把该来源复核为 content_access_level=full_text，才能按 E2 计。')
    return ''

def _finding(x):
    a=x.get('analysis',{}); cls=x.get('classification',{}); lane=_lane(x)
    ev=x.get('evidence') or []
    unknown='；'.join(a.get('uncertainties',[])) or '未填写'
    href=_safe_href(x.get('url',''))
    source_link=f'<a href="{href}" rel="noopener noreferrer" style="color:{ORANGE};text-decoration:none;">打开原文 ↗</a>' if href else '原文链接不可用'
    rows=(_kv('通道',f'{_e(lane)} · {_e(LANE_LABEL[lane])}')
          +_kv('证据',f'{_e(_evidence_text(x))} · 来源质量 {_e(SOURCE_LABEL.get(cls.get("source_quality"),cls.get("source_quality","")))}')
          +_kv('初判',_e(_judgment(a)))
          +_quote_rows(ev)
          +_estimate_row(x)
          +_kv('商业评估' if lane!='C' else '技术评估',_e(_commercial_line(x).strip()))
          +_kv('关键未知',_e(unknown))
          +_kv('下一步观察',_e(a.get('suggested_next_step','人工复核')))
          +_kv('来源',f'{_e(x.get("source_name","Unknown"))} · {source_link}'))
    return (f'<div style="padding:18px 0;border-bottom:1px solid #ececec;page-break-inside:avoid;">'
            f'<div style="font-size:15px;font-weight:700;color:{INK};line-height:1.5;">'
            f'<span style="color:{ORANGE};margin-right:6px;">{_e(x.get("score",0))}</span>{_e(x.get("title",""))}</div>'
            f'<div style="font-size:11px;color:{MUTED};margin:5px 0 8px;">初筛得分 {_e(x.get("score",0))}/100 · {_e(_evidence_text(x))} · 通道内相对优先级，不代表成功概率或市场规模</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;border-collapse:collapse;">{rows}</table></div>')

def _brief(items):
    ranked=sorted(_shown(items),key=lambda v:v.get('score',0),reverse=True)[:3]
    if not ranked: return ''
    rows=''
    for i,x in enumerate(ranked,1):
        lane=_lane(x)
        rows+=(f'<tr><td style="width:26px;vertical-align:top;padding:12px 0 0;font-size:18px;font-weight:700;color:{ORANGE};">{i}</td>'
               f'<td style="padding:12px 0 12px;border-bottom:1px solid #eee;">'
               f'<div style="font-size:14px;font-weight:700;color:{INK};line-height:1.5;">{_e(x.get("title",""))}'
               f'<span style="font-size:11px;font-weight:600;color:{MUTED};margin-left:8px;">[{_e(lane)}]</span></div>'
               f'<div style="font-size:12.5px;color:#374151;line-height:1.7;margin-top:5px;"><strong style="color:{INK};">发生了什么：</strong>'
               f'{_e(str(x.get("analysis",{}).get("summary_zh","") or "未生成摘要"))}</div>'
               f'<div style="font-size:12.5px;color:#374151;line-height:1.7;"><strong style="color:{INK};">为什么重要：</strong>{_e(_why(x))}</div>'
               f'<div style="font-size:12.5px;color:#374151;line-height:1.7;"><strong style="color:{INK};">可信度：</strong>'
               f'{_e(_evidence_text(x))} · {_e(MARKET_LABEL.get(_market(x),"未评估"))}</div>'
               f'</td></tr>')
    return (f'<div style="margin:20px 0 0;border-top:1px solid {RULE};"><div style="font-size:11px;letter-spacing:.1em;'
            f'color:{MUTED};text-transform:uppercase;padding-top:10px;">执行摘要 · 三条</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table></div>')

def _svg_bars(rows):
    """Dependency-free horizontal bar chart. rows: (label, value[, note])."""
    rows=[(r[0],r[1],r[2] if len(r)>2 else '') for r in rows]
    if not rows: return ''
    h=len(rows)*30+8; maxv=max([v for _,v,_ in rows]+[1])
    out=[f'<svg viewBox="0 0 700 {h}" width="100%" role="img" style="display:block;margin:4px 0 0;">']
    for i,(label,val,note) in enumerate(rows):
        y=i*30+6; w=round(280*val/maxv) if maxv else 0
        out.append(f'<text x="0" y="{y+13}" font-size="12" fill="{MUTED}">{_e(str(label)[:14])}</text>')
        out.append(f'<rect x="195" y="{y+2}" width="{w}" height="16" fill="{ORANGE}" opacity="0.85"/>')
        out.append(f'<text x="{195+w+8}" y="{y+14}" font-size="12" fill="{INK}">{_e(val)}</text>')
        if note: out.append(f'<text x="520" y="{y+14}" font-size="11" fill="{MUTED}">{_e(note)}</text>')
    out.append('</svg>'); return ''.join(out)

def _chart_block(title,rows,color_note=''):
    return (f'<div style="margin:14px 0 0;"><div style="font-size:12px;font-weight:600;color:{INK};margin-bottom:2px;">{_e(title)}</div>'
            f'{_svg_bars(rows)}</div>')

def _rules_html(stats):
    lane_weights=stats.get('lane_weights') or {}; lane_th=stats.get('lane_thresholds') or {}
    parts=[]
    for lane in LANES:
        w=lane_weights.get(lane)
        if not w: continue
        th=lane_th.get(lane) or {}
        wtxt=' · '.join(f'{WEIGHT_LABEL.get(k,k)} {v}' for k,v in w.items())
        parts.append(f'{_e(lane)} 通道 {_e(wtxt)}（优先 {_e(th.get("priority",75))} / 观察 {_e(th.get("watch",55))}）')
    if not parts:
        th=stats.get('thresholds') or {}
        return f"阈值 优先 {_e(th.get('priority',75))} / 观察 {_e(th.get('watch',55))}。"
    return '；'.join(parts)+'。不同通道的分数不可直接比较。'

def _audit_html(stats):
    issues=stats.get('source_issues') or []
    unresolved=int(stats.get('unresolved_sources') or 0)
    if not issues and not unresolved: return '本轮没有登记层面的阻塞问题。'
    rows=[]
    if unresolved:
        rows.append(f'{unresolved} 条历史记录未匹配到来源登记：通道按内容判断，且不套用任何来源配额。')
    rows+= [f"[{i.get('severity','info')}] {i.get('source_id','')} · {i.get('code','')}：{i.get('message','')}" for i in issues[:12]]
    return '<br>'.join(_e(r) for r in rows)

def render_html(items,stats,date_label=None):
    date_label=date_label or datetime.now().astimezone().strftime('%Y-%m-%d')
    counts=stats.get('counts',{}); strong=sum(1 for x in items if _pay_strong(x))
    shown=_shown(items); deferred=_deferred(items)
    filtered=[x for x in items if x.get('status')=='filtered']
    reason=stats.get('empty_reason') or empty_reason(stats)
    parts=[]
    parts.append('<div style="font-size:10px;letter-spacing:.24em;color:'+ORANGE+';font-weight:700;">OPPORTUNITY RADAR</div>'
                 f'<div style="font-size:30px;font-weight:700;color:{INK};line-height:1.25;margin-top:8px;">商业机会情报简报</div>'
                 f'<div style="font-size:13px;color:{MUTED};margin-top:6px;">三日通道 · 证据优先 · {_e(date_label)}</div>')
    if stats.get('sample_mode'):
        parts.append(f'<div style="margin-top:16px;padding:12px 14px;border-left:4px solid {ORANGE};background:{SOFT};font-size:13px;line-height:1.65;color:#6b3519;"><strong>离线演示数据：</strong>以下内容仅用于展示报告结构，不代表真实来源、用户需求或商业机会。</div>')
    parts.append(f'<div style="margin:26px 0 0;border-left:4px solid {ORANGE};padding:2px 0 2px 16px;">'
                 f'<div style="font-size:19px;font-weight:700;color:{INK};line-height:1.55;">{_e(decision_headline(items,stats))}</div></div>')
    note='样例仅用于演示字段和版式，不构成对真实需求的判断。' if stats.get('sample_mode') else management_note(items)
    parts.append(f'<div style="margin:16px 0 0;background:{SOFT};border:1px solid #f0e3d3;padding:14px 16px;font-size:13px;line-height:1.75;color:#4a3b2a;">'
                 f'{_e(note)}</div>')
    if shown: parts.append(_brief(items))
    tiles=(_stat('已保存分析',len(items)) if stats.get('render_only') else _stat('新增信号',stats.get('new',stats.get('analyzed',0))))
    parts.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:22px 0 0;table-layout:fixed;border-collapse:collapse;"><tr>'
                 +tiles+_stat('持续观察',counts.get('watch',0))
                 +_stat('优先验证',counts.get('priority',0))+_stat('明确付费证据',strong)+'</tr></table>')
    n=1
    for lane in LANES:
        group=sorted(_by_lane(shown,lane),key=lambda v:v.get('score',0),reverse=True)
        parts.append(_section(f'{n:02d}',LANE_LABEL[lane]))
        parts.append(f'<div style="font-size:12px;color:{MUTED};margin:-6px 0 6px;line-height:1.6;">通道定义：{_e(LANE_PROMISE[lane])}</div>')
        if group:
            parts += [_finding(x) for x in group]
        else:
            parts.append(f'<div style="font-size:13px;color:#4b5563;">本期该通道没有条目进入观察区。</div>')
        n+=1
    if not shown:
        parts.append(f'<div style="margin-top:18px;background:#fff;border:1px solid {RULE};padding:14px 16px;font-size:13px;line-height:1.7;color:#4b5563;">{_e(reason)}</div>')
    parts.append(_section(f'{n:02d}','数据概览')); n+=1
    parts.append(_chart_block('处理漏斗（条目数）',funnel(stats)))
    parts.append(_chart_block('通道分布（分析条目）',[(LANE_LABEL[r['lane']][:8],r['items'],f"入选 {r['shown']}") for r in lane_breakdown(items)]))
    line_rows=[(INTELLIGENCE_LINE_LABEL.get(str(k),str(k))[:10],v,'来源声明') for k,v in summarize(items)]
    if line_rows: parts.append(_chart_block('情报主线（分析条目）',line_rows))
    src_rows=[(r['source'],r['items'],f"引文 {r['located']}/{r['evidence']}" if r['evidence'] else '无引文') for r in source_breakdown(items)]
    parts.append(_chart_block('来源贡献（分析条目）',src_rows))
    ev_rows=[(STATE_LABEL.get(e['state'],e['state']),e['count']) for e in evidence_breakdown(items)]
    parts.append(_chart_block('证据强度（条目数）',ev_rows))
    parts.append(f'<div style="font-size:11px;color:{MUTED};margin-top:10px;line-height:1.6;">{_e(denominator_note(stats))}</div>')
    window=stats.get('sample_window')
    if window:
        parts.append(f'<div style="font-size:11px;color:{MUTED};margin-top:6px;line-height:1.6;">'
                     f"样本窗口：{_e(window.get('since') or '(无下界)')} 至 {_e(window.get('until') or '(无上界)')} UTC"
                     f"（池 {_e(window.get('pool'))} → 窗口内 {_e(window.get('in_window'))} → 取 {_e(window.get('sampled'))}）</div>")
    parts.append(_section(f'{n:02d}','战略含义与附录'))
    parts.append(f'<div style="font-size:13.5px;line-height:1.85;color:{INK};">{_e(strategic_note(items))}</div>')
    sources=', '.join(f'{k} {v}' for k,v in Counter(x.get('source_name','Unknown') for x in items).most_common()) or '无'
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.8;margin-top:14px;"><strong style="color:{INK};">来源分布：</strong>{_e(sources)}</div>')
    if deferred:
        rows=''.join(f'<div style="margin-top:6px;">[{_e(STATUS_LABEL.get(x.get("status"),x.get("status")))} · {_e(x.get("score",0))}/100] '
                     f'{_e(x.get("title",""))} <span style="color:{MUTED};">（{_e(x.get("source_name","Unknown"))}）</span></div>'
                     for x in sorted(deferred,key=lambda v:(-v.get('score',0),v.get('title',''))))
        parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:12px;"><strong style="color:{INK};">本期未纳入分发（来源单期配额）：</strong>'
                     f'{len(deferred)} 条，原始判断保留如下{rows}</div>')
    if filtered:
        rows=''
        for r,label in REASON_LABEL.items():
            group=[x for x in filtered if x.get('filter_reason')==r]
            if group: rows+=f'<div style="margin-top:8px;"><span style="color:{INK};font-weight:600;">{_e(label)}：{len(group)} 篇</span><br>'+ '<br>'.join(_e(f"[{x.get('score',0)}/100] {x.get('title','')}") for x in group[:10])+'</div>'
        parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:12px;"><strong style="color:{INK};">已过滤与待补充：</strong>{rows}</div>')
    quality=Counter(_evidence_text(x) for x in items)
    q=', '.join(f'{k} {v}' for k,v in quality.most_common()) or '无'
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:12px;"><strong style="color:{INK};">数据质量：</strong>证据等级分布 {_e(q)}。仅标题或无法在原文中定位的摘录不能作为已验证需求。</div>')
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:8px;"><strong style="color:{INK};">来源审计：</strong>{_audit_html(stats)}</div>')
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:8px;"><strong style="color:{INK};">评分规则：</strong>版本 {_e(stats.get("rules_version","v2"))}。{_rules_html(stats)}</div>')
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:8px;"><strong style="color:{INK};">分析记录：</strong>模型 {_e(stats.get("model") or "未记录")} · 提示词 v{_e(stats.get("prompt_version") or "未记录")}（{_e(stats.get("prompt_hash") or "hash未记录")}）· 规则 {_e(stats.get("rules_version","v2"))}</div>')
    evs=[e for x in items for e in (x.get('evidence') or [])]
    unlocated=sum(1 for e in evs if e.get('field')=='unlocated')
    parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:6px;"><strong style="color:{INK};">引文定位：</strong>{len(evs)-unlocated} 条可定位 · {unlocated} 条无法在原文中定位</div>')
    present={_state(x) for x in items}
    meanings=[STATE_MEANING[st] for st in EVIDENCE_STATES if st in present and st in STATE_MEANING]
    if meanings:
        parts.append(f'<div style="font-size:12px;color:#4b5563;line-height:1.75;margin-top:6px;"><strong style="color:{INK};">证据口径：</strong>{_e(" ".join(meanings))}</div>')
    parts.append(f'<div style="margin-top:26px;padding-top:12px;border-top:1px solid {RULE};font-size:11px;color:{MUTED};line-height:1.7;">免责声明：本报告为自动化初筛，不构成商业、法律或投资结论。营收、利润、市场规模和法律许可等主张必须核对原始来源及独立证据。</div>')
    html=('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
          '<meta name="viewport" content="width=device-width,initial-scale=1">'
          f'<title>{_e("Opportunity Radar "+date_label)}</title>'
          '<style>@media (max-width:560px){.page{padding:24px 16px 32px!important}.assessment-table{min-width:620px}.assessment-scroll{overflow-x:auto!important}}@media print{body{background:#fff!important}.page{max-width:100%!important;padding:0!important}.assessment-scroll{overflow:visible!important}.assessment-table{min-width:0!important}}</style>'
          f'<style>body{{margin:0;background:#ffffff;}}a{{color:{ORANGE};}}</style></head>'
          f'<body style="margin:0;background:#ffffff;font-family:{FONT};color:{INK};">'
          f'<div class="page" style="max-width:760px;margin:0 auto;padding:36px 28px 48px;box-sizing:border-box;overflow-wrap:anywhere;">'
          +''.join(parts)+'</div></body></html>')
    return html
