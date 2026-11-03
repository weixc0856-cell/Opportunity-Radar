"""Minimal, append-only Opportunity data access.

This module implements the four-table model designed in docs/OPPORTUNITY_MODEL.md:
opportunities, opportunity_links, opportunity_hypotheses and opportunity_revisions.
It does not discover opportunities, score them, or call a model.
"""
from __future__ import annotations

import json
import re

from . import lineage, linking
from .unified import now, stable_id

STAGES = ('active', 'monitoring', 'closed')
VALIDATION_STATES = ('signal_detected', 'insufficient_evidence', 'problem_supported',
                     'buyer_identified', 'payment_verified', 'opportunity_candidate',
                     'contradicted')
HYPOTHESIS_STATUSES = ('proposed', 'supported', 'contradicted', 'retired')
TARGET_KINDS = ('article', 'event', 'evidence', 'claim', 'entity')
ROLES = ('seed_signal', 'fact_basis', 'unverified_claim', 'inference', 'counter_evidence',
         'payment_evidence', 'buyer', 'subject', 'competitor', 'affected', 'context')
SUPPORTS = ('direct', 'indirect', 'contradicts', 'context')
ROLE_TARGETS = {
    'seed_signal': {'article', 'event'},
    'fact_basis': {'evidence', 'claim'},
    'unverified_claim': {'claim'},
    'inference': {'article'},
    'counter_evidence': {'evidence', 'claim'},
    'payment_evidence': {'evidence', 'claim'},
    'buyer': {'entity'},
    'subject': {'entity'},
    'competitor': {'entity'},
    'affected': {'entity'},
    'context': set(TARGET_KINDS),
}
TARGETS = {
    'article': ('articles', 'article_key'),
    'event': ('events', 'event_id'),
    'evidence': ('evidences', 'evidence_id'),
    'claim': ('claims', 'claim_id'),
    'entity': ('entities', 'entity_id'),
}


class OpportunityError(ValueError):
    """Invalid Opportunity data or an inconsistent request."""


def _norm(value):
    text = re.sub(r'[^0-9a-z一-鿿]+', ' ', str(value or '').lower())
    return re.sub(r'\s+', ' ', text).strip()


def canonical_key_for(subject, problem_statement, buyer_scope, opportunity_kind):
    """Stable identity from the commercial subject/problem, never from an article or score."""
    subject_key = _norm(subject)
    problem_key = _norm(problem_statement)
    kind_key = _norm(opportunity_kind)
    scope_key = _norm(buyer_scope) or 'unknown'
    if not subject_key:
        raise OpportunityError('subject is required for an Opportunity')
    if not problem_key:
        raise OpportunityError('problem_statement is required for an Opportunity')
    if not kind_key:
        raise OpportunityError('opportunity_kind is required for an Opportunity')
    return '|'.join((kind_key, subject_key, problem_key, scope_key))


def opportunity_id_for(canonical_key):
    return stable_id('opp-', canonical_key)


def link_id_for(opportunity_id, target_kind, target_key, role):
    return stable_id('opl-', opportunity_id, target_kind, target_key, role)


def hypothesis_id_for(opportunity_id, hypothesis_kind, statement, basis_hash, supersedes=''):
    return stable_id('oph-', opportunity_id, hypothesis_kind, statement, basis_hash, supersedes)


def basis_hash_for(link_ids, hypothesis_id=''):
    return stable_id('ob-', *sorted(str(link) for link in link_ids), str(hypothesis_id or ''))


def revision_id_for(opportunity_id, stage, validation_state, hypothesis_id, basis_hash,
                    rules_version):
    return stable_id('opr-', opportunity_id, stage, validation_state, hypothesis_id or '',
                     basis_hash, rules_version)


def _confidence(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise OpportunityError('confidence must be numeric between 0 and 1')
    if not 0 <= number <= 1:
        raise OpportunityError('confidence must be between 0 and 1')
    return number


def _locator(value):
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value or '{}')
        except (TypeError, ValueError):
            raise OpportunityError('locator_json must be valid JSON')
    if not isinstance(value, dict):
        raise OpportunityError('locator_json must be a JSON object')
    return value


