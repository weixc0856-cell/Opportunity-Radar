from collections import Counter
from datetime import datetime
from .analytics import funnel,source_breakdown,evidence_breakdown,denominator_note

STATUS_LABEL={'priority':'优先验证','watch':'持续观察','filtered':'已过滤'}
REASON_LABEL={'hiring':'招聘/企业动态','no_business_signal':'无商业信号','content_insufficient':'内容不足，无法核实','low_score':'分数未达门槛'}
EVIDENCE_LABEL={'none':'无','title':'仅标题','untraceable':'无法在原文中定位','summary':'RSS 摘要','full_text':'正文'}
SIGNAL_LABEL={'payment_demand':'明确付费需求','user_pain':'用户痛点','deployment_blocker':'部署障碍','product_gap':'产品缺口','tech_trend':'技术趋势'}
BUYER_LABEL={'individual_dev':'个人开发者','smb':'中小企业','engineering_team':'工程团队','enterprise_it':'企业 IT','unknown':'未知'}
PAY_LABEL={'explicit_budget':'明确预算','stated_willingness':'表达了付费意愿','existing_purchase':'已有采购','indirect':'间接证据','none':'无证据'}
DELIVERY_LABEL={'service':'服务交付','custom_tool':'定制工具','product':'标准化产品','not_fit':'暂不适合'}
SOURCE_LABEL={'first_party':'一手用户表达','project_record':'项目记录','secondhand_report':'二手报道','vendor_marketing':'官方宣传'}
WEIGHT_LABEL={'demand_clarity':'需求明确度','payment_evidence':'付费证据','actionability':'可执行性','feasibility':'个人可行性','novelty':'新颖性'}
PAY_STRONG={'explicit_budget','existing_purchase'}

def _pay_strong(x):
    return x.get('classification',{}).get('payment_evidence') in PAY_STRONG

def _top(items):
    return max(items,key=lambda x:x.get('score',0)) if items else None

def decision_headline(items,stats):
    if stats.get('sample_mode'): return '本页仅展示报告结构与评分流程，不形成真实商业判断。'
    pri=[x for x in items if x.get('status')=='priority']; watch=[x for x in items if x.get('status')=='watch']
    if pri:
        return f"本期筛选出 {len(pri)} 条达到验证门槛的信号，建议优先核实《{_top(pri)['title']}》。"
    if watch:
        return f"本期尚未发现经过验证的付费机会，建议集中核实一项：{_top(watch)['title']}。"
    if not stats.get('fetched',stats.get('article_count',0)): return '本轮未获取到新内容，无法形成商业判断。'
    if stats.get('analyzed',stats.get('analyzed_count',0))==0 and stats.get('skipped',0)>0: return '本轮没有新增分析任务，结论沿用已有结果；不代表没有机会。'
    if stats.get('analyzed',stats.get('analyzed_count',0))==0 and stats.get('failed',stats.get('error_count',0))>0: return '本轮分析未完成，暂不形成商业判断。'
    return '本期没有信号通过筛选门槛，建议维持观察。'

def management_note(items):
    strong=sum(1 for x in items if _pay_strong(x))
    parts=[]
    if strong==0: parts.append('本期所有条目均缺少直接付费证据，当前证据更适合支持问题调查，而非进入产品开发。')
    else: parts.append(f'本期有 {strong} 条出现明确付费证据，可优先评估其真实性与可持续性。')
    eng=sum(1 for x in items if x.get('classification',{}).get('buyer_type')=='engineering_team')
    if eng: parts.append(f'其中 {eng} 条面向工程团队，与你既有的工程验证背景重叠最高。')
    parts.append('下一阶段的重点应从增加信息量转向验证需求的真实性、发生频率与付费可能性。')
    return ' '.join(parts)

def strategic_note(items):
    if not items: return '本期没有可分析的信号，无法形成战略判断。'
    kinds=Counter(x.get('classification',{}).get('signal_type','unknown') for x in items)
    top,n=kinds.most_common(1)[0]
    note=f'本期信号以{SIGNAL_LABEL.get(top,top)}为主（{n} 条）。'
    eng=sum(1 for x in items if x.get('classification',{}).get('buyer_type')=='engineering_team')
    if eng: note+=f'其中 {eng} 条买方为工程团队，宜优先评估能否以仿真自动化或工程数据工作流作为切入。'
    if not any(_pay_strong(x) for x in items): note+='由于没有任何条目出现预算或采购证据，现阶段不建议进入产品开发。'
    return note

