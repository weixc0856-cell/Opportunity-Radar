"""Independent SQLite store for the ingest channel.

One database file, its own tables, its own run and failure records.
It never opens the production database and never writes the RSS pipeline's tables.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import assert_isolated_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  records INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  exit_code INTEGER
);
CREATE TABLE IF NOT EXISTS ingest_failures(
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  source_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  error_class TEXT NOT NULL,
  detail TEXT NOT NULL,
  external_ref TEXT,
  occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_snapshots(
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  request_key TEXT NOT NULL,
  status INTEGER,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  path TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  UNIQUE(source_id, request_key, sha256)
);
CREATE TABLE IF NOT EXISTS sec_facts(
  fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
  cik TEXT NOT NULL,
  entity_name TEXT,
  taxonomy TEXT NOT NULL,
  tag TEXT NOT NULL,
  unit TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT,
  value_num REAL,
  value_raw TEXT,
  fy INTEGER,
  fp TEXT,
  form TEXT,
  filed TEXT,
  accn TEXT NOT NULL,
  frame TEXT,
  metric_id TEXT NOT NULL,
  filing_relation TEXT NOT NULL,
  selection_status TEXT NOT NULL,
  quality_flags TEXT NOT NULL DEFAULT '',
  snapshot_hash TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(cik, taxonomy, tag, unit, period_start, period_end, accn)
);
CREATE INDEX IF NOT EXISTS idx_sec_facts_metric ON sec_facts(metric_id, cik);
CREATE TABLE IF NOT EXISTS eia_series(
  series_id TEXT PRIMARY KEY,
  dataset TEXT NOT NULL,
  route TEXT NOT NULL,
  metric TEXT NOT NULL,
  unit TEXT NOT NULL,
  frequency TEXT NOT NULL,
  description TEXT,
  first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eia_observations(
  obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_id TEXT NOT NULL,
  period TEXT NOT NULL,
  value_raw TEXT,
  value_num REAL,
  unit TEXT NOT NULL,
  period_kind TEXT NOT NULL,
  is_partial_year INTEGER NOT NULL DEFAULT 0,
  quality_flags TEXT NOT NULL DEFAULT '',
  snapshot_hash TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(series_id, period)
);
CREATE TABLE IF NOT EXISTS eia_observation_versions(
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_id TEXT NOT NULL,
  period TEXT NOT NULL,
  value_raw TEXT,
  value_num REAL,
  observed_at TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  change_kind TEXT NOT NULL,
  UNIQUE(series_id, period, snapshot_hash)
);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


class IngestStore:
    def __init__(self, path, production=None):
        self.path = assert_isolated_db(path, production=production)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir = self.path.parent / 'snapshots'
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=5.0)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def init(self):
        with self.connect() as c:
            c.executescript(SCHEMA)

    # ------------------------------------------------------------ runs & failures
    def start_run(self, source_id):
        with self.connect() as c:
            return c.execute('INSERT INTO ingest_runs(source_id,started_at,status) VALUES(?,?,?)',
                             (source_id, now(), 'running')).lastrowid

    def finish_run(self, run_id, status, requests=0, records=0, errors=0, message='', exit_code=None):
        with self.connect() as c:
            c.execute('UPDATE ingest_runs SET finished_at=?,status=?,requests=?,records=?,errors=?,'
                      'message=?,exit_code=? WHERE run_id=?',
                      (now(), status, requests, records, errors, message[:1000], exit_code, run_id))

    def record_failure(self, run_id, source_id, stage, error_class, detail, external_ref=''):
        with self.connect() as c:
            c.execute('INSERT INTO ingest_failures(run_id,source_id,stage,error_class,detail,'
                      'external_ref,occurred_at) VALUES(?,?,?,?,?,?,?)',
                      (run_id, source_id, stage, error_class, str(detail)[:1000], external_ref, now()))

    def failures(self, run_id=None):
        with self.connect() as c:
            if run_id is None:
                rows = c.execute('SELECT * FROM ingest_failures ORDER BY failure_id DESC').fetchall()
            else:
                rows = c.execute('SELECT * FROM ingest_failures WHERE run_id=? ORDER BY failure_id',
                                 (run_id,)).fetchall()
            return [dict(r) for r in rows]

    def latest_run(self, source_id=None):
        with self.connect() as c:
            if source_id:
                r = c.execute('SELECT * FROM ingest_runs WHERE source_id=? ORDER BY run_id DESC LIMIT 1',
                              (source_id,)).fetchone()
            else:
                r = c.execute('SELECT * FROM ingest_runs ORDER BY run_id DESC LIMIT 1').fetchone()
            return dict(r) if r else None

    # ------------------------------------------------------------ snapshots
    def save_snapshot(self, source_id, url, request_key, status, body, retrieved_at=None):
        """Persist the raw bytes once per (source, request, hash). Never overwrites."""
        digest = hashlib.sha256(body).hexdigest()
        rel = Path(source_id) / f'{digest}.json'
        target = self.snapshot_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        created = False
        if not target.exists():
            target.write_bytes(body)
            created = True
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO raw_snapshots(source_id,url,request_key,status,sha256,'
                      'bytes,path,retrieved_at) VALUES(?,?,?,?,?,?,?,?)',
                      (source_id, url, request_key, status, digest, len(body),
                       str(Path('snapshots') / rel).replace('\\', '/'), retrieved_at or now()))
        return digest, created

    # ------------------------------------------------------------ SEC
    def upsert_sec_fact(self, fact):
        """Idempotent on the natural key; only last_seen_at and flags move on re-observation."""
        keys = ('cik', 'taxonomy', 'tag', 'unit', 'period_start', 'period_end', 'accn')
        with self.connect() as c:
            row = c.execute(
                'SELECT fact_id FROM sec_facts WHERE cik=? AND taxonomy=? AND tag=? AND unit=? '
                'AND period_start IS ? AND period_end IS ? AND accn=?',
                tuple(fact[k] for k in keys)).fetchone()
            if row:
                c.execute('UPDATE sec_facts SET last_seen_at=?, quality_flags=?, filing_relation=?, '
                          'selection_status=?, snapshot_hash=? WHERE fact_id=?',
                          (fact['last_seen_at'], fact['quality_flags'], fact['filing_relation'],
                           fact['selection_status'], fact['snapshot_hash'], row['fact_id']))
                return 'updated'
            c.execute('INSERT INTO sec_facts(cik,entity_name,taxonomy,tag,unit,period_start,period_end,'
                      'value_num,value_raw,fy,fp,form,filed,accn,frame,metric_id,filing_relation,'
                      'selection_status,quality_flags,snapshot_hash,first_seen_at,last_seen_at) '
                      'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (fact['cik'], fact['entity_name'], fact['taxonomy'], fact['tag'], fact['unit'],
                       fact['period_start'], fact['period_end'], fact['value_num'], fact['value_raw'],
                       fact['fy'], fact['fp'], fact['form'], fact['filed'], fact['accn'], fact['frame'],
                       fact['metric_id'], fact['filing_relation'], fact['selection_status'],
                       fact['quality_flags'], fact['snapshot_hash'], fact['first_seen_at'],
                       fact['last_seen_at']))
            return 'inserted'

    def set_sec_selection(self, cik, taxonomy, tag, unit, period_start, period_end, selected_accn):
        """Exactly one accession per (entity, metric, period) carries current_selected."""
        with self.connect() as c:
            c.execute('UPDATE sec_facts SET selection_status=CASE WHEN accn=? THEN ? ELSE ? END '
                      'WHERE cik=? AND taxonomy=? AND tag=? AND unit=? AND period_start IS ? AND period_end IS ?',
                      (selected_accn, 'current_selected', 'superseded',
                       cik, taxonomy, tag, unit, period_start, period_end))

    # ------------------------------------------------------------ EIA
    def ensure_series(self, series):
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO eia_series(series_id,dataset,route,metric,unit,frequency,'
                      'description,first_seen_at) VALUES(?,?,?,?,?,?,?,?)',
                      (series['series_id'], series['dataset'], series['route'], series['metric'],
                       series['unit'], series['frequency'], series.get('description', ''), now()))

    def upsert_eia_observation(self, obs):
        """Never overwrites history: a changed value adds a version row and flags observed_change."""
        with self.connect() as c:
            prev = c.execute('SELECT value_raw FROM eia_observations WHERE series_id=? AND period=?',
                             (obs['series_id'], obs['period'])).fetchone()
            if prev is None:
                c.execute('INSERT OR IGNORE INTO eia_observation_versions(series_id,period,value_raw,'
                          'value_num,observed_at,snapshot_hash,change_kind) VALUES(?,?,?,?,?,?,?)',
                          (obs['series_id'], obs['period'], obs['value_raw'], obs['value_num'],
                           obs['last_seen_at'], obs['snapshot_hash'], 'first_observed'))
                c.execute('INSERT INTO eia_observations(series_id,period,value_raw,value_num,unit,'
                          'period_kind,is_partial_year,quality_flags,snapshot_hash,first_seen_at,'
                          'last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                          (obs['series_id'], obs['period'], obs['value_raw'], obs['value_num'],
                           obs['unit'], obs['period_kind'], obs['is_partial_year'],
                           obs['quality_flags'], obs['snapshot_hash'], obs['first_seen_at'],
                           obs['last_seen_at']))
                return 'inserted'
            changed = (prev['value_raw'] or '') != (obs['value_raw'] or '')
            if changed:
                c.execute('INSERT OR IGNORE INTO eia_observation_versions(series_id,period,value_raw,'
                          'value_num,observed_at,snapshot_hash,change_kind) VALUES(?,?,?,?,?,?,?)',
                          (obs['series_id'], obs['period'], obs['value_raw'], obs['value_num'],
                           obs['last_seen_at'], obs['snapshot_hash'], 'observed_change'))
                flags = obs['quality_flags']
                obs['quality_flags'] = ','.join([f for f in (flags, 'observed_change') if f])
            c.execute('UPDATE eia_observations SET value_raw=?, value_num=?, quality_flags=?, '
                      'snapshot_hash=?, last_seen_at=? WHERE series_id=? AND period=?',
                      (obs['value_raw'], obs['value_num'], obs['quality_flags'], obs['snapshot_hash'],
                       obs['last_seen_at'], obs['series_id'], obs['period']))
            return 'changed' if changed else 'unchanged'

    # ------------------------------------------------------------ reporting helpers
    def counts(self):
        with self.connect() as c:
            out = {}
            for table in ('ingest_runs', 'ingest_failures', 'raw_snapshots', 'sec_facts',
                          'eia_series', 'eia_observations', 'eia_observation_versions'):
                out[table] = c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            return out

    def sec_summary(self):
        with self.connect() as c:
            rows = c.execute('SELECT metric_id, COUNT(*) n FROM sec_facts GROUP BY metric_id').fetchall()
            return {r['metric_id']: r['n'] for r in rows}

    def eia_summary(self):
        with self.connect() as c:
            rows = c.execute('SELECT period_kind, COUNT(*) n FROM eia_observations GROUP BY period_kind')
            return {r['period_kind']: r['n'] for r in rows}

    def dump(self, table):
        with self.connect() as c:
            return [dict(r) for r in c.execute(f'SELECT * FROM {table}')]


def write_json(path, payload):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return p
