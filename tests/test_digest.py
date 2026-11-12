import unittest
from opportunity_radar.digest import render_digest, management_note, readiness_of, decision_request

def item(status='watch',score=60,title='t',reason=''):
    return {'title':title,'url':'https://example.invalid/a','source_name':'s','analysis':{},'score':score,'status':status,
            'filter_reason':reason,'evidence_level':'summary','classification':{'article_type':'user_pain','signal_type':'user_pain'},'risk_flag':''}

def news(status='priority',score=88,title='Acme raises guidance'):
    return {'title':title,'url':'https://example.invalid/n','source_name':'News','analysis':{},
            'score':score,'status':status,'filter_reason':'','evidence_level':'summary','evidence_state':'rss_excerpt_only',
            'classification':{'article_type':'funding','signal_type':'payment_demand','buyer_type':'enterprise_it'},'risk_flag':''}

def validation_item(status='priority',score=80,title='real candidate'):
    it=item(status,score,title)
    it['evidence']=[{'id':'e1','quote':'q','field':'summary'}]
    it['evidence_state']='rss_excerpt_only'
    it['market_validation']='single_source'
    it['classification']={'article_type':'user_pain','signal_type':'user_pain','pain_evidence':'repeated'}
    it['analysis']={'actionability':'investigate','summary_zh':title,
                    'facts':[{'ordinal':1,'text':'f','quote':'q','status':'located','evidence_id':'e1'}],
                    'gaps':[{'missing':'m','why_it_matters':'w','how_to_close':'h'}],
                    'actions':[{'step':'s','kind':'verify_fact','done_when':'d'}]}
    return it


LANE_WEIGHTS={
 'A':{'importance':25,'source_reliability':20,'evidence_completeness':20,'novelty':15,'relevance':10,'timeliness':10},
 'B':{'pain_severity':20,'buyer_clarity':15,'payment_evidence':25,'corroboration':15,'feasibility':10,'solution_gap':10,'novelty':5},
 'C':{'technical_maturity':25,'reproducibility':20,'impact_scope':20,'source_reliability':20,'novelty':15}}

def stats(**kw):
    d={'fetched':0,'new':0,'queued':0,'analyzed':0,'failed':0,'skipped':0,
       'lane_weights':LANE_WEIGHTS,
       'lane_thresholds':{l:{'priority':75,'watch':55} for l in 'ABC'}}
    d.update(kw); return d

