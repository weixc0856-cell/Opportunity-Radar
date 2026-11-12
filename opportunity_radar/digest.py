import json
from collections import Counter
from datetime import datetime
from .analytics import funnel,source_breakdown,evidence_breakdown,denominator_note,lane_breakdown
from .intelligence_lines import INTELLIGENCE_LINE_LABEL, summarize
from .evidence import STATE_LABEL, STATE_MEANING, EVIDENCE_STATES, state_of
from .publication import disclosure, headline_notice
from .unified import (EVENT_CONTEXT_AVAILABLE, EVENT_CONTEXT_LABEL)
from .lanes import LANES, LANE_LABEL, LANE_PROMISE, item_lane as _lane
from . import display

STATUS_LABEL={'priority':'优先验证','watch':'持续观察','filtered':'已过滤'}
REASON_LABEL={'hiring':'招聘/企业动态','no_business_signal':'无商业信号','insufficient_evidence':'证据不足，无法进入简报','content_insufficient':'内容不足，无法核实','low_score':'分数未达门槛'}
SIGNAL_LABEL={'payment_demand':'明确付费需求','user_pain':'用户痛点','deployment_blocker':'部署障碍','product_gap':'产品缺口','tech_trend':'技术趋势'}
BUYER_LABEL={'individual_dev':'个人开发者','smb':'中小企业','engineering_team':'工程团队','enterprise_it':'企业 IT','unknown':'未知'}
PAY_LABEL={'explicit_budget':'明确预算','stated_willingness':'表达了付费意愿','existing_purchase':'已有采购','indirect':'间接证据','none':'无证据'}
DELIVERY_LABEL={'service':'服务交付','custom_tool':'定制工具','product':'标准化产品','not_fit':'暂不适合'}
SOURCE_LABEL={'first_party':'一手用户表达','project_record':'项目记录','secondhand_report':'二手报道','vendor_marketing':'官方宣传'}
ADOPTION_LABEL={'production_use':'生产环境使用','none':'未见采用证据'}
SELLER_LABEL={'commercial_service':'商业服务/付费支持','pricing_published':'公开定价','none':'无'}
MARKET_LABEL={'multi_source':'多来源覆盖（未核对独立性）','buyer_confirmed':'买方付费证据','single_source':'单一来源','seller_claim':'仅卖方自述','none':'无'}
WEIGHT_LABEL={
 'demand_clarity':'需求明确度','payment_evidence':'付费证据','actionability':'可执行性','feasibility':'验证可行性','novelty':'新颖性',
 'importance':'重要性','source_reliability':'来源可靠性','evidence_completeness':'证据完整度','relevance':'相关性','timeliness':'时效性',
 'pain_severity':'痛点严重度','buyer_clarity':'买方明确度','corroboration':'独立佐证','solution_gap':'现有方案缺口',
 'technical_maturity':'技术成熟度','reproducibility':'可复现性','impact_scope':'影响范围'}
LANE_WHY={
 'A':'来源记录了公司、行业或宏观层面的变化，值得跟踪其对资本开支与竞争格局的影响。',
 'B':'有用户描述的具体问题，但还缺少付费或采购证据。',
 'C':'技术变化本身可核对，但还不足以得出商业结论。',
}
PAY_STRONG={'explicit_budget','existing_purchase'}

def _pay_strong(x):
    cls=x.get('classification',{})
    return cls.get('buyer_payment_evidence',cls.get('payment_evidence')) in PAY_STRONG

def _top(items):
    return max(items,key=lambda x:x.get('score',0)) if items else None

def _shown(items):
    """What this issue actually prints: worth attention AND within the source quota."""
    return [x for x in items if x.get('status') in {'priority','watch'} and x.get('distribution')!='deferred']

def event_id_of(x):
    return str((x.get('event') or {}).get('event_id') or '')


PRIORITY_RANK={'P0':0,'P1':1,'P2':2,'P3':3,'REJECT':4}


def _order_key(item):
    return (PRIORITY_RANK.get(item.get('editorial_priority') or '', 5),
            -item.get('score', 0), item.get('title', ''))


def group_by_event(items):
    """One card per event. Editorial priority first, score second.

    Grouping happens across lanes on purpose: the same event filed once as economy and once
    as an opportunity is still one thing that happened, and printing it twice is how a
    reading list turns into a duplicate feed.
    """
    ordered = sorted(items, key=_order_key)
    reps, siblings = [], {}
    for item in ordered:
        event_id = event_id_of(item)
        if event_id and event_id in siblings:
            siblings[event_id].append(item)
            continue
        if event_id:
            siblings[event_id] = []
        reps.append(item)
    return reps, siblings


CLAIM_KIND_LABEL={'fact':'事实','source_interpretation':'来源解释','system_inference':'系统推断',
                  'hypothesis':'假设','forecast':'预测','opinion':'观点'}
CLAIM_STATE_LABEL={'unverified':'未核验','verified':'已核验','rejected':'已否决','unverifiable':'无法核验'}
EVIDENCE_STATUS_LABEL={'EVIDENCE_BACKED':'有证据','NO_EVIDENCE':'无证据','INSUFFICIENT_EVIDENCE':'证据不足'}
EVENT_EVIDENCE_NOTE={'EVIDENCE_BACKED':'事件有证据（不等于主张已核验）',
                     'NO_EVIDENCE':'事件无证据（仅线索）',
                     'INSUFFICIENT_EVIDENCE':'事件证据不足'}


def event_evidence_note(event):
    return EVENT_EVIDENCE_NOTE.get((event or {}).get('evidence_status'), '')


def event_context_note(item):
    status = (item.get('event_context') or {}).get('status')
    if status and status != EVENT_CONTEXT_AVAILABLE:
        return EVENT_CONTEXT_LABEL.get(status, status)
    return ''


def event_status_note(item):
    return event_evidence_note(item.get('event') or {}) or event_context_note(item)


def event_context_line(item):
    note = event_context_note(item)
    if not note:
        return ''
    return (f'   事件上下文：{note}；文章证据等级 {_evidence_text(item)} '
            '不是事件级核验结论')


def _locator_text(raw):
    """`summary@0-15` or the filing/series reference, in one short form."""
    try:
        loc=json.loads(raw or '{}')
    except ValueError:
        return ''
    if not isinstance(loc,dict): return ''
    if loc.get('field'):
        start=loc.get('start'); length=loc.get('length')
        return f"{loc['field']}@{start}-{start+length}" if isinstance(start,int) and isinstance(length,int) else str(loc['field'])
    for key in ('accn','series_id','period'):
        if loc.get(key): return f"{key}={loc[key]}"
    return ''


