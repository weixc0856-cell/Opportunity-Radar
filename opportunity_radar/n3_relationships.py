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
from .semantic_common import (FAILED, INVALID_OUTPUT, PARTIAL, SCHEMA_ERROR, SUCCESS, hash_json,
                              locate_quote,
                              make_batches, model_metadata, node_input_hash, prompt_hash,
                              schema_hash)

NODE = 'N3'
NODE_VERSION = 'n3-v3'
PROMPT_VERSION = 'n3-prompt-v3'
SCHEMA_VERSION = 'n3-schema-v2'
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
- Every supplied claim_value candidate with in_batch=true must be assigned to at least one relationship, or listed in candidate_dispositions as ambiguous or unresolved. Never drop one.
- Only candidates with in_batch=true are this batch's claim_value candidates. A candidate with in_batch=false is context even if its n2 disposition says claim_value: do not put it in value_candidate_ids, though it may be baseline, period, comparison-period or denominator context. non_claim candidates may never be referenced.
- Never change what N2 said the number measures; if the relation cannot be stated without changing it, mark it unresolved.
- relationship_type=level for a stated level; change for an increase/decrease; comparison when two values or periods are compared; range for an interval; share for a part of a whole; rate for a stated rate; revision when a revised figure is compared with the earlier one.
- Use comparison=period_change when the text compares a value with an earlier period: "from $92.8 billion in July to $105.6 billion in August", "up from ... last month", "compared with the previous quarter", or a change amount stated for the current period followed by "to <new level>" ("increased $12.8 billion in August to $136.6 billion"). Do not infer period_change merely because two numbers appear in the same article. Use month_over_month only when the text explicitly says month over month / month-on-month / MoM.
- A single change amount with no earlier value, no "from", and no "to <new level>" is comparison=unknown, not period_change.
- "grew to $30 trillion" makes the $30 trillion a level, not a growth amount.
- A currency amount and a percentage in the same clause are different values. The amount is the change amount; the percentage is the rate of that change. Classify the percentage by its own clause; a rate word elsewhere in the window does not apply. Keep both values and their own relationships.
  - Exact rate phrase in the clause ("0.2 percent at a monthly rate", "at an annual rate", "quarterly rate"): relationship_type=rate, comparison=monthly_rate|annual_rate|quarterly_rate, direction=not_applicable.
  - No rate phrase in the clause ("increased $113.1 billion (0.5 percent)", "increased $52.7 billion (0.2 percent)"): relationship_type=change, comparison=unknown, direction=increase|decrease. A percent sign alone never makes a rate.
  - Named rate or ratio in the clause ("the personal saving rate was 3.8 percent", "the unemployment rate", "share of GDP"): relationship_type=rate (share for a part of a whole), comparison=level when no comparison basis is stated, direction=not_applicable. Do not omit a candidate merely because it is a rate definition; give it its own level relationship.
  Do not mark a percentage ambiguous only because its comparison basis is unstated.
- Do not copy one candidate's comparison or direction onto another candidate when the text attaches it to only one of them.
- comparison=level for a stated level with no comparison basis; comparison=unknown when the text implies a comparison but does not state the basis. monthly_rate is not month_over_month. annual_rate is not year_over_year. percentage_point_change is not a percent change. A range is not a change.
- direction describes the movement for a change (increase/decrease/unchanged); use not_applicable for a level, range or share.
- Only set revision or seasonality when the text says so. Do not infer a revision from the publisher, and do not infer seasonal adjustment from the indicator.
- When a comparison basis is not stated, keep the relationship and use comparison=level for a level or comparison=unknown for a change; do not invent a baseline number.
- Omit empty arrays and omit any optional field that is unknown or not applicable; the program fills defaults. Include period_raw only when the text states the period, and copy it exactly (for example "september", "2026-09", "q3 2026"), not the whole sentence.
- The payload lists every date/period candidate in the document under document_period_candidates, and each candidate's period_hints list the period candidates near it. "same_sentence" means the period candidate is in the same sentence as the value; "title_same_month" means the title states the same month with a year.
- When the sentence states the period of a relationship (for example "in september", "in august 2026", "in the third quarter of 2026"), reference that exact candidate in period_candidate_ids and copy its raw_text into period_raw. Use period_hints for the value candidate; do not leave the period empty when the sentence states one.
- A month or quarter in the sentence inherits the year from a title period of the same month/quarter (for example title "September 2026", sentence "in September"). Reference the full candidate when one is supplied. Never infer a year from the publication date or from a different period.
- Do not move a period from one sentence to another, and do not give one period to every number in the article. If two different periods apply and the text does not say which belongs to the value, leave period_candidate_ids empty and mark the relationship ambiguous.
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


