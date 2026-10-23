import csv
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

from opportunity_radar.intelligence_lines import (
    ENGINEERING, INTELLIGENCE_LINES, INTELLIGENCE_LINE_LABEL, MACRO, POLICY, TECH,
    labels_of, lines_of, summarize,
)
from opportunity_radar.source_audit import audit_sources
from opportunity_radar.source_policy import Source, load_sources

ROOT = Path(__file__).resolve().parents[1]


def source(**overrides):
    values = dict(source_id='test', name='Test', homepage='https://example.org',
                  feed_url='https://example.org/feed.xml', access_method='rss',
                  permission_status='approved', enabled=True, freshrss_feed_id='7',
                  source_type='government', provenance_class='first_party',
                  canonical_domain='example.org', terms_url='https://example.org/terms',
                  last_verified_at='2026-10-20', reviewed_at='2026-10-20',
                  editorial_lanes='A', content_access_level='auto', source_cap=3,
                  intelligence_lines=MACRO)
    values.update(overrides)
    return Source(**values)


class ParsingTests(unittest.TestCase):
    def test_parses_several_lines_in_canonical_order(self):
        self.assertEqual(lines_of({'intelligence_lines': 'technology_research, macro_economy'}), (MACRO, TECH))
        self.assertEqual(lines_of({'intelligence_lines': 'TECHNOLOGY_RESEARCH;MACRO_ECONOMY'}), (MACRO, TECH))

    def test_empty_and_missing_are_undeclared(self):
        self.assertEqual(lines_of({'intelligence_lines': ''}), ())
        self.assertEqual(lines_of(Source('x', 'X', 'https://x', '', 'rss', 'disabled', False)), ())

    def test_unknown_tokens_are_not_returned(self):
        self.assertEqual(lines_of({'intelligence_lines': 'macro_economy,typo_line'}), (MACRO,))

    def test_labels_follow_codes(self):
        self.assertEqual(labels_of({'intelligence_lines': POLICY}), (INTELLIGENCE_LINE_LABEL[POLICY],))

    def test_summarize_counts_items_and_flags_undeclared(self):
        items = [{'intelligence_lines': 'macro_economy,technology_research'},
                 {'intelligence_lines': 'macro_economy'},
                 {'intelligence_lines': ''}]
        rows = dict(summarize(items))
        self.assertEqual(rows[MACRO], 2)
        self.assertEqual(rows[TECH], 1)
        self.assertEqual(rows['(undeclared)'], 1)


class AuditTests(unittest.TestCase):
    def test_unknown_line_is_an_error(self):
        issues = audit_sources([source(intelligence_lines='macro_economy,not_a_line')], date(2026, 10, 20))
        self.assertIn('invalid_intelligence_line', {i['code'] for i in issues})

    def test_missing_line_is_a_warning_not_a_blocker(self):
        issues = audit_sources([source(intelligence_lines='')], date(2026, 10, 20))
        missing = [i for i in issues if i['code'] == 'missing_intelligence_lines']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['severity'], 'warning')

    def test_registry_declares_only_valid_lines(self):
        for s in load_sources():
            declared = {t.strip() for t in s.intelligence_lines.split(',') if t.strip()}
            self.assertTrue(declared, s.source_id)
            self.assertTrue(declared <= set(INTELLIGENCE_LINES), s.source_id)


class MigrationToolTests(unittest.TestCase):
    def _load_tool(self):
        spec = importlib.util.spec_from_file_location(
            'migrate_intelligence_lines', ROOT / 'tools' / 'migrate_intelligence_lines.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _write(self, path, rows, fields):
        with path.open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_adds_column_fills_known_and_leaves_unknown_blank(self):
        tool = self._load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sources.csv'
            self._write(path, [
                {'source_id': 'us-bea', 'name': 'BEA'},
                {'source_id': 'someone-new', 'name': 'New'},
            ], ['source_id', 'name'])
            result = tool.migrate(path)
            self.assertTrue(result['added_column'])
            self.assertEqual(result['filled'], ['us-bea'])
            self.assertEqual(result['skipped'], ['someone-new'])
            with path.open(encoding='utf-8-sig') as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]['intelligence_lines'], MACRO)
            self.assertEqual(rows[1]['intelligence_lines'], '')

    def test_second_run_is_idempotent_and_keeps_existing_values(self):
        tool = self._load_tool()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sources.csv'
            self._write(path, [{'source_id': 'us-bea', 'intelligence_lines': 'policy_regulation'}],
                        ['source_id', 'intelligence_lines'])
            result = tool.migrate(path)
            self.assertFalse(result['added_column'])
            self.assertEqual(result['already'], ['us-bea'])
            with path.open(encoding='utf-8-sig') as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]['intelligence_lines'], POLICY)


class AdminFieldTests(unittest.TestCase):
    def test_admin_exposes_the_field(self):
        from opportunity_radar.admin_server import SOURCE_FIELDS
        self.assertIn('intelligence_lines', SOURCE_FIELDS)
        self.assertIn('full_text_fetch', SOURCE_FIELDS)


class LegacyConfigTests(unittest.TestCase):
    def test_registry_without_the_column_loads_as_undeclared(self):
        """An old local registry must keep working, with a visible warning — not a crash."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sources.csv'
            path.write_text(
                'source_id,name,homepage,feed_url,access_method,permission_status,reviewed_at,'
                'review_notes,max_requests_per_day,enabled,freshrss_feed_id,source_type,'
                'provenance_class,canonical_domain,terms_url,last_verified_at,feed_provider,'
                'feed_provider_terms_url,topic,quality_tier,expected_signal,editorial_lanes,'
                'topic_tags,source_authority,content_access_level,source_cap\n'
                'legacy,Legacy,https://example.org/,https://example.org/feed.xml,rss,'
                'review_required,,,12,false,,government,first_party,example.org,'
                'https://example.org/terms,,,,topic,tier,signal,A,tags,official_primary,auto,2\n',
                encoding='utf-8')
            rows = load_sources(str(path))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].intelligence_lines, '')
            issues = audit_sources(rows, date(2026, 10, 23))
            missing = [i for i in issues if i['code'] == 'missing_intelligence_lines']
            self.assertEqual(len(missing), 1)
            self.assertEqual(missing[0]['severity'], 'warning')


class ReportTests(unittest.TestCase):
    def _item(self, lines):
        return {'title': 't', 'url': 'https://example.invalid/a', 'source_name': 's',
                'analysis': {}, 'score': 60, 'status': 'watch', 'filter_reason': '',
                'evidence_level': 'summary', 'classification': {'article_type': 'user_pain'},
                'risk_flag': '', 'intelligence_lines': lines}

    def test_digest_reports_mainline_coverage(self):
        from opportunity_radar.digest import render_digest
        stats = {'fetched': 2, 'new': 2, 'queued': 2, 'analyzed': 2, 'failed': 0, 'skipped': 0,
                 'counts': {'priority': 0, 'watch': 2, 'filtered': 0}}
        _, body = render_digest([self._item('macro_economy,technology_research'),
                                 self._item('')], stats, '2026-10-20')
        self.assertIn('情报主线', body)
        self.assertIn('宏观经济与统计 1', body)
        self.assertIn('(undeclared) 1', body)


if __name__ == '__main__':
    unittest.main()