class Tests(unittest.TestCase):
 def test_sample_mode_disclaims_real_business_judgment(self):
  _,body=render_digest([item('watch',60,'synthetic')],stats(sample_mode=True,fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('不形成真实商业判断',body)
  self.assertIn('演示数据声明',body)
 def test_empty_no_data_is_honest(self):
  subject,body=render_digest([],stats(),'2026-10-20')
  self.assertIn('2026-10-20',subject);self.assertIn('本轮没有从 FreshRSS 获取到文章',body)
 def test_all_skipped_is_not_no_opportunity(self):
  _,body=render_digest([],stats(fetched=10,skipped=10),'2026-10-20')
  self.assertIn('本轮没有新的分析任务',body);self.assertIn('不代表没有机会',body)
 def test_skipped_and_failed_are_not_no_new_content(self):
  _,body=render_digest([],stats(fetched=10,skipped=5,failed=5),'2026-10-20')
  self.assertIn('本轮分析未完成',body)
  self.assertNotIn('本轮没有新增分析任务',body)
 def test_failed_run_is_reported_as_empty(self):
  _,body=render_digest([],stats(fetched=10,failed=3),'2026-10-20')
  self.assertIn('分析结果为空',body)
 def test_a_priority_item_leads_the_key_judgments(self):
  _,body=render_digest([news()],stats(fetched=1,analyzed=1),'2026-10-20')
  block=body.split('二、关键判断\n')[1].split('三、建议行动')[0]
  self.assertIn('Acme raises guidance',block)
 def test_a_selected_item_is_traceable_in_the_appendix(self):
  _,body=render_digest([item('priority',80,'real candidate')],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('[80/100] real candidate',body)
 def test_the_consulting_sections_are_always_present(self):
  _,body=render_digest([item('watch',60)],stats(fetched=1,analyzed=1),'2026-10-20')
  for heading in ('一、执行摘要（核心判断）','二、关键判断','三、建议行动','四、待验证假设',
                  '五、风险与反证','六、监测清单','七、证据与方法','八、附录 A'):
   self.assertIn(heading,body)
 def test_filtered_grouped_by_reason(self):
  _,body=render_digest([item('filtered',20,'a job',reason='hiring')],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('招聘/企业动态：1 篇',body)
 def test_stats_line_reports_each_stage(self):
  _,body=render_digest([],stats(fetched=10,new=2,updated=1,queued=3,analyzed=3,failed=1,skipped=7),'2026-10-20')
  self.assertIn('获取 10',body);self.assertIn('新增 2',body);self.assertIn('内容更新 1',body);self.assertIn('已有结果跳过 7',body)
 def test_conclusion_first(self):
  _,body=render_digest([validation_item('watch',62,'ParaView crinkle')],stats(fetched=10,analyzed=10),'2026-10-20')
  head=body.split('一、执行摘要（核心判断）\n')[1].split('\n')[0].strip()
  self.assertIn('验证级',head);self.assertIn('不投入产品开发',head)
 def test_next_step_is_inline(self):
  it=item('watch',62,'ParaView crinkle'); it['analysis']={'suggested_next_step':'联系 3 位 ParaView 用户确认复现条件'}
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('下一步观察：联系 3 位 ParaView 用户确认复现条件',body)
 def test_strategic_note_has_no_raw_tuple(self):
  _,body=render_digest([item('watch',62)],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertNotIn("('",body)
 def test_rules_are_readable(self):
  _,body=render_digest([],stats(),'2026-10-20')
  self.assertIn('B 通道',body);self.assertIn('付费证据 25',body);self.assertNotIn("{'pain_severity'",body)
 def test_render_only_is_labelled(self):
  s=stats(fetched=10,analyzed=10); s['render_only']=True
  _,body=render_digest([item('watch',60)],s,'2026-10-20')
  self.assertIn('未重新调用模型',body);self.assertNotIn('运行统计：',body)
 def test_evidence_ids_rendered(self):
  it=item('watch',60); it['evidence']=[{'id':'e1','quote':'owners paid','field':'summary','start':0}]
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('[e1] owners paid',body)
 def test_unlocated_quote_is_never_presented_as_fact(self):
  it=item('watch',60); it['evidence']=[{'id':'e1','quote':'q','field':'summary','start':0},
                                       {'id':'e2','quote':'invented sentence','field':'unlocated','start':-1}]
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  fact_line=next(l for l in body.splitlines() if '事实（可在原文定位）' in l)
  self.assertNotIn('invented sentence',fact_line)
  self.assertIn('未核实引文（原文中未找到，不作为事实）',body)
 def test_no_verified_quote_is_stated_plainly(self):
  it=item('watch',60); it['evidence']=[{'id':'e1','quote':'x','field':'unlocated','start':-1}]
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('事实（可在原文定位）：无可定位引文',body)
 def test_analysis_record_rendered(self):
  s=stats(fetched=1,analyzed=1); s['model']='qwen'; s['prompt_version']='2'
  _,body=render_digest([],s,'2026-10-20')
  self.assertIn('模型 qwen',body);self.assertIn('提示词 v2',body);self.assertIn('规则 v2',body)
  self.assertNotIn('规则 vv2',body)
 def test_evidence_locator_summary(self):
  it=item('watch',60)
  it['evidence']=[{'id':'e1','quote':'q','field':'summary','start':0},{'id':'e2','quote':'x','field':'unlocated','start':-1}]
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('1 条可定位 · 1 条无法在原文中定位',body)
 def test_basis_of_preparation_section(self):
  it=item('watch',60); it['evidence']=[{'id':'e1','quote':'q','field':'summary','start':0}]
  _,body=render_digest([it],stats(fetched=10,new=8,queued=6,analyzed=6,counts={'watch':1,'priority':0,'filtered':5}),'2026-10-20')
  self.assertIn('七、证据与方法',body);self.assertIn('漏斗：本轮获取 10',body)
  self.assertIn('口径：本轮进入分析的 6 条',body)
 def test_none_commercial_signal_is_not_appended(self):
  it=item('watch',60); it['analysis']={'summary_zh':'用户报告了下载问题','commercial_signal':'none'}
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('初判：用户报告了下载问题',body);self.assertNotIn('下载问题 none',body)

 def test_key_judgments_are_capped_at_four(self):
  items=[validation_item('priority',90-i,f'item {i}') for i in range(6)]
  _,body=render_digest(items,stats(fetched=6,analyzed=6),'2026-10-20')
  block=body.split('二、关键判断\n')[1].split('三、建议行动')[0]
  self.assertEqual(block.count('KJ'),4)
 def test_source_audit_section_reports_issues(self):
  s=stats(fetched=1,analyzed=1,source_issues=[{'severity':'warning','source_id':'x','code':'stale_last_verified_at','message':'re-review'}])
  _,body=render_digest([],s,'2026-10-20')
  self.assertIn('来源审计',body);self.assertIn('stale_last_verified_at',body)
 def test_management_note_counts_selected_items_only(self):
  a=item('watch',60,'w'); a['classification']={'article_type':'user_pain','buyer_type':'engineering_team'}
  b=item('filtered',20,'f'); b['classification']={'article_type':'tech','buyer_type':'engineering_team'}
  note=management_note([a,b])
  self.assertIn('入选 1 条',note); self.assertIn('有 1 条面向工程团队',note)

class LegacyRecordTests(unittest.TestCase):
 def test_archived_record_without_an_explicit_state_still_renders(self):
  it=item('watch',60); it['evidence']=[{'id':'e1','quote':'q','field':'summary'}]
  it['evidence_level']='summary'; it.pop('evidence_state',None)
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('E1 · 摘要引文已定位',body)

 def test_estimate_is_shown_when_it_exceeds_what_we_can_claim(self):
  it=item('watch',60)
  it['evidence']=[{'id':'e1','quote':'q','field':'summary'}]
  it['evidence_basis']='excerpt'; it['content_basis_estimate']='full_text'
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('内容完整性估计',body)
  self.assertIn('content_access_level=full_text',body)

 def test_estimate_hint_is_absent_when_the_source_is_reviewed(self):
  it=item('watch',60)
  it['evidence']=[{'id':'e1','quote':'q','field':'summary'}]
  it['evidence_basis']='full_text'; it['content_basis_estimate']='full_text'
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertNotIn('内容完整性估计',body)

 def test_evidence_scope_is_printed_in_the_appendix(self):
  it=item('watch',60); it['evidence']=[{'id':'e1','quote':'q','field':'summary'}]
  it['evidence_state']='multi_source_coverage'
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('证据口径',body)
  self.assertIn('尚未核对这些来源是否独立',body)

class OutputConsistencyTests(unittest.TestCase):
 """Every surface must describe the same item the same way."""
 def _rich(self):
  it=validation_item('priority',80,'same item')
  return it
 def test_brief_and_card_agree_on_evidence_and_validation(self):
  _,body=render_digest([self._rich()],stats(fetched=1,analyzed=1),'2026-10-20')
  brief=body.split('二、关键判断\n')[1].split('三、建议行动')[0]
  self.assertIn('E1 · 摘要引文已定位',brief)
  self.assertIn('单一来源',brief)
  card=next(l for l in body.splitlines() if l.startswith('   证据：'))
  self.assertIn('E1 · 摘要引文已定位',card)
 def test_multi_source_is_described_as_coverage_in_every_surface(self):
  from opportunity_radar.render_html import render_html
  it=self._rich(); it['market_validation']='multi_source'; it['evidence_state']='multi_source_coverage'
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  html=render_html([it],stats(fetched=1,analyzed=1),'2026-10-20')
  for surface in (body,html):
   self.assertIn('多来源覆盖',surface)
   self.assertIn('未核对',surface)
   self.assertNotIn('交叉验证已通过',surface)
 def test_one_evidence_vocabulary_only(self):
  from opportunity_radar import digest
  self.assertFalse(hasattr(digest,'EVIDENCE_LABEL'))

class DistributionTests(unittest.TestCase):
 """A quota decides what is printed, not what an item is worth."""
 def _deferred(self):
  it=item('priority',94,'供应链中断公告'); it['distribution']='deferred'
  return it
 def test_deferred_item_keeps_its_verdict_in_the_appendix(self):
  _,body=render_digest([self._deferred()],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('本期未纳入分发（来源单期配额）：1 条',body)
  self.assertIn('优先验证 · 94/100',body)
  # It must not also appear as a normal reading card.
  self.assertNotIn('1. [94/100] 供应链中断公告',body)
 def test_headline_reports_deferral_instead_of_no_signal(self):
  _,body=render_digest([self._deferred()],stats(fetched=1,analyzed=1),'2026-10-20')
  head=body.split('一、执行摘要（核心判断）\n')[1].split('\n')[0]
  self.assertIn('未进入阅读区',head)
  self.assertNotIn('没有信号通过筛选门槛',head)
 def test_stats_line_separates_verdict_from_distribution(self):
  _,body=render_digest([self._deferred()],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('优先验证：1',body)
  self.assertIn('未纳入分发：1',body)
 def test_management_note_explains_the_deferral(self):
  from opportunity_radar.digest import management_note
  note=management_note([self._deferred()])
  self.assertIn('不代表价值较低',note)
 def test_html_shows_deferred_separately_from_filtered(self):
  from opportunity_radar.render_html import render_html
  html=render_html([self._deferred()],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('本期未纳入分发',html)
  self.assertIn('优先验证 · 94/100',html)

class FailureReportingTests(unittest.TestCase):
 def test_a_failed_run_is_not_reported_as_no_new_tasks(self):
  from opportunity_radar.digest import empty_reason
  reason=empty_reason({'fetched':10,'analyzed':0,'failed':5,'skipped':5})
  self.assertIn('分析结果为空',reason)
  self.assertNotIn('没有新的分析任务',reason)

class EmptyReportTests(unittest.TestCase):
 def test_empty_briefing_states_the_evidence_distribution_as_none(self):
  _,body=render_digest([],stats(),'2026-10-20')
  self.assertIn('证据等级分布 无。',body)

class CoverageDisclosureTests(unittest.TestCase):
 def test_partial_coverage_is_named_in_the_headline_and_the_body(self):
  _,body=render_digest([item()],stats(fetched=10,queued=10,analyzed=6,failed=4,coverage=0.6,
        publication_status='PASS_WITH_LIMITATIONS',failed_causes={'http_5xx':4},not_attempted=0))
  self.assertIn('未完整完成',body);self.assertIn('覆盖率 60%',body)
  self.assertIn('运行完整性',body);self.assertIn('服务端错误 5xx 4',body)
 def test_a_breaker_is_visible_in_the_report(self):
  _,body=render_digest([item()],stats(fetched=10,queued=10,analyzed=9,failed=0,not_attempted=1,
        coverage=0.9,publication_status='PASS',failed_causes={'circuit_open':1}))
  self.assertIn('熔断后未尝试 1 篇',body)
 def test_a_complete_run_does_not_claim_a_gap(self):
  _,body=render_digest([item()],stats(fetched=5,queued=5,analyzed=5,coverage=1.0,publication_status='PASS'))
  self.assertNotIn('运行完整性',body)

class ConflictSectionTests(unittest.TestCase):
 def test_conflicts_are_printed_with_both_values(self):
  _,body=render_digest([item()],stats(fetched=1,analyzed=1,conflicts=[
      '冲突主张：1 组（记录，不判定对错）',
      '  · COCA COLA CO · capex · 2017-01-01/2017-12-31 · USD（restatement）']))
  self.assertIn('数据冲突',body)
  self.assertIn('COCA COLA CO',body)
 def test_no_conflicts_no_section(self):
  _,body=render_digest([item()],stats(fetched=1,analyzed=1))
  self.assertNotIn('数据冲突',body)



class EmailEditionTests(unittest.TestCase):
 """The mail carries the brief; traceability lives in the database and archive."""
 def _items(self):
  it=item('priority',80,'real candidate'); it['evidence']=[{'id':'e1','quote':'q','field':'summary'}]
  return [it]

 def test_email_edition_omits_appendices(self):
  _,body=render_digest(self._items(),stats(fetched=1,analyzed=1),'2026-10-20',include_appendix=False)
  for heading in ('一、执行摘要（核心判断）','二、关键判断','三、建议行动','四、待验证假设',
                  '五、风险与反证','六、监测清单','七、证据与方法'):
   self.assertIn(heading,body)
  for heading in ('八、附录 A','九、附录 B','十、附录 C'):
   self.assertNotIn(heading,body)
  self.assertIn('完整附录已存档',body)
  self.assertIn('不随邮件发送',body)

 def test_email_edition_keeps_excluded_counts_visible(self):
  it=item('priority',94,'supply'); it['distribution']='deferred'
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20',include_appendix=False)
  self.assertIn('未纳入分发 1 条',body)
  self.assertIn('本地数据库',body)

 def test_email_edition_still_discloses_partial_coverage(self):
  _,body=render_digest(self._items(),stats(fetched=10,queued=10,analyzed=6,failed=4,coverage=0.6,
        publication_status='PASS_WITH_LIMITATIONS'),'2026-10-20',include_appendix=False)
  self.assertIn('覆盖率 60%',body)
  self.assertIn('运行完整性',body)

 def test_split_report_keeps_the_appendices_for_storage(self):
  from opportunity_radar.digest import split_report
  _,body=render_digest(self._items(),stats(fetched=1,analyzed=1),'2026-10-20')
  brief,sections=split_report(body)
  self.assertNotIn('八、附录 A',brief)
  self.assertEqual([k for k,_,_ in sections],['appendix_a','appendix_b','appendix_c'])
  self.assertTrue(sections[0][2].startswith('八、附录 A'))
  self.assertIn('十、附录 C',sections[2][2])


class ReadinessTests(unittest.TestCase):
 def test_existing_purchase_is_validation_not_decision(self):
  it=validation_item('priority',80,'paid user complaint')
  it['classification']['buyer_payment_evidence']='existing_purchase'
  it['analysis']['actionability']='investigate'
  self.assertEqual(readiness_of(it),'validation')

 def test_explicit_budget_with_evidence_and_action_is_decision(self):
  it=validation_item('priority',80,'budgeted buyer')
  it['classification']['buyer_payment_evidence']='explicit_budget'
  it['analysis']['actionability']='decide'
  it['market_validation']='multi_source'
  it['evidence_state']='full_text_verified'
  self.assertEqual(readiness_of(it),'decision')

 def test_same_family_coverage_is_not_independent_enough_for_a_decision(self):
  it=validation_item('priority',80,'budgeted buyer')
  it['classification']['buyer_payment_evidence']='explicit_budget'
  it['analysis']['actionability']='decide'; it['evidence_state']='full_text_verified'
  it['market_validation']='multi_source'
  it['event']={'independent_corroboration':False,'source_families':['one-family'],
               'independent_source_units':1,'members':[{},{}]}
  self.assertEqual(readiness_of(it),'validation')

 def test_two_source_families_with_budget_are_decision_grade(self):
  it=validation_item('priority',80,'budgeted buyer')
  it['classification']['buyer_payment_evidence']='explicit_budget'
  it['analysis']['actionability']='decide'; it['evidence_state']='full_text_verified'
  it['event']={'independent_corroboration':True,'source_families':['a','b'],
               'independent_source_units':2,'members':[{},{}]}
  self.assertEqual(readiness_of(it),'decision')

 def test_title_only_signal_is_monitor(self):
  it=validation_item('priority',80,'title only')
  it['evidence']=[]; it['evidence_state']='title_only'
  it['analysis']['facts']=[]
  self.assertEqual(readiness_of(it),'monitor')

 def test_single_forum_post_is_validation_when_pain_repeats(self):
  it=validation_item('watch',60,'forum pain')
  self.assertEqual(readiness_of(it),'validation')


class DecisionSummaryTests(unittest.TestCase):
 def test_no_decision_grade_item_says_so_before_detail(self):
  _,body=render_digest([validation_item('watch',60)],stats(fetched=1,analyzed=1),'2026-10-20')
  head=body.split('一、执行摘要（核心判断）\n')[1].split('\n')[0]
  self.assertIn('没有决策级机会',head)
  self.assertIn('不投入产品开发',head)

 def test_decision_request_is_explicit_and_defaults_to_no_investment(self):
  items=[validation_item('watch',60)]
  request=decision_request(items,stats(fetched=1,analyzed=1))
  self.assertIn('限时验证',request)
  self.assertIn('默认不投入',request)

 def test_verification_ledger_names_gap_and_stop_condition(self):
  _,body=render_digest([validation_item('watch',60,'ledger candidate')],stats(fetched=1,analyzed=1),'2026-10-20')
  ledger=body.split('验证台账（候选')[1]
  self.assertIn('关键缺口',ledger)
  self.assertIn('停止条件',ledger)
  self.assertIn('不是市场规模或收入预测',ledger)

 def test_risk_register_is_a_table_not_a_bullet_list(self):
  _,body=render_digest([validation_item('watch',60)],stats(fetched=1,analyzed=1),'2026-10-20')
  block=body.split('五、风险与反证\n')[1].split('六、监测清单')[0]
  self.assertIn('风险 | 触发条件 | 影响 | 应对',block)
  self.assertIn('单一来源',block)

 def test_validation_records_are_shown_in_the_judgment_and_ledger(self):
  it=validation_item('watch',60,'validated candidate')
  it['validation']=[{'kind':'interview','result':'supports','note':'买方确认预算','recorded_at':'2026-11-12T00:00:00+00:00'}]
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('验证记录：访谈 / 支持',body)
  self.assertIn('验证记录（最近）',body)
  self.assertIn('买方确认预算',body)

 def test_v9_executive_fields_override_fallbacks(self):
  it=validation_item('watch',60,'v9 item')
  it['analysis'].update({'action_title':'模型给出的完整执行标题',
                         'so_what':'模型给出的决策含义。',
                         'why_now':'本周发布新版本。',
                         'kill_criteria':['两周内找不到第二来源']})
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('KJ1｜模型给出的完整执行标题',body)
  self.assertIn('影响（so what）：模型给出的决策含义。',body)
  self.assertIn('时效性：本周发布新版本。',body)
  self.assertIn('停止条件：两周内找不到第二来源',body)


class ProvenanceRenderingTests(unittest.TestCase):
 def test_youtube_and_search_provenance_are_printed(self):
  it=validation_item('watch',60,'provenance item')
  it['youtube']={'channel':'Test Channel','transcript_kind':'auto',
                 'excerpt_start':75.0,'excerpt_end':180.0}
  it['discovery']={'provider':'google_news','query_id':'gnews-ai',
                   'publisher':'Reuters','page_status':'not_attempted'}
  s=stats(fetched=1,analyzed=1,
          youtube={'candidates':2,'selected':1,'fetched':1,'analyzed':1,'skipped_reason':{}},
          discovery={'queries':1,'candidates':3,'selected':1,'page_fetched':0,
                     'page_skipped':0,'providers':{'google_news':3}})
  _,body=render_digest([it],s,'2026-10-20')
  self.assertIn('YouTube：Test Channel · 字幕 自动字幕',body)
  self.assertIn('公开检索：google_news · gnews-ai',body)
  self.assertIn('YouTube 字幕：候选 2',body)
  self.assertIn('公开检索：查询 1',body)
  self.assertIn('按 E1 上限处理',body)