def _period_candidates(n1):
    return [candidate for candidate in n1.get('candidates') or []
            if candidate.get('candidate_type') in ('date', 'period')
            and isinstance(candidate.get('temporal'), dict)]


def _period_payload(candidate, relation='', distance=None):
    payload = {
        'candidate_id': candidate['candidate_id'],
        'raw_text': candidate['raw_text'],
        'temporal': candidate.get('temporal'),
        'field': candidate.get('field'),
        'sentence_id': candidate.get('sentence_id'),
        'start': candidate.get('start'),
        'end': candidate.get('end'),
    }
    if relation:
        payload['relation'] = relation
    if distance is not None:
        payload['distance'] = distance
    return payload


def _temporal_slot(candidate):
    temporal = candidate.get('temporal') or {}
    kind = temporal.get('kind')
    if kind == 'month':
        return ('month', temporal.get('month'))
    if kind == 'quarter':
        return ('quarter', temporal.get('quarter'))
    return None


def _has_year(candidate):
    return bool((candidate.get('temporal') or {}).get('year'))


def _period_distance(value_candidate, period_candidate):
    if period_candidate['end'] <= value_candidate['start']:
        return value_candidate['start'] - period_candidate['end']
    return period_candidate['start'] - value_candidate['end']


def _period_hints(n1, value_candidate):
    """Period candidates the text puts next to this value.

    The same sentence is the primary evidence. A month/quarter without a year may also use a
    title candidate for the same month/quarter; that is the only cross-sentence promotion and
    it never invents a year. Everything else stays unassociated.
    """
    periods = _period_candidates(n1)
    same_sentence = [candidate for candidate in periods
                     if candidate.get('sentence_id') == value_candidate.get('sentence_id')]
    hints = []
    for candidate in same_sentence:
        hints.append(_period_payload(candidate, 'same_sentence',
                                     _period_distance(value_candidate, candidate)))
    slots = {_temporal_slot(candidate) for candidate in same_sentence
             if _temporal_slot(candidate) and not _has_year(candidate)}
    if not slots:
        return hints
    for candidate in periods:
        if candidate in same_sentence or not _has_year(candidate):
            continue
        if _temporal_slot(candidate) not in slots:
            continue
        if candidate.get('field') == 'title':
            hints.append(_period_payload(candidate, 'title_same_month'))
        elif candidate.get('paragraph_id') == value_candidate.get('paragraph_id'):
            hints.append(_period_payload(candidate, 'same_paragraph_same_month'))
    return hints


