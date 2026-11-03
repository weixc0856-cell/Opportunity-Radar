"""CLI for the isolated source pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from dataclasses import replace

from .bls import run_bls
from .config import (
    GdeltQuery, PilotConfigError, config_hash, load_bls_series,
    load_federal_register_watchlist, load_gdelt_queries, load_pilot_sources,
    PilotSettings, pilot_source,
)
from .federal_register import default_since, run_federal_register
from .gdelt import run_gdelt, window_for_query
from .report import (
    latest_summary, write_bls_summary, write_federal_register_summary,
    write_gdelt_summary,
)
from .rights import PilotRightsError, assert_source_allowed
from ..config import load_dotenv
from .store import PilotStore


def _print(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _settings(args):
    settings = PilotSettings.from_env()
    overrides = {}
    if getattr(args, 'db', None):
        overrides['db_path'] = args.db
    if getattr(args, 'production_db', None):
        overrides['production_db'] = args.production_db
    if getattr(args, 'report_dir', None):
        overrides['report_dir'] = args.report_dir
    if getattr(args, 'snapshot_dir', None):
        overrides['snapshot_dir'] = args.snapshot_dir
    if overrides:
        settings = replace(settings, **overrides)
    return settings.validate()


def cmd_health(args):
    settings = _settings(args)
    sources = load_pilot_sources()
    gdelt = pilot_source('gdelt')
    fr = pilot_source('federal-register')
    bls = pilot_source('bls')
    queries = load_gdelt_queries()
    watches = load_federal_register_watchlist()
    bls_series = load_bls_series()
    assert_source_allowed('gdelt')
    assert_source_allowed('federal-register')
    assert_source_allowed('bls')
    _print({
        'status': 'ok',
        'db_path': settings.db_path,
        'snapshot_dir': settings.snapshot_dir,
        'report_dir': settings.report_dir,
        'production_db': settings.production_db,
        'gdelt_base_url': settings.gdelt_base_url,
        'fr_base_url': settings.fr_base_url,
        'bls_base_url': settings.bls_base_url,
        'max_records': settings.max_records,
        'min_interval_seconds': settings.gdelt_min_interval,
        'sources': [source.source_id for source in sources],
        'gdelt': {
            'enabled': gdelt.enabled,
            'commercial_use': gdelt.commercial_use,
            'subscriber_display': gdelt.subscriber_display,
            'retention_limit': gdelt.retention_limit,
        },
        'federal_register': {
            'enabled': fr.enabled,
            'commercial_use': fr.commercial_use,
            'subscriber_display': fr.subscriber_display,
            'retention_limit': fr.retention_limit,
            'watches': [watch.watch_id for watch in watches if watch.enabled],
        },
        'bls': {
            'enabled': bls.enabled,
            'commercial_use': bls.commercial_use,
            'subscriber_display': bls.subscriber_display,
            'retention_limit': bls.retention_limit,
            'series': [series.series_id for series in bls_series if series.enabled],
        },
        'queries': [query.query_id for query in queries if query.enabled],
    })
    return 0


def cmd_gdelt(args):
    settings = _settings(args)
    queries = load_gdelt_queries()
    if args.controlled:
        queries = [GdeltQuery(
            'controlled-retest',
            args.query_text or 'artificial intelligence',
            args.timespan or '1d',
            args.max_records or 10,
            '', '', True, 'single controlled retest; no retries',
        )]
    if args.max_records:
        queries = [replace(query, max_records=args.max_records) for query in queries]
    if args.query_id and not args.controlled:
        queries = [query for query in queries if query.query_id in set(args.query_id)]
    if args.limit_queries and not args.controlled:
        queries = queries[:args.limit_queries]
    if not queries:
        raise PilotConfigError('no GDELT queries selected')

    if not args.live:
        plans = []
        for query in queries:
            window = window_for_query(query, None, args.timespan)
            plans.append({
                'query_id': query.query_id,
                'query': query.query,
                'max_records': query.max_records,
                'window': window.__dict__,
                'controlled': args.controlled,
            })
        _print({'dry_run': True, 'source_id': 'gdelt', 'plans': plans})
        return 0

    store = PilotStore(settings.db_path, production=settings.production_db,
                       snapshot_dir=settings.snapshot_dir)
    config_file_hash = config_hash('config/pilot_sources.csv', 'config/pilot_gdelt_queries.csv')
    query_hash = hashlib.sha256(
        '|'.join(query.query_id for query in queries).encode('utf-8')
    ).hexdigest()
    summary = run_gdelt(
        settings, store, queries, timespan=args.timespan,
        query_ids=None if args.controlled else args.query_id,
        limit_queries=None if args.controlled else args.limit_queries,
        dry_run=False, config_hash=config_file_hash,
        query_hash=query_hash, report_writer=write_gdelt_summary,
        controlled=args.controlled,
    )
    _print(summary)
    return 0 if summary['status'] == 'success' else 1


def cmd_federal_register(args):
    settings = _settings(args)
    watches = load_federal_register_watchlist()
    if args.watch_id:
        watches = [watch for watch in watches if watch.watch_id in set(args.watch_id)]
    if args.limit_watches:
        watches = watches[:args.limit_watches]
    if not watches:
        raise PilotConfigError('no Federal Register watch rows selected')
    since = args.since or default_since()

    if not args.live:
        plans = [
            {'watch_id': watch.watch_id, 'agency_slug': watch.agency_slug,
             'term': watch.term, 'types': watch.types, 'max_documents': watch.max_documents}
            for watch in watches
        ]
        _print({'dry_run': True, 'source_id': 'federal-register', 'since': since,
                'until': args.until, 'max_pages': args.max_pages,
                'max_documents': args.max_documents, 'watches': plans})
        return 0

    store = PilotStore(settings.db_path, production=settings.production_db,
                       snapshot_dir=settings.snapshot_dir)
    config_file_hash = config_hash('config/pilot_sources.csv',
                                   'config/pilot_federal_register_watchlist.csv')
    query_hash = hashlib.sha256(
        '|'.join(watch.watch_id for watch in watches).encode('utf-8')
    ).hexdigest()
    summary = run_federal_register(
        settings, store, watches, since=since, until=args.until,
        max_pages=args.max_pages, max_documents=args.max_documents,
        watch_ids=args.watch_id, limit_watches=args.limit_watches,
        config_hash=config_file_hash, query_hash=query_hash,
        report_writer=write_federal_register_summary,
    )
    _print(summary)
    return 0 if summary['status'] == 'success' else 1


def cmd_bls(args):
    settings = _settings(args)
    series_list = load_bls_series()
    if args.series_id:
        wanted = set(args.series_id)
        series_list = [series for series in series_list if series.series_id in wanted]
    if args.limit_series:
        series_list = series_list[:args.limit_series]
    if not series_list:
        raise PilotConfigError('no BLS series selected')
    end_year = args.end_year or date.today().year
    start_year = args.start_year or (end_year - 9)

    if not args.live:
        _print(run_bls(
            settings, None, series_list, start_year, end_year, dry_run=True,
        ))
        return 0

    store = PilotStore(settings.db_path, production=settings.production_db,
                       snapshot_dir=settings.snapshot_dir)
    config_file_hash = config_hash('config/pilot_sources.csv', 'config/pilot_bls_series.csv')
    query_hash = hashlib.sha256(
        '|'.join(series.series_id for series in series_list).encode('utf-8')
    ).hexdigest()
    summary = run_bls(
        settings, store, series_list, start_year, end_year,
        config_hash=config_file_hash, query_hash=query_hash,
        report_writer=write_bls_summary,
    )
    _print(summary)
    return 0 if summary['status'] == 'success' else 1


def cmd_report(args):
    settings = _settings(args)
    store = PilotStore(settings.db_path, production=settings.production_db,
                       snapshot_dir=settings.snapshot_dir)
    found = latest_summary(store, args.source)
    if not found:
        print(f'no pilot run for {args.source}', file=sys.stderr)
        return 2
    _print(found)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description='Opportunity-Radar source pilot')
    sub = parser.add_subparsers(dest='command', required=True)

    health = sub.add_parser('health', help='validate pilot config and isolation')
    health.add_argument('--db')
    health.add_argument('--production-db')
    health.add_argument('--snapshot-dir')
    health.add_argument('--report-dir')
    health.set_defaults(func=cmd_health)

    gdelt = sub.add_parser('gdelt', help='GDELT discovery pilot')
    gdelt.add_argument('--live', action='store_true',
                       help='make real GDELT requests and write the pilot DB')
    gdelt.add_argument('--timespan', help='GDELT timespan, e.g. 1d or 7d')
    gdelt.add_argument('--query-id', action='append', help='run only this query id')
    gdelt.add_argument('--limit-queries', type=int)
    gdelt.add_argument('--max-records', type=int)
    gdelt.add_argument('--controlled', action='store_true',
                       help='one simple query, one HTTP request, no retry on 429')
    gdelt.add_argument('--query-text', help='simple query for --controlled mode')
    gdelt.add_argument('--db')
    gdelt.add_argument('--production-db')
    gdelt.add_argument('--snapshot-dir')
    gdelt.add_argument('--report-dir')
    gdelt.set_defaults(func=cmd_gdelt)

    fr = sub.add_parser('federal-register', help='Federal Register policy pilot')
    fr.add_argument('--live', action='store_true',
                    help='make real Federal Register requests and write the pilot DB')
    fr.add_argument('--since', help='publication_date >= YYYY-MM-DD; default 7 days ago')
    fr.add_argument('--until', help='publication_date <= YYYY-MM-DD')
    fr.add_argument('--watch-id', action='append', help='run only this watch id')
    fr.add_argument('--limit-watches', type=int)
    fr.add_argument('--max-pages', type=int, default=5)
    fr.add_argument('--max-documents', type=int, default=200)
    fr.add_argument('--db')
    fr.add_argument('--production-db')
    fr.add_argument('--snapshot-dir')
    fr.add_argument('--report-dir')
    fr.set_defaults(func=cmd_federal_register)

    bls = sub.add_parser('bls', help='BLS macro-series pilot')
    bls.add_argument('--live', action='store_true',
                     help='make a real BLS API v1 request and write the pilot DB')
    bls.add_argument('--start-year', type=int)
    bls.add_argument('--end-year', type=int)
    bls.add_argument('--series-id', action='append')
    bls.add_argument('--limit-series', type=int)
    bls.add_argument('--db')
    bls.add_argument('--production-db')
    bls.add_argument('--snapshot-dir')
    bls.add_argument('--report-dir')
    bls.set_defaults(func=cmd_bls)

    report = sub.add_parser('report', help='show latest pilot run')
    report.add_argument('--source', default='gdelt')
    report.add_argument('--db')
    report.add_argument('--production-db')
    report.add_argument('--snapshot-dir')
    report.add_argument('--report-dir')
    report.set_defaults(func=cmd_report)
    return parser


def main(argv=None):
    # Scheduled runs start from a bare shell; .env is the project's only config file.
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (PilotConfigError, PilotRightsError) as exc:
        print(f'[config] {exc}', file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI reports a clean failure
        print(f'[error] {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
