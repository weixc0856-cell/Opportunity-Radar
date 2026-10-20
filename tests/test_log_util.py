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
