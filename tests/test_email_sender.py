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

from unittest.mock import patch
import opportunity_radar.email_sender as es

class DetailedSendTests(unittest.TestCase):
    def test_one_failure_does_not_hide_other_recipients(self):
        def fake(host,port,username,password,sender,address,subject,body,html,use_ssl,use_starttls):
            if address.startswith('fail'):
                raise RuntimeError('smtp boom')
        with patch.object(es,'_send_one',side_effect=fake):
            results=es.send_email_detailed('h',465,'u','p','from@example.com','ok@example.com,fail@example.com','s','b',security='ssl')
        self.assertEqual([r['ok'] for r in results],[True,False])
        self.assertIn('smtp boom',results[1]['error'])
    def test_send_email_still_raises_on_partial_failure(self):
        def fake(*args,**kwargs): raise RuntimeError('boom')
        with patch.object(es,'_send_one',side_effect=fake):
            with self.assertRaises(RuntimeError): es.send_email('h',465,'u','p','from@example.com','a@example.com','s','b',security='ssl')
