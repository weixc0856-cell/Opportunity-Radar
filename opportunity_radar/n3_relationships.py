"""N3: what relation does the text state between the numbers N2 identified?

N3 reads N0, N1 and the successful N2 interpretations. It only assigns relations to
candidates N2 classified as `claim_value`; `context_only` candidates (dates, periods,
baselines) may be referenced as context, and `non_claim` candidates may not be used at all.

It never rescans for numbers, never changes N2's subject or measure, and never converts a
percentage into a percentage point. Every `claim_value` candidate ends in an explicit
disposition: assigned to one or more relationships, ambiguous, or unresolved.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from . import claim_contract
from .semantic_common import (FAILED, PARTIAL, SCHEMA_ERROR, SUCCESS, hash_json, locate_quote,
                              make_batches, model_metadata, node_input_hash, prompt_hash,
                              schema_hash)

NODE = 'N3'
NODE_VERSION = 'n3-v1'
PROMPT_VERSION = 'n3-prompt-v1'
SCHEMA_VERSION = 'n3-schema-v1'
# Program validation is part of what a cached N3 result means: a rule change must not reuse
# a result produced by the old checks.
RULESET = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:16]

RELATIONSHIP_TYPES = ('level', 'change', 'comparison', 'range', 'revision', 'share', 'rate',
                      'unknown')
DIRECTIONS = ('increase', 'decrease', 'unchanged', 'not_applicable', 'unknown')
COMPARISONS = claim_contract.COMPARISONS
SEASONALITY = claim_contract.SEASONALITY
REVISION = claim_contract.REVISION
STATUSES = ('resolved', 'ambiguous', 'unresolved')
DISPOSITION_STATUSES = ('assigned', 'ambiguous', 'unresolved')

# A comparison basis is only accepted when the text states it, and a rate phrase is only
# attached to the value it sits next to. This is the deterministic half of the rule "do not
# infer month-over-month from the word month".
SEASONALITY_PHRASES = {
    'seasonally_adjusted': ('seasonally adjusted',),
    'not_seasonally_adjusted': ('not seasonally adjusted',),
}
REVISION_PHRASES = {
    'preliminary': ('preliminary',),
    'advance_estimate': ('advance estimate',),
    'final': ('final',),
    'revised': ('revised', 'revision'),
    'amendment': ('amendment',),
    'subsequent_comparative': ('subsequent comparative',),
}


def _stated(value, phrases, context_text):
    if value == 'unknown':
        return True
    return any(phrase in context_text.lower() for phrase in phrases.get(value, ()))


COMPARISON_PHRASES = {
    'monthly_rate': ('monthly rate', 'at a monthly rate'),
    'quarterly_rate': ('quarterly rate',),
    'annual_rate': ('annual rate', 'annualized', 'annualised'),
    'year_over_year': ('year over year', 'year-over-year', 'year-on-year', 'yoy',
                       'from a year earlier', 'a year earlier'),
    'month_over_month': ('month over month', 'month-over-month', 'month-on-month', 'mom'),
    'quarter_over_quarter': ('quarter over quarter', 'quarter-over-quarter', 'qoq'),
    'percentage_point_change': ('percentage point', 'percentage points', 'pp'),
    'share': ('percent of', 'percentage of', 'share of', 'as a percentage of',
              'accounted for'),
}

SYSTEM_PROMPT = """You are a deterministic relation-extraction component. You receive a context window from one article, numeric candidates with their N2 semantic interpretation, and the relation hints a scanner already found. State the relationships the text explicitly supports.

Return only JSON with this shape:
{"relationships": [{"relationship_type": "level|change|comparison|range|revision|share|rate|unknown", "value_candidate_ids": ["..."], "baseline_candidate_ids": [], "period_candidate_ids": [], "comparison_period_candidate_ids": [], "denominator_candidate_ids": [], "related_expression_ids": [], "direction": "increase|decrease|unchanged|not_applicable|unknown", "comparison": "level|year_over_year|quarter_over_quarter|month_over_month|period_change|percentage_point_change|share|monthly_rate|quarterly_rate|annual_rate|unknown", "seasonality": "seasonally_adjusted|not_seasonally_adjusted|unknown", "revision": "original|revised|preliminary|unknown|amendment|subsequent_comparative|advance_estimate|final", "period_raw": "...", "evidence_sentence_ids": ["s0001"], "evidence_quote": "...", "status": "resolved|ambiguous|unresolved", "reason": "..."}], "candidate_dispositions": [{"candidate_id": "...", "status": "assigned|ambiguous|unresolved", "relationship_indexes": [0], "reason": "..."}]}

