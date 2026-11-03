"""Read-only end-to-end audit for the P0 data chain.

The audit opens the database with SQLite mode=ro and never calls Store.init(),
UnifiedStore.init() or any backfill. It reports what is present, what is missing and
which semantic boundary is broken; it does not repair data.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from . import lineage, linking, source_policy


def _norm(value):
    return re.sub(r'[^0-9a-z]+', ' ', str(value or '').lower()).strip()


def _connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table):
    try:
        return {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
    except sqlite3.OperationalError:
        return set()


def _table(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _samples(rows, keys, limit=5):
    out = []
    for row in list(rows)[:limit]:
        item = dict(row)
        out.append({key: item.get(key) for key in keys})
    return out


def _load_sources(path=None):
    if path:
        return source_policy.load_sources(path)
    env = os.getenv('OR_SOURCES_PATH')
    if env:
        return source_policy.load_sources(env)
    local = Path('config/sources.local.csv')
    return source_policy.load_sources(str(local)) if local.exists() else source_policy.load_sources()


def _check(check_id, severity, summary, count, samples=(), detail=None):
    return {'id': check_id, 'severity': severity, 'summary': summary,
            'count': int(count or 0), 'samples': list(samples or []),
            **({'detail': detail} if detail is not None else {})}


def _source_checks(conn, sources, lineage_path):
    checks, info = [], {}
    if not _table(conn, 'articles'):
        checks.append(_check('source.articles_absent', 'ERROR', 'articles table is missing', 1))
        return checks, info
    cols = _columns(conn, 'articles')
    total = conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
    info['articles'] = total
    info['source_id_column'] = 'source_id' in cols
    if 'source_id' not in cols:
        checks.append(_check('source.source_id_absent', 'WARN',
                             'articles.source_id is absent; ingestion identity is unavailable', total,
                             _samples(conn.execute('SELECT article_key, source_name FROM articles'), ['article_key', 'source_name'])))
        info['ingested_from_articles'] = 0
    else:
        info['ingested_from_articles'] = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE source_id<>''").fetchone()[0]
        missing = conn.execute(
            "SELECT article_key, source_name FROM articles WHERE source_id='' ORDER BY article_key")
        checks.append(_check('source.article_missing_source_id', 'WARN',
                             'articles without a bound ingestion source_id',
                             conn.execute("SELECT COUNT(*) FROM articles WHERE source_id=''").fetchone()[0],
                             _samples(missing, ['article_key', 'source_name'])))
    registry = {source.source_id: source for source in sources if source.source_id}
    info['registry_sources'] = len(registry)
    if registry and 'source_id' in cols:
        unknown = [row for row in conn.execute(
            "SELECT article_key, source_id, source_name FROM articles "
            "WHERE source_id<>'' AND source_id NOT IN (%s) ORDER BY article_key"
            % ','.join('?' * len(registry)), tuple(registry))]
        checks.append(_check('source.source_id_not_registered', 'ERROR',
                             'article source_id is not present in the source registry', len(unknown),
                             _samples(unknown, ['article_key', 'source_id', 'source_name'])))
        mismatched = [row for row in conn.execute(
            "SELECT a.article_key, a.source_id, a.source_name FROM articles a "
            "WHERE a.source_id<>'' ORDER BY a.article_key")
            if row['source_id'] in registry
            and _norm(row['source_name']) != _norm(registry[row['source_id']].name)]
        checks.append(_check('source.source_name_differs_from_registry', 'INFO',
                             'source_name is a feed label that differs from the registry display name; '
                             'it is not evidence of a publisher', len(mismatched),
                             _samples(mismatched, ['article_key', 'source_id', 'source_name'])))
    registry_rows = lineage.load(lineage_path or lineage.DEFAULT_REGISTRY)
    review_status = {}
    groups = set()
    for row in registry_rows.values():
        status = (row.get('review_status') or '').strip() or 'unknown'
        review_status[status] = review_status.get(status, 0) + 1
        if (row.get('syndication_group') or '').strip():
            groups.add(row['syndication_group'].strip())
    info['lineage_review_status'] = review_status
    info['lineage_registry_rows'] = len(registry_rows)
    info['lineage_syndication_groups'] = len(groups)
    if review_status.get('declared', 0) and not review_status.get('verified', 0):
        checks.append(_check('source.lineage_only_declared', 'WARN',
                             'source lineage rows are declared, not independently verified',
                             review_status.get('declared', 0), detail=review_status))
    if _table(conn, 'evidences'):
        syndicated = conn.execute(
            "SELECT COUNT(*) FROM evidences WHERE syndication_group<>''").fetchone()[0]
        info['syndicated_evidences'] = syndicated
        checks.append(_check('source.syndication_group_evidence', 'INFO',
                             'evidence rows with a recorded syndication group', syndicated))
    if _table(conn, 'entity_relations'):
        published = [dict(row) for row in conn.execute(
            "SELECT relation_id, subject_entity_id, method, verification_state FROM entity_relations "
            "WHERE relation_type=?", (linking.REL_PUBLISHED_BY,))]
        unsupported = [row for row in published if row.get('method') == 'source_name']
        checks.append(_check('source.published_by_without_explicit_publisher', 'ERROR',
                             'PUBLISHED_BY was derived from a feed/source label, not a publisher identity',
                             len(unsupported), _samples(unsupported, ['relation_id', 'subject_entity_id', 'method'])))
        if published and not unsupported:
            checks.append(_check('source.published_by_present', 'WARN',
                                 'PUBLISHED_BY rows exist; verify each has an explicit publisher basis',
                                 len(published), _samples(published, ['relation_id', 'subject_entity_id', 'method'])))
    return checks, info


def _evidence_claim_checks(conn):
    checks = []
    evidence_cols = _columns(conn, 'evidences')
    if not evidence_cols:
        return [_check('evidence.table_absent', 'ERROR', 'evidences table is missing', 1)]
    if 'source_id' in evidence_cols:
        missing = [dict(row) for row in conn.execute(
            "SELECT evidence_id, article_key, source_id FROM evidences WHERE source_id=''")]
        checks.append(_check('evidence.missing_source', 'ERROR',
                             'evidence without a source identity', len(missing),
                             _samples(missing, ['evidence_id', 'article_key', 'source_id'])))
    if 'locator_json' in evidence_cols:
        missing_locator = [dict(row) for row in conn.execute(
            "SELECT evidence_id, article_key FROM evidences WHERE locator_json IN ('{}','')")]
        checks.append(_check('evidence.missing_locator', 'ERROR',
                             'evidence without a locator', len(missing_locator),
                             _samples(missing_locator, ['evidence_id', 'article_key'])))
    if _table(conn, 'articles'):
        unresolvable = [dict(row) for row in conn.execute(
            "SELECT v.evidence_id, v.article_key FROM evidences v "
            "LEFT JOIN articles a USING(article_key) "
            "WHERE (v.article_key<>'' AND a.article_key IS NULL) "
            "   OR (v.article_key='' AND v.locator_json NOT LIKE '%accn%' "
            "       AND v.locator_json NOT LIKE '%series_id%')")]
        checks.append(_check('evidence.unresolvable_to_source_record', 'ERROR',
                             'evidence cannot be traced to an article or filing/series record',
                             len(unresolvable), _samples(unresolvable, ['evidence_id', 'article_key'])))
    if _table(conn, 'claims'):
        claim_cols = _columns(conn, 'claims')
        if 'locator_json' in claim_cols:
            missing = [dict(row) for row in conn.execute(
                "SELECT claim_id, article_key FROM claims WHERE locator_json IN ('{}','')")]
            checks.append(_check('claim.missing_locator', 'WARN',
                                 'claims without a locator', len(missing),
                                 _samples(missing, ['claim_id', 'article_key'])))
        if _table(conn, 'claim_evidence'):
            invalid = [dict(row) for row in conn.execute(
                '''SELECT c.claim_id, c.article_key FROM claims c
                   WHERE NOT EXISTS (
                     SELECT 1 FROM claim_evidence ce JOIN evidences v USING(evidence_id)
                     WHERE ce.claim_id=c.claim_id AND trim(v.source_id)<>''
                       AND trim(v.quote)<>'' AND v.locator_json NOT IN ('{}',''))''')]
            checks.append(_check('claim.without_valid_evidence', 'ERROR',
                                 'claims without a valid source/quote/locator link', len(invalid),
                                 _samples(invalid, ['claim_id', 'article_key'])))
            mismatch = [dict(row) for row in conn.execute(
                '''SELECT c.claim_id, c.article_key AS claim_article, v.evidence_id,
                          v.article_key AS evidence_article
                   FROM claims c JOIN claim_evidence ce USING(claim_id)
                   JOIN evidences v USING(evidence_id)
                   WHERE c.article_key<>'' AND v.article_key<>''
                     AND c.article_key<>v.article_key''')]
            checks.append(_check('claim.evidence_article_mismatch', 'ERROR',
                                 'claim and linked evidence point at different articles', len(mismatch),
                                 _samples(mismatch, ['claim_id', 'claim_article', 'evidence_id', 'evidence_article'])))
            orphan = [dict(row) for row in conn.execute(
                '''SELECT ce.claim_id, ce.evidence_id FROM claim_evidence ce
                   LEFT JOIN claims c USING(claim_id)
                   LEFT JOIN evidences v USING(evidence_id)
                   WHERE c.claim_id IS NULL OR v.evidence_id IS NULL''')]
            checks.append(_check('claim_evidence.orphan', 'ERROR',
                                 'claim_evidence rows with a missing claim or evidence', len(orphan),
                                 _samples(orphan, ['claim_id', 'evidence_id'])))
        if 'extractor' in claim_cols and 'verification_state' in claim_cols:
            skeleton_period = [dict(row) for row in conn.execute(
                "SELECT claim_id, period FROM claims WHERE extractor='skeleton' AND period<>''")]
            checks.append(_check('claim.skeleton_with_period', 'ERROR',
                                 'skeleton claims carry a fact period', len(skeleton_period),
                                 _samples(skeleton_period, ['claim_id', 'period'])))
            skeleton_verified = [dict(row) for row in conn.execute(
                "SELECT claim_id, verification_state FROM claims "
                "WHERE extractor='skeleton' AND verification_state='verified'")]
            checks.append(_check('claim.skeleton_verified', 'ERROR',
                                 'skeleton claims were marked verified', len(skeleton_verified),
                                 _samples(skeleton_verified, ['claim_id', 'verification_state'])))
    return checks


def _event_checks(conn):
    checks, info = [], {}
    if not _table(conn, 'events') or not _table(conn, 'event_articles'):
        return [_check('event.tables_absent', 'ERROR', 'event tables are missing', 1)], info
    if _table(conn, 'articles'):
        without_event = [dict(row) for row in conn.execute(
            '''SELECT a.article_key, a.title FROM articles a
               LEFT JOIN event_articles ea USING(article_key)
               WHERE ea.article_key IS NULL''')]
        if _table(conn, 'analyses'):
            analysed = [row for row in without_event
                        if conn.execute('SELECT 1 FROM analyses WHERE article_key=?',
                                        (row['article_key'],)).fetchone()]
            unanalysed = [row for row in without_event if row not in analysed]
            checks.append(_check('event.analysed_article_without_event', 'ERROR',
                                 'analysed articles not assigned to any event', len(analysed),
                                 _samples(analysed, ['article_key', 'title'])))
            checks.append(_check('event.unanalysed_article_without_event', 'INFO',
                                 'articles not analysed and therefore not assigned to an event',
                                 len(unanalysed), _samples(unanalysed, ['article_key', 'title'])))
        else:
            checks.append(_check('event.article_without_event', 'WARN',
                                 'articles not assigned to any event', len(without_event),
                                 _samples(without_event, ['article_key', 'title'])))
    if _table(conn, 'articles'):
        orphan = [dict(row) for row in conn.execute(
            '''SELECT ea.event_id, ea.article_key FROM event_articles ea
               LEFT JOIN events e USING(event_id)
               LEFT JOIN articles a USING(article_key)
               WHERE e.event_id IS NULL OR a.article_key IS NULL''')]
        orphan_label = 'event_articles rows with a missing event or article'
    else:
        orphan = [dict(row) for row in conn.execute(
            '''SELECT ea.event_id, ea.article_key FROM event_articles ea
               LEFT JOIN events e USING(event_id) WHERE e.event_id IS NULL''')]
        orphan_label = 'event_articles rows with a missing event'
    checks.append(_check('event.orphan_membership', 'ERROR', orphan_label, len(orphan),
                         _samples(orphan, ['event_id', 'article_key'])))
    if _table(conn, 'event_links'):
        candidates = conn.execute(
            "SELECT COUNT(*) FROM event_links WHERE relation=?", (linking.REL_EVENT_CANDIDATE,)).fetchone()[0]
        accepted = [dict(row) for row in conn.execute(
            "SELECT link_id, left_key, right_key, status FROM event_links "
            "WHERE relation=? AND status='accepted'", (linking.REL_EVENT_CANDIDATE,))]
        info['event_candidate_links'] = candidates
        info['accepted_event_candidate_links'] = len(accepted)
        checks.append(_check('event.candidate_links', 'INFO',
                             'event pairs recorded as candidates, not merged', candidates))
        checks.append(_check('event.candidate_accepted_as_relation', 'WARN',
                             'event candidates with accepted status; accepted is not a merge and must not be read as one',
                             len(accepted), _samples(accepted, ['link_id', 'left_key', 'right_key', 'status'])))
    event_total = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    info['event_total'] = event_total
    if _table(conn, 'evidences'):
        rows = [dict(row) for row in conn.execute(
            '''SELECT ea.event_id, v.article_key, v.evidence_id, v.source_id, v.source_family,
                      v.independence, v.syndication_group
               FROM event_articles ea JOIN evidences v USING(article_key)''')]
        by_event = {}
        for row in rows:
            by_event.setdefault(row['event_id'], []).append(row)
        profiles = {event_id: linking.source_independence(items)
                    for event_id, items in by_event.items()}
        info['events'] = len(profiles)
        info['events_without_evidence'] = event_total - len(profiles)
        empty_events = [dict(row) for row in conn.execute(
            '''SELECT e.event_id, e.title_norm FROM events e
               WHERE NOT EXISTS (
                 SELECT 1 FROM event_articles ea JOIN evidences v USING(article_key)
                 WHERE ea.event_id=e.event_id) ORDER BY e.event_id''')]
        checks.append(_check('event.event_without_evidence', 'WARN',
                             'events with no evidence rows', len(empty_events),
                             _samples(empty_events, ['event_id', 'title_norm'])))
        info['events_with_multiple_source_families'] = sum(
            1 for profile in profiles.values() if profile['source_family_count'] > 1)
        info['events_with_independent_corroboration'] = sum(
            1 for profile in profiles.values() if profile['independent_corroboration'])
        info['events_unknown_independence'] = sum(
            1 for profile in profiles.values() if profile['independence_status'] == 'UNKNOWN')
        info['events_partial_independence'] = sum(
            1 for profile in profiles.values() if profile['independence_status'] == 'PARTIAL')
        info['unknown_family_evidences'] = sum(
            1 for row in rows if not str(row.get('source_family') or '').strip())
        info['unknown_independence_evidences'] = sum(
            1 for row in rows if (row.get('independence') or 'unknown') not in linking.CORROBORATING)
        info['syndicated_evidences'] = sum(
            1 for row in rows if str(row.get('syndication_group') or '').strip())
    return checks, info


def _entity_checks(conn):
    checks, info, limitations = [], {}, []
    if not _table(conn, 'entity_mentions'):
        return [_check('entity.mentions_table_absent', 'WARN',
                       'entity_mentions table is absent; entity layer is not deployed', 1)], info, limitations
    cols = _columns(conn, 'entity_mentions')
    total = conn.execute('SELECT COUNT(*) FROM entity_mentions').fetchone()[0]
    info['mentions'] = total
    info['mention_columns'] = sorted(cols)
    if 'article_key' in cols:
        missing_article = [dict(row) for row in conn.execute(
            "SELECT mention_id, target_kind, target_key, article_key FROM entity_mentions "
            "WHERE article_key='' OR article_key IS NULL")]
        checks.append(_check('entity.mention_without_article', 'ERROR',
                             'mentions cannot be traced to an article', len(missing_article),
                             _samples(missing_article, ['mention_id', 'target_kind', 'target_key', 'article_key'])))
    if 'locator_json' in cols:
        missing_locator = [dict(row) for row in conn.execute(
            "SELECT mention_id, target_kind, target_key FROM entity_mentions "
            "WHERE locator_json IN ('{}','')")]
        checks.append(_check('entity.mention_without_locator', 'ERROR',
                             'mentions without a locator', len(missing_locator),
                             _samples(missing_locator, ['mention_id', 'target_kind', 'target_key'])))
    if 'target_kind' in cols and 'target_key' in cols:
        if _table(conn, 'evidences'):
            missing_evidence = [dict(row) for row in conn.execute(
                '''SELECT m.mention_id, m.target_key FROM entity_mentions m
                   LEFT JOIN evidences v ON v.evidence_id=m.target_key
                   WHERE m.target_kind='evidence' AND v.evidence_id IS NULL''')]
            checks.append(_check('entity.mention_missing_evidence', 'ERROR',
                                 'evidence mentions whose evidence_id does not exist', len(missing_evidence),
                                 _samples(missing_evidence, ['mention_id', 'target_key'])))
        if _table(conn, 'claims'):
            missing_claim = [dict(row) for row in conn.execute(
                '''SELECT m.mention_id, m.target_key FROM entity_mentions m
                   LEFT JOIN claims c ON c.claim_id=m.target_key
                   WHERE m.target_kind='claim' AND c.claim_id IS NULL''')]
            checks.append(_check('entity.mention_missing_claim', 'ERROR',
                                 'claim mentions whose claim_id does not exist', len(missing_claim),
                                 _samples(missing_claim, ['mention_id', 'target_key'])))
    if 'occurrence_count' in cols:
        bad_count = [dict(row) for row in conn.execute(
            "SELECT mention_id, occurrence_count FROM entity_mentions WHERE occurrence_count<1")]
        checks.append(_check('entity.mention_occurrence_count', 'ERROR',
                             'mentions with an invalid occurrence_count', len(bad_count),
                             _samples(bad_count, ['mention_id', 'occurrence_count'])))
        limitations.append('occurrence_count counts repeated mentions in one source/method; '
                           'only the first occurrence locator is stored.')
    if not _table(conn, 'entity_relations'):
        checks.append(_check('entity.relations_table_absent', 'WARN',
                             'entity_relations table is absent; entity relations are not deployed', 1))
        return checks, info, limitations
    relation_cols = _columns(conn, 'entity_relations')
    relation_total = conn.execute('SELECT COUNT(*) FROM entity_relations').fetchone()[0]
    info['entity_relations'] = relation_total
    if 'locator_json' in relation_cols:
        missing_locator = [dict(row) for row in conn.execute(
            "SELECT relation_id, relation_type, subject_entity_id FROM entity_relations "
            "WHERE locator_json IN ('{}','')")]
        checks.append(_check('entity.relation_without_locator', 'ERROR',
                             'entity relations without a locator', len(missing_locator),
                             _samples(missing_locator, ['relation_id', 'relation_type', 'subject_entity_id'])))
    if 'evidence_id' in relation_cols and 'article_key' in relation_cols:
        missing_source = [dict(row) for row in conn.execute(
            "SELECT relation_id, relation_type, subject_entity_id FROM entity_relations "
            "WHERE evidence_id='' AND article_key=''")]
        checks.append(_check('entity.relation_without_evidence_or_article', 'ERROR',
                             'entity relations with neither evidence nor article', len(missing_source),
                             _samples(missing_source, ['relation_id', 'relation_type', 'subject_entity_id'])))
    if 'verification_state' in relation_cols:
        verified = [dict(row) for row in conn.execute(
            "SELECT relation_id, relation_type, verification_state FROM entity_relations "
            "WHERE verification_state IN ('verified','confirmed')")]
        checks.append(_check('entity.relation_verified', 'WARN',
                             'entity relations marked verified/confirmed; verify the basis before trusting',
                             len(verified), _samples(verified, ['relation_id', 'relation_type', 'verification_state'])))
        info['entity_relations_unverified'] = conn.execute(
            "SELECT COUNT(*) FROM entity_relations WHERE verification_state='unverified'").fetchone()[0]
    if 'relation_type' in relation_cols:
        affected = conn.execute(
            "SELECT COUNT(*) FROM entity_relations WHERE relation_type=?",
            (linking.REL_AFFECTED_BY,)).fetchone()[0]
        checks.append(_check('entity.affected_by_generated', 'WARN',
                             'AFFECTED_BY rows exist; this relation must have explicit factual evidence',
                             affected))
        published = conn.execute(
            "SELECT COUNT(*) FROM entity_relations WHERE relation_type=?",
            (linking.REL_PUBLISHED_BY,)).fetchone()[0]
        if published:
            checks.append(_check('entity.published_by_present', 'WARN',
                                 'PUBLISHED_BY rows exist; source_name alone is not publisher evidence',
                                 published))
    return checks, info, limitations


def _chains(conn, limit=10):
    if not _table(conn, 'articles'):
        return []
    article_cols = _columns(conn, 'articles')
    source_expr = 'a.source_id' if 'source_id' in article_cols else "'' AS source_id"
    rows = [dict(row) for row in conn.execute(
        f'''SELECT a.article_key, {source_expr}, a.source_name,
                  ea.event_id, v.evidence_id, v.source_family,
                  ce.claim_id, c.extractor, c.period
           FROM articles a
           LEFT JOIN event_articles ea USING(article_key)
           LEFT JOIN evidences v USING(article_key)
           LEFT JOIN claim_evidence ce USING(evidence_id)
           LEFT JOIN claims c USING(claim_id)
           ORDER BY a.article_key, v.evidence_id, ce.claim_id''')]
    chains = {}
    for row in rows:
        item = chains.setdefault(row['article_key'], {
            'article_key': row['article_key'], 'source_id': row['source_id'],
            'source_name': row['source_name'], 'event_id': '', 'evidence_id': '',
            'source_family': '', 'claim_id': '', 'claim_extractor': '', 'claim_period': '',
            'mentions': 0, 'entity_relations': 0})
        for key, value in (('event_id', row['event_id']), ('evidence_id', row['evidence_id']),
                           ('source_family', row['source_family']), ('claim_id', row['claim_id']),
                           ('claim_extractor', row['extractor']), ('claim_period', row['period'])):
            if value and not item[key]:
                item[key] = value
    for article_key, item in chains.items():
        if _table(conn, 'entity_mentions') and 'article_key' in _columns(conn, 'entity_mentions'):
            item['mentions'] = conn.execute(
                'SELECT COUNT(*) FROM entity_mentions WHERE article_key=?', (article_key,)).fetchone()[0]
        if _table(conn, 'entity_relations') and 'article_key' in _columns(conn, 'entity_relations'):
            item['entity_relations'] = conn.execute(
                'SELECT COUNT(*) FROM entity_relations WHERE article_key=?', (article_key,)).fetchone()[0]
        missing = []
        for key, label in (('source_id', 'source_id'), ('event_id', 'event'),
                           ('evidence_id', 'evidence'), ('claim_id', 'claim'),
                           ('mentions', 'entity_mention')):
            if not item[key]:
                missing.append(label)
        item['missing'] = missing
        item['complete'] = not missing
    ordered = sorted(chains.values(),
                     key=lambda item: (not item['complete'], len(item['missing']), item['article_key']))
    return ordered[:limit]


def audit(db_path, source_registry=None, lineage_registry=None):
    """Return a read-only report. The database is opened with mode=ro; no migration."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    conn = _connect(path)
    try:
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
        sources = _load_sources(source_registry)
        source_checks, source_info = _source_checks(conn, sources, lineage_registry)
        claim_checks = _evidence_claim_checks(conn)
        event_checks, event_info = _event_checks(conn)
        entity_checks, entity_info, limitations = _entity_checks(conn)
        checks = source_checks + claim_checks + event_checks + entity_checks
        errors = [item for item in checks if item['severity'] == 'ERROR' and item['count'] > 0]
        warnings = [item for item in checks if item['severity'] == 'WARN' and item['count'] > 0]
        status = 'FAIL' if errors else ('PARTIAL' if warnings else 'PASS')
        return {
            'db': str(path),
            'schema': {'user_version': version, 'tables': tables},
            'status': status,
            'checks': checks,
            'source': source_info,
            'event': event_info,
            'entity': entity_info,
            'limitations': limitations + [
                'source_name is a feed label, not a verified publisher identity.',
                'PUBLISHED_BY is not generated from source_name; no explicit publisher identity exists in the current registry.',
                'INGESTED_FROM is represented by articles.source_id/source_name, not a separate relation row.',
                'SOURCE_FAMILY is represented by evidences.source_family; SYNDICATED_FROM only by a recorded syndication_group.',
                'A mention is not AFFECTED_BY or a business relationship.',
                'event_candidate rows are candidates; they do not merge events.',
            ],
            'chains': _chains(conn),
        }
    finally:
        conn.close()
