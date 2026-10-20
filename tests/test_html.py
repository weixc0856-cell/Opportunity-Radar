import unittest
from opportunity_radar.render_html import render_html

def item(status='priority',score=80,title='candidate',url='https://example.invalid/a'):
    return {'title':title,'url':url,'source_name':'s','analysis':{'summary_zh':'s','target_customer':'t','commercial_signal':'c',
            'evidence_quotes':['q'],'uncertainties':['u'],'suggested_next_step':'interview 5 people'},'score':score,
            'status':status,'filter_reason':'','evidence_level':'summary','classification':{'article_type':'user_pain'},'risk_flag':''}

def stats(**kw):
    d={'fetched':10,'new':1,'analyzed':1,'failed':0,'skipped':9,'counts':{'priority':1,'watch':0,'filtered':0},'rules_version':'v2'}; d.update(kw); return d

class Tests(unittest.TestCase):
 def test_renders_report_shell(self):
  html=render_html([item()],stats(),'2026-10-20')
  self.assertIn('商业机会情报简报',html);self.assertIn('2026-10-20',html);self.assertIn('优先验证',html)
 def test_includes_source_link(self):
  html=render_html([item()],stats(),'2026-10-20')
  self.assertIn('href="https://example.invalid/a"',html);self.assertIn('打开原文',html)
 def test_escapes_untrusted_text(self):
  html=render_html([item(title='<script>alert(1)</script>')],stats(),'2026-10-20')
  self.assertNotIn('<script>alert(1)</script>',html);self.assertIn('&lt;script&gt;',html)
 def test_unsafe_source_url_is_not_rendered_as_link(self):
  html=render_html([item(url='javascript:alert(1)')],stats(),'2026-10-20')
  self.assertNotIn('href="javascript:alert(1)',html)
  self.assertIn('原文链接不可用',html)
 def test_sample_mode_has_prominent_disclaimer(self):
  html=render_html([item()],stats(sample_mode=True),'2026-10-20')
  self.assertIn('离线演示数据',html)
  self.assertIn('不代表真实来源、用户需求或商业机会',html)
 def test_no_priority_shows_empty_reason(self):
  html=render_html([],stats(fetched=10,analyzed=0,skipped=10,counts={'priority':0,'watch':0,'filtered':0},empty_reason='本轮没有新的分析任务'),'2026-10-20')
  self.assertIn('本轮没有新的分析任务',html)
 def test_filtered_reasons_rendered(self):
  it=item(status='filtered',score=20); it['filter_reason']='hiring'
  html=render_html([it],stats(counts={'priority':0,'watch':0,'filtered':1}),'2026-10-20')
  self.assertIn('招聘/企业动态',html)
 def test_includes_data_overview_charts(self):
  html=render_html([item()],stats(),'2026-10-20')
  self.assertIn('数据概览',html);self.assertIn('处理漏斗',html);self.assertIn('<svg',html);self.assertIn('来源贡献',html)