def _claim_lines(event):
    items=event.get('claim_items') or []
    if not items: return []
    states=Counter(i.get('verification_state') or 'unverified' for i in items)
    summary='，'.join(f"{CLAIM_STATE_LABEL.get(k,k)} {v}" for k,v in states.items())
    lines=[f"   事实主张：{len(items)} 条（{summary}）"]
    for item in items[:2]:
        kind=CLAIM_KIND_LABEL.get(item.get('kind'),item.get('kind') or '')
        state=CLAIM_STATE_LABEL.get(item.get('verification_state'),item.get('verification_state') or '')
        text=(item.get('value_text') or item.get('quote') or '').strip()
        if len(text)>48: text=text[:48]+'…'
        pointer=item.get('evidence_id') or '无证据'
        where=_locator_text(item.get('locator_json'))
        source=item.get('evidence_source_id') or ''
        detail='；'.join(part for part in (where, source) if part)
        tier,_reason=display.claim_tier(item)
        lines.append(f"     · [{kind}·{state}·{tier}] 「{text}」 ← 证据 {pointer}"+(f"（{detail}）" if detail else ''))
    if len(items)>2: lines.append(f"     · 另有 {len(items)-2} 条主张，见归档 JSON")
    return lines


def _link_lines(event):
    items=event.get('link_items') or []
    if not items: return []
    by_status=Counter(i.get('status') or 'candidate' for i in items)
    label='，'.join(f"{k} {v}" for k,v in by_status.items())
    lines=[f"   候选关联：{len(items)} 条（{label}）· 未经确认，不作为已发生的事实"]
    for item in items[:2]:
        peer=item.get('right_key') if item.get('left_kind')=='claim' else item.get('left_key')
        pointer=f"{item.get('left_kind')}→{item.get('right_kind')}" if item.get('left_kind') else ''
        lines.append(f"     · {pointer} {peer}（{item.get('basis')}，{item.get('confidence')}，{item.get('status')}）")
    return lines


def event_summary_lines(x):
    """What the R1 tables add: the claims, their evidence, and the corroboration picture."""
    event = x.get('event') or {}
    if not event:
        line = event_context_line(x)
        return [line] if line else []
    members = event.get('members') or []
    families = event.get('source_families') or []
    others = max(0, len(members) - 1)
    claims = event.get('claim_items') or []
    links = event.get('link_items') or []
    evidence_status = event.get('evidence_status')
    if (others == 0 and len(families) <= 1 and not links and not claims
            and evidence_status is None):
        return []
    verdict = '是' if event.get('independent_corroboration') else '否'
    outlets = len(event.get('member_sources') or []) or len(event.get('sources') or [])
    lines = []
    # A single report from a single family says nothing about corroboration; printing the
    # line anyway would train the reader to skip it.
    if (others or len(families) > 1 or links
            or evidence_status in EVIDENCE_STATUS_LABEL):
        units = event.get('independent_source_units', event.get('corroborating_units'))
        unit_text = f" · 独立来源单元 {units} 个" if units is not None else ''
        syndicated = event.get('syndicated_article_count')
        syndicated_text = f" · 已识别转载 {syndicated} 篇" if syndicated else ''
        status = event.get('independence_status')
        status_text = ''
        if status == 'PARTIAL':
            status_text = ' · 独立性部分未知'
        elif status == 'UNKNOWN':
            status_text = ' · 独立性未知'
        evidence_text = (f" · 证据状态：{EVIDENCE_STATUS_LABEL[evidence_status]}"
                         f"（{'仅线索，不作为已核实事实' if evidence_status == 'NO_EVIDENCE' else
                              '不能作为已核实事实' if evidence_status == 'INSUFFICIENT_EVIDENCE' else
                              '不等于主张已核验'}）"
                         if evidence_status in EVIDENCE_STATUS_LABEL else '')
        lines.append(f"   事件结构：同事件报道 {len(members)} 篇 · 报道来源 {outlets} 个 · "
                     f"来源族 {len(families)} 个{unit_text}{syndicated_text}{status_text}"
                     f"{evidence_text} · 独立佐证：{verdict}")
    lines += _claim_lines(event)
    lines += _link_lines(event)
    if others:
        listed = [f"{m.get('source_name','?')}《{str(m.get('title',''))[:36]}》{m.get('url','')}"
                  for m in members if m.get('url') and m['url'] != x.get('url')][:4]
        if listed:
            lines.append('   同事件其他报道：' + '；'.join(listed))
    return lines


def _deferred(items):
    return [x for x in items if x.get('distribution')=='deferred']

def _by_lane(items,lane):
    return [x for x in items if _lane(x)==lane]

def _state(x):
    return x.get('evidence_state') or state_of(x)

def _evidence_text(x):
    return STATE_LABEL.get(_state(x),str(_state(x)))

def _market(x):
    """Corroboration state; archived records predate the field, so derive it the same way."""
    value=x.get('market_validation')
    if value: return value
    cls=x.get('classification',{})
    if cls.get('buyer_payment_evidence') in PAY_STRONG: return 'buyer_confirmed'
    if cls.get('source_quality')=='vendor_marketing': return 'seller_claim'
    return 'single_source' if (x.get('evidence') or []) else 'none'

def decision_headline(items,stats):
    """One line a reader can act on. An incomplete run says so before it says anything else."""
    if stats.get('sample_mode'): return '本页仅展示报告结构与评分流程，不形成真实商业判断。'
    return headline_notice(stats)+_decision_body(items,stats)

