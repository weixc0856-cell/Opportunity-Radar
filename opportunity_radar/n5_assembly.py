"""N5: completeness gate and r2-v4 shadow claim assembly.

N5 is the only node that writes a Claim, and it writes a shadow Claim. It takes subject,
measure and kind from N2; value, unit, scale and currency from N4; relationship, comparison,
period and baseline from N3 only as explicitly provided. It does not call a model and does
not fill a missing period, baseline, subject or measure.

Its main output is not the claim count but the disposition of every N1 candidate: accepted
claim, context_only, non_claim, ambiguous, unresolved, relationship unassigned, normalization
failure, or an explicit rejection reason.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import claim_contract, units
from .semantic_common import hash_json, locate_quote, node_input_hash

NODE = 'N5'
NODE_VERSION = 'n5-v1'
RULESET = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:16]
CONTRACT_VERSION = claim_contract.CONTRACT_VERSION
CONTRACT_HASH = hashlib.sha256(
    Path(claim_contract.__file__).resolve().read_bytes()).hexdigest()[:16]

CRITICAL_DEVIATIONS = ('missing', 'not_numeric', 'unknown_unit', 'unknown_currency',
                       'unrecognised_format')


def _stable(value):
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if key not in ('seconds', 'batches',
                                                                   'output_hash')}


def input_hash(document, n1, n2, n3, n4):
    return node_input_hash({
        'node': NODE, 'node_version': NODE_VERSION,
        'document_id': document.get('document_id'),
        'text_hash': document.get('text_hash'),
        'n1_hash': hash_json(n1),
        'n2_hash': hash_json(_stable(n2)),
        'n3_hash': hash_json(_stable(n3)),
        'n4_hash': hash_json(_stable(n4)),
        'contract_version': CONTRACT_VERSION, 'contract_hash': CONTRACT_HASH,
        'ruleset': RULESET,
    })


def _claim_id(input_hash_value, record, subject, predicate, quote):
    material = '\x00'.join((input_hash_value, record['record_id'], subject, predicate,
                            str(record.get('value')), str(record.get('unit_string')),
                            str(record.get('period')), str(record.get('comparison')), quote))
    return 'c_' + hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]


def _evidence(document, interpretation, record):
    """(quote, start, end, field) preferring the N2 quote, which names the subject."""
    options = []
    if interpretation:
        options.append((interpretation.get('evidence_quote'),
                        interpretation.get('evidence_start'),
                        interpretation.get('evidence_end'),
                        interpretation.get('evidence_field')))
    options.append((record.get('evidence_quote'), record.get('evidence_start'),
                    record.get('evidence_end'), record.get('evidence_field')))
    located = []
    for quote, start, end, field in options:
        quote = str(quote or '').strip()
        if not quote:
            continue
        if start is not None and end is not None:
            if document['text'][start:end].lower() == quote.lower():
                located.append((quote, start, end, field or ''))
                continue
        sentence_ids = (interpretation or {}).get('evidence_sentence_ids') or []
        locator = locate_quote(document, sentence_ids, quote)
        if locator:
            located.append((quote, locator[0], locator[1], locator[2]))
    for item in located:
        if item[3] != 'title':
            return item
    return located[0] if located else ('', None, None, '')


def _payload(record, interpretation, document):
    quote, start, end, field = _evidence(document, interpretation, record)
    payload = {
        'subject': interpretation.get('subject') or '',
        'predicate': interpretation.get('predicate') or '',
        'kind': interpretation.get('kind') or 'unknown',
        'value_num': record.get('value'),
        'value_text': quote,
        'unit': record.get('unit_string') or '',
        'currency': record.get('currency') or '',
        'period': record.get('period') or '',
        'comparison': record.get('comparison') or 'unknown',
        'seasonality': record.get('seasonality') or 'unknown',
        'revision': record.get('revision') or 'unknown',
        'denominator': record.get('denominator') or '',
        'region': '',
        'quote': quote,
    }
    meta = {'quote': quote, 'start': start, 'end': end, 'field': field}
    return payload, meta


def _critical(deviations):
    return [deviation for deviation in deviations
            if deviation.get('reason') in CRITICAL_DEVIATIONS]


def _disposition_for(candidate, interpretation, records, accepted, roles,
                     rejected_by_candidate=None):
    candidate_id = candidate['candidate_id']
    rejected_by_candidate = rejected_by_candidate or {}
    if not interpretation:
        return {'candidate_id': candidate_id, 'status': 'unresolved',
                'reason': 'n2_missing', 'claim_ids': []}
    disposition = interpretation.get('disposition')
    if disposition == 'context_only':
        return {'candidate_id': candidate_id, 'status': 'context_only',
                'reason': 'n2_context_only', 'claim_ids': []}
    if disposition == 'non_claim':
        return {'candidate_id': candidate_id, 'status': 'non_claim',
                'reason': 'n2_non_claim', 'claim_ids': []}
    if disposition == 'ambiguous':
        return {'candidate_id': candidate_id, 'status': 'ambiguous',
                'reason': 'n2_ambiguous', 'claim_ids': []}
    if disposition == 'unresolved':
        return {'candidate_id': candidate_id, 'status': 'unresolved',
                'reason': 'n2_unresolved', 'claim_ids': []}
    if disposition == 'claim_value' and interpretation.get('status') != 'resolved':
        status = 'ambiguous' if interpretation.get('status') == 'ambiguous' else 'unresolved'
        return {'candidate_id': candidate_id, 'status': status,
                'reason': f"n2_{interpretation.get('status')}", 'claim_ids': []}
    if accepted.get(candidate_id):
        return {'candidate_id': candidate_id, 'status': 'claim_accepted',
                'reason': 'assembled', 'claim_ids': sorted(accepted[candidate_id])}
    relevant = records.get(candidate_id, [])
    if relevant:
        statuses = [record.get('status') for record in relevant]
        if 'unsupported_unit' in statuses:
            return {'candidate_id': candidate_id, 'status': 'normalization_failed',
                    'reason': 'unsupported_unit', 'claim_ids': []}
        if 'invalid_relationship' in statuses:
            return {'candidate_id': candidate_id, 'status': 'rejected',
                    'reason': 'invalid_relationship', 'claim_ids': []}
        if 'ambiguous_numeric' in statuses:
            return {'candidate_id': candidate_id, 'status': 'ambiguous',
                    'reason': 'ambiguous_numeric', 'claim_ids': []}
        if 'unresolved' in statuses:
            return {'candidate_id': candidate_id, 'status': 'unresolved',
                    'reason': 'n3_unresolved', 'claim_ids': []}
        if 'missing_semantics' in statuses:
            return {'candidate_id': candidate_id, 'status': 'relationship_unassigned',
                    'reason': 'no_relationship_value', 'claim_ids': []}
        if rejected_by_candidate.get(candidate_id):
            return {'candidate_id': candidate_id, 'status': 'rejected',
                    'reason': rejected_by_candidate[candidate_id][0], 'claim_ids': []}
        return {'candidate_id': candidate_id, 'status': 'normalization_failed',
                'reason': 'normalization_failed', 'claim_ids': []}
    if rejected_by_candidate.get(candidate_id):
        return {'candidate_id': candidate_id, 'status': 'rejected',
                'reason': rejected_by_candidate[candidate_id][0], 'claim_ids': []}
    if candidate_id in roles:
        return {'candidate_id': candidate_id, 'status': 'used_as_context',
                'reason': ','.join(sorted(roles[candidate_id])), 'claim_ids': []}
    return {'candidate_id': candidate_id, 'status': 'relationship_unassigned',
            'reason': 'no_n3_relationship', 'claim_ids': []}


def assemble(document, n1, n2, n3, n4):
    """N5's output for one document. No model calls, no production writes."""
    if not all(isinstance(value, dict) for value in (document, n1, n2, n3, n4)):
        raise ValueError('N5 needs the N0, N1, N2, N3 and N4 dicts')
    for value in (n1, n2, n3, n4):
        if document.get('document_id') != value.get('document_id'):
            raise ValueError('N5 inputs are from different documents')
    started = time.time()
    computed_hash = input_hash(document, n1, n2, n3, n4)
    candidates = {candidate['candidate_id']: candidate for candidate in n1.get('candidates') or []}
    interpretations = {item.get('candidate_id'): item
                       for item in n2.get('candidate_interpretations') or []}
    records = {}
    for record in n4.get('normalized_records') or []:
        records.setdefault(record['candidate_id'], []).append(record)
    roles = {}
    for relationship in n3.get('relationships') or []:
        for field, role in (('value_candidate_ids', 'value'),
                            ('baseline_candidate_ids', 'baseline'),
                            ('period_candidate_ids', 'period'),
                            ('comparison_period_candidate_ids', 'comparison_period'),
                            ('denominator_candidate_ids', 'denominator')):
            for candidate_id in relationship.get(field) or []:
                roles.setdefault(candidate_id, set()).add(role)

    claims, rejected, unresolved, duplicates = [], [], [], []
    accepted = {}
    seen = {}
    payloads = []
    claim_meta = []
    if n2.get('status') not in ('success', 'partial'):
        result = {
            'node': NODE, 'node_version': NODE_VERSION,
            'document_id': document.get('document_id'), 'input_hash': computed_hash,
            'ruleset': RULESET, 'contract_version': CONTRACT_VERSION,
            'contract_hash': CONTRACT_HASH, 'claims': [], 'candidate_dispositions': [
                _disposition_for(candidate, interpretations.get(candidate['candidate_id']),
                                 records, {}, roles)
                for candidate in n1.get('candidates') or []],
            'rejected_items': [], 'unresolved_items': [
                {'candidate_id': candidate['candidate_id'], 'reason': 'n2_not_successful'}
                for candidate in n1.get('candidates') or []],
            'coverage_statistics': {}, 'contract_validation': {},
            'status': 'blocked', 'seconds': round(time.time() - started, 2),
        }
        return result
    for candidate_id, candidate in candidates.items():
        interpretation = interpretations.get(candidate_id)
        if not interpretation or interpretation.get('disposition') != 'claim_value':
            continue
        accepted_here = []
        for record in records.get(candidate_id, []):
            if record.get('status') not in ('normalized', 'partially_normalized'):
                reason = record.get('reason') or record.get('status')
                (unresolved if record.get('status') in ('missing_semantics', 'unresolved')
                 else rejected).append({'candidate_id': candidate_id,
                                        'relationship_id': record.get('relationship_id'),
                                        'n4_record_id': record.get('record_id'),
                                        'reason': reason, 'status': record.get('status')})
                continue
            payload, meta = _payload(record, interpretation, document)
            if not meta['quote']:
                rejected.append({'candidate_id': candidate_id,
                                 'relationship_id': record.get('relationship_id'),
                                 'n4_record_id': record.get('record_id'),
                                 'reason': 'evidence_missing', 'status': 'rejected'})
                continue
            if meta['field'] == 'title':
                rejected.append({'candidate_id': candidate_id,
                                 'relationship_id': record.get('relationship_id'),
                                 'n4_record_id': record.get('record_id'),
                                 'reason': 'title_only_evidence', 'status': 'rejected'})
                continue
            claim, deviations = claim_contract.normalize(payload)
            critical = _critical(deviations)
            if (critical or not claim['subject'] or not claim['predicate']
                    or claim['value_num'] is None):
                rejected.append({'candidate_id': candidate_id,
                                 'relationship_id': record.get('relationship_id'),
                                 'n4_record_id': record.get('record_id'),
                                 'reason': 'contract_invalid',
                                 'status': 'rejected',
                                 'deviations': critical or deviations})
                continue
            key = (claim['subject'].lower(), claim['predicate'].lower(), claim['kind'],
                   claim['value_num'], claim['unit'], claim['scale'], claim['currency'],
                   claim['period'], claim['comparison'], record.get('relationship_type'))
            if key in seen:
                duplicates.append({'candidate_id': candidate_id,
                                   'n4_record_id': record.get('record_id'),
                                   'reason': 'duplicate_claim',
                                   'duplicate_of': seen[key]})
                continue
            claim_id = _claim_id(computed_hash, record, claim['subject'],
                                 claim['predicate'], claim['quote'])
            seen[key] = claim_id
            accepted_here.append(claim_id)
            payloads.append(payload)
            claim_meta.append({'claim_id': claim_id, 'record': record,
                               'interpretation': interpretation, 'meta': meta,
                               'deviations': deviations})
        accepted[candidate_id] = accepted_here

    parsed, contract_deviations = claim_contract.parse_claims({'claims': payloads}) \
        if payloads else ([], [])
    parsed_by_ordinal = {item['ordinal']: item for item in parsed}
    for index, meta in enumerate(claim_meta, 1):
        claim = parsed_by_ordinal.get(index)
        if claim is None:
            rejected.append({'candidate_id': meta['record']['candidate_id'],
                             'n4_record_id': meta['record']['record_id'],
                             'reason': 'contract_parse_failed',
                             'status': 'rejected',
                             'deviations': [deviation for deviation in contract_deviations
                                            if deviation.get('ordinal') == index]})
            continue
        record = meta['record']
        interpretation = meta['interpretation']
        claim['claim_id'] = meta['claim_id']
        claim['status'] = 'accepted'
        claim['deviations'] = ([deviation for deviation in contract_deviations
                                if deviation.get('ordinal') == index]
                               + list(record.get('deviations') or []))
        claim['trace'] = {
            'candidate_ids': record.get('source_candidate_ids') or [record['candidate_id']],
            'value_candidate_id': record['candidate_id'],
            'relationship_id': record.get('relationship_id') or '',
            'n4_record_id': record.get('record_id'),
            'n4_status': record.get('status') or '',
            'n4_deviations': record.get('deviations') or [],
            'relationship_type': record.get('relationship_type') or '',
            'direction': record.get('direction') or 'unknown',
            'baseline': record.get('baseline') or [],
            'period_candidate_ids': record.get('period_candidate_ids') or [],
            'denominator_candidate_ids': record.get('denominator_candidate_ids') or [],
            'evidence_sentence_ids': interpretation.get('evidence_sentence_ids') or [],
            'evidence_start': meta['meta']['start'], 'evidence_end': meta['meta']['end'],
            'evidence_field': meta['meta']['field'],
            'n2_subject': interpretation.get('subject') or '',
            'n2_predicate': interpretation.get('predicate') or '',
        }
        claims.append(claim)
    claims.sort(key=lambda item: (item['trace']['evidence_start']
                                  if item['trace']['evidence_start'] is not None else 10 ** 12,
                                  item['subject'], item['predicate'], item['value_num']))
    rejected_by_candidate = {}
    for item in rejected:
        rejected_by_candidate.setdefault(item['candidate_id'], []).append(item['reason'])
    dispositions = [_disposition_for(candidates[candidate_id],
                                     interpretations.get(candidate_id),
                                     records, accepted, roles, rejected_by_candidate)
                    for candidate_id in candidates]
    for item in dispositions:
        if item['status'] in ('ambiguous', 'unresolved', 'relationship_unassigned'):
            unresolved.append({'candidate_id': item['candidate_id'],
                               'reason': item['reason']})
    rejected.extend(duplicates)
    disposition_counts = {}
    for item in dispositions:
        disposition_counts[item['status']] = disposition_counts.get(item['status'], 0) + 1
    by_record_status = {}
    for record in n4.get('normalized_records') or []:
        by_record_status[record.get('status')] = by_record_status.get(record.get('status'), 0) + 1
    claim_value_total = sum(1 for item in interpretations.values()
                            if item.get('disposition') == 'claim_value')
    claim_value_resolved = sum(1 for item in interpretations.values()
                               if item.get('disposition') == 'claim_value'
                               and item.get('status') == 'resolved')
    coverage = {
        'input_candidates': len(candidates),
        'accepted_candidates': sum(1 for item in dispositions
                                   if item['status'] == 'claim_accepted'),
        'assembled_claims': len(claims),
        'claim_value_total': claim_value_total,
        'claim_value_resolved': claim_value_resolved,
        'context_only': sum(1 for item in interpretations.values()
                            if item.get('disposition') == 'context_only'),
        'non_claim': sum(1 for item in interpretations.values()
                         if item.get('disposition') == 'non_claim'),
        'n2_ambiguous': sum(1 for item in interpretations.values()
                            if item.get('status') == 'ambiguous'),
        'n2_unresolved': sum(1 for item in interpretations.values()
                             if item.get('status') == 'unresolved'),
        'relationship_assigned': sum(1 for candidate_id in candidates
                                     if 'value' in roles.get(candidate_id, set())),
        'n4_records': len(n4.get('normalized_records') or []),
        'n4_by_status': by_record_status,
        'claims_rejected': len(rejected),
        'duplicate_claims': len(duplicates),
        'disposition_counts': disposition_counts,
        'coverage_complete': (len(dispositions) == len(candidates)
                              and len({item['candidate_id'] for item in dispositions})
                              == len(candidates)),
    }
    terminal = {'claim_accepted', 'context_only', 'non_claim', 'used_as_context'}
    if not coverage['coverage_complete']:
        status = 'failed'
    elif (all(item['status'] in terminal for item in dispositions)
          and n4.get('status') == 'success'):
        status = 'success'
    else:
        status = 'partial'
    result = {
        'node': NODE, 'node_version': NODE_VERSION,
        'document_id': document.get('document_id'), 'input_hash': computed_hash,
        'ruleset': RULESET, 'contract_version': CONTRACT_VERSION,
        'contract_hash': CONTRACT_HASH,
        'claims': claims, 'candidate_dispositions': dispositions,
        'rejected_items': rejected, 'unresolved_items': unresolved,
        'coverage_statistics': coverage,
        'contract_validation': {
            'version': CONTRACT_VERSION, 'schema_hash': CONTRACT_HASH,
            'claims_checked': len(payloads), 'claims_valid': len(parsed),
            'deviations': contract_deviations,
            'valid': len(parsed) == len(payloads),
        },
        'duplicates': duplicates,
        'status': status,
    }
    result['output_hash'] = hashlib.sha256(
        json.dumps(_stable(result), ensure_ascii=False,
                   sort_keys=True).encode('utf-8')).hexdigest()
    result['seconds'] = round(time.time() - started, 2)
    return result
