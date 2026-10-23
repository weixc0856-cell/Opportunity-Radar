from collections import Counter
from datetime import datetime
from .analytics import funnel,source_breakdown,evidence_breakdown,denominator_note,lane_breakdown
from .evidence import STATE_LABEL, STATE_MEANING, EVIDENCE_STATES, state_of
from .lanes import LANES, LANE_LABEL, LANE_PROMISE, item_lane as _lane

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
    if stats.get('sample_mode'): return '本页仅展示报告结构与评分流程，不形成真实商业判断。'
    visible=_shown(items); pri=[x for x in visible if x.get('status')=='priority']; watch=[x for x in visible if x.get('status')=='watch']
    deferred=_deferred(items)
    if pri:
        return f"本期筛选出 {len(pri)} 条达到验证门槛的信号，建议优先核实《{_top(pri)['title']}》。"
    if watch:
        return f"本期尚未发现经过验证的付费机会，建议集中核实一项：{_top(watch)['title']}。"
    if deferred and (watch or pri):
        return f"本期筛选出 {len(pri)} 条优先、{len(watch)} 条观察信号，另有 {len(deferred)} 条受来源单期配额限制未进入阅读区，详见附录。"
    if deferred: return f"本期有 {len(deferred)} 条达到观察或验证门槛，但受来源单期配额限制未进入阅读区，详见附录。"
    if not stats.get('fetched',stats.get('article_count',0)): return '本轮未获取到新内容，无法形成商业判断。'
    if stats.get('analyzed',stats.get('analyzed_count',0))==0 and stats.get('skipped',0)>0: return '本轮没有新增分析任务，结论沿用已有结果；不代表没有机会。'
    if stats.get('analyzed',stats.get('analyzed_count',0))==0 and stats.get('failed',stats.get('error_count',0))>0: return '本轮分析未完成，暂不形成商业判断。'
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
    if analyzed==0 and skipped>0: return f'本轮没有新的分析任务：{skipped} 篇文章均已有分析结果，无需重新分析。这只说明本轮没有新内容，不代表没有机会。'
    if analyzed==0 and failed>0: return f'本轮分析结果为空：{failed} 篇尝试分析均未通过，请查看运行日志排查原因。'
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

def _card(i,x):
    a=x.get('analysis',{}); cls=x.get('classification',{}); lane=_lane(x)
    ev=x.get('evidence') or []
    unknown='；'.join(a.get('uncertainties',[])) or '未填写'
    lines=['',f"{i}. [{x.get('score',0)}/100] {x.get('title','')}",
           f"   通道：{lane} · {LANE_LABEL[lane]}",
           f"   证据：{_evidence_text(x)} · 来源质量：{SOURCE_LABEL.get(cls.get('source_quality'),cls.get('source_quality',''))}",
           f"   初判：{_judgment(a)}"]
    lines+=_quote_lines(ev)
    lines+=_estimate_hint(x)
    lines+=[_commercial_line(x),
            f"   关键未知：{unknown}",
            f"   下一步观察：{a.get('suggested_next_step','人工复核')}",
            f"   来源：{x.get('source_name','Unknown')} · {x.get('url','')}"]
    return lines

def executive_brief(items):
    """Three items at most: what happened, why it matters, how far the evidence goes."""
    ranked=sorted(_shown(items),key=lambda v:v.get('score',0),reverse=True)[:3]
    if not ranked: return []
    out=['','执行摘要：']
    for i,x in enumerate(ranked,1):
        lane=_lane(x)
        out+=[f" {i}. [{lane}] {x.get('title','')}",
              f"    发生了什么：{str(x.get('analysis',{}).get('summary_zh','') or '').strip() or '未生成摘要'}",
              f"    为什么重要：{_why(x)}",
              f"    可信度：{_evidence_text(x)} · {MARKET_LABEL.get(_market(x),'未评估')}"]
    return out

