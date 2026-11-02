"""N4: deterministic normalization of N1 atoms under N2/N3 semantics.

N4 never calls a model and never re-decides what a number means or how it relates. It takes
the atom's written value/unit/scale/currency from N1, the subject/measure from N2 and the
relationship/period/baseline from N3, and produces a normalized record whose fields feed the
existing r2-v4 contract without double-scaling anything.

A missing period or baseline stays missing and is recorded as such. An unknown unit, an
ambiguous value or an unsupported relationship becomes an explicit status, never a default
that looks like a success.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import claim_contract, units

NODE = 'N4'
NODE_VERSION = 'n4-v2'
RULESET = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:16]
UNITS_VERSION = hashlib.sha256(Path(units.__file__).resolve().read_bytes()).hexdigest()[:16]

STATUSES = ('normalized', 'partially_normalized', 'unsupported_unit', 'ambiguous_numeric',
            'missing_semantics', 'invalid_relationship', 'unresolved')
SUPPORTED_RELATIONSHIPS = ('level', 'change', 'comparison', 'revision', 'share', 'rate')
PERIOD_NEEDED = ('change', 'comparison')
BASELINE_NEEDED = ('comparison', 'revision')


def _stable(value):
    """Upstream result without timing/retry bookkeeping."""
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if key not in ('seconds', 'batches',
                                                                   'output_hash')}


def input_hash(document, n1, n2, n3):
    from .semantic_common import hash_json, node_input_hash
    return node_input_hash({
        'node': NODE, 'node_version': NODE_VERSION,
        'document_id': document.get('document_id'),
        'text_hash': document.get('text_hash'),
        'n1_hash': hash_json(n1),
        'n2_hash': hash_json(_stable(n2)),
        'n3_hash': hash_json(_stable(n3)),
        'ruleset': RULESET, 'units_version': UNITS_VERSION,
    })


def _period_value(temporal):
    if not temporal:
        return ''
    kind = temporal.get('kind')
    if kind == 'year':
        return f"{temporal['year']:04d}"
    if kind == 'month' and temporal.get('year'):
        return f"{temporal['year']:04d}-{temporal['month']:02d}"
    if kind == 'day':
        return f"{temporal['year']:04d}-{temporal['month']:02d}-{temporal['day']:02d}"
    if kind == 'quarter' and temporal.get('year'):
        return f"{temporal['year']:04d}-Q{temporal['quarter']}"
    if kind == 'range':
        return f"{temporal['start_year']:04d}-{temporal['end_year']:04d}"
    if kind == 'fiscal_year':
        return f"{temporal['year']:04d}"
    return ''


def _period_from(ids, candidates, relationship):
    """(period, period_raw, candidate_id, evidence).

    A period candidate without a year (for example "september" or "second quarter") keeps its
    raw text and locator but has an empty normalized period. The program does not infer the
    year. A later candidate with a year for the same slot wins over the year-less one.
    """
    fallback = None
    for candidate_id in ids or []:
        candidate = candidates.get(candidate_id)
        if not candidate:
            continue
        raw_text = candidate.get('raw_text') or ''
        evidence = {'quote': raw_text, 'start': candidate.get('start'),
                    'end': candidate.get('end'), 'field': candidate.get('field') or ''}
        value = _period_value(candidate.get('temporal'))
        if value:
            return value, raw_text, candidate_id, evidence
        if fallback is None:
            fallback = ('', raw_text, candidate_id, evidence)
    if fallback is not None:
        return fallback
    raw = str(relationship.get('period_raw') or '').strip()
    if raw:
        evidence = {'quote': relationship.get('period_evidence_quote') or '',
                    'start': relationship.get('period_evidence_start'),
                    'end': relationship.get('period_evidence_end'),
                    'field': relationship.get('period_evidence_field') or ''}
        return (raw if claim_contract.valid_period(raw) else ''), raw, '', evidence
    return '', '', '', {'quote': '', 'start': None, 'end': None, 'field': ''}


def _baseline(ids, candidates):
    out = []
    for candidate_id in ids or []:
        candidate = candidates.get(candidate_id)
        if not candidate:
            continue
        out.append({'candidate_id': candidate_id,
                    'raw_text': candidate.get('raw_text'),
                    'value': candidate.get('value'),
                    'unit': candidate.get('unit'),
                    'scale': candidate.get('scale'),
                    'currency': candidate.get('currency'),
                    'candidate_type': candidate.get('candidate_type')})
    return out


def _unit_string(unit, scale, currency):
    base = unit or currency
    # Currency reads naturally first ('USD billion'); a physical unit keeps the scale in front
    # ('million vehicles'). split_unit accepts either order, so neither is a contract change.
    if scale and currency:
        return f'{currency} {scale}'
    if scale and base:
        return f'{scale} {base}'
    return scale or base


def _record(candidate, interpretation, relationship, period_ids, baseline_ids,
            denominator_ids, candidates, document, input_hash_value):
    deviations = []
    value = candidate.get('value')
    unit = candidate.get('unit') or ''
    scale = candidate.get('scale') or ''
    currency = candidate.get('currency') or ''
    flags = list(candidate.get('flags') or [])
    status = 'normalized'
    reason = ''

    if interpretation.get('status') not in ('resolved',):
        status = 'unresolved'
        reason = f"n2_{interpretation.get('status')}"
    if relationship.get('status') != 'resolved':
        status = 'unresolved' if relationship.get('status') != 'ambiguous' else 'ambiguous_numeric'
        reason = f"n3_relationship_{relationship.get('status')}"
    if relationship.get('relationship_type') not in SUPPORTED_RELATIONSHIPS:
        status = 'invalid_relationship'
        reason = f"unsupported_relationship_type:{relationship.get('relationship_type')}"
    if value is None:
        status = 'ambiguous_numeric'
        reason = 'candidate_has_no_numeric_value'
    if 'currency_conflict' in flags:
        status = 'ambiguous_numeric'
        reason = 'currency_conflict'
    family = candidate.get('unit_family') or 'unknown'
    if family == 'unknown' and unit:
        family = units.unit_family(unit)
    if unit and family == 'unknown':
        status = 'unsupported_unit'
        reason = f'unknown_unit:{unit}'
    if currency and currency not in units.CURRENCIES:
        status = 'ambiguous_numeric'
        reason = f'unknown_currency:{currency}'
    if 'parenthesized' in flags:
        deviations.append({'field': 'value', 'reason': 'parenthesized_sign_not_inferred',
                           'value': candidate.get('raw_text')})
    if 'scientific' in flags:
        deviations.append({'field': 'value', 'reason': 'scientific_notation',
                           'value': candidate.get('raw_text')})

    period, period_raw, period_id, period_evidence = _period_from(
        period_ids, candidates, relationship)
    if not period and relationship.get('relationship_type') in PERIOD_NEEDED:
        deviations.append({'field': 'period', 'reason': 'period_missing', 'value': ''})
        if status == 'normalized':
            status = 'partially_normalized'
    baseline = _baseline(baseline_ids, candidates)
    if not baseline and relationship.get('relationship_type') in BASELINE_NEEDED:
        deviations.append({'field': 'baseline', 'reason': 'baseline_missing', 'value': ''})
        if status == 'normalized':
            status = 'partially_normalized'
    denominator = ' / '.join(str(candidates[candidate_id].get('raw_text') or '')
                             for candidate_id in denominator_ids or []
                             if candidate_id in candidates)
    if relationship.get('comparison') == 'unknown':
        deviations.append({'field': 'comparison', 'reason': 'comparison_unknown', 'value': ''})

    evidence_quote = relationship.get('evidence_quote') or ''
    evidence_start = relationship.get('evidence_start')
    evidence_end = relationship.get('evidence_end')
    evidence_field = relationship.get('evidence_field')
    if not evidence_quote:
        evidence_quote = interpretation.get('evidence_quote') or ''
        evidence_start = interpretation.get('evidence_start')
        evidence_end = interpretation.get('evidence_end')
        evidence_field = interpretation.get('evidence_field')
    source_ids = [candidate['candidate_id']] + list(period_ids or []) + list(baseline_ids or []) \
        + list(denominator_ids or [])
    material = '\x00'.join((input_hash_value, candidate['candidate_id'],
                            str(relationship.get('relationship_id') or ''),
                            str(relationship.get('relationship_type') or ''), str(value),
                            unit, scale, currency, str(evidence_start), str(evidence_end)))
    record = {
        'record_id': 'n4_' + hashlib.sha256(material.encode('utf-8')).hexdigest()[:16],
        'candidate_id': candidate['candidate_id'],
        'candidate_type': candidate.get('candidate_type'),
        'relationship_id': relationship.get('relationship_id') or '',
        'relationship_type': relationship.get('relationship_type') or '',
        'value': value,
        'unit': unit,
        'scale': scale,
        'currency': currency,
        'unit_family': family,
        'unit_string': _unit_string(unit, scale, currency),
        'raw_value': candidate.get('number_raw') or candidate.get('raw_text') or '',
        'raw_unit': unit,
        'raw_scale': scale,
        'comparison': relationship.get('comparison') or 'unknown',
        'seasonality': relationship.get('seasonality') or 'unknown',
        'revision': relationship.get('revision') or 'unknown',
        'direction': relationship.get('direction') or 'unknown',
        'period': period,
        'period_raw': period_raw,
        'period_candidate_ids': list(period_ids or []),
        'period_evidence_quote': period_evidence['quote'],
        'period_evidence_start': period_evidence['start'],
        'period_evidence_end': period_evidence['end'],
        'period_evidence_field': period_evidence['field'],
        'period_source': relationship.get('period_source') or (
            'n3_period_candidate' if period_id else 'n3_period_raw' if period_raw else ''),
        'period_rule': relationship.get('period_rule') or '',
        'baseline': baseline,
        'baseline_candidate_ids': list(baseline_ids or []),
        'denominator': denominator,
        'denominator_candidate_ids': list(denominator_ids or []),
        'source_candidate_ids': sorted(set(value for value in source_ids if value)),
        'source_relationship_ids': [relationship.get('relationship_id')]
        if relationship.get('relationship_id') else [],
        'evidence_quote': evidence_quote,
        'evidence_start': evidence_start,
        'evidence_end': evidence_end,
        'evidence_field': evidence_field,
        'interpretation_quote': interpretation.get('evidence_quote') or '',
        'interpretation_start': interpretation.get('evidence_start'),
        'interpretation_end': interpretation.get('evidence_end'),
        'interpretation_field': interpretation.get('evidence_field'),
        'source': 'n3' if relationship.get('evidence_quote') else 'n2',
        'status': status,
        'reason': reason,
        'deviations': deviations,
    }
    return record


def _missing(candidate, interpretation, reason, input_hash_value):
    material = '\x00'.join((input_hash_value, candidate['candidate_id'], 'missing', reason))
    return {
        'record_id': 'n4_' + hashlib.sha256(material.encode('utf-8')).hexdigest()[:16],
        'candidate_id': candidate['candidate_id'],
        'candidate_type': candidate.get('candidate_type'),
        'relationship_id': '', 'relationship_type': '',
        'value': candidate.get('value'), 'unit': candidate.get('unit') or '',
        'scale': candidate.get('scale') or '', 'currency': candidate.get('currency') or '',
        'unit_family': units.unit_family(candidate.get('unit') or '')
        if candidate.get('unit') else 'unknown',
        'unit_string': _unit_string(candidate.get('unit') or '', candidate.get('scale') or '',
                                    candidate.get('currency') or ''),
        'raw_value': candidate.get('number_raw') or candidate.get('raw_text') or '',
        'raw_unit': candidate.get('unit') or '', 'raw_scale': candidate.get('scale') or '',
        'comparison': 'unknown', 'seasonality': 'unknown', 'revision': 'unknown',
        'direction': 'unknown', 'period': '', 'period_raw': '',
        'period_candidate_ids': [], 'period_evidence_quote': '',
        'period_evidence_start': None, 'period_evidence_end': None,
        'period_evidence_field': '', 'period_source': '', 'period_rule': '',
        'baseline': [], 'baseline_candidate_ids': [],
        'denominator': '', 'denominator_candidate_ids': [],
        'source_candidate_ids': [candidate['candidate_id']],
        'source_relationship_ids': [],
        'evidence_quote': interpretation.get('evidence_quote') or '',
        'evidence_start': interpretation.get('evidence_start'),
        'evidence_end': interpretation.get('evidence_end'),
        'evidence_field': interpretation.get('evidence_field'),
        'interpretation_quote': interpretation.get('evidence_quote') or '',
        'interpretation_start': interpretation.get('evidence_start'),
        'interpretation_end': interpretation.get('evidence_end'),
        'interpretation_field': interpretation.get('evidence_field'),
        'source': 'n2',
        'status': 'missing_semantics', 'reason': reason, 'deviations': [],
    }


def normalize(document, n1, n2, n3):
    """N4's output for one document. Purely deterministic."""
    if not isinstance(document, dict) or not all(
            isinstance(value, dict) for value in (n1, n2, n3)):
        raise ValueError('N4 needs the N0, N1, N2 and N3 dicts')
    for value in (n1, n2, n3):
        if document.get('document_id') != value.get('document_id'):
            raise ValueError('N4 inputs are from different documents')
    started = time.time()
    computed_hash = input_hash(document, n1, n2, n3)
    candidates = {candidate['candidate_id']: candidate for candidate in n1.get('candidates') or []}
    interpretations = {item.get('candidate_id'): item
                       for item in n2.get('candidate_interpretations') or []}
    relationships = list(n3.get('relationships') or [])
    claim_values = [candidate_id for candidate_id, item in interpretations.items()
                    if item.get('disposition') == 'claim_value'
                    and item.get('status') == 'resolved' and candidate_id in candidates]
    records = []
    covered = set()
    for relationship in relationships:
        if relationship.get('status') not in ('resolved', 'ambiguous'):
            for candidate_id in relationship.get('value_candidate_ids') or []:
                candidate = candidates.get(candidate_id)
                interpretation = interpretations.get(candidate_id)
                if not candidate or not interpretation:
                    continue
                if interpretation.get('disposition') != 'claim_value':
                    continue
                records.append(_record(candidate, interpretation, relationship, [], [], [],
                                       candidates, document, computed_hash))
                covered.add(candidate_id)
            continue
        for candidate_id in relationship.get('value_candidate_ids') or []:
            candidate = candidates.get(candidate_id)
            interpretation = interpretations.get(candidate_id)
            if not candidate or not interpretation:
                continue
            if interpretation.get('disposition') != 'claim_value':
                continue
            records.append(_record(candidate, interpretation, relationship,
                                   relationship.get('period_candidate_ids') or [],
                                   relationship.get('baseline_candidate_ids') or [],
                                   relationship.get('denominator_candidate_ids') or [],
                                   candidates, document, computed_hash))
            covered.add(candidate_id)
    for candidate_id in claim_values:
        if candidate_id in covered:
            continue
        records.append(_missing(candidates[candidate_id], interpretations[candidate_id],
                                'no_relationship_value', computed_hash))
    records.sort(key=lambda item: (item.get('evidence_start') if item.get('evidence_start')
                                   is not None else 10 ** 12,
                                   item['candidate_id'], item['relationship_id']))
    by_status = {}
    for record in records:
        by_status[record['status']] = by_status.get(record['status'], 0) + 1
    statistics = {'input_candidates': len(candidates), 'claim_values': len(claim_values),
                  'records': len(records), 'by_status': by_status,
                  'relationships': len(relationships)}
    if n2.get('status') not in ('success', 'partial'):
        status = 'failed'
    elif not claim_values:
        status = 'success'
    elif all(value in ('normalized', 'partially_normalized') for value in by_status):
        status = 'success' if set(by_status) == {'normalized'} else 'partial'
    elif any(value in ('normalized', 'partially_normalized') for value in by_status):
        status = 'partial'
    else:
        status = 'failed'
    result = {
        'node': NODE, 'node_version': NODE_VERSION,
        'document_id': document.get('document_id'),
        'input_hash': computed_hash, 'ruleset': RULESET, 'units_version': UNITS_VERSION,
        'normalized_records': records, 'statistics': statistics, 'status': status,
    }
    result['output_hash'] = hashlib.sha256(
        json.dumps(_stable(result), ensure_ascii=False,
                   sort_keys=True).encode('utf-8')).hexdigest()
    result['seconds'] = round(time.time() - started, 2)
    return result