def _candidate_payload(candidate, interpretation, period_hints=None, in_batch=False):
    payload = {
        'candidate_id': candidate['candidate_id'],
        'in_batch': bool(in_batch),
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
    if period_hints:
        payload['period_hints'] = period_hints
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
        'document_period_candidates': [_period_payload(candidate)
                                        for candidate in _period_candidates(n1)],
        'candidates': [_candidate_payload(candidate,
                                          interpretations.get(candidate['candidate_id']),
                                          _period_hints(n1, candidate),
                                          candidate['candidate_id'] in claim_value_ids)
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
                            document_period_ids, window_positions, expression_ids,
                            context_text, period_candidates):
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
    # Baselines/denominators are limited to the window the model actually saw. Periods are
    # different: a title period outside the window may be the only place the year is stated.
    baselines, unknown_baselines = _ids(raw.get('baseline_candidate_ids'), window_ids)
    # Periods may be named anywhere in the document: a title period is often the only place
    # the year is stated. Other context (baselines, denominators) must still come from the
    # window the model saw.
    periods, unknown_periods = _ids(raw.get('period_candidate_ids'), document_period_ids)
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
    period_attempted = bool(period_raw or raw.get('period_candidate_ids'))
    period_rejected = bool(unknown_periods)
    period_evidence = {'quote': '', 'start': None, 'end': None, 'field': ''}
    if periods:
        period_candidate = period_candidates.get(periods[0]) or {}
        period_raw = str(period_candidate.get('raw_text') or period_raw).strip()
        period_evidence = {
            'quote': period_candidate.get('raw_text') or '',
            'start': period_candidate.get('start'),
            'end': period_candidate.get('end'),
            'field': period_candidate.get('field') or '',
        }
    elif period_raw:
        candidate_raws = {str(candidate.get('raw_text') or '').lower()
                          for candidate in period_candidates.values()}
        if period_raw.lower() not in context_text.lower() and period_raw.lower() not in candidate_raws:
            deviations.append({'field': 'period_raw', 'reason': 'not_in_context',
                               'value': period_raw[:120]})
            period_raw = ''
            period_rejected = True

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
    if relationship_type == 'revision' and not baselines:
        deviations.append({'field': 'baseline_candidate_ids',
                           'reason': 'revision_without_baseline', 'value': ''})
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
        'period_evidence_quote': period_evidence['quote'],
        'period_evidence_start': period_evidence['start'],
        'period_evidence_end': period_evidence['end'],
        'period_evidence_field': period_evidence['field'],
        'period_source': ('model' if (periods or period_raw)
                          else 'model_rejected' if (period_attempted or period_rejected) else ''),
        'period_rule': '',
        'evidence_sentence_ids': valid_ids,
        'evidence_quote': quote,
        'evidence_start': locator[0] if locator else None,
        'evidence_end': locator[1] if locator else None,
        'evidence_field': locator[2] if locator else None,
        'status': status,
        'reason': reason,
        'deviations': deviations,
    }, deviations


RATE_COMPARISONS = (
    ('monthly_rate', ('at a monthly rate', 'monthly rate')),
    ('annual_rate', ('at an annual rate', 'annual rate', 'annualized', 'annualised')),
    ('quarterly_rate', ('at a quarterly rate', 'quarterly rate')),
)
RATE_WORDS = (' rate', 'rate ', ' ratio', 'share of', 'percent of', 'percentage of')
INCREASE_WORDS = ('increased', 'increase ', 'rose', ' rise', 'grew', 'grow', 'gained',
                  'gain ', 'up from')
DECREASE_WORDS = ('decreased', 'decrease ', 'fell', ' fall', 'declined', 'decline ',
                  'dropped', 'drop ', 'down from')


def _local_text(document, candidate, radius=110):
    sentence = next((item for item in document['sentences']
                     if item['sentence_id'] == candidate.get('sentence_id')), None)
    if sentence is None:
        return ''
    start = max(sentence['start'], candidate['start'] - radius)
    end = min(sentence['end'], candidate['end'] + radius)
    return document['text'][start:end].lower()


def _direction_in(text):
    if any(word in text for word in INCREASE_WORDS):
        return 'increase'
    if any(word in text for word in DECREASE_WORDS):
        return 'decrease'
    return 'unknown'


def _parenthetical_after_amount(text, candidate_text):
    """True for '$54.5 billion (0.2 percent at a monthly rate)' style wording."""
    if '(' not in text or ')' not in text:
        return False
    start = text.find('(')
    end = text.find(')', start)
    if start < 0 or end < 0 or candidate_text not in text[start:end + 1]:
        return False
    before = text[max(0, start - 80):start]
    return '$' in before or 'usd' in before


