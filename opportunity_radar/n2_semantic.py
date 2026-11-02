"""N2: what does each numeric candidate describe?

N2 answers one question per N1 atom: is this number the value of a claim, a date/period or
other context number, a non-economic identifier, or something the context cannot settle?
It never rescans the text, never computes a value, and never decides direction or
comparison basis - those belong to N3.

The model sees bounded sentence windows, not the whole article, and one batch is one call.
Every input candidate gets exactly one interpretation. A model answer that omits, duplicates
or invents a candidate is repaired into an explicit `unresolved` result and recorded as a
deviation; nothing is dropped silently.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from . import claim_contract
from .semantic_common import (COVERAGE_ERROR, FAILED, INVALID_OUTPUT, PARTIAL, SCHEMA_ERROR,
                              SUCCESS,
                              JsonRunner, hash_json, locate_quote, make_batches,
                              model_metadata, node_input_hash, prompt_hash, schema_hash)

NODE = 'N2'
NODE_VERSION = 'n2-v2'
PROMPT_VERSION = 'n2-prompt-v2'
SCHEMA_VERSION = 'n2-schema-v2'
# Program validation is part of what a cached N2 result means: a rule change must not reuse
# a result produced by the old checks.
RULESET = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:16]

DISPOSITIONS = ('claim_value', 'context_only', 'non_claim', 'ambiguous', 'unresolved')
# `system_inference` is deliberately excluded: N2 must not present a model inference as a
# statement the source makes.
KINDS = tuple(kind for kind in claim_contract.KINDS if kind != 'system_inference')
STATUSES = ('resolved', 'ambiguous', 'unresolved')
ECONOMIC_RELEVANCE = ('economic', 'non_economic', 'uncertain')

SYSTEM_PROMPT = """You are a deterministic information-extraction component. You receive a context window from one article and the numeric candidates that a scanner already found in it. For each candidate, decide what the number describes.

Return only JSON with this shape:
{"interpretations": [{"candidate_id": "...", "economic_relevance": "economic|non_economic|uncertain", "disposition": "claim_value|context_only|non_claim|ambiguous|unresolved", "subject": "...", "predicate": "...", "kind": "fact|source_interpretation|hypothesis|forecast|opinion|unknown", "reason": "...", "evidence_sentence_ids": ["s0001"], "evidence_quote": "...", "status": "resolved|ambiguous|unresolved"}]}

