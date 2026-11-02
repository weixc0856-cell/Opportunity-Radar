"""JsonRunner metrics and fallback behaviour (the model client is faked)."""
import unittest

from opportunity_radar.semantic_common import JsonRunner


class DetailedClient:
    def __init__(self):
        self.calls = 0

    def complete_detailed(self, messages, max_tokens=None, temperature=None,
                          response_format=None):
        self.calls += 1
        return '{"interpretations": []}', {
            'seconds': 1.25,
            'usage': {'prompt_tokens': 120, 'completion_tokens': 30},
            'timings': {'predicted_per_second': 8.0},
        }


class PlainClient:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, max_tokens=None, temperature=None, response_format=None):
        self.calls += 1
        return '{"interpretations": []}'


class JsonRunnerTests(unittest.TestCase):
    def test_detailed_client_metrics_are_returned(self):
        client = DetailedClient()
        runner = JsonRunner(client, 'system', {'type': 'object'}, max_tokens=100)
        result = runner.run({'candidates': []})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['usage']['prompt_tokens'], 120)
        self.assertEqual(result['usage']['completion_tokens'], 30)
        self.assertEqual(result['seconds'], 1.25)
        self.assertEqual(result['input_chars'], len('{"candidates": []}'))
        self.assertEqual(result['output_chars'], len('{"interpretations": []}'))
        self.assertFalse(result['parse_retry'])

    def test_plain_client_still_works(self):
        client = PlainClient()
        runner = JsonRunner(client, 'system', {'type': 'object'}, max_tokens=100)
        result = runner.run({'candidates': []})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['usage'], {})
        self.assertEqual(client.calls, 1)

    def test_invalid_json_retries_once_and_reports_it(self):
        class BadClient:
            def __init__(self):
                self.calls = 0

            def complete(self, messages, max_tokens=None, temperature=None,
                         response_format=None):
                self.calls += 1
                return 'not json'

        client = BadClient()
        runner = JsonRunner(client, 'system', {'type': 'object'}, max_tokens=100, retries=1)
        result = runner.run({'candidates': []})
        self.assertEqual(result['status'], 'invalid_output')
        self.assertEqual(client.calls, 2)
        self.assertTrue(result['parse_retry'])


if __name__ == '__main__':
    unittest.main()
