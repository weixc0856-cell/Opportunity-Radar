import unittest
from opportunity_radar.admin_server import valid_email, read_sources, source_validation

class AdminServerTests(unittest.TestCase):
    def test_email_validation(self):
        self.assertTrue(valid_email('reader@example.com'))
        self.assertFalse(valid_email('not-an-email'))
        self.assertFalse(valid_email('reader@example.com,other@example.com'))

    def test_curated_sources_are_candidates_not_enabled(self):
        rows = read_sources()
        self.assertGreaterEqual(len(rows), 15)
        self.assertTrue(all(row.get('enabled') == 'false' for row in rows))
        self.assertTrue(any(row.get('quality_tier', '').startswith('A') for row in rows))

    def test_disabled_candidate_registry_passes_blocking_validation(self):
        rows = read_sources()
        self.assertEqual(source_validation(rows), [])

if __name__ == '__main__':
    unittest.main()
