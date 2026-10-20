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
 def test_reads_weights_and_thresholds(self):
  c=load_scoring()
  self.assertEqual(c['thresholds']['priority'],75);self.assertEqual(c['thresholds']['watch'],55)
  self.assertEqual(sum(c['weights'].values()),100)
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