def action_items(items):
    targets=sorted([x for x in items if x.get('status') in {'priority','watch'}],key=lambda x:x.get('score',0),reverse=True)[:3]
    if not targets: return ['维持现有来源，等待下一轮信号；不要为了填满报告而放宽门槛。']
    return [f"核实《{x['title']}》：确认问题是否仍然存在、影响哪些用户、现有替代方案为何不足；找到 2–3 名独立用户重复该问题后再评估方案。" for x in targets]

def empty_reason(stats):
    fetched=stats.get('fetched',stats.get('article_count',0)); analyzed=stats.get('analyzed',stats.get('analyzed_count',0))
    failed=stats.get('failed',stats.get('error_count',0)); skipped=stats.get('skipped',0)
    if not fetched: return '本轮没有从 FreshRSS 获取到文章。请检查来源状态与运行日志；这不代表没有商业机会。'
    if analyzed==0 and skipped>0: return f'本轮没有新的分析任务：{skipped} 篇文章均已有分析结果，无需重新分析。这只说明本轮没有新内容，不代表没有机会。'
    if analyzed==0 and failed>0: return f'本轮分析结果为空：{failed} 篇尝试分析均未通过，请查看运行日志排查原因。'
    return f'本轮没有满足条件的机会：{analyzed} 篇进入分析，均未达到 {stats.get("thresholds",{}).get("watch",55)} 分门槛或未通过硬性过滤。'

def _counts(items):
    return {s:sum(1 for x in items if x.get('status')==s) for s in STATUS_LABEL}

def _judgment(a):
    summary=str(a.get('summary_zh','') or '').strip(); cs=str(a.get('commercial_signal','') or '').strip()
    return f'{summary} {cs}'.strip() if cs.lower() not in {'','none','unknown','n/a','未知','无'} else summary

def _card(i,x):
    a=x.get('analysis',{}); cls=x.get('classification',{})
    ev=x.get('evidence') or []
    quotes='；'.join(f"[{e.get('id')}] {e.get('quote','')}" if e.get('id') else e.get('quote','') for e in ev) or '；'.join(a.get('evidence_quotes',[])) or '无可追溯摘录'
    unknown='；'.join(a.get('uncertainties',[])) or '未填写'
    level=EVIDENCE_LABEL.get(x.get('evidence_level'),x.get('evidence_level',''))
    judgment=_judgment(a)
    return ['',f"{i}. [{x.get('score',0)}/100] {x.get('title','')}",
            f"   初筛得分：{x.get('score',0)}/100（规则模型的相对优先级，不代表成功概率或市场规模）",
            f"   证据等级：{level} · 来源质量：{SOURCE_LABEL.get(cls.get('source_quality'),cls.get('source_quality',''))}",
            f"   事实：{quotes}",
            f"   初判：{judgment}",
            f"   商业评估：需求 {SIGNAL_LABEL.get(cls.get('signal_type'),cls.get('signal_type',''))} · 买方 {BUYER_LABEL.get(cls.get('buyer_type'),cls.get('buyer_type',''))} · 付费证据 {PAY_LABEL.get(cls.get('payment_evidence'),cls.get('payment_evidence',''))} · 交付 {DELIVERY_LABEL.get(cls.get('delivery_fit'),cls.get('delivery_fit',''))}",
            f"   关键未知：{unknown}",
            f"   建议验证：{a.get('suggested_next_step','人工复核')}",
            f"   来源：{x.get('source_name','Unknown')} · {x.get('url','')}"]

