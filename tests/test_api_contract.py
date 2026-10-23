import http.client, json, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from opportunity_radar.admin_server import Handler, validate_source_rows, validate_recipient_list


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        data = json.dumps(body).encode() if body is not None else None
        h = dict(headers or {})
        if data is not None: h['Content-Type'] = 'application/json'
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse(); raw = r.read().decode(); conn.close()
        return r.status, json.loads(raw)

    def test_contract_envelope(self):
        status, data = self.call('GET', '/api/contract')
        self.assertEqual(status, 200); self.assertTrue(data['ok']); self.assertTrue(data['request_id'])
        self.assertIn('VALIDATION_ERROR', data['error_codes'])

    def test_unknown_route_uses_error_envelope(self):
        status, data = self.call('GET', '/api/nope')
        self.assertEqual(status, 404); self.assertFalse(data['ok'])
        self.assertEqual(data['error']['code'], 'NOT_FOUND'); self.assertTrue(data['request_id'])
        self.assertIsInstance(data['error']['details'], list)

    def test_non_local_host_is_blocked(self):
        status, data = self.call('GET', '/api/contract', headers={'Host': 'evil.example'})
        self.assertEqual(status, 403); self.assertEqual(data['error']['code'], 'FORBIDDEN')

    def test_frontend_assets_are_served(self):
        status, data = self.call('GET', '/api/contract')
        self.assertEqual(status, 200)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('GET', '/assets/app.js'); r = conn.getresponse(); js = r.read().decode(); conn.close()
        self.assertEqual(r.status, 200); self.assertIn('function api', js)
        self.assertIn('copyLog', js)
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request('GET', '/assets/app.css'); r = conn.getresponse(); css = r.read().decode(); conn.close()
        self.assertEqual(r.status, 200); self.assertIn(':focus-visible', css)

    def test_frontend_is_split_and_accessible(self):
        html = Path('admin/index.html').read_text(encoding='utf-8')
        self.assertNotIn('<style>', html); self.assertNotIn('<script>const', html)
        self.assertIn('href="/assets/app.css"', html); self.assertIn('src="/assets/app.js"', html)
        self.assertIn('aria-live="polite"', html); self.assertIn('aria-modal="true"', html)
        self.assertEqual(html.count('id="run-btn"'), 0)
        self.assertGreaterEqual(html.count('run-trigger'), 3)

    def test_source_rows_return_field_details(self):
        details = validate_source_rows([{'source_id': 'demo', 'name': '', 'feed_url': 'http://insecure', 'enabled': 'true'}])
        fields = {d['field'] for d in details}
        self.assertIn('sources[0].name', fields)
        self.assertIn('sources[0].feed_url', fields)
        self.assertIn('sources[0].permission_status', fields)
        self.assertIn('sources[0].freshrss_feed_id', fields)

    def test_duplicate_source_id_rejected(self):
        details = validate_source_rows([{'source_id': 'a', 'name': 'A', 'feed_url': 'https://a.example/f'}, {'source_id': 'a', 'name': 'B', 'feed_url': 'https://b.example/f'}])
        self.assertTrue(any('duplicate' in d['message'] for d in details))

    def test_recipient_list_points_at_the_bad_index(self):
        details = validate_recipient_list(['ok@example.com', 'bad'])
        self.assertEqual(details[0]['field'], 'recipients[1]')


class SourceRowValidationTests(unittest.TestCase):
    """A candidate may have no verified endpoint; an enabled source may not."""

    def test_candidate_without_a_verified_feed_is_allowed(self):
        details = validate_source_rows([{'source_id': 'c', 'name': 'C', 'feed_url': '', 'enabled': 'false'}])
        self.assertEqual(details, [])

    def test_enabled_source_without_a_feed_is_rejected(self):
        details = validate_source_rows([{'source_id': 'c', 'name': 'C', 'feed_url': '', 'enabled': 'true',
                                         'freshrss_feed_id': '1', 'permission_status': 'approved'}])
        self.assertIn('feed_url', ' '.join(d['field'] for d in details))

    def test_a_publisher_page_is_still_checked_for_https(self):
        details = validate_source_rows([{'source_id': 'c', 'name': 'C', 'feed_url': 'http://x.example/page', 'enabled': 'false'}])
        self.assertIn('feed_url', ' '.join(d['field'] for d in details))
