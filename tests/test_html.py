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
  self.assertIn('个人情报简报',html);self.assertIn('2026-10-20',html);self.assertIn('优先验证',html)
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
  self.assertIn('证据与方法',html);self.assertIn('处理漏斗',html);self.assertIn('<svg',html);self.assertIn('来源贡献',html)

class ConflictBlockTests(unittest.TestCase):
 def test_the_conflict_block_renders_both_sides(self):
  html=render_html([item()],stats(conflicts=['冲突主张：1 组（记录，不判定对错）','  · COCA COLA CO · capex · 2017（restatement）']),'2026-10-20')
  self.assertIn('数据冲突',html);self.assertIn('COCA COLA CO',html);self.assertIn('不判定对错',html)
 def test_no_block_without_conflicts(self):
  self.assertNotIn('数据冲突',render_html([item()],stats(),'2026-10-20'))



class EmailEditionTests(unittest.TestCase):
 def test_email_edition_has_no_appendix_cards(self):
  html=render_html([item()],stats(),'2026-10-20',include_appendix=False)
  self.assertIn('执行摘要',html)
  self.assertNotIn('附录 A · 条目明细',html)
  self.assertNotIn('class="card"',html)
  self.assertIn('完整附录',html)
 def test_full_edition_keeps_appendices(self):
  html=render_html([item()],stats(),'2026-10-20')
  self.assertIn('附录 A · 条目明细',html)


def rich_item(status='priority',title='real candidate'):
 it=item(status,80,title)
 it['evidence']=[{'id':'e1','quote':'q','field':'summary'}]
 it['evidence_state']='rss_excerpt_only'
 it['market_validation']='single_source'
 it['classification']={'article_type':'user_pain','signal_type':'user_pain','pain_evidence':'repeated',
                       'buyer_type':'engineering_team','delivery_fit':'custom_tool'}
 it['analysis']={'actionability':'investigate','summary_zh':title,'pain_point':'无法动态获取面名称',
                 'facts':[{'ordinal':1,'text':'f','quote':'q','status':'located','evidence_id':'e1'}],
                 'gaps':[{'missing':'官方接口是否已支持','why_it_matters':'w','how_to_close':'运行 example.py'}],
                 'actions':[{'step':'s','kind':'verify_fact','done_when':'d'}]}
 return it


class EmailClientCompatibilityTests(unittest.TestCase):
 """The mailed edition must survive clients that strip <style>, CSS grid/flex and SVG."""
 def test_email_edition_has_no_svg_or_style_block(self):
  html=render_html([rich_item()],stats(fetched=1,analyzed=1),'2026-10-20',include_appendix=False)
  self.assertNotIn('<svg',html)
  self.assertNotIn('<style',html)
  self.assertNotIn('display:grid',html)
  self.assertNotIn('display:flex',html)
 def test_email_edition_uses_tables_for_layout(self):
  html=render_html([rich_item()],stats(fetched=1,analyzed=1),'2026-10-20',include_appendix=False)
  self.assertIn('<table',html)
 def test_full_edition_still_uses_svg_charts(self):
  html=render_html([rich_item()],stats(fetched=1,analyzed=1),'2026-10-20')
  self.assertIn('<svg',html)
 def test_lane_labels_are_not_truncated_mid_word(self):
  for include_appendix in (True,False):
   html=render_html([rich_item()],stats(fetched=1,analyzed=1),'2026-10-20',include_appendix=include_appendix)
   self.assertIn('客户痛点与商业机会',html)
   self.assertNotIn('客户痛点与商业机<',html)
 def test_watch_list_trigger_is_a_condition_not_an_action(self):
  from opportunity_radar.digest import _watch_rows
  it=rich_item('watch','watched candidate')
  rows=_watch_rows([it])
  self.assertEqual(rows[0][1],'一旦确认：官方接口是否已支持')
 def test_readiness_row_does_not_repeat_the_evidence_row(self):
  html=render_html([rich_item()],stats(fetched=1,analyzed=1),'2026-10-20',include_appendix=True)
  self.assertIn('可执行性：调查',html)
