"""Deterministic B-lane seed promotion into the Opportunity database.

A B-lane article is a *signal*, not a confirmed commercial opportunity. This module
therefore creates only `signal_detected` Opportunities: the seed article, its event, its
evidence and its unverified claims are linked, while problem and buyer text stay explicitly
labelled as model hints. No problem_supported / buyer_identified / payment_verified state is
ever inferred here; those require a human review manifest or direct evidence.

The canonical key includes the article key so two different seeds are never merged by a
generic problem phrase. Merging requires a reviewed identity, which this module does not
claim to have.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import opportunity, opportunity_candidates, unified

RULES_VERSION = 'opp-v1'
AUTO_CONFIDENCE = 0.2
ELIGIBLE_SEED = 'EVIDENCE_BACKED_SEED'


def _text(value, limit=400):
    return ' '.join(str(value or '').split())[:limit]


def _hint(candidate):
    identity = candidate.get('identity') or {}
    problem = _text(identity.get('problem_hint') or identity.get('problem') or '')
    buyer = _text(identity.get('buyer_scope_hint') or identity.get('buyer_scope') or '')
    subject = _text(identity.get('subject') or '')
    kind = _text(identity.get('opportunity_kind_hint') or identity.get('opportunity_kind')
                 or 'signal')
    return subject, problem, buyer, kind


def _link_specs(candidate):
    specs = [{'target_kind': 'article', 'target_key': candidate['article_key'],
              'role': 'seed_signal', 'support': 'direct', 'method': 'deterministic',
              'confidence': 1.0}]
    if candidate.get('event_id'):
        specs.append({'target_kind': 'event', 'target_key': candidate['event_id'],
                      'role': 'context', 'support': 'context', 'method': 'deterministic',
                      'confidence': 1.0})
    for evidence in candidate.get('evidence_refs') or []:
        if evidence.get('evidence_id') and not evidence.get('problems'):
            specs.append({'target_kind': 'evidence', 'target_key': evidence['evidence_id'],
                          'role': 'context', 'support': 'indirect',
                          'method': 'deterministic', 'confidence': 1.0,
                          'locator': evidence.get('locator_json') or {}})
    for claim in candidate.get('claim_refs') or []:
        if claim.get('claim_id'):
            specs.append({'target_kind': 'claim', 'target_key': claim['claim_id'],
                          'role': 'unverified_claim', 'support': 'indirect',
                          'method': 'deterministic', 'confidence': 0.5})
    for entity in candidate.get('entity_refs') or []:
        if entity.get('entity_id'):
            specs.append({'target_kind': 'entity', 'target_key': entity['entity_id'],
                          'role': 'subject', 'support': 'context',
                          'method': 'deterministic', 'confidence': 0.5})
    return specs


def discover(db_path, limit=None):
    """Create `signal_detected` Opportunities for evidence-backed B seeds.

    Idempotent: an existing canonical key is returned untouched. The seed set is read from
    the same read-only candidate report the human reviewer sees, so there is one definition
    of what a B seed is.
    """
    report = opportunity_candidates.build_candidates(db_path)
    store = unified.UnifiedStore(db_path, migrate=False)
    created, existing, skipped, errors = 0, 0, 0, []
    candidates = [c for c in report.get('candidates') or []
                  if c.get('seed_class') == ELIGIBLE_SEED]
    if limit:
        candidates = candidates[:limit]
    for candidate in candidates:
        subject_hint, problem, buyer, kind = _hint(candidate)
        if not problem:
            skipped += 1
            continue
        # A deterministic, seed-scoped subject prevents a generic model phrase from merging
        # unrelated articles into one Opportunity.
        subject = subject_hint or f"seed:{candidate['article_key'][:16]}"
        title = _text(candidate.get('article_title') or problem, 200)
        try:
            result = opportunity.create_opportunity_with_links(
                store,
                subject=subject,
                problem_statement=problem,
                buyer_scope=buyer,
                opportunity_kind=kind or 'signal',
                title=title,
                stage='active',
                validation_state='signal_detected',
                confidence=AUTO_CONFIDENCE,
                rules_version=RULES_VERSION,
                actor='pipeline',
                note=('auto-discovered from B-lane evidence-backed seed; '
                      'problem/buyer are model hints, not confirmed facts'),
                links=_link_specs(candidate))
            if result.get('created'):
                created += 1
            else:
                existing += 1
        except Exception as exc:
            errors.append({'candidate_id': candidate.get('candidate_id'),
                           'error': f'{type(exc).__name__}: {exc}'[:300]})
    return {'eligible': len(candidates), 'created': created, 'existing': existing,
            'skipped_no_problem': skipped, 'errors': errors,
            'validation_state': 'signal_detected'}


if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Create signal_detected opportunities')
    parser.add_argument('--db', default='data/opportunity_radar.sqlite3')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    try:
        result = discover(args.db, args.limit)
    except Exception as exc:
        logging.exception('opportunity discovery failed')
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
