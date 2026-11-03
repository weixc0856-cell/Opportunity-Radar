"""SEC EDGAR ingest entry point — independent process.

    .venv\\Scripts\\python.exe -I -m opportunity_radar.ingest.sec_main [--limit N] [--json]

Never called by cli.main(). Writes only to the ingest database and the ingest report directory.
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timezone

from . import http, labels, rights
from .config import IngestConfigError, IngestSettings
from .http import IngestError
from .sec import ConceptRequest, SecClient, assign_filing_relations, normalize_concept, plan_selection
from .store import IngestStore, now, write_json
from ..config import load_dotenv


def run(settings, store, limit=None, client=None):
    rights.assert_source_allowed('sec-edgar')
    run_id = store.start_run('sec-edgar')
    client = client or SecClient(settings)
    requests = records = errors = 0
    failures, per_company = [], {}
    targets = labels.requested_tags()
    if limit:
        targets = targets[:limit]
    for cik, metric, taxonomy, tag, status in targets:
        req = ConceptRequest(cik=cik, taxonomy=taxonomy, tag=tag, metric_id=metric)
        try:
            payload = client.companyconcept(req, store=store)
            requests += 1
            digest = _sha(payload)
            facts, flag = normalize_concept(payload, req, digest, now())
            if flag == 'no_facts':
                store.record_failure(run_id, 'sec-edgar', 'normalize', http.EMPTY_RESULT,
                                     f'{labels.COMPANIES[cik]["ticker"]} {metric} {tag}: no facts', tag)
                failures.append({'cik': cik, 'metric': metric, 'tag': tag,
                                 'error_class': http.EMPTY_RESULT, 'detail': 'no_facts'})
                continue
            relations = assign_filing_relations(facts)
            inserted = updated = 0
            for fact in facts:
                if status == labels.REQUIRES_FILING_PARSE:
                    fact['quality_flags'] = ','.join(
                        [f for f in (fact['quality_flags'], labels.REQUIRES_FILING_PARSE) if f])
                outcome = store.upsert_sec_fact(fact)
                inserted += outcome == 'inserted'
                updated += outcome == 'updated'
            for key, accn in plan_selection(facts):
                store.set_sec_selection(*key, selected_accn=accn)
            records += len(facts)
            per_company.setdefault(cik, []).append(
                {'metric': metric, 'tag': tag, 'status': status, 'facts': len(facts),
                 'inserted': inserted, 'updated': updated, 'relations': relations})
        except IngestError as exc:
            errors += 1
            store.record_failure(run_id, 'sec-edgar', 'fetch/normalize', exc.error_class,
                                 exc.detail, tag)
            failures.append({'cik': cik, 'metric': metric, 'tag': tag,
                             'error_class': exc.error_class, 'detail': exc.detail})
        except Exception as exc:  # noqa: BLE001 - one company must not abort the rest
            errors += 1
            store.record_failure(run_id, 'sec-edgar', 'unexpected', http.SERVER,
                                 f'{type(exc).__name__}: {exc}', tag)
            failures.append({'cik': cik, 'metric': metric, 'tag': tag,
                             'error_class': http.SERVER, 'detail': str(exc)})
    status = 'success' if errors == 0 else ('failed' if records == 0 else 'partial_failed')
    store.finish_run(run_id, status, requests, records, errors,
                     f'{len(failures)} failure(s)', 0 if status == 'success' else 1)
    return {'run_id': run_id, 'status': status, 'requests': requests, 'records': records,
            'errors': errors, 'failures': failures,
            'unsupported': labels.unsupported(), 'by_company': per_company,
            'generated_at': datetime.now(timezone.utc).isoformat()}


def _sha(payload):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description='SEC EDGAR independent ingest (G-D2 phase 1)')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    # Scheduled runs start from a bare shell; .env is the project's only config file.
    load_dotenv()
    settings = IngestSettings.from_env()
    problems = settings.validate_sec()
    if problems:
        for p in problems:
            print(f'[config] {p}', file=sys.stderr)
        return 2
    try:
        store = IngestStore(settings.db_path)
    except IngestConfigError as exc:
        print(f'[config] {exc}', file=sys.stderr)
        return 2
    report = run(settings, store, limit=args.limit)
    report['database'] = str(store.path)
    path = write_json(f'{settings.report_dir}/sec-report.json', report)
    if args.json:
        print(path)
    else:
        print(f"SEC: {report['status']} requests={report['requests']} records={report['records']} "
              f"errors={report['errors']} -> {path}")
    return 0 if report['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
