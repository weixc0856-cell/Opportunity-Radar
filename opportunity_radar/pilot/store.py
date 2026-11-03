"""Isolated SQLite store for source-pilot observations.

One file, its own schema, its own snapshots and run records. It never opens the production
RSS database for writing and never reuses the SEC/EIA ingest schema.
"""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from opportunity_radar.ingest.config import assert_isolated_db

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS pilot_runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  records INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  exit_code INTEGER,
  config_hash TEXT NOT NULL DEFAULT '',
  query_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pilot_failures(
  failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  source_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  error_class TEXT NOT NULL,
  detail TEXT NOT NULL,
  external_ref TEXT,
  occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pilot_raw_snapshots(
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  request_key TEXT NOT NULL,
  status INTEGER,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  content_type TEXT,
  etag TEXT,
  last_modified TEXT,
  path TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  UNIQUE(source_id, request_key, sha256)
);
CREATE TABLE IF NOT EXISTS pilot_watermarks(
  source_id TEXT NOT NULL,
  query_id TEXT NOT NULL,
  last_success_at TEXT,
  last_seendate TEXT,
  last_run_id INTEGER,
  PRIMARY KEY(source_id, query_id)
);
CREATE TABLE IF NOT EXISTS discovery_candidates(
  candidate_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  domain TEXT NOT NULL,
  title TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  seen_count INTEGER NOT NULL DEFAULT 1,
  matched_article_key TEXT,
  matched_event_id TEXT,
  approved_source_id TEXT,
  resolution_status TEXT NOT NULL,
  lineage_role TEXT NOT NULL DEFAULT 'aggregator',
  evidence_role TEXT NOT NULL DEFAULT 'discovery',
  UNIQUE(source_id, canonical_url)
);
CREATE INDEX IF NOT EXISTS idx_discovery_domain ON discovery_candidates(domain);
CREATE INDEX IF NOT EXISTS idx_discovery_status ON discovery_candidates(resolution_status);
CREATE TABLE IF NOT EXISTS discovery_candidate_observations(
  observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id TEXT NOT NULL,
  query_id TEXT NOT NULL,
  seendate TEXT NOT NULL,
  title TEXT,
  language TEXT,
  source_country TEXT,
  raw_snapshot_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  UNIQUE(candidate_id, query_id, seendate)
);
CREATE INDEX IF NOT EXISTS idx_discovery_obs_query
  ON discovery_candidate_observations(query_id, observed_at);
CREATE TABLE IF NOT EXISTS link_candidates(
  link_id TEXT PRIMARY KEY,
  left_kind TEXT NOT NULL,
  left_key TEXT NOT NULL,
  right_kind TEXT NOT NULL,
  right_key TEXT NOT NULL,
  relation TEXT NOT NULL,
  basis TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(left_kind, left_key, right_kind, right_key, relation, basis)
);
CREATE TABLE IF NOT EXISTS policy_documents(
  document_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL DEFAULT 'federal-register',
  document_number TEXT NOT NULL,
  document_type TEXT NOT NULL,
  title TEXT NOT NULL,
  abstract TEXT,
  agencies_json TEXT NOT NULL DEFAULT '[]',
  agency_slugs TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  effective_on TEXT,
  comments_close_on TEXT,
  docket_ids_json TEXT NOT NULL DEFAULT '[]',
  citation TEXT,
  html_url TEXT,
  pdf_url TEXT,
  raw_text_url TEXT,
  related_document_numbers_json TEXT NOT NULL DEFAULT '[]',
  content_hash TEXT NOT NULL,
  latest_snapshot_hash TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(source_id, document_number)
);
CREATE INDEX IF NOT EXISTS idx_policy_type ON policy_documents(document_type);
CREATE INDEX IF NOT EXISTS idx_policy_published ON policy_documents(published_at);
CREATE TABLE IF NOT EXISTS policy_document_versions(
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  change_kind TEXT NOT NULL,
  fields_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(document_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_policy_versions_doc
  ON policy_document_versions(document_id, retrieved_at);
CREATE TABLE IF NOT EXISTS macro_series(
  series_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL DEFAULT 'bls',
  label TEXT NOT NULL,
  topic TEXT NOT NULL,
  unit TEXT NOT NULL,
  frequency TEXT NOT NULL,
  seasonal_adjustment TEXT NOT NULL,
  source_url TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS macro_observations(
  observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_id TEXT NOT NULL,
  year TEXT NOT NULL,
  period_raw TEXT NOT NULL,
  period TEXT,
  period_name TEXT,
  value_raw TEXT,
  value_num REAL,
  unit TEXT NOT NULL,
  preliminary INTEGER,
  latest INTEGER,
  footnotes_json TEXT NOT NULL DEFAULT '[]',
  quality_flags TEXT NOT NULL DEFAULT '',
  snapshot_hash TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(series_id, year, period_raw)
);
CREATE INDEX IF NOT EXISTS idx_macro_obs_series ON macro_observations(series_id, period);
CREATE TABLE IF NOT EXISTS macro_observation_versions(
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_id TEXT NOT NULL,
  year TEXT NOT NULL,
  period_raw TEXT NOT NULL,
  value_raw TEXT,
  value_num REAL,
  preliminary INTEGER,
  latest INTEGER,
  footnotes_json TEXT NOT NULL DEFAULT '[]',
  observed_at TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  change_kind TEXT NOT NULL,
  UNIQUE(series_id, year, period_raw, snapshot_hash)
);
CREATE INDEX IF NOT EXISTS idx_macro_versions_series
  ON macro_observation_versions(series_id, period_raw, observed_at);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


class PilotStore:
    def __init__(self, path, production=None, snapshot_dir=None):
        production_set = {Path(production)} if production else None
        self.path = assert_isolated_db(path, production=production_set)
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else Path(self.path).parent / 'snapshots'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self):
        with self.connect() as conn:
            current = conn.execute('PRAGMA user_version').fetchone()[0]
            if current < 4:
                # v3's macro tables keyed only on (series, period_raw), which collapses
                # M09 across years. BLS pilot data written under v3 is invalid; rebuild
                # only the macro tables, never production or other pilot domains.
                conn.execute('DROP TABLE IF EXISTS macro_observation_versions')
                conn.execute('DROP TABLE IF EXISTS macro_observations')
            conn.executescript(SCHEMA)
            if current < SCHEMA_VERSION:
                conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    # ------------------------------------------------------------ runs
    def start_run(self, source_id, config_hash='', query_hash=''):
        with self.connect() as conn:
            return conn.execute(
                'INSERT INTO pilot_runs(source_id,started_at,status,config_hash,query_hash) '
                'VALUES(?,?,?,?,?)',
                (source_id, now(), 'running', config_hash, query_hash)
            ).lastrowid

    def finish_run(self, run_id, status, requests=0, records=0, errors=0,
                   message='', exit_code=None):
        with self.connect() as conn:
            conn.execute(
                'UPDATE pilot_runs SET finished_at=?,status=?,requests=?,records=?,errors=?,'
                'message=?,exit_code=? WHERE run_id=?',
                (now(), status, requests, records, errors, message[:1000], exit_code, run_id)
            )

    def record_failure(self, run_id, source_id, stage, error_class, detail, external_ref=''):
        with self.connect() as conn:
            conn.execute(
                'INSERT INTO pilot_failures(run_id,source_id,stage,error_class,detail,'
                'external_ref,occurred_at) VALUES(?,?,?,?,?,?,?)',
                (run_id, source_id, stage, error_class, str(detail)[:2000],
                 external_ref, now())
            )

    def latest_run(self, source_id=None):
        with self.connect() as conn:
            if source_id:
                row = conn.execute(
                    'SELECT * FROM pilot_runs WHERE source_id=? ORDER BY run_id DESC LIMIT 1',
                    (source_id,)
                ).fetchone()
            else:
                row = conn.execute(
                    'SELECT * FROM pilot_runs ORDER BY run_id DESC LIMIT 1'
                ).fetchone()
            return dict(row) if row else None

    def failures(self, run_id=None):
        with self.connect() as conn:
            if run_id is None:
                rows = conn.execute(
                    'SELECT * FROM pilot_failures ORDER BY failure_id DESC'
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM pilot_failures WHERE run_id=? ORDER BY failure_id',
                    (run_id,)
                ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------ snapshots
    def save_snapshot(self, source_id, url, request_key, status, body,
                      content_type='application/json', etag='', last_modified='',
                      retrieved_at=None):
        digest = hashlib.sha256(body).hexdigest()
        rel = Path(source_id) / f'{digest}.json'
        target = self.snapshot_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        created = False
        if not target.exists():
            target.write_bytes(body)
            created = True
        with self.connect() as conn:
            conn.execute(
                'INSERT OR IGNORE INTO pilot_raw_snapshots(source_id,url,request_key,status,'
                'sha256,bytes,content_type,etag,last_modified,path,retrieved_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (source_id, url, request_key, status, digest, len(body), content_type,
                 etag, last_modified,
                 str(Path('snapshots') / rel).replace('\\', '/'),
                 retrieved_at or now())
            )
        return digest, created

    # ------------------------------------------------------------ watermarks
    def get_watermark(self, source_id, query_id):
        with self.connect() as conn:
            row = conn.execute(
                'SELECT * FROM pilot_watermarks WHERE source_id=? AND query_id=?',
                (source_id, query_id)
            ).fetchone()
            return dict(row) if row else None

    def set_watermark(self, source_id, query_id, last_success_at, last_seendate='',
                      last_run_id=None):
        with self.connect() as conn:
            conn.execute(
                'INSERT INTO pilot_watermarks(source_id,query_id,last_success_at,last_seendate,'
                'last_run_id) VALUES(?,?,?,?,?) '
                'ON CONFLICT(source_id,query_id) DO UPDATE SET '
                'last_success_at=excluded.last_success_at, '
                'last_seendate=excluded.last_seendate, '
                'last_run_id=excluded.last_run_id',
                (source_id, query_id, last_success_at, last_seendate, last_run_id)
            )

    # ------------------------------------------------------------ discovery
    def upsert_candidate(self, candidate):
        keys = ('candidate_id', 'source_id', 'url', 'canonical_url', 'domain', 'title',
                'first_seen_at', 'last_seen_at', 'matched_article_key', 'matched_event_id',
                'approved_source_id', 'resolution_status', 'lineage_role', 'evidence_role')
        values = tuple(candidate.get(key) for key in keys)
        with self.connect() as conn:
            row = conn.execute(
                'SELECT candidate_id FROM discovery_candidates WHERE candidate_id=?',
                (candidate['candidate_id'],)
            ).fetchone()
            if row:
                conn.execute(
                    'UPDATE discovery_candidates SET last_seen_at=?, seen_count=seen_count+1, '
                    'title=COALESCE(NULLIF(?, \'\'), title), '
                    'matched_article_key=COALESCE(?, matched_article_key), '
                    'matched_event_id=COALESCE(?, matched_event_id), '
                    'approved_source_id=COALESCE(?, approved_source_id), '
                    'resolution_status=? WHERE candidate_id=?',
                    (candidate['last_seen_at'], candidate.get('title'),
                     candidate.get('matched_article_key'), candidate.get('matched_event_id'),
                     candidate.get('approved_source_id'), candidate['resolution_status'],
                     candidate['candidate_id'])
                )
                return 'updated'
            conn.execute(
                'INSERT INTO discovery_candidates(candidate_id,source_id,url,canonical_url,domain,'
                'title,first_seen_at,last_seen_at,seen_count,matched_article_key,matched_event_id,'
                'approved_source_id,resolution_status,lineage_role,evidence_role) '
                'VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)',
                values
            )
            return 'inserted'

    def add_candidate_observation(self, candidate_id, query_id, seendate, title,
                                  language, source_country, raw_snapshot_hash,
                                  observed_at=None):
        with self.connect() as conn:
            cur = conn.execute(
                'INSERT OR IGNORE INTO discovery_candidate_observations(candidate_id,query_id,'
                'seendate,title,language,source_country,raw_snapshot_hash,observed_at) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (candidate_id, query_id, seendate, title, language, source_country,
                 raw_snapshot_hash, observed_at or now())
            )
            return cur.rowcount > 0

    def record_link_candidate(self, left_kind, left_key, right_kind, right_key,
                              relation, basis, confidence=0.0, evidence_json='{}'):
        link_id = hashlib.sha256(
            f'{left_kind}|{left_key}|{right_kind}|{right_key}|{relation}|{basis}'.encode()
        ).hexdigest()
        with self.connect() as conn:
            cur = conn.execute(
                'INSERT OR IGNORE INTO link_candidates(link_id,left_kind,left_key,right_kind,'
                'right_key,relation,basis,confidence,status,evidence_json,created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (link_id, left_kind, left_key, right_kind, right_key, relation, basis,
                 confidence, 'candidate', evidence_json, now())
            )
            return cur.rowcount > 0

    def candidate_by_url(self, canonical_url):
        with self.connect() as conn:
            row = conn.execute(
                'SELECT * FROM discovery_candidates WHERE canonical_url=?', (canonical_url,)
            ).fetchone()
            return dict(row) if row else None

    def candidate_stats(self, run_id=None):
        with self.connect() as conn:
            if run_id is not None:
                rows = conn.execute(
                    'SELECT resolution_status, COUNT(*) n FROM discovery_candidates '
                    'WHERE candidate_id IN (SELECT candidate_id FROM discovery_candidate_observations '
                    'WHERE observed_at >= (SELECT started_at FROM pilot_runs WHERE run_id=?)) '
                    'GROUP BY resolution_status', (run_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT resolution_status, COUNT(*) n FROM discovery_candidates '
                    'GROUP BY resolution_status'
                ).fetchall()
            return {row['resolution_status']: row['n'] for row in rows}

    def link_count(self):
        with self.connect() as conn:
            return conn.execute('SELECT COUNT(*) FROM link_candidates').fetchone()[0]

    # ------------------------------------------------------------ policy documents
    def upsert_policy_document(self, document):
        columns = (
            'document_id', 'source_id', 'document_number', 'document_type', 'title',
            'abstract', 'agencies_json', 'agency_slugs', 'published_at', 'effective_on',
            'comments_close_on', 'docket_ids_json', 'citation', 'html_url', 'pdf_url',
            'raw_text_url', 'related_document_numbers_json', 'content_hash',
            'latest_snapshot_hash', 'first_seen_at', 'last_seen_at',
        )
        values = tuple(document.get(key) for key in columns)
        with self.connect() as conn:
            row = conn.execute(
                'SELECT content_hash FROM policy_documents WHERE document_id=?',
                (document['document_id'],)
            ).fetchone()
            if row:
                if row['content_hash'] == document['content_hash']:
                    conn.execute(
                        'UPDATE policy_documents SET last_seen_at=?, latest_snapshot_hash=? '
                        'WHERE document_id=?',
                        (document['last_seen_at'], document['latest_snapshot_hash'],
                         document['document_id'])
                    )
                    return 'unchanged'
                conn.execute(
                    'UPDATE policy_documents SET document_type=?, title=?, abstract=?, '
                    'agencies_json=?, agency_slugs=?, published_at=?, effective_on=?, '
                    'comments_close_on=?, docket_ids_json=?, citation=?, html_url=?, '
                    'pdf_url=?, raw_text_url=?, related_document_numbers_json=?, '
                    'content_hash=?, latest_snapshot_hash=?, last_seen_at=? '
                    'WHERE document_id=?',
                    (document['document_type'], document['title'], document['abstract'],
                     document['agencies_json'], document['agency_slugs'],
                     document['published_at'], document['effective_on'],
                     document['comments_close_on'], document['docket_ids_json'],
                     document['citation'], document['html_url'], document['pdf_url'],
                     document['raw_text_url'], document['related_document_numbers_json'],
                     document['content_hash'], document['latest_snapshot_hash'],
                     document['last_seen_at'], document['document_id'])
                )
                self._insert_policy_version(conn, document, 'content_changed')
                return 'updated'
            conn.execute(
                'INSERT INTO policy_documents(%s) VALUES(%s)'
                % (','.join(columns), ','.join('?' * len(columns))),
                values
            )
            self._insert_policy_version(conn, document, 'initial')
            return 'inserted'

    @staticmethod
    def _insert_policy_version(conn, document, change_kind):
        conn.execute(
            'INSERT OR IGNORE INTO policy_document_versions(document_id,snapshot_hash,'
            'content_hash,retrieved_at,change_kind,fields_json) VALUES(?,?,?,?,?,?)',
            (document['document_id'], document['latest_snapshot_hash'],
             document['content_hash'], document.get('retrieved_at') or now(),
             change_kind, document.get('fields_json') or '{}')
        )

    def policy_document_by_number(self, document_number):
        with self.connect() as conn:
            row = conn.execute(
                'SELECT * FROM policy_documents WHERE document_number=?', (document_number,)
            ).fetchone()
            return dict(row) if row else None

    def policy_stats(self, run_id=None):
        with self.connect() as conn:
            if run_id is not None:
                where = ('WHERE last_seen_at >= '
                         '(SELECT started_at FROM pilot_runs WHERE run_id=?)')
                params = (run_id,)
            else:
                where = ''
                params = ()
            rows = conn.execute(
                f'SELECT document_type, COUNT(*) n FROM policy_documents {where} '
                'GROUP BY document_type', params
            ).fetchall()
            return {row['document_type']: row['n'] for row in rows}

    def policy_version_count(self):
        with self.connect() as conn:
            return conn.execute('SELECT COUNT(*) FROM policy_document_versions').fetchone()[0]

    # ------------------------------------------------------------ macro series
    def upsert_macro_series(self, series):
        columns = ('series_id', 'source_id', 'label', 'topic', 'unit', 'frequency',
                   'seasonal_adjustment', 'source_url', 'first_seen_at', 'last_seen_at')
        values = tuple(series.get(key) for key in columns)
        with self.connect() as conn:
            row = conn.execute('SELECT series_id FROM macro_series WHERE series_id=?',
                               (series['series_id'],)).fetchone()
            if row:
                conn.execute(
                    'UPDATE macro_series SET label=?, topic=?, unit=?, frequency=?, '
                    'seasonal_adjustment=?, source_url=?, last_seen_at=? WHERE series_id=?',
                    (series['label'], series['topic'], series['unit'], series['frequency'],
                     series['seasonal_adjustment'], series.get('source_url'),
                     series['last_seen_at'], series['series_id'])
                )
                return 'updated'
            conn.execute(
                'INSERT INTO macro_series(%s) VALUES(%s)'
                % (','.join(columns), ','.join('?' * len(columns))), values
            )
            return 'inserted'

    def upsert_macro_observation(self, observation):
        columns = ('series_id', 'year', 'period_raw', 'period', 'period_name', 'value_raw',
                   'value_num', 'unit', 'preliminary', 'latest', 'footnotes_json',
                   'quality_flags', 'snapshot_hash', 'first_seen_at', 'last_seen_at')
        values = tuple(observation.get(key) for key in columns)
        with self.connect() as conn:
            row = conn.execute(
                'SELECT * FROM macro_observations WHERE series_id=? AND year=? AND period_raw=?',
                (observation['series_id'], observation['year'], observation['period_raw'])
            ).fetchone()
            if row:
                same = (
                    row['year'] == observation.get('year') and
                    row['value_raw'] == observation.get('value_raw') and
                    row['value_num'] == observation.get('value_num') and
                    row['period'] == observation.get('period') and
                    row['period_name'] == observation.get('period_name') and
                    row['preliminary'] == observation.get('preliminary') and
                    row['latest'] == observation.get('latest') and
                    row['footnotes_json'] == observation.get('footnotes_json')
                )
                if same:
                    conn.execute(
                        'UPDATE macro_observations SET last_seen_at=?, snapshot_hash=? '
                        'WHERE observation_id=?',
                        (observation['last_seen_at'], observation['snapshot_hash'],
                         row['observation_id'])
                    )
                    return 'unchanged'
                conn.execute(
                    'UPDATE macro_observations SET period=?, period_name=?, value_raw=?, '
                    'value_num=?, unit=?, preliminary=?, latest=?, footnotes_json=?, '
                    'quality_flags=?, snapshot_hash=?, last_seen_at=? WHERE observation_id=?',
                    (observation.get('period'), observation.get('period_name'),
                     observation.get('value_raw'), observation.get('value_num'),
                     observation.get('unit'), observation.get('preliminary'),
                     observation.get('latest'), observation.get('footnotes_json'),
                     observation.get('quality_flags'), observation['snapshot_hash'],
                     observation['last_seen_at'], row['observation_id'])
                )
                self._insert_macro_version(conn, observation, 'revision')
                return 'updated'
            conn.execute(
                'INSERT INTO macro_observations(%s) VALUES(%s)'
                % (','.join(columns), ','.join('?' * len(columns))), values
            )
            self._insert_macro_version(conn, observation, 'initial')
            return 'inserted'

    @staticmethod
    def _insert_macro_version(conn, observation, change_kind):
        conn.execute(
            'INSERT OR IGNORE INTO macro_observation_versions(series_id,year,period_raw,value_raw,'
            'value_num,preliminary,latest,footnotes_json,observed_at,snapshot_hash,change_kind) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (observation['series_id'], observation['year'], observation['period_raw'],
             observation.get('value_raw'),
             observation.get('value_num'), observation.get('preliminary'),
             observation.get('latest'), observation.get('footnotes_json'),
             observation.get('observed_at') or now(), observation['snapshot_hash'], change_kind)
        )

    def macro_observation_by_period(self, series_id, year, period_raw):
        with self.connect() as conn:
            row = conn.execute(
                'SELECT * FROM macro_observations WHERE series_id=? AND year=? AND period_raw=?',
                (series_id, year, period_raw)
            ).fetchone()
            return dict(row) if row else None

    def macro_stats(self, run_id=None):
        with self.connect() as conn:
            rows = conn.execute(
                'SELECT s.frequency, COUNT(o.observation_id) n '
                'FROM macro_series s LEFT JOIN macro_observations o USING(series_id) '
                'GROUP BY s.frequency'
            ).fetchall()
            return {row['frequency']: row['n'] for row in rows}

    def macro_version_count(self):
        with self.connect() as conn:
            return conn.execute('SELECT COUNT(*) FROM macro_observation_versions').fetchone()[0]
