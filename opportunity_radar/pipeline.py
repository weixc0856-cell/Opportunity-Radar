"""The single production pipeline that runs after article analysis.

The daily digest used to stop at `analyses`: events were assigned, but Evidence, Claim,
verification, entities, opportunities and quality metrics were only produced by manual
CLIs. This module makes that post-analysis chain part of the daily run and records each
step, so a partial pipeline is visible instead of being mistaken for a complete issue.

Order matters:
    R1 backfill -> N0-N5 claims -> entities -> lineage -> event candidates
    -> verification -> opportunity discovery -> economic refresh -> quality snapshot

The N0-N5 step is bounded (default 8 articles per run) because it makes two local-model
calls per article. The bound and the skipped count are recorded; they are never hidden.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from . import (article_text, economic, numeric_candidates, n2_semantic, n3_relationships,
               n4_normalization, n5_assembly, opportunity_discovery, quality,
               semantic_common, unified, unified_main, verify)
from .pipeline_store import PipelineStore
from .store import Store

DEFAULT_CLAIM_STORE = Path('data/claim-pipeline/node_runs.sqlite3')
DEFAULT_CLAIM_LIMIT = 8


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _node_params(node, max_tokens):
    return {'node': node, 'temperature': 0.0, 'max_tokens': int(max_tokens),
            'response_format': 'json_schema'}


def _record(store, article, document, node, version, input_hash, output, params, tools,
            status='ok'):
    if store is None:
        return
    store.record(article_id=article.article_id, document_id=document.get('document_id', ''),
                 content_hash=document.get('content_hash', ''), node_name=node,
                 node_version=version, input_hash=input_hash, output=output,
                 params=params, tools=tools, status=status)


def _has_n5(conn, article_key):
    try:
        return conn.execute(
            "SELECT 1 FROM claims WHERE article_key=? AND extractor='n5' LIMIT 1",
            (article_key,)).fetchone() is not None
    except Exception:
        return False


def _prepare(article):
    payload = {
        'article_id': article.article_id or article.url,
        'source_id': article.feed_id or article.source_name,
        'title': article.title,
        'content': article.summary,
        'content_format': 'html',
        'source_url': article.url,
    }
    text = article_text.build(payload)
    document = text.to_dict()
    n1 = numeric_candidates.extract(text)
    return payload, text, document, n1


def _promote(db_path, article, article_key, document, n5, source_id, event_id):
    """Write N5 claims and their evidence. Returns (evidence, claims, links, rejected)."""
    store = unified.UnifiedStore(db_path, migrate=False)
    evidences, claims, links, rejected = [], [], [], []
    for index, claim in enumerate(n5.get('claims') or [], 1):
        quote = str(claim.get('quote') or '').strip()
        trace = claim.get('trace') or {}
        field = trace.get('evidence_field') or 'summary'
        start = trace.get('evidence_start')
        end = trace.get('evidence_end')
        if not quote or start is None or end is None:
            rejected.append({'reason': 'evidence_locator_missing', 'claim': claim.get('claim_id')})
            continue
        locator = {'field': field, 'start': int(start), 'length': int(end) - int(start),
                   'document_id': document.get('document_id', ''),
                   'locator_basis': 'n0_document'}
        locator_json = json.dumps(locator, ensure_ascii=False, sort_keys=True)
        evidence_id = unified.evidence_id_for(article_key, quote, locator)
        evidence = {
            'evidence_id': evidence_id, 'article_key': article_key,
            'source_id': source_id or '', 'evidence_kind': 'quote', 'quote': quote,
            'locator_json': locator_json, 'source_family': '', 'independence': 'unknown',
            'observed_at': article.published or '', 'rules_version': 'r2-v4',
            'created_at': unified.now(),
        }
        claim_id = unified.claim_id_for(article_key,
                                        key_parts=('n5', article_key, claim.get('claim_id') or index))
        record = {
            'claim_id': claim_id, 'article_key': article_key, 'event_id': event_id,
            'fact_ordinal': index,
            'subject': claim.get('subject') or '', 'predicate': claim.get('predicate') or '',
            'value_num': claim.get('value_num'), 'value_text': claim.get('value_text') or quote,
            'unit': claim.get('unit') or '', 'unit_raw': claim.get('unit_raw') or '',
            'scale': claim.get('scale') or '', 'currency': claim.get('currency') or '',
            'region': claim.get('region') or '', 'period': claim.get('period') or '',
            'period_raw': claim.get('period_raw') or '',
            'comparison': claim.get('comparison') or 'unknown',
            'denominator': claim.get('denominator') or '',
            'seasonality': claim.get('seasonality') or 'unknown',
            'revision': claim.get('revision') or 'unknown',
            'revision_raw': claim.get('revision_raw') or '',
            'kind': claim.get('kind') or 'unknown', 'quote': quote,
            'locator_json': locator_json, 'verification_state': 'unverified',
            'extractor': 'n5', 'rules_version': 'r2-v4', 'created_at': unified.now(),
        }
        evidences.append(evidence)
        claims.append(record)
        links.append((claim_id, evidence_id, 'direct', 'unknown', locator_json, unified.now()))
    written = store.bulk_add(evidences, claims, links)
    return {'evidences': written.get('evidences', 0), 'claims': written.get('claims', 0),
            'links': written.get('links', 0),
            'rejected': rejected + list(written.get('rejected') or [])}


def run_claim_pipeline(db_path, articles, analyzed_keys, settings, limit=None,
                       store_path=DEFAULT_CLAIM_STORE, logger=logging):
    """N0-N5 for new articles with numeric candidates, bounded and idempotent."""
    if not settings:
        return {'status': 'skipped', 'reason': 'no settings'}
    limit = int(limit if limit is not None else
                os.getenv('OR_CLAIM_PIPELINE_MAX_ARTICLES', DEFAULT_CLAIM_LIMIT))
    if limit <= 0:
        return {'status': 'skipped', 'reason': 'disabled', 'limit': limit}
    store = PipelineStore(store_path)
    client = semantic_common.make_client(settings, max_tokens=2400,
                                         timeout=max(settings.llm_timeout, 600))
    model = semantic_common.model_metadata(settings, 2400, True)
    db = Store(db_path, migrate=False)
    with db.connect() as conn:
        already = {row[0] for row in conn.execute(
            "SELECT DISTINCT article_key FROM claims WHERE extractor='n5'")}
        analysed = {row[0] for row in conn.execute('SELECT article_key FROM analyses')}
    processed = skipped_existing = skipped_no_numbers = failed = 0
    claims_written = evidences_written = 0
    details = []
    for article in articles:
        if processed >= limit:
            break
        article_key = Store.key(article.url)
        if article_key in already:
            skipped_existing += 1
            continue
        # A previously analysed article can still be missing N5 claims (the run cap or a
        # killed run). The fetched body is available, so backfill it on this run.
        if article_key not in analysed:
            continue
        if not str(article.summary or '').strip():
            skipped_no_numbers += 1
            continue
        try:
            payload, text, document, n1 = _prepare(article)
            _record(store, article, document, 'N0', article_text.VERSION,
                    _hash({'title': payload['title'], 'content': payload['content'],
                           'content_format': payload['content_format'],
                           'version': article_text.VERSION,
                           'ruleset': article_text.RULESET}), document,
                    {'content_format': 'html', 'ruleset': article_text.RULESET},
                    {'python': 'stdlib'})
            n1_input = _hash({'document_id': document.get('document_id'),
                              'text_hash': document.get('text_hash'),
                              'paragraphs': len(document.get('paragraphs') or []),
                              'sentences': len(document.get('sentences') or []),
                              'version': article_text.VERSION,
                              'ruleset': numeric_candidates.RULESET})
            _record(store, article, document, 'N1', numeric_candidates.VERSION, n1_input, n1,
                    {'recognizers': 'off', 'ruleset': numeric_candidates.RULESET},
                    {'python': 'stdlib'})
            if not (n1.get('candidates') or []):
                skipped_no_numbers += 1
                continue
            n2_runner = semantic_common.JsonRunner(client, n2_semantic.SYSTEM_PROMPT,
                                                   n2_semantic.SCHEMA, 1600, retries=1)
            n2 = n2_semantic.run(document, n1, n2_runner, model, max_candidates=4)
            _record(store, article, document, 'N2', n2_semantic.NODE_VERSION,
                    n2_semantic.input_hash(document, n1, model), n2,
                    _node_params('N2', 1600), {'model': model},
                    'ok' if n2.get('status') in ('success', 'partial') else 'failed')
            if n2.get('status') not in ('success', 'partial'):
                failed += 1
                details.append({'article_key': article_key, 'error': 'n2 ' + str(n2.get('status'))})
                continue
            n3_runner = semantic_common.JsonRunner(client, n3_relationships.SYSTEM_PROMPT,
                                                   n3_relationships.SCHEMA, 2400, retries=1)
            n3 = n3_relationships.run(document, n1, n2, n3_runner, model, max_candidates=4)
            _record(store, article, document, 'N3', n3_relationships.NODE_VERSION,
                    n3_relationships.input_hash(document, n1, n2, model), n3,
                    _node_params('N3', 2400), {'model': model},
                    'ok' if n3.get('status') in ('success', 'partial') else 'failed')
            n4 = n4_normalization.normalize(document, n1, n2, n3)
            _record(store, article, document, 'N4', n4_normalization.NODE_VERSION,
                    n4_normalization.input_hash(document, n1, n2, n3), n4,
                    _node_params('N4', 0), {'python': 'stdlib'},
                    'ok' if n4.get('status') in ('success', 'partial') else 'failed')
            n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
            _record(store, article, document, 'N5', n5_assembly.NODE_VERSION,
                    n5_assembly.input_hash(document, n1, n2, n3, n4), n5,
                    _node_params('N5', 0), {'python': 'stdlib'},
                    'ok' if n5.get('status') in ('success', 'partial') else 'failed')
            with Store(db_path, migrate=False).connect() as conn:
                row = conn.execute('SELECT source_id FROM articles WHERE article_key=?',
                                   (article_key,)).fetchone()
                source_id = row['source_id'] if row else ''
                event = conn.execute('SELECT event_id FROM event_articles WHERE article_key=?',
                                     (article_key,)).fetchone()
                event_id = event['event_id'] if event else None
            promoted = _promote(db_path, article, article_key, document, n5, source_id, event_id)
            claims_written += promoted['claims']
            evidences_written += promoted['evidences']
            processed += 1
            details.append({'article_key': article_key,
                            'n2': n2.get('status'), 'n3': n3.get('status'),
                            'n4': n4.get('status'), 'n5': n5.get('status'),
                            'claims': promoted['claims'], 'rejected': promoted['rejected'][:5]})
        except Exception as exc:
            failed += 1
            logger.warning('Claim pipeline failed for %s: %s', article.url, exc, exc_info=True)
            details.append({'article_key': article_key,
                            'error': f'{type(exc).__name__}: {exc}'[:300]})
    status = 'success' if not failed else ('partial' if processed else 'failed')
    return {'status': status, 'limit': limit, 'processed': processed,
            'skipped_already_processed': skipped_existing,
            'skipped_no_numeric_candidates': skipped_no_numbers,
            'failed': failed, 'claims_written': claims_written,
            'evidences_written': evidences_written, 'details': details[:20]}


def run_after_analysis(db_path, articles=(), analyzed_keys=(), settings=None,
                       claim_limit=None, claim_store=DEFAULT_CLAIM_STORE,
                       logger=logging):
    """Run every post-analysis production step and return a visible step report."""
    if os.getenv('OR_PIPELINE_ENABLED', '1').strip().lower() in {'0', 'false', 'no', 'off'}:
        return {'status': 'disabled', 'steps': {}, 'blocking_failures': [],
                'warnings': [], 'ok': True}
    report = {'steps': {}, 'blocking_failures': [], 'warnings': []}

    def step(name, fn, blocking=False):
        try:
            result = fn()
            report['steps'][name] = {'ok': True, 'result': result}
            return result
        except Exception as exc:
            report['steps'][name] = {'ok': False,
                                     'error': f'{type(exc).__name__}: {exc}'[:500]}
            if blocking:
                report['blocking_failures'].append(name)
                logger.error('Pipeline step %s failed: %s', name, exc, exc_info=True)
            else:
                report['warnings'].append(name)
                logger.warning('Pipeline step %s failed: %s', name, exc, exc_info=True)
            return None

    step('rss_backfill', lambda: unified_main.backfill_rss(db_path), blocking=True)
    step('claim_pipeline', lambda: run_claim_pipeline(
        db_path, articles, set(analyzed_keys), settings, claim_limit, claim_store, logger))
    step('entities', lambda: unified_main.seed_entities_and_mentions(db_path))
    step('lineage', lambda: unified_main.apply_lineage(db_path))
    step('event_candidates', lambda: unified_main.build_event_candidates(db_path))
    step('verification', lambda: verify.verify(unified.UnifiedStore(db_path, migrate=False)))
    step('opportunities', lambda: opportunity_discovery.discover(db_path))
    step('economic', lambda: economic.refresh())
    step('quality', lambda: quality.record(db_path))
    report['ok'] = not report['blocking_failures']
    report['status'] = ('success' if report['ok'] and not report['warnings']
                        else 'partial' if report['ok'] else 'failed')
    return report
