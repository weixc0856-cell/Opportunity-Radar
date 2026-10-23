import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opportunity_radar.page_monitor import (
    Watch, audit_watchlist, check_watch, extract_links, fingerprint, init_db,
    parse_robots, robots_allows,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def watch(**overrides):
    values = dict(watch_id='w1', institution='Org', name='Page',
                  url='https://example.org/list/', include_pattern='', exclude_pattern='',
                  min_links='2', min_interval_hours='6', terms_url='', status='approved', notes='')
    values.update(overrides)
    return Watch(**values)


def page(*links):
    body = ''.join(f'<a href="{href}">{title}</a>' for href, title in links)
    return f'<html><body>{body}</body></html>'


class RobotTests(unittest.TestCase):
    def test_wildcard_disallow_applies(self):
        rules = parse_robots('User-agent: *\nDisallow: /private\n')
        self.assertFalse(robots_allows(rules, '/private/x'))
        self.assertTrue(robots_allows(rules, '/public'))

    def test_more_specific_agent_wins_over_wildcard(self):
        text = ('User-agent: *\nDisallow: /\n\n'
                'User-agent: OpportunityRadar-PageWatch\nDisallow: /blocked\n')
        rules = parse_robots(text)
        self.assertTrue(robots_allows(rules, '/list/'))
        self.assertFalse(robots_allows(rules, '/blocked/a'))

    def test_allow_overrides_longer_disallow(self):
        rules = parse_robots('User-agent: *\nDisallow: /a\nAllow: /a/b\n')
        self.assertTrue(robots_allows(rules, '/a/b/c'))
        self.assertFalse(robots_allows(rules, '/a/c'))

    def test_empty_disallow_allows_everything(self):
        self.assertTrue(robots_allows(parse_robots('User-agent: *\nDisallow:\n'), '/x'))


class ExtractTests(unittest.TestCase):
    def test_keeps_same_site_links_and_resolves_relative(self):
        html = page(('/a.html', 'First long title'), ('https://other.example/b', 'Other long title'))
        items = extract_links(html, 'https://example.org/list/')
        self.assertEqual([i['url'] for i in items], ['https://example.org/a.html'])

    def test_include_pattern_matches_url_and_excludes_navigation(self):
        html = page(('/list/', 'Navigation'), ('/2026/t1.html', 'Release one'), ('/2026/t2.html', 'Release two'))
        items = extract_links(html, 'https://example.org/list/', include=r'/2026/t\d\.html')
        self.assertEqual(len(items), 2)

    def test_duplicate_url_keeps_longest_title(self):
        html = page(('/a.html', 'Short'), ('/a.html', 'A much longer title'))
        items = extract_links(html, 'https://example.org/')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], 'A much longer title')

    def test_fingerprint_is_order_independent(self):
        a = [{'url': 'https://x/1', 'title': 'one'}, {'url': 'https://x/2', 'title': 'two'}]
        self.assertEqual(fingerprint(a), fingerprint(list(reversed(a))))
        self.assertNotEqual(fingerprint(a), fingerprint(a[:1]))


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = init_db(str(Path(self.tmp.name) / 'state.sqlite3'))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def fetcher(self, pages):
        def _f(url, timeout=25):
            if url in pages:
                return pages[url]
            return 404, ''
        return _f

    def allow(self, *args, **kwargs):
        return True, 'allowed'

    def test_first_run_reports_all_items_as_new(self):
        f = self.fetcher({'https://example.org/list/': (200, page(('/1', 'Title one'), ('/2', 'Title two')))})
        result = check_watch(watch(), self.conn, NOW, fetcher=f, robots=self.allow)
        self.assertEqual(result['status'], 'new_items')
        self.assertEqual(len(result['new_items']), 2)

    def test_second_run_is_unchanged(self):
        f = self.fetcher({'https://example.org/list/': (200, page(('/1', 'Title one'), ('/2', 'Title two')))})
        check_watch(watch(), self.conn, NOW, fetcher=f, robots=self.allow)
        later = NOW + timedelta(hours=7)
        result = check_watch(watch(), self.conn, later, fetcher=f, robots=self.allow)
        self.assertEqual(result['status'], 'unchanged')

    def test_interval_blocks_early_recheck(self):
        f = self.fetcher({'https://example.org/list/': (200, page(('/1', 'Title one'), ('/2', 'Title two')))})
        check_watch(watch(), self.conn, NOW, fetcher=f, robots=self.allow)
        result = check_watch(watch(), self.conn, NOW + timedelta(hours=1), fetcher=f, robots=self.allow)
        self.assertEqual(result['status'], 'skipped_interval')

    def test_structure_change_keeps_previous_fingerprint(self):
        good = (200, page(('/1', 'Title one'), ('/2', 'Title two')))
        check_watch(watch(), self.conn, NOW, fetcher=self.fetcher({'https://example.org/list/': good}),
                    robots=self.allow)
        before = self.conn.execute('select fingerprint from page_watch_state').fetchone()[0]
        empty = (200, '<html><body>redesigned</body></html>')
        result = check_watch(watch(), self.conn, NOW + timedelta(hours=7),
                             fetcher=self.fetcher({'https://example.org/list/': empty}), robots=self.allow)
        after = self.conn.execute('select fingerprint from page_watch_state').fetchone()[0]
        self.assertEqual(result['status'], 'structure_changed')
        self.assertEqual(before, after)

    def test_blocked_status_does_not_retry_or_store_items(self):
        f = self.fetcher({'https://example.org/list/': (403, '')})
        result = check_watch(watch(), self.conn, NOW, fetcher=f, robots=self.allow)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.conn.execute('select count(*) from page_watch_items').fetchone()[0], 0)

    def test_robots_disallow_prevents_fetch(self):
        calls = []
        def fetcher(url, timeout=25):
            calls.append(url)
            return 200, page(('/1', 'Title one'))
        def deny(*args, **kwargs):
            return False, 'disallowed'
        result = check_watch(watch(), self.conn, NOW, fetcher=fetcher, robots=deny)
        self.assertEqual(result['status'], 'robots_disallowed')
        self.assertEqual(calls, [])

    def test_unapproved_watch_is_not_fetched(self):
        result = check_watch(watch(status='candidate'), self.conn, NOW,
                             fetcher=lambda *a, **k: (500, ''), robots=self.allow)
        self.assertEqual(result['status'], 'not_approved')


class WatchlistAuditTests(unittest.TestCase):
    def test_duplicate_id_and_bad_values(self):
        issues = audit_watchlist([watch(), watch(url='http://insecure.example/')])
        codes = {i['code'] for i in issues}
        self.assertIn('duplicate_or_missing_id', codes)
        self.assertIn('invalid_url', codes)

    def test_interval_must_be_sane(self):
        issues = audit_watchlist([watch(min_interval_hours='0')])
        self.assertIn('invalid_interval', {i['code'] for i in issues})

    def test_repository_watchlist_is_valid(self):
        from opportunity_radar.page_monitor import load_watchlist
        rows = load_watchlist()
        self.assertFalse([i for i in audit_watchlist(rows) if i['severity'] == 'error'])


if __name__ == '__main__':
    unittest.main()