def _decision_body(items,stats):
    visible=_shown(items); pri=[x for x in visible if x.get('status')=='priority']; watch=[x for x in visible if x.get('status')=='watch']
    deferred=_deferred(items)
    if pri:
        # Name something the brief will actually argue for. A priority item with no
        # commercial edge is a high score, not a recommendation.
        pick=next((x for x in sorted(pri,key=_pool_key) if _has_commercial_edge(x)),None)
        if pick:
            return f"本期筛选出 {len(pri)} 条达到验证门槛的信号，建议优先核实《{pick['title']}》。"
        edge=sorted([x for x in _shown(items) if _has_commercial_edge(x)],key=_pool_key)
        if edge:
            return (f"本期筛选出 {len(pri)} 条达到验证门槛的信号，但均无付费或采购证据；"
                    f"建议先核实《{edge[0]['title']}》。")
        return f"本期筛选出 {len(pri)} 条达到验证门槛的信号，建议优先核实《{_top(pri)['title']}》。"
    if watch:
        return f"本期尚未发现经过验证的付费机会，建议集中核实一项：{_top(watch)['title']}。"
    if deferred and (watch or pri):
        return f"本期筛选出 {len(pri)} 条优先、{len(watch)} 条观察信号，另有 {len(deferred)} 条受来源单期配额限制未进入阅读区，详见附录。"
    if deferred: return f"本期有 {len(deferred)} 条达到观察或验证门槛，但受来源单期配额限制未进入阅读区，详见附录。"
    if not stats.get('fetched',stats.get('article_count',0)): return '本轮未获取到新内容，无法形成商业判断。'
    # A failed analysis is not "nothing new". Check it first, or a run in which every new
    # article failed prints "no new analysis tasks" while the stats line says "failed 5".
    if stats.get('analyzed',stats.get('analyzed_count',0))==0 and stats.get('failed',stats.get('error_count',0))>0: return '本轮分析未完成，暂不形成商业判断。'
    if stats.get('analyzed',stats.get('analyzed_count',0))==0 and stats.get('skipped',0)>0: return '本轮没有新增分析任务，结论沿用已有结果；不代表没有机会。'
    return '本期没有信号通过筛选门槛，建议维持观察。'

def management_note(items):
    selected=_shown(items)
    scope=selected or items
    strong=sum(1 for x in scope if _pay_strong(x))
    parts=[]
    if not selected:
        parts.append(f'本期没有条目进入观察区；全部分析的 {len(items)} 条均未通过证据或分数门槛。')
    elif strong==0:
        parts.append(f'本期入选 {len(selected)} 条，均缺少直接付费证据；当前证据更适合支持问题调查，而非进入产品开发。')
    else:
        parts.append(f'本期入选 {len(selected)} 条，其中 {strong} 条出现明确付费证据，可优先评估其真实性与可持续性。')
    eng=sum(1 for x in scope if x.get('classification',{}).get('buyer_type')=='engineering_team')
    if eng: parts.append(f'在{"入选" if selected else "全部分析"}条目中，有 {eng} 条面向工程团队，与你既有的工程验证背景重叠最高。')
    deferred=len(_deferred(items))
    if deferred:
        parts.append(f'另有 {deferred} 条达到观察或验证门槛，因来源单期配额未进入本次阅读区；它们已保留在附录，不代表价值较低。')
    parts.append('下一阶段的重点应从增加信息量转向验证需求的真实性、发生频率与付费可能性。')
    return ' '.join(parts)

def strategic_note(items):
    selected=[x for x in items if x.get('status') in {'priority','watch'}]
    if not selected: return f'本期没有进入观察区的条目（共分析 {len(items)} 条），无法形成战略判断。'
    counts=Counter(_lane(x) for x in selected)
    parts=[f'本期入选 {len(selected)} 条：'+'，'.join(f'{LANE_LABEL[l]} {counts[l]} 条' for l in LANES if counts[l])+'。']
    if counts.get('A'):
        parts.append('情报通道出现的变化应优先回查一手公告或财报，再判断是否构成结构性影响。')
    if counts.get('B') and not any(_pay_strong(x) for x in selected):
        parts.append('机会通道仍没有出现预算或采购证据，现阶段不建议进入产品开发。')
    if counts.get('C'):
        parts.append('技术观察通道的内容只用于跟踪，不应直接当作商业机会。')
    return ''.join(parts)

def empty_reason(stats):
    fetched=stats.get('fetched',stats.get('article_count',0)); analyzed=stats.get('analyzed',stats.get('analyzed_count',0))
    failed=stats.get('failed',stats.get('error_count',0)); skipped=stats.get('skipped',0)
    if not fetched: return '本轮没有从 FreshRSS 获取到文章。请检查来源状态与运行日志；这不代表没有商业机会。'
    if analyzed==0 and failed>0: return f'本轮分析结果为空：{failed} 篇尝试分析均未通过，请查看运行日志排查原因。'
    if analyzed==0 and skipped>0: return f'本轮没有新的分析任务：{skipped} 篇文章均已有分析结果，无需重新分析。这只说明本轮没有新内容，不代表没有机会。'
    if stats.get('coverage') is not None and stats['coverage']<1:
        return disclosure(stats)
    return f'本轮没有满足条件的机会：{analyzed} 篇进入分析，均未达到观察门槛或未通过硬性过滤。'

def _counts(items):
    return {s:sum(1 for x in items if x.get('status')==s) for s in STATUS_LABEL}

def _judgment(a):
    summary=str(a.get('summary_zh','') or '').strip(); cs=str(a.get('commercial_signal','') or '').strip()
    return f'{summary} {cs}'.strip() if cs.lower() not in {'','none','unknown','n/a','未知','无'} else summary

def _why(x):
    a=x.get('analysis',{})
    cs=str(a.get('commercial_signal','') or '').strip()
    if cs.lower() not in {'','none','unknown','n/a','未知','无'}: return cs
    return LANE_WHY[_lane(x)]

def _quote_lines(ev):
    """Verified and unverified quotations must never share one label.

    The old card printed every quote under 事实, so an item labelled 'E0 · 无法定位'
    could still show fabricated-looking excerpts as established facts.
    """
    verified=[e for e in ev if e.get('field')!='unlocated']
    unverified=[e for e in ev if e.get('field')=='unlocated']
    fmt=lambda e: f"[{e.get('id')}] {e.get('quote','')}" if e.get('id') else e.get('quote','')
    rows=[]
    rows.append('   事实（可在原文定位）：'+('；'.join(fmt(e) for e in verified) if verified else '无可定位引文'))
    if unverified:
        rows.append('   未核实引文（原文中未找到，不作为事实）：'+'；'.join(fmt(e) for e in unverified))
    return rows

def _commercial_line(x):
    cls=x.get('classification',{}); lane=_lane(x)
    if lane=='A':
        return (f"   影响面：{SIGNAL_LABEL.get(cls.get('signal_type'),'-')} · 买方 {BUYER_LABEL.get(cls.get('buyer_type'),'-')}"
                f" · 验证状态 {MARKET_LABEL.get(_market(x),'-')}")
    if lane=='C':
        comp=x.get('scoring',{}).get('components') or x.get('components') or {}
        return (f"   技术评估：成熟度 {comp.get('technical_maturity','-')}/5 · 可复现性 {comp.get('reproducibility','-')}/5"
                f" · 影响范围 {comp.get('impact_scope','-')}/5")
    return (f"   商业评估：需求 {SIGNAL_LABEL.get(cls.get('signal_type'),'-')} · 买方 {BUYER_LABEL.get(cls.get('buyer_type'),'-')}"
            f" · 付费证据 {PAY_LABEL.get(cls.get('buyer_payment_evidence',cls.get('payment_evidence')),'-')}"
            f" · 卖方变现信号 {SELLER_LABEL.get(cls.get('seller_monetization_signal'),'-')}"
            f" · 采用 {ADOPTION_LABEL.get(cls.get('adoption_signal'),'-')}"
            f" · 交付 {DELIVERY_LABEL.get(cls.get('delivery_fit'),'-')}")

