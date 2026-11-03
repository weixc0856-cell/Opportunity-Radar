"""R5 economic data engine.

A time series is not an article: it has a period, a unit, a frequency, a seasonal
adjustment and a revision policy. This module keeps a separate, append-only store for
official observations (BLS and EIA today), keeps every observed revision, and computes
derived metrics with the formula and inputs recorded next to the result.

It never writes the RSS business tables and never turns a series into an article.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RULES_VERSION = 'econ-v1'
DEFAULT_DB = Path('data/economic/economic.sqlite3')
PILOT_DB = Path('data/pilot/source_pilot.sqlite3')
INGEST_DB = Path('data/ingest/opportunity_radar_ingest.sqlite3')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS datasets(
  dataset_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  indicator TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT '',
  frequency TEXT NOT NULL DEFAULT '',
  geography TEXT NOT NULL DEFAULT '',
  seasonal_adjustment TEXT NOT NULL DEFAULT '',
  base_period TEXT NOT NULL DEFAULT '',
  revision_policy TEXT NOT NULL DEFAULT '',
  license TEXT NOT NULL DEFAULT '',
  source_db TEXT NOT NULL DEFAULT '',
  source_table TEXT NOT NULL DEFAULT '',
  source_key TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations(
  observation_id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL,
  period TEXT NOT NULL,
  value_num REAL,
  value_raw TEXT NOT NULL DEFAULT '',
  unit TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'observed',
  content_hash TEXT NOT NULL DEFAULT '',
  source_run TEXT NOT NULL DEFAULT '',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(dataset_id, period)
);
CREATE TABLE IF NOT EXISTS observation_versions(
  version_id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL,
  period TEXT NOT NULL,
  value_num REAL,
  value_raw TEXT NOT NULL DEFAULT '',
  content_hash TEXT NOT NULL DEFAULT '',
  observed_at TEXT NOT NULL,
  source_run TEXT NOT NULL DEFAULT '',
  UNIQUE(dataset_id, period, content_hash)
);
CREATE TABLE IF NOT EXISTS derived_metrics(
  metric_id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL,
  period TEXT NOT NULL,
  formula TEXT NOT NULL,
  inputs_json TEXT NOT NULL,
  value REAL,
  unit TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(dataset_id, period, formula)
);
CREATE TABLE IF NOT EXISTS economic_runs(
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  datasets INTEGER NOT NULL DEFAULT 0,
  observations INTEGER NOT NULL DEFAULT 0,
  versions INTEGER NOT NULL DEFAULT 0,
  derived INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT ''
);
'''


def _now():
    return datetime.now(timezone.utc).isoformat()


def _stable(prefix, *parts):
    digest = hashlib.sha256('\x1f'.join(str(part) for part in parts).encode('utf-8')).hexdigest()
    return prefix + digest[:16]


def _ro(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _connect(path=DEFAULT_DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _upsert_dataset(conn, dataset):
    stamp = _now()
    conn.execute(
        '''INSERT INTO datasets(dataset_id,provider,indicator,unit,frequency,geography,
              seasonal_adjustment,base_period,revision_policy,license,source_db,source_table,
              source_key,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(dataset_id) DO UPDATE SET
              provider=excluded.provider, indicator=excluded.indicator, unit=excluded.unit,
              frequency=excluded.frequency, geography=excluded.geography,
              seasonal_adjustment=excluded.seasonal_adjustment,
              base_period=excluded.base_period, revision_policy=excluded.revision_policy,
              license=excluded.license, source_db=excluded.source_db,
              source_table=excluded.source_table, source_key=excluded.source_key,
              updated_at=excluded.updated_at''',
        (dataset['dataset_id'], dataset.get('provider', ''), dataset.get('indicator', ''),
         dataset.get('unit', ''), dataset.get('frequency', ''), dataset.get('geography', 'US'),
         dataset.get('seasonal_adjustment', ''), dataset.get('base_period', ''),
         dataset.get('revision_policy', 'append_only_versions'), dataset.get('license', ''),
         dataset.get('source_db', ''), dataset.get('source_table', ''),
         dataset.get('source_key', ''), stamp, stamp))


def _upsert_observation(conn, dataset_id, period, value_num, value_raw, unit, source_run,
                        content_hash='', status='observed'):
    """Keep the current row and append a version whenever the observed value changes."""
    stamp = _now()
    content_hash = content_hash or hashlib.sha256(
        f'{dataset_id}\x1f{period}\x1f{value_raw}'.encode('utf-8')).hexdigest()
    current = conn.execute(
        'SELECT observation_id, content_hash, value_num FROM observations '
        'WHERE dataset_id=? AND period=?', (dataset_id, period)).fetchone()
    versions = 0
    if current is None:
        conn.execute(
            '''INSERT INTO observations(observation_id,dataset_id,period,value_num,value_raw,
                 unit,status,content_hash,source_run,first_seen_at,last_seen_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (_stable('obs-', dataset_id, period), dataset_id, period, value_num, value_raw,
             unit, status, content_hash, source_run, stamp, stamp))
        versions = 1
    else:
        if current['content_hash'] != content_hash or current['value_num'] != value_num:
            versions = 1
            conn.execute(
                '''UPDATE observations SET value_num=?,value_raw=?,unit=?,status=?,
                     content_hash=?,source_run=?,last_seen_at=? WHERE observation_id=?''',
                (value_num, value_raw, unit, status, content_hash, source_run, stamp,
                 current['observation_id']))
        else:
            conn.execute('UPDATE observations SET last_seen_at=? WHERE observation_id=?',
                         (stamp, current['observation_id']))
    # Every distinct observation of a period is retained, including the first one.
    inserted = conn.execute(
        '''INSERT OR IGNORE INTO observation_versions(version_id,dataset_id,period,value_num,
             value_raw,content_hash,observed_at,source_run)
           VALUES(?,?,?,?,?,?,?,?)''',
        (_stable('ver-', dataset_id, period, content_hash), dataset_id, period, value_num,
         value_raw, content_hash, stamp, source_run)).rowcount
    return 1, versions, inserted


def sync_bls(conn, path=PILOT_DB):
    path = Path(path)
    if not path.exists():
        return {'datasets': 0, 'observations': 0, 'versions': 0, 'source': str(path),
                'status': 'absent'}
    src = _ro(path)
    try:
        series = [dict(row) for row in src.execute('SELECT * FROM macro_series')]
        datasets = observations = versions = 0
        for item in series:
            dataset_id = f"bls:{item['series_id']}"
            _upsert_dataset(conn, {
                'dataset_id': dataset_id, 'provider': 'BLS',
                'indicator': item.get('label') or item['series_id'],
                'unit': item.get('unit') or '', 'frequency': item.get('frequency') or '',
                'geography': 'US', 'seasonal_adjustment': item.get('seasonal_adjustment') or '',
                'license': 'BLS public data API v1; internal use',
                'source_db': str(path), 'source_table': 'macro_observations',
                'source_key': item['series_id']})
            datasets += 1
            rows = [dict(row) for row in src.execute(
                'SELECT period,value_num,value_raw,unit,snapshot_hash FROM macro_observations '
                'WHERE series_id=? ORDER BY period', (item['series_id'],))]
            for row in rows:
                if not row.get('period'):
                    continue
                obs, vers, new_versions = _upsert_observation(
                    conn, dataset_id, row['period'], row.get('value_num'),
                    row.get('value_raw') or '', row.get('unit') or item.get('unit') or '',
                    'bls-pilot', row.get('snapshot_hash') or '')
                observations += obs
                versions += new_versions
        return {'datasets': datasets, 'observations': observations, 'versions': versions,
                'source': str(path), 'status': 'ok'}
    finally:
        src.close()


def sync_eia(conn, path=INGEST_DB):
    path = Path(path)
    if not path.exists():
        return {'datasets': 0, 'observations': 0, 'versions': 0, 'source': str(path),
                'status': 'absent'}
    src = _ro(path)
    try:
        series = [dict(row) for row in src.execute('SELECT * FROM eia_series')]
        datasets = observations = versions = 0
        for item in series:
            dataset_id = f"eia:{item['series_id']}"
            _upsert_dataset(conn, {
                'dataset_id': dataset_id, 'provider': 'EIA',
                'indicator': item.get('metric') or item['series_id'],
                'unit': item.get('unit') or '', 'frequency': item.get('frequency') or '',
                'geography': 'US', 'seasonal_adjustment': 'not stated',
                'license': 'EIA public data API; internal use',
                'source_db': str(path), 'source_table': 'eia_observations',
                'source_key': item['series_id']})
            datasets += 1
            rows = [dict(row) for row in src.execute(
                'SELECT period,value_num,value_raw,unit,snapshot_hash FROM eia_observations '
                'WHERE series_id=? ORDER BY period', (item['series_id'],))]
            for row in rows:
                if not row.get('period'):
                    continue
                obs, vers, new_versions = _upsert_observation(
                    conn, dataset_id, row['period'], row.get('value_num'),
                    row.get('value_raw') or '', row.get('unit') or item.get('unit') or '',
                    'eia-ingest', row.get('snapshot_hash') or '')
                observations += obs
                versions += new_versions
        return {'datasets': datasets, 'observations': observations, 'versions': versions,
                'source': str(path), 'status': 'ok'}
    finally:
        src.close()


def _previous_month(period):
    try:
        year, month = (int(part) for part in str(period).split('-'))
    except (TypeError, ValueError):
        return ''
    month -= 1
    if month == 0:
        year, month = year - 1, 12
    return f'{year:04d}-{month:02d}'


def _monthly_periods(conn, dataset_id):
    rows = [dict(row) for row in conn.execute(
        "SELECT period, value_num FROM observations WHERE dataset_id=? AND value_num IS NOT NULL "
        "AND period GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' ORDER BY period", (dataset_id,))]
    return rows


def derive(conn):
    """Month-over-month and year-over-year changes with formula and inputs recorded."""
    written = 0
    stamp = _now()
    datasets = [row[0] for row in conn.execute(
        "SELECT DISTINCT dataset_id FROM observations WHERE period GLOB "
        "'[0-9][0-9][0-9][0-9]-[0-9][0-9]'")]
    for dataset_id in datasets:
        rows = _monthly_periods(conn, dataset_id)
        by_period = {row['period']: row['value_num'] for row in rows if row['value_num'] is not None}
        unit_row = conn.execute('SELECT unit FROM datasets WHERE dataset_id=?',
                                (dataset_id,)).fetchone()
        unit = unit_row['unit'] if unit_row else ''
        for index, row in enumerate(rows):
            current = row['value_num']
            if current is None:
                continue
            previous = rows[index - 1] if index > 0 else None
            if (previous and previous['period'] == _previous_month(row['period'])
                    and previous['value_num'] not in (None, 0)):
                formula = 'mom_pct = (value / previous_value - 1) * 100'
                value = round((current / previous['value_num'] - 1) * 100, 6)
                written += conn.execute(
                    '''INSERT OR IGNORE INTO derived_metrics(metric_id,dataset_id,period,formula,
                         inputs_json,value,unit,created_at) VALUES(?,?,?,?,?,?,?,?)''',
                    (_stable('drv-', dataset_id, row['period'], formula), dataset_id,
                     row['period'], formula,
                     json.dumps({'current': current, 'previous': previous['value_num'],
                                 'previous_period': previous['period']}, sort_keys=True),
                     value, 'percent', stamp)).rowcount
            year, month = row['period'].split('-')
            prior_period = f'{int(year) - 1}-{month}'
            if prior_period in by_period and by_period[prior_period] not in (None, 0):
                formula = 'yoy_pct = (value / value_one_year_earlier - 1) * 100'
                value = round((current / by_period[prior_period] - 1) * 100, 6)
                written += conn.execute(
                    '''INSERT OR IGNORE INTO derived_metrics(metric_id,dataset_id,period,formula,
                         inputs_json,value,unit,created_at) VALUES(?,?,?,?,?,?,?,?)''',
                    (_stable('drv-', dataset_id, row['period'], formula), dataset_id,
                     row['period'], formula,
                     json.dumps({'current': current,
                                 'previous': by_period[prior_period],
                                 'previous_period': prior_period}, sort_keys=True),
                     value, 'percent', stamp)).rowcount
    return written


def refresh(db_path=DEFAULT_DB, pilot_db=PILOT_DB, ingest_db=INGEST_DB):
    """Sync BLS + EIA, append revisions, derive MoM/YoY, and record the run."""
    started = _now()
    conn = _connect(db_path)
    run_id = _stable('econrun-', started)
    try:
        conn.execute(
            'INSERT INTO economic_runs(run_id,started_at,status) VALUES(?,?,?)',
            (run_id, started, 'running'))
        conn.commit()
        errors = []
        bls = sync_bls(conn, pilot_db)
        eia = sync_eia(conn, ingest_db)
        derived = derive(conn)
        for result in (bls, eia):
            if result.get('status') not in ('ok', 'absent'):
                errors.append(result)
        datasets = conn.execute('SELECT COUNT(*) FROM datasets').fetchone()[0]
        observations = conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        versions = conn.execute('SELECT COUNT(*) FROM observation_versions').fetchone()[0]
        status = 'success' if not errors else 'partial_failed'
        conn.execute(
            '''UPDATE economic_runs SET finished_at=?,status=?,datasets=?,observations=?,
                 versions=?,derived=?,errors=?,message=? WHERE run_id=?''',
            (_now(), status, datasets, observations, versions, derived, len(errors),
             json.dumps({'bls': bls, 'eia': eia}, ensure_ascii=False, sort_keys=True),
             run_id))
        conn.commit()
        return {'run_id': run_id, 'status': status, 'datasets': datasets,
                'observations': observations, 'versions': versions, 'derived': derived,
                'errors': errors, 'sources': {'bls': bls, 'eia': eia}}
    except Exception as exc:
        conn.execute('UPDATE economic_runs SET finished_at=?,status=?,message=? WHERE run_id=?',
                     (_now(), 'failed', f'{type(exc).__name__}: {exc}'[:500], run_id))
        conn.commit()
        raise
    finally:
        conn.close()


def summary(db_path=DEFAULT_DB):
    conn = _connect(db_path)
    try:
        return {
            'datasets': [dict(row) for row in conn.execute(
                'SELECT * FROM datasets ORDER BY dataset_id')],
            'observations': conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0],
            'versions': conn.execute('SELECT COUNT(*) FROM observation_versions').fetchone()[0],
            'derived': conn.execute('SELECT COUNT(*) FROM derived_metrics').fetchone()[0],
            'runs': [dict(row) for row in conn.execute(
                'SELECT * FROM economic_runs ORDER BY started_at DESC LIMIT 5')],
        }
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Refresh the economic observation engine')
    parser.add_argument('--db', default=str(DEFAULT_DB))
    parser.add_argument('--pilot-db', default=str(PILOT_DB))
    parser.add_argument('--ingest-db', default=str(INGEST_DB))
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args()
    result = summary(args.db) if args.summary else refresh(args.db, args.pilot_db, args.ingest_db)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
