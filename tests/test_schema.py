import json,unittest
from opportunity_radar.schema import parse_model_json
VALID={'category':'customer_pain','summary_zh':'测试','pain_point':'痛点','target_customer':'客户','commercial_signal':'未知','revenue_claim':'none','evidence_quotes':[],'uncertainties':['待核实'],'suggested_next_step':'访谈','relevance_score':50,'confidence':'low'}
class Tests(unittest.TestCase):
 def test_valid(self): self.assertEqual(parse_model_json(json.dumps(VALID))['category'],'customer_pain')
 def test_missing_field(self):
  d=dict(VALID);d.pop('summary_zh')
  with self.assertRaises(ValueError):parse_model_json(json.dumps(d))
 def test_bad_category(self):
  d=dict(VALID);d['category']='magic'
  with self.assertRaises(ValueError):parse_model_json(json.dumps(d))
 def test_think_prefix_stripped(self):
  raw='<think>\nweighing options\n</think>\n'+json.dumps(VALID)
  self.assertEqual(parse_model_json(raw)['category'],'customer_pain')
 def test_empty_think_prefix_stripped(self):
  raw='<think>\n\n</think>\n\n'+json.dumps(VALID)
  self.assertEqual(parse_model_json(raw)['category'],'customer_pain')
 def test_fenced_json_unwrapped(self):
  raw='```json\n'+json.dumps(VALID)+'\n```'
  self.assertEqual(parse_model_json(raw)['category'],'customer_pain')
 def test_prose_wrapped_json_recovered(self):
  raw='Here is the result:\n'+json.dumps(VALID)+'\nHope this helps.'
  self.assertEqual(parse_model_json(raw)['category'],'customer_pain')
 def test_unterminated_think_rejected(self):
  with self.assertRaises(ValueError):parse_model_json('<think>\nstill reasoning about the article')
 def test_list_field_as_string_wrapped(self):
  d=dict(VALID);d['evidence_quotes']='exact quote';d['uncertainties']='needs checking'
  r=parse_model_json(json.dumps(d))
  self.assertEqual(r['evidence_quotes'],['exact quote']);self.assertEqual(r['uncertainties'],['needs checking'])
 def test_unescaped_inner_quote_repaired(self):
  d=dict(VALID);d['summary_zh']='标题为“无广告 Android TV" 的讨论'
  raw=json.dumps(d,ensure_ascii=False).replace('\\"','"')
  self.assertIn('TV" 的讨论',raw)
  self.assertEqual(parse_model_json(raw)['summary_zh'],d['summary_zh'])
 def test_escaped_quotes_untouched(self):
  d=dict(VALID);d['summary_zh']='他说 "你好" 然后走了'
  self.assertEqual(parse_model_json(json.dumps(d,ensure_ascii=False))['summary_zh'],d['summary_zh'])
