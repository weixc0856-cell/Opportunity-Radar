import unittest
from opportunity_radar.config import load_scoring

class Tests(unittest.TestCase):
 def test_reads_weights_and_thresholds(self):
  c=load_scoring()
  self.assertEqual(c['thresholds']['priority'],75);self.assertEqual(c['thresholds']['watch'],55)
  self.assertEqual(sum(c['weights'].values()),100)
 def test_missing_file_returns_empty(self):
  self.assertEqual(load_scoring('config/does-not-exist.toml'),{})