def _apply_comparison_rules(relationship, document, n1):
    """Keep period_change only when the clause compares periods, and level out levels."""
    if relationship.get('status') != 'resolved':
        return None
    candidates = {candidate['candidate_id']: candidate
                  for candidate in n1.get('candidates') or []}
    value_id = (relationship.get('value_candidate_ids') or [''])[0]
    candidate = candidates.get(value_id)
    if not candidate:
        return None
    text = _local_text(document, candidate, radius=160).lower()
    comparison = relationship.get('comparison')
    if relationship.get('relationship_type') == 'level' and comparison == 'period_change':
        relationship['comparison'] = 'level'
        return {'field': 'comparison', 'reason': 'level_cannot_be_period_change',
                'value': value_id, 'before': ['level', 'period_change'],
                'after': ['level', 'level']}
    if relationship.get('relationship_type') == 'change' and comparison == 'period_change':
        has_baseline = bool(relationship.get('baseline_candidate_ids'))
        cues = ('from ', 'to ', 'previous', 'last ', 'compared with', 'prior')
        if not has_baseline and not any(cue in text for cue in cues):
            relationship['comparison'] = 'unknown'
            return {'field': 'comparison', 'reason': 'period_change_without_period_cue',
                    'value': value_id, 'before': ['change', 'period_change'],
                    'after': ['change', 'unknown']}
    return None


def _apply_rate_rules(relationship, document, n1):
    """Correct rate/change classification when the wording is explicit.

    This never creates a relationship for an omitted value. It only reclassifies a relationship
    the model already emitted, using the value's own clause. An explicit parenthetical rate
    after an amount is a rate; a named rate/ratio with no movement is a rate; a bare percent in
    an increase/decrease is a change. The parenthetical test keeps 'increased at an annual rate
    of 3.4 percent' as a change.
    """
    if relationship.get('status') != 'resolved':
        return None
    candidates = {candidate['candidate_id']: candidate
                  for candidate in n1.get('candidates') or []}
    for value_id in relationship.get('value_candidate_ids') or []:
        candidate = candidates.get(value_id)
        if not candidate or candidate.get('candidate_type') != 'percentage':
            continue
        text = _local_text(document, candidate)
        explicit = next(((name, phrase) for name, phrases in RATE_COMPARISONS
                         for phrase in phrases if phrase in text), None)
        if explicit and _parenthetical_after_amount(text, candidate.get('raw_text', '').lower()):
            name = explicit[0]
            if (relationship.get('relationship_type'), relationship.get('comparison'),
                    relationship.get('direction')) == ('rate', name, 'not_applicable'):
                return None
            before = (relationship.get('relationship_type'), relationship.get('comparison'),
                      relationship.get('direction'))
            relationship['relationship_type'] = 'rate'
            relationship['comparison'] = name
            relationship['direction'] = 'not_applicable'
            return {'field': 'relationship_type', 'reason': 'explicit_parenthetical_rate',
                    'value': value_id, 'before': list(before),
                    'after': ['rate', name, 'not_applicable']}
        named_rate = any(word in text for word in RATE_WORDS)
        direction = _direction_in(text)
        if (explicit and not _parenthetical_after_amount(text, candidate.get('raw_text', '').lower())
                and relationship.get('relationship_type') == 'rate'
                and direction in ('increase', 'decrease')):
            before = (relationship.get('relationship_type'), relationship.get('comparison'),
                      relationship.get('direction'))
            relationship['relationship_type'] = 'change'
            relationship['comparison'] = explicit[0]
            relationship['direction'] = direction
            return {'field': 'relationship_type', 'reason': 'rate_phrase_with_movement',
                    'value': value_id, 'before': list(before),
                    'after': ['change', explicit[0], direction]}
        if relationship.get('relationship_type') == 'rate':
            if named_rate:
                if relationship.get('comparison') == 'unknown':
                    before = (relationship.get('relationship_type'),
                              relationship.get('comparison'),
                              relationship.get('direction'))
                    relationship['comparison'] = 'level'
                    relationship['direction'] = 'not_applicable'
                    return {'field': 'comparison', 'reason': 'named_rate_level',
                            'value': value_id, 'before': list(before),
                            'after': ['rate', 'level', 'not_applicable']}
                return None
            before = (relationship.get('relationship_type'), relationship.get('comparison'),
                      relationship.get('direction'))
            relationship['relationship_type'] = 'change'
            relationship['comparison'] = 'unknown'
            relationship['direction'] = direction
            return {'field': 'relationship_type', 'reason': 'rate_without_rate_phrase',
                    'value': value_id, 'before': list(before),
                    'after': ['change', 'unknown', direction]}
        if (relationship.get('relationship_type') == 'change' and named_rate
                and direction == 'unknown' and not explicit):
            before = (relationship.get('relationship_type'), relationship.get('comparison'),
                      relationship.get('direction'))
            relationship['relationship_type'] = 'rate'
            relationship['comparison'] = 'level'
            relationship['direction'] = 'not_applicable'
            return {'field': 'relationship_type', 'reason': 'named_rate_without_movement',
                    'value': value_id, 'before': list(before),
                    'after': ['rate', 'level', 'not_applicable']}
    return None