def _target_problem(conn, target_kind, target_key):
    if target_kind not in TARGETS:
        return 'unknown target_kind'
    table, key = TARGETS[target_kind]
    try:
        row = conn.execute(f'SELECT 1 FROM {table} WHERE {key}=?', (target_key,)).fetchone()
    except Exception:
        return 'target table unavailable'
    return '' if row else 'target does not exist'


def link_target_problem(store, target_kind, target_key):
    with store.connect() as conn:
        return _target_problem(conn, target_kind, target_key)


def target_exists(store, target_kind, target_key):
    return link_target_problem(store, target_kind, target_key) == ''


def _valid_fact_link(conn, link):
    target_kind = link['target_kind']
    target_key = link['target_key']
    if target_kind == 'evidence':
        row = conn.execute(
            "SELECT source_id, quote, locator_json FROM evidences WHERE evidence_id=?",
            (target_key,)).fetchone()
        return bool(row and str(row['source_id'] or '').strip()
                    and str(row['quote'] or '').strip()
                    and str(row['locator_json'] or '{}') not in ('', '{}'))
    if target_kind == 'claim':
        row = conn.execute(
            "SELECT verification_state FROM claims WHERE claim_id=?", (target_key,)).fetchone()
        return bool(row and row['verification_state'] == 'verified')
    return False


def _validate_state(conn, validation_state, links):
    if validation_state not in VALIDATION_STATES:
        raise OpportunityError(f'unknown validation_state: {validation_state!r}')
    fact = any(link['role'] == 'fact_basis' and _valid_fact_link(conn, link) for link in links)
    buyer = any(link['role'] == 'buyer' and link['target_kind'] == 'entity' for link in links)
    payment = any(link['role'] == 'payment_evidence' and link['support'] == 'direct'
                  and _valid_fact_link(conn, link) for link in links)
    counter = any(link['role'] == 'counter_evidence' and link['support'] == 'contradicts'
                  for link in links)
    if validation_state in ('problem_supported', 'buyer_identified', 'payment_verified',
                            'opportunity_candidate') and not fact:
        raise OpportunityError(f'{validation_state} requires a valid fact_basis link')
    if validation_state in ('buyer_identified', 'payment_verified', 'opportunity_candidate') and not buyer:
        raise OpportunityError(f'{validation_state} requires a buyer entity link')
    if validation_state in ('payment_verified', 'opportunity_candidate') and not payment:
        raise OpportunityError(f'{validation_state} requires direct payment_evidence')
    if validation_state == 'contradicted' and not counter:
        raise OpportunityError('contradicted requires counter_evidence with support=contradicts')


def _links_for(conn, opportunity_id, link_ids=None):
    if link_ids is None:
        return [dict(row) for row in conn.execute(
            'SELECT * FROM opportunity_links WHERE opportunity_id=? ORDER BY link_id',
            (opportunity_id,))]
    ids = sorted({str(link) for link in link_ids})
    if not ids:
        return []
    rows = [dict(row) for row in conn.execute(
        'SELECT * FROM opportunity_links WHERE opportunity_id=? AND link_id IN (%s)'
        % ','.join('?' * len(ids)), (opportunity_id, *ids))]
    if len(rows) != len(ids):
        found = {row['link_id'] for row in rows}
        missing = [link_id for link_id in ids if link_id not in found]
        raise OpportunityError(f'link_ids do not belong to this Opportunity: {missing}')
    return rows


