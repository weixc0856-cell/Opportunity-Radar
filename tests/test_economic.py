"""R5 economic engine: sync, append-only revisions, derived metrics."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import economic


def _make_pilot(path):
    conn = sqlite3.connect(path)
    conn.executescript('''
    CREATE TABLE macro_series(series_id TEXT PRIMARY KEY, source_id TEXT, label TEXT, topic TEXT,
      unit TEXT, frequency TEXT, seasonal_adjustment TEXT, source_url TEXT,
      first_seen_at TEXT, last_seen_at TEXT);
    CREATE TABLE macro_observations(observation_id INTEGER PRIMARY KEY, series_id TEXT,
      year TEXT, period_raw TEXT, period TEXT, period_name TEXT, value_raw TEXT, value_num REAL,
      unit TEXT, preliminary INTEGER, latest INTEGER, footnotes_json TEXT, quality_flags TEXT,
      snapshot_hash TEXT, first_seen_at TEXT, last_seen_at TEXT);
    ''')
    conn.execute("INSERT INTO macro_series VALUES('S1','bls','Employment','jobs','thousands',"
                 "'monthly','seasonally adjusted','u','t','t')")
    conn.executemany(
        "INSERT INTO macro_observations(series_id,period,value_raw,value_num,unit,snapshot_hash)"
        " VALUES('S1',?,?,?,'thousands',?)",
        [('2025-12', '100', 100.0, 'h1'), ('2026-01', '110', 110.0, 'h2')])
    conn.commit()
    conn.close()


def _make_ingest(path):
    conn = sqlite3.connect(path)
    conn.executescript('''
    CREATE TABLE eia_series(series_id TEXT PRIMARY KEY, dataset TEXT, route TEXT, metric TEXT,
      unit TEXT, frequency TEXT, description TEXT, first_seen_at TEXT);
    CREATE TABLE eia_observations(obs_id INTEGER PRIMARY KEY, series_id TEXT, period TEXT,
      value_raw TEXT, value_num REAL, unit TEXT, period_kind TEXT, is_partial_year INTEGER,
      quality_flags TEXT, snapshot_hash TEXT, first_seen_at TEXT, last_seen_at TEXT);
    ''')
    conn.execute("INSERT INTO eia_series VALUES('E1','d','r','generation','MWh','monthly','','t')")
    conn.execute("INSERT INTO eia_observations(series_id,period,value_raw,value_num,unit,snapshot_hash)"
                 " VALUES('E1','2026-01','50',50.0,'MWh','e1')")
    conn.commit()
    conn.close()


class EconomicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pilot = str(self.dir / 'pilot.sqlite3')
        self.ingest = str(self.dir / 'ingest.sqlite3')
        self.db = str(self.dir / 'economic.sqlite3')
        _make_pilot(self.pilot)
        _make_ingest(self.ingest)

    def tearDown(self):
        self.tmp.cleanup()

    def test_refresh_syncs_and_derives_with_formula(self):
        result = economic.refresh(self.db, self.pilot, self.ingest)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['datasets'], 2)
        self.assertEqual(result['observations'], 3)
        summary = economic.summary(self.db)
        self.assertEqual(summary['observations'], 3)
        self.assertGreaterEqual(summary['derived'], 1)
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT formula, inputs_json, value FROM derived_metrics "
            "WHERE dataset_id='bls:S1' AND period='2026-01' AND formula LIKE 'mom_pct%'").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[2], 10.0)
        inputs = json.loads(row[1])
        self.assertEqual(inputs['previous_period'], '2025-12')

    def test_revision_is_appended_not_overwritten(self):
        economic.refresh(self.db, self.pilot, self.ingest)
        conn = sqlite3.connect(self.pilot)
        conn.execute("UPDATE macro_observations SET value_raw='111', value_num=111.0, "
                     "snapshot_hash='h3' WHERE period='2026-01'")
        conn.commit()
        conn.close()
        result = economic.refresh(self.db, self.pilot, self.ingest)
        self.assertEqual(result['status'], 'success')
        summary = economic.summary(self.db)
        self.assertEqual(summary['versions'], 4)  # three initial + one revision
        conn = sqlite3.connect(self.db)
        current = conn.execute(
            "SELECT value_num FROM observations WHERE dataset_id='bls:S1' AND period='2026-01'"
        ).fetchone()[0]
        versions = conn.execute(
            "SELECT COUNT(*) FROM observation_versions WHERE dataset_id='bls:S1' "
            "AND period='2026-01'").fetchone()[0]
        conn.close()
        self.assertEqual(current, 111.0)
        self.assertEqual(versions, 2)


if __name__ == '__main__':
    unittest.main()