def _resolve_period(relationship, n1):
    """Attach a period only when the same sentence states one for this value.

    This is the deterministic fallback for a model that omitted an explicit period. It never
    takes a period from another sentence, never shares one period across values in different
    periods, and never invents a year. A month/quarter without a year is kept as raw text with
    an empty normalized period unless a title/paragraph candidate supplies the same slot.
    """
    if (relationship.get('period_candidate_ids') or relationship.get('period_raw')
            or relationship.get('period_source') == 'model_rejected'):
        return None
    if relationship.get('status') != 'resolved':
        return None
    candidates = {candidate['candidate_id']: candidate
                  for candidate in n1.get('candidates') or []}
    chosen = []
    for value_id in relationship.get('value_candidate_ids') or []:
        value = candidates.get(value_id)
        if not value:
            continue
        hints = _period_hints(n1, value)
        same_sentence = [hint for hint in hints if hint.get('relation') == 'same_sentence']
        if not same_sentence:
            continue
        best = min(same_sentence, key=lambda hint: hint.get('distance', 10 ** 9))
        if not _has_year(best):
            upgrades = [hint for hint in hints
                        if hint.get('relation') in ('title_same_month',
                                                    'same_paragraph_same_month')
                        and _temporal_slot(hint) == _temporal_slot(best)]
            if upgrades:
                upgrades.sort(key=lambda hint: (0 if hint.get('relation') == 'title_same_month'
                                                else 1, hint.get('start') or 0))
                best = upgrades[0]
        chosen.append(best)
    if not chosen:
        return None
    unique = {hint['candidate_id']: hint for hint in chosen}
    if len(unique) > 1:
        if len({_temporal_slot(hint) for hint in unique.values()}) > 1:
            return None
        with_year = {candidate_id: hint for candidate_id, hint in unique.items()
                     if _has_year(hint)}
        if with_year:
            if len({(hint.get('temporal') or {}).get('year')
                    for hint in with_year.values()}) > 1:
                return None
            unique = with_year
        if len(unique) > 1:
            # The same slot can be stated in the title and in the sentence. They are the same
            # period; keep the title one, otherwise the earliest candidate.
            best = sorted(unique.values(), key=lambda hint: (
                0 if hint.get('field') == 'title' else 1, hint.get('start') or 0))[0]
        else:
            best = next(iter(unique.values()))
    else:
        best = next(iter(unique.values()))
    relationship['period_candidate_ids'] = [best['candidate_id']]
    relationship['period_raw'] = best.get('raw_text') or ''
    relationship['period_evidence_quote'] = best.get('raw_text') or ''
    relationship['period_evidence_start'] = best.get('start')
    relationship['period_evidence_end'] = best.get('end')
    relationship['period_evidence_field'] = best.get('field') or ''
    relationship['period_source'] = 'program'
    relationship['period_rule'] = best.get('relation') or 'same_sentence'
    return best


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