def _estimate_hint(x):
    """Show the gap between what the text looks like and what we are allowed to claim."""
    if x.get('content_basis_estimate')=='full_text' and x.get('evidence_basis')!='full_text':
        return ['   内容完整性估计：这段文本看起来是全文；只有把该来源复核为 content_access_level=full_text，才能按 E2 计。']
    return []

def _confidence_label(value):
    return {'low':'低','medium':'中','high':'高'}.get(str(value or '').lower(),'—')

def _basis_label(inference):
    basis=[b for b in (inference or {}).get('basis') or [] if isinstance(b,int)]
    return '、'.join(f'F{b}' for b in basis) if basis else '—'

def _v5_sections(x, event_status=None):
    """Facts, inferences, gaps and actions. Unverified claims never share a label with
    located ones: a quote the locator rejected is not evidence, and an inference with no
    located fact behind it is not a conclusion."""
    a=x.get('analysis',{})
    facts=[f for f in a.get('facts') or [] if isinstance(f,dict)]
    located=[f for f in facts if f.get('status')=='located']
    unlocated=[f for f in facts if f.get('status')!='located']
    inferences=[i for i in a.get('inferences') or [] if isinstance(i,dict)]
    supported=[i for i in inferences if i.get('status')=='supported']
    unsupported=[i for i in inferences if i.get('status')!='supported']
    gaps=[g for g in a.get('gaps') or [] if isinstance(g,dict)]
    actions=[c for c in a.get('actions') or [] if isinstance(c,dict)]
    label=('   文章内可定位文本（不代表事件已核实）'
           if event_status in ('NO_EVIDENCE', 'INSUFFICIENT_EVIDENCE')
           else '   事实（可在原文定位）')
    lines=[label]
    if located:
        for f in located:
            eid=f.get('evidence_id') or ''
            line=f"     {('['+eid+'] ') if eid else ''}{f.get('text','')}"
            quote=str(f.get('quote') or '').strip()
            if quote: line+=f" — “{quote}”"
            lines.append(line)
            actor=str(f.get('actor') or '').strip()
            url=str(f.get('source_url') or x.get('url') or '').strip()
            if actor or url:
                lines.append(f"          来源：{actor}{' · ' if actor and url else ''}{url}".rstrip())
    else:
        lines.append('     无可定位事实')
    if len(supported)==1:
        lines.append(f"   推断（基于 {_basis_label(supported[0])}，置信度 {_confidence_label(supported[0].get('confidence'))}）")
    else:
        lines.append('   推断')
    if supported:
        for inf in supported:
            suffix=''
            if len(supported)>1:
                suffix=f"（基于 {_basis_label(inf)}；置信度 {_confidence_label(inf.get('confidence'))}）"
            assumptions=[str(v).strip() for v in inf.get('assumptions') or [] if str(v).strip()]
            assumption=f"（假设：{'；'.join(assumptions)}）" if assumptions else ''
            lines.append(f"     - {inf.get('text','')}{suffix}{assumption}")
    else:
        lines.append('     无获事实支持的推断')
    lines.append('   证据缺口')
    if gaps:
        for g in gaps:
            detail=[]
            if g.get('why_it_matters'): detail.append(f"为什么重要：{g['why_it_matters']}")
            if g.get('how_to_close'): detail.append(f"如何补齐：{g['how_to_close']}")
            lines.append(f"     - {g.get('missing','')}"+(f"（{'；'.join(detail)}）" if detail else ''))
    else:
        lines.append('     无')
    lines.append('   建议行动')
    if actions:
        for c in actions:
            done=f"（完成标准：{c['done_when']}）" if c.get('done_when') else ''
            lines.append(f"     - {c.get('step','')}{done}")
    else:
        lines.append('     无')
    if unlocated:
        lines.append('   未能定位（不作为事实）')
        for f in unlocated:
            quote=str(f.get('quote') or '').strip()
            line=f"     - {f.get('text','')}"
            if quote: line+=f" — “{quote}”"
            lines.append(line)
    if unsupported:
        lines.append('   未获事实支持的推断')
        for inf in unsupported:
            lines.append(f"     - {inf.get('text','')}")
    return lines

def _card(i,x):
    a=x.get('analysis',{}); cls=x.get('classification',{}); lane=_lane(x)
    v5=a.get('schema_version')==5
    unknown='；'.join(a.get('uncertainties',[])) or '未填写'
    lines=['',f"{i}. [{x.get('score',0)}/100] {x.get('title','')}",
           f"   通道：{lane} · {LANE_LABEL[lane]}",
           f"   证据：{_evidence_text(x)} · 来源质量：{SOURCE_LABEL.get(cls.get('source_quality'),cls.get('source_quality',''))}"]
    priority=x.get('editorial_priority')
    if priority:
        lines.append(f"   编辑优先级：{priority} · 信号 {x.get('signal_score',x.get('score',0))}/100"
                     f" · 证据 {x.get('evidence_score',0)}/100（{x.get('priority_basis','')}）")
    if v5:
        lines.append(f"   排序分：{x.get('score',0)}/100（仅用于本期排序，不是结论）")
        lines+=_v5_sections(x, (x.get('event') or {}).get('evidence_status'))
    else:
        lines+=[f"   初判：{_judgment(a)}"]
        lines+=_quote_lines(x.get('evidence') or [])
        lines+=_estimate_hint(x)
    lines.append(_commercial_line(x))
    if not v5:
        lines+=[f"   关键未知：{unknown}",
                f"   下一步观察：{a.get('suggested_next_step','人工复核')}"]
    lines.append(f"   来源：{x.get('source_name','Unknown')} · {x.get('url','')}")
    return lines

KJ_LIMIT=4
ACTION_LIMIT=5

def _one_line(value,limit=60):
    """One clause, cut at a sentence boundary; never left dangling on a comma."""
    text=' '.join(str(value or '').split())
    if len(text)<=limit: return text
    for sep in ('。','；'):
        cut=text.find(sep,12,limit)
        if cut>0: return text[:cut+1]
    for i in range(12,min(limit,len(text))):
        if text[i]=='.' and (i+1==len(text) or text[i+1] in ' \t'):
            return text[:i+1]
    return text[:limit-1]+'…'