def add_link(store, opportunity_id, target_kind, target_key, role, support='context',
             locator=None, method='manual', confidence=0.0, observed_at=None):
    if target_kind not in TARGET_KINDS:
        raise OpportunityError(f'unknown target_kind: {target_kind!r}')
    if role not in ROLES:
        raise OpportunityError(f'unknown link role: {role!r}')
    if target_kind not in ROLE_TARGETS[role]:
        raise OpportunityError(f'role {role} cannot target {target_kind}')
    if support not in SUPPORTS:
        raise OpportunityError(f'unknown support: {support!r}')
    if role == 'counter_evidence' and support != 'contradicts':
        raise OpportunityError('counter_evidence requires support=contradicts')
    if role == 'payment_evidence' and support != 'direct':
        raise OpportunityError('payment_evidence requires support=direct')
    confidence = _confidence(confidence)
    locator_json = json.dumps(_locator(locator), ensure_ascii=False, sort_keys=True)
    with store.connect() as conn:
        if not conn.execute('SELECT 1 FROM opportunities WHERE opportunity_id=?',
                            (opportunity_id,)).fetchone():
            raise OpportunityError(f'no such Opportunity: {opportunity_id}')
        problem = _target_problem(conn, target_kind, target_key)
        if problem:
            raise OpportunityError(problem)
        if role == 'fact_basis' and target_kind == 'claim':
            if not _valid_fact_link(conn, {'target_kind': target_kind, 'target_key': target_key}):
                raise OpportunityError('fact_basis claim must be verified')
        link_id = link_id_for(opportunity_id, target_kind, target_key, role)
        existing = conn.execute('SELECT * FROM opportunity_links WHERE link_id=?',
                                (link_id,)).fetchone()
        if existing:
            same = (existing['support'] == support and existing['locator_json'] == locator_json
                    and existing['method'] == method and float(existing['confidence']) == confidence
                    and (existing['observed_at'] or '') == str(observed_at or ''))
            if same:
                return False
            raise OpportunityError('link exists with a different payload')
        conn.execute(
            'INSERT INTO opportunity_links(link_id,opportunity_id,target_kind,target_key,role,'
            'support,locator_json,method,confidence,observed_at,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (link_id, opportunity_id, target_kind, target_key, role, support, locator_json,
             method, confidence, observed_at, now()))
        return True


def create_hypothesis(store, opportunity_id, hypothesis_kind, statement, basis_hash,
                      confidence=0.0, status='proposed', supersedes=''):
    hypothesis_kind = _norm(hypothesis_kind)
    statement = str(statement or '').strip()
    basis_hash = str(basis_hash or '').strip()
    if not hypothesis_kind or not statement or not basis_hash:
        raise OpportunityError('hypothesis_kind, statement and basis_hash are required')
    if status not in HYPOTHESIS_STATUSES:
        raise OpportunityError(f'unknown hypothesis status: {status!r}')
    confidence = _confidence(confidence)
    hypothesis_id = hypothesis_id_for(opportunity_id, hypothesis_kind, statement, basis_hash,
                                      supersedes)
    with store.connect() as conn:
        if not conn.execute('SELECT 1 FROM opportunities WHERE opportunity_id=?',
                            (opportunity_id,)).fetchone():
            raise OpportunityError(f'no such Opportunity: {opportunity_id}')
        if supersedes:
            if supersedes == hypothesis_id:
                raise OpportunityError('a hypothesis cannot supersede itself')
            old = conn.execute('SELECT opportunity_id FROM opportunity_hypotheses WHERE hypothesis_id=?',
                               (supersedes,)).fetchone()
            if not old or old['opportunity_id'] != opportunity_id:
                raise OpportunityError('supersedes must reference a hypothesis of the same Opportunity')
        existing = conn.execute('SELECT 1 FROM opportunity_hypotheses WHERE hypothesis_id=?',
                                (hypothesis_id,)).fetchone()
        if existing:
            return hypothesis_id
        conn.execute(
            'INSERT INTO opportunity_hypotheses(hypothesis_id,opportunity_id,hypothesis_kind,'
            'statement,basis_hash,confidence,status,supersedes,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?)',
            (hypothesis_id, opportunity_id, hypothesis_kind, statement, basis_hash, confidence,
             status, supersedes, now()))
    return hypothesis_id


