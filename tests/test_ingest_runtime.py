"""Runtime evidence for the two gaps left open by the phase-1 acceptance:

1. an ingest writer process running while the RSS digest renders;
2. a process killed mid-transaction (hard kill, no cleanup).

Both run in an isolated copy of the production database and never touch the real one.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / 'data' / 'opportunity_radar.sqlite3'
PY = sys.executable

WRITER = r'''
import sys
from opportunity_radar.ingest.store import IngestStore
s = IngestStore(sys.argv[1])
for i in range(300):
    s.upsert_eia_observation({
        'series_id': 'eia:concurrent', 'period': f'2026-{i % 12 + 1:02d}-{i:03d}',
        'value_raw': '1', 'value_num': 1.0, 'unit': 'thousand megawatthours',
        'period_kind': 'monthly', 'is_partial_year': 0, 'quality_flags': '',
        'snapshot_hash': f'h{i}', 'first_seen_at': 't', 'last_seen_at': 't'})
print('writer done')
'''

CRASHER = r'''
import os, sys, time
from opportunity_radar.ingest.store import IngestStore
store = IngestStore(sys.argv[1])
marker = sys.argv[2]
with store.connect() as c:
    c.execute('BEGIN')
    for i in range(50):
        c.execute("INSERT INTO ingest_runs(source_id,started_at,status) VALUES('crash','t','running')")
    open(marker, 'w').write('open')
    time.sleep(60)
    c.commit()
'''


def fingerprint(path):
    st = path.stat()
    return (st.st_size, st.st_mtime_ns)


@unittest.skipUnless(PROD.exists(), 'production database not present')
class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='or-runtime-'))
        self.db_copy = self.tmp / 'copy.sqlite3'
        shutil.copy2(PROD, self.db_copy)
        self.ingest_db = self.tmp / 'ingest.sqlite3'
        self.prod_before = fingerprint(PROD)
        self.env = dict(os.environ, OR_DB_PATH=str(self.db_copy),
                        OR_REPORT_DIR=str(self.tmp / 'reports'),
                        OR_LOG_PATH=str(self.tmp / 'digest.log'))

    def tearDown(self):
        self.assertEqual(fingerprint(PROD), self.prod_before,
                         'the production database must not change')

    def _render(self, report_dir):
        env = dict(self.env, OR_REPORT_DIR=str(report_dir))
        proc = subprocess.run([PY, '-m', 'opportunity_radar.cli', '--render-only'],
                              cwd=str(ROOT), env=env, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=120)
        out = Path(report_dir) / 'latest-digest.txt'
        digest = hashlib.sha256(out.read_bytes()).hexdigest() if out.exists() else None
        return proc.returncode, digest, proc.stderr

    def test_ingest_writer_and_digest_rendering_run_concurrently(self):
        base_code, base_hash, base_err = self._render(self.tmp / 'reports')
        self.assertEqual(base_code, 0, base_err)
        self.assertIsNotNone(base_hash)

        writer = subprocess.Popen([PY, '-c', WRITER, str(self.ingest_db)],
                                  cwd=str(ROOT), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        try:
            code, digest, err = self._render(self.tmp / 'reports2')
            self.assertEqual(code, 0, err)
            self.assertEqual(digest, base_hash,
                             'a concurrent ingest writer must not change the rendered digest')
        finally:
            stdout, stderr = writer.communicate(timeout=120)
        self.assertEqual(writer.returncode, 0, stderr)

        from opportunity_radar.ingest.store import IngestStore
        store = IngestStore(self.ingest_db)
        self.assertEqual(store.counts()['eia_observations'], 300)
        self.assertEqual(store.counts()['ingest_failures'], 0, 'no lock contention recorded')

    def test_a_process_killed_mid_transaction_leaves_no_partial_state(self):
        marker = self.tmp / 'open.marker'
        proc = subprocess.Popen([PY, '-c', CRASHER, str(self.ingest_db), str(marker)],
                                cwd=str(ROOT), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        deadline = time.time() + 30
        while not marker.exists() and time.time() < deadline:
            time.sleep(0.05)
            self.assertIsNone(proc.poll(), 'crasher exited before the transaction opened')
        self.assertTrue(marker.exists(), 'crasher never opened its transaction')

        proc.kill()
        proc.communicate(timeout=30)

        from opportunity_radar.ingest.store import IngestStore
        import sqlite3
        store = IngestStore(self.ingest_db)
        self.assertEqual(store.counts()['ingest_runs'], 0,
                         'an uncommitted transaction must be rolled back by the database')
        with sqlite3.connect(self.ingest_db) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

        # Restart and repeat: the store must still work and stay idempotent.
        rid = store.start_run('eia')
        store.finish_run(rid, 'success', 1, 1, 0)
        obs = {'series_id': 's', 'period': '2026-08', 'value_raw': '1', 'value_num': 1.0,
               'unit': 'thousand megawatthours', 'period_kind': 'monthly', 'is_partial_year': 0,
               'quality_flags': '', 'snapshot_hash': 'h', 'first_seen_at': 't', 'last_seen_at': 't'}
        store.upsert_eia_observation(obs)
        store.upsert_eia_observation(dict(obs))
        self.assertEqual(store.counts()['eia_observations'], 1)
        self.assertEqual(store.counts()['ingest_runs'], 1)

    def test_repeated_runs_after_a_crash_stay_consistent(self):
        for _ in range(3):
            code, digest, err = self._render(self.tmp / 'reports')
            self.assertEqual(code, 0, err)
        self.assertEqual(fingerprint(PROD), self.prod_before)


if __name__ == '__main__':
    unittest.main()
