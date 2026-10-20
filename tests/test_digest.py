import unittest
from opportunity_radar.digest import render_digest

def item(status='watch',score=60,title='t',reason=''):
    return {'title':title,'url':'https://example.invalid/a','source_name':'s','analysis':{},'score':score,'status':status,
            'filter_reason':reason,'evidence_level':'summary','classification':{'article_type':'user_pain'},'risk_flag':''}

def stats(**kw):
    d={'fetched':0,'new':0,'queued':0,'analyzed':0,'failed':0,'skipped':0,
       'thresholds':{'priority':75,'watch':55},
       'weights':{'demand_clarity':25,'payment_evidence':25,'actionability':20,'feasibility':20,'novelty':10}}
    d.update(kw); return d

class Tests(unittest.TestCase):
 def test_sample_mode_disclaims_real_business_judgment(self):
  _,body=render_digest([item('watch',60,'synthetic')],stats(sample_mode=True,fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('不形成真实商业判断',body)
  self.assertIn('演示数据没有真实验证任务',body)
 def test_empty_no_data_is_honest(self):
  subject,body=render_digest([],stats(),'2026-10-20')
  self.assertIn('2026-10-20',subject);self.assertIn('本轮没有从 FreshRSS 获取到文章',body)
  self.assertNotIn('没有足够证据',body)
 def test_all_skipped_is_not_no_opportunity(self):
  _,body=render_digest([],stats(fetched=10,skipped=10),'2026-10-20')
  self.assertIn('本轮没有新的分析任务',body);self.assertIn('不代表没有机会',body)
 def test_failed_run_is_reported_as_empty(self):
  _,body=render_digest([],stats(fetched=10,failed=3),'2026-10-20')
  self.assertIn('分析结果为空',body)
 def test_priority_section(self):
  _,body=render_digest([item('priority',80,'real candidate')],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('一、关键发现',body);self.assertIn('[80/100] real candidate',body)
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
 def test_actions_are_named(self):
  _,body=render_digest([item('watch',62,'ParaView crinkle')],stats(fetched=10,analyzed=10),'2026-10-20')
  self.assertIn('五、建议行动',body);self.assertIn('核实《ParaView crinkle》',body)
 def test_strategic_note_has_no_raw_tuple(self):
  _,body=render_digest([item('watch',62)],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertNotIn("('",body)
 def test_rules_are_readable(self):
  _,body=render_digest([],stats(),'2026-10-20')
  self.assertIn('需求明确度 25',body);self.assertNotIn("{'demand_clarity'",body)
 def test_render_only_is_labelled(self):
  s=stats(fetched=10,analyzed=10); s['render_only']=True
  _,body=render_digest([item('watch',60)],s,'2026-10-20')
  self.assertIn('未重新调用模型',body);self.assertNotIn('运行统计：',body)
 def test_evidence_ids_rendered(self):
  it=item('watch',60); it['evidence']=[{'id':'e1','quote':'owners paid','field':'summary','start':0}]
  _,body=render_digest([it],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('[e1] owners paid',body)
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