Rules:
- Return exactly one object for every supplied candidate_id. Never omit, duplicate or invent a candidate.
- Use only the supplied context. Never use outside knowledge.
- First decide economic_relevance. economic means the number is a business, financial, industry, market or official-statistics measure (revenue, cost, price, output, capacity, shipments, margin, profit, GDP, inflation, trade, employment, vehicle_count ...). non_economic means a software or model version, object/model id, technical parameter (opacity, resolution, grid size, timestep, FPS, coordinate, file size, benchmark time), age or death age, phone number, citation or similar. uncertain means the context does not settle it.
- If economic_relevance is non_economic, disposition MUST be non_claim (or context_only for a date/period). If uncertain, do not force claim_value: use ambiguous with a reason. A technical value is not a commercial claim merely because a company publishes it.
- disposition=claim_value: the number is the value of a statement about a subject and a measure. subject and predicate are required. predicate is the measure itself: personal_income for "personal income increased $54.5 billion" and also for "personal income increased 0.2 percent"; disposable_personal_income; personal_consumption_expenditures; personal_saving; personal_saving_rate; vehicle_count for "5 million vehicles". Never write increase_amount, monthly_change, change, growth_rate, amount or any direction/relationship word in the predicate; another node decides level versus change.
- subject must be the entity the measure belongs to, named in the same clause as the number. It is not the measure itself: "Intel reported revenue of $16.5 billion" has subject intel and predicate revenue, not subject revenue. "Google value plunges by $500bn" has subject google and predicate market_value, not subject google_value. If the clause names disposable personal income, use disposable_personal_income even when the previous sentence spoke about personal income. Do not carry a subject over from an earlier clause.
- disposition=context_only: a date, period, comparison basis or other supporting number that does not itself state a claim. subject/predicate may be empty.
- disposition=non_claim: an identifier, phone number, form number, version, citation or other non-economic number.
- disposition=ambiguous: more than one reasonable reading and the context does not settle it. Give the reason.
- disposition=unresolved: you cannot interpret it. Give the reason. Never invent a subject or measure to fill the field.
- kind follows the source statement: a figure a government or company publishes is fact; a forecast stays forecast; interpretation, hypothesis and opinion keep their own kind. Never use system_inference.
- Do not decide level versus change, increase versus decrease, year-over-year versus month-over-month, monthly rate versus period change, revision status, or seasonality. Another node does that.
- Keep a percentage and a percentage point distinct in the predicate when the raw text does.
- Do not put direction or movement words (increase, plunge, surge, fall, rise, growth, decline, drop, gain, slide) in the predicate; they belong to N3.
- reason must be one short sentence, at most 25 words.
- evidence_quote must be the shortest exact contiguous excerpt copied from the supplied context that includes the number and the words naming its subject or measure when the sentence provides them. Do not quote the bare number when the clause states who or what it describes. Do not paraphrase, join separate excerpts, translate or add ellipses. evidence_sentence_ids are the sentence ids that contain it (at least one for claim_value).
- status=resolved only when the interpretation is settled. Use ambiguous or unresolved rather than guessing.
"""

SCHEMA = {
    'type': 'object',
    'properties': {
        'interpretations': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'candidate_id': {'type': 'string'},
                    'economic_relevance': {'type': 'string',
                                           'enum': list(ECONOMIC_RELEVANCE)},
                    'disposition': {'type': 'string', 'enum': list(DISPOSITIONS)},
                    'subject': {'type': 'string'},
                    'predicate': {'type': 'string'},
                    'kind': {'type': 'string', 'enum': list(KINDS)},
                    'reason': {'type': 'string'},
                    'evidence_sentence_ids': {'type': 'array', 'items': {'type': 'string'}},
                    'evidence_quote': {'type': 'string'},
                    'status': {'type': 'string', 'enum': list(STATUSES)},
                },
                'required': ['candidate_id', 'economic_relevance', 'disposition', 'subject',
                             'predicate', 'kind', 'reason', 'evidence_sentence_ids',
                             'evidence_quote', 'status'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['interpretations'],
    'additionalProperties': False,
}

MAX_REASON = 600
MAX_QUOTE = 1000
# The model sometimes slips a relationship into the measure ("increase_amount",
# "monthly_change"), which is N3's decision. When it does, the measure is rebuilt from the
# subject and the substitution is recorded; the model's wording is kept in predicate_raw.
RELATIONSHIP_WORDS = {'increase', 'increased', 'decrease', 'decreased', 'rise', 'rose',
                      'fall', 'fell', 'growth', 'grow', 'grew', 'change', 'decline',
                      'declined', 'drop', 'dropped', 'gain', 'gained', 'loss', 'plunge',
                      'plunged', 'surge', 'surged', 'jump', 'jumped', 'climb', 'climbed',
                      'slide', 'slid', 'slump', 'slumped', 'soar', 'soared', 'tumble',
                      'tumbled', 'rally', 'rallied', 'rebound', 'rebounded', 'spike',
                      'spiked', 'dive', 'dived', 'slip', 'slipped', 'retreat', 'retreated',
                      'monthly', 'annual', 'quarterly', 'yoy', 'mom', 'qoq'}
GENERIC_MEASURES = {'amount', 'rate', 'value', 'level', 'total'}


def _measure_from_subject(subject):
    slug = re.sub(r'[^a-z0-9]+', '_', subject.lower()).strip('_')
    return slug[:claim_contract.MAX_PREDICATE]


def input_hash(document, n1, model):
    return node_input_hash({
        'node': NODE, 'node_version': NODE_VERSION,
        'document_id': document.get('document_id'),
        'text_hash': document.get('text_hash'),
        'n1_hash': hash_json(n1),
        'prompt_version': PROMPT_VERSION, 'prompt_hash': prompt_hash(SYSTEM_PROMPT),
        'schema_version': SCHEMA_VERSION, 'schema_hash': schema_hash(SCHEMA),
        'ruleset': RULESET,
        'model': model,
    })


def _unresolved(candidate_id, reason, deviations=None):
    return {
        'candidate_id': candidate_id,
        'economic_relevance': 'unknown',
        'relevance_raw': '',
        'model_disposition': '',
        'model_status': '',
        'model_kind': '',
        'model_subject': '',
        'model_predicate': '',
        'disposition': 'unresolved',
        'subject': '', 'predicate': '', 'predicate_raw': '', 'predicate_source': 'none',
        'kind': 'unknown',
        'reason': str(reason)[:MAX_REASON],
        'evidence_sentence_ids': [], 'evidence_quote': '',
        'evidence_start': None, 'evidence_end': None, 'evidence_field': None,
        'status': 'unresolved',
        'deviations': list(deviations or []),
    }


def _normalise(raw, candidate, document, sentence_ids):
    """(record, deviations) for one model item. Never invents a claim."""
    deviations = []
    disposition = str(raw.get('disposition') or '').strip().lower()
    model_disposition = disposition
    if disposition not in DISPOSITIONS:
        deviations.append({'field': 'disposition', 'reason': 'unknown_value',
                           'value': disposition[:80]})
        disposition = 'unresolved'
    relevance_raw = str(raw.get('economic_relevance') or '').strip().lower()
    if relevance_raw not in ECONOMIC_RELEVANCE:
        deviations.append({'field': 'economic_relevance', 'reason': 'unknown_value',
                           'value': relevance_raw[:80]})
        economic_relevance = 'uncertain'
    else:
        economic_relevance = relevance_raw
    subject = str(raw.get('subject') or '').strip()
    predicate = str(raw.get('predicate') or '').strip()
    model_subject, model_predicate = subject, predicate
    kind = str(raw.get('kind') or '').strip().lower()
    model_kind = kind
    if kind not in KINDS:
        deviations.append({'field': 'kind', 'reason': 'unknown_value', 'value': kind[:80]})
        kind = 'unknown'
    reason = str(raw.get('reason') or '').strip()
    ids = raw.get('evidence_sentence_ids')
    ids = [value for value in ids if isinstance(value, str)] if isinstance(ids, list) else []
    valid_ids = [value for value in ids if value in sentence_ids]
    if len(valid_ids) != len(ids):
        deviations.append({'field': 'evidence_sentence_ids', 'reason': 'unknown_sentence',
                           'value': ','.join(value for value in ids if value not in sentence_ids)[:120]})
    quote = str(raw.get('evidence_quote') or '').strip()
    locator = locate_quote(document, valid_ids, quote) if valid_ids and quote else None
    if quote and locator is None:
        deviations.append({'field': 'evidence_quote', 'reason': 'not_located',
                           'value': quote[:120]})
    if len(quote) > MAX_QUOTE:
        deviations.append({'field': 'evidence_quote', 'reason': 'too_long',
                           'value': str(len(quote))})
    if len(subject) > claim_contract.MAX_SUBJECT:
        deviations.append({'field': 'subject', 'reason': 'too_long', 'value': str(len(subject))})
    if len(predicate) > claim_contract.MAX_PREDICATE:
        deviations.append({'field': 'predicate', 'reason': 'too_long',
                           'value': str(len(predicate))})
    if len(reason) > MAX_REASON:
        deviations.append({'field': 'reason', 'reason': 'too_long', 'value': str(len(reason))})

    predicate_raw = predicate
    predicate_source = 'model'
    if disposition == 'claim_value' and subject:
        tokens = re.split(r'[^a-z0-9]+', predicate.lower())
        if (any(token in RELATIONSHIP_WORDS for token in tokens)
                or predicate.lower() in GENERIC_MEASURES):
            cleaned = '_'.join(token for token in tokens
                               if token and token not in RELATIONSHIP_WORDS)
            fallback = (cleaned if cleaned and cleaned not in GENERIC_MEASURES
                        else _measure_from_subject(subject))
            if fallback:
                deviations.append({'field': 'predicate', 'reason': 'relationship_leak',
                                   'value': predicate[:80]})
                predicate = fallback
                predicate_source = ('direction_removed'
                                    if cleaned and cleaned not in GENERIC_MEASURES
                                    else 'subject_fallback')

    model_status = str(raw.get('status') or '').strip().lower()
    status = model_status
    if status not in STATUSES:
        deviations.append({'field': 'status', 'reason': 'unknown_value', 'value': status[:80]})
        status = 'resolved'
    if disposition == 'claim_value' and economic_relevance == 'non_economic':
        deviations.append({'field': 'economic_relevance',
                           'reason': 'non_economic_claim_value',
                           'value': relevance_raw})
        disposition = 'non_claim'
        status = 'resolved'
        kind = 'unknown'
    elif disposition == 'claim_value' and economic_relevance == 'uncertain':
        deviations.append({'field': 'economic_relevance',
                           'reason': 'economic_relevance_uncertain',
                           'value': relevance_raw})
        disposition = 'ambiguous'
        status = 'ambiguous'
        kind = 'unknown'
    if disposition == 'claim_value':
        if not subject or not predicate:
            deviations.append({'field': '*', 'reason': 'claim_value_without_subject_or_predicate',
                               'value': ''})
            status = 'unresolved'
        elif locator is None:
            deviations.append({'field': 'evidence_quote', 'reason': 'claim_value_without_evidence',
                               'value': ''})
            status = 'unresolved'
        elif (len(subject) > claim_contract.MAX_SUBJECT
              or len(predicate) > claim_contract.MAX_PREDICATE or len(quote) > MAX_QUOTE):
            status = 'unresolved'
    elif disposition == 'ambiguous':
        status = 'ambiguous'
    elif disposition == 'unresolved':
        status = 'unresolved'
    elif status == 'resolved':
        # context_only / non_claim may be resolved, but the model may also say ambiguous.
        pass
    return ({
        'candidate_id': candidate['candidate_id'],
        'economic_relevance': economic_relevance,
        'relevance_raw': relevance_raw,
        'model_disposition': model_disposition,
        'model_status': model_status,
        'model_kind': model_kind,
        'model_subject': model_subject,
        'model_predicate': model_predicate,
        'disposition': disposition,
        # Long values are kept as the model wrote them and marked with a deviation; trimming
        # them here would be the silent truncation the contract forbids.
        'subject': subject,
        'predicate': predicate,
        'predicate_raw': predicate_raw,
        'predicate_source': predicate_source,
        'kind': kind,
        'reason': reason,
        'evidence_sentence_ids': valid_ids,
        'evidence_quote': quote,
        'evidence_start': locator[0] if locator else None,
        'evidence_end': locator[1] if locator else None,
        'evidence_field': locator[2] if locator else None,
        'status': status,
        'deviations': deviations,
    }, deviations)


def _batch_payload(document, batch):
    return {
        'task': 'Interpret each numeric candidate. Return one interpretation per candidate_id.',
        'article': {'title': document.get('title', ''), 'document_id': document.get('document_id')},
        'context': {
            'field': batch['field'],
            'sentences': batch['sentences'],
        },
        'candidates': batch['candidates'],
        'allowed': {
            'dispositions': list(DISPOSITIONS),
            'kinds': list(KINDS),
            'statuses': list(STATUSES),
        },
    }


def run(document, n1, runner, model, max_candidates=4, max_chars=3500):
    """N2 for one document. `runner` is a JsonRunner (or a test double with .run(payload))."""
    if not isinstance(document, dict) or not isinstance(n1, dict):
        raise ValueError('N2 needs the N0 document dict and the N1 output dict')
    if document.get('document_id') != n1.get('document_id'):
        raise ValueError('N2 input document and N1 output are from different documents')
    candidates = list(n1.get('candidates') or [])
    started = time.time()
    computed_hash = input_hash(document, n1, model)
    base = {
        'node': NODE, 'node_version': NODE_VERSION,
        'document_id': document.get('document_id'),
        'input_hash': computed_hash,
        'prompt_version': PROMPT_VERSION, 'prompt_hash': prompt_hash(SYSTEM_PROMPT),
        'schema_version': SCHEMA_VERSION, 'schema_hash': schema_hash(SCHEMA),
        'ruleset': RULESET,
        'model': model,
    }
    if not candidates:
        statistics = {'input_candidate_count': 0, 'resolved_count': 0, 'claim_value_count': 0,
                      'context_only_count': 0, 'non_claim_count': 0, 'ambiguous_count': 0,
                      'unresolved_count': 0, 'batch_count': 0, 'failed_batches': 0}
        return dict(base, status=SUCCESS, candidate_interpretations=[], batches=[],
                    statistics=statistics, seconds=round(time.time() - started, 2))

    sentence_ids = {item['sentence_id'] for item in document['sentences']}
    batches = make_batches(document, candidates, max_candidates=max_candidates,
                           max_chars=max_chars)
    interpretations, batch_records = [], []
    for batch in batches:
        batch_started = time.time()
        result = runner.run(_batch_payload(document, batch))
        expected = set(batch['candidate_ids'])
        usage = result.get('usage') or {}
        record = {'candidate_ids': list(batch['candidate_ids']),
                  'status': result.get('status', FAILED),
                  'attempts': result.get('attempts', 0),
                  'seconds': result.get('seconds', round(time.time() - batch_started, 2)),
                  'input_chars': result.get('input_chars'),
                  'output_chars': result.get('output_chars'),
                  'prompt_tokens': usage.get('prompt_tokens'),
                  'completion_tokens': usage.get('completion_tokens'),
                  'parse_retry': result.get('parse_retry', False),
                  'context_chars': len(batch['context_text']),
                  'candidate_count': len(batch['candidate_ids']),
                  'error': result.get('error', ''),
                  'unknown_candidate_ids': [], 'duplicate_candidate_ids': [],
                  'deviations': []}
        if result.get('status') != 'ok':
            for candidate_id in batch['candidate_ids']:
                interpretations.append(_unresolved(
                    candidate_id, f"model_{record['status']}: {record['error'] or 'no output'}",
                    [{'field': '*', 'reason': record['status'], 'value': ''}]))
            batch_records.append(record)
            continue
        parsed = result['parsed']
        raw_items = parsed.get('interpretations')
        if not isinstance(raw_items, list):
            record['status'] = SCHEMA_ERROR
            record['error'] = 'interpretations is not a list'
            for candidate_id in batch['candidate_ids']:
                interpretations.append(_unresolved(
                    candidate_id, 'model_output_schema_error',
                    [{'field': '*', 'reason': 'schema_error', 'value': ''}]))
            batch_records.append(record)
            continue
        by_id = {}
        for item in raw_items:
            if not isinstance(item, dict):
                record['deviations'].append({'field': '*', 'reason': 'not_an_object',
                                             'value': ''})
                continue
            candidate_id = item.get('candidate_id')
            if candidate_id not in expected:
                record['unknown_candidate_ids'].append(str(candidate_id)[:80])
                continue
            if candidate_id in by_id:
                record['duplicate_candidate_ids'].append(candidate_id)
                continue
            by_id[candidate_id] = item
        for candidate in batch['candidates']:
            candidate_id = candidate['candidate_id']
            item = by_id.get(candidate_id)
            if item is None:
                record['deviations'].append({'field': '*', 'reason': 'model_omitted_candidate',
                                             'value': candidate_id})
                interpretations.append(_unresolved(
                    candidate_id, 'model_omitted_candidate',
                    [{'field': '*', 'reason': 'coverage_error', 'value': candidate_id}]))
                continue
            normalised, deviations = _normalise(item, candidate, document, sentence_ids)
            record['deviations'].extend(deviations)
            interpretations.append(normalised)
        if record['deviations'] or record['unknown_candidate_ids'] or record['duplicate_candidate_ids']:
            record['status'] = PARTIAL
        else:
            record['status'] = SUCCESS
        batch_records.append(record)

    order = {candidate['candidate_id']: index for index, candidate in enumerate(candidates)}
    interpretations.sort(key=lambda item: order.get(item['candidate_id'], 10 ** 6))
    stats = {'input_candidate_count': len(candidates), 'batch_count': len(batches),
             'failed_batches': sum(1 for record in batch_records
                                   if record['status'] not in (SUCCESS, PARTIAL))}
    stats['claim_value_count'] = sum(1 for item in interpretations
                                     if item['disposition'] == 'claim_value'
                                     and item['status'] == 'resolved')
    stats['context_only_count'] = sum(1 for item in interpretations
                                      if item['disposition'] == 'context_only')
    stats['non_claim_count'] = sum(1 for item in interpretations
                                   if item['disposition'] == 'non_claim')
    stats['claim_value_total'] = sum(1 for item in interpretations
                                     if item['disposition'] == 'claim_value')
    stats['unresolved_count'] = sum(1 for item in interpretations
                                    if item['status'] == 'unresolved')
    stats['ambiguous_count'] = sum(1 for item in interpretations
                                   if item['status'] == 'ambiguous')
    stats['resolved_count'] = sum(1 for item in interpretations
                                  if item['status'] == 'resolved')
    stats['coverage_complete'] = (len(interpretations) == len(candidates)
                                  and len({item['candidate_id'] for item in interpretations})
                                  == len(candidates))
    if not stats['coverage_complete']:
        stats['coverage_error'] = COVERAGE_ERROR
    failed = [record for record in batch_records if record['status'] not in (SUCCESS, PARTIAL)]
    if failed and len(failed) == len(batch_records):
        statuses = {record['status'] for record in failed}
        status = statuses.pop() if len(statuses) == 1 else FAILED
    elif failed or not stats['coverage_complete'] or any(
            record['deviations'] or record['unknown_candidate_ids']
            or record['duplicate_candidate_ids'] for record in batch_records):
        status = PARTIAL
    else:
        status = SUCCESS
    return dict(base, status=status, candidate_interpretations=interpretations,
                batches=batch_records, statistics=stats,
                seconds=round(time.time() - started, 2))