def render_digest(items,stats,date_label=None):
    """Consulting-style text report: conclusion first, then one section per lane."""
    date_label=date_label or datetime.now().astimezone().strftime('%Y-%m-%d')
    subject=f'Opportunity Radar｜商业机会情报简报｜{date_label}'
    fetched=stats.get('fetched',stats.get('article_count',0)); new=stats.get('new',0)
    queued=stats.get('queued',stats.get('analyzed_count',0)); analyzed=stats.get('analyzed',stats.get('analyzed_count',0))
    failed=stats.get('failed',stats.get('error_count',0)); skipped=stats.get('skipped',0)
    counts=stats.get('counts') or _counts(items); strong=sum(1 for x in items if _pay_strong(x))
    shown=_shown(items); deferred=_deferred(items)
    filtered=[x for x in items if x.get('status')=='filtered']
    lines=[f'Opportunity Radar · 商业机会情报简报 · {date_label}','='*56]
    if stats.get('sample_mode'):
        lines += ['【演示数据声明】以下内容为离线样例，仅用于展示版式与评分流程，不代表真实来源或真实商业机会。','']
    lines += ['【执行摘要】',decision_headline(items,stats),('样例仅用于演示字段和版式，不构成对真实需求的判断。' if stats.get('sample_mode') else management_note(items)),'']
    lines += executive_brief(items)
    lines += ['',f"{'已保存分析' if stats.get('render_only') else '新增信号'}：{len(items) if stats.get('render_only') else new} | 持续观察：{counts['watch']} | 优先验证：{counts['priority']} | 明确付费证据：{strong} | 未纳入分发：{len(deferred)}"]
    lines.append(f'报告来源：基于数据库已保存的 {len(items)} 条分析重新生成（未重新调用模型）。' if stats.get('render_only')
                 else f"运行统计：获取 {fetched} | 新增 {new} | 内容更新 {stats.get('updated',0)} | 进入分析 {queued} | 成功 {analyzed} | 失败 {failed} | 已有结果跳过 {skipped} | 重复事件 {stats.get('duplicate_events',0)}")
    sections=[('一、商业、科技与经济情报','A'),('二、值得验证的商业机会','B'),('三、技术观察与工程信号','C')]
    for title,lane in sections:
        lines+=['',title,f'   通道定义：{LANE_PROMISE[lane]}']
        group=_by_lane(shown,lane)
        if group:
            for i,x in enumerate(sorted(group,key=lambda v:v.get('score',0),reverse=True),1): lines+=_card(i,x)
        else:
            lines+=['   本期该通道没有条目进入观察区。']
    if not shown and not filtered:
        lines+=['',empty_reason(stats)]
    lines+=['','四、数据概览']
    lines.append('   漏斗：'+' → '.join(f'{k} {v}' for k,v in funnel(stats)))
    lanes=lane_breakdown(items)
    lines.append('   通道分布：'+('，'.join(f"{LABEL} 入选 {r['shown']} · 分析 {r['items']}" for r,LABEL in ((r,LANE_LABEL[r['lane']]) for r in lanes)) or '无'))
    src=source_breakdown(items)
    if src:
        lines.append('   来源贡献（分析条目 / 可定位引文）：')
        for r in src:
            detail=f"可定位引文 {r['located']}/{r['evidence']}" if r['evidence'] else '无引文'
            lines.append(f"     {r['source']}：分析 {r['items']} 条 · {detail}")
    ev=evidence_breakdown(items)
    lines.append('   证据强度：'+('，'.join(f"{STATE_LABEL.get(e['state'],e['state'])} {e['count']}" for e in ev) or '无'))
    lines.append('   '+denominator_note(stats))
    lines+=['','五、附录','   来源分布：'+(', '.join(f'{k} {v}' for k,v in Counter(x.get('source_name','Unknown') for x in items).most_common()) or '无')]
    if deferred:
        lines.append(f'   本期未纳入分发（来源单期配额）：{len(deferred)} 条，原始判断保留如下')
        for x in sorted(deferred,key=lambda v:(-v.get('score',0),v.get('title',''))):
            lines.append(f"       - [{STATUS_LABEL.get(x.get('status'),x.get('status'))} · {x.get('score',0)}/100] {x.get('title','')}（{x.get('source_name','Unknown')}）")
    if filtered:
        lines.append('   已过滤与待补充：')
        for reason in REASON_LABEL:
            group=[x for x in filtered if x.get('filter_reason')==reason]
            if group:
                lines.append(f'     {REASON_LABEL[reason]}：{len(group)} 篇')
                lines+=[f"       - [{x.get('score',0)}/100] {x.get('title','')}" for x in group[:10]]
    quality=Counter(_evidence_text(x) for x in items)
    lines.append('   数据质量：证据等级分布 '+', '.join(f'{k} {v}' for k,v in quality.most_common())+'。仅标题或无法定位的摘录不能作为已验证需求。')
    lines+=_source_audit_note(stats)
    lines.append(f"   分析记录：模型 {stats.get('model') or '未记录'} · 提示词 v{stats.get('prompt_version') or '未记录'}（{stats.get('prompt_hash') or 'hash未记录'}）· 规则 {stats.get('rules_version','v2')}")
    evs=[e for x in items for e in (x.get('evidence') or [])]
    unlocated=sum(1 for e in evs if e.get('field')=='unlocated')
    lines.append(f"   引文定位：{len(evs)-unlocated} 条可定位 · {unlocated} 条无法在原文中定位")
    present={_state(x) for x in items}
    meanings=[STATE_MEANING[st] for st in EVIDENCE_STATES if st in present and st in STATE_MEANING]
    if meanings: lines.append('   证据口径：'+' '.join(meanings))
    lines.append(_rules_line(stats))
    lines.append('   免责声明：初筛分数只表示相对优先级；营收、利润、市场规模和法律许可等主张必须核对原始来源及独立证据。')
    return subject,'\n'.join(lines)

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
