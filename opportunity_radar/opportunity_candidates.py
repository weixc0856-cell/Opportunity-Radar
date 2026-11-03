"""Read-only B-lane seed mapping.

This module turns stored B-lane analysis records into reviewable seed candidates.
It never creates Opportunities, links, hypotheses or revisions, and it never writes
the source database. Output files are written only to the requested report directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path

from . import lineage, linking
from .unified import evidence_integrity_problems, stable_id
from .unified import UnifiedStore

SEED_CLASSES = ('EVIDENCE_BACKED_SEED', 'SIGNAL_ONLY_SEED', 'INSUFFICIENT_MAPPING')
REVIEW_STATUSES = ('pending', 'accepted_as_seed', 'rejected', 'needs_more_evidence',
                   'duplicate_suspected')
def _connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _source_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _normalise(value):
    text = re.sub(r'[^0-9a-z一-鿿]+', ' ', str(value or '').lower())
    return re.sub(r'\s+', ' ', text).strip()


def _candidate_id(article_key, event_id):
    return stable_id('opc-', article_key, event_id or '')


def _cluster_id(parts):
    return stable_id('opcl-', *[_normalise(part) for part in parts])


def _event_evidence_status(profile):
    return profile.get('evidence_status') if profile else 'NO_EVENT'


def _classify(profile, evidence_refs, claims, event_id):
    if not event_id or profile is None:
        return 'INSUFFICIENT_MAPPING', ['event_or_profile_missing']
    if evidence_refs and not any(item['valid'] for item in evidence_refs):
        return 'INSUFFICIENT_MAPPING', ['evidence_present_but_invalid']
    if evidence_refs and any(item['valid'] for item in evidence_refs) and not claims:
        return 'INSUFFICIENT_MAPPING', ['claim_missing']
    status = profile.get('evidence_status')
    if status == 'EVIDENCE_BACKED':
        return 'EVIDENCE_BACKED_SEED', []
    if status == 'NO_EVIDENCE':
        return 'SIGNAL_ONLY_SEED', ['no_valid_evidence']
    if status == 'INSUFFICIENT_EVIDENCE':
        return 'INSUFFICIENT_MAPPING', ['insufficient_event_evidence']
    return 'INSUFFICIENT_MAPPING', ['unknown_event_evidence_status']


def _evidence_refs(conn, article_key):
    refs = []
    for row in conn.execute('SELECT * FROM evidences WHERE article_key=? ORDER BY evidence_id',
                            (article_key,)):
        item = dict(row)
        problems = evidence_integrity_problems(item)
        refs.append({'evidence_id': item.get('evidence_id') or '',
                     'source_id': item.get('source_id') or '',
                     'source_family': item.get('source_family') or '',
                     'quote': item.get('quote') or '',
                     'locator_json': item.get('locator_json') or '{}',
                     'valid': not problems, 'problems': problems})
    return refs


def _claim_refs(conn, article_key):
    return [dict(row) for row in conn.execute(
        'SELECT claim_id,verification_state,extractor,locator_json FROM claims '
        'WHERE article_key=? ORDER BY claim_id', (article_key,))]


def _entity_refs(conn, article_key):
    cols = {row[1] for row in conn.execute('PRAGMA table_info(entity_mentions)')}
    if not cols:
        return []
    locator = "m.locator_json" if 'locator_json' in cols else "'{}'"
    return [dict(row) for row in conn.execute(
        f'''SELECT m.mention_id,m.entity_id,m.target_kind,m.target_key,m.matched_text,
                   m.confidence,{locator} AS locator_json,e.canonical_name,e.entity_type
            FROM entity_mentions m LEFT JOIN entities e USING(entity_id)
            WHERE m.target_kind='article' AND m.target_key=? ORDER BY m.mention_id''',
        (article_key,))]


def _identity(analysis, classification, entities):
    names = sorted({str(item.get('canonical_name') or '').strip()
                    for item in entities if item.get('canonical_name')})
    subject = names[0] if len(names) == 1 else ''
    problem_hint = str(analysis.get('pain_point') or '').strip()
    buyer_hint = str(classification.get('buyer_type') or '').strip()
    if buyer_hint.lower() in ('unknown', 'none', 'n/a'):
        buyer_hint = ''
    kind_hint = str(classification.get('signal_type') or classification.get('article_type') or '').strip()
    # A confirmed problem is always required; model pain text is only a hint.
    missing = ['missing_confirmed_problem', 'missing_buyer']
    if not subject:
        missing.append('missing_subject')
    if not problem_hint:
        missing.append('missing_problem')
    if not buyer_hint:
        missing.append('missing_buyer_hint')
    if not kind_hint:
        missing.append('missing_kind')
    # pain_point and title are model output, not a confirmed problem identity. Therefore
    # no canonical key is generated from them; a human must supply/confirm the problem.
    completeness = 'complete' if not missing else 'incomplete'
    canonical = ''
    canonical_status = 'blocked_missing_confirmed_problem'
    return {
        'subject': subject,
        'problem': '',
        'buyer_scope': '',
        'opportunity_kind': '',
        'problem_hint': problem_hint,
        'buyer_scope_hint': buyer_hint,
        'opportunity_kind_hint': kind_hint,
        'identity_completeness': completeness,
        'identity_missing': missing,
        'canonical_key_candidate': canonical,
        'canonical_key_status': canonical_status,
    }


def _lineage_for(source_ids, registry):
    result = []
    for source_id in sorted({str(item or '') for item in source_ids if str(item or '')}):
        row = registry.get(source_id)
        result.append({'source_id': source_id,
                       'review_status': (row or {}).get('review_status', 'unknown') or 'unknown',
                       'source_family': (row or {}).get('source_family', '') or '',
                       'independence': (row or {}).get('independence', 'unknown') or 'unknown',
                       'syndication_group': (row or {}).get('syndication_group', '') or ''})
    return result


def build_candidates(db_path):
    """Build deterministic B candidate records from a read-only database connection."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    conn = _connect(path)
    uni = UnifiedStore(str(path), read_only=True)
    registry = lineage.load()
    rows = [dict(row) for row in conn.execute(
        '''SELECT a.article_key,a.title,a.url,a.source_name,a.published,an.result_json,
                  ea.event_id
           FROM articles a JOIN analyses an USING(article_key)
           LEFT JOIN event_articles ea USING(article_key)
           ORDER BY a.article_key''')]
    candidates = []
    for row in rows:
        try:
            payload = json.loads(row['result_json'] or '{}')
        except (TypeError, ValueError):
            continue
        scoring = payload.get('scoring') or {}
        if scoring.get('lane') != 'B':
            continue
        meta = payload.get('meta') or {}
        analysis = payload.get('analysis') or {}
        classification = scoring.get('classification') or {}
        event_id = row.get('event_id') or ''
        profile = None
        if event_id:
            try:
                profile = linking.event_profile(uni, event_id)
            except Exception:
                profile = None
        evidence = _evidence_refs(conn, row['article_key'])
        claims = _claim_refs(conn, row['article_key'])
        entities = _entity_refs(conn, row['article_key'])
        source_ids = [meta.get('source_id')] + [item['source_id'] for item in evidence]
        source_id = str(meta.get('source_id') or (evidence[0]['source_id'] if evidence else '') or '')
        status, reasons = _classify(profile, evidence, claims, event_id)
        identity = _identity(analysis, classification, entities)
        lineage_rows = _lineage_for(source_ids, registry)
        source_families = profile.get('source_families', []) if profile else []
        syndication = profile.get('syndication_groups', []) if profile else []
        independence = profile or {}
        flags = list(reasons)
        flags += identity['identity_missing']
        if not event_id:
            flags.append('event_missing')
        if not evidence:
            flags.append('evidence_absent')
        if not claims:
            flags.append('claim_absent')
        if any(claim.get('verification_state') != 'verified' for claim in claims):
            flags.append('unverified_claim')
        if any(item.get('review_status') != 'verified' for item in lineage_rows):
            flags.append('unverified_lineage')
        cluster = ''
        if identity['subject'] and identity['problem_hint'] and identity['buyer_scope_hint']:
            cluster = _cluster_id((identity['subject'], identity['problem_hint'],
                                   identity['buyer_scope_hint'],
                                   identity['opportunity_kind_hint']))
        missing_dimensions = {
            'missing_buyer': 'missing_buyer' in identity['identity_missing'],
            'missing_independent_sourcing': (any(item.get('review_status') != 'verified'
                                                  for item in lineage_rows)
                                              or not (profile or {}).get('independent_corroboration', False)),
            'missing_event': not event_id,
            'missing_evidence': not evidence,
            'missing_claim': not claims,
            'incomplete_identity': identity['identity_completeness'] != 'complete',
        }
        candidates.append({
            'candidate_id': _candidate_id(row['article_key'], event_id),
            'article_key': row['article_key'],
            'article_title': row['title'],
            'article_url': row['url'],
            'source_id': source_id,
            'source_name': row['source_name'],
            'published': row['published'],
            'event_id': event_id,
            'event_evidence_status': _event_evidence_status(profile),
            'seed_class': status,
            'b_status': scoring.get('status') or '',
            'b_score': scoring.get('score'),
            'b_evidence_state': scoring.get('evidence_state') or '',
            'classification': classification,
            'identity': identity,
            'evidence_refs': evidence,
            'claim_refs': claims,
            'entity_refs': entities,
            'source_families': source_families,
            'syndication_groups': syndication,
            'lineage': lineage_rows,
            'source_independence': {
                'independent_source_units': independence.get('independent_source_units', 0),
                'declared_only_evidence_count': independence.get('declared_only_evidence_count', 0),
                'independence_status': independence.get('independence_status', 'INSUFFICIENT_DATA'),
                'independent_corroboration': independence.get('independent_corroboration', False),
            },
            'daily_display_status': scoring.get('status') or '',
            'displayed_by_status': scoring.get('status') in ('priority', 'watch'),
            'daily_display': ('status_eligible' if scoring.get('status') in ('priority', 'watch')
                              else 'not_shown_by_status'),
            'daily_display_confidence': 'status_only_source_cap_not_replayed',
            'source_cap_replayed': False,
            'duplicate_cluster_candidate': cluster,
            'review_status': 'pending',
            'review_flags': sorted(set(flags)),
            'missing_dimensions': missing_dimensions,
            'review_notes': [],
            'cannot_form_reason': reasons,
        })
    # A cluster id is only assigned when at least two candidates share it. No candidate
    # is merged or deleted.
    counts = Counter(item['duplicate_cluster_candidate'] for item in candidates
                     if item['duplicate_cluster_candidate'])
    for item in candidates:
        cluster = item['duplicate_cluster_candidate']
        if cluster and counts[cluster] > 1:
            item['review_flags'] = sorted(set(item['review_flags'] + ['duplicate_suspected']))
        else:
            item['duplicate_cluster_candidate'] = ''
    candidates.sort(key=lambda item: (item['candidate_id'], item['article_key']))
    stats = {
        'b_candidates': len(candidates),
        'seed_classes': dict(Counter(item['seed_class'] for item in candidates)),
        'statuses': dict(Counter(item['b_status'] for item in candidates)),
        'evidence_backed': sum(1 for item in candidates
                               if item['seed_class'] == 'EVIDENCE_BACKED_SEED'),
        'signal_only': sum(1 for item in candidates
                           if item['seed_class'] == 'SIGNAL_ONLY_SEED'),
        'insufficient_mapping': sum(1 for item in candidates
                                    if item['seed_class'] == 'INSUFFICIENT_MAPPING'),
        'with_evidence': sum(1 for item in candidates if item['evidence_refs']),
        'with_claims': sum(1 for item in candidates if item['claim_refs']),
        'with_entities': sum(1 for item in candidates if item['entity_refs']),
        'identity_complete': sum(1 for item in candidates
                                 if item['identity']['identity_completeness'] == 'complete'),
        'canonical_key_candidates': sum(1 for item in candidates
                                        if item['identity']['canonical_key_candidate']),
        'duplicate_clusters': len([key for key, count in counts.items() if count > 1]),
        'declared_only_candidates': sum(1 for item in candidates
                                        if any(line['review_status'] != 'verified'
                                               for line in item['lineage'])),
        'no_evidence_reason': sum(1 for item in candidates
                                  if 'no_valid_evidence' in item['cannot_form_reason']),
        'status_eligible_for_daily': sum(1 for item in candidates
                                         if item['daily_display'] == 'status_eligible'),
        'missing_buyer': sum(1 for item in candidates
                             if item['missing_dimensions']['missing_buyer']),
        'missing_independent_sourcing': sum(1 for item in candidates
                                            if item['missing_dimensions']['missing_independent_sourcing']),
        'missing_event': sum(1 for item in candidates
                             if item['missing_dimensions']['missing_event']),
        'missing_evidence': sum(1 for item in candidates
                                if item['missing_dimensions']['missing_evidence']),
        'missing_claim': sum(1 for item in candidates
                             if item['missing_dimensions']['missing_claim']),
        'daily_display_source_cap_replayed': 0,
    }
    conn.close()
    opportunity_rows = _opportunity_count(path)
    return {
        'schema_version': 1,
        'source_db': str(path),
        'source_sha256': _source_hash(path),
        'read_only': True,
        'opportunity_table': 'present' if opportunity_rows is not None else 'absent',
        'opportunity_rows': opportunity_rows,
        'review_statuses': list(REVIEW_STATUSES),
        'stats': stats,
        'candidates': candidates,
    }


