"""Shared plumbing for the model-driven claim nodes N2 and N3.

Both nodes call the same local llama.cpp service through the existing `LocalAnalyzer`, ask
for one JSON object per batch, validate the answer as data rather than trusting the schema,
and depend on N0/N1 positions for every quote and candidate they reference.

Nothing here selects or retries unboundedly: one JSON repair attempt, then the batch is
reported with an explicit failure status. A failed batch becomes explicit `unresolved`
results for its candidates, never a silent drop.
"""
from __future__ import annotations

import hashlib
import json
import time

from . import schema
from .analyzer import (CONNECT_REFUSED, CONNECT_RESET, ModelCallError, TIMEOUT,
                       LocalAnalyzer)

SUCCESS = 'success'
PARTIAL = 'partial'
FAILED = 'failed'
BLOCKED = 'blocked'
INVALID_OUTPUT = 'invalid_output'
MODEL_UNAVAILABLE = 'model_unavailable'
TIMEOUT_STATUS = 'timeout'
SCHEMA_ERROR = 'schema_error'
COVERAGE_ERROR = 'coverage_error'

FIELD_ORDER = {'title': 0, 'body': 1}


def sha256_text(text):
    return hashlib.sha256(str(text).encode('utf-8')).hexdigest()


def hash_json(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def prompt_hash(text):
    return sha256_text(text)[:16]


def schema_hash(value):
    return hash_json(value)[:16]


def failure_status(exc):
    if isinstance(exc, ModelCallError):
        if exc.cause == TIMEOUT:
            return TIMEOUT_STATUS
        if exc.cause in (CONNECT_REFUSED, CONNECT_RESET):
            return MODEL_UNAVAILABLE
    return FAILED


def make_client(settings, max_tokens, timeout, retries=1):
    """The offline client: temperature 0 and a bounded retry budget."""
    return LocalAnalyzer(settings.llm_base_url, settings.llm_model, timeout=timeout,
                         max_tokens=max_tokens, api_key=settings.llm_api_key,
                         connect_retries=settings.llm_connect_retries,
                         timeout_retries=settings.llm_timeout_retries,
                         backoff=tuple(float(part) for part in
                                       settings.llm_retry_backoff.split(',') if part.strip()),
                         retry_after_max=settings.llm_retry_after_max,
                         retry_max_seconds=settings.llm_retry_max_seconds,
                         api_style=settings.llm_api_style,
                         temperature=0.0)


def model_metadata(settings, max_tokens, response_format):
    return {
        'provider': 'llama.cpp',
        'model_id': settings.llm_model,
        # llama.cpp exposes no content hash for a loaded GGUF; recording a made-up value would
        # make a different model look identical, so this stays explicit.
        'model_fingerprint': 'unknown',
        'generation_params': {
            'temperature': 0.0,
            'max_tokens': int(max_tokens),
            'response_format': 'json_schema' if response_format else 'prompt_only',
            'seed': 'not_sent',
            'top_p': 'not_sent',
        },
    }


class JsonRunner:
    """One system prompt, one JSON repair attempt, explicit failure status."""

    def __init__(self, client, system, schema_definition, max_tokens, retries=1,
                 response_format=True):
        self.client = client
        self.system = system
        self.schema = schema_definition
        self.max_tokens = int(max_tokens)
        self.retries = max(0, int(retries))
        self.response_format = ({'type': 'json_object', 'schema': schema_definition}
                                if response_format else None)
        self.calls = 0
        self.failures = 0

    def run(self, payload):
        messages = [{'role': 'system', 'content': self.system},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        input_chars = len(messages[1]['content'])
        last_raw, error = '', ''
        total_seconds = 0.0
        usage = {}
        attempts_metrics = []
        for attempt in range(1, self.retries + 2):
            self.calls += 1
            started = time.time()
            detail = {}
            try:
                if hasattr(self.client, 'complete_detailed'):
                    raw, detail = self.client.complete_detailed(
                        messages, max_tokens=self.max_tokens, temperature=0.0,
                        response_format=self.response_format)
                    seconds = detail.get('seconds', time.time() - started)
                    usage = detail.get('usage') or {}
                else:
                    raw = self.client.complete(messages, max_tokens=self.max_tokens,
                                               temperature=0.0,
                                               response_format=self.response_format)
                    seconds = time.time() - started
            except ModelCallError as exc:
                self.failures += 1
                total_seconds += time.time() - started
                return {'status': failure_status(exc),
                        'error': f'{exc.cause}: {exc.detail}'[:300],
                        'attempts': attempt, 'raw': '',
                        'seconds': round(total_seconds, 2), 'input_chars': input_chars,
                        'output_chars': 0, 'usage': usage,
                        'attempts_metrics': attempts_metrics}
            total_seconds += float(seconds)
            attempts_metrics.append({'attempt': attempt, 'seconds': round(float(seconds), 2),
                                     'output_chars': len(raw), 'usage': usage})
            last_raw = raw
            try:
                parsed = schema._load_object(raw)
                if not isinstance(parsed, dict):
                    raise ValueError('top-level JSON is not an object')
                return {'status': 'ok', 'parsed': parsed, 'raw': raw, 'attempts': attempt,
                        'seconds': round(total_seconds, 2), 'input_chars': input_chars,
                        'output_chars': len(raw), 'usage': usage,
                        'finish_reason': detail.get('finish_reason', ''),
                        'parse_retry': attempt > 1, 'attempts_metrics': attempts_metrics,
                        'timings': detail.get('timings') or {}}
            except (ValueError, json.JSONDecodeError) as exc:
                error = f'{type(exc).__name__}: {exc}'[:300]
                messages = [messages[0], {
                    'role': 'user',
                    'content': ('Your previous answer was not valid JSON. Return the same '
                                'information as one raw JSON object, with no markdown and no '
                                'commentary.\n' + raw[:4000]),
                }]
        self.failures += 1
        return {'status': INVALID_OUTPUT, 'error': error, 'attempts': self.retries + 1,
                'raw': last_raw, 'seconds': round(total_seconds, 2),
                'input_chars': input_chars, 'output_chars': len(last_raw), 'usage': usage,
                'parse_retry': True, 'attempts_metrics': attempts_metrics}


def locate_quote(document, sentence_ids, quote):
    """(start, end, field) of a verbatim quote inside the declared sentences, or None.

    The document text is canonical (lower case, collapsed whitespace), and the model sees
    that text, so a case-folded comparison is the strictest check that still tolerates the
    model copying a capitalised token.
    """
    quote = str(quote or '').strip()
    ids = [value for value in (sentence_ids or []) if isinstance(value, str)]
    if not quote or not ids:
        return None
    sentences = {item['sentence_id']: item for item in document['sentences']}
    chosen = [sentences[value] for value in ids if value in sentences]
    if len(chosen) != len(set(ids)):
        return None
    fields = {item['field'] for item in chosen}
    if len(fields) != 1:
        return None
    start = min(item['start'] for item in chosen)
    end = max(item['end'] for item in chosen)
    haystack = document['text'][start:end]
    index = haystack.find(quote.lower())
    if index < 0:
        return None
    return start + index, start + index + len(quote.lower()), chosen[0]['field']


def _field_sentences(document):
    out = {}
    for sentence in document['sentences']:
        out.setdefault(sentence['field'], []).append(sentence)
    for values in out.values():
        values.sort(key=lambda item: item['start'])
    return out


def _candidate_payload(candidate):
    return {
        'candidate_id': candidate['candidate_id'],
        'candidate_type': candidate['candidate_type'],
        'raw_text': candidate['raw_text'],
        'value': candidate.get('value'),
        'scale': candidate.get('scale'),
        'unit': candidate.get('unit'),
        'currency': candidate.get('currency'),
        'temporal': candidate.get('temporal'),
        'start': candidate['start'],
        'end': candidate['end'],
        'sentence_id': candidate.get('sentence_id'),
        'paragraph_id': candidate.get('paragraph_id'),
        'cues': [{'term': cue['term'], 'role': cue['role']}
                 for cue in candidate.get('cues', [])],
    }


def make_batches(document, candidates, max_candidates=8, max_chars=3500):
    """Contiguous candidate batches with their sentence context.

    The batch is built around candidates, never around characters: the sentence holding a
    candidate is always included whole, and the previous/next sentence is added when the
    budget allows. Each candidate belongs to exactly one batch.
    """
    by_field = _field_sentences(document)
    ordered = sorted(candidates, key=lambda item: (
        FIELD_ORDER.get(item['field'], 9),
        next((pos for pos, sentence in enumerate(by_field.get(item['field'], []))
              if sentence['sentence_id'] == item.get('sentence_id')), item['start']),
        item['start']))
    batches, current = [], []

    def build(batch):
        field = batch[0]['field']
        sentences = by_field.get(field, [])
        positions = [pos for pos, sentence in enumerate(sentences)
                     if sentence['sentence_id'] in {item.get('sentence_id') for item in batch}]
        if not positions:
            # Last resort: a candidate with no sentence record must still reach the model,
            # never be dropped from the batch. The span is the candidate text itself.
            start = min(item['start'] for item in batch)
            end = max(item['end'] for item in batch)
            return {
                'field': field,
                'sentence_ids': [],
                'context_start': start, 'context_end': end,
                'context_text': document['text'][start:end],
                'sentences': [],
                'candidate_ids': [item['candidate_id'] for item in batch],
                'candidates': [_candidate_payload(item) for item in batch],
            }
        first, last = min(positions), max(positions)
        low, high = first, last
        if len(sentences) > 1:
            # one previous and one next sentence, if the character budget allows it
            trial_low, trial_high = max(0, first - 1), min(len(sentences) - 1, last + 1)
            if sentences[trial_high]['end'] - sentences[trial_low]['start'] <= max_chars * 1.5:
                low, high = trial_low, trial_high
        start = sentences[low]['start']
        end = sentences[high]['end']
        return {
            'field': field,
            'sentence_ids': [sentence['sentence_id'] for sentence in sentences[low:high + 1]],
            'context_start': start, 'context_end': end,
            'context_text': document['text'][start:end],
            'sentences': [{'sentence_id': sentence['sentence_id'],
                           'paragraph_id': sentence['paragraph_id'],
                           'text': sentence['text']} for sentence in sentences[low:high + 1]],
            'candidate_ids': [item['candidate_id'] for item in batch],
            'candidates': [_candidate_payload(item) for item in batch],
        }

    for candidate in ordered:
        if current and candidate['field'] != current[0]['field']:
            finished = build(current)
            if finished:
                batches.append(finished)
            current = [candidate]
            continue
        trial = current + [candidate]
        batch = build(trial)
        too_large = (batch is not None and len(trial) > max_candidates) or (
            batch is not None and len(current) > 0
            and batch['context_end'] - batch['context_start'] > max_chars)
        if current and too_large:
            finished = build(current)
            if finished:
                batches.append(finished)
            current = [candidate]
        else:
            current = trial
    if current:
        finished = build(current)
        if finished:
            batches.append(finished)
    return batches


def hash_n1(n1):
    return hash_json(n1)


def hash_n2(n2):
    return hash_json(n2)


def node_input_hash(parts):
    return hash_json(parts)
