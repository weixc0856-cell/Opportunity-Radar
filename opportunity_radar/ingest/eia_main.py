"""EIA ingest entry point — independent process.

    .venv\\Scripts\\python.exe -I -m opportunity_radar.ingest.eia_main [--json]

Never called by cli.main(). Scope is the single verified series (see eia.py); the API key is
read from the environment and never written to a snapshot, report or log.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

from . import eia, http, rights
from .config import IngestConfigError, IngestSettings
from .http import IngestError
from .store import IngestStore, now, write_json
from ..config import load_dotenv

DEFAULT_START = '2024-01'
DEFAULT_END = '2026-08'
DEFAULT_ANNUAL_START = '2024'
DEFAULT_ANNUAL_END = '2025'


def _batch_hash(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def run(settings, store, client=None, start=DEFAULT_START, end=DEFAULT_END,
        annual_start=DEFAULT_ANNUAL_START, annual_end=DEFAULT_ANNUAL_END):
    rights.assert_source_allowed('eia')
    run_id = store.start_run('eia')
    client = client or eia.EiaClient(settings)
    requests = records = errors = 0
    failures, batches = [], {}
    plans = [('monthly', start, end), ('annual', annual_start, annual_end)]
    for frequency, s, e in plans:
        try:
            query = eia.Query(frequency=frequency, start=s, end=e)
            rows = client.fetch_all(query, store=store)
            requests += 1
            digest = _batch_hash(rows)
            seen = now()
            observations = eia.normalize(query, rows, digest, seen)
            store.ensure_series(eia.series_meta(query, {'response': {}}))
            inserted = changed = unchanged = 0
            for obs in observations:
                outcome = store.upsert_eia_observation(obs)
                inserted += outcome == 'inserted'
                changed += outcome == 'changed'
                unchanged += outcome == 'unchanged'
            records += len(observations)
            batches[frequency] = {'rows': len(rows), 'inserted': inserted, 'changed': changed,
                                  'unchanged': unchanged, 'snapshot_hash': digest,
                                  'periods': [o['period'] for o in observations][:3] + ['...']
                                             + [o['period'] for o in observations][-2:]}
        except IngestError as exc:
            errors += 1
            store.record_failure(run_id, 'eia', f'fetch:{frequency}', exc.error_class,
                                 exc.detail, frequency)
            failures.append({'frequency': frequency, 'error_class': exc.error_class,
                             'detail': exc.detail})
        except Exception as exc:  # noqa: BLE001 - one frequency must not abort the other
            errors += 1
            store.record_failure(run_id, 'eia', f'unexpected:{frequency}', http.SERVER,
                                 f'{type(exc).__name__}: {exc}', frequency)
            failures.append({'frequency': frequency, 'error_class': http.SERVER,
                             'detail': str(exc)})
    status = 'success' if errors == 0 else ('failed' if records == 0 else 'partial_failed')
    store.finish_run(run_id, status, requests, records, errors,
                     f'{len(failures)} failure(s)', 0 if status == 'success' else 1)
    ytd = _year_to_date(store)
    return {'run_id': run_id, 'status': status, 'requests': requests, 'records': records,
            'errors': errors, 'failures': failures, 'batches': batches, 'ytd': ytd,
            'range': {'monthly': [start, end], 'annual': [annual_start, annual_end]},
            'generated_at': datetime.now(timezone.utc).isoformat()}


def _year_to_date(store):
    """Computed from stored monthly observations; never written as an annual observation."""
    rows = store.dump('eia_observations')
    if not rows:
        return None
    obs = [{'period': r['period'], 'period_kind': r['period_kind'], 'value_num': r['value_num']}
           for r in rows]
    years = sorted({o['period'][:4] for o in obs if o['period_kind'] == 'monthly'})
    if not years:
        return None
    return eia.year_to_date(obs, years[-1])


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description='EIA independent ingest (G-D2 phase 1)')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--start', default=DEFAULT_START)
    parser.add_argument('--end', default=DEFAULT_END)
    args = parser.parse_args(argv)
    # Scheduled runs start from a bare shell; .env is the project's only config file.
    load_dotenv()
    settings = IngestSettings.from_env()
    problems = settings.validate_eia()
    if problems:
        for p in problems:
            print(f'[config] {p}', file=sys.stderr)
        return 2
    try:
        store = IngestStore(settings.db_path)
    except IngestConfigError as exc:
        print(f'[config] {exc}', file=sys.stderr)
        return 2
    report = run(settings, store, start=args.start, end=args.end)
    report['database'] = str(store.path)
    path = write_json(f'{settings.report_dir}/eia-report.json', report)
    if args.json:
        print(path)
    else:
        print(f"EIA: {report['status']} requests={report['requests']} records={report['records']} "
              f"errors={report['errors']} -> {path}")
    return 0 if report['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
