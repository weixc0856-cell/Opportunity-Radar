"""Deterministic claim verification (R2, rules r2-v1).

What this module decides, and what it refuses to decide:

* It checks a claim against the evidence it cites: is the value in the quote, is the unit
  the same kind of thing, does the period match the evidence record, is a percentage being
  passed off as a percentage point, does the comparison wording agree.
* `verified` therefore means "this claim reproduces its evidence correctly". For a filing
  record that is a real check; it is not independent confirmation that the filing is right.
* A claim with no structured fields - every claim the v5 prompt produced - is
  `unverifiable`. Prose is not a verified number, and saying so is the whole point.

Every run appends a verification record and updates the claim's state. Re-running with the
same inputs changes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import claim_contract, units
from .unified import UnifiedStore, now, stable_id

RULES_VERSION = 'r2-v1'
SUPPORTS = ('direct', 'indirect', 'unsupported', 'contradiction')
FAILING = ('fail',)

YOY_WORDS = ('year-over-year', 'year over year', 'yoy', '同比', '较上年同期', 'from a year earlier')
MOM_WORDS = ('month-over-month', 'month over month', 'mom', '环比', 'from the previous month')
QOQ_WORDS = ('quarter-over-quarter', 'quarter over quarter', 'qoq', '环比', '较上季度')


def _norm(text):
    return ' '.join(str(text or '').lower().split())


def _period_end(period):
    text = str(period or '')
    return text.split('/')[-1][:10] if '/' in text else text[:10]


def classify_support(claim, evidence):
    """(support, reason): does the quote say what the claim says it says?"""
    quote = _norm(evidence.get('quote'))
    if not quote:
        return 'unsupported', 'no_quote'
    value = claim.get('value_num')
    if value is None:
        return 'direct', 'quote_present_no_value'
    base_unit, scale = units.split_unit(claim.get('unit'))
    family = units.unit_family(base_unit)
    claim_value = float(value) * scale
    comparable = [(v, u) for v, u in units.quantities(quote) if u and units.unit_family(u) == family]
    if not comparable:
        # No number of the same kind in the quote; a bare number elsewhere is not evidence.
        return 'unsupported', 'no_comparable_value'
    if any(units.same_number(v, claim_value) for v, _ in comparable):
        return 'direct', 'value_in_quote'
    return 'contradiction', 'quote_has_different_value'


def _check_value(claim, evidence, support):
    if claim.get('value_num') is None:
        return {'name': 'value_in_quote', 'result': 'skip', 'detail': 'claim has no numeric value'}
    if support == 'direct':
        return {'name': 'value_in_quote', 'result': 'pass', 'detail': 'value found in the quote'}
    if support == 'contradiction':
        return {'name': 'value_in_quote', 'result': 'fail', 'detail': 'the quote states a different value'}
    return {'name': 'value_in_quote', 'result': 'fail', 'detail': 'the quote has no comparable value'}


def _check_unit(claim, evidence):
    unit = units.normalize_unit(claim.get('unit'))
    if not unit:
        return {'name': 'unit', 'result': 'skip', 'detail': 'claim declares no unit'}
    quote_units = [u for _, u in units.quantities(_norm(evidence.get('quote'))) if u]
    if not quote_units:
        return {'name': 'unit', 'result': 'fail', 'detail': 'the quote carries no unit to compare'}
    claim_family = units.unit_family(unit)
    if any(units.unit_family(u) == claim_family for u in quote_units):
        if claim_family == 'percent':
            kinds = {units.percent_or_point(u) for u in quote_units}
            if units.percent_or_point(unit) not in kinds:
                return {'name': 'unit', 'result': 'fail',
                        'detail': 'percentage and percentage point are different quantities'}
        return {'name': 'unit', 'result': 'pass', 'detail': f'quote unit is {claim_family}'}
    return {'name': 'unit', 'result': 'fail',
            'detail': f'quote units {sorted(set(quote_units))} are not {claim_family}'}


def _check_period(claim, evidence):
    period = str(claim.get('period') or '')
    if not period:
        return {'name': 'period', 'result': 'skip', 'detail': 'claim declares no period'}
    try:
        locator = json.loads(evidence.get('locator_json') or '{}')
    except ValueError:
        locator = {}
    evidence_period = locator.get('period') or locator.get('period_end') or ''
    if not evidence_period:
        return {'name': 'period', 'result': 'skip', 'detail': 'the evidence carries no period'}
    if _period_end(period) == str(evidence_period)[:10]:
        return {'name': 'period', 'result': 'pass', 'detail': f'{period} matches {evidence_period}'}
    return {'name': 'period', 'result': 'fail',
            'detail': f'claim period {period} does not match evidence period {evidence_period}'}


def _check_comparison(claim, evidence):
    comparison = str(claim.get('comparison') or 'unknown')
    if comparison in ('', 'unknown', 'level'):
        return {'name': 'comparison', 'result': 'skip', 'detail': 'no comparison to check'}
    quote = _norm(evidence.get('quote'))
    words = {'year_over_year': YOY_WORDS, 'month_over_month': MOM_WORDS,
             'quarter_over_quarter': QOQ_WORDS}.get(comparison)
    if not words:
        return {'name': 'comparison', 'result': 'skip', 'detail': f'{comparison} is not phrase-checkable'}
    declared = any(word in quote for word in words)
    others = [name for name, group in (('year_over_year', YOY_WORDS), ('month_over_month', MOM_WORDS),
                                       ('quarter_over_quarter', QOQ_WORDS))
              if name != comparison and any(word in quote for word in group)]
    if declared:
        return {'name': 'comparison', 'result': 'pass', 'detail': f'quote says {comparison}'}
    if others:
        return {'name': 'comparison', 'result': 'fail',
                'detail': f'claim says {comparison}, quote says {others[0]}'}
    return {'name': 'comparison', 'result': 'skip', 'detail': 'quote states no comparison basis'}


def check_claim(claim, evidence):
    """One claim against one evidence. Returns state, support, basis and every check."""
    if claim.get('extractor') == 'skeleton' or (claim.get('value_num') is None
                                                and (claim.get('predicate') or '') == 'assertion'):
        support = 'direct' if (evidence or {}).get('quote') else 'unsupported'
        return {'state': 'unverifiable', 'support': support, 'basis': 'skeleton_no_structured_fields',
                'checks': [{'name': 'structured_fields', 'result': 'skip',
                            'detail': 'claim carries prose only; nothing to verify numerically'}],
                'deviations': []}
    if not evidence:
        return {'state': 'unverifiable', 'support': 'unsupported', 'basis': 'no_evidence',
                'checks': [{'name': 'evidence', 'result': 'fail', 'detail': 'claim cites no evidence'}],
                'deviations': []}
    fields = {k: claim.get(k) for k in ('subject', 'predicate', 'kind', 'value_num', 'value_text',
                                        'unit', 'currency', 'period', 'comparison', 'seasonality',
                                        'revision', 'region', 'denominator', 'quote')}
    # A structured claim keeps its quote on the evidence, not on the claim row.
    fields['quote'] = fields.get('quote') or (evidence.get('quote') or '')
    contract, deviations = claim_contract.normalize(fields)
    support, support_reason = classify_support(contract, evidence)
    checks = [_check_value(contract, evidence, support),
              _check_unit(contract, evidence),
              _check_period(contract, evidence),
              _check_comparison(contract, evidence)]
    failed = [c for c in checks if c['result'] in FAILING]
    passed = [c for c in checks if c['result'] == 'pass']
    if failed:
        state, basis = 'rejected', failed[0]['name'] + ': ' + failed[0]['detail']
    elif passed:
        state = 'verified'
        basis = ('structured_quote_support' if support == 'direct' else 'partial')
    else:
        state, basis = 'unverifiable', 'no check could be applied'
    return {'state': state, 'support': support, 'basis': basis,
            'checks': checks + [{'name': 'quote_support', 'result': support,
                                 'detail': support_reason}],
            'deviations': deviations}


def _evidence_for(conn, claim_id):
    row = conn.execute('''SELECT v.* FROM claim_evidence ce JOIN evidences v USING(evidence_id)
                          WHERE ce.claim_id=? ORDER BY v.evidence_id LIMIT 1''', (claim_id,)).fetchone()
    return dict(row) if row else None


# Only the fields the verdict reads. Hashing the whole row would make every run look like a
# new input, because the previous run just wrote its own verdict into it.
INPUT_FIELDS = ('claim_id', 'subject', 'predicate', 'kind', 'value_num', 'value_text', 'unit',
                'currency', 'period', 'comparison', 'seasonality', 'revision', 'region',
                'denominator', 'quote', 'extractor', 'locator_json')


def _input_hash(claim, evidence):
    payload = json.dumps({'claim': {k: claim.get(k) for k in INPUT_FIELDS},
                          'evidence': {k: (evidence or {}).get(k) for k in
                                       ('evidence_id', 'quote', 'locator_json')}},
                         sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def verify(store, limit=None, dry_run=False):
    """Verify every claim in the database. Writes only when a verdict is new."""
    report = {'claims': 0, 'by_state': {}, 'by_support': {}, 'written': 0, 'deviations': 0, 'dry_run': dry_run}
    with store.connect() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM claims ORDER BY claim_id')]
    if limit:
        rows = rows[:limit]
    verdicts = []
    for claim in rows:
        with store.connect() as conn:
            evidence = _evidence_for(conn, claim['claim_id'])
        verdict = check_claim(claim, evidence)
        verdicts.append((claim, evidence, verdict))
        report['claims'] += 1
        report['by_state'][verdict['state']] = report['by_state'].get(verdict['state'], 0) + 1
        report['by_support'][verdict['support']] = report['by_support'].get(verdict['support'], 0) + 1
        report['deviations'] += len(verdict['deviations'])
    if dry_run:
        return report
    with store.connect() as conn:
        for claim, evidence, verdict in verdicts:
            input_hash = _input_hash(claim, evidence)
            conn.execute('INSERT OR IGNORE INTO claim_verifications(verification_id,claim_id,rules_version,'
                         'input_hash,state,support,basis,checks_json,deviations_json,created_at) '
                         'VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (stable_id('ver-', claim['claim_id'], RULES_VERSION, input_hash),
                          claim['claim_id'], RULES_VERSION, input_hash, verdict['state'], verdict['support'],
                          verdict['basis'], json.dumps(verdict['checks'], ensure_ascii=False, sort_keys=True),
                          json.dumps(verdict['deviations'], ensure_ascii=False, sort_keys=True), now()))
            report['written'] += 1
            conn.execute('UPDATE claims SET verification_state=?, verified_at=?, verification_basis=? WHERE claim_id=?',
                         (verdict['state'], now(), verdict['basis'][:300], claim['claim_id']))
            if evidence:
                conn.execute('UPDATE claim_evidence SET support=? WHERE claim_id=? AND evidence_id=?',
                             (verdict['support'], claim['claim_id'], evidence['evidence_id']))
    report['conflicts'] = find_conflicts(store)
    return report


def find_conflicts(store):
    """Same subject + measure + period + unit with different values. Revisions are noted, not hidden."""
    written = 0
    with store.connect() as conn:
        groups = [tuple(r) for r in conn.execute(
            '''SELECT subject, predicate, period, unit, COUNT(DISTINCT value_num) n
               FROM claims WHERE value_num IS NOT NULL AND period<>''
               GROUP BY subject, predicate, period, unit HAVING n>1''')]
        for subject, predicate, period, unit, _n in groups:
            rows = [dict(r) for r in conn.execute(
                '''SELECT claim_id, value_num, revision, article_key FROM claims
                   WHERE subject=? AND predicate=? AND period=? AND unit=? AND value_num IS NOT NULL
                   ORDER BY claim_id''', (subject, predicate, period, unit))]
            for i, left in enumerate(rows):
                for right in rows[i + 1:]:
                    if units.same_number(left['value_num'], right['value_num']):
                        continue
                    written += conn.execute(
                        'INSERT OR IGNORE INTO claim_conflicts(conflict_id,claim_a,claim_b,reason,detail_json,created_at) '
                        'VALUES(?,?,?,?,?,?)',
                        (stable_id('con-', left['claim_id'], right['claim_id'], 'value_differs'),
                         left['claim_id'], right['claim_id'], 'value_differs_same_measure',
                         json.dumps({'subject': subject, 'predicate': predicate, 'period': period,
                                     'unit': unit, 'a': left['value_num'], 'b': right['value_num'],
                                     'revision_a': left['revision'], 'revision_b': right['revision']},
                                    ensure_ascii=False, sort_keys=True), now())).rowcount
    return written


def summary(store):
    with store.connect() as conn:
        out = {'claims_by_state': {r[0]: r[1] for r in conn.execute(
                   'SELECT verification_state, COUNT(*) FROM claims GROUP BY 1 ORDER BY 2 DESC')},
               'verifications': conn.execute('SELECT COUNT(*) FROM claim_verifications').fetchone()[0],
               'conflicts': conn.execute('SELECT COUNT(*) FROM claim_conflicts').fetchone()[0],
               'by_support': {r[0]: r[1] for r in conn.execute(
                   'SELECT support, COUNT(*) FROM claim_evidence GROUP BY 1 ORDER BY 2 DESC')}}
        rows = [dict(r) for r in conn.execute(
            'SELECT state, rules_version, COUNT(*) n FROM claim_verifications GROUP BY 1,2')]
        out['verification_history'] = rows
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description='Verify structured claims against their evidence')
    parser.add_argument('--db', help='database to verify')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args(argv)
    db = args.db or 'data/opportunity_radar.sqlite3'
    store = UnifiedStore(db)
    output = summary(store) if args.summary else verify(store, limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