def _action_title(x):
    """A conclusion, not a topic label. The model's summary already states one."""
    return _one_line((x.get('analysis') or {}).get('summary_zh') or x.get('title',''),56)

def _evidence_basis(x):
    cls=x.get('classification',{})
    parts=[_evidence_text(x),MARKET_LABEL.get(_market(x),_market(x) or '未评估')]
    quality=SOURCE_LABEL.get(cls.get('source_quality'),cls.get('source_quality'))
    if quality: parts.append('来源 '+str(quality))
    located=sum(1 for f in (x.get('analysis') or {}).get('facts') or []
                if isinstance(f,dict) and f.get('status')=='located')
    parts.append(f'{located} 条可定位事实')
    return ' · '.join(parts)

def _confidence(x):
    """The model's confidence, downgraded where the evidence cannot carry it."""
    raw=_confidence_label((x.get('analysis') or {}).get('confidence'))
    if raw=='—': return '未评估'
    if raw=='高' and _market(x)!='buyer_confirmed': return '中（单一来源，未独立佐证）'
    return raw

def _implication(x):
    """The 'so what', expressed only with fields the analysis actually produced."""
    a=x.get('analysis',{}); cls=x.get('classification',{}); lane=_lane(x); comp=x.get('components') or {}
    buyer=BUYER_LABEL.get(cls.get('buyer_type'),'未知买方')
    if lane=='B':
        pain=_one_line(a.get('pain_point'),48) or '未描述具体问题'
        pay=PAY_LABEL.get(cls.get('buyer_payment_evidence',cls.get('payment_evidence')),'无证据')
        delivery=DELIVERY_LABEL.get(cls.get('delivery_fit'),'未评估')
        subject='' if buyer in ('未知买方','未知','') else buyer
        return f'{subject}存在「{pain}」；付费证据 {pay}，交付形态 {delivery}，均未验证。'
    if lane=='C':
        maturity=comp.get('technical_maturity') or cls.get('technical_maturity') or '—'
        repro=comp.get('reproducibility','—'); scope=comp.get('impact_scope','—')
        return (f'技术成熟度 {maturity} · 可复现性 {repro}/5 · 影响范围 {scope}/5；'
                '当前只支持跟踪，不支持产品决策。')
    # Lane A only earns an implication the analysis actually made. A repeated template line
    # four times over is filler, and filler is what makes a brief read as machine output.
    signal=str(a.get('commercial_signal') or '').strip()
    if signal.lower() not in NONE_WORDS:
        return signal
    return ''

NONE_WORDS={'','none','unknown','n/a','无','未知'}
PAY_STRONG_SET={'explicit_budget','existing_purchase'}
COMMERCIAL_SIGNALS={'payment_demand','user_pain','deployment_blocker','product_gap'}

def _has_commercial_edge(x):
    """Would this change an action, or is it background?

    Decided from structured fields only. Reading the free-text `commercial_signal` was
    unreliable: every item that says "无商业机会信号" contains the word 商业, so a keyword
    test promoted game reviews and statistics previews into the key judgments.
    """
    a=x.get('analysis') or {}; cls=x.get('classification') or {}
    pay=cls.get('buyer_payment_evidence') or cls.get('payment_evidence')
    if pay in PAY_STRONG_SET: return True
    if str(cls.get('signal_type') or '') in COMMERCIAL_SIGNALS: return True
    pain=str(a.get('pain_point') or '').strip().lower()
    if pain and pain not in NONE_WORDS: return True
    return False

ACTION_RANK={'act':0,'decide':1,'investigate':2,'monitor':3,'none':4,'':5}
LANE_RANK={'B':0,'A':1,'C':2}

def _pool_key(x):
    """Actionability first, then the opportunity lane, then editorial priority and score.

    A trend piece can carry the highest editorial priority and still be the wrong thing to
    lead with: the brief's job is to say what could change an action.
    """
    actionability=str((x.get('analysis') or {}).get('actionability') or '').lower()
    return (ACTION_RANK.get(actionability,5),LANE_RANK.get(_lane(x),3),_order_key(x))

def _judgment_pool(items):
    """Items that may lead: commercial edge first, ordered by what can be acted on."""
    return sorted([x for x in _shown(items) if _has_commercial_edge(x)],key=_pool_key)

def _key_judgments(items):
    """Three to five conclusions. With no commercial edge, the brief says so instead."""
    ranked=_judgment_pool(items)[:KJ_LIMIT]
    lines=[]
    if not ranked:
        lines.append('  本期入选条目的分析结论均为「无商业信号」：没有客户、预算、价格或采购迹象。')
        lines.append('  因此本节不设关键判断；条目仍保留在附录 A 供追溯，不作为行动依据。')
        return lines
    for i,x in enumerate(ranked,1):
        summary=_one_line((x.get('analysis') or {}).get('summary_zh') or x.get('title',''),140)
        lines+=[f'  KJ{i}｜{_action_title(x)}',
                f'       判断：{summary}',
                f'       依据：{_evidence_basis(x)}']
        implication=_implication(x)
        if implication: lines.append(f'       影响：{implication}')
        lines.append(f'       置信度：{_confidence(x)}')
    rest=len(_shown(items))-len(ranked)
    if rest>0:
        lines.append(f'  另有 {rest} 条入选条目没有可识别的商业信号（评测、预告、纯技术动态），'
                     '保留在附录 A 供追溯，不进入行动层。')
    return lines

def _next_actions(items):
    """The actions the analysis already proposed. Nothing is invented for the table.

    Each row cites the key judgment it serves (KJ1) rather than repeating that judgment's
    full sentence, which is what made the table unreadable.
    """
    pool=_judgment_pool(items)
    kj={id(x):i for i,x in enumerate(pool[:KJ_LIMIT],1)}
    rows=[]; seen=set()
    for x in pool:
        basis=f'KJ{kj[id(x)]}' if id(x) in kj else _one_line(x.get('title',''),32)
        for action in (x.get('analysis') or {}).get('actions') or []:
            if not isinstance(action,dict): continue
            step=_one_line(action.get('step'),70)
            if not step or step in seen: continue
            seen.add(step)
            rows.append((step,_one_line(action.get('done_when'),50) or '—',basis))
            if len(rows)>=ACTION_LIMIT: return rows
    return rows