def create_opportunity(store, *, subject, problem_statement, buyer_scope='',
                       opportunity_kind='demand', title='', stage='active',
                       validation_state='signal_detected', confidence=0.0,
                       rules_version='opp-v1', actor='system', note=''):
    if stage not in STAGES:
        raise OpportunityError(f'unknown stage: {stage!r}')
    if validation_state not in VALIDATION_STATES:
        raise OpportunityError(f'unknown validation_state: {validation_state!r}')
    confidence = _confidence(confidence)
    canonical_key = canonical_key_for(subject, problem_statement, buyer_scope, opportunity_kind)
    opportunity_id = opportunity_id_for(canonical_key)
    with store.connect() as conn:
        existing = conn.execute('SELECT * FROM opportunities WHERE canonical_key=?',
                                (canonical_key,)).fetchone()
        if existing:
            return {'opportunity_id': existing['opportunity_id'], 'created': False,
                    'current_revision_id': existing['current_revision_id']}
        stamp = now()
        conn.execute(
            'INSERT INTO opportunities(opportunity_id,canonical_key,title,problem_statement,'
            'buyer_scope,opportunity_kind,stage,validation_state,confidence,first_seen_at,'
            'last_seen_at,current_revision_id,rules_version,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (opportunity_id, canonical_key, str(title or problem_statement).strip(),
             str(problem_statement).strip(), str(buyer_scope or '').strip(),
             str(opportunity_kind).strip(), stage, validation_state, confidence, stamp, stamp,
             '', rules_version, stamp, stamp))
        link_ids = []
        basis_hash = basis_hash_for(link_ids)
        revision_id = revision_id_for(opportunity_id, stage, validation_state, '', basis_hash,
                                       rules_version)
        _validate_state(conn, validation_state, [])
        conn.execute(
            'INSERT INTO opportunity_revisions(revision_id,opportunity_id,stage,validation_state,'
            'hypothesis_id,basis_hash,link_ids_json,rules_version,actor,note,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (revision_id, opportunity_id, stage, validation_state, '', basis_hash, '[]',
             rules_version, actor, note, stamp))
        conn.execute(
            'UPDATE opportunities SET current_revision_id=?,updated_at=? WHERE opportunity_id=?',
            (revision_id, stamp, opportunity_id))
    return {'opportunity_id': opportunity_id, 'created': True, 'current_revision_id': revision_id}


def append_revision(store, opportunity_id, *, stage, validation_state, hypothesis_id='',
                    link_ids=None, rules_version='opp-v1', actor='system', note='',
                    confidence=None):
    if stage not in STAGES:
        raise OpportunityError(f'unknown stage: {stage!r}')
    if validation_state not in VALIDATION_STATES:
        raise OpportunityError(f'unknown validation_state: {validation_state!r}')
    if confidence is not None:
        confidence = _confidence(confidence)
    with store.connect() as conn:
        opportunity = conn.execute('SELECT * FROM opportunities WHERE opportunity_id=?',
                                   (opportunity_id,)).fetchone()
        if not opportunity:
            raise OpportunityError(f'no such Opportunity: {opportunity_id}')
        if hypothesis_id:
            hypothesis = conn.execute(
                'SELECT opportunity_id FROM opportunity_hypotheses WHERE hypothesis_id=?',
                (hypothesis_id,)).fetchone()
            if not hypothesis or hypothesis['opportunity_id'] != opportunity_id:
                raise OpportunityError('hypothesis_id must belong to this Opportunity')
        links = _links_for(conn, opportunity_id, link_ids)
        _validate_state(conn, validation_state, links)
        basis_hash = basis_hash_for([link['link_id'] for link in links], hypothesis_id)
        revision_id = revision_id_for(opportunity_id, stage, validation_state, hypothesis_id,
                                       basis_hash, rules_version)
        existing = conn.execute('SELECT * FROM opportunity_revisions WHERE revision_id=?',
                                (revision_id,)).fetchone()
        if existing:
            return {'revision_id': revision_id, 'created': False,
                    'current_revision_id': opportunity['current_revision_id']}
        stamp = now()
        conn.execute(
            'INSERT INTO opportunity_revisions(revision_id,opportunity_id,stage,validation_state,'
            'hypothesis_id,basis_hash,link_ids_json,rules_version,actor,note,created_at) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (revision_id, opportunity_id, stage, validation_state, hypothesis_id, basis_hash,
             json.dumps(sorted(link['link_id'] for link in links)), rules_version, actor, note,
             stamp))
        conn.execute(
            'UPDATE opportunities SET stage=?,validation_state=?,confidence=COALESCE(?,confidence),'
            'last_seen_at=?,current_revision_id=?,updated_at=? WHERE opportunity_id=?',
            (stage, validation_state, confidence, stamp, revision_id, stamp, opportunity_id))
    return {'revision_id': revision_id, 'created': True, 'current_revision_id': revision_id}


