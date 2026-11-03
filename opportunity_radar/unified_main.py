"""Fill the unified Event / Evidence / Claim model from the stores that already exist.

    python -m opportunity_radar.unified_main rss      # production database
    python -m opportunity_radar.unified_main sec      # SEC facts in the ingest database
    python -m opportunity_radar.unified_main eia      # EIA observations in the ingest database
    python -m opportunity_radar.unified_main report   # what is in there now

Every identifier is a content hash and every insert is INSERT OR IGNORE, so a second run
adds nothing. `--dry-run` works on a throwaway copy of the database and reports what would
have changed.

This command never runs the digest, never calls a model and never touches scoring. It reads
existing records and writes only the R1 tables.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from . import audit, lineage, linking, migration, unified
from . import opportunity_candidates, opportunity_review
from .source_binding import backfill_article_sources
from .store import Store

DEFAULT_DB = 'data/opportunity_radar.sqlite3'
DEFAULT_INGEST_DB = 'data/ingest/opportunity_radar_ingest.sqlite3'


def _rss_db(explicit=None):
    return explicit or os.getenv('OR_DB_PATH') or DEFAULT_DB


def _ingest_db(explicit=None):
    return explicit or os.getenv('OR_INGEST_DB_PATH') or DEFAULT_INGEST_DB


def _payload(result_json):
    try:
        payload = json.loads(result_json or '{}')
    except (TypeError, ValueError):
        return {}, {}
    if not isinstance(payload, dict):
        return {}, {}
    return (payload.get('analysis') or {}), (payload.get('meta') or {})


def backfill_rss(db_path, limit=None):
    """Articles -> events; located v5 facts -> evidence + claim skeleton + link."""
    store = Store(db_path, migrate=False)
    uni = unified.UnifiedStore(db_path, migrate=False)
    report = {'articles': 0, 'events_new': 0, 'articles_skipped_v4': 0,
              'facts_located': 0, 'facts_skipped_unlocated': 0,
              'evidences': 0, 'claims': 0, 'links': 0,
              'evidences_rejected': 0, 'claims_rejected': 0, 'links_rejected': 0,
              'rejected_count': 0, 'rejected': []}

    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            '''SELECT a.article_key, a.url, a.title, a.published, a.summary_hash, a.source_id, s.result_json
               FROM articles a JOIN analyses s USING(article_key)
               ORDER BY COALESCE(a.published,''), a.article_key''')]
    if limit:
        rows = rows[:limit]

    for row in rows:
        analysis, meta = _payload(row['result_json'])
        ref = unified.ArticleRef(article_key=row['article_key'], url=row['url'] or '',
                                 title=row['title'] or '', published=row['published'] or '',
                                 source_id=str(meta.get('source_id') or row.get('source_id') or ''),
                                 summary_hash=row['summary_hash'] or '')
        placed = uni.assign_article(ref)
        report['articles'] += 1
        if placed.get('created'):
            report['events_new'] += 1
        if analysis.get('schema_version') != 5:
            # The plan is explicit: v4 records keep their analysis and get no invented claim.
            report['articles_skipped_v4'] += 1
            continue

        evidences, claims, links = [], [], []
        for section in store.analysis_sections(row['article_key']):
            if section.get('kind') != 'fact':
                continue
            fact_meta = section.get('meta') or {}
            if section.get('status') != 'located' or not fact_meta.get('quote') or not fact_meta.get('locator'):
                report['facts_skipped_unlocated'] += 1
                continue
            evidence = unified.evidence_from_fact(row['article_key'], section, ref.source_id)
            claim = unified.claim_from_fact(row['article_key'], section, placed['event_id'])
            evidences.append(evidence)
            claims.append(claim)
            links.append((claim['claim_id'], evidence['evidence_id'], 'direct',
                          evidence['independence'], claim['locator_json'], unified.now()))
            report['facts_located'] += 1
        written = uni.bulk_add(evidences, claims, links)
        for key in ('evidences', 'claims', 'links', 'evidences_rejected', 'claims_rejected',
                    'links_rejected', 'rejected_count'):
            report[key] += written.get(key, 0)
        report['rejected'].extend(written.get('rejected', []))
        report['rejected'] = report['rejected'][:20]
    return report


def _structured(db_path, table, to_evidence, to_claim, join=None):
    uni = unified.UnifiedStore(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        records = [dict(r) for r in conn.execute(f'SELECT * FROM {table}')]
        series = {}
        if join:
            series = {r['series_id']: dict(r) for r in conn.execute('SELECT * FROM eia_series')}
    finally:
        conn.close()
    evidences, claims, links = [], [], []
    for record in records:
        related = series.get(record.get('series_id')) if join else None
        evidence = to_evidence(record) if related is None else to_evidence(record, related)
        claim = to_claim(record) if related is None else to_claim(record, related)
        evidences.append(evidence)
        claims.append(claim)
        links.append((claim['claim_id'], evidence['evidence_id'], 'direct',
                      evidence['independence'], claim['locator_json'], unified.now()))
    written = uni.bulk_add(evidences, claims, links)
    written['records'] = len(records)
    return written


def backfill_sec(db_path):
    """Each stored XBRL fact becomes one primary-source evidence and one structured claim."""
    return _structured(db_path, 'sec_facts', unified.sec_evidence, unified.sec_claim)


def backfill_eia(db_path):
    return _structured(db_path, 'eia_observations', unified.eia_evidence, unified.eia_claim, join=True)


def seed_entities_and_mentions(db_path):
    """Register the companies the structured sources already cover, then extract mentions.

    The company list is the same static registry the SEC connector uses; nothing is derived
    from filing values. Mentions are produced by the single extract path so the daily run
    and the manual command cannot create two parallel mention rows for the same text.
    """
    from .ingest.labels import COMPANIES   # static registry, not ingest data

    store = unified.UnifiedStore(db_path, migrate=False)
    companies = [{'cik': cik, 'name': info['name'], 'ticker': info['ticker']}
                 for cik, info in COMPANIES.items()]
    created = linking.seed_entities(store, companies)
    report = linking.extract_entities(store)
    return {'entities_created': created,
            'mentions_created': report['mention_rows_written'],
            'articles_with_mentions': report['articles_scanned']}


def apply_lineage(db_path, registry_path=None):
    """Trace every evidence row back to the organisation behind its source.

    An invalid registry is not applied at all: a half-applied lineage would make some
    evidences look independent while their neighbours stayed unknown.
    """
    registry = lineage.load(registry_path or lineage.DEFAULT_REGISTRY)
    if not registry:
        return {'applied': False, 'problems': ['registry is empty or missing']}
    problems = lineage.validate(registry)
    if problems:
        return {'applied': False, 'problems': problems}
    store = unified.UnifiedStore(db_path, migrate=False)
    result = lineage.apply(store, registry)
    result['applied'] = True
    result['families'] = lineage.families_for(registry)
    return result


def build_event_candidates(db_path, window_days=linking.EVENT_CANDIDATE_WINDOW_DAYS):
    """Find strong/weak event pairs. They are candidates; no event is merged or moved."""
    return linking.link_event_candidates(unified.UnifiedStore(db_path, migrate=False), window_days=window_days)


def extract_entities(db_path):
    """Extract mentions and explicit entity relations from stored text."""
    return linking.extract_entities(unified.UnifiedStore(db_path, migrate=False))


def build_links(db_path, ingest_db):
    """Candidate links only: claim<->event when a company and a period line up, and
    event<->event when two events name the same company or share a strong event signal."""
    store = unified.UnifiedStore(db_path, migrate=False)
    with store.connect() as conn:
        cik_to_entity = {r['cik']: r['entity_id'] for r in conn.execute("SELECT cik, entity_id FROM entities WHERE cik<>''")}
    claims = []
    source = Path(ingest_db)
    if source.exists():
        conn = sqlite3.connect(source)
        conn.row_factory = sqlite3.Row
        try:
            has_claims = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='claims'").fetchone()
            if has_claims:
                for row in conn.execute("SELECT claim_id, period, locator_json FROM claims WHERE extractor='structured'"):
                    try:
                        locator = json.loads(row['locator_json'] or '{}')
                    except ValueError:
                        continue
                    entity_id = cik_to_entity.get(str(locator.get('cik') or ''))
                    if entity_id:
                        claims.append({'claim_id': row['claim_id'], 'entity_id': entity_id, 'period': row['period']})
        finally:
            conn.close()
    claim_links = linking.link_claims_to_events(store, claims)
    event_links = linking.link_events_by_entity(store)
    event_candidates = linking.link_event_candidates(store)
    return {'structured_claims_considered': len(claims), 'claim_event_links': claim_links,
            'event_event_links': event_links, 'event_candidates': event_candidates}


def report(db_path):
    """What the model holds, and where it is still thin. Counts only; no interpretation."""
    uni = unified.UnifiedStore(db_path, read_only=True)
    out = {'db': str(db_path), 'counts': uni.counts()}
    out['claims_without_evidence'] = len(uni.unlinked_claims(limit=100000))
    out['claims_without_locator'] = len(uni.claims_without_locator(limit=100000))
    multi = uni.events_with_multiple_sources()
    out['events_with_multiple_sources'] = len(multi)
    out['events_with_multiple_source_ids'] = len(multi)
    with uni.connect() as conn:
        event_ids = [r[0] for r in conn.execute('SELECT event_id FROM events ORDER BY event_id')]
        out['events_with_multiple_articles'] = conn.execute(
            'SELECT COUNT(*) FROM (SELECT event_id FROM event_articles GROUP BY event_id HAVING COUNT(*)>1)').fetchone()[0]
        out['claims_by_extractor'] = {r[0]: r[1] for r in conn.execute(
            'SELECT extractor, COUNT(*) FROM claims GROUP BY extractor ORDER BY 2 DESC')}
        out['claims_by_state'] = {r[0]: r[1] for r in conn.execute(
            'SELECT verification_state, COUNT(*) FROM claims GROUP BY verification_state ORDER BY 2 DESC')}
        out['entity_count_by_category'] = {category: 0 for category in linking.ENTITY_CATEGORIES}
        for row in conn.execute('SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type'):
            category = linking.entity_category(row[0])
            out['entity_count_by_category'][category] = out['entity_count_by_category'].get(category, 0) + row[1]
        mention_columns = {row[1] for row in conn.execute('PRAGMA table_info(entity_mentions)')}
        out['mention_rows'] = conn.execute('SELECT COUNT(*) FROM entity_mentions').fetchone()[0]
        if 'occurrence_count' in mention_columns:
            out['mention_occurrences'] = conn.execute(
                'SELECT COALESCE(SUM(occurrence_count),0) FROM entity_mentions').fetchone()[0]
        else:
            out['mention_occurrences'] = out['mention_rows']
        out['mentions_by_category'] = {category: 0 for category in linking.ENTITY_CATEGORIES}
        for row in conn.execute(
                'SELECT e.entity_type, COALESCE(SUM(m.occurrence_count),0) '
                'FROM entity_mentions m JOIN entities e USING(entity_id) GROUP BY e.entity_type'
                if 'occurrence_count' in mention_columns else
                'SELECT e.entity_type, COUNT(*) FROM entity_mentions m JOIN entities e USING(entity_id) '
                'GROUP BY e.entity_type'):
            category = linking.entity_category(row[0])
            out['mentions_by_category'][category] = out['mentions_by_category'].get(category, 0) + row[1]
        out['mentions_with_evidence'] = (conn.execute(
            "SELECT COUNT(*) FROM entity_mentions WHERE evidence_id<>''").fetchone()[0]
            if 'evidence_id' in mention_columns else 'absent')
        out['mentions_with_locator'] = (conn.execute(
            "SELECT COUNT(*) FROM entity_mentions WHERE locator_json NOT IN ('{}','')").fetchone()[0]
            if 'locator_json' in mention_columns else 'absent')
        try:
            out['entity_relations_by_type'] = {relation_type: 0 for relation_type in linking.RELATION_TYPES}
            for row in conn.execute(
                    'SELECT relation_type, COUNT(*) FROM entity_relations GROUP BY relation_type'):
                out['entity_relations_by_type'][row[0]] = row[1]
            out['entity_relations_by_type'][linking.REL_MENTIONED_IN] = out['mention_rows']
            out['unverified_entity_relations'] = conn.execute(
                "SELECT COUNT(*) FROM entity_relations WHERE verification_state='unverified'").fetchone()[0]
        except sqlite3.OperationalError:
            out['entity_relations_by_type'] = 'absent'
            out['unverified_entity_relations'] = 'absent'
        out['evidences_without_source'] = conn.execute(
            "SELECT COUNT(*) FROM evidences WHERE trim(source_id)=''").fetchone()[0]
        out['evidences_without_locator'] = conn.execute(
            "SELECT COUNT(*) FROM evidences WHERE locator_json IN ('{}','')").fetchone()[0]
        out['orphan_claim_evidence'] = conn.execute(
            '''SELECT COUNT(*) FROM claim_evidence ce LEFT JOIN evidences v USING(evidence_id)
               WHERE v.evidence_id IS NULL''').fetchone()[0]
        out['claims_without_valid_evidence'] = conn.execute(
            '''SELECT COUNT(*) FROM claims c WHERE NOT EXISTS (
                 SELECT 1 FROM claim_evidence ce JOIN evidences v USING(evidence_id)
                 WHERE ce.claim_id=c.claim_id AND trim(v.source_id)<>''
                   AND trim(v.quote)<>'' AND v.locator_json NOT IN ('{}',''))''').fetchone()[0]
        out['source_family_count'] = conn.execute(
            "SELECT COUNT(DISTINCT source_family) FROM evidences WHERE source_family<>''").fetchone()[0]
        out['syndicated_evidences'] = conn.execute(
            "SELECT COUNT(*) FROM evidences WHERE syndication_group<>''").fetchone()[0]
        out['syndication_groups'] = conn.execute(
            "SELECT COUNT(DISTINCT syndication_group) FROM evidences WHERE syndication_group<>''").fetchone()[0]
        corroborating = tuple(linking.CORROBORATING)
        out['unknown_independence_evidences'] = conn.execute(
            'SELECT COUNT(*) FROM evidences WHERE independence NOT IN (%s)'
            % ','.join('?' * len(corroborating)), corroborating).fetchone()[0]
        out['event_candidate_links'] = conn.execute(
            'SELECT COUNT(*) FROM event_links WHERE relation=?',
            (linking.REL_EVENT_CANDIDATE,)).fetchone()[0]
        reprint_candidate_links = 0
        for row in conn.execute('SELECT evidence_json FROM event_links WHERE relation=?',
                                (linking.REL_EVENT_CANDIDATE,)):
            try:
                evidence = json.loads(row[0] or '{}')
            except (TypeError, ValueError):
                evidence = {}
            if evidence.get('reprint_candidate'):
                reprint_candidate_links += 1
        out['reprint_candidate_links'] = reprint_candidate_links
        out['skeleton_claims_with_period'] = conn.execute(
            "SELECT COUNT(*) FROM claims WHERE extractor='skeleton' AND period<>''").fetchone()[0]
        out['skeleton_claims_verified'] = conn.execute(
            "SELECT COUNT(*) FROM claims WHERE extractor='skeleton' AND verification_state='verified'").fetchone()[0]
        if uni.has_articles:
            out['skeleton_claims_with_publication_period'] = conn.execute(
                '''SELECT COUNT(*) FROM claims c JOIN articles a USING(article_key)
                   WHERE c.extractor='skeleton' AND c.period<>''
                     AND c.period=substr(a.published,1,10)''').fetchone()[0]
        out['relations'] = {r[0]: r[1] for r in conn.execute(
            'SELECT relation, COUNT(*) FROM event_articles GROUP BY relation ORDER BY 2 DESC')}
        for table in ('entities', 'entity_mentions', 'event_links', 'claim_corrections'):
            try:
                out[table] = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            except sqlite3.OperationalError:
                out[table] = 'absent'
        try:
            out['links_by_status'] = {r[0]: r[1] for r in conn.execute(
                'SELECT status, COUNT(*) FROM event_links GROUP BY status')}
            out['links_by_relation'] = {r[0]: r[1] for r in conn.execute(
                'SELECT relation, COUNT(*) FROM event_links GROUP BY relation')}
            out['mentions_by_entity'] = [dict(r) for r in conn.execute(
                'SELECT en.canonical_name name, COUNT(*) n FROM entity_mentions m JOIN entities en USING(entity_id) '
                'GROUP BY en.entity_id ORDER BY n DESC LIMIT 10')]
        except sqlite3.OperationalError:
            pass
        try:
            out['evidences_by_family'] = {r[0] or '(none)': r[1] for r in conn.execute(
                'SELECT source_family, COUNT(*) FROM evidences GROUP BY source_family ORDER BY 2 DESC')}
            out['evidences_by_independence'] = {r[0]: r[1] for r in conn.execute(
                'SELECT independence, COUNT(*) FROM evidences GROUP BY independence ORDER BY 2 DESC')}
        except sqlite3.OperationalError:
            pass
    profiles = [linking.event_profile(uni, event_id) for event_id in event_ids]
    out['events_with_multiple_source_families'] = sum(
        1 for profile in profiles if profile.get('source_family_count', 0) > 1)
    out['events_with_independent_corroboration'] = sum(
        1 for profile in profiles if profile.get('independent_corroboration'))
    out['events_with_unknown_independence'] = sum(
        1 for profile in profiles if profile.get('independence_status') == 'UNKNOWN')
    out['events_with_partial_independence'] = sum(
        1 for profile in profiles if profile.get('independence_status') == 'PARTIAL')
    out['top_multi_source_events'] = multi[:10]
    return out


def _write_b_candidates(db_path, output_dir, fmt):
    report = opportunity_candidates.build_candidates(db_path)
    report['outputs'] = opportunity_candidates.write_outputs(report, output_dir, fmt)
    return report


def _run_on_copy(db_path, action):
    """`--dry-run` must not write to the real database, so it writes to a copy."""
    source = Path(db_path)
    if not source.exists():
        raise SystemExit(f'database not found: {db_path}')
    tmp = Path(tempfile.mkdtemp(prefix='or-unified-'))
    copy = tmp / source.name
    shutil.copy2(source, copy)
    try:
        return action(str(copy))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _split_review_argv(argv):
    raw = list(sys.argv[1:] if argv is None else argv)
    action = ''
    if raw and raw[0] == 'b-review':
        if len(raw) > 1 and raw[1] in ('validate', 'preview', 'apply'):
            action = raw[1]
            raw = [raw[0]] + raw[2:]
    return raw, action


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description='Backfill the unified Event/Evidence/Claim model')
    parser.add_argument('what', choices=('db-migrate', 'rss', 'sec', 'eia', 'entities', 'extract', 'links', 'candidates', 'b-candidates', 'b-review', 'lineage', 'sources', 'periods', 'audit', 'report', 'economic', 'quality', 'backtest', 'benchmark', 'opportunities', 'weekly', 'monthly'))
    parser.add_argument('--db', help='database to read and write')
    parser.add_argument('--ingest-db', help='SEC/EIA database (links)')
    parser.add_argument('--registry', help='source lineage registry (lineage)')
    parser.add_argument('--source-registry', help='source CSV used by audit')
    parser.add_argument('--limit', type=int, help='only the first N articles (rss)')
    parser.add_argument('--dry-run', action='store_true', help='work on a copy and leave the database untouched')
    parser.add_argument('--apply', action='store_true', help='apply a change (periods repair or db migration)')
    parser.add_argument('--backup', help='backup file required by db-migrate --apply')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--output-dir', default='reports', help='b-candidates report directory')
    parser.add_argument('--format', choices=('both', 'json', 'markdown'), default='both',
                        help='b-candidates output format')
    parser.add_argument('--manifest', help='b-review manifest path')
    parser.add_argument('--report', default='reports/opportunity-candidates.json',
                        help='candidate report used by b-review')
    parser.add_argument('--result-dir', default='reports', help='b-review apply result directory')
    argv, review_action = _split_review_argv(argv)
    args = parser.parse_args(argv)
    args.review_action = review_action

    if args.what == 'db-migrate':
        db = _rss_db(args.db)
        if args.apply and args.dry_run:
            print('choose either db-migrate --apply or --dry-run', file=sys.stderr)
            return 2
        try:
            result = migration.migrate(db, apply=args.apply, backup=args.backup)
        except (ValueError, RuntimeError, unified.SchemaVersionError) as exc:
            print(f'Migration stopped: {exc}', file=sys.stderr)
            return 2
        result['database'] = db
        result['dry_run'] = not args.apply
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.what == 'rss':
        db = _rss_db(args.db)
        action = lambda path: backfill_rss(path, limit=args.limit)
    elif args.what == 'sec':
        db = _ingest_db(args.db)
        action = backfill_sec
    elif args.what == 'eia':
        db = _ingest_db(args.db)
        action = backfill_eia
    elif args.what == 'entities':
        db = _rss_db(args.db)
        action = seed_entities_and_mentions
    elif args.what == 'extract':
        db = _rss_db(args.db)
        action = extract_entities
    elif args.what == 'lineage':
        db = _rss_db(args.db)
        action = lambda path: apply_lineage(path, args.registry)
    elif args.what == 'sources':
        db = _rss_db(args.db)
        action = lambda path: backfill_article_sources(Store(path, migrate=False))
    elif args.what == 'audit':
        db = _rss_db(args.db)
        action = lambda path: audit.audit(path, source_registry=args.source_registry,
                                          lineage_registry=args.registry)
    elif args.what == 'periods':
        db = _rss_db(args.db)
        if args.apply:
            action = lambda path: unified.repair_skeleton_periods(
                unified.UnifiedStore(path, migrate=False), apply=True)
        else:
            # An audit must not migrate the production schema. Only --apply opens writable.
            action = lambda path: unified.repair_skeleton_periods(
                unified.UnifiedStore(path, read_only=True), apply=False)
    elif args.what == 'links':
        db = _rss_db(args.db)
        action = lambda path: build_links(path, _ingest_db(args.ingest_db))
    elif args.what == 'candidates':
        db = _rss_db(args.db)
        action = lambda path: build_event_candidates(path)
    elif args.what == 'b-candidates':
        db = _rss_db(args.db)
        action = lambda path: _write_b_candidates(path, args.output_dir, args.format)
    elif args.what == 'economic':
        from . import economic
        db = _rss_db(args.db)
        action = lambda path: economic.refresh()
    elif args.what == 'quality':
        from . import quality
        db = _rss_db(args.db)
        action = lambda path: quality.record(path)
    elif args.what == 'backtest':
        from . import quality
        db = _rss_db(args.db)
        action = lambda path: quality.backtest(path, days=30)
    elif args.what == 'benchmark':
        from . import quality
        db = _rss_db(args.db)
        action = lambda path: quality.benchmark()
    elif args.what == 'opportunities':
        from . import opportunity_discovery
        db = _rss_db(args.db)
        action = lambda path: opportunity_discovery.discover(path)
    elif args.what in ('weekly', 'monthly'):
        from . import period_report
        db = _rss_db(args.db)
        action = lambda path: period_report.write(period_report.build(path, args.what),
                                                  args.output_dir)
    elif args.what == 'b-review':
        db = _rss_db(args.db)
        if not args.manifest:
            print('b-review requires --manifest', file=sys.stderr)
            return 2
        if args.review_action not in ('validate', 'preview', 'apply'):
            print('b-review requires validate, preview or apply', file=sys.stderr)
            return 2
        if args.review_action == 'apply' and not args.apply:
            print('b-review apply requires --apply', file=sys.stderr)
            return 2
        try:
            if args.review_action == 'validate':
                result = opportunity_review.validate_manifest(args.manifest, db, args.report)
            elif args.review_action == 'preview':
                result = opportunity_review.preview_manifest(args.manifest, db, args.report)
            else:
                result = opportunity_review.apply_manifest(args.manifest, db, args.report,
                                                            apply=True,
                                                            result_dir=args.result_dir)
        except (opportunity_review.ManifestError, unified.SchemaVersionError) as exc:
            print(f'b-review stopped: {exc}', file=sys.stderr)
            return 2
        result['database'] = db
        result['review_action'] = args.review_action
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if args.review_action == 'apply':
            return 0 if result.get('ok') else 2
        return 0 if result.get('valid') else 2
    else:
        db = _rss_db(args.db)
        action = report

    try:
        result = _run_on_copy(db, action) if args.dry_run else action(db)
    except unified.SchemaVersionError as exc:
        print(f'Database schema check failed: {exc}', file=sys.stderr)
        return 2
    result['database'] = db
    result['dry_run'] = bool(args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