def _accept_raw_relationships(raw_relationships, batch, batch_claim_ids, record, document,
                               n1, sentence_ids, expression_ids, document_period_ids,
                               period_candidates, rate_adjustments, comparison_adjustments,
                               relationship_deviations):
    """Validate raw model relationships for one batch and apply program corrections."""
    context_text = batch['context_text']
    batch_values = set(batch_claim_ids)
    window_candidates = _window_candidates(n1, batch['context_start'], batch['context_end'])
    window_ids = {candidate['candidate_id'] for candidate in window_candidates}
    window_positions = [(candidate['candidate_id'],
                         candidate['start'] - batch['context_start'],
                         candidate['end'] - batch['context_start'])
                        for candidate in window_candidates]
    accepted = []
    for raw in raw_relationships:
        if not isinstance(raw, dict):
            record['deviations'].append({'field': '*', 'reason': 'not_an_object', 'value': ''})
            continue
        relationship, deviations = _normalise_relationship(
            raw, document, sentence_ids, batch_values, window_ids, document_period_ids,
            window_positions, expression_ids, context_text, period_candidates)
        if not relationship['value_candidate_ids']:
            record['deviations'].extend(deviations or [])
            record['deviations'].append({'field': 'value_candidate_ids',
                                         'reason': 'not_in_batch', 'value': ''})
            continue
        record['deviations'].extend(deviations)
        relationship_deviations.extend(deviations)
        _resolve_period(relationship, n1)
        adjustment = _apply_rate_rules(relationship, document, n1)
        if adjustment:
            rate_adjustments.append((relationship, adjustment))
        adjustment = _apply_comparison_rules(relationship, document, n1)
        if adjustment:
            comparison_adjustments.append((relationship, adjustment))
        accepted.append(relationship)
    return accepted


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
    period_candidates = {candidate['candidate_id']: candidate
                         for candidate in _period_candidates(n1)}
    document_period_ids = set(period_candidates)
    relationships, relationship_deviations, batch_records = [], [], []
    rate_adjustments = []
    comparison_adjustments = []
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
                  'finish_reason': result.get('finish_reason', ''),
                  'token_limit_reached': False,
                  'context_chars': len(batch['context_text']),
                  'claim_value_count': len(batch_claim_ids),
                  'error': result.get('error', ''),
                  'deviations': []}
        if result.get('status') != 'ok':
            completion_tokens = (result.get('usage') or {}).get('completion_tokens')
            max_tokens = int(getattr(runner, 'max_tokens', 0) or 0)
            if (result.get('finish_reason') == 'length'
                    or (completion_tokens is not None and max_tokens
                        and int(completion_tokens) >= max_tokens)):
                record['token_limit_reached'] = True
            batch_records.append(record)
            continue
        completion_tokens = (result.get('usage') or {}).get('completion_tokens')
        finish_reason = result.get('finish_reason') or ''
        max_tokens = int(getattr(runner, 'max_tokens', 0) or 0)
        truncated = (finish_reason == 'length'
                     or (not finish_reason and completion_tokens is not None
                         and max_tokens and int(completion_tokens) >= max_tokens))
        if truncated:
            record['status'] = INVALID_OUTPUT
            record['token_limit_reached'] = True
            record['error'] = 'output_token_limit_reached'
            record['completion_tokens'] = completion_tokens
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
        batch_relationships = _accept_raw_relationships(
            raw_relationships, batch, batch_claim_ids, record, document, n1, sentence_ids,
            expression_ids, document_period_ids, period_candidates, rate_adjustments,
            comparison_adjustments, relationship_deviations)
        relationships.extend(batch_relationships)
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
    # Coverage retry: a model can say 'assigned' and still omit the relationship. One focused
    # retry for just the missing candidates is model-based, not a program default.
    assigned_ids = {candidate_id for relationship in relationships
                    if relationship.get('status') == 'resolved'
                    for candidate_id in relationship.get('value_candidate_ids') or []}
    noted = {item.get('candidate_id') for item in disposition_raw
             if item.get('status') in ('ambiguous', 'unresolved')}
    missing = [candidate_id for candidate_id in claim_value_ids
               if candidate_id not in assigned_ids and candidate_id not in noted]
    retry_records = []
    if missing:
        missing_candidates = [candidate for candidate in candidates
                              if candidate['candidate_id'] in set(missing)]
        for retry_batch in make_batches(document, missing_candidates,
                                        max_candidates=max_candidates, max_chars=max_chars):
            retry_ids = [value for value in retry_batch['candidate_ids']]
            payload = _batch_payload(document, n1, n2, retry_batch, retry_ids)
            batch_started = time.time()
            result = runner.run(payload)
            usage = result.get('usage') or {}
            record = {'claim_value_ids': retry_ids,
                      'status': result.get('status', FAILED),
                      'attempts': result.get('attempts', 0),
                      'seconds': result.get('seconds', round(time.time() - batch_started, 2)),
                      'input_chars': result.get('input_chars'),
                      'output_chars': result.get('output_chars'),
                      'prompt_tokens': usage.get('prompt_tokens'),
                      'completion_tokens': usage.get('completion_tokens'),
                      'parse_retry': result.get('parse_retry', False),
                      'finish_reason': result.get('finish_reason', ''),
                      'token_limit_reached': False,
                      'context_chars': len(retry_batch['context_text']),
                      'claim_value_count': len(retry_ids),
                      'error': result.get('error', ''),
                      'retry_for': 'coverage_missing',
                      'deviations': []}
            if result.get('status') != 'ok':
                completion_tokens = (result.get('usage') or {}).get('completion_tokens')
                max_tokens = int(getattr(runner, 'max_tokens', 0) or 0)
                if (result.get('finish_reason') == 'length'
                        or (completion_tokens is not None and max_tokens
                            and int(completion_tokens) >= max_tokens)):
                    record['token_limit_reached'] = True
                batch_records.append(record)
                retry_records.append(record)
                continue
            completion_tokens = usage.get('completion_tokens')
            finish_reason = result.get('finish_reason') or ''
            max_tokens = int(getattr(runner, 'max_tokens', 0) or 0)
            if (finish_reason == 'length'
                    or (not finish_reason and completion_tokens is not None
                        and max_tokens and int(completion_tokens) >= max_tokens)):
                record['status'] = INVALID_OUTPUT
                record['token_limit_reached'] = True
                record['error'] = 'output_token_limit_reached'
                record['completion_tokens'] = completion_tokens
                batch_records.append(record)
                retry_records.append(record)
                continue
            parsed = result['parsed']
            raw_relationships = parsed.get('relationships')
            raw_dispositions = parsed.get('candidate_dispositions')
            if not isinstance(raw_relationships, list) or not isinstance(raw_dispositions, list):
                record['status'] = SCHEMA_ERROR
                record['error'] = 'relationships or candidate_dispositions is not a list'
                batch_records.append(record)
                retry_records.append(record)
                continue
            retry_relationships = _accept_raw_relationships(
                raw_relationships, retry_batch, retry_ids, record, document, n1, sentence_ids,
                expression_ids, document_period_ids, period_candidates, rate_adjustments,
                comparison_adjustments, relationship_deviations)
            relationships.extend(retry_relationships)
            for item in raw_dispositions:
                if isinstance(item, dict) and item.get('candidate_id') in set(retry_ids):
                    disposition_raw.append(item)
                else:
                    record['deviations'].append({
                        'field': 'candidate_id', 'reason': 'not_in_batch',
                        'value': str(item.get('candidate_id') if isinstance(item, dict)
                                     else item)[:80]})
            record['status'] = (PARTIAL if (record['deviations'] or any(
                item.get('status') != 'resolved' for item in retry_relationships))
                else SUCCESS)
            batch_records.append(record)
            retry_records.append(record)
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
    period_adjustments = [{
        'relationship_id': relationship['relationship_id'],
        'value_candidate_ids': list(relationship['value_candidate_ids']),
        'field': 'period_candidate_ids',
        'reason': 'period_attached_by_program',
        'period_candidate_id': relationship['period_candidate_ids'][0],
        'period_raw': relationship['period_raw'],
        'rule': relationship['period_rule'],
    } for relationship in relationships if relationship.get('period_source') == 'program']
    program_adjustments = period_adjustments + [
        dict(adjustment, relationship_id=relationship['relationship_id'],
             value_candidate_ids=list(relationship['value_candidate_ids']))
        for relationship, adjustment in rate_adjustments + comparison_adjustments]
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
        'period_linked_relationships': sum(1 for item in relationships
                                           if item.get('period_candidate_ids')
                                           or item.get('period_raw')),
        'period_attached_by_program': len(period_adjustments),
        'rate_adjusted_by_program': len(rate_adjustments),
        'comparison_adjusted_by_program': len(comparison_adjustments),
        'coverage_retries': len(retry_records),
        'coverage_recovered': sum(
            1 for candidate_id in missing
            if any(relationship.get('status') == 'resolved'
                   and candidate_id in (relationship.get('value_candidate_ids') or [])
                   for relationship in relationships)),
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
                program_adjustments=program_adjustments,
                seconds=round(time.time() - started, 2))