def _hypotheses(items):
    """Inferences the analysis supports but has not verified. They stay labelled as such."""
    rows=[]
    for x in (_judgment_pool(items) or sorted(_shown(items),key=_order_key))[:KJ_LIMIT]:
        for inf in (x.get('analysis') or {}).get('inferences') or []:
            if not isinstance(inf,dict) or inf.get('status')!='supported': continue
            text=_one_line(inf.get('text'),110)
            if not text: continue
            rows.append((text,_basis_label(inf),_confidence_label(inf.get('confidence')),
                         _one_line(x.get('title',''),32)))
            if len(rows)>=4: return rows
    return rows

def _risks(items):
    """What would falsify this issue: single sources, unlocated quotes, open gaps."""
    rows=[]
    visible=_shown(items)
    single=[x for x in visible if _market(x)=='single_source']
    if single:
        rows.append(f'单一来源：{len(single)} 条判断只有 1 个来源，未获独立佐证，不得当作已验证结论。')
    unlocated=sum(1 for x in items for f in (x.get('analysis') or {}).get('facts') or []
                  if isinstance(f,dict) and f.get('status')!='located')
    if unlocated:
        rows.append(f'引文未定位：{unlocated} 条事实无法在原文中定位，已从事实层移出。')
    for x in sorted(visible,key=_order_key)[:3]:
        gaps=[g for g in (x.get('analysis') or {}).get('gaps') or []
              if isinstance(g,dict) and g.get('missing')]
        if gaps:
            short=_one_line(x.get('title',''),28)
            rows.append(f'证据缺口（{short}）：{_one_line(gaps[0].get("missing"),50)}')
    if not rows: rows.append('本期没有记录到会推翻现有判断的反证；这表示证据没有被检验过，不等于证据可靠。')
    return rows

def _watch_rows(items):
    """Watch-list rows: subject, the trigger that would change the judgment, current score."""
    rows=[]
    # An executive watch list is a short list; the appendix keeps the rest.
    for x in sorted([i for i in _shown(items) if i.get('status')=='watch'],key=_order_key)[:6]:
        gaps=[g for g in (x.get('analysis') or {}).get('gaps') or [] if isinstance(g,dict)]
        how=_one_line(gaps[0].get('how_to_close'),40) if gaps else ''
        rows.append((_one_line(x.get('title',''),40),how or '出现独立来源或付费证据',
                     f"{x.get('score',0)}/100"))
    return rows

REPORT_APPENDICES=(('appendix_a','八、附录 A · 条目明细（可追溯证据）'),
                  ('appendix_b','九、附录 B · 未纳入与失败'),
                  ('appendix_c','十、附录 C · 来源与数据源'))


def appendix_note(items,stats):
    """One compact line replacing the appendices in the email edition.

    The counts stay visible so an excluded item never disappears silently, but the
    traceability detail is stored in SQLite and the archive instead of being mailed.
    """
    shown=_shown(items); deferred=_deferred(items)
    filtered=[x for x in items if x.get('status')=='filtered']
    representatives,_siblings=group_by_event(shown)
    parts=[f'条目明细 {len(representatives)} 条']
    if deferred: parts.append(f'未纳入分发 {len(deferred)} 条')
    if filtered: parts.append(f'已过滤 {len(filtered)} 篇')
    if stats.get('watchlist'): parts.append('弱信号另行保留在库中')
    issues=len(stats.get('source_issues') or [])
    unresolved=int(stats.get('unresolved_sources') or 0)
    if issues or unresolved: parts.append(f'来源审计问题 {issues+unresolved} 项')
    return ('本次邮件只发送结论与证据方法部分；完整附录（'
            + ' · '.join(parts)
            + '）已写入本地数据库与归档报告，可追溯引文与未纳入条目请到管理台“日志与报告”查看完整版。')


def split_report(body):
    """Split a rendered report into its brief and the three appendix sections.

    Email uses the brief; SQLite keeps the appendices keyed by report hash so traceability
    survives archive cleanup. Returns (brief, [(kind,title,text), ...]).
    """
    lines=body.splitlines(); marks=[]
    for kind,title in REPORT_APPENDICES:
        for i,line in enumerate(lines):
            if line.strip()==title:
                marks.append((i,kind,title)); break
    if not marks: return body, []
    brief='\n'.join(lines[:marks[0][0]]).rstrip()
    sections=[]
    for n,(i,kind,title) in enumerate(marks):
        end=marks[n+1][0] if n+1<len(marks) else len(lines)
        sections.append((kind,title,'\n'.join(lines[i:end]).rstrip()))
    return brief,sections


