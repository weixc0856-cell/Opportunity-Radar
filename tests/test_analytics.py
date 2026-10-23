import unittest
from opportunity_radar.analytics import funnel,source_breakdown,evidence_breakdown,denominator_note,lane_breakdown

def item(source,level,fields,status='watch',lane='B'):
    return {'source_name':source,'evidence_level':level,'evidence':[{'field':f} for f in fields],
            'status':status,'lane':lane}

class Tests(unittest.TestCase):
 def test_funnel_values(self):
  rows=dict(funnel({'fetched':10,'new':8,'queued':6,'analyzed':5,'counts':{'watch':2,'priority':1}}))
  self.assertEqual(rows['本轮获取'],10);self.assertEqual(rows['分析成功'],5);self.assertEqual(rows['优先验证'],1)
 def test_render_only_funnel_does_not_show_fake_zeros(self):
  rows=funnel({'analyzed':10,'render_only':True,'counts':{'watch':2,'priority':0}})
  self.assertEqual(rows[0],('已保存分析',10));self.assertNotIn('新增',dict(rows))
 def test_source_breakdown_counts_located_evidence(self):
  items=[item('A','summary',['summary','unlocated']),item('A','title',['title']),item('B','none',[])]
  rows={r['source']:r for r in source_breakdown(items)}
  self.assertEqual(rows['A']['items'],2);self.assertEqual(rows['A']['evidence'],3);self.assertEqual(rows['A']['located'],2)
  self.assertEqual(rows['B']['items'],1);self.assertEqual(rows['B']['located'],0)
 def test_evidence_breakdown_is_ordered_strongest_first(self):
  rows=evidence_breakdown([item('A','title',[]),item('B','summary',[]),item('C','summary',[])])
  self.assertEqual(rows[0],{'state':'rss_excerpt_only','count':2})
  self.assertEqual(rows[1],{'state':'title_only','count':1})
 def test_evidence_breakdown_prefers_the_explicit_state(self):
  it=item('A','summary',[]); it['evidence_state']='primary_source_located'
  self.assertEqual(evidence_breakdown([it])[0]['state'],'primary_source_located')
 def test_lane_breakdown_counts_per_lane(self):
  items=[item('A','summary',[],lane='A'),item('B','summary',[],lane='A'),item('C','summary',[],lane='B',status='priority')]
  rows={r['lane']:r for r in lane_breakdown(items)}
  self.assertEqual(rows['A']['items'],2);self.assertEqual(rows['A']['shown'],2)
  self.assertEqual(rows['B']['priority'],1);self.assertEqual(rows['C']['items'],0)
 def test_denominator_note_mentions_scope(self):
  self.assertIn('进入分析的 10 条',denominator_note({'analyzed':10}))
  self.assertIn('未重新调用模型',denominator_note({'analyzed':10,'render_only':True}))
