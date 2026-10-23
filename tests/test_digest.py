import unittest
from opportunity_radar.digest import render_digest, management_note

def item(status='watch',score=60,title='t',reason=''):
    return {'title':title,'url':'https://example.invalid/a','source_name':'s','analysis':{},'score':score,'status':status,
            'filter_reason':reason,'evidence_level':'summary','classification':{'article_type':'user_pain'},'risk_flag':''}

def news(status='priority',score=88,title='Acme raises guidance'):
    return {'title':title,'url':'https://example.invalid/n','source_name':'News','analysis':{},
            'score':score,'status':status,'filter_reason':'','evidence_level':'summary','evidence_state':'rss_excerpt_only',
            'classification':{'article_type':'funding','signal_type':'payment_demand','buyer_type':'enterprise_it'},'risk_flag':''}

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
 def test_failed_run_is_reported_as_empty(self):
  _,body=render_digest([],stats(fetched=10,failed=3),'2026-10-20')
  self.assertIn('分析结果为空',body)
 def test_primary_claims_land_in_their_lane_section(self):
  _,body=render_digest([news()],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('一、商业、科技与经济情报',body);self.assertIn('[88/100] Acme raises guidance',body)
 def test_community_pain_lands_in_the_opportunity_lane(self):
  _,body=render_digest([item('priority',80,'real candidate')],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('二、值得验证的商业机会',body);self.assertIn('[80/100] real candidate',body)
 def test_all_three_lane_sections_are_always_present(self):
  _,body=render_digest([item('watch',60)],stats(fetched=1,analyzed=1),'2026-10-20')
  for heading in ('一、商业、科技与经济情报','二、值得验证的商业机会','三、技术观察与工程信号'):
   self.assertIn(heading,body)
 def test_filtered_grouped_by_reason(self):
  _,body=render_digest([item('filtered',20,'a job',reason='hiring')],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('招聘/企业动态：1 篇',body)
 def test_stats_line_reports_each_stage(self):
  _,body=render_digest([],stats(fetched=10,new=2,updated=1,queued=3,analyzed=3,failed=1,skipped=7),'2026-10-20')
  self.assertIn('获取 10',body);self.assertIn('新增 2',body);self.assertIn('内容更新 1',body);self.assertIn('已有结果跳过 7',body)
 def test_conclusion_first(self):
  _,body=render_digest([item('watch',62,'ParaView crinkle')],stats(fetched=10,analyzed=10),'2026-10-20')
  head=body.split('【执行摘要】\n')[1].split('\n')[0]
  self.assertIn('建议集中核实',head);self.assertIn('ParaView crinkle',head)
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
 def test_data_overview_section(self):
  it=item('watch',60); it['evidence']=[{'id':'e1','quote':'q','field':'summary','start':0}]
  _,body=render_digest([it],stats(fetched=10,new=8,queued=6,analyzed=6,counts={'watch':1,'priority':0,'filtered':5}),'2026-10-20')
  self.assertIn('数据概览',body);self.assertIn('漏斗：本轮获取 10',body)
  self.assertIn('口径：本轮进入分析的 6 条',body)
 def test_none_commercial_signal_is_not_appended(self):
  it=item('watch',60); it['analysis']={'summary_zh':'用户报告了下载问题','commercial_signal':'none'}
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('初判：用户报告了下载问题',body);self.assertNotIn('下载问题 none',body)

 def test_executive_brief_has_at_most_three_items(self):
  items=[item('priority',90-i,f'item {i}') for i in range(5)]
  _,body=render_digest(items,stats(fetched=5,analyzed=5),'2026-10-20')
  brief=body.split('执行摘要：\n')[1].split('新增信号')[0]
  self.assertEqual(brief.count('发生了什么：'),3)
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
  it=item('priority',80,'same item')
  it['evidence']=[{'id':'e1','quote':'q','field':'summary'}]
  it['evidence_state']='rss_excerpt_only'; it['market_validation']='single_source'
  return it
 def test_brief_and_card_agree_on_evidence_and_validation(self):
  _,body=render_digest([self._rich()],stats(fetched=1,analyzed=1),'2026-10-20')
  brief=body.split('执行摘要：\n')[1].split('新增信号')[0]
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
  head=body.split('【执行摘要】\n')[1].split('\n')[0]
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
