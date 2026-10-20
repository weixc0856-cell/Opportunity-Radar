import unittest
from opportunity_radar.email_sender import parse_recipients

class RecipientTests(unittest.TestCase):
    def test_comma_and_semicolon_separated_recipients(self):
        self.assertEqual(parse_recipients('a@example.com, b@example.com; c@example.com'),
                         ['a@example.com', 'b@example.com', 'c@example.com'])

    def test_duplicate_recipients_removed_case_insensitively(self):
        self.assertEqual(parse_recipients('A@example.com, a@example.com'), ['A@example.com'])

    def test_empty_recipients_ignored(self):
        self.assertEqual(parse_recipients(' , ; '), [])

if __name__ == '__main__':
    unittest.main()
