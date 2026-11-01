import unittest
from opportunity_radar.config import load_scoring, Settings

def settings(**kw):
    base=dict(freshrss_base_url='',freshrss_username='',freshrss_api_key='',llm_base_url='',llm_model='',llm_api_key='',
              llm_timeout=90,llm_max_tokens=500,smtp_host='smtp.163.com',smtp_port=465,smtp_username='u@163.com',
              smtp_password='abcd1234abcd1234',email_from='u@163.com',email_to='u@163.com',smtp_starttls=False,
              max_articles=10,request_timeout=20,db_path='',log_path='',report_dir='',smtp_security='ssl',
              email_on_empty=False,alert_after_failures=3)
    base.update(kw); return Settings(**base)

class Tests(unittest.TestCase):
 def test_reads_lane_weights_and_thresholds(self):
  c=load_scoring()
  lanes=c['lanes']
  self.assertEqual(set(lanes),{'A','B','C'})
  for lane in ('A','B','C'):
   self.assertEqual(lanes[lane]['thresholds']['priority'],75)
   self.assertEqual(lanes[lane]['thresholds']['watch'],55)
   self.assertEqual(sum(lanes[lane]['weights'].values()),100,lane)
 def test_lane_promotion_gates_are_declared(self):
  lanes=load_scoring()['lanes']
  self.assertEqual(lanes['A']['promote_rank'],'E1')
  self.assertEqual(lanes['B']['promote_rank'],'E2')
  self.assertEqual(lanes['C']['promote_rank'],'E2')
 def test_evidence_threshold_is_configured(self):
  self.assertGreater(load_scoring()['evidence']['full_text_min_chars'],0)
 def test_missing_file_returns_empty(self):
  self.assertEqual(load_scoring('config/does-not-exist.toml'),{})
 def test_mail_config_accepts_complete_settings(self):
  self.assertEqual(settings().validate_mail(),[])
 def test_mail_config_flags_placeholder_password(self):
  self.assertIn('OR_SMTP_PASSWORD', ' '.join(settings(smtp_password='replace_me').validate_mail()))
 def test_mail_config_flags_invalid_address(self):
  self.assertIn('OR_EMAIL_TO', ' '.join(settings(email_to='not-an-email').validate_mail()))
 def test_mail_config_flags_bad_port_and_security(self):
  issues=' '.join(settings(smtp_port=0,smtp_security='guess').validate_mail())
  self.assertIn('OR_SMTP_PORT',issues);self.assertIn('OR_SMTP_SECURITY',issues)
 def test_mail_config_accepts_multiple_recipients(self):
  self.assertEqual(settings(email_to='a@163.com, b@qq.com; c@gmail.com').validate_mail(),[])
 def test_mail_config_flags_invalid_recipient_among_many(self):
  issues=' '.join(settings(email_to='a@163.com, not-an-email').validate_mail())
  self.assertIn('OR_EMAIL_TO contains an invalid address',issues)

class PublicationSettingsTests(unittest.TestCase):
 def test_defaults_match_the_approved_thresholds(self):
  s=settings()
  self.assertEqual((s.publish_min_coverage,s.publish_hold_below),(0.8,0.5))
  self.assertEqual((s.llm_connect_retries,s.llm_timeout_retries),(3,1))
 def test_ratio_is_clamped_and_junk_falls_back(self):
  from opportunity_radar.config import _ratio
  self.assertEqual(_ratio('0.9'),0.9); self.assertEqual(_ratio('1.5'),1.0)
  self.assertEqual(_ratio('-1'),0.0); self.assertEqual(_ratio('abc'),1.0)
  self.assertEqual(_ratio('nan'),1.0)
 def test_backoff_parsing_ignores_junk(self):
  from opportunity_radar.config import parse_backoff
  self.assertEqual(parse_backoff('1,2,3'),(1.0,2.0,3.0))
  self.assertEqual(parse_backoff('x,4'),(4.0,))
  self.assertEqual(parse_backoff(''),(2.0,5.0,10.0))
 def test_environment_overrides_are_read(self):
  import os
  from unittest import mock
  with mock.patch.dict(os.environ,{'OR_PUBLISH_MIN_COVERAGE':'0.9','OR_PUBLISH_HOLD_BELOW':'0.6',
                                   'OR_LLM_CONNECT_RETRIES':'2'},clear=False):
   s=Settings.from_env()
  self.assertEqual((s.publish_min_coverage,s.publish_hold_below,s.llm_connect_retries),(0.9,0.6,2))