def _opportunity_count(path):
    conn = _connect(path)
    try:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='opportunities'").fetchone()
        if not row:
            return None
        return conn.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0]
    finally:
        conn.close()


def _markdown(report):
    lines = ['# B Opportunity Seed Candidates', '',
             f"- source_db: `{report['source_db']}`",
             f"- source_sha256: `{report['source_sha256']}`",
             f"- read_only: `{str(report['read_only']).lower()}`",
             f"- opportunity_table: `{report['opportunity_table']}`",
             f"- opportunity_rows: `{report['opportunity_rows']}`", '',
             '## Statistics', '']
    for key, value in report['stats'].items():
        lines.append(f"- {key}: {value}")
    lines += ['', '## Candidates', '']
    for item in report['candidates']:
        lines += [f"### {item['candidate_id']} · {item['seed_class']}", '',
                  f"- article: `{item['article_key']}` · {item['article_title']}",
                  f"- source: `{item['source_id'] or 'unknown'}` · {item['source_name']}",
                  f"- event: `{item['event_id'] or 'NONE'}` · evidence `{item['event_evidence_status']}`",
                  f"- B: status `{item['b_status']}` · score `{item['b_score']}` · "
                  f"evidence state `{item['b_evidence_state']}`",
                  f"- identity: {json.dumps(item['identity'], ensure_ascii=False)}",
                  f"- evidence: {', '.join(ref['evidence_id'] for ref in item['evidence_refs']) or 'none'}",
                  f"- claims: {', '.join(ref['claim_id'] + ':' + ref['verification_state'] for ref in item['claim_refs']) or 'none'}",
                  f"- entities: {', '.join(ref.get('canonical_name', '') for ref in item['entity_refs']) or 'none'}",
                  f"- source independence: {json.dumps(item['source_independence'], ensure_ascii=False)}",
                  f"- daily display: `{item['daily_display']}` · `{item['daily_display_confidence']}`",
                  f"- duplicate cluster: `{item['duplicate_cluster_candidate'] or 'none'}`",
                  f"- review: `{item['review_status']}` · flags {', '.join(item['review_flags']) or 'none'}",
                  f"- cannot form reason: {', '.join(item['cannot_form_reason']) or 'none'}", '']
    return '\n'.join(lines).rstrip() + '\n'


def _write_atomic(path, text):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def write_outputs(report, output_dir='reports', fmt='both'):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / 'opportunity-candidates.json'
    md_path = out / 'opportunity-candidates.md'
    json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if fmt in ('both', 'json'):
        _write_atomic(json_path, json_text)
    if fmt in ('both', 'markdown'):
        _write_atomic(md_path, _markdown(report))
    return {'json': str(json_path) if fmt in ('both', 'json') else '',
            'markdown': str(md_path) if fmt in ('both', 'markdown') else ''}
