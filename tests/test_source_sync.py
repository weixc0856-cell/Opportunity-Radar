"""The launcher's source sync must be visible in the daily run, and never silently pass.

SEC/EIA/Federal Register/BLS run into their own databases before the CLI. Only statuses
travel into the digest: a source that is not configured or failed is reported there, and a
missing file is reported as no record rather than as success.
"""
import json
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import digest
from opportunity_radar.cli import _source_sync_note


class SourceSyncNoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / 'sources').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, payload):
        (self.dir / 'sources' / 'latest.json').write_text(json.dumps(payload), encoding='utf-8')

    def test_missing_file_is_no_record(self):
        self.assertIsNone(_source_sync_note(self.dir))

    def test_statuses_are_read_without_payloads(self):
        self.write({'status': 'failed', 'started_at': '2026-11-03T08:00:00+08:00',
                    'sources': {'eia': {'status': 'not_configured', 'exit_code': 2,
                                        'log': 'reports/sources/eia.log'},
                                'bls': {'status': 'ok', 'exit_code': 0}}})
        note = _source_sync_note(self.dir)
        self.assertEqual(note['status'], 'failed')
        self.assertEqual(note['sources']['eia']['status'], 'not_configured')
        self.assertNotIn('log', note['sources']['eia'])

    def test_broken_json_is_no_record(self):
        (self.dir / 'sources' / 'latest.json').write_text('{not json', encoding='utf-8')
        self.assertIsNone(_source_sync_note(self.dir))

    def test_digest_prints_failures_and_frozen_sources(self):
        stats = {'counts': {}, 'source_sync': {
            'status': 'failed', 'started_at': '2026-11-03T08:00:00+08:00',
            'sources': {'sec': {'status': 'not_configured', 'reason': ''},
                        'gdelt': {'status': 'frozen', 'reason': 'HTTP 429'}}}}
        _subject, body = digest.render_digest([], stats)
        self.assertIn('外部数据源同步（2026-11-03）', body)
        self.assertIn('sec not_configured', body)
        self.assertIn('gdelt frozen（HTTP 429）', body)
        self.assertIn('不进入本报告的证据与主张', body)

    def test_digest_omits_the_line_when_nothing_ran(self):
        _subject, body = digest.render_digest([], {'counts': {}})
        self.assertNotIn('外部数据源同步', body)


if __name__ == '__main__':
    unittest.main()