def render_digest(items,stats,date_label=None,include_appendix=True):
    """Consulting-format brief: answer first, then the few judgments that carry it.

    Structure follows the pyramid principle used by MBB/Big Four briefs: a governing
    message, 3-5 key judgments with evidence and implication, an action table, the
    hypotheses still open, what would falsify them, a watch list, and a basis-of-preparation
    block. The evidence cards move to the appendix so the body stays readable.
    """
    date_label=date_label or datetime.now().astimezone().strftime('%Y-%m-%d')
    subject=f'Opportunity Radar｜商业机会情报简报｜{date_label}'
    fetched=stats.get('fetched',stats.get('article_count',0)); new=stats.get('new',0)
    queued=stats.get('queued',stats.get('analyzed_count',0)); analyzed=stats.get('analyzed',stats.get('analyzed_count',0))
    failed=stats.get('failed',stats.get('error_count',0)); skipped=stats.get('skipped',0)
    counts=stats.get('counts') or _counts(items); strong=sum(1 for x in items if _pay_strong(x))
    shown=_shown(items); deferred=_deferred(items)
    filtered=[x for x in items if x.get('status')=='filtered']
    coverage=stats.get('coverage')
    lines=[f'Opportunity Radar · 商业机会情报简报 · {date_label}','='*64]
    lines.append(f'报告编号 OR-{date_label.replace("-","")} · 生成于 {datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")}')
    lines.append(f'数据基础：本轮获取 {fetched} 篇 · 新增分析 {analyzed} 篇'
                 + (f' · 已有结果跳过 {skipped} 篇' if skipped else '')
                 + (f' · 分析覆盖率 {coverage:.0%}' if isinstance(coverage,(int,float)) else '')
                 + f' · 入选 {len(shown)} 条')
    if stats.get('sample_mode'):
        lines += ['','【演示数据声明】以下内容为离线样例，仅用于展示版式与评分流程，不代表真实来源或真实商业机会。']

    lines += ['','一、执行摘要（核心判断）','  '+decision_headline(items,stats)]
    note=management_note(items)
    if note: lines.append('  '+note)

    lines += ['','二、关键判断',
              '  按可执行性、通道与信号分排序；每条只回答一个问题：这条信息是否改变我们的行动。']
    lines += _key_judgments(items)

    actions=_next_actions(items)
    lines += ['','三、建议行动']
    if actions:
        lines.append('   序号  行动 | 完成标准 | 依据')
        for i,(step,done,base) in enumerate(actions,1):
            lines.append(f'   {i}. {step}')
            lines.append(f'      完成标准：{done}')
            lines.append(f'      依据：{base}')
    else:
        lines.append('   本期没有达到可执行程度的条目；维持监测，不启动新动作。')

    hypotheses=_hypotheses(items)
    lines += ['','四、待验证假设','   以下是分析给出、但尚未被证据支持的推断。不作为结论使用。']
    if hypotheses:
        for i,(text,basis,conf,title) in enumerate(hypotheses,1):
            lines.append(f'   H{i}｜{text}')
            lines.append(f'      依据 {basis} · 置信度 {conf} · 出自《{title}》')
    else:
        lines.append('   无。')

    lines += ['','五、风险与反证']
    lines += ['   - '+row for row in _risks(items)]

    watch=_watch_rows(items)
    lines += ['','六、监测清单']
    if watch:
        lines.append('   主题 | 触发条件 | 当前评分')
        for topic,trigger,score in watch:
            lines.append(f'   {topic} | {trigger} | {score}')
    else:
        lines.append('   本期没有需要单独设触发条件的观察项。')

    lines += ['','七、证据与方法（Basis of preparation）']
    funnel_line=' → '.join(f'{k} {v}' for k,v in funnel(stats))
    lines.append(f'   漏斗：{funnel_line}')
    if stats.get('render_only'):
        lines.append(f'   报告来源：基于数据库已保存的 {len(items)} 条分析重新生成（未重新调用模型）。')
    else:
        lines.append(f"   运行统计：获取 {fetched} | 新增 {new} | 内容更新 {stats.get('updated',0)} | 进入分析 {queued} | 成功 {analyzed} | 失败 {failed} | 已有结果跳过 {skipped} | 重复事件 {stats.get('duplicate_events',0)}")
    disclosed=disclosure(stats)
    if disclosed: lines.append(f'   运行完整性：{disclosed}')
    lanes=lane_breakdown(items)
    if lanes:
        lines.append('   通道分布：'+'，'.join(f"{LANE_LABEL[r['lane']]} 入选 {r['shown']} · 分析 {r['items']}" for r in lanes))
    lines.append(f"   入选分布：优先验证：{counts['priority']} · 持续观察：{counts['watch']}"
                 f" · 未纳入分发：{len(deferred)} · 明确付费证据：{strong}")
    ev=evidence_breakdown(items)
    lines.append('   证据强度：'+('，'.join(f"{STATE_LABEL.get(e['state'],e['state'])} {e['count']}" for e in ev) or '无'))
    present={_state(x) for x in items}
    meanings=[STATE_MEANING[st] for st in EVIDENCE_STATES if st in present and st in STATE_MEANING]
    if meanings: lines.append('   证据口径：'+' '.join(meanings))
    window=stats.get('sample_window')
    if window:
        lines.append(f"   样本窗口：{window.get('since') or '(无下界)'} 至 {window.get('until') or '(无上界)'} UTC"
                     f"（池 {window.get('pool')} → 窗口内 {window.get('in_window')} → 取 {window.get('sampled')}）")
    lines.append('   '+denominator_note(stats))
    evs=[e for x in items for e in (x.get('evidence') or [])]
    unlocated=sum(1 for e in evs if e.get('field')=='unlocated')
    lines.append(f'   引文定位：{len(evs)-unlocated} 条可定位 · {unlocated} 条无法在原文中定位')
    pipeline=stats.get('pipeline')
    if pipeline:
        steps=pipeline.get('steps') or {}
        ok=sum(1 for value in steps.values() if value.get('ok'))
        lines.append(f"   统一管线：{pipeline.get('status','')} · {ok}/{len(steps)} 步成功"
                     + (f" · 阻断：{','.join(pipeline.get('blocking_failures') or [])}" if pipeline.get('blocking_failures') else '')
                     + (f" · 警告：{','.join(pipeline.get('warnings') or [])}" if pipeline.get('warnings') else ''))
    lines.append(f"   分析记录：模型 {stats.get('model') or '未记录'} · 提示词 v{stats.get('prompt_version') or '未记录'}（{stats.get('prompt_hash') or 'hash未记录'}）· 规则 {stats.get('rules_version','v2')}")
    lines.append('   局限：本报告只覆盖已成功分析的条目；单一来源、未定位引文与未验证推断均已逐条标注，不构成对营收、市场规模或法律许可的结论。')

    if not include_appendix:
        lines += ['','附：完整附录已存档，不随邮件发送','   '+appendix_note(items,stats)]
        return subject,'\n'.join(lines)

    lines += ['','八、附录 A · 条目明细（可追溯证据）']
    representatives,_siblings=group_by_event(shown)
    if representatives:
        for i,x in enumerate(sorted(representatives,key=_order_key),1):
            lines+=_card(i,x)
            lines+=event_summary_lines(x)
    else:
        lines+=['',empty_reason(stats)]

    lines += ['','九、附录 B · 未纳入与失败']
    if deferred:
        lines.append(f'   本期未纳入分发（来源单期配额）：{len(deferred)} 条。原始判断保留，不代表价值较低。')
        for x in sorted(deferred,key=lambda v:(-v.get('score',0),v.get('title',''))):
            lines.append(f"     - [{STATUS_LABEL.get(x.get('status'),x.get('status'))} · {x.get('score',0)}/100] {x.get('title','')}（{x.get('source_name','Unknown')}）")
    if filtered:
        for reason in REASON_LABEL:
            group=[x for x in filtered if x.get('filter_reason')==reason]
            if group:
                lines.append(f'   已过滤 · {REASON_LABEL[reason]}：{len(group)} 篇')
                lines+=[f"     - [{x.get('score',0)}/100] {x.get('title','')}" for x in group[:10]]
    if not deferred and not filtered:
        lines.append('   无。')

    lines += ['','十、附录 C · 来源与数据源']
    src=source_breakdown(items)
    if src:
        lines.append('   来源贡献（分析条目 / 可定位引文）：')
        for r in src:
            detail=f"可定位引文 {r['located']}/{r['evidence']}" if r['evidence'] else '无引文'
            lines.append(f"     {r['source']}：分析 {r['items']} 条 · {detail}")
    lines.append('   情报主线：'+(('，'.join(f"{INTELLIGENCE_LINE_LABEL.get(k,k)} {v}" for k,v in summarize(items))) or '无')+'。按来源声明统计，未声明来源计为 (undeclared)。')
    conflict_lines=stats.get('conflicts') or []
    if conflict_lines:
        lines.append('   数据冲突（记录，不判定对错）：')
        lines+=[f'     {line}' for line in conflict_lines]
    quality=Counter(_evidence_text(x) for x in items)
    lines.append('   数据质量：证据等级分布 '+(', '.join(f'{k} {v}' for k,v in quality.most_common()) or '无')+'。仅标题或无法定位的摘录不能作为已验证需求。')
    sync=stats.get('source_sync')
    if sync:
        rows=[f"{name} {row.get('status')}"+(f"（{row.get('reason')}）" if row.get('reason') else '')
              for name,row in (sync.get('sources') or {}).items()]
        lines.append(f"   外部数据源同步（{str(sync.get('started_at') or '')[:10] or '时间未记录'}）："+', '.join(rows)+'. 各源独立入库，不进入本报告的证据与主张。')
    watch_lines=_watch_lines(stats)
    lines+=watch_lines
    lines+=_source_audit_note(stats)
    lines.append(_rules_line(stats))
    lines.append('   免责声明：初筛分数只表示相对优先级；营收、利润、市场规模和法律许可等主张必须核对原始来源及独立证据。')
    return subject,'\n'.join(lines)

