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

from . import lineage, linking, unified
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
    store = Store(db_path)
    uni = unified.UnifiedStore(db_path)
    report = {'articles': 0, 'events_new': 0, 'articles_skipped_v4': 0,
              'facts_located': 0, 'facts_skipped_unlocated': 0,
              'evidences': 0, 'claims': 0, 'links': 0}

    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            '''SELECT a.article_key, a.url, a.title, a.published, a.summary_hash, s.result_json
               FROM articles a JOIN analyses s USING(article_key)
               ORDER BY COALESCE(a.published,''), a.article_key''')]
    if limit:
        rows = rows[:limit]

    for row in rows:
        analysis, meta = _payload(row['result_json'])
        ref = unified.ArticleRef(article_key=row['article_key'], url=row['url'] or '',
                                 title=row['title'] or '', published=row['published'] or '',
                                 source_id=str(meta.get('source_id') or ''),
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
        report['evidences'] += written['evidences']
        report['claims'] += written['claims']
        report['links'] += written['links']
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
    """Register the companies the structured sources already cover, then find them in text.

    The company list is the same static registry the SEC connector uses; nothing is derived
    from filing values. Mentions are searched in what the pipeline actually holds: the title
    and every fact and inference the analysis produced.
    """
    from .ingest.labels import COMPANIES   # static registry, not ingest data

    store = unified.UnifiedStore(db_path)
    companies = [{'cik': cik, 'name': info['name'], 'ticker': info['ticker']}
                 for cik, info in COMPANIES.items()]
    created = linking.seed_entities(store, companies)

    analyser = Store(db_path)
    texts = []
    with analyser.connect() as conn:
        articles = [(r['article_key'], r['title'] or '') for r in conn.execute('SELECT article_key, title FROM articles')]
    for article_key, title in articles:
        parts = [title]
        for section in analyser.analysis_sections(article_key):
            if section.get('kind') in ('fact', 'inference') and section.get('text'):
                parts.append(section['text'])
        texts.append((article_key, ' | '.join(parts)))
    indexed = linking.index_mentions(store, texts)
    return {'entities_created': created, 'mentions_created': indexed['mentions'],
            'articles_with_mentions': indexed['articles']}


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
    store = unified.UnifiedStore(db_path)
    result = lineage.apply(store, registry)
    result['applied'] = True
    result['families'] = lineage.families_for(registry)
    return result


def build_links(db_path, ingest_db):
    """Candidate links only: claim<->event when a company and a period line up, and
    event<->event when two events name the same company within a few days."""
    store = unified.UnifiedStore(db_path)
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
    return {'structured_claims_considered': len(claims), 'claim_event_links': claim_links,
            'event_event_links': event_links}


def report(db_path):
    """What the model holds, and where it is still thin. Counts only; no interpretation."""
    uni = unified.UnifiedStore(db_path, read_only=True)
    out = {'db': str(db_path), 'counts': uni.counts()}
    out['claims_without_evidence'] = len(uni.unlinked_claims(limit=100000))
    out['claims_without_locator'] = len(uni.claims_without_locator(limit=100000))
    multi = uni.events_with_multiple_sources()
    out['events_with_multiple_sources'] = len(multi)
    with uni.connect() as conn:
        out['events_with_multiple_articles'] = conn.execute(
            'SELECT COUNT(*) FROM (SELECT event_id FROM event_articles GROUP BY event_id HAVING COUNT(*)>1)').fetchone()[0]
        out['claims_by_extractor'] = {r[0]: r[1] for r in conn.execute(
            'SELECT extractor, COUNT(*) FROM claims GROUP BY extractor ORDER BY 2 DESC')}
        out['claims_by_state'] = {r[0]: r[1] for r in conn.execute(
            'SELECT verification_state, COUNT(*) FROM claims GROUP BY verification_state ORDER BY 2 DESC')}
        out['relations'] = {r[0]: r[1] for r in conn.execute(
            'SELECT relation, COUNT(*) FROM event_articles GROUP BY relation ORDER BY 2 DESC')}
        for table in ('entities', 'entity_mentions', 'event_links'):
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
    out['top_multi_source_events'] = multi[:10]
    return out


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


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description='Backfill the unified Event/Evidence/Claim model')
    parser.add_argument('what', choices=('rss', 'sec', 'eia', 'entities', 'links', 'lineage', 'report'))
    parser.add_argument('--db', help='database to read and write')
    parser.add_argument('--ingest-db', help='SEC/EIA database (links)')
    parser.add_argument('--registry', help='source lineage registry (lineage)')
    parser.add_argument('--limit', type=int, help='only the first N articles (rss)')
    parser.add_argument('--dry-run', action='store_true', help='work on a copy and leave the database untouched')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

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
    elif args.what == 'lineage':
        db = _rss_db(args.db)
        action = lambda path: apply_lineage(path, args.registry)
    elif args.what == 'links':
        db = _rss_db(args.db)
        action = lambda path: build_links(path, _ingest_db(args.ingest_db))
    else:
        db = _rss_db(args.db)
        action = report

    result = _run_on_copy(db, action) if args.dry_run else action(db)
    result['database'] = db
    result['dry_run'] = bool(args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