def get_opportunity(store, opportunity_id):
    with store.connect() as conn:
        row = conn.execute('SELECT * FROM opportunities WHERE opportunity_id=?',
                           (opportunity_id,)).fetchone()
        return dict(row) if row else None


def get_by_canonical_key(store, canonical_key):
    with store.connect() as conn:
        row = conn.execute('SELECT * FROM opportunities WHERE canonical_key=?',
                           (canonical_key,)).fetchone()
        return dict(row) if row else None


def history(store, opportunity_id):
    with store.connect() as conn:
        opportunity = conn.execute('SELECT * FROM opportunities WHERE opportunity_id=?',
                                   (opportunity_id,)).fetchone()
        if not opportunity:
            return None
        links = [dict(row) for row in conn.execute(
            'SELECT * FROM opportunity_links WHERE opportunity_id=? ORDER BY created_at,link_id',
            (opportunity_id,))]
        hypotheses = [dict(row) for row in conn.execute(
            'SELECT * FROM opportunity_hypotheses WHERE opportunity_id=? ORDER BY created_at,hypothesis_id',
            (opportunity_id,))]
        revisions = [dict(row) for row in conn.execute(
            'SELECT * FROM opportunity_revisions WHERE opportunity_id=? ORDER BY created_at,revision_id',
            (opportunity_id,))]
    return {'opportunity': dict(opportunity), 'links': links, 'hypotheses': hypotheses,
            'revisions': revisions}


def current_projection_problems(store, opportunity_id):
    with store.connect() as conn:
        opportunity = conn.execute('SELECT * FROM opportunities WHERE opportunity_id=?',
                                   (opportunity_id,)).fetchone()
        if not opportunity:
            return ['opportunity does not exist']
        revision = conn.execute('SELECT * FROM opportunity_revisions WHERE revision_id=? AND opportunity_id=?',
                                (opportunity['current_revision_id'], opportunity_id)).fetchone()
        if not revision:
            return ['current_revision_id does not reference a revision of this Opportunity']
        latest = conn.execute(
            'SELECT * FROM opportunity_revisions WHERE opportunity_id=? '
            'ORDER BY created_at DESC,revision_id DESC LIMIT 1', (opportunity_id,)).fetchone()
        problems = []
        if latest and revision['revision_id'] != latest['revision_id']:
            problems.append('current_revision_id is not the latest revision')
        if (opportunity['stage'], opportunity['validation_state']) != (revision['stage'],
                                                                       revision['validation_state']):
            problems.append('current projection does not match current revision')
        return problems


def state_problems(store, opportunity_id, validation_state=None):
    """Return the state-gate problems for an Opportunity, without changing it."""
    with store.connect() as conn:
        opportunity = conn.execute('SELECT * FROM opportunities WHERE opportunity_id=?',
                                   (opportunity_id,)).fetchone()
        if not opportunity:
            return ['opportunity does not exist']
        state = validation_state or opportunity['validation_state']
        links = _links_for(conn, opportunity_id, None)
        try:
            _validate_state(conn, state, links)
        except OpportunityError as exc:
            return [str(exc)]
        return []


def independence(store, opportunity_id):
    """Count linked fact-basis sources by recorded lineage; declared-only never corroborates."""
    with store.connect() as conn:
        links = [dict(row) for row in conn.execute(
            "SELECT * FROM opportunity_links WHERE opportunity_id=? AND role='fact_basis'",
            (opportunity_id,))]
        rows = []
        for link in links:
            if link['target_kind'] == 'evidence':
                evidence = conn.execute('SELECT * FROM evidences WHERE evidence_id=?',
                                        (link['target_key'],)).fetchone()
            elif link['target_kind'] == 'claim':
                evidence = conn.execute(
                    'SELECT v.* FROM claim_evidence ce JOIN evidences v USING(evidence_id) '
                    'WHERE ce.claim_id=? ORDER BY v.evidence_id LIMIT 1',
                    (link['target_key'],)).fetchone()
            else:
                evidence = None
            if evidence:
                rows.append(dict(evidence))
    registry = lineage.load()
    verified = {source_id for source_id, row in registry.items()
                if (row.get('review_status') or '').strip() == 'verified'}
    return linking.source_independence(rows, verified_sources=verified)
