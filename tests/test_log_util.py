import tempfile,unittest
from pathlib import Path
from opportunity_radar.log_util import redact, rotate_log

class RedactTests(unittest.TestCase):
 def test_masks_credentials(self):
  text=redact('password=abc123 api_key: xyz Authorization: Bearer tok')
  self.assertNotIn('abc123',text);self.assertNotIn('xyz',text);self.assertNotIn('tok',text)
 def test_masks_email_address(self):
  self.assertIn('us***@example.com',redact('contact user@example.com now'))
 def test_leaves_normal_text(self):
  self.assertEqual(redact('no secrets here'),'no secrets here')

class RotateTests(unittest.TestCase):
 def test_rotates_when_over_limit(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'app.log'; p.write_text('x'*1200)
   self.assertTrue(rotate_log(p,max_bytes=1000,backups=2))
   self.assertFalse(p.exists()); self.assertTrue(Path(str(p)+'.1').exists())
 def test_does_not_rotate_small_file(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'app.log'; p.write_text('x'*10)
   self.assertFalse(rotate_log(p,max_bytes=1000)); self.assertTrue(p.exists())

class RedactFilterTests(unittest.TestCase):
 """The filter runs on every log record; it must not change argument types."""
 def _record(self,msg,args):
  import logging
  return logging.LogRecord('x',logging.INFO,'f.py',1,msg,args,None)
 def test_numeric_arguments_survive_percent_d(self):
  from opportunity_radar.log_util import RedactFilter
  r=self._record('Digest sent: articles=%d analyzed=%d errors=%d recipients=%d',(10,10,0,3))
  RedactFilter().filter(r)
  self.assertEqual(r.getMessage(),'Digest sent: articles=10 analyzed=10 errors=0 recipients=3')
 def test_secrets_in_arguments_are_still_masked(self):
  from opportunity_radar.log_util import RedactFilter
  r=self._record('fetch %s',('https://x?api_key=abc123',))
  RedactFilter().filter(r)
  self.assertNotIn('abc123',r.getMessage())
 def test_zero_is_not_turned_into_an_empty_string(self):
  from opportunity_radar.log_util import redact
  self.assertEqual(redact(0),0)
  self.assertEqual(redact(None),'')
 def test_a_real_handler_emits_the_record_without_error(self):
  import io,logging
  from opportunity_radar.log_util import RedactFilter
  stream=io.StringIO(); handler=logging.StreamHandler(stream)
  handler.addFilter(RedactFilter())
  logger=logging.getLogger('redact-filter-test'); logger.handlers=[handler]; logger.setLevel(logging.INFO)
  logger.info('Digest sent: articles=%d errors=%d',10,0)
  self.assertIn('articles=10 errors=0',stream.getvalue())