Rules:
- Every supplied claim_value candidate must be assigned to at least one relationship, or listed in candidate_dispositions as ambiguous or unresolved. Never drop one.
- value_candidate_ids may contain only supplied claim_value candidates. context_only candidates may appear only as period, comparison-period, baseline or denominator context. non_claim candidates may never be referenced.
- Never change what N2 said the number measures; if the relation cannot be stated without changing it, mark it unresolved.
- relationship_type=level for a stated level; change for an increase/decrease; comparison when two values or periods are compared; range for an interval; share for a part of a whole; rate for a stated rate; revision when a revised figure is compared with the earlier one.
- "grew to $30 trillion" makes the $30 trillion a level, not a growth amount.
- A currency amount and a percentage in the same clause are different values. The amount is the change amount; the percentage is the rate. When a rate phrase follows the percentage ("0.2 percent at a monthly rate"), give monthly_rate/annual_rate to the percentage, not to the currency amount. A parenthetical percentage directly after an amount states the rate for the same change; keep both values and their own relationships. Do not mark that percentage ambiguous merely because its comparison basis is unstated: use relationship_type=change and comparison=unknown.
- Do not copy one candidate's comparison or direction onto another candidate when the text attaches it to only one of them.
- comparison=level for a stated level with no comparison basis; comparison=unknown when the text implies a comparison but does not state the basis. monthly_rate is not month_over_month. annual_rate is not year_over_year. percentage_point_change is not a percent change. A range is not a change.
- direction describes the movement for a change (increase/decrease/unchanged); use not_applicable for a level, range or share.
- Only set revision or seasonality when the text says so. Do not infer a revision from the publisher, and do not infer seasonal adjustment from the indicator.
- When a comparison basis is not stated, keep the relationship and use comparison=level for a level or comparison=unknown for a change; do not invent a baseline number.
- Omit empty arrays and omit any optional field that is unknown or not applicable; the program fills defaults. Include period_raw only when the text states the period, and copy it exactly (for example "september", "2026-09", "q3 2026"), not the whole sentence.
- When the context states the period of a relationship (for example "in september"), reference the supplied context_only period candidate in period_candidate_ids and copy its exact text into period_raw. Do not leave the period empty when the sentence states one.
- When the context states a baseline ("from $95 billion", "compared with 3.2%"), reference that candidate in baseline_candidate_ids; do not invent one when the text gives none.
- reason must be one short sentence, at most 20 words.
- evidence_quote must be the shortest exact contiguous excerpt copied from the supplied context that shows this relation. Do not paraphrase or join separate excerpts. evidence_sentence_ids are the sentences that contain it.
- Use resolved only when the relation is explicit. Otherwise use ambiguous or unresolved and say why.
"""

SCHEMA = {
    'type': 'object',
    'properties': {
        'relationships': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'relationship_type': {'type': 'string', 'enum': list(RELATIONSHIP_TYPES)},
                    'value_candidate_ids': {'type': 'array', 'items': {'type': 'string'}},
                    'baseline_candidate_ids': {'type': 'array', 'items': {'type': 'string'}},
                    'period_candidate_ids': {'type': 'array', 'items': {'type': 'string'}},
                    'comparison_period_candidate_ids': {'type': 'array', 'items': {'type': 'string'}},
                    'denominator_candidate_ids': {'type': 'array', 'items': {'type': 'string'}},
                    'related_expression_ids': {'type': 'array', 'items': {'type': 'string'}},
                    'direction': {'type': 'string', 'enum': list(DIRECTIONS)},
                    'comparison': {'type': 'string', 'enum': list(COMPARISONS)},
                    'seasonality': {'type': 'string', 'enum': list(SEASONALITY)},
                    'revision': {'type': 'string', 'enum': list(REVISION)},
                    'period_raw': {'type': 'string'},
                    'evidence_sentence_ids': {'type': 'array', 'items': {'type': 'string'}},
                    'evidence_quote': {'type': 'string'},
                    'status': {'type': 'string', 'enum': list(STATUSES)},
                    'reason': {'type': 'string'},
                },
                'required': ['relationship_type', 'value_candidate_ids', 'direction',
                             'comparison', 'evidence_sentence_ids', 'evidence_quote',
                             'status', 'reason'],
                'additionalProperties': False,
            },
        },
        'candidate_dispositions': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'candidate_id': {'type': 'string'},
                    'status': {'type': 'string', 'enum': list(DISPOSITION_STATUSES)},
                    'relationship_indexes': {'type': 'array', 'items': {'type': 'integer'}},
                    'reason': {'type': 'string'},
                },
                'required': ['candidate_id', 'status', 'reason'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['relationships', 'candidate_dispositions'],
    'additionalProperties': False,
}

MAX_REASON = 600


def _stable_n2(n2):
    """The N2 result without timing/retry bookkeeping: what N3 actually depends on."""
    return {key: value for key, value in n2.items() if key not in ('seconds', 'batches')}


def input_hash(document, n1, n2, model):
    return node_input_hash({
        'node': NODE, 'node_version': NODE_VERSION,
        'document_id': document.get('document_id'),
        'text_hash': document.get('text_hash'),
        'n1_hash': hash_json(n1),
        'n2_hash': hash_json(_stable_n2(n2)),
        'prompt_version': PROMPT_VERSION, 'prompt_hash': prompt_hash(SYSTEM_PROMPT),
        'schema_version': SCHEMA_VERSION, 'schema_hash': schema_hash(SCHEMA),
        'ruleset': RULESET,
        'model': model,
    })


def _empty(statistics, **extra):
    return dict(extra, relationships=[], candidate_dispositions=[], batches=[],
                statistics=statistics)


def _interpretations(n2):
    return {item.get('candidate_id'): item
            for item in (n2.get('candidate_interpretations') or [])
            if isinstance(item, dict)}


def _window_candidates(n1, start, end):
    return [candidate for candidate in n1.get('candidates') or []
            if candidate.get('start', -1) < end and start < candidate.get('end', -1)]


def _window_groups(n1, start, end):
    return [group for group in n1.get('expression_groups') or []
            if group.get('start', -1) < end and start < group.get('end', -1)]


def _candidate_payload(candidate, interpretation):
    payload = {
        'candidate_id': candidate['candidate_id'],
        'candidate_type': candidate['candidate_type'],
        'raw_text': candidate['raw_text'],
        'value': candidate.get('value'),
        'scale': candidate.get('scale'),
        'unit': candidate.get('unit'),
        'currency': candidate.get('currency'),
        'temporal': candidate.get('temporal'),
        'start': candidate['start'], 'end': candidate['end'],
        'sentence_id': candidate.get('sentence_id'),
        'paragraph_id': candidate.get('paragraph_id'),
        'local_cues': [{'term': cue.get('term'), 'role': cue.get('role')}
                       for cue in (candidate.get('cues') or [])
                       if abs(cue.get('start', 0) - candidate.get('start', 0)) <= 60],
    }
    if interpretation:
        payload['n2'] = {
            'disposition': interpretation.get('disposition'),
            'subject': interpretation.get('subject'),
            'predicate': interpretation.get('predicate'),
            'kind': interpretation.get('kind'),
            'status': interpretation.get('status'),
        }
    return payload


def _batch_payload(document, n1, n2, batch, claim_value_ids):
    interpretations = _interpretations(n2)
    start, end = batch['context_start'], batch['context_end']
    window = _window_candidates(n1, start, end)
    context_only = [candidate['candidate_id'] for candidate in window
                    if (interpretations.get(candidate['candidate_id']) or {}).get('disposition')
                    == 'context_only'
                    and (interpretations.get(candidate['candidate_id']) or {}).get('status')
                    == 'resolved']
    return {
        'task': 'State the relations the context explicitly supports and dispose every claim_value candidate.',
        'article': {'title': document.get('title', ''), 'document_id': document.get('document_id')},
        'context': {'field': batch['field'], 'sentences': batch['sentences']},
        'claim_value_ids': list(claim_value_ids),
        'context_only_ids': context_only,
        'candidates': [_candidate_payload(candidate, interpretations.get(candidate['candidate_id']))
                       for candidate in window],
        'expression_groups': [
            {'expression_id': group.get('expression_id'),
             'expression_type': group.get('expression_type'),
             'raw_text': group.get('raw_text'),
             'candidate_ids': group.get('candidate_ids')}
            for group in _window_groups(n1, start, end)
        ],
        'allowed': {
            'relationship_types': list(RELATIONSHIP_TYPES),
            'directions': list(DIRECTIONS),
            'comparisons': list(COMPARISONS),
            'seasonality': list(SEASONALITY),
            'revision': list(REVISION),
            'statuses': list(STATUSES),
            'disposition_statuses': list(DISPOSITION_STATUSES),
        },
    }


def _ids(value, allowed):
    if not isinstance(value, list):
        return [], []
    values = [item for item in value if isinstance(item, str)]
    valid = [item for item in values if item in allowed]
    invalid = [item for item in values if item not in allowed]
    return valid, invalid


def _phrase_attachment(comparison, context_text, window_positions, value_ids):
    """(ok, expected_id): does the stated comparison phrase sit next to one of these values?

    ok is None when the phrase is not in the context at all; False when it is next to a
    different atom. That is the check that keeps "0.2 percent at a monthly rate" from giving
    the monthly rate to the "$54.5 billion" that precedes the percentage.
    """
    phrases = COMPARISON_PHRASES.get(comparison)
    if not phrases:
        return True, ''
    lower = context_text.lower()
    positions = []
    for phrase in phrases:
        start = lower.find(phrase)
        while start >= 0:
            positions.append((start, start + len(phrase)))
            start = lower.find(phrase, start + 1)
    if not positions:
        return None, ''
    for start, end in positions:
        before = [(start - candidate_end, candidate_id)
                  for candidate_id, candidate_start, candidate_end in window_positions
                  if candidate_end <= start and start - candidate_end <= 40]
        after = [(candidate_start - end, candidate_id)
                 for candidate_id, candidate_start, candidate_end in window_positions
                 if candidate_start >= end and candidate_start - end <= 40]
        nearest = sorted(before + after)
        if nearest:
            return (nearest[0][1] in value_ids), nearest[0][1]
    return True, ''


def _normalise_relationship(raw, document, sentence_ids, batch_values, window_ids,
                            window_positions, expression_ids, context_text):
    deviations = []
    relationship_type = str(raw.get('relationship_type') or '').strip().lower()
    if relationship_type not in RELATIONSHIP_TYPES:
        deviations.append({'field': 'relationship_type', 'reason': 'unknown_value',
                           'value': relationship_type[:80]})
        relationship_type = 'unknown'
    values, unknown_values = _ids(raw.get('value_candidate_ids'), batch_values)
    if unknown_values:
        deviations.append({'field': 'value_candidate_ids', 'reason': 'not_a_claim_value',
                           'value': ','.join(unknown_values)[:120]})
    # Context ids are limited to the window the model actually saw; a period from another
    # batch is not evidence the model could have read.
    baselines, unknown_baselines = _ids(raw.get('baseline_candidate_ids'), window_ids)
    periods, unknown_periods = _ids(raw.get('period_candidate_ids'), window_ids)
    comparison_periods, unknown_comparison_periods = _ids(
        raw.get('comparison_period_candidate_ids'), window_ids)
    denominators, unknown_denominators = _ids(raw.get('denominator_candidate_ids'), window_ids)
    for field, values_invalid in (('baseline_candidate_ids', unknown_baselines),
                                  ('period_candidate_ids', unknown_periods),
                                  ('comparison_period_candidate_ids', unknown_comparison_periods),
                                  ('denominator_candidate_ids', unknown_denominators)):
        if values_invalid:
            deviations.append({'field': field, 'reason': 'not_usable_context',
                               'value': ','.join(values_invalid)[:120]})
    expressions, unknown_expressions = _ids(raw.get('related_expression_ids'), expression_ids)
    if unknown_expressions:
        deviations.append({'field': 'related_expression_ids', 'reason': 'unknown_expression',
                           'value': ','.join(unknown_expressions)[:120]})

    direction = str(raw.get('direction') or '').strip().lower()
    if direction not in DIRECTIONS:
        deviations.append({'field': 'direction', 'reason': 'unknown_value',
                           'value': direction[:80]})
        direction = 'unknown'
    comparison = str(raw.get('comparison') or '').strip().lower()
    if comparison not in COMPARISONS:
        deviations.append({'field': 'comparison', 'reason': 'unknown_value',
                           'value': comparison[:80]})
        comparison = 'unknown'
    ok, expected = _phrase_attachment(comparison, context_text, window_positions, set(values))
    if ok is None:
        deviations.append({'field': 'comparison', 'reason': 'not_stated',
                           'value': comparison})
        comparison = 'level' if relationship_type in ('level', 'rate', 'share') else 'unknown'
    elif ok is False:
        deviations.append({'field': 'comparison', 'reason': 'attached_to_other_candidate',
                           'value': f'{comparison}->{expected}'})
        comparison = 'level' if relationship_type in ('level', 'rate', 'share') else 'unknown'
    if relationship_type == 'change' and comparison == 'level':
        deviations.append({'field': 'comparison', 'reason': 'change_cannot_be_level',
                           'value': 'level'})
        comparison = 'unknown'
    seasonality = str(raw.get('seasonality') or '').strip().lower()
    if seasonality and seasonality not in SEASONALITY:
        deviations.append({'field': 'seasonality', 'reason': 'unknown_value',
                           'value': seasonality[:80]})
        seasonality = 'unknown'
    elif not seasonality:
        seasonality = 'unknown'
    if not _stated(seasonality, SEASONALITY_PHRASES, context_text):
        deviations.append({'field': 'seasonality', 'reason': 'not_stated',
                           'value': seasonality})
        seasonality = 'unknown'
    revision = str(raw.get('revision') or '').strip().lower()
    if revision and revision not in REVISION:
        deviations.append({'field': 'revision', 'reason': 'unknown_value',
                           'value': revision[:80]})
        revision = 'unknown'
    elif not revision:
        revision = 'unknown'
    if not _stated(revision, REVISION_PHRASES, context_text):
        deviations.append({'field': 'revision', 'reason': 'not_stated', 'value': revision})
        revision = 'unknown'
    period_raw = str(raw.get('period_raw') or '').strip()
    if period_raw and period_raw.lower() not in context_text.lower():
        deviations.append({'field': 'period_raw', 'reason': 'not_in_context',
                           'value': period_raw[:120]})
        period_raw = ''

    ids = raw.get('evidence_sentence_ids')
    ids = [value for value in ids if isinstance(value, str)] if isinstance(ids, list) else []
    valid_ids = [value for value in ids if value in sentence_ids]
    if len(valid_ids) != len(ids):
        deviations.append({'field': 'evidence_sentence_ids', 'reason': 'unknown_sentence',
                           'value': ','.join(value for value in ids
                                             if value not in sentence_ids)[:120]})
    quote = str(raw.get('evidence_quote') or '').strip()
    locator = locate_quote(document, valid_ids, quote) if valid_ids and quote else None
    if quote and locator is None:
        deviations.append({'field': 'evidence_quote', 'reason': 'not_located',
                           'value': quote[:120]})
    status = str(raw.get('status') or '').strip().lower()
    if status not in STATUSES:
        deviations.append({'field': 'status', 'reason': 'unknown_value', 'value': status[:80]})
        status = 'resolved'
    if not values:
        deviations.append({'field': 'value_candidate_ids', 'reason': 'empty',
                           'value': ''})
        status = 'unresolved'
    if quote and locator is None:
        status = 'unresolved'
    if status == 'resolved' and locator is None:
        status = 'unresolved'
    reason = str(raw.get('reason') or '').strip()
    return {
        'expression_id': '',
        'relationship_type': relationship_type,
        'value_candidate_ids': values,
        'baseline_candidate_ids': baselines,
        'period_candidate_ids': periods,
        'comparison_period_candidate_ids': comparison_periods,
        'denominator_candidate_ids': denominators,
        'related_expression_ids': expressions,
        'direction': direction,
        'comparison': comparison,
        'seasonality': seasonality,
        'revision': revision,
        'period_raw': period_raw,
        'evidence_sentence_ids': valid_ids,
        'evidence_quote': quote,
        'evidence_start': locator[0] if locator else None,
        'evidence_end': locator[1] if locator else None,
        'evidence_field': locator[2] if locator else None,
        'status': status,
        'reason': reason,
        'deviations': deviations,
    }, deviations


def _disposition_records(raw_items, claim_value_ids):
    """Model dispositions as hints. Relationship indexes are derived by the program.

    The model indexes into the relationship order it returned, which is not the order after
    validation and sorting. Keeping its numbers would point at the wrong relations, so only
    its ambiguous/unresolved judgement and reason are used.
    """
    deviations, by_id, unknown = [], {}, []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                deviations.append({'field': '*', 'reason': 'not_an_object', 'value': ''})
                continue
            candidate_id = item.get('candidate_id')
            if candidate_id not in claim_value_ids:
                unknown.append(str(candidate_id)[:80])
                continue
            if candidate_id in by_id:
                deviations.append({'field': 'candidate_id', 'reason': 'duplicate',
                                   'value': candidate_id})
                continue
            status = str(item.get('status') or '').strip().lower()
            if status not in DISPOSITION_STATUSES:
                deviations.append({'field': 'status', 'reason': 'unknown_value',
                                   'value': status[:80]})
                status = 'unresolved'
            by_id[candidate_id] = {'candidate_id': candidate_id, 'status': status,
                                   'relationship_indexes': [],
                                   'reason': str(item.get('reason') or '')[:MAX_REASON]}
    else:
        deviations.append({'field': '*', 'reason': 'dispositions_not_a_list', 'value': ''})
    return by_id, unknown, deviations


def run(document, n1, n2, runner, model, max_candidates=4, max_chars=3500):
    """N3 for one document. Never runs the model when N2 did not succeed."""
    if not isinstance(document, dict) or not isinstance(n1, dict) or not isinstance(n2, dict):
        raise ValueError('N3 needs the N0, N1 and N2 dicts')
    for value in (n1, n2):
        if document.get('document_id') != value.get('document_id'):
            raise ValueError('N3 inputs are from different documents')
    started = time.time()
    computed_hash = input_hash(document, n1, n2, model)
    base = {
        'node': NODE, 'node_version': NODE_VERSION,
        'document_id': document.get('document_id'),
        'input_hash': computed_hash, 'n2_output_hash': hash_json(_stable_n2(n2)),
        'prompt_version': PROMPT_VERSION, 'prompt_hash': prompt_hash(SYSTEM_PROMPT),
        'schema_version': SCHEMA_VERSION, 'schema_hash': schema_hash(SCHEMA),
        'ruleset': RULESET,
        'model': model,
    }
    if n2.get('status') not in (SUCCESS, PARTIAL):
        return dict(base, status='blocked', blocked_reason='n2_not_successful',
                    relationships=[], candidate_dispositions=[], batches=[],
                    statistics={'input_claim_value_count': 0, 'relationship_count': 0,
                                'assigned_count': 0, 'unresolved_count': 0,
                                'ambiguous_count': 0, 'coverage_complete': True},
                    seconds=round(time.time() - started, 2))
    interpretations = _interpretations(n2)
    candidates = list(n1.get('candidates') or [])
    claim_value_ids = [candidate['candidate_id'] for candidate in candidates
                       if (interpretations.get(candidate['candidate_id']) or {}).get('disposition')
                       == 'claim_value'
                       and (interpretations.get(candidate['candidate_id']) or {}).get('status')
                       == 'resolved']
    if not claim_value_ids:
        return dict(base, status=SUCCESS, relationships=[], candidate_dispositions=[],
                    batches=[], statistics={
                        'input_claim_value_count': 0, 'relationship_count': 0,
                        'assigned_count': 0, 'unresolved_count': 0, 'ambiguous_count': 0,
                        'by_type': {}, 'coverage_complete': True},
                    seconds=round(time.time() - started, 2))
    claims = [candidate for candidate in candidates
              if candidate['candidate_id'] in set(claim_value_ids)]
    batches = make_batches(document, claims, max_candidates=max_candidates, max_chars=max_chars)
    sentence_ids = {item['sentence_id'] for item in document['sentences']}
    expression_ids = {group['expression_id'] for group in n1.get('expression_groups') or []}
    relationships, relationship_deviations, batch_records = [], [], []
    disposition_raw, disposition_unknown, disposition_deviations = [], [], []
    for batch in batches:
        batch_started = time.time()
        batch_claim_ids = [value for value in batch['candidate_ids']
                           if value in set(claim_value_ids)]
        payload = _batch_payload(document, n1, n2, batch, batch_claim_ids)
        result = runner.run(payload)
        usage = result.get('usage') or {}
        record = {'claim_value_ids': batch_claim_ids,
                  'status': result.get('status', FAILED),
                  'attempts': result.get('attempts', 0),
                  'seconds': result.get('seconds', round(time.time() - batch_started, 2)),
                  'input_chars': result.get('input_chars'),
                  'output_chars': result.get('output_chars'),
                  'prompt_tokens': usage.get('prompt_tokens'),
                  'completion_tokens': usage.get('completion_tokens'),
                  'parse_retry': result.get('parse_retry', False),
                  'context_chars': len(batch['context_text']),
                  'claim_value_count': len(batch_claim_ids),
                  'error': result.get('error', ''),
                  'deviations': []}
        if result.get('status') != 'ok':
            batch_records.append(record)
            continue
        parsed = result['parsed']
        raw_relationships = parsed.get('relationships')
        raw_dispositions = parsed.get('candidate_dispositions')
        if not isinstance(raw_relationships, list) or not isinstance(raw_dispositions, list):
            record['status'] = SCHEMA_ERROR
            record['error'] = 'relationships or candidate_dispositions is not a list'
            batch_records.append(record)
            continue
        context_text = batch['context_text']
        batch_values = set(batch_claim_ids)
        window_candidates = _window_candidates(n1, batch['context_start'], batch['context_end'])
        window_ids = {candidate['candidate_id'] for candidate in window_candidates}
        window_positions = [(candidate['candidate_id'],
                             candidate['start'] - batch['context_start'],
                             candidate['end'] - batch['context_start'])
                            for candidate in window_candidates]
        batch_relationships = []
        for raw in raw_relationships:
            if not isinstance(raw, dict):
                record['deviations'].append({'field': '*', 'reason': 'not_an_object',
                                             'value': ''})
                continue
            relationship, deviations = _normalise_relationship(
                raw, document, sentence_ids, batch_values, window_ids, window_positions,
                expression_ids, context_text)
            if not relationship['value_candidate_ids']:
                record['deviations'].extend(deviations or [])
                record['deviations'].append({'field': 'value_candidate_ids',
                                             'reason': 'not_in_batch', 'value': ''})
                continue
            relationship_deviations.extend(deviations)
            record['deviations'].extend(deviations)
            relationships.append(relationship)
            batch_relationships.append(relationship)
        # A disposition may only describe a candidate that was in this batch's payload;
        # one naming another batch is a cross-batch reference and is not accepted.
        for item in raw_dispositions:
            if isinstance(item, dict) and item.get('candidate_id') in batch_values:
                disposition_raw.append(item)
            else:
                record['deviations'].append({
                    'field': 'candidate_id', 'reason': 'not_in_batch',
                    'value': str(item.get('candidate_id') if isinstance(item, dict)
                                 else item)[:80]})
        if record['deviations']:
            record['status'] = PARTIAL
        record['status'] = (PARTIAL if (record['deviations'] or any(
            item.get('status') != 'resolved' for item in batch_relationships)) else SUCCESS)
        batch_records.append(record)
    for index, relationship in enumerate(relationships):
        material = '\x00'.join((str(base['n2_output_hash']), str(relationship['relationship_type']),
                                ','.join(sorted(relationship['value_candidate_ids'])),
                                str(relationship.get('evidence_start')),
                                str(relationship.get('evidence_end'))))
        relationship['relationship_id'] = 'r' + hashlib.sha256(
            material.encode('utf-8')).hexdigest()[:16]
    relationships.sort(key=lambda item: (item.get('evidence_start') if item.get('evidence_start')
                                         is not None else 10 ** 12,
                                         item['relationship_type']))
    # model dispositions are interpreted against the final relationship order
    model_dispositions, unknown_dispositions, disposition_deviations = _disposition_records(
        disposition_raw, set(claim_value_ids))
    for value in unknown_dispositions:
        disposition_deviations.append({'field': 'candidate_id', 'reason': 'not_a_claim_value',
                                       'value': value})
    assigned = {}
    for index, relationship in enumerate(relationships):
        if relationship['status'] != 'resolved':
            continue
        for candidate_id in (relationship['value_candidate_ids']
                             + relationship['baseline_candidate_ids']
                             + relationship['period_candidate_ids']
                             + relationship['comparison_period_candidate_ids']
                             + relationship['denominator_candidate_ids']):
            if candidate_id in set(claim_value_ids):
                assigned.setdefault(candidate_id, set()).add(index)
    dispositions, unresolved = [], 0
    for candidate_id in claim_value_ids:
        record = model_dispositions.get(candidate_id)
        indexes = sorted(assigned.get(candidate_id, set()))
        if indexes:
            dispositions.append({'candidate_id': candidate_id, 'status': 'assigned',
                                 'relationship_indexes': indexes,
                                 'reason': 'assigned_by_relationships'})
        elif record and record['status'] in ('ambiguous', 'unresolved'):
            dispositions.append({'candidate_id': candidate_id, 'status': record['status'],
                                 'relationship_indexes': [],
                                 'reason': record['reason'] or 'model_disposition'})
            unresolved += 1 if record['status'] == 'unresolved' else 0
        else:
            reason = ('model_said_assigned_without_a_relationship'
                      if record and record['status'] == 'assigned'
                      else 'model_omitted_disposition')
            dispositions.append({'candidate_id': candidate_id, 'status': 'unresolved',
                                 'relationship_indexes': [],
                                 'reason': reason})
            disposition_deviations.append({'field': '*', 'reason': 'coverage_error',
                                           'value': candidate_id})
            unresolved += 1
    assigned_count = sum(1 for item in dispositions if item['status'] == 'assigned')
    ambiguous_count = sum(1 for item in dispositions if item['status'] == 'ambiguous')
    unresolved_count = sum(1 for item in dispositions if item['status'] == 'unresolved')
    by_type = {}
    for relationship in relationships:
        by_type[relationship['relationship_type']] = \
            by_type.get(relationship['relationship_type'], 0) + 1
    statistics = {
        'input_claim_value_count': len(claim_value_ids),
        'relationship_count': len(relationships),
        'by_type': by_type,
        'resolved_relationships': sum(1 for item in relationships
                                      if item['status'] == 'resolved'),
        'ambiguous_relationships': sum(1 for item in relationships
                                       if item['status'] == 'ambiguous'),
        'unresolved_relationships': sum(1 for item in relationships
                                        if item['status'] == 'unresolved'),
        'assigned_count': assigned_count,
        'ambiguous_count': ambiguous_count,
        'unresolved_count': unresolved_count,
        'evidence_located_relationships': sum(1 for item in relationships
                                              if item.get('evidence_start') is not None),
        'coverage_complete': len(dispositions) == len(claim_value_ids)
        and len({item['candidate_id'] for item in dispositions}) == len(claim_value_ids),
        'batch_count': len(batches),
        'failed_batches': sum(1 for record in batch_records
                              if record['status'] not in (SUCCESS, PARTIAL)),
    }
    failed = [record for record in batch_records if record['status'] not in (SUCCESS, PARTIAL)]
    if failed and len(failed) == len(batch_records):
        statuses = {record['status'] for record in failed}
        status = statuses.pop() if len(statuses) == 1 else FAILED
    elif (failed or not statistics['coverage_complete'] or statistics['unresolved_count']
          or statistics['ambiguous_count'] or any(record['deviations']
                                                  for record in batch_records)):
        status = PARTIAL
    else:
        status = SUCCESS
    return dict(base, status=status, relationships=relationships,
                candidate_dispositions=dispositions, batches=batch_records,
                statistics=statistics, deviations=relationship_deviations + disposition_deviations,
                seconds=round(time.time() - started, 2))
