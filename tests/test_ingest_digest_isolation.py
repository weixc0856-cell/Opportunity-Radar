import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROD = Path('data/opportunity_radar.sqlite3')


def fingerprint(path):
    st = path.stat()
    return (st.st_size, st.st_mtime_ns)


@unittest.skipUnless(PROD.exists(), 'production database not present')
class RenderOnlyRegressionTests(unittest.TestCase):
    """--render-only in a copy of the production database must be unaffected by the ingest channel."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='or-digest-'))
        self.db_copy = self.tmp / 'copy.sqlite3'
        shutil.copy2(PROD, self.db_copy)
        self.report_dir = self.tmp / 'reports'
        self.before = fingerprint(PROD)

    def tearDown(self):
        self.assertEqual(fingerprint(PROD), self.before,
                         'the production database must not be touched by the regression run')

    def _render(self, db_path):
        env = {'OR_DB_PATH': str(db_path), 'OR_REPORT_DIR': str(self.report_dir),
               'OR_LOG_PATH': str(self.tmp / 'render.log'),
               'OR_DISCOVERY_ENABLED': '0', 'OR_YOUTUBE_ENABLED': '0'}
        with mock.patch.dict(os.environ, env, clear=False):
            from opportunity_radar.cli import main
            with mock.patch('sys.stdout') as out:
                code = main(['--render-only'])
            return code, out

    def test_render_only_is_deterministic_and_untouched_by_ingest_data(self):
        code1, out1 = self._render(self.db_copy)
        text1 = (self.report_dir / 'latest-digest.txt').read_text(encoding='utf-8')
        hash1 = hashlib.sha256(text1.encode()).hexdigest()

        code2, _ = self._render(self.db_copy)
        text2 = (self.report_dir / 'latest-digest.txt').read_text(encoding='utf-8')
        hash2 = hashlib.sha256(text2.encode()).hexdigest()

        self.assertEqual(code1, 0)
        self.assertEqual(code2, 0)
        self.assertEqual(hash1, hash2, 'render-only must be deterministic for the same database')

        # An ingest database sitting next to the copy must not change what the digest renders.
        ingest_db = self.tmp / 'ingest.sqlite3'
        from opportunity_radar.ingest.store import IngestStore
        store = IngestStore(ingest_db)
        store.upsert_eia_observation({
            'series_id': 'eia:test', 'period': '2026-08', 'value_raw': '1', 'value_num': 1.0,
            'unit': 'thousand megawatthours', 'period_kind': 'monthly', 'is_partial_year': 0,
            'quality_flags': '', 'snapshot_hash': 'h', 'first_seen_at': 't', 'last_seen_at': 't'})
        code3, _ = self._render(self.db_copy)
        text3 = (self.report_dir / 'latest-digest.txt').read_text(encoding='utf-8')
        self.assertEqual(code3, 0)
        self.assertEqual(hashlib.sha256(text3.encode()).hexdigest(), hash1,
                         'ingest data must not reach the digest')

    def test_the_digest_contains_no_ingest_tables(self):
        import sqlite3
        with sqlite3.connect(self.db_copy) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({t for t in tables if t.startswith(('ingest_', 'sec_', 'eia_'))})


if __name__ == '__main__':
    unittest.main()