def _watch_lines(stats):
    """Everything the digest did not promote, still visible with its reason.

    A weak signal is not a fact and never enters the publication gate; it is kept so a
    later run, a corroborating source or a human reviewer can act on it.
    """
    watch=stats.get('watchlist')
    if not watch: return []
    limit=int(watch.get('limit') or 8)
    lines=['','   弱信号（保留在库中，不进入主阅读区）',
           '   口径：这些条目保留在库中并参与追溯，不进入主阅读区；弱信号不等于事实，也不计入发布门禁。']
    opps=watch.get('opportunities') or {}; opp_items=opps.get('items') or []
    records=int(opps.get('records') or opps.get('count') or 0)
    titles=int(opps.get('count') or 0)
    extra_note=(f"，原始 {records} 条记录（同一文章重分析会生成多条）" if records>titles else '')
    lines.append(f"   1. 低置信 Opportunity：{titles} 个标题{extra_note}"
                 '（仅 signal_detected，未经问题/买方/付费验证）')
    for item in opp_items[:limit]:
        dup=(f" · 同标题 {(item.get('duplicates') or 0)+1} 条" if item.get('duplicates') else '')
        lines.append(f"      - [{display.label(item.get('tier'),item.get('reason'))}] {item.get('title')}"
                     f"（confidence {float(item.get('confidence') or 0):.2f} · 追溯链接 {item.get('links')}{dup}）")
    if int(opps.get('count') or 0) > len(opp_items):
        lines.append(f"      - 另有 {int(opps.get('count') or 0)-len(opp_items)} 条，见归档 JSON")
    nums=watch.get('numeric_without_claims') or {}; num_items=nums.get('items') or []
    lines.append(f"   2. 有数字但未形成可核验主张：{int(nums.get('count') or 0)} 篇")
    for item in num_items[:limit]:
        lines.append(f"      - [{display.label(item.get('tier'),item.get('reason'))}] {item.get('title')}"
                     f"（数字候选 {item.get('candidates')} 个）")
    if int(nums.get('count') or 0) > len(num_items):
        lines.append(f"      - 另有 {int(nums.get('count') or 0)-len(num_items)} 篇，见归档 JSON")
    links=watch.get('candidate_links') or {}; link_items=links.get('items') or []
    lines.append(f"   3. 可能相关事件（未确认合并）：{int(links.get('count') or 0)} 对。未经确认，不作为同一事件")
    for item in link_items[:limit]:
        basis=item.get('basis') or ''
        lines.append(f"      - [{display.label(item.get('tier'),item.get('reason'))}] {item.get('left')} ↔ {item.get('right')}"
                     f"（依据 {basis} · {float(item.get('confidence') or 0):.2f}）")
    if int(links.get('count') or 0) > len(link_items):
        lines.append(f"      - 另有 {int(links.get('count') or 0)-len(link_items)} 对，见归档 JSON")
    cap=int(watch.get('cap_unprocessed') or 0)
    if cap:
        lines.append(f"   4. N0–N5 本轮上限外：{cap} 篇已分析文章未进入主张提取，下一轮继续（不是丢弃）。")
    return lines

def _rules_line(stats):
    lane_weights=stats.get('lane_weights') or {}
    lane_th=stats.get('lane_thresholds') or {}
    parts=[]
    for lane in LANES:
        w=lane_weights.get(lane)
        if not w: continue
        th=lane_th.get(lane) or {}
        wtxt=' · '.join(f'{WEIGHT_LABEL.get(k,k)} {v}' for k,v in w.items())
        parts.append(f"{lane} 通道 {wtxt}（优先 {th.get('priority',75)} / 观察 {th.get('watch',55)}）")
    if not parts:
        th=stats.get('thresholds') or {}
        return f"   评分规则：版本 {stats.get('rules_version','v2')} · 阈值 优先 {th.get('priority',75)} / 观察 {th.get('watch',55)}。初筛分数只表示相对优先级。"
    return (f"   评分规则：版本 {stats.get('rules_version','v2')}。"+'；'.join(parts)+
            '。初筛分数只表示相对优先级，不同通道之间不可直接比较。')

def _source_audit_note(stats):
    """Surface feed and evidence problems instead of quietly shrinking the report."""
    issues=stats.get('source_issues') or []
    unresolved=int(stats.get('unresolved_sources') or 0)
    rows=['','   来源审计：']
    if not issues and not unresolved:
        return rows+['     本轮没有登记层面的阻塞问题。']
    match=stats.get('source_match') or {}
    if stats.get('render_only') and match:
        rows.append(f"     旧记录来源匹配：按 ID {match.get('by_id',0)} 条 · 按名称 {match.get('by_name',0)} 条 · 未匹配 {match.get('unresolved',0)} 条 · 名称冲突 {match.get('ambiguous',0)} 个。")
    if unresolved:
        rows.append(f'     {unresolved} 条历史记录未匹配到来源登记：通道按内容判断，且不套用任何来源配额。')
    for issue in issues[:12]:
        rows.append(f"     [{issue.get('severity','info')}] {issue.get('source_id','')} · {issue.get('code','')}：{issue.get('message','')}")
    return rows
