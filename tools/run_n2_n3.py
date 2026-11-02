"""Run N2 and N3 over the FreshRSS pool or a fixture, with node-run reuse.

    python tools/run_n2_n3.py --limit 50 --n3-limit 15
    python tools/run_n2_n3.py --fixture data/claim-pipeline/n2n3-fixtures.json
    python tools/run_n2_n3.py --nodes n3 --limit 20

N0/N1 come from the append-only store when the same input and ruleset are already there.
N2 and N3 are stored separately; N3's input hash includes the N2 output hash, so a changed
N2 result invalidates N3 automatically. The production database and the model analyzer are
not touched.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_radar import n2_semantic, n3_relationships, semantic_common  # noqa: E402
from opportunity_radar.config import Settings  # noqa: E402
from opportunity_radar.pipeline_store import PipelineStore  # noqa: E402
from tools.run_n1 import fetch_pool, prepare_document  # noqa: E402

DEFAULT_STORE = ROOT / 'data' / 'claim-pipeline' / 'node_runs.sqlite3'


def fixture_articles(path):
    entries = json.loads(Path(path).read_text(encoding='utf-8'))
    articles = []
    for index, entry in enumerate(entries, 1):
        articles.append(SimpleNamespace(
            article_id=str(entry.get('article_id') or f'fixture-{index}'),
            title=str(entry.get('title') or ''),
            url=str(entry.get('source_url') or f'fixture://{index}'),
            summary=str(entry.get('content') or ''),
            published=str(entry.get('published') or ''),
            source_name=str(entry.get('source_id') or 'fixture'),
            feed_id=str(entry.get('source_id') or 'fixture'),
        ))
    return articles


def _node_params(node, max_tokens, response_format):
    return {'node': node, 'temperature': 0.0, 'max_tokens': int(max_tokens),
            'response_format': 'json_schema' if response_format else 'prompt_only'}


def _reuse(store, article_id, node, version, input_hash, params=None, document_id=''):
    if store is None:
        return None
    # Latest usable result for this exact input; failed attempts are skipped so a retry can
    # resume without overwriting history. If only a metrics-only code change moved the hash,
    # the same document_id proves the semantic input is unchanged.
    return (store.find_latest(article_id, node, version, input_hash)
            or store.find_latest_document(article_id, node, version, document_id))


def _record(store, article_id, document, node, version, input_hash, output, params, tools):
    if store is None:
        return
    store.record(article_id=article_id, document_id=document.get('document_id', ''),
                 content_hash=document.get('content_hash', ''), node_name=node,
                 node_version=version, input_hash=input_hash, output=output,
                 params=params, tools=tools)


def _n2_stable_hash(n2):
    return semantic_common.hash_json(
        {key: value for key, value in n2.items()
         if key not in ('seconds', 'batches', 'output_hash')})


def run_n2(article, document, n1, client, settings, args, store):
    model = semantic_common.model_metadata(settings, args.n2_tokens, not args.no_json_schema)
    input_hash = n2_semantic.input_hash(document, n1, model)
    params = _node_params('N2', args.n2_tokens, not args.no_json_schema)
    if not args.no_reuse:
        cached = _reuse(store, article.article_id, 'N2', n2_semantic.NODE_VERSION,
                        input_hash, params, document.get('document_id'))
        if cached is not None:
            cached_ids = {item.get('candidate_id')
                          for item in cached.get('candidate_interpretations') or []}
            current_ids = {item['candidate_id'] for item in n1.get('candidates') or []}
            if current_ids.issubset(cached_ids):
                return cached, True
    runner = semantic_common.JsonRunner(client, n2_semantic.SYSTEM_PROMPT,
                                        n2_semantic.SCHEMA, args.n2_tokens, retries=1,
                                        response_format=not args.no_json_schema)
    started = time.time()
    output = n2_semantic.run(document, n1, runner, model,
                              max_candidates=args.max_candidates)
    output['seconds'] = round(time.time() - started, 2)
    record_params = params
    if output.get('status') not in ('success', 'partial'):
        record_params = dict(params, failed_status=output.get('status'))
    elif args.no_reuse:
        record_params = dict(params, retry=True)
    _record(store, article.article_id, document, 'N2', n2_semantic.NODE_VERSION,
            input_hash, output, record_params, {'model': model})
    return output, False


def run_n3(article, document, n1, n2, client, settings, args, store):
    model = semantic_common.model_metadata(settings, args.n3_tokens, not args.no_json_schema)
    input_hash = n3_relationships.input_hash(document, n1, n2, model)
    params = _node_params('N3', args.n3_tokens, not args.no_json_schema)
    if not args.no_reuse:
        cached = _reuse(store, article.article_id, 'N3', n3_relationships.NODE_VERSION,
                        input_hash, params, document.get('document_id'))
        if (cached is not None
                and cached.get('n2_output_hash') == _n2_stable_hash(n2)):
            return cached, True
    runner = semantic_common.JsonRunner(client, n3_relationships.SYSTEM_PROMPT,
                                        n3_relationships.SCHEMA, args.n3_tokens, retries=1,
                                        response_format=not args.no_json_schema)
    started = time.time()
    output = n3_relationships.run(document, n1, n2, runner, model,
                                  max_candidates=args.max_candidates)
    output['seconds'] = round(time.time() - started, 2)
    record_params = params
    if output.get('status') not in ('success', 'partial', 'blocked'):
        record_params = dict(params, failed_status=output.get('status'))
    elif args.no_reuse:
        record_params = dict(params, retry=True)
    _record(store, article.article_id, document, 'N3', n3_relationships.NODE_VERSION,
            input_hash, output, record_params, {'model': model})
    return output, False


def _batch_metrics(records, node):
    batches = []
    for record in records:
        output = record.get(node)
        if not output or record.get(f'{node}_reused'):
            continue
        for batch in output.get('batches') or []:
            batches.append((record.get('article_id'), batch))
    seconds = sum(batch.get('seconds') or 0 for _article, batch in batches)
    slowest = max(batches, key=lambda item: item[1].get('seconds') or 0,
                  default=(None, {}))
    return {
        'batches': len(batches),
        'prompt_tokens': sum(batch.get('prompt_tokens') or 0 for _article, batch in batches),
        'completion_tokens': sum(batch.get('completion_tokens') or 0
                                 for _article, batch in batches),
        'parse_retries': sum(1 for _article, batch in batches
                             if batch.get('parse_retry')
                             or (batch.get('attempts') or 0) > 1),
        'avg_batch_seconds': round(seconds / len(batches), 2) if batches else 0,
        'slowest_batch': {
            'article_id': slowest[0],
            'seconds': slowest[1].get('seconds'),
            'prompt_tokens': slowest[1].get('prompt_tokens'),
            'completion_tokens': slowest[1].get('completion_tokens'),
            'input_chars': slowest[1].get('input_chars'),
            'output_chars': slowest[1].get('output_chars'),
            'status': slowest[1].get('status'),
        },
    }


def summarise(records, seconds):
    n2_records = [record['n2'] for record in records if record.get('n2')]
    n3_records = [record['n3'] for record in records if record.get('n3')]
    active_n2 = [record['n2'] for record in records
                 if record.get('n2') and not record.get('n2_reused')]
    active_n3 = [record['n3'] for record in records
                 if record.get('n3') and not record.get('n3_reused')]
    n2_stats = [output.get('statistics', {}) for output in n2_records]
    n3_stats = [output.get('statistics', {}) for output in n3_records]
    by_type = {}
    for statistics in n3_stats:
        for key, value in (statistics.get('by_type') or {}).items():
            by_type[key] = by_type.get(key, 0) + value
    n3_relationships_total = sum(statistics.get('relationship_count', 0)
                                 for statistics in n3_stats)
    evidence_located = sum(statistics.get('evidence_located_relationships', 0)
                           for statistics in n3_stats)
    n2_metrics = _batch_metrics(records, 'n2')
    n3_metrics = _batch_metrics(records, 'n3')
    return {
        'seconds': round(seconds, 1),
        'articles': len(records),
        'n2': {
            'articles': len(n2_records),
            'candidates': sum(statistics.get('input_candidate_count', 0)
                              for statistics in n2_stats),
            'claim_value': sum(statistics.get('claim_value_count', 0)
                               for statistics in n2_stats),
            'context_only': sum(statistics.get('context_only_count', 0)
                                for statistics in n2_stats),
            'non_claim': sum(statistics.get('non_claim_count', 0) for statistics in n2_stats),
            'ambiguous': sum(statistics.get('ambiguous_count', 0) for statistics in n2_stats),
            'unresolved': sum(statistics.get('unresolved_count', 0)
                              for statistics in n2_stats),
            'failed_articles': sum(1 for output in n2_records
                                   if output.get('status') not in ('success', 'partial')),
            'reused': sum(1 for record in records if record.get('n2_reused')),
            'model_calls': sum(batch.get('attempts', 0) for output in active_n2
                               for batch in output.get('batches', [])),
            'seconds': round(sum(output.get('seconds', 0) for output in active_n2), 1),
            **n2_metrics,
        },
        'n3': {
            'articles': len(n3_records),
            'claim_values': sum(statistics.get('input_claim_value_count', 0)
                                for statistics in n3_stats),
            'relationships': n3_relationships_total,
            'by_type': by_type,
            'assigned': sum(statistics.get('assigned_count', 0) for statistics in n3_stats),
            'ambiguous': sum(statistics.get('ambiguous_count', 0) for statistics in n3_stats),
            'unresolved': sum(statistics.get('unresolved_count', 0)
                              for statistics in n3_stats),
            'evidence_located': evidence_located,
            'evidence_located_rate': (round(evidence_located / n3_relationships_total, 3)
                                      if n3_relationships_total else None),
            'period_linked': sum(statistics.get('period_linked_relationships', 0)
                                 for statistics in n3_stats),
            'period_attached_by_program': sum(
                statistics.get('period_attached_by_program', 0) for statistics in n3_stats),
            'rate_adjusted_by_program': sum(
                statistics.get('rate_adjusted_by_program', 0) for statistics in n3_stats),
            'comparison_adjusted_by_program': sum(
                statistics.get('comparison_adjusted_by_program', 0) for statistics in n3_stats),
            'coverage_retries': sum(statistics.get('coverage_retries', 0)
                                    for statistics in n3_stats),
            'coverage_recovered': sum(statistics.get('coverage_recovered', 0)
                                      for statistics in n3_stats),
            'failed_articles': sum(1 for output in n3_records
                                   if output.get('status') not in ('success', 'partial',
                                                                   'blocked')),
            'reused': sum(1 for record in records if record.get('n3_reused')),
            'model_calls': sum(batch.get('attempts', 0) for output in active_n3
                               for batch in output.get('batches', [])),
            'seconds': round(sum(output.get('seconds', 0) for output in active_n3), 1),
            **n3_metrics,
        },
        'errors': [{'article_id': record['article_id'], 'error': record['error']}
                   for record in records if record.get('error')],
    }


def render(summary):
    n2, n3 = summary['n2'], summary['n3']
    lines = [
        '# N2 + N3 语义节点运行', '',
        f"- 文章：{summary['articles']} 篇；总耗时：{summary['seconds']} 秒", '',
        '## N2', '',
        '| 指标 | 数值 |', '|---|---:|',
        f"| 文章 | {n2['articles']} |",
        f"| 输入候选 | {n2['candidates']} |",
        f"| claim_value | {n2['claim_value']} |",
        f"| context_only | {n2['context_only']} |",
        f"| non_claim | {n2['non_claim']} |",
        f"| ambiguous | {n2['ambiguous']} |",
        f"| unresolved | {n2['unresolved']} |",
        f"| 失败文章 | {n2['failed_articles']} |",
        f"| 缓存复用 | {n2['reused']} |",
        f"| 模型调用次数 | {n2['model_calls']} |",
        f"| 节点耗时 | {n2['seconds']} 秒 |",
        f"| 批次 / prompt tokens / completion tokens / 重试 | {n2['batches']} / "
        f"{n2['prompt_tokens']} / {n2['completion_tokens']} / {n2['parse_retries']} |",
        f"| 最慢批次 | {json.dumps(n2['slowest_batch'], ensure_ascii=False)} |", '',
        '## N3', '',
        '| 指标 | 数值 |', '|---|---:|',
        f"| 文章 | {n3['articles']} |",
        f"| 输入 claim_value | {n3['claim_values']} |",
        f"| 关系 | {n3['relationships']} |",
        f"| assigned / ambiguous / unresolved | {n3['assigned']} / {n3['ambiguous']} / "
        f"{n3['unresolved']} |",
        f"| 证据定位通过率 | {n3['evidence_located_rate']} |",
        f"| 关联期间 / 程序补期间 | {n3['period_linked']} / "
        f"{n3['period_attached_by_program']} |",
        f"| 程序修正 rate / comparison | {n3['rate_adjusted_by_program']} / "
        f"{n3['comparison_adjusted_by_program']} |",
        f"| 覆盖重试 / 找回 | {n3['coverage_retries']} / {n3['coverage_recovered']} |",
        f"| 失败文章 | {n3['failed_articles']} |",
        f"| 缓存复用 | {n3['reused']} |",
        f"| 模型调用次数 | {n3['model_calls']} |",
        f"| 节点耗时 | {n3['seconds']} 秒 |",
        f"| 批次 / prompt tokens / completion tokens / 重试 | {n3['batches']} / "
        f"{n3['prompt_tokens']} / {n3['completion_tokens']} / {n3['parse_retries']} |",
        f"| 最慢批次 | {json.dumps(n3['slowest_batch'], ensure_ascii=False)} |", '',
        '关系类型：' + json.dumps(n3['by_type'], ensure_ascii=False),
    ]
    if summary['errors']:
        lines += ['', '## 失败', '']
        for error in summary['errors']:
            lines.append(f"- {error['article_id']}: {error['error'][:160]}")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run N2 and/or N3 over articles')
    parser.add_argument('--nodes', default='both', choices=['n2', 'n3', 'both'])
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--n3-limit', type=int, default=0,
                        help='run N3 for at most this many articles with claim values (0=all)')
    parser.add_argument('--article-id', action='append', default=[])
    parser.add_argument('--sources', default='')
    parser.add_argument('--urls-file', default='')
    parser.add_argument('--per-source', type=int, default=0)
    parser.add_argument('--fixture', default='', help='JSON list of article fixtures')
    parser.add_argument('--out', default='')
    parser.add_argument('--store', default=str(DEFAULT_STORE))
    parser.add_argument('--no-store', action='store_true')
    parser.add_argument('--no-reuse', action='store_true')
    parser.add_argument('--no-json-schema', action='store_true')
    parser.add_argument('--max-candidates', type=int, default=4)
    parser.add_argument('--n2-tokens', type=int, default=1600)
    parser.add_argument('--n3-tokens', type=int, default=2400)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.fixture:
        articles = fixture_articles(args.fixture)
    else:
        articles = fetch_pool(settings, args.limit, args.sources, args.urls_file,
                              args.per_source)
    if args.article_id:
        wanted = set(args.article_id)
        articles = [article for article in articles
                    if article.article_id in wanted or article.url in wanted]
    articles = articles[:args.limit]
    if not articles:
        print('no article matched; nothing to run', file=sys.stderr)
        return 2

    store = None if args.no_store else PipelineStore(args.store)
    client = semantic_common.make_client(settings, max_tokens=max(args.n2_tokens,
                                                                  args.n3_tokens),
                                         timeout=args.timeout)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(args.out or ROOT / 'data' / 'claim-pipeline' / f'n2n3-{stamp}')
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records = []
    n3_used = 0
    with (out_dir / 'n2n3.jsonl').open('w', encoding='utf-8') as stream:
        for index, article in enumerate(articles, 1):
            record = {'n': index, 'article_id': article.article_id, 'title': article.title,
                      'source': article.source_name, 'url': article.url}
            article_started = time.time()
            try:
                _text, document, n1, n1_reused = prepare_document(article, store)
                record['n1_reused'] = n1_reused
                record['n1_statistics'] = n1.get('statistics')
                if args.nodes in ('n2', 'both'):
                    n2, n2_reused = run_n2(article, document, n1, client, settings, args, store)
                    record['n2'], record['n2_reused'] = n2, n2_reused
                else:
                    n2 = None
                    if store is not None:
                        model = semantic_common.model_metadata(
                            settings, args.n2_tokens, not args.no_json_schema)
                        n2 = store.find(article.article_id, 'N2', n2_semantic.NODE_VERSION,
                                        n2_semantic.input_hash(document, n1, model),
                                        _node_params('N2', args.n2_tokens,
                                                     not args.no_json_schema))
                    if n2 is None:
                        record['n3_status'] = 'n2_missing'
                        record['error'] = 'N2 result not found in the store'
                    else:
                        record['n2'], record['n2_reused'] = n2, True
                if (args.nodes in ('n3', 'both') and n2 is not None
                        and n2.get('status') in ('success', 'partial')):
                    claim_values = n2.get('statistics', {}).get('claim_value_count', 0)
                    # Even with zero claim values an empty N3 is recorded: N4/N5 must still
                    # dispose the context_only/non_claim candidates. It makes no model call
                    # and does not consume the n3-limit.
                    if claim_values == 0 or not args.n3_limit or n3_used < args.n3_limit:
                        n3, n3_reused = run_n3(article, document, n1, n2, client, settings,
                                               args, store)
                        record['n3'], record['n3_reused'] = n3, n3_reused
                        if claim_values > 0:
                            n3_used += 1
                record['seconds'] = round(time.time() - article_started, 1)
            except Exception as exc:  # one article must not stop the run
                record['error'] = f'{type(exc).__name__}: {exc}'[:300]
                record['seconds'] = round(time.time() - article_started, 1)
            records.append(record)
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            stream.flush()
            statuses = (record.get('n2', {}).get('status', '-'),
                        record.get('n3', {}).get('status', '-'))
            print(f"[{index}/{len(articles)}] {article.title[:50]} · N2={statuses[0]} "
                  f"N3={statuses[1]} · {record['seconds']}s", flush=True)
    seconds = time.time() - started
    summary = summarise(records, seconds)
    (out_dir / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / 'summary.md').write_text(render(summary), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'written to {out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