def render_digest(items,stats,date_label=None):
    """Consulting-style text report: conclusion first, then evidence, judgment and actions."""
    date_label=date_label or datetime.now().astimezone().strftime('%Y-%m-%d')
    subject=f'Opportunity Radar｜商业机会情报简报｜{date_label}'
    fetched=stats.get('fetched',stats.get('article_count',0)); new=stats.get('new',0)
    queued=stats.get('queued',stats.get('analyzed_count',0)); analyzed=stats.get('analyzed',stats.get('analyzed_count',0))
    failed=stats.get('failed',stats.get('error_count',0)); skipped=stats.get('skipped',0)
    counts=stats.get('counts') or _counts(items); strong=sum(1 for x in items if _pay_strong(x))
    priority=[x for x in items if x.get('status')=='priority']; watch=[x for x in items if x.get('status')=='watch']
    shown=priority+watch; filtered=[x for x in items if x.get('status')=='filtered']
    lines=[f'Opportunity Radar · 商业机会情报简报 · {date_label}','='*56]
    if stats.get('sample_mode'):
        lines += ['【演示数据声明】以下内容为离线样例，仅用于展示版式与评分流程，不代表真实来源或真实商业机会。','']
    lines += ['【执行摘要】',decision_headline(items,stats),('样例仅用于演示字段和版式，不构成对真实需求的判断。' if stats.get('sample_mode') else management_note(items)),'',
           f"{'已保存分析' if stats.get('render_only') else '新增信号'}：{len(items) if stats.get('render_only') else new} | 持续观察：{counts['watch']} | 优先验证：{counts['priority']} | 明确付费证据：{strong}"]
    lines.append(f'报告来源：基于数据库已保存的 {len(items)} 条分析重新生成（未重新调用模型）。' if stats.get('render_only')
                 else f"运行统计：获取 {fetched} | 新增 {new} | 内容更新 {stats.get('updated',0)} | 进入分析 {queued} | 成功 {analyzed} | 失败 {failed} | 已有结果跳过 {skipped}")
    lines.append('')
    lines+=['一、关键发现']
    if shown:
        for i,x in enumerate(sorted(shown,key=lambda v:v.get('score',0),reverse=True),1): lines+=_card(i,x)
    else:
        lines+=['',empty_reason(stats)]
    lines+=['','二、数据概览']
    lines.append('   漏斗：'+' → '.join(f'{k} {v}' for k,v in funnel(stats)))
    src=source_breakdown(items)
    if src:
        lines.append('   来源贡献（分析条目 / 可定位引文）：')
        for r in src:
            detail=f"可定位引文 {r['located']}/{r['evidence']}" if r['evidence'] else '无引文'
            lines.append(f"     {r['source']}：分析 {r['items']} 条 · {detail}")
    ev=evidence_breakdown(items)
    lines.append('   证据强度：'+('，'.join(f"{EVIDENCE_LABEL.get(e['level'],e['level'])} {e['count']}" for e in ev) or '无'))
    lines.append('   '+denominator_note(stats))
    lines+=['','三、商业评估']
    if shown:
        lines+=['   条目 | 需求 | 付费证据 | 交付可行性 | 证据等级']
        for x in sorted(shown,key=lambda v:v.get('score',0),reverse=True):
            cls=x.get('classification',{})
            lines.append(f"   {x.get('title','')[:28]} | {SIGNAL_LABEL.get(cls.get('signal_type'),'-')} | {PAY_LABEL.get(cls.get('payment_evidence'),'-')} | {DELIVERY_LABEL.get(cls.get('delivery_fit'),'-')} | {EVIDENCE_LABEL.get(x.get('evidence_level'),'-')}")
    else:
        lines.append('   本期没有进入观察区的条目，无法形成商业评估。')
    lines+=['','四、战略含义',strategic_note(items),'','五、建议行动']
    actions=['演示数据没有真实验证任务；请将此处替换为基于真实来源和证据的行动建议。'] if stats.get('sample_mode') else action_items(items)
    lines+=[f'{i}. {a}' for i,a in enumerate(actions,1)]
    lines+=['','六、附录','   来源分布：'+(', '.join(f'{k} {v}' for k,v in Counter(x.get('source_name','Unknown') for x in items).most_common()) or '无')]
    if filtered:
        lines.append('   已过滤与待补充：')
        for reason in REASON_LABEL:
            group=[x for x in filtered if x.get('filter_reason')==reason]
            if group:
                lines.append(f'     {REASON_LABEL[reason]}：{len(group)} 篇')
                lines+=[f"       - [{x.get('score',0)}/100] {x.get('title','')}" for x in group[:10]]
    quality=Counter(EVIDENCE_LABEL.get(x.get('evidence_level'),x.get('evidence_level','')) for x in items)
    lines.append('   数据质量：证据等级分布 '+', '.join(f'{k} {v}' for k,v in quality.most_common())+'。仅标题或无法定位的摘录不能作为已验证需求。')
    lines.append(f"   分析记录：模型 {stats.get('model') or '未记录'} · 提示词 v{stats.get('prompt_version') or '未记录'}（{stats.get('prompt_hash') or 'hash未记录'}）· 规则 {stats.get('rules_version','v2')}")
    evs=[e for x in items for e in (x.get('evidence') or [])]
    unlocated=sum(1 for e in evs if e.get('field')=='unlocated')
    lines.append(f"   引文定位：{len(evs)-unlocated} 条可定位 · {unlocated} 条无法在原文中定位")
    weights=stats.get('weights') or {}; th=stats.get('thresholds') or {}
    wtext=' · '.join(f'{WEIGHT_LABEL.get(k,k)} {v}' for k,v in weights.items()) or '默认'
    lines.append(f"   评分规则：版本 {stats.get('rules_version','v2')} · 权重 {wtext} · 阈值 优先 {th.get('priority',75)} / 观察 {th.get('watch',55)}。初筛分数只表示相对优先级。")
    lines.append('   免责声明：初筛分数只表示相对优先级；营收、利润、市场规模和法律许可等主张必须核对原始来源及独立证据。')
    return subject,'\n'.join(lines)
