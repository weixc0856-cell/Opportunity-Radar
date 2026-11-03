"""Read-only audit checks for the four Opportunity tables."""
from __future__ import annotations

import json

from . import opportunity


def _table(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _samples(rows, keys, limit=5):
    out = []
    for row in list(rows)[:limit]:
        item = dict(row)
        out.append({key: item.get(key) for key in keys})
    return out


def _check(check_id, severity, summary, count, samples=(), detail=None):
    return {'id': check_id, 'severity': severity, 'summary': summary,
            'count': int(count or 0), 'samples': list(samples or []),
            **({'detail': detail} if detail is not None else {})}


def check(conn):
    checks = []
    required = ('opportunities', 'opportunity_links', 'opportunity_hypotheses',
                'opportunity_revisions')
    info = {'tables_present': all(_table(conn, name) for name in required),
            'opportunities': 0, 'links': 0, 'hypotheses': 0, 'revisions': 0}
    if not info['tables_present']:
        checks.append(_check('opportunity.tables_absent', 'INFO',
                             'Opportunity tables are not deployed', 1))
        return checks, info
    info['opportunities'] = conn.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0]
    info['links'] = conn.execute('SELECT COUNT(*) FROM opportunity_links').fetchone()[0]
    info['hypotheses'] = conn.execute('SELECT COUNT(*) FROM opportunity_hypotheses').fetchone()[0]
    info['revisions'] = conn.execute('SELECT COUNT(*) FROM opportunity_revisions').fetchone()[0]
    if not info['opportunities']:
        checks.append(_check('opportunity.empty', 'INFO',
                             'Opportunity schema is present but contains no rows', 1,
                             detail=dict(info)))
        return checks, info

    targets = {
        'article': ('articles', 'article_key'), 'event': ('events', 'event_id'),
        'evidence': ('evidences', 'evidence_id'), 'claim': ('claims', 'claim_id'),
        'entity': ('entities', 'entity_id'),
    }
    invalid_targets = []
    for row in conn.execute('SELECT link_id,target_kind,target_key FROM opportunity_links'):
        table = targets.get(row['target_kind'])
        if not table:
            invalid_targets.append(dict(row, reason='unknown target_kind'))
            continue
        try:
            found = conn.execute(f'SELECT 1 FROM {table[0]} WHERE {table[1]}=?',
                                 (row['target_key'],)).fetchone()
        except Exception:
            found = None
        if not found:
            invalid_targets.append(dict(row, reason='target does not exist'))
    checks.append(_check('opportunity.link_target_missing', 'ERROR',
                         'Opportunity links whose target object does not exist',
                         len(invalid_targets),
                         _samples(invalid_targets,
                                  ['link_id', 'target_kind', 'target_key', 'reason'])))

    orphan_links = [dict(row) for row in conn.execute(
        '''SELECT l.link_id,l.opportunity_id FROM opportunity_links l
           LEFT JOIN opportunities o USING(opportunity_id)
           WHERE o.opportunity_id IS NULL''')]
    checks.append(_check('opportunity.link_orphan', 'ERROR',
                         'Opportunity links whose Opportunity does not exist',
                         len(orphan_links), _samples(orphan_links, ['link_id', 'opportunity_id'])))

    bad_role_targets = [dict(row) for row in conn.execute(
        '''SELECT link_id,role,target_kind FROM opportunity_links
           WHERE (role='fact_basis' AND target_kind NOT IN ('evidence','claim'))
              OR (role='unverified_claim' AND target_kind<>'claim')
              OR (role='payment_evidence' AND target_kind NOT IN ('evidence','claim'))
              OR (role='counter_evidence' AND target_kind NOT IN ('evidence','claim'))
              OR (role IN ('buyer','subject','competitor','affected') AND target_kind<>'entity')
              OR (role='seed_signal' AND target_kind NOT IN ('article','event'))''')]
    checks.append(_check('opportunity.link_role_target_mismatch', 'ERROR',
                         'Opportunity links whose role is incompatible with target_kind',
                         len(bad_role_targets),
                         _samples(bad_role_targets, ['link_id', 'role', 'target_kind'])))

    bad_fact_claims = [dict(row) for row in conn.execute(
        '''SELECT l.link_id,l.target_key,c.verification_state
           FROM opportunity_links l JOIN claims c ON c.claim_id=l.target_key
           WHERE l.role='fact_basis' AND l.target_kind='claim'
             AND c.verification_state<>'verified' ''')]
    checks.append(_check('opportunity.fact_basis_unverified_claim', 'ERROR',
                         'Fact basis links pointing at unverified claims',
                         len(bad_fact_claims),
                         _samples(bad_fact_claims,
                                  ['link_id', 'target_key', 'verification_state'])))

    bad_payment_support = [dict(row) for row in conn.execute(
        "SELECT link_id,support FROM opportunity_links "
        "WHERE role='payment_evidence' AND support<>'direct'")]
    checks.append(_check('opportunity.payment_not_direct', 'ERROR',
                         'Payment evidence links that are not direct',
                         len(bad_payment_support),
                         _samples(bad_payment_support, ['link_id', 'support'])))

    bad_hypothesis = [dict(row) for row in conn.execute(
        '''SELECT r.revision_id,r.hypothesis_id FROM opportunity_revisions r
           LEFT JOIN opportunity_hypotheses h ON h.hypothesis_id=r.hypothesis_id
           WHERE r.hypothesis_id<>'' AND
                 (h.hypothesis_id IS NULL OR h.opportunity_id<>r.opportunity_id)''')]
    checks.append(_check('opportunity.revision_hypothesis_invalid', 'ERROR',
                         'Revisions whose hypothesis is missing or belongs to another Opportunity',
                         len(bad_hypothesis),
                         _samples(bad_hypothesis, ['revision_id', 'hypothesis_id'])))

    bad_link_refs = []
    for row in conn.execute(
            'SELECT revision_id,opportunity_id,link_ids_json FROM opportunity_revisions'):
        try:
            ids = json.loads(row['link_ids_json'] or '[]')
        except (TypeError, ValueError):
            ids = None
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            bad_link_refs.append({'revision_id': row['revision_id'], 'reason': 'invalid_json'})
            continue
        for link_id in ids:
            link = conn.execute('SELECT opportunity_id FROM opportunity_links WHERE link_id=?',
                                (link_id,)).fetchone()
            if not link or link['opportunity_id'] != row['opportunity_id']:
                bad_link_refs.append({'revision_id': row['revision_id'], 'link_id': link_id,
                                      'reason': 'missing_or_other_opportunity'})
    checks.append(_check('opportunity.revision_link_invalid', 'ERROR',
                         'Revisions whose link_ids are invalid or belong to another Opportunity',
                         len(bad_link_refs),
                         _samples(bad_link_refs, ['revision_id', 'link_id', 'reason'])))

    projection_problems = []
    state_problems = []
    for row in conn.execute('SELECT * FROM opportunities ORDER BY opportunity_id'):
        current = conn.execute(
            'SELECT * FROM opportunity_revisions WHERE revision_id=? AND opportunity_id=?',
            (row['current_revision_id'], row['opportunity_id'])).fetchone()
        latest = conn.execute(
            'SELECT * FROM opportunity_revisions WHERE opportunity_id=? '
            'ORDER BY created_at DESC,revision_id DESC LIMIT 1',
            (row['opportunity_id'],)).fetchone()
        if not current:
            projection_problems.append({'opportunity_id': row['opportunity_id'],
                                        'reason': 'current_revision_missing'})
        else:
            if latest and current['revision_id'] != latest['revision_id']:
                projection_problems.append({'opportunity_id': row['opportunity_id'],
                                            'reason': 'current_revision_not_latest'})
            if (row['stage'], row['validation_state']) != (current['stage'],
                                                            current['validation_state']):
                projection_problems.append({'opportunity_id': row['opportunity_id'],
                                            'reason': 'projection_mismatch'})
        links = [dict(item) for item in conn.execute(
            'SELECT * FROM opportunity_links WHERE opportunity_id=?',
            (row['opportunity_id'],))]
        try:
            opportunity._validate_state(conn, row['validation_state'], links)
        except opportunity.OpportunityError as exc:
            state_problems.append({'opportunity_id': row['opportunity_id'],
                                   'validation_state': row['validation_state'],
                                   'reason': str(exc)})
    checks.append(_check('opportunity.projection_inconsistent', 'ERROR',
                         'Opportunity current projection/revision inconsistencies',
                         len(projection_problems),
                         _samples(projection_problems, ['opportunity_id', 'reason'])))
    checks.append(_check('opportunity.validation_gate_failed', 'ERROR',
                         'Opportunity current states that fail their evidence gate',
                         len(state_problems),
                         _samples(state_problems,
                                  ['opportunity_id', 'validation_state', 'reason'])))

    duplicates = [dict(row) for row in conn.execute(
        '''SELECT opportunity_id,target_kind,target_key,role,COUNT(*) AS n
           FROM opportunity_links
           GROUP BY opportunity_id,target_kind,target_key,role HAVING n>1''')]
    checks.append(_check('opportunity.duplicate_link', 'ERROR',
                         'Duplicate logical Opportunity links', len(duplicates),
                         _samples(duplicates,
                                  ['opportunity_id', 'target_kind', 'target_key', 'role'])))
    duplicate_keys = [dict(row) for row in conn.execute(
        'SELECT canonical_key,COUNT(*) AS n FROM opportunities '
        'GROUP BY canonical_key HAVING n>1')]
    checks.append(_check('opportunity.duplicate_canonical_key', 'ERROR',
                         'Duplicate Opportunity canonical keys', len(duplicate_keys),
                         _samples(duplicate_keys, ['canonical_key', 'n'])))
    return checks, info
