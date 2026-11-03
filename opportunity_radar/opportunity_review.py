"""Explicit, manifest-driven Opportunity creation.

This module is the Batch 12 review boundary. It reads a manifest and an existing B-candidate
report, validates every reference against the target database, previews proposed creations,
and only writes when the CLI is given both ``--apply`` and an isolated schema-v9 database.

It never discovers candidates, fills identity fields, merges Opportunities, or migrates a
database. Candidate mapping remains in ``opportunity_candidates.py``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from . import opportunity, opportunity_audit
from .unified import UnifiedStore, evidence_integrity_problems

MANIFEST_VERSION = 1
REVIEW_STATUSES = ('pending', 'accepted_as_seed', 'rejected', 'needs_more_evidence',
                   'duplicate_suspected')
PROMOTION_DECISIONS = ('none', 'create_opportunity')
REVIEW_MODES = ('human', 'ai_assisted')
ENTITY_ROLES = ('subject', 'buyer', 'competitor', 'affected', 'context')
EVIDENCE_ROLES = ('fact_basis', 'context')
CLAIM_ROLES = ('unverified_claim', 'fact_basis')
REPORT_PATH = Path('reports/opportunity-candidates.json')
RESULT_JSON = 'opportunity-review-result.json'
RESULT_MD = 'opportunity-review-result.md'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_DB = PROJECT_ROOT / 'data/opportunity_radar.sqlite3'
FORMAL_ALLOWLIST = PROJECT_ROOT / 'data/archive/p0-batch12-validation/opportunity_radar.sqlite3'


class ManifestError(ValueError):
    """A manifest cannot be parsed or applied as requested."""


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise ManifestError(f'file not found: {path}')
    except (OSError, ValueError) as exc:
        raise ManifestError(f'cannot read JSON {path}: {exc}')


def _sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        raise ManifestError(f'file not found: {path}')


def _connect_ro(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _schema_version(path):
    if not Path(path).exists():
        raise ManifestError(f'database not found: {path}')
    conn = _connect_ro(path)
    try:
        return conn.execute('PRAGMA user_version').fetchone()[0]
    finally:
        conn.close()


def _table(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _is_production(path):
    """Resolve and compare inode where possible; a string-prefix check is not enough."""
    candidate = Path(path).resolve()
    production = PRODUCTION_DB.resolve()
    if candidate == production:
        return True
    try:
        return candidate.exists() and production.exists() and os.path.samefile(candidate, production)
    except OSError:
        return False


def _assert_allowed_target(db_path, allowed_paths=None):
    """Fail closed unless the exact, non-symlinked target is in the explicit allowlist.

    The allowlist is an internal/test capability. The formal CLI never passes an override.
    """
    allowed = tuple(allowed_paths or (FORMAL_ALLOWLIST,))
    if not allowed:
        raise ManifestError('no allowed apply target is configured')
    raw = Path(db_path)
    if any(part == '..' for part in raw.parts):
        raise ManifestError('apply target contains path traversal')
    try:
        requested = raw.resolve(strict=True)
    except OSError:
        raise ManifestError(f'apply target does not exist or cannot be resolved: {db_path}')
    if not requested.is_file():
        raise ManifestError(f'apply target is not a regular file: {db_path}')
    if raw.is_symlink() or any(parent.is_symlink() for parent in raw.parents):
        raise ManifestError('apply target must not be a symlink or inside a symlink')
    if _is_production(requested):
        raise ManifestError('apply refuses the production database path or a hardlink to it')
    requested_abs = Path(os.path.abspath(raw))
    matched = False
    for item in allowed:
        allowed_abs = Path(os.path.abspath(item))
        if requested_abs == allowed_abs:
            if not allowed_abs.exists() or not allowed_abs.is_file():
                raise ManifestError(f'allowlist target is missing or not a file: {allowed_abs}')
            matched = True
            break
    if not matched:
        raise ManifestError(f'apply target is outside the explicit allowlist: {db_path}')
    return str(requested_abs)


def _norm(value):
    text = re.sub(r'[^0-9a-z一-鿿]+', ' ', str(value or '').lower())
    return re.sub(r'\s+', ' ', text).strip()


def _err(code, message, candidate_id='', field=''):
    item = {'code': code, 'message': message}
    if candidate_id:
        item['candidate_id'] = candidate_id
    if field:
        item['field'] = field
    return item


def _candidate_index(report):
    candidates = report.get('candidates') if isinstance(report, dict) else None
    if not isinstance(candidates, list):
        raise ManifestError('candidate report has no candidates list')
    index = {}
    for item in candidates:
        if isinstance(item, dict) and item.get('candidate_id'):
            index[item['candidate_id']] = item
    return index


def _ref_id(ref, kind):
    if isinstance(ref, str):
        return ref.strip()
    if isinstance(ref, dict):
        return str(ref.get(f'{kind}_id') or ref.get('id') or '').strip()
    return ''


def _parse_refs(raw, kind, default_role, candidate_id):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError(f'{candidate_id}: {kind}_refs must be a list')
    parsed = []
    for ref in raw:
        ref_id = _ref_id(ref, kind)
        if not ref_id:
            raise ManifestError(f'{candidate_id}: {kind}_ref has no {kind}_id')
        role = ref.get('role', default_role) if isinstance(ref, dict) else default_role
        if not isinstance(role, str) or not role:
            raise ManifestError(f'{candidate_id}: {kind}_ref has invalid role')
        support = ref.get('support', 'context') if isinstance(ref, dict) else 'context'
        parsed.append({'id': ref_id, 'role': role, 'support': support})
    return parsed


def _existing_action(conn, canonical_key, identity, link_specs):
    """Return (action, detail) for an existing canonical key.

    ``create`` means the key is free; ``idempotent`` means the existing Opportunity and its
    first revision exactly match this request; ``conflict`` is never merged or overwritten.
    """
    existing = conn.execute('SELECT * FROM opportunities WHERE canonical_key=?',
                            (canonical_key,)).fetchone()
    if not existing:
        return 'create', ''
    expected = {
        'problem_statement': str(identity['problem_statement']).strip(),
        'buyer_scope': str(identity.get('buyer_scope') or '').strip(),
        'opportunity_kind': str(identity['opportunity_kind']).strip(),
    }
    actual = {key: str(existing[key] or '').strip() for key in expected}
    if actual != expected:
        return 'conflict', 'existing Opportunity has different identity fields'
    revision = conn.execute(
        'SELECT * FROM opportunity_revisions WHERE revision_id=? AND opportunity_id=?',
        (existing['current_revision_id'], existing['opportunity_id'])).fetchone()
    if not revision:
        return 'conflict', 'existing Opportunity has no current revision'
    if (revision['stage'], revision['validation_state']) != ('active', 'signal_detected'):
        return 'conflict', 'existing Opportunity is not in active/signal_detected state'
    expected_ids = {opportunity.link_id_for(existing['opportunity_id'], spec['target_kind'],
                                            spec['target_key'], spec['role'])
                    for spec in link_specs}
    try:
        revision_ids = set(json.loads(revision['link_ids_json'] or '[]'))
    except (TypeError, ValueError):
        return 'conflict', 'existing revision has invalid link_ids_json'
    if revision_ids != expected_ids:
        return 'conflict', 'existing revision links differ from this request'
    rows = [dict(row) for row in conn.execute(
        'SELECT * FROM opportunity_links WHERE opportunity_id=?', (existing['opportunity_id'],))]
    if len(rows) != len(expected_ids):
        return 'conflict', 'existing Opportunity has additional links'
    by_id = {row['link_id']: row for row in rows}
    for spec in link_specs:
        link_id = opportunity.link_id_for(existing['opportunity_id'], spec['target_kind'],
                                          spec['target_key'], spec['role'])
        row = by_id.get(link_id)
        if not row:
            return 'conflict', 'existing Opportunity is missing an expected link'
        locator = spec.get('locator')
        if isinstance(locator, str):
            try:
                locator = json.loads(locator or '{}')
            except (TypeError, ValueError):
                locator = {}
        expected_locator = json.dumps(locator or {}, ensure_ascii=False, sort_keys=True)
        if (row['support'] != spec.get('support', 'context')
                or row['locator_json'] != expected_locator
                or row['method'] != spec.get('method', 'review_manifest')
                or float(row['confidence']) != float(spec.get('confidence', 0.0))):
            return 'conflict', 'existing link payload differs from this request'
    return 'idempotent', ''


def _article_specs(article_key, event_id, report_candidate):
    specs = [{
        'target_kind': 'article', 'target_key': article_key, 'role': 'seed_signal',
        'support': 'context',
        'locator': {'field': 'article', 'url': report_candidate.get('article_url', '')},
        'method': 'review_manifest', 'confidence': 1.0,
    }]
    if event_id:
        specs.append({
            'target_kind': 'event', 'target_key': event_id, 'role': 'context',
            'support': 'context', 'locator': {'field': 'event', 'event_id': event_id},
            'method': 'review_manifest', 'confidence': 0.5,
        })
    return specs


def _validate_candidate(conn, manifest_candidate, report_candidate, schema_version,
                        seen_candidates, seen_canonical, review_mode='human',
                        allow_ai_create=False):
    cid = str(manifest_candidate.get('candidate_id') or '')
    errors = []
    warnings = []
    if not cid:
        errors.append(_err('candidate_id_missing', 'candidate_id is required'))
    elif cid in seen_candidates:
        errors.append(_err('candidate_duplicate', f'candidate appears twice: {cid}', cid))
    seen_candidates.add(cid)
    if not report_candidate:
        errors.append(_err('candidate_not_found', f'candidate is not in report: {cid}', cid))
        return {'candidate_id': cid, 'errors': errors, 'warnings': warnings,
                'create': False, 'canonical_key': '', 'opportunity_id': '',
                'existing_action': None, 'idempotent': False, 'link_specs': [],
                'identity': {}, 'review_status': '', 'promotion_decision': ''}

    article_key = str(manifest_candidate.get('article_key') or '')
    event_id = str(manifest_candidate.get('event_id') or '')
    if article_key != str(report_candidate.get('article_key') or ''):
        errors.append(_err('article_key_mismatch', 'article_key does not match report', cid,
                           'article_key'))
    if event_id != str(report_candidate.get('event_id') or ''):
        errors.append(_err('event_id_mismatch', 'event_id does not match report', cid, 'event_id'))

    review_status = str(manifest_candidate.get('review_status') or '')
    promotion = str(manifest_candidate.get('promotion_decision') or '')
    if review_status not in REVIEW_STATUSES:
        errors.append(_err('review_status_invalid', f'invalid review_status: {review_status!r}',
                           cid, 'review_status'))
    if promotion not in PROMOTION_DECISIONS:
        errors.append(_err('promotion_decision_invalid',
                           f'invalid promotion_decision: {promotion!r}', cid,
                           'promotion_decision'))
    create = promotion == 'create_opportunity'
    if create and review_status != 'accepted_as_seed':
        errors.append(_err('promotion_not_accepted',
                           'only accepted_as_seed may request create_opportunity', cid,
                           'promotion_decision'))
    if (review_mode != 'human' and not allow_ai_create
            and review_status == 'accepted_as_seed'):
        errors.append(_err('human_approval_required',
                           'accepted_as_seed requires a human review manifest', cid,
                           'review_mode'))
    if create and review_mode != 'human' and not allow_ai_create:
        errors.append(_err('human_approval_required',
                           'create_opportunity requires a human review manifest', cid,
                           'review_mode'))
    notes = str(manifest_candidate.get('review_notes') or '').strip()
    if create and not notes:
        errors.append(_err('review_notes_required', 'create_opportunity requires review_notes',
                           cid, 'review_notes'))

    identity = manifest_candidate.get('identity')
    if not isinstance(identity, dict):
        if create:
            errors.append(_err('identity_missing', 'identity must be an object', cid, 'identity'))
        identity = {}
    subject = str(identity.get('subject') or '').strip()
    problem = str(identity.get('problem_statement') or '').strip()
    kind = str(identity.get('opportunity_kind') or '').strip()
    buyer = str(identity.get('buyer_scope') or '').strip()
    if create:
        for field, value in (('subject', subject), ('problem_statement', problem),
                             ('opportunity_kind', kind)):
            if not value:
                errors.append(_err('identity_field_missing', f'{field} is required', cid,
                                   f'identity.{field}'))
    canonical = ''
    if subject and problem and kind:
        try:
            canonical = opportunity.canonical_key_for(subject, problem, buyer, kind)
        except opportunity.OpportunityError as exc:
            errors.append(_err('canonical_key_invalid', str(exc), cid, 'identity'))
    if canonical and create:
        if canonical in seen_canonical:
            errors.append(_err('duplicate_application', 'same canonical_key is requested twice',
                               cid, 'identity'))
        seen_canonical.add(canonical)

    if _table(conn, 'articles') and not conn.execute(
            'SELECT 1 FROM articles WHERE article_key=?', (article_key,)).fetchone():
        errors.append(_err('article_not_found', 'article_key does not exist in target DB', cid,
                           'article_key'))
    if event_id and _table(conn, 'events') and not conn.execute(
            'SELECT 1 FROM events WHERE event_id=?', (event_id,)).fetchone():
        errors.append(_err('event_not_found', 'event_id does not exist in target DB', cid,
                           'event_id'))

    link_specs = _article_specs(article_key, event_id, report_candidate)
    try:
        evidence_refs = _parse_refs(manifest_candidate.get('evidence_refs'), 'evidence',
                                    'fact_basis', cid)
        entity_refs = _parse_refs(manifest_candidate.get('entity_refs'), 'entity',
                                  'subject', cid)
        claim_refs = _parse_refs(manifest_candidate.get('claim_refs'), 'claim',
                                 'unverified_claim', cid)
    except ManifestError as exc:
        errors.append(_err('refs_invalid', str(exc), cid))
        evidence_refs, entity_refs, claim_refs = [], [], []

    for ref in evidence_refs:
        if ref['role'] not in EVIDENCE_ROLES:
            errors.append(_err('evidence_role_invalid', f'invalid evidence role {ref["role"]!r}',
                               cid, 'evidence_refs'))
            continue
        if ref['support'] not in opportunity.SUPPORTS:
            errors.append(_err('evidence_support_invalid', 'invalid evidence support', cid,
                               'evidence_refs'))
            continue
        row = conn.execute('SELECT * FROM evidences WHERE evidence_id=?', (ref['id'],)).fetchone()
        if not row:
            errors.append(_err('evidence_not_found', f'evidence does not exist: {ref["id"]}', cid,
                               'evidence_refs'))
            continue
        if str(row['article_key'] or '') != article_key:
            errors.append(_err('evidence_article_mismatch',
                               'evidence belongs to a different article', cid, 'evidence_refs'))
        problems = evidence_integrity_problems(dict(row))
        if ref['role'] == 'fact_basis' and problems:
            errors.append(_err('evidence_invalid',
                               'fact_basis evidence is not valid: ' + ', '.join(problems), cid,
                               'evidence_refs'))
        support = 'direct' if ref['role'] == 'fact_basis' else 'context'
        link_specs.append({
            'target_kind': 'evidence', 'target_key': ref['id'], 'role': ref['role'],
            'support': support, 'locator': row['locator_json'] or '{}',
            'method': 'review_manifest', 'confidence': 0.5,
        })

    for ref in entity_refs:
        if ref['role'] not in ENTITY_ROLES:
            errors.append(_err('entity_role_invalid', f'invalid entity role {ref["role"]!r}', cid,
                               'entity_refs'))
            continue
        if ref['support'] not in opportunity.SUPPORTS:
            errors.append(_err('entity_support_invalid', 'invalid entity support', cid,
                               'entity_refs'))
            continue
        row = conn.execute('SELECT * FROM entities WHERE entity_id=?', (ref['id'],)).fetchone()
        if not row:
            errors.append(_err('entity_not_found', f'entity does not exist: {ref["id"]}', cid,
                               'entity_refs'))
            continue
        mention = conn.execute(
            "SELECT locator_json FROM entity_mentions WHERE target_kind='article' "
            "AND target_key=? AND entity_id=? ORDER BY mention_id LIMIT 1",
            (article_key, ref['id'])).fetchone()
        if not mention:
            errors.append(_err('entity_not_traceable',
                               'entity has no article mention for this candidate', cid,
                               'entity_refs'))
            continue
        link_specs.append({
            'target_kind': 'entity', 'target_key': ref['id'], 'role': ref['role'],
            'support': 'context', 'locator': mention['locator_json'] or '{}',
            'method': 'review_manifest', 'confidence': 0.5,
        })

    for ref in claim_refs:
        if ref['role'] not in CLAIM_ROLES:
            errors.append(_err('claim_role_invalid', f'invalid claim role {ref["role"]!r}', cid,
                               'claim_refs'))
            continue
        if ref['support'] not in opportunity.SUPPORTS:
            errors.append(_err('claim_support_invalid', 'invalid claim support', cid,
                               'claim_refs'))
            continue
        row = conn.execute('SELECT * FROM claims WHERE claim_id=?', (ref['id'],)).fetchone()
        if not row:
            errors.append(_err('claim_not_found', f'claim does not exist: {ref["id"]}', cid,
                               'claim_refs'))
            continue
        if ref['role'] == 'fact_basis' and row['verification_state'] != 'verified':
            errors.append(_err('claim_fact_basis_unverified',
                               'fact_basis claim must be verified; skeleton/unverified is forbidden',
                               cid, 'claim_refs'))
        link_specs.append({
            'target_kind': 'claim', 'target_key': ref['id'], 'role': ref['role'],
            'support': 'direct' if ref['role'] == 'fact_basis' else 'context',
            'locator': row['locator_json'] or '{}', 'method': 'review_manifest',
            'confidence': 0.5,
        })

    # A manifest may only name roles that are valid for the target kind. The opportunity
    # data layer repeats these checks inside the creation transaction.
    for spec in link_specs:
        if spec['target_kind'] not in opportunity.ROLE_TARGETS.get(spec['role'], set()):
            errors.append(_err('link_role_invalid',
                               f'role {spec["role"]!r} cannot target {spec["target_kind"]!r}',
                               cid, 'link_specs'))

    existing_action = None
    if canonical and create and _table(conn, 'opportunities'):
        try:
            existing_action, detail = _existing_action(conn, canonical, identity, link_specs)
        except (sqlite3.OperationalError, KeyError) as exc:
            errors.append(_err('existing_check_failed', str(exc), cid))
        else:
            if existing_action == 'conflict':
                errors.append(_err('canonical_key_conflict', detail, cid, 'identity'))
            similar = []
            wanted_problem = _norm(problem)
            for row in conn.execute('SELECT * FROM opportunities ORDER BY opportunity_id'):
                if (_norm(row['problem_statement']) == wanted_problem
                        and row['canonical_key'] != canonical):
                    similar.append(row['opportunity_id'])
            if similar:
                warnings.append(_err('similar_existing_opportunity',
                                      'similar subject/problem exists: ' + ', '.join(similar[:5]),
                                      cid))

    if schema_version < 9 and create:
        warnings.append(_err('target_schema_below_v9',
                             'target schema is below v9; apply will refuse until a separate copy is migrated',
                             cid))
    return {
        'candidate_id': cid,
        'article_key': article_key,
        'event_id': event_id,
        'review_status': review_status,
        'promotion_decision': promotion,
        'identity': {'subject': subject, 'problem_statement': problem,
                     'buyer_scope': buyer, 'opportunity_kind': kind},
        'canonical_key': canonical,
        'opportunity_id': opportunity.opportunity_id_for(canonical) if canonical else '',
        'create': create,
        'existing_action': existing_action,
        'idempotent': existing_action == 'idempotent',
        'link_specs': link_specs,
        'errors': errors,
        'warnings': warnings,
    }


def validate_manifest(manifest_path, db_path, report_path=REPORT_PATH, allow_ai_create=False):
    """Read-only validation of a review manifest against a candidate report and DB."""
    manifest = _read_json(manifest_path)
    report = _read_json(report_path)
    if not isinstance(manifest, dict):
        raise ManifestError('manifest must be a JSON object')
    report_hash = _sha256(report_path)
    schema_version = _schema_version(db_path)
    errors = []
    warnings = []
    if manifest.get('manifest_version') != MANIFEST_VERSION:
        errors.append(_err('manifest_version_invalid',
                           f'manifest_version must be {MANIFEST_VERSION}'))
    if not str(manifest.get('source_report_hash') or '').strip():
        errors.append(_err('source_report_hash_missing', 'source_report_hash is required'))
    elif str(manifest['source_report_hash']) != report_hash:
        errors.append(_err('source_report_hash_mismatch',
                           'source_report_hash does not match the candidate report'))
    if not str(manifest.get('reviewer') or '').strip():
        errors.append(_err('reviewer_missing', 'reviewer is required'))
    review_mode = str(manifest.get('review_mode') or 'human')
    if review_mode not in REVIEW_MODES:
        errors.append(_err('review_mode_invalid', f'invalid review_mode: {review_mode!r}'))
    if review_mode == 'ai_assisted':
        warnings.append(_err('ai_review_not_human_approval',
                             'review_mode=ai_assisted is provisional and is not human approval'))

    index = _candidate_index(report)
    raw_candidates = manifest.get('candidates')
    if not isinstance(raw_candidates, list):
        errors.append(_err('candidates_invalid', 'candidates must be a list'))
        raw_candidates = []
    conn = _connect_ro(db_path)
    try:
        seen_candidates = set()
        seen_canonical = set()
        results = []
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                errors.append(_err('candidate_invalid', 'candidate must be an object'))
                continue
            cid = str(raw.get('candidate_id') or '')
            result = _validate_candidate(conn, raw, index.get(cid), schema_version,
                                         seen_candidates, seen_canonical, review_mode,
                                         allow_ai_create)
            results.append(result)
            errors.extend(result['errors'])
            warnings.extend(result['warnings'])
    finally:
        conn.close()
    counts = {
        'candidates': len(results),
        'create_requests': sum(1 for item in results if item['create']),
        'would_create': sum(1 for item in results if item['create']
                            and not item['errors'] and not item['idempotent']),
        'idempotent': sum(1 for item in results if item['idempotent']),
        'accepted_without_promotion': sum(
            1 for item in results
            if item['review_status'] == 'accepted_as_seed' and not item['create']),
        'rejected': sum(1 for item in results if item['review_status'] == 'rejected'),
        'blocked': sum(1 for item in results if item['create'] and item['errors']),
    }
    return {
        'manifest_version': MANIFEST_VERSION,
        'manifest_path': str(manifest_path),
        'report_path': str(report_path),
        'report_hash': report_hash,
        'db': str(db_path),
        'schema_version': schema_version,
        'read_only': True,
        'review_mode': review_mode,
        'reviewer': str(manifest.get('reviewer') or ''),
        'valid': not errors,
        'errors': errors,
        'warnings': warnings,
        'counts': counts,
        'candidates': results,
    }


def preview_manifest(manifest_path, db_path, report_path=REPORT_PATH, allow_ai_create=False):
    """Return the deterministic creation preview; never writes the target database."""
    validation = validate_manifest(manifest_path, db_path, report_path, allow_ai_create)
    preview = []
    for item in validation['candidates']:
        if not item['create']:
            action = 'not_promoted'
        elif item['idempotent']:
            action = 'idempotent'
        elif item['errors'] or validation['schema_version'] < 9:
            action = 'blocked'
        else:
            action = 'create'
        preview.append({
            'candidate_id': item['candidate_id'],
            'action': action,
            'canonical_key': item['canonical_key'],
            'opportunity_id': item['opportunity_id'],
            'seed_links': [spec for spec in item['link_specs']
                           if spec['target_kind'] in ('article', 'event')],
            'evidence_refs': [spec for spec in item['link_specs']
                              if spec['target_kind'] == 'evidence'],
            'entity_refs': [spec for spec in item['link_specs']
                            if spec['target_kind'] == 'entity'],
            'claim_refs': [spec for spec in item['link_specs']
                           if spec['target_kind'] == 'claim'],
            'blockers': item['errors'],
            'warnings': item['warnings'],
            'evidence_limitations': [
                'initial state is signal_detected; no validation state is upgraded',
                'manual identity fields are not evidence',
            ],
        })
    result = dict(validation)
    result['preview'] = preview
    result['counts']['preview_create'] = sum(1 for item in preview if item['action'] == 'create')
    result['counts']['preview_idempotent'] = sum(1 for item in preview
                                                if item['action'] == 'idempotent')
    result['counts']['preview_blocked'] = sum(1 for item in preview if item['action'] == 'blocked')
    return result


def _audit(db_path):
    conn = _connect_ro(db_path)
    try:
        checks, info = opportunity_audit.check(conn)
        return checks, info
    finally:
        conn.close()


def _state_distribution(db_path):
    conn = _connect_ro(db_path)
    try:
        if not _table(conn, 'opportunities'):
            return {}
        return {row[0]: row[1] for row in conn.execute(
            'SELECT validation_state,COUNT(*) FROM opportunities GROUP BY validation_state')}
    finally:
        conn.close()


def _markdown(result):
    lines = ['# Opportunity Review Apply Result', '',
             f"- manifest: `{result.get('manifest_path', '')}`",
             f"- db: `{result.get('db', '')}`",
             f"- valid: `{str(result.get('valid', False)).lower()}`",
             f"- schema_version: `{result.get('schema_version')}`",
             f"- applied: `{str(result.get('applied', False)).lower()}`", '',
             '## Counts', '']
    for key, value in result.get('counts', {}).items():
        lines.append(f'- {key}: {value}')
    lines += ['', '## Created', '']
    for item in result.get('created', []):
        lines.append(f"- `{item['opportunity_id']}` · `{item['canonical_key']}` · "
                     f"revision `{item['revision_id']}` · links {len(item['link_ids'])}")
    lines += ['', '## Errors', '']
    for item in result.get('errors', []):
        lines.append(f"- `{item.get('code')}` · {item.get('message')}")
    lines += ['', '## Audit', '']
    for check in result.get('audit', {}).get('checks', []):
        if check.get('count'):
            lines.append(f"- `{check['id']}` · {check['severity']} · {check['count']}")
    return '\n'.join(lines).rstrip() + '\n'


def _write_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def apply_manifest(manifest_path, db_path, report_path=REPORT_PATH, apply=False,
                   result_dir='reports', allowed_paths=None, allow_ai_create=False):
    """Validate and explicitly create Opportunities, one transaction per Opportunity."""
    if not apply:
        raise ManifestError('--apply is required for b-review apply')
    _assert_allowed_target(db_path, allowed_paths)
    schema_version = _schema_version(db_path)
    if schema_version < 9:
        raise ManifestError(
            f'target schema is {schema_version}, below v9; copy the database and migrate the copy '
            'separately before apply')
    validation = validate_manifest(manifest_path, db_path, report_path, allow_ai_create)
    if not validation['valid']:
        result = dict(validation)
        result.update({'applied': False, 'counts': {**validation['counts'], 'created': 0,
                                                    'failed': 0, 'idempotent': 0,
                                                    'conflicts': 0},
                       'created': [], 'failed': [], 'idempotent': [], 'conflicts': []})
        return result

    store = UnifiedStore(str(db_path), migrate=False)
    created = []
    failed = []
    idempotent = []
    conflicts = []
    for item in validation['candidates']:
        if not item['create']:
            continue
        if item['idempotent']:
            idempotent.append({'candidate_id': item['candidate_id'],
                               'opportunity_id': item['opportunity_id']})
            continue
        if item['errors']:
            conflicts.append({'candidate_id': item['candidate_id'], 'errors': item['errors']})
            continue
        try:
            written = opportunity.create_opportunity_with_links(
                store,
                subject=item['identity']['subject'],
                problem_statement=item['identity']['problem_statement'],
                buyer_scope=item['identity']['buyer_scope'],
                opportunity_kind=item['identity']['opportunity_kind'],
                title=item['identity']['problem_statement'],
                stage='active', validation_state='signal_detected', confidence=0.0,
                rules_version='opp-v1', actor='manifest:' + str(validation['review_mode']),
                note='Batch 12 manifest ' + str(manifest_path) + '; reviewer='
                     + str(validation.get('reviewer') or ''),
                links=item['link_specs'])
        except (opportunity.OpportunityError, sqlite3.Error) as exc:
            failed.append({'candidate_id': item['candidate_id'], 'error': str(exc)})
            continue
        if written.get('created'):
            created.append({'candidate_id': item['candidate_id'],
                            'opportunity_id': written['opportunity_id'],
                            'canonical_key': written['canonical_key'],
                            'revision_id': written['current_revision_id'],
                            'link_ids': written['link_ids']})
        else:
            # A concurrent creator or a pre-existing record: verify exact idempotence,
            # otherwise report a conflict and never append/merge.
            conn = _connect_ro(db_path)
            try:
                action, detail = _existing_action(conn, written.get('canonical_key', ''),
                                                  item['identity'], item['link_specs'])
            finally:
                conn.close()
            if action == 'idempotent':
                idempotent.append({'candidate_id': item['candidate_id'],
                                   'opportunity_id': written['opportunity_id']})
            else:
                conflicts.append({'candidate_id': item['candidate_id'],
                                  'opportunity_id': written['opportunity_id'],
                                  'reason': detail})
    checks, info = _audit(db_path)
    audit_errors = [check for check in checks
                    if check.get('severity') == 'ERROR' and check.get('count')]
    result = dict(validation)
    result.update({
        'applied': True,
        'counts': {
            **validation['counts'],
            'created': len(created),
            'failed': len(failed),
            'idempotent': len(idempotent),
            'conflicts': len(conflicts),
            'validation_states': _state_distribution(db_path),
        },
        'created': created,
        'failed': failed,
        'idempotent': idempotent,
        'conflicts': conflicts,
        'audit': {'checks': checks, 'info': info, 'errors': audit_errors},
        'ok': not failed and not conflicts and not audit_errors,
    })
    out = Path(result_dir)
    _write_atomic(out / RESULT_JSON,
                  json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    _write_atomic(out / RESULT_MD, _markdown(result))
    result['outputs'] = {'json': str(out / RESULT_JSON), 'markdown': str(out / RESULT_MD)}
    return result
