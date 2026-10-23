import unittest
from datetime import date
from opportunity_radar.source_policy import Source, load_sources
from opportunity_radar.source_audit import audit_sources, url_targets


def source(**overrides):
    values = dict(source_id='test', name='Test', homepage='https://example.org',
                  feed_url='https://example.org/feed.xml', access_method='rss',
                  permission_status='approved', enabled=True, freshrss_feed_id='7',
                  source_type='user_forum', provenance_class='first_party',
                  canonical_domain='example.org', terms_url='https://example.org/terms',
                  last_verified_at='2026-10-20', reviewed_at='2026-10-20',
                  editorial_lanes='A', content_access_level='auto', source_cap=3)
    values.update(overrides)
    return Source(**values)


class SourceAuditTests(unittest.TestCase):
    def test_current_repository_registry_is_safe_by_default(self):
        sources = load_sources()
        self.assertTrue(sources)
        self.assertFalse(any(s.enabled for s in sources))
        self.assertTrue(any(i['code'] == 'no_enabled_sources' for i in audit_sources(sources, date(2026, 10, 20))))

    def test_enabled_source_requires_review_dates(self):
        issues = audit_sources([source(reviewed_at='', last_verified_at='')], date(2026, 10, 20))
        codes = {i['code'] for i in issues}
        self.assertIn('missing_reviewed_at', codes)
        self.assertIn('missing_last_verified_at', codes)

    def test_stale_review_blocks_enabled_source(self):
        issues = audit_sources([source(reviewed_at='2025-01-01', last_verified_at='2025-01-01')], date(2026, 10, 20))
        self.assertIn('stale_last_verified_at', {i['code'] for i in issues})

    def test_duplicate_feed_id_blocks_enabled_sources(self):
        issues = audit_sources([source(source_id='a'), source(source_id='b')], date(2026, 10, 20))
        self.assertIn('duplicate_feed_id', {i['code'] for i in issues})

    def test_bridge_requires_provider_terms(self):
        issues = audit_sources([source(feed_url='https://feeds.example.net/feed.xml')], date(2026, 10, 20))
        codes = {i['code'] for i in issues}
        self.assertIn('missing_feed_provider', codes)
        self.assertIn('missing_feed_provider_terms', codes)

    def test_non_https_terms_url_rejected(self):
        issues = audit_sources([source(terms_url='http://example.org/terms')], date(2026, 10, 20))
        self.assertIn('invalid_terms_url', {i['code'] for i in issues})

    def test_url_targets_skip_undeclared_provider_terms(self):
        targets = dict(url_targets(source()))
        self.assertEqual(set(targets), {'homepage', 'feed', 'terms'})
        bridged = dict(url_targets(source(feed_provider_terms_url='https://hnrss.org/')))
        self.assertEqual(bridged['feed_provider_terms'], 'https://hnrss.org/')


class EditorialGovernanceTests(unittest.TestCase):
    def test_unknown_lane_rejected(self):
        issues = audit_sources([source(editorial_lanes='D')], date(2026, 10, 20))
        self.assertIn('invalid_editorial_lane', {i['code'] for i in issues})

    def test_enabled_source_needs_an_editorial_lane(self):
        issues = audit_sources([source(editorial_lanes='')], date(2026, 10, 20))
        self.assertIn('missing_editorial_lanes', {i['code'] for i in issues})

    def test_disabled_source_is_not_blocked_for_a_missing_lane(self):
        issues = audit_sources([source(enabled=False, permission_status='review_required', editorial_lanes='')], date(2026, 10, 20))
        self.assertNotIn('missing_editorial_lanes', {i['code'] for i in issues})

    def test_invalid_content_access_level(self):
        issues = audit_sources([source(content_access_level='guess')], date(2026, 10, 20))
        self.assertIn('invalid_content_access_level', {i['code'] for i in issues})

    def test_invalid_source_cap(self):
        issues = audit_sources([source(source_cap=900)], date(2026, 10, 20))
        self.assertIn('invalid_source_cap', {i['code'] for i in issues})


    def test_repository_registry_declares_governance_for_every_row(self):
        for s in load_sources():
            self.assertTrue(s.editorial_lanes, s.source_id)
            self.assertIn(s.content_access_level, {'auto', 'full_text', 'excerpt', 'title_only'}, s.source_id)
